import os
import importlib
import tempfile
import unittest
import sys
import types
from pathlib import Path
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'

import db
from sqlalchemy import create_engine


class BudgetCycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.engine_patch = patch.object(db, 'ENGINE', self.engine)
        self.engine_patch.start()
        db._INITED = False
        db.init_db()
        self.clock = patch.object(db, 'today_ist', return_value=date(2026, 10, 2))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        db._INITED = False

    def receipt(self, day='2026-09-25', amount=12000, **kwargs):
        return db.add_transaction(day, 'Pocket money', amount, direction='credit',
                                  category='Pocket Money', **kwargs)

    def test_spending_and_allowance_start_at_receipt(self):
        db.set_balance(7355)
        db.add_transaction('2026-09-24', 'Old spending', 900)
        self.receipt()
        db.add_transaction('2026-09-25', 'Food', 218)
        db.add_transaction('2026-10-01', 'Food', 1782)
        db.add_transaction('2026-10-03', 'Future spend', 500)
        db.set_balance(7355)
        key = db.get_current_cycle_month(date(2026, 10, 2))
        self.assertEqual(key, '2026-09-25')
        m = db.compute_metrics(key, date(2026, 10, 2))
        self.assertEqual(m['burn'], 2000)
        self.assertEqual(m['daily_avg'], 250)  # Eight days, including today.
        self.assertEqual(m['days_remaining'], 23)
        self.assertEqual(m['balance'], 7355)
        self.assertAlmostEqual(m['daily_allowance'], m['balance'] / 23)
        self.assertAlmostEqual(m['fun_money'], m['daily_allowance'] - 350)

    def test_next_receipt_closes_previous_cycle_without_overlap(self):
        self.receipt()
        self.receipt('2026-10-02')
        self.assertEqual(db.get_cycle_dates('2026-09-25'),
                         (date(2026, 9, 25), date(2026, 10, 1)))
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-10-02')
        db.add_transaction('2026-10-02', 'Food', 300)
        m = db.compute_metrics('2026-10-02', date(2026, 10, 2))
        self.assertEqual(m['daily_avg'], 300)
        self.assertEqual(m['days_remaining'], 31)

    def test_requested_formulas_use_cash_without_adding_rollover(self):
        self.receipt('2026-10-01')
        db.add_transaction('2026-10-01', 'Food', 1600)
        db.add_transaction('2026-10-02', 'Peer payment', 182, is_peer=True)
        db.set_balance(7355)
        db.set_setting('rollover_balance', 725)
        m = db.compute_metrics('2026-10-01', date(2026, 10, 2))
        self.assertEqual(m['days_remaining'], 30)
        self.assertEqual(m['days_elapsed'], 2)
        self.assertAlmostEqual(m['daily_allowance'], 7355 / 30)
        self.assertAlmostEqual(m['fun_money'], 7355 / 30 - 350)
        self.assertAlmostEqual(m['safe_per_meal'], 7355 / 60)
        self.assertEqual(m['daily_avg'], 891)
        self.assertAlmostEqual(m['days_until_broke'], 7355 / 891)
        self.assertLess(m['safe_to_spend'], m['balance'])

    def test_burn_rate_includes_zero_spend_days_and_has_no_food_minimum_floor(self):
        self.receipt('2026-09-25')
        db.set_balance(12000)
        m = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        self.assertEqual(m['daily_avg'], 0)
        self.assertIsNone(m['days_until_broke'])
        db.add_transaction('2026-10-02', 'Food', 80)
        m = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        self.assertEqual(m['daily_avg'], 10)
        self.assertEqual(m['days_until_broke'], 1192)

    def test_late_receipt_does_not_reset_cycle(self):
        self.receipt('2026-08-25')
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-08-25')
        m = db.compute_metrics('2026-08-25', date(2026, 10, 2))
        self.assertEqual(m['days_remaining'], 1)
        self.assertEqual(m['cycle_start'], date(2026, 8, 25))

    def test_backfilled_receipt_does_not_move_latest_cycle(self):
        self.receipt()
        self.receipt('2026-08-20')
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-09-25')

    def test_reclassification_and_deletion_recompute_cycle(self):
        db.add_transaction('2026-09-25', 'Transfer', 12000, direction='credit', category='Other')
        tx_id = db.get_received_credits(date(2026, 10, 2))[0]['id']
        db.update_category(tx_id, 'Pocket Money')
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-09-25')
        db.update_category(tx_id, 'Other')
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-10')
        db.update_category(tx_id, 'Pocket Money')
        db.delete_transaction(tx_id)
        self.assertEqual(db.get_current_cycle_month(date(2026, 10, 2)), '2026-10')

    def test_refunds_pending_future_and_debits_do_not_start_cycle(self):
        self.receipt()
        self.receipt('2026-10-01', status='pending')
        self.receipt('2026-10-03')
        db.add_transaction('2026-10-02', 'Refund', 12000, direction='credit', category='Other')
        db.add_transaction('2026-10-02', 'Payment', 500, category='Pocket Money')
        self.assertEqual(db.get_pocket_money_dates(date(2026, 10, 2)), ['2026-09-25'])
        self.assertEqual(db.get_cycle_dates('2026-09-25')[1], date(2026, 10, 24))

    def test_same_day_receipts_share_cycle_and_duplicates_are_ignored(self):
        self.assertTrue(self.receipt(upi_ref='12345'))
        self.assertFalse(self.receipt(upi_ref='12345'))
        self.receipt(amount=1000)
        self.assertEqual(db.get_pocket_money_dates(date(2026, 10, 2)), ['2026-09-25'])

    def test_short_month_and_year_boundary(self):
        for start, as_of, end in [('2026-01-31', date(2026, 2, 1), date(2026, 2, 27)),
                                  ('2028-01-31', date(2028, 2, 1), date(2028, 2, 28)),
                                  ('2026-12-31', date(2027, 1, 1), date(2027, 1, 30))]:
            with self.subTest(start=start):
                self.assertEqual(db.get_cycle_dates(start, as_of)[1], end)

    def test_legacy_opening_balance_survives_switch_to_receipt_cycle(self):
        db.set_setting('opening_balance_2026-09', 500)
        db.add_transaction('2026-09-20', 'Food', 200)
        self.receipt()
        db.add_transaction('2026-10-01', 'Food', 1000)
        m = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        self.assertTrue(m['has_balance'])
        self.assertEqual(m['balance'], 11300)
        self.assertEqual(m['burn'], 1000)

    def test_closed_cycle_average_has_no_extra_day(self):
        self.receipt('2026-09-01')
        db.add_transaction('2026-09-01', 'Food', 3000)
        self.receipt('2026-10-01')
        self.assertEqual(db.compute_metrics('2026-09-01', date(2026, 10, 2))['daily_avg'], 100)

    def test_chart_starts_on_receipt_including_zero_spend_days(self):
        import pandas as pd
        from dashboard.theme import burn_rate_line
        fig = burn_rate_line(pd.DataFrame([{'date': '2026-10-01', 'amount': 100}]),
                             350, date(2026, 9, 25), date(2026, 10, 24), date(2026, 10, 2))
        self.assertEqual(pd.Timestamp(fig.data[0].x[0]).date(), date(2026, 9, 25))
        self.assertEqual(fig.data[0].y[0], 350)
        self.assertEqual(list(fig.data[1].y), [0, 0, 0, 0, 0, 0, 100, 100])


class DashboardTests(unittest.TestCase):
    def test_database_loader_refreshes_changed_source_and_reuses_unchanged_source(self):
        from dashboard.database_loader import load_database
        name = '_finance_tracker_dashboard_db'
        previous = sys.modules.pop(name, None)
        try:
            with patch('pathlib.Path.read_bytes', return_value=b'VERSION = 1'):
                first = load_database()
                self.assertIs(load_database(), first)
            with patch('pathlib.Path.read_bytes', return_value=b'VERSION = 2'):
                second = load_database()
                self.assertIsNot(second, first)
                self.assertEqual(second.VERSION, 2)
        finally:
            sys.modules.pop(name, None)
            if previous is not None:
                sys.modules[name] = previous

    def test_mark_existing_credit_and_reopen_active_cycle(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'COOKED_DB': os.path.join(directory, 'test.db')}):
                importlib.reload(db)
                db.init_db()
                today = db.today_ist()
                db.add_transaction(str(today), 'Pocket payment', 12000,
                                   direction='credit', category='Other')
                db.set_balance(12000)
                script = Path(__file__).resolve().parents[1] / 'dashboard' / 'app.py'
                # A cached older/unrelated db module must not break the dashboard.
                original_db = sys.modules['db']
                sys.modules['db'] = types.ModuleType('db')
                try:
                    app = AppTest.from_file(str(script), default_timeout=30).run()
                finally:
                    sys.modules['db'] = original_db
                self.assertEqual(list(app.exception), [])
                button = next(b for b in app.button if b.label == 'Mark as pocket money')
                button.click().run()
                self.assertEqual(list(app.exception), [])
                cycle = next(s for s in app.selectbox if s.label == 'Budget cycle')
                self.assertEqual(cycle.value, str(today))
                self.assertEqual(db.get_pocket_money_dates(today), [str(today)])
                db.ENGINE.dispose()
                cached = sys.modules.pop('_finance_tracker_dashboard_db', None)
                if cached is not None:
                    cached.ENGINE.dispose()
        importlib.reload(db)


if __name__ == '__main__':
    unittest.main()
