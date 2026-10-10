"""Draws a Timeline as a self-contained interactive HTML file (plotly, with plotly.js inlined)."""

from typing import TYPE_CHECKING

import plotly.graph_objects as go

if TYPE_CHECKING:
    from pathlib import Path

    from inflation_station.valuation import Timeline

CHART_NAME = "chart.html"


def write_chart(timeline: Timeline, data_dir: Path) -> Path:
    """Write the chart into `data_dir` and return its path. Doesn't open a browser."""
    figure = go.Figure(
        go.Scatter(
            x=timeline.dates,
            y=[float(amount) for amount in timeline.amount_invested],
            name="Amount invested",
            line_shape="hv",
            hovertemplate="%{y:,.2f} CZK",
        ),
        layout={"title": "Amount invested", "yaxis_title": "CZK", "hovermode": "x unified"},
    )
    path = data_dir / CHART_NAME
    figure.write_html(path, include_plotlyjs=True)
    return path
