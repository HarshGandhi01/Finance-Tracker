"""Presentation helpers for Am I Cooked? No DB or business logic here."""
from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

BG = "#0A0A0C"
INK = "#F2F2F4"
MUTED = "#8B8B94"
LINE = "#232329"
FONT_DISPLAY = "Bricolage Grotesque, IBM Plex Sans, sans-serif"
FONT_BODY = "IBM Plex Sans, system-ui, sans-serif"

# First (largest) category gets the accent; the rest cycle through distinct, low-saturation hues.
SERIES = ["#7C83FF", "#3DBE8B", "#E8A93A", "#F0584F", "#4FB7E5", "#B28CFF", "#8B8B94"]

pio.templates["cooked_dark"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family=FONT_BODY, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        hoverlabel=dict(bgcolor="#1C222C", bordercolor=LINE, font=dict(family=FONT_BODY, color=INK)),
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
