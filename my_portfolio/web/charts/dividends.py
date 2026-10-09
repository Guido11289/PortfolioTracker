"""Bouwt een Plotly-figuur uit de output van analysis/dividends.py.

Bewust géén berekeningen hier — alleen mapping van data naar een chart-spec.
"""
import plotly.graph_objects as go

_MONTHS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]


def build_monthly_dividend_figure(
    months: list[dict],
    forecast: list[dict],
    year: int,
) -> dict:
    """Werkelijk en verwacht dividend per maand.

    `months` = output van compute_monthly_dividends()
    `forecast` = output van compute_monthly_dividend_forecast()

    Geeft {"data": [...], "layout": {...}} terug voor
    Plotly.react(el, fig.data, fig.layout).
    """

    # ------------------------------------------------------------
    # Werkelijk dividend
    # ------------------------------------------------------------
    actual_hover_text = []

    for m in months:
        lines = [
            f"<b>{_MONTHS[m['month'] - 1]}</b>",
            f"Totaal: €{m['total_eur']:,.2f}",
        ]

        for payment in sorted(
            m.get("payments", []),
            key=lambda p: p["amount_eur"],
            reverse=True,
        ):
            lines.append(
                f"{payment['name']}: €{payment['amount_eur']:,.2f}"
            )

        actual_hover_text.append("<br>".join(lines))

    # ------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------
    forecast_hover_text = []

    for m in forecast:
        lines = [
            f"<b>{_MONTHS[m['month'] - 1]}</b>",
            "<b>Verwachting</b>",
            f"Totaal: €{m['total_eur']:,.2f}",
        ]

        for payment in sorted(
            m.get("payments", []),
            key=lambda p: p["amount_eur"],
            reverse=True,
        ):
            lines.append(
                f"{payment['name']}: €{payment['amount_eur']:,.2f}"
            )

        forecast_hover_text.append("<br>".join(lines))

    # ------------------------------------------------------------
    # Grafiek
    # ------------------------------------------------------------
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=_MONTHS,
        y=[m["total_eur"] for m in months],
        name="Werkelijk",
        marker_color="#667eea",
        hovertemplate="%{customdata}<extra></extra>",
        customdata=actual_hover_text,
    ))

    fig.add_trace(go.Bar(
        x=_MONTHS,
        y=[m["total_eur"] for m in forecast],
        name="Verwachting",
        marker_color="#a5b4fc",
        opacity=0.65,
        hovertemplate="%{customdata}<extra></extra>",
        customdata=forecast_hover_text,
    ))

    fig.update_layout(
        title=f"Dividend per maand — {year}",
        yaxis=dict(
            title="EUR",
            tickprefix="€",
        ),
        margin=dict(
            t=50,
            b=30,
            l=60,
            r=20,
        ),
        barmode="group",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig.to_dict()
