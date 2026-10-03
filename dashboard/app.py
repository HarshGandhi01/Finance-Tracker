"""Am I Cooked? dashboard."""
import os
import sys
from datetime import date

# Ensure repo root is on the path so 'import db' works on Vercel/Streamlit
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


def split_fields(amount, key, existing=None):
    existing = existing or []
    if not st.checkbox("Split with others", value=bool(existing), key=f"split_{key}"):
        return []
    names_text = st.text_input("Who owes you? (comma-separated names)",
                              value=", ".join(s['person'] for s in existing), key=f"names_{key}")
    names = [n.strip() for n in names_text.split(',') if n.strip()]
    mode = st.radio("Split method", ["Equal shares", "Custom shares"],
                    index=1 if existing else 0, key=f"mode_{key}", horizontal=True)
    splits = []
    total_cents = db.money_cents(amount)
    for i, name in enumerate(names):
        default = next((s['cents'] / 100 for s in existing if s['person'] == name), 0.0)
        if mode == "Equal shares":
            share = (total_cents // (len(names) + 1)) / 100
        else:
            share = st.number_input(f"{name}'s share (₹)", min_value=0.0, value=default,
                                    step=1.0, format="%.2f", key=f"share_{key}_{i}_{name}")
        splits.append((name, share))
    personal = (total_cents - sum(db.money_cents(a) for _, a in splits)) / 100
    st.caption(f"You paid {inr(amount, 2)} · Your share {inr(personal, 2)}")
    st.caption("Only your share counts as spending. Equal splits leave any extra paise in your share. "
               "If you're treating someone, include their cost in your own share.")
    if not names:
        st.warning("Enter at least one name to split this expense.")
        return None
    return splits



@st.fragment
def transaction_editor(t, cat_options, existing_splits):
    with st.popover("Edit", key=f"edit_{t['id']}", help="Edit or delete"):
        if t['direction'] == 'debit':
            st.caption(f"Your share {inr(t['personal_amount'], 2)} · Paid {inr(t['amount'], 2)}")
            with st.container():
                edited_splits = split_fields(t['amount'], t['id'], existing_splits)
            if st.button("Save split", key=f"save_split_{t['id']}", disabled=edited_splits is None):
                try:
                    db.set_splits(t['id'], edited_splits)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if t['is_repayment']:
            st.caption("Split repayment · excluded from spending offsets")
            if st.button("Unlink repayment", key=f"unlink_{t['id']}"):
                db.unlink_repayment(t['id'])
                st.rerun()
        new_cat = st.selectbox(
            "Category", options=cat_options,
            index=cat_options.index(t["category"]) if t["category"] in cat_options else 0,
            key=f"cat_{t['id']}",
        )
        col_save, col_del = st.columns(2)
        with col_save:
            if st.button("Save", key=f"save_{t['id']}", use_container_width=True):
                try:
                    if new_cat != t["category"]:
                        db.update_category(t["id"], new_cat)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with col_del:
            if st.button("Delete", key=f"del_{t['id']}", use_container_width=True):
                try:
                    db.delete_transaction(t["id"])
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


@st.fragment
def manual_transaction_editor(today):
    with st.popover("Add manual transaction", width="stretch"):
        m_date = st.date_input("Transaction date", value=today, max_value=today)
        m_merchant = st.text_input("Merchant", placeholder="e.g. Hungry")
        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_cat = st.selectbox("Category", options=db.CATEGORIES)
        m_dir = st.selectbox("Direction", options=["debit", "credit"])
        manual_splits = split_fields(m_amount, 'manual') if m_dir == 'debit' else []
        if st.button("Log transaction", width="stretch", disabled=manual_splits is None):
            if m_merchant and m_amount > 0:
                try:
                    if db.add_transaction(m_date, m_merchant, m_amount, direction=m_dir, category=m_cat, splits=manual_splits):
                        st.rerun()
                    else:
                        st.error("Could not save this transaction.")
                except ValueError as exc:
                    st.error(str(exc))
            else:
                st.error("Enter a merchant and an amount.")


@st.fragment
def repayment_editor(shares, received_credits, today):
    with st.expander("Owed to me", expanded=True):
        outstanding = [s for s in shares if s['date'] <= str(today) and s['cents'] - round(s['repaid'] * 100) > 0]
        st.metric("Outstanding across all cycles", inr(sum(s['cents'] / 100 - s['repaid'] for s in outstanding), 2))
        st.caption("Link repayments already in your records to avoid adding the money twice.")
        if not outstanding:
            st.info("All settled. Split a transaction to track money owed to you.")
        for s in outstanding:
            remaining = (s['cents'] - round(s['repaid'] * 100)) / 100
            with st.expander(f"{s['person']} · {inr(remaining, 2)} owed · {s['merchant']} · {s['date']}"):
                st.caption(f"Share {inr(s['cents'] / 100, 2)} · Repaid {inr(s['repaid'], 2)}")
                method = st.radio("Repayment", ["Link existing credit", "Record new repayment"], key=f"repay_method_{s['id']}")
                credit_id = None
                repayment_amount = remaining
                repayment_date = today
                if method == "Link existing credit":
                    available = [t for t in received_credits
                                 if t['category'] != 'Pocket Money' and not t['is_repayment'] and t['date'] >= s['date']
                                 and db.money_cents(t['amount']) <= db.money_cents(remaining)]
                    options = {t['id']: t for t in available}
                    credit_id = st.selectbox("Received credit", list(options), index=None,
                        format_func=lambda i: f"{options[i]['date']} · {options[i]['merchant']} · {inr(options[i]['amount'], 2)}",
                        key=f"repay_credit_{s['id']}")
                else:
                    repayment_amount = st.number_input("Amount received (₹)", min_value=0.01,
                        max_value=remaining, value=remaining, step=1.0, key=f"repay_amount_{s['id']}")
                    repayment_date = st.date_input("Received on", value=today, min_value=date.fromisoformat(s['date']),
                                                   max_value=today, key=f"repay_date_{s['id']}")
                if st.button("Save repayment", key=f"repay_save_{s['id']}",
                             disabled=method == "Link existing credit" and credit_id is None):
                    try:
                        db.record_repayment(s['id'], repayment_date, repayment_amount, credit_id)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))




@st.fragment
def transaction_list(txs, shares_by_tx, month):
    st.markdown('<div class="section-title">SYSTEM_LEDGER</div>', unsafe_allow_html=True)

    if not txs:
        st.info("No entries this cycle.")
    else:
        sorted_txs = sorted(txs, key=lambda x: x["date"], reverse=True)
        cat_options = list(db.CATEGORIES) + sorted({t["category"] for t in sorted_txs if t["category"] not in db.CATEGORIES})

        page_size = 25
        page_count = (len(sorted_txs) + page_size - 1) // page_size
        page = 1
        if page_count > 1:
            page = st.selectbox("Transaction page", range(1, page_count + 1), key=f"tx_page_{month}")
        start = (page - 1) * page_size
        st.caption(f"Showing {start + 1}–{min(start + page_size, len(sorted_txs))} of {len(sorted_txs)} transactions")
        for t in sorted_txs[start:start + page_size]:
            dt = pd.to_datetime(t["date"], errors="coerce")
            date_str = dt.strftime("%d %b") if pd.notna(dt) else t["date"]
            sign = "+" if t["direction"] == "credit" else "-"
            amt_class = "tx-credit" if t["direction"] == "credit" else "tx-debit"
            amt_str = f'{sign}{inr(t["amount"], 2)}'

            col1, col2 = st.columns([10, 1], vertical_alignment="center")
            with col1:
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
            with col1:
                if t['personal_amount'] != t['amount']:
                    st.caption(f"Your share {inr(t['personal_amount'], 2)} · Others' shares {inr(t['amount'] - t['personal_amount'], 2)}")
                if t['is_repayment']:
                    st.caption("Split repayment")
            with col2:
                transaction_editor(t, cat_options, shares_by_tx.get(t['id'], []))


# ---------------------------------------------------------------- top bar
today = db.today_ist()

def _shift_month(d: date, delta: int) -> str:
    idx = d.year * 12 + (d.month - 1) + delta
    return f"{idx // 12}-{idx % 12 + 1:02d}"

snapshot = db.load_dashboard(today, st.session_state.get('budget_cycle'), TARGET_DAILY)
month_now = snapshot['month_now']
receipt_dates = snapshot['receipt_dates']
month_options = snapshot['month_options']
if st.session_state.get('budget_cycle') not in month_options:
    st.session_state['budget_cycle'] = snapshot['month']

col_nav1, col_nav2 = st.columns([3, 1], vertical_alignment="center")
with col_nav1:
    st.markdown('<div class="nav-title">Am I cooked?</div>', unsafe_allow_html=True)
with col_nav2:
    month = st.selectbox("Budget cycle", options=month_options, index=0,
                         format_func=lambda key: f"From {key}" if len(key) == 10 else key,
                         label_visibility="collapsed", key="budget_cycle")

received_credits = snapshot['credits']
shares = snapshot['shares']
shares_by_tx = {}
for share in shares:
    shares_by_tx.setdefault(share["transaction_id"], []).append(share)

with st.expander("Pocket-money cycle", expanded=not receipt_dates):
    st.caption("Your cycle starts on the date of a received credit marked Pocket Money. "
               "Mark the existing ₹12,000 payment below. Other credits do not reset your cycle.")
    credits = [t for t in received_credits if not t['is_repayment']]
    if credits:
        credits_by_id = {t["id"]: t for t in credits}
        credit_id = st.selectbox(
            "Received payment", options=list(credits_by_id),
            format_func=lambda key: (
                f"{credits_by_id[key]['date']} · {credits_by_id[key]['merchant']} · "
                f"{inr(credits_by_id[key]['amount'])} · {credits_by_id[key]['category']}"
            ),
        )
        if st.button("Mark as pocket money", width="stretch"):
            db.update_category(credit_id, "Pocket Money")
            st.rerun()
    else:
        st.info("Add the received payment below as a credit with category Pocket Money and its receipt date.")
    if not receipt_dates:
        st.info("No pocket-money receipt marked yet. Showing the existing monthly budget until you select one.")

# ---------------------------------------------------------------- data
m = snapshot['metrics']
st.caption(f"Cycle started {m['cycle_start']:%d %b %Y} · "
           f"{'Estimated through' if month == month_now and receipt_dates else 'Through'} "
           f"{m['cycle_end']:%d %b %Y} · {m['days_remaining']} days remaining")
if receipt_dates and month == month_now:
    st.caption("Allowance assumes the next payment arrives one month after the last. "
               "The cycle resets only when the next received payment is marked Pocket Money.")

daily_avg = m.get("daily_avg", 0.0)
balance = m.get("balance", 0.0)
safe_to_spend = m.get("safe_to_spend", balance)
days_left = m['days_until_broke']
days_left_label = str(int(days_left)) if days_left is not None else '—'
rate_description = (f"net spending {inr(daily_avg)} a day" if daily_avg >= 0
                    else f"net gaining {inr(abs(daily_avg))} a day")

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

clock_tone = "hot" if days_left is not None and days_left <= 7 else (
    "warn" if days_left is not None and days_left <= 14 else "")
food_tone = "hot" if food_remaining < 0 else ""
bar_pct = min(max(food_spent / TARGET_DAILY, 0), 1) * 100 if TARGET_DAILY else 0

hero_left, hero_right = st.columns([1, 1.25], gap="large", vertical_alignment="center")
with hero_left:
    # --- Hero Left (System Depletion) ---
    st.markdown(
        f"""
        <div class="hud-panel">
          <div class="hud-label">SYSTEM_DEPLETION_ESTIMATE</div>
          <div class="hud-value-lg {clock_tone}">{days_left_label}</div>
          <div class="hud-text" style="font-family:var(--font-display); font-size:0.8rem; letter-spacing:0.05em;">
            {inr(balance)} REMAINING · {rate_description.upper()}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hero_right:
    # --- Hero Right (Food Status) ---
    st.markdown(
        f"""
        <div class="hud-panel">
          <div class="hud-label">NUTRIENT_ALLOCATION_TODAY</div>
          <div class="hud-value-md {food_tone}">{inr(food_remaining)}</div>
          <div class="hud-text">{status_text}</div>
          <div class="bar"><span class="bar-fill {food_tone}" style="width:{bar_pct:.0f}%"></span></div>
          <div class="bar-cap"><span>{inr(food_spent)} SPENT</span><span>{inr(TARGET_DAILY)} LIMIT</span></div>
          <div class="silo" style="margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--line); display:flex; justify-content:space-between; color:var(--mute); font-size:0.8rem;">
            <span>Food Silo Reserves</span><b class="hud-value">{inr(food_silo)}</b>
          </div>
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
    f'<div class="hud-tile{" lead" if lead else ""}"><div class="tile-label">{label}</div>'
    f'<div class="tile-value">{value}</div></div>'
    for label, value, lead in tiles
)
st.markdown(f'<div class="section-title">CYCLE_READOUT</div><div class="tiles">{tiles_html}</div>', unsafe_allow_html=True)
with st.expander('How these numbers are calculated'):
    st.write(f"Daily allowance: {inr(balance, 2)} current balance ÷ "
             f"{m['days_remaining']} days left = {inr(m['daily_allowance'], 2)} per day.")
    st.write(f"Extra per day: {inr(m['daily_allowance'], 2)} − {inr(TARGET_DAILY)} "
             f"food minimum = {inr(m['fun_money'], 2)}.")
    st.write(f"Safe per meal: {inr(m['daily_allowance'], 2)} ÷ 2 meals = "
             f"{inr(m['safe_per_meal'], 2)} per meal.")
    st.write(f"Current burn rate: ({inr(m['personal_spending'], 2)} personal spending − "
             f"{inr(m['received_offsets'], 2)} received credits) ÷ "
             f"{m['days_elapsed']} elapsed days = {inr(daily_avg, 2)} per day.")
    st.caption('Day counts include today and days with no spending. Your month starts when pocket money arrives. '
               'Received credits offset spending, except Pocket Money, which funds the cycle. '
               'A negative burn rate means more money came in than went out, excluding pocket money. '
               'Income and carried-over cash are already included in your current balance.')
    st.caption("Split expenses count only your share. Linked repayments are excluded from spending offsets. "
               "Money owed to you is not available cash until repaid.")
    st.write(f"Safe to spend is a separate figure: {inr(balance, 2)} balance − "
             f"{inr(m['reserved'], 2)} reserved funds = {inr(safe_to_spend, 2)}. "
             "Daily allowance uses the full current balance, as requested.")
    if days_left is None:
        st.caption('No depletion estimate: net spending is zero or negative this cycle.')

# ---------------------------------------------------------------- breakdown charts
txs = m["txs"]
st.markdown('<div class="section-title">RESOURCE_DISTRIBUTION</div>', unsafe_allow_html=True)

if not txs:
    st.info("No spending data to analyze this cycle.")
else:
    df_tx = pd.DataFrame(txs)
    debits = df_tx[df_tx["direction"] == "debit"].copy()
    debits['amount'] = debits['personal_amount']

    col_c1, col_c2, col_c3 = st.columns(3, gap="large")

    with col_c1:
        if not debits.empty:
            cat_sums = debits.groupby("category")["amount"].sum().sort_values(ascending=False)
            st.plotly_chart(spending_donut(cat_sums, "spent"), width="stretch", config={"displayModeBar": False})

    with col_c2:
        if not debits.empty:
            merch_sums = debits.groupby("merchant")["amount"].sum().sort_values(ascending=False).head(5)
            # Group the rest into "Other" if there are many
            if len(debits["merchant"].unique()) > 5:
                other_sum = debits["amount"].sum() - merch_sums.sum()
                if other_sum > 0:
                    merch_sums["Other Merchants"] = other_sum
            st.plotly_chart(spending_donut(merch_sums, "top vendors"), width="stretch", config={"displayModeBar": False})

    with col_c3:
        if not df_tx.empty:
            st.plotly_chart(burn_rate_line(df_tx, TARGET_DAILY,
                                          m["cycle_start"], m["cycle_end"], today),
                           width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- splits
repayment_editor(shares, received_credits, today)

# ---------------------------------------------------------------- ledger
transaction_list(txs, shares_by_tx, month)

# ---------------------------------------------------------------- admin
st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
with st.expander("Settings & maintenance"):
    st.caption(
        f"Debug: date {today} | budget {TARGET_DAILY} | spend {m.get('today_food_spend', 0)} | "
        f"rollover {m.get('food_rollover', 0)} | remaining {m.get('food_remaining_today', 0)}"
    )

    manual_transaction_editor(today)

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

    unparsed = snapshot['unparsed']
    if unparsed:
        st.divider()
        st.markdown("**Unread bank texts**")
        for u in unparsed:
            st.code(u["raw"], language=None)
            if st.button("Clear", key=f"u_admin_{u['id']}"):
                db.delete_unparsed(u["id"])
                st.rerun()
