"""Am I Cooked? dashboard."""
import os
import sys
from datetime import date
from html import escape

# Ensure repo root is on the path so 'import db' works on Vercel/Streamlit
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

import pandas as pd
import streamlit as st

from database_loader import load_database
from theme import apply_theme, inr, burn_rate_line

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
def transaction_editor(t, cat_options, existing_splits, rules):
    with st.popover("Edit", key=f"edit_{t['id']}", help="Edit this transaction", width="stretch"):
        st.subheader("Edit transaction")
        merchant = st.text_input("Vendor or person", value=t['merchant'], key=f"merchant_{t['id']}")
        new_cat = st.selectbox("Category", options=cat_options,
                              index=cat_options.index(t['category']), key=f"cat_{t['id']}")
        remember = None
        if t['direction'] == 'debit':
            rule = rules.get(db.normalize_merchant(t['merchant']))
            remember_checked = st.checkbox("Use for future payments to this vendor", value=bool(rule), key=f"remember_{t['id']}")
            st.caption(f"Saved default: {rule}. Uncheck to remove it." if rule else "Matches this vendor name, ignoring case and extra spaces.")
            if remember_checked or rule:
                remember = remember_checked
        col_save, col_del = st.columns([2, 1])
        with col_save:
            if st.button("Save changes", key=f"save_{t['id']}", type="primary", width="stretch"):
                try:
                    db.edit_transaction(t['id'], merchant, new_cat, remember)
                    st.session_state['notice'] = 'Transaction updated. Vendor rule saved.' if remember else 'Transaction updated.'
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with col_del:
            if st.button("Delete", key=f"del_{t['id']}", width="stretch"):
                try:
                    db.delete_transaction(t['id'])
                    st.session_state['notice'] = 'Transaction deleted.'
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        if t['direction'] == 'debit':
            st.divider()
            st.caption(f"Paid {inr(t['amount'], 2)} · Your share {inr(t['personal_amount'], 2)}")
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


@st.fragment
def manual_transaction_editor(today):
    with st.popover("Add transaction", width="stretch"):
        m_date = st.date_input("Transaction date", value=today, max_value=today)
        m_merchant = st.text_input("Merchant", placeholder="e.g. Hungry")

        # Auto-tagging logic
        default_cat = db.CATEGORIES[0]
        if m_merchant:
            mapped_cat = db.get_merchant_category(m_merchant)
            if mapped_cat and mapped_cat in db.CATEGORIES:
                default_cat = mapped_cat

        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_cat = st.selectbox("Category", options=db.CATEGORIES, index=db.CATEGORIES.index(default_cat))
        m_dir = st.selectbox("Direction", options=["debit", "credit"])

        auto_tag = st.checkbox("Save as default category for this merchant", value=False)

        manual_splits = split_fields(m_amount, 'manual') if m_dir == 'debit' else []
        if st.button("Log transaction", width="stretch", disabled=manual_splits is None):
            if m_merchant and m_amount > 0:
                try:
                    if db.add_transaction(m_date, m_merchant, m_amount, direction=m_dir, category=m_cat, splits=manual_splits, apply_merchant_rule=False):
                        if auto_tag:
                            db.set_merchant_category(m_merchant, m_cat)
                        st.rerun()
                    else:
                        st.error("Could not save this transaction.")
                except ValueError as exc:
                    st.error(str(exc))
            else:
                st.error("Enter a merchant and an amount.")


@st.fragment
def repayment_editor(shares, received_credits, today):
    with st.expander("Owed to me", expanded=False):
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
def transaction_list(txs, shares_by_tx, month, rules):
    with st.container(border=True, key='ledger'):
        title, search, category = st.columns([2, 2, 1.2], vertical_alignment='center')
        with title:
            st.subheader('Transactions')
        with search:
            query = st.text_input('Search vendor or person', placeholder='Search vendor or person…', label_visibility='collapsed', key='ledger_search')
        cat_options = list(db.CATEGORIES) + sorted({t['category'] for t in txs if t['category'] not in db.CATEGORIES})
        with category:
            selected = st.selectbox('Filter by category', ['All categories'] + cat_options, label_visibility='collapsed', key='ledger_category')
        matches = [t for t in txs if query.casefold().strip() in t['merchant'].casefold()
                   and (selected == 'All categories' or t['category'] == selected)]
        sorted_txs = sorted(matches, key=lambda t: (t['date'], t['id']), reverse=True)
        if not sorted_txs:
            st.info('No transactions match your filters.' if txs else 'No transactions yet. Add your first payment to get started.')
            return
        page_size = 25
        page_count = (len(sorted_txs) + page_size - 1) // page_size
        page_key = f'tx_page_{month}'
        if st.session_state.get(page_key, 1) > page_count:
            st.session_state[page_key] = 1
        page = st.selectbox('Transaction page', range(1, page_count + 1), key=page_key) if page_count > 1 else 1
        start = (page - 1) * page_size
        st.markdown('<div class="ledger-head"><span>Date</span><span>Vendor or person</span><span>Category</span><span>Amount</span><span></span></div>', unsafe_allow_html=True)
        for t in sorted_txs[start:start + page_size]:
            date_str = date.fromisoformat(t['date']).strftime('%d %b')
            sign = '+' if t['direction'] == 'credit' else '−'
            tone = 'credit' if t['direction'] == 'credit' else ''
            detail = ''
            if t['personal_amount'] != t['amount']:
                detail = f"Your share {inr(t['personal_amount'], 2)}"
            elif t['is_repayment']:
                detail = 'Split repayment'
            elif t['direction'] == 'debit' and db.normalize_merchant(t['merchant']) in rules:
                detail = 'Vendor rule saved'
            with st.container(key=f"ledger_row_{t['id']}"):
                row, action = st.columns([10, 1], vertical_alignment='center', gap='small')
                with row:
                    st.markdown(f'<div class="ledger-row"><span class="row-date">{date_str}</span>'
                                f'<span class="row-vendor">{escape(t["merchant"])}<small>{escape(detail)}</small></span>'
                                f'<span class="row-category"><span>{escape(t["category"])}</span></span>'
                                f'<span class="row-amount {tone}">{sign}{inr(t["amount"], 2)}</span></div>', unsafe_allow_html=True)
                with action:
                    transaction_editor(t, cat_options, shares_by_tx.get(t['id'], []), rules)
        st.caption(f'Showing {start + 1}–{min(start + page_size, len(sorted_txs))} of {len(sorted_txs)} transactions')


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

brand, add = st.columns([5, 1.2], vertical_alignment='center')
with brand:
    st.markdown('<div class="brand">Am I cooked? <span>Personal finance</span></div>', unsafe_allow_html=True)
with add:
    manual_transaction_editor(today)
heading, cycle = st.columns([4, 1.3], vertical_alignment='center')
with heading:
    st.title('Overview')
with cycle:
    month = st.selectbox('Budget cycle', options=month_options,
                        format_func=lambda key: f'From {key}' if len(key) == 10 else key,
                        label_visibility='collapsed', key='budget_cycle')
if 'notice' in st.session_state:
    st.toast(st.session_state.pop('notice'))

received_credits = snapshot['credits']
shares = snapshot['shares']
shares_by_tx = {}
for share in shares:
    shares_by_tx.setdefault(share["transaction_id"], []).append(share)

# ---------------------------------------------------------------- overview
m = snapshot['metrics']
balance = m['balance']
st.caption(f"{m['cycle_start']:%d %b} – {m['cycle_end']:%d %b %Y} · {m['days_remaining']} days remaining")
outstanding = sum(max(s['cents'] / 100 - s['repaid'], 0) for s in shares if s['date'] <= str(today))
summary = [
    ('Current balance', inr(balance) if m['has_balance'] else 'Not set', 'Money available right now'),
    ('Daily allowance', inr(m['daily_allowance']), f"Across {m['days_remaining']} remaining days"),
    ('Food left today', inr(m['food_remaining_today']), f"{inr(m['today_food_spend'])} spent · {inr(TARGET_DAILY)} daily budget"),
    ('Owed to you', inr(outstanding), 'Outstanding across all cycles'),
]
st.markdown('<div class="summary-grid">' + ''.join(
    f'<div class="summary-item"><div>{label}</div><strong>{value}</strong><small>{caption}</small></div>'
    for label, value, caption in summary) + '</div>', unsafe_allow_html=True)
if not m['has_balance']:
    st.info('Set your current balance in Settings & maintenance to calculate your daily allowance.')

txs = m['txs']
chart, breakdown = st.columns([1.7, 1], gap='medium')
with chart:
    with st.container(border=True):
        st.subheader('Spending this cycle')
        st.caption('Your share of expenses, less received credits. Pocket money and split repayments are excluded.')
        if txs:
            fig = burn_rate_line(pd.DataFrame(txs), TARGET_DAILY, m['cycle_start'], m['cycle_end'], today)
            fig.update_layout(height=230, margin=dict(l=10, r=10, t=5, b=0))
            st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        else:
            st.info('Your spending trend will appear after your first transaction.')
with breakdown:
    with st.container(border=True):
        st.subheader('By category')
        st.caption('Personal spending this cycle')
        totals = {}
        for t in txs:
            if t['direction'] == 'debit' and t['personal_amount'] > 0:
                totals[t['category']] = totals.get(t['category'], 0) + t['personal_amount']
        total = sum(totals.values())
        for label, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
            pct = amount / total * 100
            st.markdown(f'<div class="category-line"><span>{escape(label)}</span><b>{inr(amount)}</b><small>{pct:.0f}%</small></div>'
                        f'<div class="category-track"><span style="width:{pct:.1f}%"></span></div>', unsafe_allow_html=True)
        if not totals:
            st.caption('No personal expenses this cycle.')
transaction_list(txs, shares_by_tx, month, snapshot['merchant_categories'])
repayment_editor(shares, received_credits, today)
with st.expander('Budget details'):
    st.write(f"Daily allowance: {inr(balance, 2)} ÷ {m['days_remaining']} days = {inr(m['daily_allowance'], 2)}.")
    st.write(f"Safe to spend: {inr(m['safe_to_spend'])} · Reserved funds: {inr(m['reserved'])} · Food savings: {inr(m['food_rollover'])}.")
    st.write(f"Safe per meal: {inr(m['safe_per_meal'])} · Extra per day: {inr(m['fun_money'])} · Average net spend: {inr(m['daily_avg'])} per day.")
    st.caption('Allowance uses available cash. Money owed to you becomes available only when repaid. The cycle resets when the next received payment is marked Pocket Money.')

# ---------------------------------------------------------------- admin
st.markdown('<div class="spacer-lg"></div>', unsafe_allow_html=True)
with st.expander("Settings & maintenance"):
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

with st.expander("Pocket-money cycle", expanded=not receipt_dates):
    st.caption("Your cycle starts on the date of a received credit marked Pocket Money. "
               "Choose its received payment below. Other credits do not reset your cycle.")
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

