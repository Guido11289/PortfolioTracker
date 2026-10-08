"""Bouwt een Plotly-figuur uit de output van analysis/dividends.py.

Bewust géén berekeningen hier — alleen mapping van data naar een chart-spec.
"""
import plotly.graph_objects as go

_MONTHS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]


def build_monthly_dividend_figure(months: list[dict], year: int) -> dict:
    """months = output van compute_monthly_dividends() (12 rijen). Geeft
    {"data": [...], "layout": {...}} terug voor `Plotly.react(el, fig.data, fig.layout)`."""
    fig = go.Figure(go.Bar(
        x=_MONTHS,
        y=[m["total_eur"] for m in months],
        marker_color="#667eea",
        hovertemplate="%{x}<br>€%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Dividend per maand — {year}",
        yaxis=dict(title="EUR", tickprefix="€"),
        margin=dict(t=50, b=30, l=60, r=20),
    )
    return fig.to_dict()
