import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'

import db
from sqlalchemy import create_engine


class ReverseTransactionTests(unittest.TestCase):
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

    def test_reverse_debit_adds_offsetting_credit_and_nets_balance(self):
        db.add_transaction('2026-09-25', 'Pocket money', 12000, direction='credit',
                           category='Pocket Money')
        db.set_balance(10000)
        tx_id = db.all_transactions()[-1]['id']  # most recent insert id
        db.add_transaction('2026-10-02', 'Swiggy', 400, category='Food')
        failed = db.all_transactions()[-1]['id']
        self.assertEqual(db.compute_metrics('2026-09-25', date(2026, 10, 2))['balance'], 9600)

        db.reverse_transaction(failed)
        credits = [t for t in db.all_transactions()
                   if t['merchant'] == 'Swiggy' and t['direction'] == 'credit']
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0]['amount'], 400)
        # Refund restores the balance the phantom debit had removed.
        self.assertEqual(db.compute_metrics('2026-09-25', date(2026, 10, 2))['balance'], 10000)


if __name__ == '__main__':
    unittest.main()
