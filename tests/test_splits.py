import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'
import db
from sqlalchemy import create_engine


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.patches = [patch.object(db, 'ENGINE', self.engine),
                        patch.object(db, 'today_ist', return_value=date(2026, 10, 3))]
        for p in self.patches:
            p.start()
        db._INITED = False
        db.init_db()
        db.set_balance(1000)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        db._INITED = False

    def expense(self, **kwargs):
        db.add_transaction('2026-10-03', 'Lunch', 600, **kwargs)
        return db.get_transactions('2026-10')[0]['id']

    def metrics(self):
        return db.compute_metrics('2026-10', date(2026, 10, 3))

    def test_split_and_partial_repayments_preserve_personal_spending(self):
        self.expense(splits=[('Sam', 350)])
        m = self.metrics()
        self.assertEqual((m['balance'], m['burn'], m['today_food_spend']), (400, 250, 250))
        share = db.get_splits()[0]
        db.record_repayment(share['id'], '2026-10-03', 100)
        self.assertEqual(db.get_splits()[0]['repaid'], 100)
        self.assertEqual((self.metrics()['balance'], self.metrics()['burn']), (500, 250))
        db.record_repayment(share['id'], '2026-10-03', 250)
        self.assertEqual((self.metrics()['balance'], self.metrics()['burn']), (750, 250))
        with self.assertRaises(ValueError):
            db.record_repayment(share['id'], '2026-10-03', 1)

    def test_link_imported_credit_and_undo_without_duplicate_cash(self):
        tx_id = self.expense(splits=[('Sam', 350)])
        db.add_transaction('2026-10-03', 'Sam UPI', 350, direction='credit')
        credit_id = db.get_received_credits(date(2026, 10, 3))[0]['id']
        share = db.get_splits()[0]
        db.record_repayment(share['id'], '2026-10-03', credit_id=credit_id)
        self.assertEqual((self.metrics()['balance'], self.metrics()['burn']), (750, 250))
        with self.assertRaises(ValueError):
            db.record_repayment(share['id'], '2026-10-03', credit_id=credit_id)
        with self.assertRaises(ValueError):
            db.delete_transaction(tx_id)
        with self.assertRaises(ValueError):
            db.set_splits(tx_id, [('Sam', 400)])
        with self.assertRaises(ValueError):
            db.update_category(credit_id, 'Pocket Money')
        db.unlink_repayment(credit_id)
        self.assertEqual(db.get_splits()[0]['repaid'], 0)
        self.assertEqual(self.metrics()['balance'], 750)
        db.record_repayment(share['id'], '2026-10-03', credit_id=credit_id)
        db.delete_transaction(credit_id)
        self.assertEqual(db.get_splits()[0]['repaid'], 0)
        self.assertEqual(self.metrics()['balance'], 400)
        db.delete_transaction(tx_id)
        self.assertEqual(db.get_splits(), [])

    def test_invalid_splits_are_atomic_and_existing_expense_can_be_unsplit(self):
        for splits in [[('Sam', 601)], [('Sam', 0)], [('', 20)], [('Sam', 1.001)],
                       [('Sam', 10), ('sam', 10)], [('Sam', float('nan'))]]:
            with self.subTest(splits=splits), self.assertRaises(ValueError):
                self.expense(splits=splits)
        self.assertEqual(db.get_transactions('2026-10'), [])
        tx_id = self.expense()
        db.set_splits(tx_id, [('Sam', 200), ('Alex', 150)])
        self.assertEqual(self.metrics()['burn'], 250)
        db.set_splits(tx_id, [])
        self.assertEqual(self.metrics()['burn'], 600)

    def test_backdated_split_corrects_silo_and_survives_cycle_change(self):
        db.add_transaction('2026-09-30', 'Dinner', 600)
        tx_id = db.get_transactions('2026-09')[0]['id']
        db.set_setting('food_silo_last_update', '2026-09-30')
        db.update_food_silo(date(2026, 10, 1), [])
        self.assertEqual(float(db.get_setting('food_silo_balance')), -250)
        db.set_splits(tx_id, [('Sam', 350)])
        self.assertEqual(float(db.get_setting('food_silo_balance')), 100)
        db.record_repayment(db.get_splits()[0]['id'], '2026-10-03', 350)
        self.assertEqual(self.metrics()['burn'], 0)

    def test_chart_and_fund_use_personal_share(self):
        import pandas as pd
        from dashboard.theme import burn_rate_line
        self.expense(category='Laundry', splits=[('Sam', 350)])
        db.record_repayment(db.get_splits()[0]['id'], '2026-10-03', 350)
        db.set_setting('fund_prior_2026-10_Laundry', 0)
        self.assertEqual(self.metrics()['fund_spent']['Laundry'], 250)
        fig = burn_rate_line(pd.DataFrame(db.get_transactions('2026-10')), 350,
                             date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 3))
        self.assertEqual(list(fig.data[1].y), [0, 0, 250])

    def test_reject_invalid_repayments_and_split_credits(self):
        with self.assertRaises(ValueError):
            self.expense(direction='credit', splits=[('Sam', 100)])
        self.expense(is_peer=True, splits=[('Sam', 350)])
        self.assertEqual(self.metrics()['today_food_spend'], 250)
        share_id = db.get_splits()[0]['id']
        for day, amount in [('2026-10-04', 100), ('2026-10-02', 100), ('2026-10-03', 351),
                            ('2026-10-03', -1), ('2026-10-03', 0)]:
            with self.subTest(day=day, amount=amount), self.assertRaises(ValueError):
                db.record_repayment(share_id, day, amount)
        self.assertEqual(db.get_received_credits(date(2026, 10, 3)), [])


class SplitDashboardTests(unittest.TestCase):
    def test_existing_expense_split_and_repayment_flow(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine('sqlite:///' + directory + '/test.db')
            with patch.object(db, 'ENGINE', engine), patch.dict(os.environ, {'COOKED_DB': directory + '/test.db'}):
                db._INITED = False
                db.init_db()
                today = db.today_ist()
                db.set_balance(1000)
                db.add_transaction(today, 'Lunch', 600)
                tx_id = db.get_transactions(str(today)[:7])[0]['id']
                cached = sys.modules.pop('_finance_tracker_dashboard_db', None)
                if cached:
                    cached.ENGINE.dispose()
                try:
                    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py'), default_timeout=30).run()
                    app.checkbox(key=f'split_{tx_id}').check().run()
                    app.text_input(key=f'names_{tx_id}').set_value('Sam').run()
                    app.radio(key=f'mode_{tx_id}').set_value('Custom shares').run()
                    app.number_input(key=f'share_{tx_id}_0_Sam').set_value(350).run()
                    app.button(key=f'save_split_{tx_id}').click().run()
                    self.assertEqual(list(app.exception), [])
                    share = db.get_splits()[0]
                    app.radio(key=f"repay_method_{share['id']}").set_value('Record new repayment').run()
                    app.number_input(key=f"repay_amount_{share['id']}").set_value(100).run()
                    app.button(key=f"repay_save_{share['id']}").click().run()
                    self.assertEqual(list(app.exception), [])
                    self.assertEqual(db.get_splits()[0]['repaid'], 100)
                    m = db.compute_metrics(str(today)[:7], today)
                    self.assertEqual((m['balance'], m['today_food_spend']), (500, 250))
                    # New manual expense, equal shares with a one-paisa remainder.
                    next(x for x in app.text_input if x.label == 'Merchant').set_value('Dinner')
                    next(x for x in app.number_input if x.label == 'Amount (₹)').set_value(100)
                    app.checkbox(key='split_manual').check().run()
                    app.text_input(key='names_manual').set_value('Alex, Jo').run()
                    next(b for b in app.button if b.label == 'Log transaction').click().run()
                    self.assertEqual(list(app.exception), [])
                    dinner = next(t for t in db.get_transactions(str(today)[:7]) if t['merchant'] == 'Dinner')
                    self.assertAlmostEqual(dinner['personal_amount'], 33.34)
                    self.assertEqual([s['cents'] for s in db.get_splits(dinner['id'])], [3333, 3333])
                    # More rows must not cause one database read per editor/debt.
                    for i in range(20):
                        db.add_transaction(today, f'Meal {i}', 100, splits=[(f'Friend {i}', 50)])
                    dashboard_db = sys.modules['_finance_tracker_dashboard_db']
                    with patch.object(dashboard_db, 'get_splits', wraps=dashboard_db.get_splits) as splits_read, \
                         patch.object(dashboard_db, 'get_received_credits', wraps=dashboard_db.get_received_credits) as credits_read:
                        app.run()
                        self.assertEqual(list(app.exception), [])
                        self.assertEqual(splits_read.call_count, 1)
                        self.assertEqual(credits_read.call_count, 1)
                    transactions = db.get_transactions(str(today)[:7])
                    self.assertEqual(len([b for b in app.button if b.label == 'Delete']), len(transactions))
                    for i in range(8):
                        db.add_transaction(today, f'Extra {i}', 10)
                    app.run()
                    self.assertEqual(len([b for b in app.button if b.label == 'Delete']), 25)
                    next(s for s in app.selectbox if s.label == 'Transaction page').set_value(2).run()
                    self.assertEqual(list(app.exception), [])
                    self.assertEqual(len([b for b in app.button if b.label == 'Delete']), 6)
                finally:
                    cached = sys.modules.pop('_finance_tracker_dashboard_db', None)
                    if cached:
                        cached.ENGINE.dispose()
                    engine.dispose()
                    db._INITED = False


if __name__ == '__main__':
    unittest.main()
