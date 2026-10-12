"""Draws a Timeline as one self-contained HTML page (plotly.js and the page's own CSS and JS inlined).

The page has three layouts of the same data, switched in its top bar: a dashboard with a fund table, every value
relative to inflation, and a strip of funds above one big chart. Python builds every chart's plotly traces and the
figures shown beside them, as JSON in the page; `chart_page.js` lays them out, colours each trace by its role (`meta`)
in the light or dark theme, and blurs absolute amounts in private mode.
"""

import json
import re
from datetime import timedelta
from decimal import Decimal
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from plotly.offline import get_plotlyjs

from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES
from inflation_station.valuation import CZK

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from inflation_station.valuation import Hurdle, Timeline

CHART_NAME = "chart.html"
HOVER_CZK = "%{y:,.2f} CZK"
HOVER_PCT = "%{y:+.1%}"
# What a trace stands for; the page gives each role one colour on every chart. Fund lines have none and take the
# colourway.
VALUE, INVESTED, INFLATION = "value", "invested", "inflation"
# How each price index series' published hurdle is drawn; both share the inflation colour. Estimated parts are dotted.
HURDLE_DASH = {CSU_CPI: "solid", EUROSTAT_HICP: "dash"}


def write_chart(timeline: Timeline, data_dir: Path, *, warnings: Sequence[str] = ()) -> Path:
    """Write the chart page into `data_dir` and return its path. Doesn't open a browser.

    `warnings`, about out-of-date series, are shown at the top of the page.
    """
    package = files("inflation_station")
    parts = {
        "STYLE": package.joinpath("chart_page.css").read_text(encoding="utf-8"),
        "PLOTLY": get_plotlyjs(),
        "SCRIPT": package.joinpath("chart_page.js").read_text(encoding="utf-8"),
        # "</" would close the script element it's in; escaped, it is the same JSON.
        "DATA": json.dumps(_page_data(timeline, warnings), ensure_ascii=False).replace("</", "<\\/"),
    }
    # In one pass, so nothing in a part (plotly.js has "{{") is taken for a placeholder.
    template = package.joinpath("chart_page.html").read_text(encoding="utf-8")
    html = re.sub(r"\{\{(STYLE|PLOTLY|SCRIPT|DATA)\}\}", lambda m: parts[m[1]], template)
    path = data_dir / CHART_NAME
    path.write_text(html, encoding="utf-8")
    return path


def _page_data(timeline: Timeline, warnings: Sequence[str]) -> dict[str, Any]:
    """Everything the page shows: the figures on the last day, and the traces of every chart.

    Funds come largest CZK value on the last day first. The benchmark, which the relative charts and the "vs" figures
    measure against, is ČSÚ CPI, else the only index there is; None before any index is fetched.
    """
    benchmark = CSU_CPI if CSU_CPI in timeline.hurdles else next(iter(timeline.hurdles), None)
    hurdle = timeline.hurdles[benchmark] if benchmark else None
    order = _by_last_value(timeline)
    return {
        "asOf": timeline.dates[-1].isoformat(),
        "warnings": list(warnings),
        "benchmark": NAMES[benchmark] if benchmark else None,
        "estimatedFrom": hurdle.estimated_from.isoformat() if hurdle else None,
        "portfolio": {
            "value": _last(timeline.portfolio_value),
            "invested": _last(timeline.amount_invested),
            "hurdles": [{"name": NAMES[series], "value": _last(h.values)} for series, h in timeline.hurdles.items()],
            "benchmarkHurdle": _last(hurdle.values) if hurdle else None,
            "chart": _overall(timeline),
            "composition": _composition(timeline, order),
            "relative": _relative(timeline.dates, timeline.portfolio_value, timeline.amount_invested, hurdle),
        },
        "funds": [_fund(timeline, isin, benchmark) for isin in order],
    }


def _fund(timeline: Timeline, isin: str, benchmark: str | None) -> dict[str, Any]:
    hurdle = timeline.fund_hurdles[isin][benchmark] if benchmark else None
    currency = timeline.fund_currencies.get(isin, CZK)
    currency_value = _last(timeline.fund_currency_values.get(isin))
    return {
        "isin": isin,
        "name": timeline.fund_names[isin],
        "pricedIn": timeline.priced_in[isin],
        "value": _last(timeline.fund_values.get(isin)),
        # Only for funds valued in a currency other than CZK.
        "currencyValue": None if currency == CZK or currency_value is None else f"{currency_value:,.2f} {currency}",
        "invested": _last(timeline.fund_amount_invested[isin]),
        "units": _units(timeline.units_held[isin][-1]),
        "benchmarkHurdle": _last(hurdle.values) if hurdle else None,
        "notValued": timeline.not_valued.get(isin),
        "chart": _fund_chart(timeline, isin),
        "relative": _relative(
            timeline.dates, timeline.fund_values.get(isin), timeline.fund_amount_invested[isin], hurdle
        ),
    }


def _overall(timeline: Timeline) -> list[dict[str, Any]]:
    """The portfolio's value, the amount invested and the inflation hurdles, in CZK."""
    traces = []
    if timeline.portfolio_value is not None:
        traces.append(_line(timeline.dates, timeline.portfolio_value, "Portfolio value", VALUE, line={"width": 2.5}))
    traces.append(_invested(timeline.dates, timeline.amount_invested))
    for series, hurdle in timeline.hurdles.items():
        traces += _hurdle(timeline.dates, hurdle, series)
    return traces


def _composition(timeline: Timeline, order: Sequence[str]) -> list[dict[str, Any]]:
    """`_overall` with the portfolio value split: each valued fund's value stacked, largest on top."""
    traces = [
        _fund_value(timeline, isin, timeline.fund_names[isin], stackgroup="value", line={"width": 0})
        for isin in reversed(order)
        if isin in timeline.fund_values
    ]
    traces.append(_invested(timeline.dates, timeline.amount_invested, width=2))
    for series, hurdle in timeline.hurdles.items():
        traces += _hurdle(timeline.dates, hurdle, series, width=2)
    return traces


def _fund_chart(timeline: Timeline, isin: str) -> list[dict[str, Any]]:
    """The fund's value, the amount invested in it and its inflation hurdles, in CZK, from its Purchases only."""
    traces = []
    if isin in timeline.fund_values:
        traces.append(_fund_value(timeline, isin, "Value", meta=VALUE, line={"width": 3}))
    # With no value line to show them, the units held go on the amount invested.
    invested_hover = (
        {
            "customdata": [[_units(units)] for units in timeline.units_held[isin]],
            "hovertemplate": f"{HOVER_CZK} · %{{customdata[0]}} units",
        }
        if isin in timeline.not_valued
        else {}
    )
    traces.append(_invested(timeline.dates, timeline.fund_amount_invested[isin], **invested_hover))
    for series, hurdle in timeline.fund_hurdles[isin].items():
        traces += _hurdle(timeline.dates, hurdle, series)
    return traces


def _relative(
    dates: Sequence[date],
    values: Sequence[Decimal | None] | None,
    invested: Sequence[Decimal],
    hurdle: Hurdle | None,
) -> list[dict[str, Any]]:
    """How far the value is above (+) or below (-) the benchmark's hurdle (real) and the amount invested (nominal).

    Each line takes the colour of what it's measured against. None for a value that can't be known; no lines without
    values.
    """
    if values is None:
        return []
    traces = []
    if hurdle is not None:
        traces.append(_line(dates, _ratio(values, hurdle.values), "real", INFLATION, hovertemplate=HOVER_PCT))
    traces.append(_line(dates, _ratio(values, invested), "nominal", INVESTED, hovertemplate=HOVER_PCT))
    return traces


def _by_last_value(timeline: Timeline) -> list[str]:
    """Every fund purchased, largest CZK value on the last day first; funds with no value that day come last."""

    def key(isin: str) -> tuple[bool, Decimal]:
        last = timeline.fund_values[isin][-1] if isin in timeline.fund_values else None
        return (True, Decimal(0)) if last is None else (False, -last)

    return sorted(timeline.units_held, key=key)


def _line(
    dates: Sequence[date], values: Sequence[Decimal | None], name: str, meta: str | None = None, **extra: object
) -> dict[str, Any]:
    """A plotly line in role `meta`, hovering with its CZK value unless `extra` says otherwise."""
    trace: dict[str, Any] = {
        "type": "scatter",
        "x": [d.isoformat() for d in dates],
        "y": _floats(values),
        "name": name,
        "hovertemplate": HOVER_CZK,
    }
    if meta:
        trace["meta"] = meta
    return trace | extra


def _invested(
    dates: Sequence[date], invested: Sequence[Decimal], width: float = 1.5, **extra: object
) -> dict[str, Any]:
    """A step line: the amount invested changes only on trade dates."""
    return _line(dates, invested, "Amount invested", INVESTED, line={"shape": "hv", "width": width}, **extra)


def _fund_value(timeline: Timeline, isin: str, name: str, meta: str | None = None, **extra: object) -> dict[str, Any]:
    """A fund's CZK value, hovering with its value in the fund's own currency (unless that is CZK) and its units."""
    customdata = [
        [None if value is None else float(value), _units(units)]
        for value, units in zip(timeline.fund_currency_values[isin], timeline.units_held[isin], strict=True)
    ]
    currency = timeline.fund_currencies[isin]
    in_currency = "" if currency == CZK else f" (%{{customdata[0]:,.2f}} {currency})"
    return _line(
        timeline.dates,
        timeline.fund_values[isin],
        name,
        meta,
        customdata=customdata,
        hovertemplate=f"{HOVER_CZK}{in_currency} · %{{customdata[1]}} units",
        **extra,
    )


def _hurdle(dates: Sequence[date], hurdle: Hurdle, series: str, width: float = 1.5) -> list[dict[str, Any]]:
    """The published part in the series' dash; the estimated part dotted, starting where the published part ends."""
    name = f"Inflation hurdle ({NAMES[series]})"
    parts = [
        ([n for n, d in enumerate(dates) if d < hurdle.estimated_from], name, HURDLE_DASH[series]),
        (
            [n for n, d in enumerate(dates) if d >= hurdle.estimated_from - timedelta(days=1)],
            f"Inflation hurdle ({NAMES[series]}, estimated)",
            "dot",
        ),
    ]
    return [
        _line(
            [dates[n] for n in days],
            [hurdle.values[n] for n in days],
            part_name,
            INFLATION,
            legendgroup=name,
            line={"dash": dash, "width": width},
        )
        for days, part_name, dash in parts
        if days
    ]


def _ratio(values: Sequence[Decimal | None], bases: Sequence[Decimal | None]) -> list[Decimal | None]:
    """values / bases - 1, day by day; None where either is unknown or the base is 0."""
    return [None if v is None or b is None or b == 0 else v / b - 1 for v, b in zip(values, bases, strict=True)]


def _last(amounts: Sequence[Decimal | None] | None) -> float | None:
    """The amount on the last day, as a float for the page; None when there is none."""
    return None if amounts is None or amounts[-1] is None else float(amounts[-1])


def _units(units: Decimal) -> str:
    """Units as stored: thousands separators, trailing zeros trimmed, no fixed number of decimals."""
    return f"{units.normalize():,f}"


def _floats(amounts: Sequence[Decimal | None]) -> list[float | None]:
    """Plotly takes floats; None leaves a gap in the line."""
    return [None if amount is None else float(amount) for amount in amounts]
