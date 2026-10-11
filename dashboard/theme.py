"""Presentation helpers for Am I Cooked? No DB or business logic here."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

BG = "#101416"
INK = "#EDF0F2"
MUTED = "#A1ADB4"
LINE = "#303A40"
FONT_DISPLAY = "Arial, sans-serif"
FONT_BODY = "Arial, sans-serif"

# Restrained financial workspace palette
SERIES = ["#83BDA3", "#82988D", "#B7C9BE", "#4E7461", "#98AAA0", "#A1ADB4", "#303A40"]

pio.templates["cooked_dark"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family=FONT_BODY, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        hoverlabel=dict(bgcolor="#191F22", bordercolor=LINE, font=dict(family=FONT_BODY, color=INK)),
    )
)
pio.templates.default = "cooked_dark"

_HERE = Path(__file__).parent
_CSS = next((p for p in (_HERE / "assets" / "styles.css", _HERE / "styles.css") if p.exists()), None)


def apply_theme() -> None:
    """Inject the stylesheet. Call once, right after st.set_page_config."""
    if _CSS is not None:
        st.markdown(f"<style>{_CSS.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def inr(x: float, decimals: int = 0) -> str:
    """Rupee formatting with Indian grouping (1,23,456)."""
    neg = x < 0
    whole, _, frac = f"{abs(x):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = "₹" + whole + (f".{frac}" if frac else "")
    return "-" + out if neg else out


def next_25th(today: date) -> date:
    """The next future 25th to use as the editable money-date default."""
    year, month = today.year, today.month
    if today.day >= 25:
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return date(year, month, 25)


def spending_donut(cat_sums, inner_label="spent") -> go.Figure:
    """Donut of debit totals by category (a pandas Series, sorted descending)."""
    total = float(cat_sums.sum())
    fig = go.Figure(
        go.Pie(
            labels=list(cat_sums.index),
            values=list(cat_sums.values),
            hole=0.76,
            sort=False,
            marker=dict(colors=SERIES[: len(cat_sums)] or SERIES, line=dict(color=BG, width=2)),
            textinfo="none",
            hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>",
        )
    )
    fig.add_annotation(
        text=f"<span style='font-size:24px;font-family:{FONT_DISPLAY};font-weight:600'>{inr(total)}</span>"
        f"<br><span style='font-size:11px;color:{MUTED}'>{inner_label}</span>",
        showarrow=False,
    )
    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=8, b=0),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.03, font=dict(color=MUTED, size=11)),
    )
    return fig


def burn_rate_line(txs, target_daily, cycle_start, cycle_end, today, balance=None) -> go.Figure:
    """Cumulative net spending, cash budget pace, and current spending forecast."""
    if txs.empty:
        return go.Figure()

    # Group by date and calculate cumulative sum
    txs = txs.copy()
    if 'personal_amount' in txs:
        txs['amount'] = txs['personal_amount']
    if 'direction' in txs:
        credits = txs['direction'] == 'credit'
        offsets = credits & (txs['category'] != 'Pocket Money') & (txs['status'] == 'settled')
        if 'is_repayment' in txs:
            offsets &= ~txs['is_repayment'].astype(bool)
        txs.loc[credits & ~offsets, 'amount'] = 0
        txs.loc[offsets, 'amount'] = -txs.loc[offsets, 'amount']
    amounts = txs.assign(date=pd.to_datetime(txs['date'])).groupby('date')['amount'].sum()
    dates = pd.date_range(cycle_start, min(today, cycle_end), freq='D')
    daily_spend = amounts.reindex(dates, fill_value=0).rename_axis('date').reset_index()
    daily_spend['cumulative'] = daily_spend['amount'].cumsum()

    # Cash already spent plus cash on hand is the cycle's available budget.
    # Recalculate its pace for the selected end date and the latest balance.
    target_dates = pd.date_range(cycle_start, cycle_end, freq='D')
    target_total = (float(daily_spend['cumulative'].iloc[-1]) + balance) if balance is not None else None
    pace = target_total / len(target_dates) if target_total is not None else target_daily
    target_df = pd.DataFrame({'date': target_dates,
                              'target': [(i + 1) * pace for i in range(len(target_dates))]})

    fig = go.Figure()

    # Add target line
    fig.add_trace(go.Scatter(
        x=target_df['date'],
        y=target_df['target'],
        mode='lines',
        name='Cash budget pace' if balance is not None else 'Target',
        line=dict(color=MUTED, width=2, dash='dash'),
        hovertemplate="Budget pace: ₹%{y:,.0f}<extra></extra>"
    ))

    # Add actual spend line
    fig.add_trace(go.Scatter(
        x=daily_spend['date'],
        y=daily_spend['cumulative'],
        mode='lines+markers',
        name='Net Spend',
        line=dict(color=SERIES[0], width=3),
        marker=dict(size=6, color=SERIES[0]),
        hovertemplate="Net spend: ₹%{y:,.0f}<extra></extra>"
    ))

    if balance is not None and today < cycle_end and today >= cycle_start:
        days_observed = max(len(daily_spend), 1)
        daily_average = float(daily_spend['cumulative'].iloc[-1]) / days_observed
        future = pd.date_range(today, cycle_end, freq='D')
        current = float(daily_spend['cumulative'].iloc[-1])
        fig.add_trace(go.Scatter(
            x=future,
            y=[current + i * daily_average for i in range(len(future))],
            mode='lines',
            name='At current pace',
            line=dict(color='#D6AD78', width=2, dash='dot'),
            hovertemplate="Projected spend: ₹%{y:,.0f}<extra></extra>",
        ))

    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.1, font=dict(color=MUTED, size=11)),
        xaxis=dict(showgrid=False, showline=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor=LINE, showline=False, zeroline=False, tickformat=",d", tickprefix="₹")
    )
    return fig
