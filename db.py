"""Database layer for Am I Cooked?
"""
import calendar
import os
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
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
        f"""CREATE TABLE IF NOT EXISTS expense_shares (
            id {pk}, transaction_id INTEGER NOT NULL REFERENCES transactions(id),
            person TEXT NOT NULL, cents INTEGER NOT NULL CHECK(cents > 0))""",
        """CREATE TABLE IF NOT EXISTS split_repayments (
            credit_id INTEGER PRIMARY KEY REFERENCES transactions(id),
            share_id INTEGER NOT NULL REFERENCES expense_shares(id))""",
        "CREATE INDEX IF NOT EXISTS idx_share_transaction ON expense_shares(transaction_id)",
        "CREATE INDEX IF NOT EXISTS idx_repayment_share ON split_repayments(share_id)",
        """CREATE TABLE IF NOT EXISTS sinking_funds (
            name TEXT PRIMARY KEY, monthly_amount DOUBLE PRECISION NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS expected_income (
            id {pk}, date TEXT NOT NULL, label TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL CHECK (amount > 0))""",
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS unparsed_sms (
            id {pk}, raw TEXT NOT NULL, created_at TEXT NOT NULL)""",
    ]


_READ_CONNECTION = ContextVar('dashboard_read_connection', default=None)
_READ_CACHE = ContextVar('dashboard_read_cache', default=None)


def _reuse_read(fn):
    """Reuse reads only inside one dashboard load, never across users or reruns."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        cache = _READ_CACHE.get()
        if cache is None:
            return fn(*args, **kwargs)
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = fn(*args, **kwargs)
        return cache[key]
    return wrapped


@contextmanager
def dashboard_reads():
    with ENGINE.begin() as c:
        connection_token = _READ_CONNECTION.set(c)
        cache_token = _READ_CACHE.set({})
        try:
            yield
        finally:
            _READ_CACHE.reset(cache_token)
            _READ_CONNECTION.reset(connection_token)


@contextmanager
def conn():
    active = _READ_CONNECTION.get()
    if active is not None:
        yield active
        return
    with ENGINE.begin() as c:
        yield c


def _rows(c, sql, **p):
    return [dict(r) for r in c.execute(text(sql), p).mappings().all()]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_ist():
    return datetime.now(IST).date()


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


@_reuse_read
def all_settings() -> dict:
    with conn() as c:
        return {r["key"]: r["value"] for r in _rows(c, "SELECT key, value FROM settings")}


def get_setting(key, default=None):
    if _READ_CACHE.get() is not None:
        return all_settings().get(key, default)
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


@_reuse_read
def get_cycle_dates(month: str, as_of: date | None = None) -> tuple[date, date]:
    """Receipt-date keys identify real cycles; YYYY-MM supports legacy budgets."""
    if len(month) == 10:
        as_of = as_of or today_ist()
        start = date.fromisoformat(month)
        with conn() as c:
            following = _rows(c, "SELECT MIN(date) AS d FROM transactions "
                                 "WHERE category='Pocket Money' AND direction='credit' "
                                 "AND status='settled' AND date > :s AND date <= :today",
                              s=month, today=str(as_of))
        if following[0]["d"]:
            return start, date.fromisoformat(following[0]["d"]) - timedelta(days=1)
        y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        estimated_next = date(y, m, min(start.day, calendar.monthrange(y, m)[1]))
        # Late pocket money does not silently start a new cycle.
        return start, max(estimated_next - timedelta(days=1), as_of)
    start_day = int(get_setting("budget_start_day", 1))
    y, m = map(int, month.split("-"))

    # Handle case where start_day > days in this month
    max_days = calendar.monthrange(y, m)[1]
    actual_start_day = min(start_day, max_days)
    start_date = date(y, m, actual_start_day)

    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1

    max_days_next = calendar.monthrange(next_y, next_m)[1]
    actual_end_day = min(start_day, max_days_next)
    end_date = date(next_y, next_m, actual_end_day) - timedelta(days=1)

    return start_date, end_date


def get_current_cycle_month(today: date) -> str:
    """Use the latest received pocket money, even across calendar boundaries."""
    receipts = get_pocket_money_dates(today)
    if receipts:
        return receipts[0]
    start_day = min(int(get_setting("budget_start_day", 1)),
                    calendar.monthrange(today.year, today.month)[1])
    if today.day < start_day:
        if today.month == 1:
            return f"{today.year - 1}-12"
        return f"{today.year}-{today.month - 1:02d}"
    return f"{today.year}-{today.month:02d}"


@_reuse_read
def get_pocket_money_dates(today: date) -> list[str]:
    with conn() as c:
        rows = _rows(c, "SELECT DISTINCT date FROM transactions WHERE category='Pocket Money' "
                        "AND direction='credit' AND status='settled' AND date <= :d ORDER BY date DESC",
                     d=str(today))
    return [r["date"] for r in rows]


def get_received_credits(today: date) -> list:
    with conn() as c:
        return _rows(c, "SELECT t.*, EXISTS(SELECT 1 FROM split_repayments WHERE credit_id=t.id) AS is_repayment "
                        "FROM transactions t WHERE direction='credit' "
                        "AND status='settled' AND date <= :d ORDER BY date DESC, id DESC", d=str(today))


def add_transaction(date_, merchant, amount, direction="debit", category="Food",
                    is_peer=False, peer_name=None, status="settled", upi_ref=None, splits=None) -> bool:
    upi_ref = (upi_ref or "").strip() or None
    try:
        with conn() as c:
            result = c.execute(text(
                "INSERT INTO transactions "
                "(date, merchant, amount, direction, category, is_peer, peer_name, status, upi_ref, created_at) "
                "VALUES (:d, :m, :a, :dir, :cat, :peer, :pn, :st, :ref, :ts) RETURNING id"),
                {"d": str(date_), "m": merchant.strip(), "a": float(amount), "dir": direction,
                 "cat": category, "peer": int(is_peer), "pn": peer_name, "st": status,
                 "ref": upi_ref, "ts": _now_utc()})
            tx_id = result.scalar_one()
            if splits:
                _save_splits(c, tx_id, splits)

        return True
    except IntegrityError:
        return False


def money_cents(value):
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
            raise ValueError("Use a non-negative amount with at most two decimal places.")
        return int(amount)
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid amount.") from None


def _lock_transaction(c, tx_id):
    # Serialize split edits and settlements on both supported databases.
    c.execute(text("UPDATE transactions SET amount=amount WHERE id=:i"), {"i": tx_id})
    rows = _rows(c, "SELECT * FROM transactions WHERE id=:i", i=tx_id)
    if not rows:
        raise ValueError("Transaction no longer exists.")
    return rows[0]


def _save_splits(c, tx_id, splits):
    tx = _lock_transaction(c, tx_id)
    if splits and (tx['direction'] != 'debit' or tx['status'] != 'settled'):
        raise ValueError("Only paid expenses can be split.")
    cleaned = []
    for person, amount in splits:
        person = person.strip()
        cents = money_cents(amount)
        if not person or cents <= 0:
            raise ValueError("Each person needs a name and a positive share.")
        if person.casefold() in [n.casefold() for n, _ in cleaned]:
            raise ValueError("Use a different name for each person.")
        cleaned.append((person, cents))
    total = sum(v for _, v in cleaned)
    if total > money_cents(tx['amount']):
        raise ValueError("Other people's shares cannot exceed the payment.")
    if _rows(c, "SELECT 1 FROM split_repayments r JOIN expense_shares s ON s.id=r.share_id "
                "WHERE s.transaction_id=:i", i=tx_id):
        raise ValueError("Remove linked repayments before changing this split.")
    old = _rows(c, "SELECT COALESCE(SUM(cents),0) AS n FROM expense_shares WHERE transaction_id=:i", i=tx_id)[0]['n']
    # Backdated edits must correct food savings already rolled into the silo.
    settings = {r['key']: r['value'] for r in _rows(c, "SELECT key,value FROM settings")}
    if tx['category'] == 'Food' and tx['direction'] == 'debit' and tx['date'] < settings.get('food_silo_last_update', ''):
        old_spend = tx['amount'] - old / 100 if old or not tx['is_peer'] else 0
        new_spend = tx['amount'] - total / 100 if total or not tx['is_peer'] else 0
        value = float(settings.get('food_silo_balance', 0)) + old_spend - new_spend
        c.execute(text("INSERT INTO settings(key,value) VALUES ('food_silo_balance',:v) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value"), {'v': str(value)})
    c.execute(text("DELETE FROM expense_shares WHERE transaction_id=:i"), {'i': tx_id})
    for person, cents in cleaned:
        c.execute(text("INSERT INTO expense_shares(transaction_id,person,cents) VALUES (:i,:p,:a)"),
                  {'i': tx_id, 'p': person, 'a': cents})


def set_splits(tx_id, splits):
    with conn() as c:
        _save_splits(c, tx_id, splits)


def get_splits(tx_id=None):
    with conn() as c:
        return _rows(c, "SELECT s.*, t.date, t.merchant, COALESCE((SELECT SUM(t2.amount) "
                        "FROM split_repayments r JOIN transactions t2 ON t2.id=r.credit_id "
                        "WHERE r.share_id=s.id),0) AS repaid FROM expense_shares s "
                        "JOIN transactions t ON t.id=s.transaction_id "
                        + ("WHERE s.transaction_id=:i " if tx_id is not None else "") +
                        "ORDER BY t.date,s.id", i=tx_id)


def record_repayment(share_id, received_on, amount=None, credit_id=None):
    with conn() as c:
        shares = _rows(c, "SELECT * FROM expense_shares WHERE id=:i", i=share_id)
        if not shares:
            raise ValueError("This split no longer exists.")
        share = shares[0]
        expense = _lock_transaction(c, share['transaction_id'])
        if not _rows(c, "SELECT 1 FROM expense_shares WHERE id=:i", i=share_id):
            raise ValueError("This split changed. Refresh and try again.")
        if credit_id is not None:
            credit = _lock_transaction(c, credit_id)
            if credit['direction'] != 'credit' or credit['status'] != 'settled' or credit['category'] == 'Pocket Money':
                raise ValueError("Choose a received credit that is not pocket money.")
            if _rows(c, "SELECT 1 FROM split_repayments WHERE credit_id=:i", i=credit_id):
                raise ValueError("That credit is already linked to a repayment.")
            amount, received_on = credit['amount'], credit['date']
        received_on = date.fromisoformat(str(received_on))
        if received_on > today_ist() or str(received_on) < expense['date']:
            raise ValueError("Repayment date must be between the expense date and today.")
        cents = money_cents(amount)
        paid = _rows(c, "SELECT COALESCE(SUM(t.amount),0) AS n FROM split_repayments r "
                        "JOIN transactions t ON t.id=r.credit_id WHERE r.share_id=:i", i=share_id)[0]['n']
        if cents <= 0 or cents > share['cents'] - round(paid * 100):
            raise ValueError("Repayment must be positive and cannot exceed what is owed.")
        if credit_id is None:
            credit_id = c.execute(text("INSERT INTO transactions "
                "(date,merchant,amount,direction,category,status,created_at) "
                "VALUES (:d,:m,:a,'credit','Other','settled',:ts) RETURNING id"),
                {'d': str(received_on), 'm': f"Repayment from {share['person']}",
                 'a': cents / 100, 'ts': _now_utc()}).scalar_one()
        c.execute(text("INSERT INTO split_repayments(credit_id,share_id) VALUES (:c,:s)"),
                  {'c': credit_id, 's': share_id})


def unlink_repayment(credit_id):
    with conn() as c:
        c.execute(text("DELETE FROM split_repayments WHERE credit_id=:i"), {'i': credit_id})


def get_transactions(month: str, as_of: date | None = None):
    start_date, end_date = get_cycle_dates(month, as_of)
    with conn() as c:
        return _rows(c, "SELECT t.*, amount - COALESCE((SELECT SUM(cents)/100.0 FROM expense_shares "
                        "WHERE transaction_id=t.id),0) AS personal_amount, "
                        "EXISTS(SELECT 1 FROM split_repayments WHERE credit_id=t.id) AS is_repayment "
                        "FROM transactions t WHERE date >= :s AND date <= :e "
                        "ORDER by date DESC, id DESC",
                        s=str(start_date), e=str(end_date))


def delete_transaction(tx_id: int):
    with conn() as c:
        _lock_transaction(c, tx_id)
        if _rows(c, "SELECT 1 FROM split_repayments r JOIN expense_shares s ON s.id=r.share_id "
                    "WHERE s.transaction_id=:i", i=tx_id):
            raise ValueError("Remove linked repayments before deleting this expense.")
        _save_splits(c, tx_id, [])
        c.execute(text("DELETE FROM split_repayments WHERE credit_id=:i"), {"i": tx_id})
        c.execute(text("DELETE FROM transactions WHERE id=:i"), {"i": tx_id})


def set_peer(tx_id: int, is_peer: bool):
    with conn() as c:
        c.execute(text("UPDATE transactions SET is_peer=:p WHERE id=:i"),
                  {"p": int(is_peer), "i": tx_id})


def update_category(tx_id: int, new_cat: str):
    with conn() as c:
        if new_cat == 'Pocket Money' and _rows(c, "SELECT 1 FROM split_repayments WHERE credit_id=:i", i=tx_id):
            raise ValueError("A repayment cannot be pocket money.")
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


def set_food_silo_zero():
    """Reset the food silo balance to zero."""
    set_setting("food_silo_balance", 0.0)
    set_setting("food_silo_last_update", str(today_ist()))


def current_balance(month: str, month_txs: list, settings: dict | None = None,
                    as_of: date | None = None):
    s = settings if settings is not None else all_settings()
    anchor = s.get("anchor_balance")
    if anchor is None:
        opening = s.get(opening_key(month))
        if opening is None and len(month) == 10:
            # Existing calendar-month opening balances still seed the cash ledger.
            keys = sorted(k for k in s if k.startswith("opening_balance_")
                          and len(k.removeprefix("opening_balance_")) == 7
                          and k.removeprefix("opening_balance_") <= month[:7])
            if keys:
                key = keys[-1]
                with conn() as c:
                    net = _rows(c, "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount "
                                   "ELSE -amount END),0) AS n FROM transactions "
                                   "WHERE date >= :s AND date <= :e",
                                s=key.removeprefix("opening_balance_") + "-01",
                                e=str(as_of or today_ist()))[0]["n"]
                return float(s[key]) + float(net)
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


def get_expected(month: str, as_of: date | None = None) -> list:
    _, end_date = get_cycle_dates(month, as_of)
    with conn() as c:
        return _rows(c, "SELECT * FROM expected_income WHERE date<=:e ORDER BY date", e=str(end_date))


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
    Update the food silo balance based on missed days up to yesterday.
    This is called at the start of a new day to move remaining budgets into the silo.
    """
    today_str = str(today)
    last_update_str = get_setting("food_silo_last_update")

    if last_update_str == today_str:
        return

    current_silo = float(get_setting("food_silo_balance", 0.0))

    if not last_update_str:
        set_setting("food_silo_last_update", today_str)
        return

    try:
        last_update_date = datetime.strptime(last_update_str, "%Y-%m-%d").date()
    except ValueError:
        set_setting("food_silo_last_update", today_str)
        return

    if last_update_date < today:
        with conn() as c:
            spend_rows = _rows(c, "SELECT SUM(amount - COALESCE((SELECT SUM(cents)/100.0 "
                                  "FROM expense_shares WHERE transaction_id=t.id),0)) as s FROM transactions t "
                                  "WHERE date>=:s AND date<:e AND category='Food' "
                                  "AND direction='debit' AND (is_peer=0 OR EXISTS "
                                  "(SELECT 1 FROM expense_shares WHERE transaction_id=t.id))",
                                  s=str(last_update_date), e=today_str)
        current_silo += target_daily * (today - last_update_date).days - float(spend_rows[0]["s"] or 0.0)

    set_setting("food_silo_balance", current_silo)
    set_setting("food_silo_last_update", today_str)


def compute_metrics(month: str, today: date, target_daily: float = 350.0) -> dict:
    settings = all_settings()
    txs = get_transactions(month, today)
    funds = get_funds()

    start_date, end_date = get_cycle_dates(month, today)
    days_in_cycle = (end_date - start_date).days + 1

    elapsed_days = (today - start_date).days
    if elapsed_days < 0:
        elapsed_days = 0
    elif elapsed_days > days_in_cycle:
        elapsed_days = days_in_cycle

    elapsed_frac = elapsed_days / max(days_in_cycle, 1)

    # Future-dated entries cannot contribute to spending already incurred.
    txs = [t for t in txs if t["date"] <= str(today)]

    debits = sum(t["amount"] for t in txs if t["direction"] == "debit")
    personal_debits = sum(t["personal_amount"] for t in txs if t["direction"] == "debit")
    peer_debits = sum(t["amount"] for t in txs if t["direction"] == "debit" and t["is_peer"])
    received = sum(t['amount'] for t in txs
                   if t['direction'] == 'credit' and t['status'] == 'settled'
                   and t['category'] != 'Pocket Money' and not t['is_repayment'])
    # Pocket money funds the cycle; other received money offsets cash spent.
    burn = personal_debits - received

    balance = current_balance(month, txs, settings, today)
    has_balance = balance is not None
    balance = balance or 0.0
    expected = get_expected(month, today)
    incoming = sum(e["amount"] for e in expected)

    fund_prior = {}
    for name, alloc in funds.items():
        v = settings.get(f"fund_prior_{month}_{name}")
        fund_prior[name] = float(v) if v is not None else round(alloc * elapsed_frac)

    fund_spent = {
        name: fund_prior[name] + sum(t["personal_amount"] for t in txs
                                     if t["direction"] == "debit" and t["category"] == name
                                     and (not t["is_peer"] or t['personal_amount'] != t['amount']))
        for name in funds
    }
    reserved = sum(max(funds[n] - fund_spent[n], 0) for n in funds)

    rollover = float(settings.get("rollover_balance", 0.0))
    safe_to_spend = balance - reserved

    days_remaining = days_in_cycle - elapsed_days
    if days_remaining <= 0:
        days_remaining = 1

    meals_remaining = days_remaining * 2

    # The current cash balance already includes money carried over from earlier cycles.
    daily_allowance = balance / days_remaining
    fun_money = daily_allowance - target_daily

    today_str = str(today)
    today_food_spend = sum(t["personal_amount"] for t in txs
                           if str(t["date"]).startswith(today_str)
                           and t["category"] == "Food"
                           and t["direction"] == "debit"
                           and (not t["is_peer"] or t['personal_amount'] != t['amount']))

    food_silo = float(settings.get("food_silo_balance", 0.0))

    if today_food_spend <= target_daily:
        food_remaining_today = target_daily - today_food_spend
    else:
        food_remaining_today = (target_daily + food_silo) - today_food_spend
        # ponytail: update silo immediately when overspending today
        new_silo = food_silo - (today_food_spend - target_daily)
        set_setting("food_silo_balance", new_silo)

    food_balance = balance
    safe_per_meal = daily_allowance / 2

    # +1 because if today is the first day, elapsed is 0, but we want to divide by 1 day
    days_elapsed = max(min(elapsed_days + 1, days_in_cycle), 1)
    daily_avg = burn / days_elapsed
    days_until_broke = max(balance, 0) / daily_avg if daily_avg > 0 else None

    return dict(
        has_balance=has_balance, incoming=incoming, expected=expected, balance=balance,
        burn=burn, gross=debits, peer=peer_debits, fund_prior=fund_prior, reserved=reserved,
        received_offsets=received, personal_spending=personal_debits,
        food_balance=food_balance, funds=funds, fund_spent=fund_spent,
        days_remaining=days_remaining, meals_remaining=meals_remaining, days_in_cycle=days_in_cycle,
        cycle_start=start_date, cycle_end=end_date,
        days_elapsed=days_elapsed, days_until_broke=days_until_broke,
        safe_per_meal=safe_per_meal, daily_avg=daily_avg, target_daily=target_daily, txs=txs,
        safe_to_spend=safe_to_spend, daily_allowance=daily_allowance, fun_money=fun_money, rollover=rollover,
        today_food_spend=today_food_spend, food_rollover=food_silo, food_remaining_today=food_remaining_today
    )


def load_dashboard(today, month=None, target_daily=350.0):
    """Load fresh data with one shared read connection and no persistent cache."""
    update_food_silo(today, [], target_daily)
    with dashboard_reads():
        month_now = get_current_cycle_month(today)
        receipt_dates = get_pocket_money_dates(today)
        options = receipt_dates or [month_now]
        month = month if month in options else month_now
        return dict(month=month, month_now=month_now, receipt_dates=receipt_dates,
                    month_options=options, credits=get_received_credits(today),
                    shares=get_splits(), metrics=compute_metrics(month, today, target_daily),
                    unparsed=get_unparsed())
