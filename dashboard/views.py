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
    target = metrics["target_daily"]
    if metrics["today_food_spend"] > target:
        coverage = "savings go negative" if metrics["food_silo_after_today"] < 0 else "covered by savings"
        return f"{inr(metrics['today_food_spend'] - target)} over today · {coverage}"
    return f"{inr(metrics['today_food_spend'])} spent of {inr(target)}"


VERDICT = {"Comfortable": "Not yet.", "Tight": "Almost.", "Cooked": "Yes."}
HEAT = {"Comfortable": "fine", "Tight": "tight", "Cooked": "cooked"}


def heat_scale(allowance, status, target=TARGET_DAILY):
    """Three bands at the real thresholds (0, target, 125% of target) with today's marker."""
    top = target * 2
    pos = min(max(allowance, 0) / top, 1) * 100
    bands = [("cooked", target), ("tight", target * 0.25), ("fine", target * 0.75)]
    spans = "".join(f'<span class="{"on" if HEAT[status] == name else ""}" style="flex:{w}"></span>'
                    for name, w in bands)
    ticks = "".join(f'<span class="heat-tick" style="left:{v / top * 100:.1f}%">{inr(v)}</span>'
                    for v in (target, target * 1.25))
    return (f'<div class="heat" role="img" aria-label="{inr(allowance)} a day: {status.lower()}">'
            f'<div class="heat-bands">{spans}</div>'
            f'<span class="heat-marker" style="left:{pos:.1f}%"></span>{ticks}</div>')


def allowance_note(balance, allowance, target=TARGET_DAILY):
    if balance < 0:
        return f"You're {inr(-balance)} overdrawn."
    gap = allowance - target
    if gap >= 0:
        return f"{inr(gap)} a day more than your {inr(target)} food budget."
    return f"{inr(-gap)} a day short of your {inr(target)} food budget."


def render_overview(db):
    today = db.today_ist()
    snapshot = db.load_dashboard(today, st.session_state.get("budget_cycle"))
    m = snapshot["metrics"]
    target = m["target_daily"]
    if st.session_state.get("budget_cycle") not in snapshot["month_options"]:
        st.session_state["budget_cycle"] = snapshot["month"]
    current = snapshot["month"] == snapshot["month_now"]
    if "notice" in st.session_state:
        st.toast(st.session_state.pop("notice"))
    # Wide screens: answer on the left, figures on the right. Streamlit stacks these on phones.
    top_left, top_right = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    hero = top_left.empty()
    # Seed the widget through session state only, so Streamlit never sees two defaults.
    if st.session_state.get("money_date", today) <= today:
        st.session_state["money_date"] = next_25th(today)
    with top_left.expander("Change dates"):
        cycle_col, scope_col, date_col = st.columns(3)
        with cycle_col:
            month = st.selectbox("Budget cycle", snapshot["month_options"], key="budget_cycle",
                                 format_func=lambda key: f"From {date.fromisoformat(key):%d %b %Y}"
                                 if len(key) == 10 else key)
        with scope_col:
            scope = st.selectbox("Plan until", ["Until money date", "Full cycle"], key="plan_through")
        with date_col:
            money_date = st.date_input("Ask for money on", min_value=today + timedelta(days=1),
                                       key="money_date")
    plan_end = money_date - timedelta(days=1) if scope == "Until money date" else m["cycle_end"]
    days = max((plan_end - today).days + 1, 1)
    allowance = m["safe_to_spend"] / days
    status = budget_status(allowance, target)
    if not current:
        # Today's allowance means nothing for a closed cycle; summarise it instead.
        hero.html(f'<p class="question">Cycle {m["cycle_start"]:%d %b} to {m["cycle_end"]:%d %b %Y}</p>'
                  f'<p class="past-cycle">You spent {inr(m["burn"])} in this cycle.</p>')
    elif m["has_balance"]:
        hero.html(f'<p class="question">Am I cooked?</p>'
                  f'<h1 class="answer" style="--heat:var(--{HEAT[status]})">{VERDICT[status]}</h1>'
                  f'<p class="allowance">{inr(max(allowance, 0))} a day until {plan_end:%d %b}</p>'
                  f'<p class="allowance-note">{allowance_note(m["balance"], allowance, target)}</p>'
                  + heat_scale(allowance, status, target))
    else:
        with hero.container():
            st.html('<p class="question">Am I cooked?</p>'
                    '<p class="past-cycle">Enter your bank balance to find out.</p>')
            st.page_link("settings.py", label="Set balance", icon=":material/account_balance:")
    outstanding = sum(max(s["cents"] / 100 - s["repaid"], 0)
                      for s in snapshot["shares"] if s["date"] <= str(today) and not s["forgiven"])
    breakdown_month = str(today)[:7] if current else None
    # Net = cash in (credits) − cash out (debits). Poker cash is never split, so payouts
    # count in full; as the bank a losing night shows because payouts exceed buy-ins collected.
    poker_txs = [t for t in m["txs"] if t["category"] == "Poker"
                 and (not breakdown_month or t["date"][:7] == breakdown_month)]
    poker_net = sum(t["amount"] if t["direction"] == "credit" else -t["amount"]
                    for t in poker_txs)
    figures = [
        ("Balance", inr(m["balance"]) if m["has_balance"] else "Not set", "In your account now"),
        ("Food left today", inr(m["food_remaining_today"]), food_caption(m)),
        ("Food savings", inr(m["food_rollover"]), f"{inr(m['food_silo_after_today'])} after today"),
        ("Owed to you", inr(outstanding), "From split bills"),
    ]
    if poker_txs:
        net_str = f"+{inr(poker_net)}" if poker_net > 0 else inr(poker_net)
        figures.append(("Poker", net_str,
                        f"Wins − losses {'this month' if breakdown_month else 'this cycle'}"))
    with top_right:
        st.html('<div class="stat-list">' + "".join(
            f'<div class="stat"><div class="stat-main"><div class="stat-label">{escape(label)}</div>'
            f'<small class="stat-caption">{escape(caption)}</small></div>'
            f'<div class="stat-value">{escape(value)}</div></div>'
            for label, value, caption in figures) + "</div>")
        if poker_txs:
            poker_breakdown(poker_txs, "this month" if breakdown_month else "this cycle")
        manual_transaction_editor(db, today)
    txs = m["txs"]
    # "From savings" purchases are funded by banked savings, not this cycle's budget.
    spending_txs = [t for t in txs if not t["from_savings"]]
    options = snapshot["month_options"]  # newest first; the next entry is the previous cycle
    prev_idx = (options.index(month) + 1) if month in options else len(options)
    prev_month = options[prev_idx] if prev_idx < len(options) else None
    prev_txs, prev_start, prev_end = None, None, None
    if prev_month:
        prev_txs = [t for t in db.get_transactions(prev_month) if not t["from_savings"]]
        prev_start, prev_end = db.get_cycle_dates(prev_month)
    chart_col, category_col = st.columns([2, 1], gap="large")
    with chart_col:
        spending_chart(spending_txs, m, plan_end if current else m["cycle_end"], today,
                       prev_txs, prev_start, prev_end, show_insight=current)
    with category_col:
        category_breakdown(spending_txs, breakdown_month)
    shares_by_tx = {}
    for share in snapshot["shares"]:
        shares_by_tx.setdefault(share["transaction_id"], []).append(share)
    ledger_col, side_col = st.columns([2, 1], gap="large")
    with ledger_col:
        transaction_list(db, txs, shares_by_tx, month, snapshot["merchant_categories"])
    with side_col:
        repayment_editor(db, snapshot["shares"], snapshot["credits"], today)
        if current:
            budget_culprits(spending_txs, m["safe_to_spend"], days, allowance, m["target_daily"],
                            breakdown_month)
        budget_explainer(m, days, allowance)


def spending_chart(txs, m, chart_end, today, prev_txs=None, prev_start=None, prev_end=None,
                   show_insight=True):
    st.subheader("Spending this cycle")
    if txs:
        note = "Money back and refunds are subtracted. The dotted line continues your current pace."
        if prev_txs:
            note += " The faint line is last cycle, for comparison."
        st.caption(note)
        fig = burn_rate_line(pd.DataFrame(txs), m["target_daily"], m["cycle_start"], chart_end, today,
                             balance=m["balance"],
                             prev_txs=pd.DataFrame(prev_txs) if prev_txs else None,
                             prev_start=prev_start, prev_end=prev_end)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        if show_insight and m.get("days_until_broke") is not None:
            broke = today + timedelta(days=int(m["days_until_broke"]))
            st.caption(f"At this pace, your balance runs out around **{broke:%d %b}**.")
    else:
        st.caption("Your spending line appears after your first payment.")


def category_breakdown(txs, month_prefix=None):
    # month_prefix (YYYY-MM) limits the breakdown to one calendar month, so it resets on the 1st.
    if month_prefix:
        txs = [t for t in txs if t["date"][:7] == month_prefix]
    totals = {}
    for tx in txs:
        if tx["direction"] == "debit" and tx["personal_amount"] > 0:
            totals[tx["category"]] = totals.get(tx["category"], 0) + tx["personal_amount"]
    if totals:
        st.subheader("Where it went")
        if month_prefix:
            st.caption(f"{date.fromisoformat(month_prefix + '-01'):%B} so far.")
        total = sum(totals.values())
        st.html("".join(
            f'<div class="category-line"><span>{escape(label)}</span><b>{inr(amount)}</b>'
            f'<small>{amount / total * 100:.0f}%</small></div><div class="category-track">'
            f'<span style="width:{amount / total * 100:.1f}%"></span></div>'
            for label, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)))


def poker_breakdown(poker_txs, scope_label):
    # Derived live from the ledger's transactions, so edits/deletes/reversals show on next rerun.
    by_day = {}
    for t in poker_txs:
        by_day[t["date"]] = by_day.get(t["date"], 0) + (
            t["amount"] if t["direction"] == "credit" else -t["amount"])
    with st.expander(f"Poker, day by day — {scope_label}"):
        st.html("".join(
            f'<div class="category-line"><span>{date.fromisoformat(d):%a, %d %b}</span>'
            f'<b style="color:{"var(--fine)" if net > 0 else "var(--cooked)" if net < 0 else "inherit"}">'
            f'{("+" + inr(net)) if net > 0 else inr(net)}</b></div>'
            for d, net in sorted(by_day.items(), reverse=True)))
        st.caption("Each day's winnings minus losses, bank nights included.")


def debits_to_reach(amounts, safe_to_spend, days, threshold):
    """Fewest of the largest debits whose reversal lifts allowance to threshold; (count, total) or None."""
    total = 0.0
    for i, a in enumerate(sorted(amounts, reverse=True), 1):
        total += a
        if (safe_to_spend + total) / days >= threshold:
            return i, total
    return None


def budget_culprits(spending_txs, safe_to_spend, days, allowance, target, month_prefix=None):
    """The payments that cut your daily budget the most, and what recovering them would restore."""
    if month_prefix:
        spending_txs = [t for t in spending_txs if t["date"][:7] == month_prefix]
    debits = sorted((t for t in spending_txs if t["direction"] == "debit" and t["amount"] > 0),
                    key=lambda t: t["amount"], reverse=True)
    if not debits:
        return
    status = budget_status(allowance, target)
    amounts = [t["amount"] for t in debits]
    rows = 6

    with st.expander("What's cutting your budget", expanded=status == "Cooked"):
        if status == "Comfortable":
            st.caption("You're comfortable — these simply cost the most this cycle.")
        else:
            # Cooked aims for Tight, Tight aims for Comfortable; name the band actually reached.
            goal = debits_to_reach(amounts, safe_to_spend, days, target * 1.25 if status == "Tight" else target)
            if goal:
                k, total = goal
                rows = max(rows, k)  # never cite more reversals than rows shown below
                band = budget_status((safe_to_spend + total) / days, target)
                st.caption(f"Recovering the top {k} ({inr(total)}) — a refund, or collecting what's "
                           f"owed — would lift you to {band}.")
            else:
                st.caption("These cut your budget the most this cycle.")
        for t in debits[:rows]:
            owed = (f" · {inr(t['amount'] - t['personal_amount'])} owed back"
                    if t["personal_amount"] != t["amount"] else "")
            st.html('<div class="category-line">'
                    f'<span>{escape(t["merchant"])}'
                    f'<small style="display:block;color:var(--muted)">{escape(t["category"])}{owed}</small>'
                    f'</span><b>{inr(t["amount"])}</b><small>{inr(t["amount"] / days)}/day</small></div>')


def budget_explainer(m, days, allowance):
    with st.expander("How this is worked out"):
        target = m["target_daily"]
        st.write(f"Daily amount: {inr(m['balance'], 2)} balance ÷ {days} days = {inr(allowance, 2)}.")
        st.write(f"Not yet: at least {inr(target * 1.25, 2)} a day. "
                 f"Almost: {inr(target)} to {inr(target * 1.25, 2)}. "
                 f"Yes: under {inr(target)}, your daily food budget.")
        st.caption(f"This cycle runs {m['cycle_start']:%d %b} to {m['cycle_end']:%d %b %Y}. "
                   "Food savings are part of your balance, not extra cash. "
                   "Money you're owed counts only once it's paid back. "
                   "Pocket money and split repayments are left out of the spending line.")


def render_settings(db):
    today = db.today_ist()
    snapshot = db.load_dashboard(today)
    st.title("Settings")
    st.caption("Balance, categories, and your cycle. Everything here saves straight away.")
    if "notice" in st.session_state:
        st.success(st.session_state.pop("notice"))

    st.subheader("Balance")
    st.caption("Enter what your bank app shows. New payments are added on top of it.")
    with st.form("balance_adjustment", border=False):
        balance = st.number_input("Current balance (₹)", value=float(snapshot["metrics"]["balance"]),
                                  step=100.0, format="%.2f")
        if st.form_submit_button("Update balance"):
            db.set_balance(balance)
            st.session_state["notice"] = "Balance updated."
            st.rerun()

    st.divider()
    st.subheader("Food budget")
    st.caption("Your daily food target. The whole “cooked” verdict is measured against it.")
    with st.form("food_budget", border=False):
        target = st.number_input("Daily food budget (₹)", min_value=1.0, step=50.0, format="%.2f",
                                 value=float(snapshot["metrics"]["target_daily"]))
        if st.form_submit_button("Update food budget"):
            db.set_setting("target_daily", str(target))
            st.session_state["notice"] = "Food budget updated."
            st.rerun()

    st.divider()
    category_manager(db)

    st.divider()
    st.subheader("Cycle & savings")
    with st.expander("Pocket-money cycle", expanded=not snapshot["receipt_dates"]):
        st.caption("Your cycle starts on the date of a received credit marked Pocket Money.")
        credits = {t["id"]: t for t in snapshot["credits"]
                   if not t["is_repayment"] and t["category"] != "Pocket Money"}
        if credits:
            credit_id = st.selectbox("Received payment", list(credits),
                                    format_func=lambda i: f"{credits[i]['date']} · {credits[i]['merchant']} · {inr(credits[i]['amount'])}")
            if st.button("Mark as pocket money"):
                try:
                    db.update_category(credit_id, "Pocket Money")
                    st.session_state["notice"] = "Marked as pocket money. A new cycle starts on that date."
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            st.caption("Add the received payment on Overview as a credit with category Pocket Money.")
    with st.expander("Food savings"):
        st.caption("Every day you spend under your food budget, the difference is saved here. "
                   "Resetting sets it to zero from today.")
        if st.button("Reset food savings"):
            db.set_food_silo_zero()
            st.session_state["notice"] = "Food savings reset."
            st.rerun()
    st.divider()
    with st.expander(f"Bank texts I couldn't read ({len(snapshot['unparsed'])})"):
        if not snapshot["unparsed"]:
            st.caption("Every bank text so far was understood.")
        else:
            st.caption("Add these on Overview yourself, then clear them.")
        for sms in snapshot["unparsed"]:
            st.code(sms["raw"], language=None)
            if st.button("Clear", key=f"u_admin_{sms['id']}"):
                db.delete_unparsed(sms["id"])
                st.rerun()

    st.divider()
    st.subheader("Export")
    st.caption("Every transaction as a spreadsheet, for backup or a closer look.")
    st.download_button("Download transactions (CSV)", file_name="transactions.csv", mime="text/csv",
                       data=pd.DataFrame(db.all_transactions()).to_csv(index=False))

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



def transaction_editor(db, t, cat_options, existing_splits, rules):
    # Rendered inline only for the row being edited, so the ledger builds 1 editor, not 25.
    with st.container(border=True):
        st.caption(f"Editing {t['merchant']}")
        merchant = st.text_input("Vendor or person", value=t['merchant'], key=f"merchant_{t['id']}")
        new_cat = st.selectbox("Category", options=cat_options,
                              index=cat_options.index(t['category']), key=f"cat_{t['id']}")
        remember = None
        from_savings = None
        if t['direction'] == 'debit':
            rule = rules.get(db.normalize_merchant(t['merchant']))
            remember_checked = st.checkbox("Use for future payments to this vendor",
                                           value=bool(rule), key=f"remember_{t['id']}")
            st.caption(f"Saved default: {rule}. Uncheck to remove it." if rule
                       else "Matches this vendor name, ignoring case and extra spaces.")
            if remember_checked or rule:
                remember = remember_checked
            from_savings = st.checkbox("Pay from savings (big one-off)", value=bool(t['from_savings']),
                                       key=f"fromsav_{t['id']}",
                                       help="Funded by your Food savings: kept out of your daily "
                                            "budget and spending charts, and drawn from savings.")
        if st.button("Save changes", key=f"save_{t['id']}", type="primary", width="stretch"):
            try:
                db.edit_transaction(t['id'], merchant, new_cat, remember, from_savings)
                st.session_state['notice'] = 'Transaction updated. Vendor rule saved.' if remember else 'Transaction updated.'
                st.session_state.pop('ledger_edit', None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        refund = t['direction'] == 'debit'
        col_del, col_rev = st.columns(2)
        with col_del:
            if st.button("Delete", key=f"del_{t['id']}", width="stretch"):
                try:
                    db.delete_transaction(t['id'])
                    st.session_state['notice'] = 'Transaction deleted.'
                    st.session_state.pop('ledger_edit', None)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with col_rev:
            if st.button("Reverse (refund)" if refund else "Reverse",
                         key=f"reverse_{t['id']}", width="stretch",
                         help="Adds the opposite entry to cancel this out — e.g. a failed payment "
                              "credited back. Both rows stay and net to zero."):
                try:
                    db.reverse_transaction(t['id'])
                    st.session_state['notice'] = 'Refund added.' if refund else 'Reversal added.'
                    st.session_state.pop('ledger_edit', None)
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
    with st.popover("Add transaction", icon=":material/add:", width="stretch"):
        m_date = st.date_input("Transaction date", value=today, max_value=today)
        m_merchant = st.text_input("Merchant", placeholder="Who you paid, or who paid you")

        # Auto-tagging logic
        default_cat = db.get_categories()[0]
        if m_merchant:
            mapped_cat = db.get_merchant_category(m_merchant)
            if mapped_cat and mapped_cat in db.get_categories():
                default_cat = mapped_cat

        m_amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
        m_dir = st.radio("Type", ["debit", "credit"], horizontal=True,
                         format_func={"debit": "I paid", "credit": "I received"}.get)
        m_cat = st.selectbox("Category", options=db.get_categories(), index=db.get_categories().index(default_cat))
        # Vendor rules only ever apply to payments, so don't offer one for received money.
        auto_tag = m_dir == "debit" and st.checkbox("Use this category for future payments here")
        m_from_savings = m_dir == "debit" and st.checkbox(
            "Pay from savings (big one-off)",
            help="Funded by your Food savings: kept out of your daily budget and spending charts, "
                 "and drawn from savings.")

        manual_splits = split_fields(db, m_amount, 'manual') if m_dir == 'debit' else []
        if st.button("Log transaction", width="stretch", disabled=manual_splits is None):
            if m_merchant and m_amount > 0:
                try:
                    if db.add_transaction(m_date, m_merchant, m_amount, direction=m_dir, category=m_cat, splits=manual_splits, apply_merchant_rule=False, from_savings=bool(m_from_savings)):
                        if auto_tag:
                            db.set_merchant_category(m_merchant, m_cat)
                        st.session_state["notice"] = "Transaction added."
                        st.rerun()
                    else:
                        st.error("Could not save this transaction.")
                except ValueError as exc:
                    st.error(str(exc))
            else:
                st.error("Enter a merchant and an amount.")


@st.fragment
def repayment_editor(db, shares, received_credits, today):
    with st.expander("Money owed to me", expanded=False):
        outstanding = [s for s in shares if s['date'] <= str(today) and not s['forgiven']
                       and s['cents'] - round(s['repaid'] * 100) > 0]
        st.metric("Outstanding across all cycles", inr(sum(s['cents'] / 100 - s['repaid'] for s in outstanding), 2))
        st.caption("Link repayments already in your records to avoid adding the money twice.")
        if not outstanding:
            st.caption("Nobody owes you anything. Split a payment from its edit menu to track it here.")
        else:
            with st.popover("Reset owed to ₹0"):
                st.caption("Stops tracking everything currently owed. Your balance, income, and spending "
                           "don't change — this just clears the list.")
                if st.button("Clear everything owed", type="primary", key="forgive_all"):
                    db.forgive_all_owed()
                    st.session_state["notice"] = "Cleared — nobody is marked as owing you now."
                    st.rerun()
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
            query = st.text_input('Search vendor or person', placeholder='Search', label_visibility='collapsed', key='ledger_search')
        base_cats = list(db.get_categories())  # one DB read, not two per rerun
        cat_options = base_cats + sorted({t['category'] for t in txs if t['category'] not in base_cats})
        with category:
            selected = st.selectbox('Filter by category', ['All categories'] + cat_options, label_visibility='collapsed', key='ledger_category')
        matches = [t for t in txs if query.casefold().strip() in t['merchant'].casefold()
                   and (selected == 'All categories' or t['category'] == selected)]
        sorted_txs = sorted(matches, key=lambda t: (t['date'], t['id']), reverse=True)
        if not sorted_txs:
            st.caption('Nothing matches. Clear the search or pick another category.' if txs
                       else 'No transactions yet. Payments from bank texts show up here, or add one above.')
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
            if t['date'] != previous_day:
                st.html(f'<p class="day-label">{date.fromisoformat(t["date"]):%A, %d %b}</p>')
                previous_day = t['date']
            ledger_row(db, t, cat_options, shares_by_tx.get(t['id'], []), rules)
        st.caption(f'Showing {start + 1}–{min(start + page_size, len(sorted_txs))} of {len(sorted_txs)} transactions')


@st.fragment
def ledger_row(db, t, cat_options, existing_splits, rules):
    # Each row is its own fragment: opening/closing the editor reruns only this row, not all 25.
    sign = '+' if t['direction'] == 'credit' else '−'
    tone = 'credit' if t['direction'] == 'credit' else 'debit'
    detail = ''
    if t['from_savings']:
        detail = 'From savings'
    elif t['personal_amount'] != t['amount']:
        detail = f"Your share {inr(t['personal_amount'], 2)}"
    elif t['is_repayment']:
        detail = 'Split repayment'
    elif t['direction'] == 'debit' and db.normalize_merchant(t['merchant']) in rules:
        detail = 'Vendor rule saved'
    with st.container(key=f"ledger_row_{t['id']}"):
        row, edit = st.columns([9, 1.3], vertical_alignment='center')
        row.markdown(f'<div class="ledger-row"><div class="row-vendor">'
                     f'<span title="{escape(t["merchant"], quote=True)}">{escape(t["merchant"])}</span>'
                     f'<small>{escape(t["category"])}{(" · " + escape(detail)) if detail else ""}</small></div>'
                     f'<span class="row-amount {tone}">{sign}{inr(t["amount"], 2)}</span></div>', unsafe_allow_html=True)
        if edit.button('Edit', icon=':material/edit:', key=f'edit_{t["id"]}',
                       help='Edit, delete or reverse this transaction'):
            st.session_state['ledger_edit'] = (
                None if st.session_state.get('ledger_edit') == t['id'] else t['id'])
        if st.session_state.get('ledger_edit') == t['id']:
            transaction_editor(db, t, cat_options, existing_splits, rules)


