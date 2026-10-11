"""Draws a Timeline as a self-contained interactive HTML file (plotly, with plotly.js inlined)."""

from datetime import timedelta
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING

import plotly.graph_objects as go

from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES
from inflation_station.valuation import CZK

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from inflation_station.valuation import Hurdle, Timeline

CHART_NAME = "chart.html"
HOVER_CZK = "%{y:,.2f} CZK"
PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Portfolio</title></head>
<body>
{body}
</body>
</html>
"""
# How each price index series' published hurdle is drawn. Every estimated part is dotted; the colours tell them apart.
HURDLE_LINES = {CSU_CPI: {"color": "black", "dash": "solid"}, EUROSTAT_HICP: {"color": "dimgray", "dash": "dash"}}


def write_chart(timeline: Timeline, data_dir: Path) -> Path:
    """Write the chart into `data_dir` and return its path. Doesn't open a browser.

    The overall chart comes first, then a section per fund, largest CZK value on the last day first.
    """
    # plotly.js is inlined once, with the first chart; the rest use it.
    parts = [_overall(timeline).to_html(full_html=False, include_plotlyjs=True)]
    parts += [_fund_section(timeline, isin) for isin in _by_last_value(timeline)]
    path = data_dir / CHART_NAME
    path.write_text(PAGE.format(body="\n".join(parts)), encoding="utf-8")
    return path


def _overall(timeline: Timeline) -> go.Figure:
    figure = go.Figure(layout={"title": "Portfolio", "yaxis_title": "CZK", "hovermode": "x unified"})
    if timeline.portfolio_value is not None:
        figure.add_scatter(x=timeline.dates, y=_floats(timeline.portfolio_value), name="Portfolio value")
    # Each fund is a line of its own, which a click on the legend shows or hides.
    for isin, values in timeline.fund_values.items():
        customdata, hovertemplate = _fund_hover(timeline, isin)
        figure.add_scatter(
            x=timeline.dates,
            y=_floats(values),
            name=timeline.fund_names[isin],
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    figure.add_scatter(x=timeline.dates, y=_floats(timeline.amount_invested), name="Amount invested", line_shape="hv")
    for series, hurdle in timeline.hurdles.items():
        _add_hurdle(figure, timeline.dates, hurdle, series)
    # Every line but the funds', which have their own hover, shows just its CZK value.
    figure.update_traces(hovertemplate=HOVER_CZK, selector=lambda trace: trace.hovertemplate is None)
    return figure


def _by_last_value(timeline: Timeline) -> list[str]:
    """Every fund purchased, largest CZK value on the last day first; funds with no value that day come last."""

    def key(isin: str) -> tuple[bool, Decimal]:
        last = timeline.fund_values[isin][-1] if isin in timeline.fund_values else None
        return (True, Decimal(0)) if last is None else (False, -last)

    return sorted(timeline.units_held, key=key)


def _fund_section(timeline: Timeline, isin: str) -> str:
    """The fund's heading, why it can't be valued if it can't, and its chart: all in CZK."""
    currency = timeline.fund_currencies.get(isin, timeline.purchase_currencies[isin])
    heading = f"{timeline.fund_names[isin]} · {isin} · priced in {currency}"
    figure = go.Figure(layout={"yaxis_title": "CZK", "hovermode": "x unified"})
    if isin in timeline.fund_values:
        customdata, hovertemplate = _fund_hover(timeline, isin)
        figure.add_scatter(
            x=timeline.dates,
            y=_floats(timeline.fund_values[isin]),
            name="Value",
            customdata=customdata,
            hovertemplate=hovertemplate,
        )
    # With no value line to show them, the units held go on the amount invested.
    units = (
        {
            "customdata": [[_units(units)] for units in timeline.units_held[isin]],
            "hovertemplate": f"{HOVER_CZK} · %{{customdata[0]}} units",
        }
        if isin in timeline.not_valued
        else {}
    )
    figure.add_scatter(
        x=timeline.dates,
        y=_floats(timeline.fund_amount_invested[isin]),
        name="Amount invested",
        line_shape="hv",
        **units,
    )
    for series, hurdle in timeline.fund_hurdles[isin].items():
        _add_hurdle(figure, timeline.dates, hurdle, series)
    figure.update_traces(hovertemplate=HOVER_CZK, selector=lambda trace: trace.hovertemplate is None)
    note = f'<p class="note">Not valued: {escape(timeline.not_valued[isin])}</p>' if isin in timeline.not_valued else ""
    return (
        f'<section class="fund"><h2>{escape(heading)}</h2>{note}'
        f"{figure.to_html(full_html=False, include_plotlyjs=False)}</section>"
    )


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


def _fund_hover(timeline: Timeline, isin: str) -> tuple[list[tuple[float | None, str]], str]:
    """A fund line's customdata and the hover template that reads it.

    The CZK value, then the value in the fund's own currency unless that is CZK, then the units held.
    """
    customdata = list(
        zip(
            _floats(timeline.fund_currency_values[isin]),
            [_units(units) for units in timeline.units_held[isin]],
            strict=True,
        )
    )
    currency = timeline.fund_currencies[isin]
    in_currency = "" if currency == CZK else f" (%{{customdata[0]:,.2f}} {currency})"
    return customdata, f"{HOVER_CZK}{in_currency} · %{{customdata[1]}} units"


def _units(units: Decimal) -> str:
    """Units as stored: thousands separators, trailing zeros trimmed, no fixed number of decimals."""
    return f"{units.normalize():,f}"


def _floats(amounts: Sequence[Decimal | None]) -> list[float | None]:
    """Plotly takes floats; None leaves a gap in the line."""
    return [None if amount is None else float(amount) for amount in amounts]
