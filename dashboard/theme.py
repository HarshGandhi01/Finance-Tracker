"""Presentation helpers for Am I cooked?"""
from datetime import date
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# Neon Ledger: dark-only. Heat runs mint -> amber -> hot pink; violet/cyan carry the brand.
PALETTE = {
    "dark": dict(ink="#F2F0FF", muted="#8B86A8", line="rgba(242,240,255,.12)",
                 fine="#2EE6A6", tight="#FFC23C", cooked="#FF3D7F",
                 accent="#7C5CFF", accent2="#35E7FF", bg="#0B0A14", surface="#15131F"),
}
PALETTE["light"] = PALETTE["dark"]  # dark-only: never switch to a light palette


def palette():
    return PALETTE["dark"]


def apply_theme():
    css = (Path(__file__).parent / "assets/styles.css").read_text(encoding="utf-8")
    tokens = "".join(f"--{k}:{v};" for k, v in palette().items())
    st.markdown(f"<style>:root{{{tokens}}}{css}</style>", unsafe_allow_html=True)


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

    fig = go.Figure()
    dark = True
    colors = palette()
    muted, accent, cyan = colors["muted"], colors["accent"], colors["accent2"]

    # Add actual spend line — violet with a soft neon fill down to zero.
    fig.add_trace(go.Scatter(
        x=daily_spend['date'],
        y=daily_spend['cumulative'],
        mode='lines',
        name='Net Spend',
        line=dict(color=accent, width=2.75, shape='hv'),
        fill='tozeroy', fillcolor='rgba(124,92,255,0.12)',
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
            line=dict(color=muted, width=1.5, dash='dot'),
            hovertemplate="Projected spend: ₹%{y:,.0f}<extra></extra>",
        ))

    if cycle_start <= today <= cycle_end:
        fig.add_vline(x=pd.Timestamp(today).timestamp() * 1000, line_width=1,
                      line_dash="dot", line_color=cyan)
        fig.add_annotation(x=pd.Timestamp(today), y=1, yref="paper", text="Today",
                           showarrow=False, font=dict(size=11, color=cyan), yshift=12)
    fig.update_layout(
        template="plotly_dark" if dark else "plotly_white",
        font=dict(family="'Schibsted Grotesk', sans-serif", color=muted, size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=260, margin=dict(l=0, r=8, t=30, b=0), showlegend=False,
        dragmode=False,
        xaxis=dict(showgrid=False, showline=False, zeroline=False, tickformat="%d %b", nticks=5, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.12)", showline=False,
                   zeroline=False, tickformat=",d", tickprefix="₹", nticks=4, fixedrange=True),
    )
    return fig
