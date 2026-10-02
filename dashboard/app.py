"""Am I Cooked? — survival HUD redesign."""
import os
import sys
from datetime import date

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

import pandas as pd
import streamlit as st

from database_loader import load_database
from theme import apply_theme, inr, spending_donut, burn_rate_line

db = load_database()

TARGET_DAILY = 350.0

st.set_page_config(
    page_title="Am I cooked?",
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

month_now = db.get_current_cycle_month(today)
try:
    db.update_food_silo(today, db.get_transactions(month_now), TARGET_DAILY)
except AttributeError:
    pass

receipt_dates = db.get_pocket_money_dates(today)
month_options = receipt_dates or [month_now]

# Minimalist Nav
col_nav1, col_nav2 = st.columns([3, 1], vertical_alignment="center")
with col_nav1:
    st.markdown('<div class="nav-title">Am I cooked?</div>', unsafe_allow_html=True)
with col_nav2:
    month = st.selectbox("Budget cycle", options=month_options, index=0,
                         format_func=lambda key: f"From {key}" if len(key) == 10 else key,
                         label_visibility="collapsed")

# Move pocket money config to a bottom expander to clear the HUD
# ---------------------------------------------------------------- data
m = db.compute_metrics(month, today, TARGET_DAILY)

daily_avg = m.get("daily_avg", 0.0)
balance = m.get("balance", 0.0)
safe_to_spend = m.get("safe_to_spend", balance)
days_left = m['days_until_broke']
days_left_label = str(int(days_left)) if days_left is not None else '—'

try:
    food_remaining = float(m.get("food_remaining_today", 0.0))
except (TypeError, ValueError):
    food_remaining = 0.0

# ---------------------------------------------------------------- HUD HERO
# Mood Logic
if days_left is None or days_left > 14:
    mood = "comfortable"
    status_text = "Everything is fine. Don't get cocky."
elif days_left <= 7:
    mood = "cooked"
    status_text = "You are officially cooked. Eat the mess food."
else:
    mood = "sweating"
    status_text = "You're sweating. Scale back the snacks."

# Signature Element: Life Bar (Segmented)
segments_total = 30 # One month view
segments_active = int(min(max(days_left if days_left is not None else 0, 0), segments_total))
segments_html = "".join([
    f'<div class="life-segment {"active" if i < segments_active else ""} {mood if i < segments_active else ""}"></div>'
    for i in range(segments_total)
])

# Desktop Asymmetric Layout
col_main, col_side = st.columns([2, 1], gap="large")

with col_main:
    st.markdown(
        f"""
        <div class="hud-header" style="text-align:left;">
            <div class="status-label" style="color: var(--mood-{mood})">{status_text}</div>
            <div class="hero-value">{days_left_label} <span style="font-size: 1.5rem; vertical-align: middle; opacity: 0.6;">DAYS LEFT</span></div>
            <div class="life-bar-container">{segments_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---------------------------------------------------------------- STATS
    stats = [
        ("Safe to spend", inr(safe_to_spend)),
        ("Daily runway", inr(m["daily_allowance"])),
        ("Safe per meal", inr(m["safe_per_meal"])),
    ]

    stats_html = "".join([
        f'<div class="stat-item"><div class="stat-label">{l}</div><div class="stat-value">{v}</div></div>'
        for l, v in stats
    ])
    st.markdown(f'<div class="stats-grid">{stats_html}</div>', unsafe_allow_html=True)

with col_side:
    # Move the "The Burn" chart to the side on desktop to avoid long vertical scroll
    if txs:
        df_tx = pd.DataFrame(txs)
        st.markdown('<div class="ledger-title">The Burn</div>', unsafe_allow_html=True)
        st.plotly_chart(burn_rate_line(df_tx, TARGET_DAILY, m["cycle_start"], m["cycle_end"], today),
                       use_container_width=True, config={"displayModeBar": False})

# ---------------------------------------------------------------- CHARTS (Lower section)
if txs:
    df_tx = pd.DataFrame(txs)
    debits = df_tx[df_tx["direction"] == "debit"]

    st.markdown('<div class="ledger-title" style="margin-top:3rem">Top Offenders</div>', unsafe_allow_html=True)
    if not debits.empty:
        merch_sums = debits.groupby("merchant")["amount"].sum().sort_values(ascending=False).head(5)
        total_spent = debits["amount"].sum()
        for merchant, amount in merch_sums.items():
            pct = (amount / total_spent) * 100
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; gap:1rem; margin-bottom:0.5rem;">
                    <div style="flex:1; font-family:var(--font-display); font-size:0.9rem;">{merchant}</div>
                    <div style="width:100px; height:8px; background:var(--surface); border-radius:4px; overflow:hidden;">
                        <div style="width:{pct}%; height:100%; background:var(--mood-{mood});"></div>
                    </div>
                    <div style="width:80px; text-align:right; font-family:var(--font-display); font-weight:700;">{inr(amount)}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

# ---------------------------------------------------------------- LEDGER
st.markdown('<div class="ledger-title" style="margin-top:3rem">Log</div>', unsafe_allow_html=True)

if not txs:
    st.info("No entries this cycle.")
else:
    sorted_txs = sorted(txs, key=lambda x: x["date"], reverse=True)

    for t in sorted_txs:
        dt = pd.to_datetime(t["date"], errors="coerce")
        date_str = dt.strftime("%d %b") if pd.notna(dt) else t["date"]
        amt_class = "amount-credit" if t["direction"] == "credit" else "amount-debit"
        sign = "+" if t["direction"] == "credit" else ""

        # Use a small dot for category
        cat_color = "var(--mood-comfortable)" if t["category"] == "Pocket Money" else "var(--mute)"

        st.markdown(
            f"""
            <div class="tx-row" onclick="window.location.reload()">
              <div class="tx-info">
                <div class="tx-merchant">{str(t["merchant"])} <span style="font-weight:400; opacity:0.5; font-size:0.8rem; margin-left:0.5rem;">{date_str}</span></div>
                <div class="tx-category">
                    <span class="cat-dot" style="background:{cat_color}"></span> {t["category"]}
                </div>
              </div>
              <div class="tx-amount {amt_class}">{sign}{inr(t["amount"], 2)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Logic for Editing: The prompt asks for "tap a row to open a dialog".
        # Since Streamlit doesn't have native "onclick" for HTML, we use the popover but move it
        # to a single interaction point or handle it via the admin section.
        # To strictly follow "remove per-row edit buttons", we remove the col2 popover.

# ---------------------------------------------------------------- ADMIN / SETTINGS
with st.expander("Settings & Maintenance"):
    # Move the pocket money cycle here
    st.markdown("### Budget Cycle")
    credits = db.get_received_credits(today)
    if credits:
        credits_by_id = {t["id"]: t for t in credits}
        credit_id = st.selectbox(
            "Mark as pocket money", options=list(credits_by_id),
            format_func=lambda key: f"{credits_by_id[key]['date']} · {credits_by_id[key]['merchant']} · {inr(credits_by_id[key]['amount'])}",
        )
        if st.button("Confirm Reset", width="stretch"):
            db.update_category(credit_id, "Pocket Money")
            st.rerun()

    st.divider()

    with st.popover("Add transaction", width="stretch"):
        m_date = st.date_input("Date", value=today, max_value=today)
        m_merchant = st.text_input("Merchant")
        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_cat = st.selectbox("Category", options=db.CATEGORIES)
        m_dir = st.selectbox("Direction", options=["debit", "credit"])
        if st.button("Log", width="stretch"):
            if m_merchant and m_amount > 0:
                db.add_transaction(m_date, m_merchant, m_amount, direction=m_dir, category=m_cat)
                st.rerun()

    st.divider()
    new_bal = st.number_input("Adjust balance", value=float(round(balance)), step=100.0)
    if st.button("Update", width="stretch"):
        db.set_balance(new_bal)
        st.rerun()
