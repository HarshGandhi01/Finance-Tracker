from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
import db
from test_expected_income import database


def test_two_rollovers_credit_one_day_only(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'silo.db'}")
    with patch.object(db, "ENGINE", engine):
        db._INITED = False
        db.init_db()
        db.set_setting("food_silo_balance", 1000)
        db.set_setting("food_silo_last_update", "2026-10-19")
        db.add_transaction("2026-10-19", "Lunch", 100)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(db.update_food_silo, [date(2026, 10, 20)] * 2))
        assert float(db.get_setting("food_silo_balance")) == 1250
        assert db.get_setting("food_silo_last_update") == "2026-10-20"
    engine.dispose()
    db._INITED = False


def test_failed_checkpoint_rolls_back_balance(database):
    db.set_setting("food_silo_balance", 1000)
    db.set_setting("food_silo_last_update", "2026-10-19")

    def fail_checkpoint(connection, cursor, statement, parameters, context, executemany):
        if "UPDATE settings SET value=?" in statement and "food_silo_last_update" in statement:
            raise RuntimeError("Simulated write failure")

    event.listen(db.ENGINE, "before_cursor_execute", fail_checkpoint)
    try:
        with pytest.raises(RuntimeError):
            db.update_food_silo(date(2026, 10, 20))
    finally:
        event.remove(db.ENGINE, "before_cursor_execute", fail_checkpoint)
    assert float(db.get_setting("food_silo_balance")) == 1000
    assert db.get_setting("food_silo_last_update") == "2026-10-19"


@pytest.mark.parametrize("checkpoint", ["", "not-a-date"])
def test_missing_or_invalid_checkpoint_preserves_balance(database, checkpoint):
    db.set_setting("food_silo_balance", 1000)
    db.set_setting("food_silo_last_update", checkpoint)
    db.update_food_silo(date(2026, 10, 20))
    assert float(db.get_setting("food_silo_balance")) == 1000
    assert db.get_setting("food_silo_last_update") == "2026-10-20"


def test_backdated_food_reaches_silo_but_not_before_a_reset(database):
    db.set_setting("food_silo_balance", 1000)
    db.set_setting("food_silo_last_update", "2026-10-20")
    db.add_transaction("2026-10-18", "Late SMS lunch", 100)
    assert float(db.get_setting("food_silo_balance")) == 900
    db.delete_transaction(db.get_transactions("2026-10")[0]["id"])
    assert float(db.get_setting("food_silo_balance")) == 1000
    with patch.object(db, "today_ist", return_value=date(2026, 10, 20)):
        db.set_food_silo_zero()
    db.add_transaction("2026-10-18", "Pre-reset dinner", 200)  # before the reset: ignored
    tx = db.get_transactions("2026-10")[0]
    db.update_category(tx["id"], "Other")
    db.delete_transaction(tx["id"])
    assert float(db.get_setting("food_silo_balance")) == 0
