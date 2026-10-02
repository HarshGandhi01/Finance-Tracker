"""Am I Cooked? — dashboard (redesign: presentation only, db calls unchanged)."""
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
safe_to_spend = m.get("safe_to_spend", balance)
divisor = max(daily_avg, TARGET_DAILY)
days_left = safe_to_spend / divisor if divisor > 0 else 999

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
          <div class="clock-sub">{inr(safe_to_spend)} left, spending {inr(divisor)} a day</div>
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
        cat_options = list(db.CATEGORIES) + sorted({t["category"] for t in sorted_txs if t["category"] not in db.CATEGORIES})

        # Render transaction rows as styled HTML cards
        for t in sorted_txs:
            dt = pd.to_datetime(t["date"], errors="coerce")
            date_str = dt.strftime("%d %b") if pd.notna(dt) else t["date"]
            sign = "+" if t["direction"] == "credit" else "-"
            amt_class = "tx-credit" if t["direction"] == "credit" else "tx-debit"
            amt_str = f'{sign}{inr(t["amount"], 2)}'

            st.markdown(
                f"""
                <div class="tx-row">
                  <div class="tx-date">{date_str}</div>
                  <div class="tx-merchant">{str(t["merchant"])}</div>
                  <div class="tx-category">{t["category"]}</div>
                  <div class="tx-amount {amt_class}">{amt_str}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.popover("✏️", key=f"edit_{t['id']}"):
                new_cat = st.selectbox(
                    "Category", options=cat_options,
                    index=cat_options.index(t["category"]) if t["category"] in cat_options else 0,
                    key=f"cat_{t['id']}",
                )
                col_save, col_del = st.columns(2)
                with col_save:
                    if st.button("Save", key=f"save_{t['id']}", use_container_width=True):
                        if new_cat != t["category"]:
                            db.update_category(t["id"], new_cat)
                        st.rerun()
                with col_del:
                    if st.button("🗑️ Delete", key=f"del_{t['id']}", use_container_width=True):
                        db.delete_transaction(t["id"])
                        st.rerun()

# ---------------------------------------------------------------- admin
st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
with st.expander("Settings & maintenance"):
    st.caption(
        f"Debug: date {today} | budget {TARGET_DAILY} | spend {m.get('today_food_spend', 0)} | "
        f"rollover {m.get('food_rollover', 0)} | remaining {m.get('food_remaining_today', 0)}"
    )

    with st.popover("Add manual transaction", width="stretch"):
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

    st.divider()

    new_bal = st.number_input(
        "Adjust current balance (₹)", value=float(round(m["balance"])), step=100.0, format="%.2f", key="admin_bal"
    )
    if st.button("Update balance", width="stretch"):
        db.set_balance(new_bal)
        st.success(f"Balance updated to {inr(new_bal)}.")
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
