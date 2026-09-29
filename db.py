"""Database layer for Am I Cooked?
"""
import calendar
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

CATEGORIES = ["Food", "Protein", "Laundry", "Sports", "Pocket Money", "Outing", "Other"]

DEFAULT_FUNDS = {
    "Laundry": 200,
}

IST = timezone(timedelta(hours=5, minutes=30))


def _make_engine():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return create_engine(f"sqlite:///{os.environ.get('COOKED_DB', 'cooked.db')}")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True, pool_recycle=240)


ENGINE = _make_engine()
IS_SQLITE = ENGINE.dialect.name == "sqlite"


def _schema():
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if IS_SQLITE else "SERIAL PRIMARY KEY"
    return [
        f"""CREATE TABLE IF NOT EXISTS transactions (
            id          {pk},
            date        TEXT    NOT NULL,
            merchant    TEXT    NOT NULL,
            amount      DOUBLE PRECISION NOT NULL CHECK (amount > 0),
            direction   TEXT    NOT NULL DEFAULT 'debit' CHECK (direction IN ('debit','credit')),
            category    TEXT    NOT NULL DEFAULT 'Food',
            is_peer     INTEGER NOT NULL DEFAULT 0,
            peer_name   TEXT,
            status      TEXT    NOT NULL DEFAULT 'settled' CHECK (status IN ('pending','settled')),
            upi_ref     TEXT    UNIQUE,
            created_at  TEXT    NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date)",
        """CREATE TABLE IF NOT EXISTS sinking_funds (
            name TEXT PRIMARY KEY, monthly_amount DOUBLE PRECISION NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS expected_income (
            id {pk}, date TEXT NOT NULL, label TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL CHECK (amount > 0))""",
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS unparsed_sms (
            id {pk}, raw TEXT NOT NULL, created_at TEXT NOT NULL)""",
    ]


@contextmanager
def conn():
    with ENGINE.begin() as c:
        yield c


def _rows(c, sql, **p):
    return [dict(r) for r in c.execute(text(sql), p).mappings().all()]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_ist():
    now = datetime.now(IST)
    if now.day <= 2:
        last_day_prev = now.replace(day=1) - timedelta(days=1)
        return last_day_prev.date()
    return now.date()


_INITED = False


def init_db():
    global _INITED
    if _INITED:
        return
    with conn() as c:
        for stmt in _schema():
            c.execute(text(stmt))
        for name, amt in DEFAULT_FUNDS.items():
            c.execute(text("INSERT INTO sinking_funds(name, monthly_amount) VALUES (:n, :a) "
                           "ON CONFLICT (name) DO NOTHING"), {"n": name, "a": amt})
    _INITED = True


def all_settings() -> dict:
    with conn() as c:
        return {r["key"]: r["value"] for r in _rows(c, "SELECT key, value FROM settings")}


def get_setting(key, default=None):
    with conn() as c:
        rows = _rows(c, "SELECT value FROM settings WHERE key=:k", k=key)
    return rows[0]["value"] if rows else default


def set_setting(key, value):
    with conn() as c:
        c.execute(text("INSERT INTO settings(key, value) VALUES (:k, :v) "
                       "ON CONFLICT (key) DO UPDATE SET value=excluded.value"),
                  {"k": key, "v": str(value)})


def opening_key(month: str) -> str:
    return f"opening_balance_{month}"


def add_transaction(date_, merchant, amount, direction="debit", category="Food",
                    is_peer=False, peer_name=None, status="settled", upi_ref=None) -> bool:
    upi_ref = (upi_ref or "").strip() or None
    try:
        with conn() as c:
            c.execute(text(
                "INSERT INTO transactions "
                "(date, merchant, amount, direction, category, is_peer, peer_name, status, upi_ref, created_at) "
                "VALUES (:d, :m, :a, :dir, :cat, :peer, :pn, :st, :ref, :ts)"),
                {"d": str(date_), "m": merchant.strip(), "a": float(amount), "dir": direction,
                 "cat": category, "peer": int(is_peer), "pn": peer_name, "st": status,
                 "ref": upi_ref, "ts": _now_utc()})
        return True
    except IntegrityError:
        return False


def get_transactions(month: str):
    with conn() as c:
        return _rows(c, "SELECT * FROM transactions WHERE substr(date,1,7)=:m "
                        "ORDER by date DESC, id DESC", m=month)


def delete_transaction(tx_id: int):
    with conn() as c:
        c.execute(text("DELETE FROM transactions WHERE id=:i"), {"i": tx_id})


def set_peer(tx_id: int, is_peer: bool):
    with conn() as c:
        c.execute(text("UPDATE transactions SET is_peer=:p WHERE id=:i"),
                  {"p": int(is_peer), "i": tx_id})


def update_category(tx_id: int, new_cat: str):
    with conn() as c:
        c.execute(text("UPDATE transactions SET category=:cat WHERE id=:i"),
                  {"cat": new_cat, "i": tx_id})


def recent_duplicate(date_, merchant, amount, direction) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
    with conn() as c:
        rows = _rows(c, "SELECT 1 AS x FROM transactions WHERE date=:d AND merchant=:m AND amount=:a "
                        "AND direction=:dir AND created_at >= :cut LIMIT 1",
                     d=str(date_), m=merchant, a=float(amount), dir=direction, cut=cutoff)
    return bool(rows)


def get_funds() -> dict:
    with conn() as c:
        return {r["name"]: r["monthly_amount"] for r in _rows(c, "SELECT name, monthly_amount FROM sinking_funds")}


def set_balance(amount: float):
    with conn() as c:
        max_id = _rows(c, "SELECT COALESCE(MAX(id),0) AS m FROM transactions")[0]["m"]
    set_setting("anchor_balance", amount)
    set_setting("anchor_max_id", max_id)


def current_balance(month: str, month_txs: list, settings: dict | None = None):
    s = settings if settings is not None else all_settings()
    anchor = s.get("anchor_balance")
    if anchor is None:
        opening = s.get(opening_key(month))
        if opening is None:
            return None
        return float(opening) + sum(t["amount"] if t["direction"] == "credit" else -t["amount"]
                                    for t in month_txs)
    with conn() as c:
        net = _rows(c, "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END),0) AS n "
                       "FROM transactions WHERE id > :i", i=int(s.get("anchor_max_id", 0)))[0]["n"]
    return float(anchor) + float(net)


def add_expected(date_, label, amount):
    with conn() as c:
        c.execute(text("INSERT INTO expected_income(date, label, amount) VALUES (:d, :l, :a)"),
                  {"d": str(date_), "l": label.strip(), "a": float(amount)})


def get_expected(month: str) -> list:
    y, m_ = map(int, month.split("-"))
    end = f"{month}-{calendar.monthrange(y, m_)[1]:02d}"
    with conn() as c:
        return _rows(c, "SELECT * FROM expected_income WHERE date<=:e ORDER BY date", e=end)


def delete_expected(exp_id: int):
    with conn() as c:
        c.execute(text("DELETE FROM expected_income WHERE id=:i"), {"i": exp_id})


def receive_expected(exp_id: int, received_on):
    with conn() as c:
        rows = _rows(c, "SELECT * FROM expected_income WHERE id=:i", i=exp_id)
    if not rows:
        return
    add_transaction(received_on, rows[0]["label"], rows[0]["amount"], direction="credit", category="Other")
    delete_expected(exp_id)


def match_expected(amount: float, month: str) -> bool:
    for e in get_expected(month):
        if abs(e["amount"] - amount) < 0.01:
            delete_expected(e["id"])
            return True
    return False


def add_unparsed(raw: str):
    with conn() as c:
        c.execute(text("INSERT INTO unparsed_sms(raw, created_at) VALUES (:r, :t)"),
                      {"r": raw, "t": _now_utc()})


def get_unparsed() -> list:
    with conn() as c:
        return _rows(c, "SELECT * FROM unparsed_sms ORDER BY id DESC")


def delete_unparsed(uid: int):
    with conn() as c:
        c.execute(text("DELETE FROM unparsed_sms WHERE id=:i"), {"i": uid})


def update_food_silo(today: date, transactions: list, target_daily: float = 350.0):
    """
    Update the food silo balance based on today's spending.
    If spend < target, the difference is added to the silo.
    If spend > target, the difference is subtracted from the silo.
    """
    today_str = str(today)
    today_food_spend = sum(t["amount"] for t in transactions
                           if str(t["date"]).startswith(today_str)
                           and t["category"] == "Food"
                           and t["direction"] == "debit"
                           and not t["is_peer"])

    diff = target_daily - today_food_spend
    current_silo = float(get_setting("food_silo_balance", 0.0))
    new_silo = current_silo + diff

    # We only update once per day to avoid repeated additive updates on every load.
    last_update = get_setting("food_silo_last_update")
    if last_update == today_str:
        return

    set_setting("food_silo_balance", new_silo)
    set_setting("food_silo_last_update", today_str)


def compute_metrics(month: str, today: date, target_daily: float = 350.0) -> dict:
    settings = all_settings()
    txs = get_transactions(month)
    funds = get_funds()

    debits = sum(t["amount"] for t in txs if t["direction"] == "debit")
    peer_debits = sum(t["amount"] for t in txs if t["direction"] == "debit" and t["is_peer"])
    burn = debits - peer_debits

    balance = current_balance(month, txs, settings)
    has_balance = balance is not None
    balance = balance or 0.0
    expected = get_expected(month)
    incoming = sum(e["amount"] for e in expected)

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    elapsed_frac = (today.day - 1) / days_in_month
    fund_prior = {}
    for name, alloc in funds.items():
        v = settings.get(f"fund_prior_{month}_{name}")
        fund_prior[name] = float(v) if v is not None else round(alloc * elapsed_frac)

    fund_spent = {
        name: fund_prior[name] + sum(t["amount"] for t in txs
                                     if t["direction"] == "debit" and t["category"] == name and not t["is_peer"])
        for name in funds
    }
    reserved = sum(max(funds[n] - fund_spent[n], 0) for n in funds)

    rollover = float(settings.get("rollover_balance", 0.0))
    # Fix: Safe to spend based on actual balance only
    safe_to_spend = balance - reserved

    days_remaining = days_in_month - today.day + 1
    meals_remaining = days_remaining * 2

    # Use only actual balance for allowance - no expected income
    total_liquid = balance
    daily_allowance = (total_liquid + rollover) / max(days_remaining, 1)
    fun_money = daily_allowance - target_daily

    # --- Food-Silo Logic ---
    today_str = str(today)
    today_food_spend = sum(t["amount"] for t in txs
                           if str(t["date"]).startswith(today_str)
                           and t["category"] == "Food"
                           and t["direction"] == "debit"
                           and not t["is_peer"])

    food_silo = float(settings.get("food_silo_balance", 0.0))
    food_remaining_today = (target_daily + food_silo) - today_food_spend

    food_balance = safe_to_spend
    safe_per_meal = max(food_balance, 0) / max(meals_remaining, 1)
    daily_avg = burn / max(today.day, 1)

    return dict(
        has_balance=has_balance, incoming=incoming, expected=expected, balance=balance,
        burn=burn, gross=debits, peer=peer_debits, fund_prior=fund_prior, reserved=reserved,
        food_balance=food_balance, funds=funds, fund_spent=fund_spent,
        days_remaining=days_remaining, meals_remaining=meals_remaining,
        safe_per_meal=safe_per_meal, daily_avg=daily_avg, target_daily=target_daily, txs=txs,
        safe_to_spend=safe_to_spend, daily_allowance=daily_allowance, fun_money=fun_money, rollover=rollover,
        today_food_spend=today_food_spend, food_rollover=food_silo, food_remaining_today=food_remaining_today
    )
