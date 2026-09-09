"""Bouwt een Plotly-figuur uit de output van analysis/sector_allocation.py.

Bewust géén berekeningen hier — alleen mapping van data naar een chart-spec.
"""
import plotly.graph_objects as go


def build_sector_allocation_figure(allocation: list[dict], title: str = "Sectorweging portfolio") -> dict:
    """allocation = output van compute_sector_allocation(). Geeft een dict
    {"data": [...], "layout": {...}} terug, direct bruikbaar door
    `Plotly.newPlot(el, fig.data, fig.layout)` in de browser."""

    if not allocation:
        fig = go.Figure()
        fig.update_layout(title=f"{title} — geen holdings om te tonen")
        return fig.to_dict()

    fig = go.Figure(
        data=[
            go.Pie(
                labels=[row["sector"] for row in allocation],
                values=[row["value_eur"] for row in allocation],
                hovertemplate="%{label}<br>€%{value:,.2f} (%{percent})<extra></extra>",
            )
        ]
    )
    fig.update_layout(title=title, margin=dict(t=50, b=20, l=20, r=20))
    return fig.to_dict()
