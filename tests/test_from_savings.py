import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'

import db
from sqlalchemy import create_engine


class FromSavingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.engine_patch = patch.object(db, 'ENGINE', self.engine)
        self.engine_patch.start()
        db._INITED = False
        db.init_db()
        self.clock = patch.object(db, 'today_ist', return_value=date(2026, 10, 2))
        self.clock.start()
        db.add_transaction('2026-09-25', 'Pocket money', 12000,
                           direction='credit', category='Pocket Money')
        db.set_setting('food_silo_start', '2026-09-25')

    def tearDown(self):
        self.clock.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        db._INITED = False

    def test_tagged_purchase_draws_savings_and_protects_allowance(self):
        db.set_setting('food_silo_balance', 2000)
        db.set_balance(5000)
        base = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        db.add_transaction('2026-10-01', 'Headphones', 1500, category='Other', from_savings=True)
        m = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        self.assertEqual(m['food_rollover'], 2000)                # eating pot unchanged by the buy
        self.assertEqual(m['balance'], 3500)                      # cash really left the account
        self.assertEqual(m['safe_to_spend'], base['safe_to_spend'])  # allowance still protected
        self.assertEqual(m['burn'], base['burn'])                 # kept out of spending

    def test_overdrawing_savings_stops_protection(self):
        db.set_setting('food_silo_balance', 1000)
        db.set_balance(5000)
        db.add_transaction('2026-10-01', 'Laptop', 3000, category='Other', from_savings=True)
        m = db.compute_metrics('2026-09-25', date(2026, 10, 2))
        self.assertEqual(m['food_rollover'], 1000)    # eating pot shown as-is, never dragged negative
        self.assertEqual(m['balance'], 2000)
        # Only the 1000 you banked is protected; the other 2000 really hits spendable cash.
        self.assertEqual(m['safe_to_spend'], 3000)

    def test_tagging_a_food_purchase_returns_it_to_the_silo(self):
        db.set_setting('food_silo_balance', 1000)
        db.set_setting('food_silo_last_update', '2026-10-03')  # 10-01 is inside the rolled window
        db.add_transaction('2026-10-01', 'Big grocery', 800, category='Food')
        self.assertEqual(float(db.get_setting('food_silo_balance')), 200)  # 1000 − 800 food spend
        tx_id = db.all_transactions()[-1]['id']
        db.edit_transaction(tx_id, 'Big grocery', 'Food', from_savings=True)
        self.assertEqual(float(db.get_setting('food_silo_balance')), 1000)  # food spend returned

    def test_food_tagged_from_savings_is_not_counted_by_the_rollover(self):
        # Regression: a Food purchase tagged "from savings" must not be subtracted by the daily
        # rollover (the overlay already draws it) — otherwise it hits the silo twice.
        db.set_setting('food_silo_balance', 1000)
        db.set_setting('food_silo_last_update', '2026-09-30')
        db.add_transaction('2026-10-01', 'Big grocery', 800, category='Food', from_savings=True)
        db.update_food_silo(date(2026, 10, 2))
        self.assertEqual(float(db.get_setting('food_silo_balance')), 1700)  # 2×350 added, 800 not taken

    def test_one_time_correction_recomputes_silo_from_scratch(self):
        db.set_setting('food_silo_start', '2026-09-25')
        db.set_setting('food_silo_last_update', '2026-10-02')  # 7 days rolled
        db.add_transaction('2026-09-28', 'Groceries', 500, category='Food')
        db.add_transaction('2026-09-29', 'Costco', 1200, category='Food', from_savings=True)
        db.set_setting('food_silo_balance', 750)  # a wrong value left by the old double-count
        with db.conn() as c:
            c.execute(db.text("DELETE FROM settings WHERE key='from_savings_silo_corrected'"))
            db._fix_from_savings_silo(c)
        # Rebuilt correctly: 7×350 − 500 normal food; the tagged ₹1200 is excluded.
        self.assertEqual(float(db.get_setting('food_silo_balance')), 1950)


if __name__ == '__main__':
    unittest.main()
