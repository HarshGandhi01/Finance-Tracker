import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'

import db
from sqlalchemy import create_engine


class ForgiveOwedTests(unittest.TestCase):
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

    def tearDown(self):
        self.clock.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        db._INITED = False

    def owed(self):
        return sum(s['cents'] / 100 - s['repaid'] for s in db.get_splits() if not s['forgiven'])

    def test_forgive_clears_owed_but_leaves_spending(self):
        db.add_transaction('2026-10-01', 'Dinner', 1000, category='Other', splits=[('Sam', 400)])
        personal_before = db.get_transactions('2026-09-25')[0]['personal_amount']
        self.assertEqual(personal_before, 600)   # you paid 1000, Sam owes 400
        self.assertEqual(self.owed(), 400)

        db.forgive_all_owed()

        self.assertEqual(self.owed(), 0)                                   # tracker cleared
        self.assertTrue(all(s['forgiven'] for s in db.get_splits()))
        # Spending (your personal share) and the transaction amount are untouched.
        self.assertEqual(db.get_transactions('2026-09-25')[0]['personal_amount'], 600)


if __name__ == '__main__':
    unittest.main()
