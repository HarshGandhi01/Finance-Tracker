"""Am I Cooked? — dashboard (redesign: presentation only, db calls unchanged)."""
import hashlib
import importlib
import os
import sys
from datetime import date

# Ensure repo root is on the path so 'import db' works on Vercel/Streamlit
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

import pandas as pd
import streamlit as st

import db
from theme import apply_theme, inr, spending_donut

TARGET_DAILY = 350.0

st.set_page_config(
    page_title="Am I cooked?",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_theme()
db.init_db()

# ---------------------------------------------------------------- top bar
today = db.today_ist()

def _shift_month(d: date, delta: int) -> str:
    idx = d.year * 12 + (d.month - 1) + delta
    return f"{idx // 12}-{idx % 12 + 1:02d}"

month_now = _shift_month(today, 0)
try:
    db.update_food_silo(today, db.get_transactions(month_now), TARGET_DAILY)
except AttributeError:
    # This handles cases where the deployed version of db.py
    # might be out of sync with the app.py during a push.
    pass

month_options = [_shift_month(today, -1), _shift_month(today, 0), _shift_month(today, 1)]

col_nav1, col_nav2 = st.columns([3, 1], vertical_alignment="center")
with col_nav1:
    st.markdown('<div class="nav-title">Am I cooked?</div>', unsafe_allow_html=True)
with col_nav2:
    month = st.selectbox("Budget month", options=month_options, index=1, label_visibility="collapsed")

# ---------------------------------------------------------------- data
m = db.compute_metrics(month, today, TARGET_DAILY)

daily_avg = m.get("daily_avg", 0.0)
balance = m.get("balance", 0.0)
divisor = max(daily_avg, TARGET_DAILY)
days_left = balance / divisor if divisor > 0 else 999

try:
    food_remaining = float(m.get("food_remaining_today", 0.0))
except (TypeError, ValueError):
    food_remaining = 0.0
try:
    food_spent = float(m.get("today_food_spend", 0.0))
except (TypeError, ValueError):
    food_spent = 0.0
food_silo = m.get("food_rollover", 0.0)

# ---------------------------------------------------------------- hero
if food_remaining > 0:
    status_text = f"You have {inr(food_remaining)} left for food today."
elif food_remaining == 0:
    status_text = "Food budget is exactly zero. Eat the mess food."
else:
    status_text = f"Overspent on food by {inr(abs(food_remaining))}. You're officially cooked."

clock_tone = "hot" if days_left <= 7 else ("warn" if days_left <= 14 else "")
food_tone = "hot" if food_remaining < 0 else ""
bar_pct = min(max(food_spent / TARGET_DAILY, 0), 1) * 100 if TARGET_DAILY else 0

hero_left, hero_right = st.columns([1, 1.25], gap="large", vertical_alignment="center")
with hero_left:
    st.markdown(
        f"""
        <div class="clock">
          <div class="clock-label">Days until broke</div>
          <div class="clock-value {clock_tone}">{int(days_left)}</div>
          <div class="clock-sub">{inr(balance)} left, spending {inr(divisor)} a day</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hero_right:
    st.markdown(
        f"""
        <div class="food-card">
          <div class="food-label">Left for food today</div>
          <div class="food-value {food_tone}">{inr(food_remaining)}</div>
          <div class="food-text">{status_text}</div>
          <div class="bar"><span class="{food_tone}" style="width:{bar_pct:.0f}%"></span></div>
          <div class="bar-cap"><span>{inr(food_spent)} spent</span><span>{inr(TARGET_DAILY)} target</span></div>
          <div class="silo"><span>Food silo, saved for overspending</span><b>{inr(food_silo)}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------- stat tiles
tiles = [
    ("Daily allowance", inr(m["daily_allowance"]), True),
    ("Food minimum", inr(TARGET_DAILY), False),
    ("Extra per day", inr(m["fun_money"]), False),
    ("Safe per meal", inr(m["safe_per_meal"]), False),
    ("Current burn rate", inr(m["daily_avg"]), False),
    ("Safe to spend", inr(m["safe_to_spend"]), False),
]
tiles_html = "".join(
    f'<div class="tile{" lead" if lead else ""}"><div class="tile-label">{label}</div>'
    f'<div class="tile-value">{value}</div></div>'
    for label, value, lead in tiles
)
st.markdown(f'<div class="section-title">This month</div><div class="tiles">{tiles_html}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- breakdown + ledger
txs = m["txs"]
col_chart, col_ledger = st.columns([1, 1.5], gap="large")

with col_chart:
    st.markdown('<div class="section-title">Where it went</div>', unsafe_allow_html=True)
    cat_sums = pd.Series(dtype=float)
    if txs:
        df_tx = pd.DataFrame(txs)
        debits = df_tx[df_tx["direction"] == "debit"]
        if not debits.empty:
            cat_sums = debits.groupby("category")["amount"].sum().sort_values(ascending=False)
    if cat_sums.empty:
        st.info("No spending data to analyze this month.")
    else:
        st.plotly_chart(spending_donut(cat_sums), width="stretch", config={"displayModeBar": False})

with col_ledger:
    st.markdown('<div class="section-title">Transactions</div>', unsafe_allow_html=True)
    if not txs:
        st.info("No entries this month.")
    else:
        sorted_txs = sorted(txs, key=lambda x: x["date"], reverse=True)
        ledger = pd.DataFrame(
            {
                "Date": pd.to_datetime([t["date"] for t in sorted_txs], errors="coerce"),
                "Merchant": [str(t["merchant"]) for t in sorted_txs],
                "Category": [t["category"] for t in sorted_txs],
                "Amount": [
                    f'{"+" if t["direction"] == "credit" else "-"}{inr(t["amount"], 2)}' for t in sorted_txs
                ],
            },
            index=[t["id"] for t in sorted_txs],
        )
        cat_options = list(db.CATEGORIES) + sorted({c for c in ledger["Category"] if c not in db.CATEGORIES})

        # Key changes whenever the data changes, so stale edits never get re-applied to shifted rows.
        sig = hashlib.md5(repr(list(zip(ledger.index, ledger["Category"]))).encode()).hexdigest()[:10]
        edited = st.data_editor(
            ledger,
            hide_index=True,
            disabled=["Date", "Merchant", "Amount"],
            column_config={
                "Date": st.column_config.DateColumn("Date", format="DD MMM", width="small"),
                "Merchant": st.column_config.TextColumn("Merchant", width="medium"),
                "Category": st.column_config.SelectboxColumn("Category", options=cat_options, required=True, width="small"),
                "Amount": st.column_config.TextColumn("Amount", width="small"),
            },
            height=min(38 + 35 * len(ledger), 520),
            width="stretch",
            key=f"ledger_{sig}",
        )

        changed = edited.index[edited["Category"] != ledger["Category"]]
        if len(changed):
            if hasattr(db, "update_category"):
                try:
                    for tx_id in changed:
                        db.update_category(tx_id, edited.loc[tx_id, "Category"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update category: {e}")
            else:
                st.error("Database update function not found. Please refresh the page.")

# ---------------------------------------------------------------- admin
st.markdown('<div style="height:2rem"></div>', unsafe_allow_html=True)
with st.expander("Settings & maintenance"):
    st.caption(
        f"Debug: date {today} | budget {TARGET_DAILY} | spend {m.get('today_food_spend', 0)} | "
        f"rollover {m.get('food_rollover', 0)} | remaining {m.get('food_remaining_today', 0)}"
    )

    with st.expander("➕ Add manual transaction"):
        m_merchant = st.text_input("Merchant", placeholder="e.g. Hungry")
        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_cat = st.selectbox("Category", options=db.CATEGORIES)
        m_dir = st.selectbox("Direction", options=["debit", "credit"])
        if st.button("Log transaction", width="stretch"):
            if m_merchant and m_amount > 0:
                db.add_transaction(today, m_merchant, m_amount, direction=m_dir, category=m_cat)
                st.success(f"Logged {m_dir}: {m_merchant}")
                st.rerun()
            else:
                st.error("Enter a merchant and an amount.")

    new_bal = st.number_input(
        "Adjust current balance (₹)", value=float(round(m["balance"])), step=100.0, format="%.2f", key="admin_bal"
    )
    if st.button("Update balance", width="stretch"):
        db.set_balance(new_bal)
        st.rerun()

    if st.button("Reset Food Silo to 0", width="stretch"):
        db.set_food_silo_zero()
        st.success("Food silo has been reset!")
        st.rerun()

    unparsed = db.get_unparsed()
    if unparsed:
        st.divider()
        st.markdown("**Unread bank texts**")
        for u in unparsed:
            st.code(u["raw"], language=None)
            if st.button("Clear", key=f"u_admin_{u['id']}"):
                db.delete_unparsed(u["id"])
                st.rerun()
