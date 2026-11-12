"""Presentation helpers for Am I cooked?"""
from datetime import date
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# Clean restrained dark, dark-only. One violet accent used sparingly; solid, legible semantic
# colors for the verdict (emerald -> amber -> rose). accent2 is a calm cyan for chart data only.
PALETTE = {
    "dark": dict(ink="#F3F4F6", muted="#9BA1AC", line="rgba(255,255,255,.09)",
                 fine="#34D399", tight="#F5B544", cooked="#FB5E73",
                 accent="#7C5CFF", accent2="#5AC8E0", bg="#0C0D12", surface="#16181F"),
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


def _net_daily(frame):
    """Per-day net spend: personal debits minus settled non-pocket-money, non-repayment credits."""
    frame = frame.copy()
    if 'personal_amount' in frame:
        frame['amount'] = frame['personal_amount']
    if 'direction' in frame:
        credits = frame['direction'] == 'credit'
        offsets = credits & (frame['category'] != 'Pocket Money') & (frame['status'] == 'settled')
        if 'is_repayment' in frame:
            offsets &= ~frame['is_repayment'].astype(bool)
        frame.loc[credits & ~offsets, 'amount'] = 0
        frame.loc[offsets, 'amount'] = -frame.loc[offsets, 'amount']
    return frame.assign(date=pd.to_datetime(frame['date'])).groupby('date')['amount'].sum()


def burn_rate_line(txs, target_daily, cycle_start, cycle_end, today, balance=None,
                   prev_txs=None, prev_start=None, prev_end=None) -> go.Figure:
    """This cycle's cumulative net spend, last cycle overlaid, and the current-pace forecast."""
    if txs.empty:
        return go.Figure()

    dates = pd.date_range(cycle_start, min(today, cycle_end), freq='D')
    cumulative = _net_daily(txs).reindex(dates, fill_value=0).cumsum()

    fig = go.Figure()
    colors = palette()
    muted, accent, cyan = colors["muted"], colors["accent"], colors["accent2"]

    # Last cycle, aligned day-by-day onto this cycle's axis so the two paces sit together.
    full_dates = pd.date_range(cycle_start, cycle_end, freq='D')
    if prev_txs is not None and not prev_txs.empty and prev_start is not None:
        prev_range = pd.date_range(prev_start, prev_end, freq='D')
        prev_cum = _net_daily(prev_txs).reindex(prev_range, fill_value=0).cumsum().to_numpy()
        n = min(len(prev_cum), len(full_dates))
        if n:
            fig.add_trace(go.Scatter(
                x=full_dates[:n], y=prev_cum[:n], mode='lines', name='Last cycle',
                line=dict(color='rgba(90,200,224,0.5)', width=1.5),
                hovertemplate="Last cycle: ₹%{y:,.0f}<extra></extra>"))

    # This cycle's actual spend — violet with a quiet fill down to zero.
    fig.add_trace(go.Scatter(
        x=dates, y=cumulative, mode='lines', name='This cycle',
        line=dict(color=accent, width=2.5, shape='hv'),
        fill='tozeroy', fillcolor='rgba(124,92,255,0.08)',
        hovertemplate="Net spend: ₹%{y:,.0f}<extra></extra>"))

    if balance is not None and today < cycle_end and today >= cycle_start:
        days_observed = max(len(dates), 1)
        daily_average = float(cumulative.iloc[-1]) / days_observed
        future = pd.date_range(today, cycle_end, freq='D')
        current = float(cumulative.iloc[-1])
        fig.add_trace(go.Scatter(
            x=future, y=[current + i * daily_average for i in range(len(future))],
            mode='lines', name='At current pace',
            line=dict(color=muted, width=1.5, dash='dot'),
            hovertemplate="Projected spend: ₹%{y:,.0f}<extra></extra>"))

    if cycle_start <= today <= cycle_end:
        fig.add_vline(x=pd.Timestamp(today).timestamp() * 1000, line_width=1,
                      line_dash="dot", line_color=cyan)
    fig.update_layout(
        template="plotly_dark",
        font=dict(family="'Schibsted Grotesk', sans-serif", color=muted, size=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=260, margin=dict(l=0, r=8, t=34, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, xanchor="left",
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        dragmode=False,
        xaxis=dict(showgrid=False, showline=False, zeroline=False, tickformat="%d %b", nticks=5, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.12)", showline=False,
                   zeroline=False, tickformat=",d", tickprefix="₹", nticks=4, fixedrange=True),
    )
    return fig
