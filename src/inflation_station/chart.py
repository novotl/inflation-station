"""Draws a Timeline as a self-contained interactive HTML file (plotly, with plotly.js inlined)."""

from datetime import timedelta
from typing import TYPE_CHECKING

import plotly.graph_objects as go

from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    from inflation_station.valuation import Hurdle, Timeline

CHART_NAME = "chart.html"
HOVER_CZK = "%{y:,.2f} CZK"
# How each price index series' published hurdle is drawn. Every estimated part is dotted; the colours tell them apart.
HURDLE_LINES = {CSU_CPI: {"color": "black", "dash": "solid"}, EUROSTAT_HICP: {"color": "dimgray", "dash": "dash"}}


def write_chart(timeline: Timeline, data_dir: Path) -> Path:
    """Write the chart into `data_dir` and return its path. Doesn't open a browser."""
    figure = go.Figure(layout={"title": "Portfolio", "yaxis_title": "CZK", "hovermode": "x unified"})
    if timeline.portfolio_value is not None:
        figure.add_scatter(x=timeline.dates, y=_floats(timeline.portfolio_value), name="Portfolio value")
    # Each fund is a line of its own, which a click on the legend shows or hides.
    for isin, values in timeline.fund_values.items():
        figure.add_scatter(x=timeline.dates, y=_floats(values), name=timeline.fund_names[isin])
    figure.add_scatter(x=timeline.dates, y=_floats(timeline.amount_invested), name="Amount invested", line_shape="hv")
    for series, hurdle in timeline.hurdles.items():
        _add_hurdle(figure, timeline.dates, hurdle, series)
    figure.update_traces(hovertemplate=HOVER_CZK)
    path = data_dir / CHART_NAME
    figure.write_html(path, include_plotlyjs=True)
    return path


def _add_hurdle(figure: go.Figure, dates: Sequence[date], hurdle: Hurdle, series: str) -> None:
    """The published part in the series' line; the estimated part dotted, starting where the published part ends."""
    line = HURDLE_LINES[series]
    name = f"Inflation hurdle ({NAMES[series]})"
    published = [n for n, d in enumerate(dates) if d < hurdle.estimated_from]
    if published:
        figure.add_scatter(
            x=[dates[n] for n in published],
            y=_floats([hurdle.values[n] for n in published]),
            name=name,
            legendgroup=name,
            line=line,
        )
    estimated = [n for n, d in enumerate(dates) if d >= hurdle.estimated_from - timedelta(days=1)]
    if estimated:
        figure.add_scatter(
            x=[dates[n] for n in estimated],
            y=_floats([hurdle.values[n] for n in estimated]),
            name=f"Inflation hurdle ({NAMES[series]}, estimated)",
            legendgroup=name,
            line={**line, "dash": "dot"},
        )


def _floats(amounts: Sequence[Decimal | None]) -> list[float | None]:
    """Plotly takes floats; None leaves a gap in the line."""
    return [None if amount is None else float(amount) for amount in amounts]
