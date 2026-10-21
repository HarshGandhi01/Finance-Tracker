import json
from datetime import date

import pytest
from sqlalchemy import text
import db
from test_expected_income import database


def setup_laundry():
    with db.conn() as c:
        c.execute(text("INSERT INTO sinking_funds(name,monthly_amount) VALUES ('Laundry',200) ON CONFLICT(name) DO NOTHING"))
    db.add_transaction("2026-10-01", "Cleaners", 60, category="Laundry")
    db.set_merchant_category("Cleaners", "Laundry")
    db.set_setting("fund_prior_2026-10_Laundry", 40)
    db.set_setting("fund_prior_2026-10-01_Laundry", 15)


def test_rename_updates_all_records_and_survives_restart(database):
    setup_laundry()
    db.rename_category("Laundry", "Clothes")
    assert db.get_transactions("2026-10")[0]["category"] == "Clothes"
    assert db.get_merchant_category("Cleaners") == "Clothes"
    assert db.get_funds() == {"Clothes": 200}
    assert float(db.get_setting("fund_prior_2026-10_Clothes")) == 40
    assert float(db.get_setting("fund_prior_2026-10-01_Clothes")) == 15
    assert db.get_setting("fund_prior_2026-10_Laundry") is None
    db._INITED = False
    db.init_db()
    assert "Laundry" not in db.get_categories()
    assert db.get_funds() == {"Clothes": 200}


@pytest.mark.parametrize("delete_fund", [True, False])
def test_delete_reassigns_rules_transactions_and_fund(database, delete_fund):
    setup_laundry()
    db.delete_category("Laundry", "Other", delete_fund)
    assert db.get_transactions("2026-10")[0]["category"] == "Other"
    assert db.get_merchant_category("Cleaners") == "Other"
    assert db.get_funds() == ({} if delete_fund else {"Other": 200})
    assert db.get_setting("fund_prior_2026-10_Laundry") is None
    assert db.get_setting("fund_prior_2026-10_Other") == (None if delete_fund else "40.0")


@pytest.mark.parametrize("name", ["Food", "Pocket Money", "Other"])
def test_system_categories_are_protected(database, name):
    with pytest.raises(ValueError):
        db.rename_category(name.lower(), "Changed")
    with pytest.raises(ValueError):
        db.delete_category(name.lower())


def test_casefold_uniqueness_validation_and_order(database):
    db.add_category("  Books  ")
    with pytest.raises(ValueError):
        db.add_category("books")
    with pytest.raises(ValueError):
        db.rename_category("Laundry", "BOOKS")
    for invalid in (" ", "x" * 25):
        with pytest.raises(ValueError):
            db.add_category(invalid)
    db.move_category("Books", -1)
    assert db.get_categories()[-2:] == ["Books", "Other"]
    db.rename_category("Books", "books")
    assert "books" in db.get_categories()


def test_migration_seeds_legacy_categories_without_changing_transactions(database):
    with db.conn() as c:
        c.execute(text("DELETE FROM settings WHERE key='categories_seeded'"))
        c.execute(text("INSERT INTO transactions(date,merchant,amount,category,created_at) "
                       "VALUES ('2026-10-01','Old vendor',10,'Transport','2026-10-01')"))
    db._INITED = False
    db.init_db()
    assert all(n in db.get_categories() for n in db.DEFAULT_CATEGORIES + ["Transport"])
    assert db.get_transactions("2026-10")[0]["category"] == "Transport"


def test_deleted_parser_category_falls_back_to_other(database):
    db.delete_category("Sports")
    db.add_transaction("2026-10-01", "Gym", 100, category="Sports")
    assert db.get_transactions("2026-10")[0]["category"] == "Other"


def test_delete_to_food_corrects_rolled_up_silo(database):
    setup_laundry()
    db.set_setting("food_silo_last_update", "2026-10-02")
    db.set_setting("food_silo_balance", 1000)
    db.delete_category("Laundry", "Food", True)
    assert float(db.get_setting("food_silo_balance")) == 940


def test_delete_merges_funds_and_priors(database):
    setup_laundry()
    with db.conn() as c:
        c.execute(text("INSERT INTO sinking_funds VALUES ('Other',50)"))
    db.set_setting("fund_prior_2026-10_Other", 10)
    db.delete_category("Laundry")
    assert db.get_funds() == {"Other": 250}
    assert float(db.get_setting("fund_prior_2026-10_Other")) == 50


def test_failed_rename_rolls_back_every_change(database):
    setup_laundry()
    db.set_setting("fund_prior_2026-10_Laundry", "invalid-number")
    with pytest.raises(ValueError):
        db.rename_category("Laundry", "Clothes")
    assert db.get_transactions("2026-10")[0]["category"] == "Laundry"
    assert db.get_merchant_category("Cleaners") == "Laundry"
    assert db.get_funds() == {"Laundry": 200}
    assert "Clothes" not in db.get_categories()


def test_category_management_ui(tmp_path):
    import os
    import sys
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path / 'ui.db'}")
    with patch.object(db, "ENGINE", engine), patch.dict(os.environ, {
        "DATABASE_URL": "", "COOKED_DB": str(tmp_path / "ui.db")
    }):
        db._INITED = False
        db.init_db()
        cached = sys.modules.pop("_finance_tracker_dashboard_db", None)
        if cached:
            cached.ENGINE.dispose()
        try:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/app.py"),
                                   default_timeout=30).run()
            app.switch_page("settings.py").run()
            next(t for t in app.text_input if t.label == "New category").set_value("Books")
            next(b for b in app.button if b.label == "Add category").click().run()
            assert not app.exception
            assert "Books" in db.get_categories()
            assert any(e.label == "Food · Locked" for e in app.expander)
            app.button(key="up_Books").click().run()
            assert db.get_categories()[-2] == "Books"
        finally:
            cached = sys.modules.pop("_finance_tracker_dashboard_db", None)
            if cached:
                cached.ENGINE.dispose()
    engine.dispose()
    db._INITED = False
