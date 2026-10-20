from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import hashlib

from sqlalchemy import text, inspect
import db
from test_expected_income import database


def payment(raw, ref=None):
    return db.add_transaction("2026-10-20", "Tea stall", 20, upi_ref=ref,
                              sms_hash=hashlib.sha256(raw.encode()).hexdigest())


def test_same_sms_only_once_but_separate_payments_survive(database):
    assert payment("Rs 20 paid to Tea stall at 10:00")
    assert not payment("Rs 20 paid to Tea stall at 10:00")
    assert payment("Rs 20 paid to Tea stall at 10:01")
    assert db.add_transaction("2026-10-20", "Tea stall", 20)
    assert len(db.get_transactions("2026-10")) == 3


def test_sms_hash_expires_but_upi_reference_does_not(database):
    assert payment("first", "123456789012")
    old = (datetime.now(timezone.utc) - timedelta(minutes=11)).strftime("%Y-%m-%d %H:%M:%S")
    with db.conn() as c:
        c.execute(text("UPDATE transactions SET created_at=:t"), {"t": old})
    assert not payment("changed text", "123456789012")
    assert payment("first")


def test_migration_is_additive_and_idempotent(database):
    assert payment("existing")
    db._INITED = False
    db.init_db()
    db._INITED = False
    db.init_db()
    assert "sms_hash" in {c["name"] for c in inspect(db.ENGINE).get_columns("transactions")}
    assert len(db.get_transactions("2026-10")) == 1


def test_concurrent_sms_deliveries_insert_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    with patch.object(db, "ENGINE", engine):
        db._INITED = False
        db.init_db()
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(payment, ["same", "same"])) == [False, True]
    engine.dispose()
    db._INITED = False
