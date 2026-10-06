import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'
import db
from sqlalchemy import create_engine


class VendorRuleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.patch = patch.object(db, 'ENGINE', self.engine)
        self.patch.start()
        db._INITED = False
        db.init_db()
        db.add_transaction('2026-10-07', 'Campus Canteen', 335, category='Other')
        self.tx_id = db.get_transactions('2026-10')[0]['id']

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()
        db._INITED = False

    def test_ledger_rule_applies_to_next_debit_not_credit(self):
        db.edit_transaction(self.tx_id, 'Campus Canteen', 'Food', True)
        db.add_transaction('2026-10-07', '  CAMPUS   canteen ', 100, category='Other')
        db.add_transaction('2026-10-07', 'Campus Canteen', 100, direction='credit', category='Other')
        txs = db.get_transactions('2026-10')
        self.assertEqual([t['category'] for t in txs], ['Other', 'Food', 'Food'])

    def test_one_off_edit_remove_rule_and_original_bank_name(self):
        db.edit_transaction(self.tx_id, 'Campus meals', 'Food', True)
        self.assertEqual(db.get_merchant_category('Campus Canteen'), 'Food')
        db.edit_transaction(self.tx_id, 'Campus meals', 'Outing')
        self.assertEqual(db.get_merchant_category('Campus meals'), 'Food')
        db.edit_transaction(self.tx_id, 'Campus meals', 'Other', False)
        self.assertIsNone(db.get_merchant_category('Campus meals'))

    def test_manual_override_and_legacy_rule(self):
        db.set_setting('merchant_category_map', '{"Campus Canteen": "Food"}')
        self.assertEqual(db.get_merchant_category('campus   CANTEEN'), 'Food')
        db.add_transaction('2026-10-07', 'Campus Canteen', 100, category='Outing', apply_merchant_rule=False)
        self.assertEqual(db.get_transactions('2026-10')[0]['category'], 'Outing')

    def test_invalid_edit_is_atomic_and_does_not_change_cash(self):
        db.set_balance(1000)
        with self.assertRaises(ValueError):
            db.edit_transaction(self.tx_id, '', 'Food', True)
        self.assertEqual(db.get_transactions('2026-10')[0]['category'], 'Other')
        db.edit_transaction(self.tx_id, 'Campus Canteen', 'Food', True)
        self.assertEqual(db.compute_metrics('2026-10', date(2026, 10, 7))['balance'], 1000)
