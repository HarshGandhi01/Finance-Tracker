"""Dashboard pages and shared editors."""
from datetime import date, timedelta
from html import escape
import pandas as pd
import streamlit as st
from theme import inr, burn_rate_line, next_25th

TARGET_DAILY = 350.0


def budget_status(allowance, target=TARGET_DAILY):
    if allowance >= target * 1.25:
        return "Comfortable"
    if allowance >= target:
        return "Tight"
    return "Cooked"


def food_caption(metrics):
    if metrics["today_food_spend"] > TARGET_DAILY:
        coverage = "silo is negative" if metrics["food_silo_after_today"] < 0 else "covered by silo"
        return f"{inr(metrics['today_food_spend'] - TARGET_DAILY)} over today · {coverage}"
    return f"{inr(metrics['today_food_spend'])} spent of {inr(TARGET_DAILY)}"


def render_overview(db):
    today = db.today_ist()
    snapshot = db.load_dashboard(today, st.session_state.get("budget_cycle"), TARGET_DAILY)
    m = snapshot["metrics"]
    if st.session_state.get("budget_cycle") not in snapshot["month_options"]:
        st.session_state["budget_cycle"] = snapshot["month"]
    st.markdown('<div class="brand">Am I cooked?</div>', unsafe_allow_html=True)
    if "notice" in st.session_state:
        st.toast(st.session_state.pop("notice"))
    hero = st.empty()
    summary = st.empty()
    default_date = next_25th(today)
    if st.session_state.get("money_date", default_date) <= today:
        st.session_state["money_date"] = default_date
    with st.expander("Plan dates"):
        cycle_col, scope_col, date_col = st.columns(3)
        with cycle_col:
            month = st.selectbox("Budget cycle", snapshot["month_options"], key="budget_cycle",
                                format_func=lambda key: f"From {key}" if len(key) == 10 else key)
        with scope_col:
            scope = st.selectbox("Budget horizon", ["Until money date", "Full cycle"], key="plan_through")
        with date_col:
            money_date = st.date_input("Ask for money on", value=default_date,
                                      min_value=today + timedelta(days=1), key="money_date")
    plan_end = money_date - timedelta(days=1) if scope == "Until money date" else m["cycle_end"]
    days = max((plan_end - today).days + 1, 1)
    allowance = m["safe_to_spend"] / days
    status = budget_status(allowance)
    if m["has_balance"]:
        hero.html(f'<div class="budget-status {status.lower()}">{status}</div>'
                  f'<h1 class="allowance">{inr(allowance)} a day <span class="plan-until">until {plan_end:%d %b}</span></h1>')
    else:
        hero.html('<h1 class="allowance">Set your balance</h1>'
                  '<p>Open Settings to calculate your daily allowance.</p>')
    outstanding = sum(max(s["cents"] / 100 - s["repaid"], 0)
                      for s in snapshot["shares"] if s["date"] <= str(today))
    figures = [
        ("Balance", inr(m["balance"]) if m["has_balance"] else "Not set", "Available right now"),
        ("Food left today", inr(m["food_remaining_today"]), food_caption(m)),
        ("Food silo", inr(m["food_rollover"]), f"Projected after today: {inr(m['food_silo_after_today'])}"),
        ("Owed to you", inr(outstanding), "Across all cycles"),
    ]
    summary.markdown('<div class="summary-grid">' + "".join(
        f'<div class="summary-item"><strong>{escape(value)}</strong><div>{label}</div>'
        f'<small>{escape(caption)}</small></div>' for label, value, caption in figures) + "</div>",
        unsafe_allow_html=True)
    txs = m["txs"]
    chart, breakdown = st.columns([2, 1], gap="large")
    with chart:
        st.subheader("Net spending")
        st.caption("Dotted line projects your current pace.")
        if txs:
            fig = burn_rate_line(pd.DataFrame(txs), TARGET_DAILY, m["cycle_start"], plan_end, today,
                                 balance=m["balance"])
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        else:
            st.caption("Your spending trend will appear after your first transaction.")
    with breakdown:
        st.subheader("By category")
        st.caption("Personal spending this cycle")
        totals = {}
        for tx in txs:
            if tx["direction"] == "debit" and tx["personal_amount"] > 0:
                totals[tx["category"]] = totals.get(tx["category"], 0) + tx["personal_amount"]
        total = sum(totals.values())
        for label, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
            pct = amount / total * 100
            st.markdown(f'<div class="category-line"><span>{escape(label)}</span><b>{inr(amount)}</b>'
                        f'<small>{pct:.0f}%</small></div><div class="category-track">'
                        f'<span style="width:{pct:.1f}%"></span></div>', unsafe_allow_html=True)
        if not totals:
            st.caption("No personal expenses this cycle.")
    manual_transaction_editor(db, today)
    shares_by_tx = {}
    for share in snapshot["shares"]:
        shares_by_tx.setdefault(share["transaction_id"], []).append(share)
    transaction_list(db, txs, shares_by_tx, month, snapshot["merchant_categories"])
    repayment_editor(db, snapshot["shares"], snapshot["credits"], today)
    with st.expander("Budget details"):
        st.write(f"Daily allowance: {inr(m['balance'], 2)} balance ÷ {days} days = {inr(allowance, 2)}.")
        st.write(f"Comfortable: at least {inr(TARGET_DAILY * 1.25, 2)} a day (125% of the food target). "
                 f"Tight: {inr(TARGET_DAILY)} to below {inr(TARGET_DAILY * 1.25, 2)}. "
                 f"Cooked: below {inr(TARGET_DAILY)}.")
        st.caption(f"Cycle: {m['cycle_start']:%d %b} – {m['cycle_end']:%d %b %Y}. "
                   "The silo is part of your balance, not extra cash. "
                   "Money owed becomes available only when repaid. "
                   "Pocket money and split repayments are excluded from the spending chart.")


def render_settings(db):
    today = db.today_ist()
    snapshot = db.load_dashboard(today, target_daily=TARGET_DAILY)
    st.markdown('<div class="brand">Am I cooked?</div>', unsafe_allow_html=True)
    st.title("Settings")
    st.subheader("Balance adjustment")
    with st.form("balance_adjustment", border=False):
        balance = st.number_input("Current balance (₹)", value=float(snapshot["metrics"]["balance"]),
                                  step=100.0, format="%.2f")
        if st.form_submit_button("Update balance"):
            db.set_balance(balance)
            st.session_state["notice"] = "Balance updated."
            st.rerun()
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))
    category_manager(db)
    with st.expander("Pocket-money cycle", expanded=not snapshot["receipt_dates"]):
        st.caption("Your cycle starts on the date of a received credit marked Pocket Money.")
        credits = {t["id"]: t for t in snapshot["credits"] if not t["is_repayment"]}
        if credits:
            credit_id = st.selectbox("Received payment", list(credits),
                                    format_func=lambda i: f"{credits[i]['date']} · {credits[i]['merchant']} · {inr(credits[i]['amount'])}")
            if st.button("Mark as pocket money"):
                db.update_category(credit_id, "Pocket Money")
                st.rerun()
        else:
            st.caption("Add the received payment on Overview as a credit with category Pocket Money.")
    with st.expander("Food silo"):
        st.caption("Reset accumulated food savings to zero from today.")
        if st.button("Reset food silo"):
            db.set_food_silo_zero()
            st.session_state["notice"] = "Food silo reset."
            st.rerun()
    with st.expander("Unread bank texts"):
        if not snapshot["unparsed"]:
            st.caption("No unread bank texts.")
        for sms in snapshot["unparsed"]:
            st.code(sms["raw"], language=None)
            if st.button("Clear", key=f"u_admin_{sms['id']}"):
                db.delete_unparsed(sms["id"])
                st.rerun()

def category_manager(db):
    st.subheader("Categories")
    names = db.get_categories()
    funds = db.get_funds()
    with st.form("add_category", border=False):
        name = st.text_input("New category", max_chars=24)
        if st.form_submit_button("Add category"):
            try:
                db.add_category(name)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    for index, name in enumerate(names):
        locked = name in {"Food", "Pocket Money", "Other"}
        with st.expander(f"{name} · Locked" if locked else name):
            up, down = st.columns(2)
            if up.button("Move up", key=f"up_{name}", disabled=index == 0):
                db.move_category(name, -1)
                st.rerun()
            if down.button("Move down", key=f"down_{name}", disabled=index == len(names) - 1):
                db.move_category(name, 1)
                st.rerun()
            if locked:
                st.caption("Used by budget calculations. This category cannot be renamed or deleted.")
                continue
            with st.form(f"rename_{name}", border=False):
                new_name = st.text_input("Category name", value=name, max_chars=24)
                if st.form_submit_button("Rename"):
                    try:
                        db.rename_category(name, new_name)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            with st.form(f"delete_category_{name}", border=False):
                options = [n for n in names if n != name]
                replacement = st.selectbox("Move transactions and vendor rules to", options,
                                           index=options.index("Other"))
                delete_fund = False
                if name in funds:
                    choice = st.radio("Sinking fund", ["Move fund to replacement", "Delete fund too"])
                    delete_fund = choice == "Delete fund too"
                    st.caption("Moving combines this fund with any existing replacement fund.")
                confirmed = st.checkbox("Confirm category deletion")
                if st.form_submit_button("Delete category"):
                    if not confirmed:
                        st.error("Confirm the deletion first.")
                    else:
                        try:
                            db.delete_category(name, replacement, delete_fund)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))


def split_fields(db, amount, key, existing=None):
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
def transaction_editor(db, t, cat_options, existing_splits, rules):
    with st.popover("", icon=":material/edit:", key=f"edit_{t['id']}", help="Edit this transaction", width="content"):
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
                edited_splits = split_fields(db, t['amount'], t['id'], existing_splits)
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
def manual_transaction_editor(db, today):
    with st.popover("Add transaction", width="stretch"):
        m_date = st.date_input("Transaction date", value=today, max_value=today)
        m_merchant = st.text_input("Merchant", placeholder="e.g. Hungry")

        # Auto-tagging logic
        default_cat = db.get_categories()[0]
        if m_merchant:
            mapped_cat = db.get_merchant_category(m_merchant)
            if mapped_cat and mapped_cat in db.get_categories():
                default_cat = mapped_cat

        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_cat = st.selectbox("Category", options=db.get_categories(), index=db.get_categories().index(default_cat))
        m_dir = st.selectbox("Direction", options=["debit", "credit"])

        auto_tag = st.checkbox("Save as default category for this merchant", value=False)

        manual_splits = split_fields(db, m_amount, 'manual') if m_dir == 'debit' else []
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
def repayment_editor(db, shares, received_credits, today):
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
def transaction_list(db, txs, shares_by_tx, month, rules):
    with st.container(border=False, key='ledger'):
        title, search, category = st.columns([2, 2, 1.2], vertical_alignment='center')
        with title:
            st.subheader('Transactions')
        with search:
            query = st.text_input('Search vendor or person', placeholder='Search vendor or person…', label_visibility='collapsed', key='ledger_search')
        cat_options = list(db.get_categories()) + sorted({t['category'] for t in txs if t['category'] not in db.get_categories()})
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
        previous_day = None
        for t in sorted_txs[start:start + page_size]:
            date_str = date.fromisoformat(t['date']).strftime('%d %b')
            if t['date'] != previous_day:
                st.caption(date.fromisoformat(t['date']).strftime('%A, %d %b'))
                previous_day = t['date']
            sign = '+' if t['direction'] == 'credit' else '−'
            tone = 'credit' if t['direction'] == 'credit' else 'debit'
            detail = ''
            if t['personal_amount'] != t['amount']:
                detail = f"Your share {inr(t['personal_amount'], 2)}"
            elif t['is_repayment']:
                detail = 'Split repayment'
            elif t['direction'] == 'debit' and db.normalize_merchant(t['merchant']) in rules:
                detail = 'Vendor rule saved'
            with st.container(key=f"ledger_row_{t['id']}"):
                with st.container(horizontal=True, vertical_alignment='center', gap='small'):
                    with st.container(width='stretch'):
                        st.markdown(f'<div class="ledger-row"><div class="row-vendor">'
                                    f'<span title="{escape(t["merchant"], quote=True)}">{escape(t["merchant"])}</span>'
                                    f'<small>{escape(t["category"])}{(" · " + escape(detail)) if detail else ""}</small></div>'
                                    f'<span class="row-amount {tone}">{sign}{inr(t["amount"], 2)}</span></div>', unsafe_allow_html=True)
                    with st.container(width=42):
                        transaction_editor(db, t, cat_options, shares_by_tx.get(t['id'], []), rules)
        st.caption(f'Showing {start + 1}–{min(start + page_size, len(sorted_txs))} of {len(sorted_txs)} transactions')


