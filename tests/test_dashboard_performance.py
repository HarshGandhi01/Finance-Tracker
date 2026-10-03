import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ['DATABASE_URL'] = ''
os.environ['COOKED_DB'] = ':memory:'
import db
from sqlalchemy import create_engine, event


class DashboardPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.patch = patch.object(db, 'ENGINE', self.engine)
        self.patch.start()
        db._INITED = False
        db.init_db()
        self.today = date(2026, 10, 3)
        db.set_balance(1000)
        db.add_transaction('2026-10-01', 'Pocket money', 12000,
                           direction='credit', category='Pocket Money')
        db.set_setting('food_silo_last_update', str(self.today))
        self.queries = []
        self.begins = []
        event.listen(self.engine, 'before_cursor_execute', self.query)
        event.listen(self.engine, 'begin', self.begin)

    def query(self, connection, cursor, statement, parameters, context, executemany):
        self.queries.append(statement)

    def begin(self, connection):
        self.begins.append(connection)

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()
        db._INITED = False

    def test_refresh_has_bounded_round_trips_and_reads_fresh_data(self):
        first = db.load_dashboard(self.today)
        self.assertEqual(len(self.begins), 2)
        self.assertLessEqual(len(self.queries), 11)
        self.assertEqual(first['metrics']['balance'], 13000)
        db.add_transaction(self.today, 'Imported lunch', 300)
        second = db.load_dashboard(self.today)
        self.assertEqual(second['metrics']['balance'], 12700)
        self.assertEqual(second['metrics']['today_food_spend'], 300)
        self.assertIsNone(db._READ_CONNECTION.get())
        self.assertIsNone(db._READ_CACHE.get())

    def test_catchup_uses_one_spending_query_for_many_days(self):
        db.set_setting('food_silo_last_update', '2026-09-01')
        db.add_transaction('2026-09-02', 'Dinner', 600, splits=[('Sam', 350)])
        db.add_transaction('2026-10-02', 'Lunch', 100)
        self.queries.clear()
        db.update_food_silo(self.today, [])
        spends = [q for q in self.queries if 'SELECT SUM(amount' in q]
        self.assertEqual(len(spends), 1)
        self.assertEqual(float(db.get_setting('food_silo_balance')), 32 * 350 - 350)

    def test_read_context_is_cleaned_up_on_error(self):
        with self.assertRaises(RuntimeError):
            with db.dashboard_reads():
                db.all_settings()
                raise RuntimeError('test')
        self.assertIsNone(db._READ_CONNECTION.get())
        self.assertIsNone(db._READ_CACHE.get())


if __name__ == '__main__':
    unittest.main()
