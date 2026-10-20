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

from inflation_station.domain import Platform
from inflation_station.price_index import CSU_CPI, EUROSTAT_HICP, NAMES
from inflation_station.valuation import CZK, Holding

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date
    from pathlib import Path

    from inflation_station.domain import Portfolio
    from inflation_station.valuation import Hurdle, Timeline

CHART_NAME = "chart.html"
HOVER_CZK = "%{y:,.2f} CZK"
HOVER_PCT = "%{y:+.1%}"
# What a trace stands for; the page gives each role one colour on every chart. Fund lines have none and take the
# colourway.
VALUE, INVESTED, INFLATION = "value", "invested", "inflation"
# How each price index series' published hurdle is drawn; both share the inflation colour. Estimated parts are dotted.
HURDLE_DASH = {CSU_CPI: "solid", EUROSTAT_HICP: "dash"}
# How each Platform is named on the page.
PLATFORM_NAMES = {Platform.JT: "J&T Banka", Platform.INVESTIKA: "INVESTIKA", Platform.PORTU: "Portu"}


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

    Portfolios and Holdings come largest CZK value on the last day first. The benchmark, which the relative charts and
    the "vs" figures measure against, is ČSÚ CPI, else the only index there is; None before any index is fetched.
    """
    benchmark = CSU_CPI if CSU_CPI in timeline.hurdles else next(iter(timeline.hurdles), None)
    hurdle = timeline.hurdles[benchmark] if benchmark else None
    order = _by_last_value(timeline.units_held, timeline.holding_values)
    return {
        "asOf": timeline.dates[-1].isoformat(),
        "warnings": list(warnings),
        "benchmark": NAMES[benchmark] if benchmark else None,
        "estimatedFrom": hurdle.estimated_from.isoformat() if hurdle else None,
        "wholePortfolio": {
            "value": _last(timeline.whole_portfolio_value),
            "invested": _last(timeline.amount_invested),
            "hurdles": [{"name": NAMES[series], "value": _last(h.values)} for series, h in timeline.hurdles.items()],
            "benchmarkHurdle": _last(hurdle.values) if hurdle else None,
            "chart": _whole_portfolio_chart(timeline),
            "composition": _composition(timeline, order),
            "relative": _relative(timeline.dates, timeline.whole_portfolio_value, timeline.amount_invested, hurdle),
        },
        "portfolios": [
            _portfolio_section(timeline, portfolio, benchmark)
            for portfolio in _by_last_value(
                timeline.portfolios, {a: t.value for a, t in timeline.portfolios.items() if t.value is not None}
            )
        ],
        "funds": [_holding_section(timeline, holding) for holding in order],
    }


def _portfolio_section(timeline: Timeline, portfolio: Portfolio, benchmark: str | None) -> dict[str, Any]:
    """A Portfolio's figures on the last day and its chart, as the Whole Portfolio's."""
    series = timeline.portfolios[portfolio]
    hurdle = series.hurdles[benchmark] if benchmark else None
    held = [h for h in timeline.units_held if h.portfolio == portfolio]
    # With no value, nothing in it can be valued: each of its funds, and its Cash in every currency.
    missing = (["funds"] if held else []) + (["Cash"] if series.cash_not_valued else [])
    return {
        "key": _key(portfolio),
        "name": portfolio_name(portfolio),
        "value": _last(series.value),
        "invested": _last(series.amount_invested),
        "hurdles": [{"name": NAMES[s], "value": _last(h.values)} for s, h in series.hurdles.items()],
        "benchmarkHurdle": _last(hurdle.values) if hurdle else None,
        "notValued": None if series.value is not None else f"none of its {' or '.join(missing)} valued",
        # What its value leaves out: its funds and its Cash in each currency that can't be valued, saying why.
        "leftOut": [
            f"{timeline.fund_names[h.isin]} ({timeline.not_valued[h.isin]})"
            for h in held
            if h not in timeline.holding_values
        ]
        + [f"{currency} Cash ({reason})" for currency, reason in series.cash_not_valued.items()],
        "chart": _portfolio_chart(timeline, portfolio),
        "relative": _relative(timeline.dates, series.value, series.amount_invested, hurdle),
    }


def _holding_section(timeline: Timeline, holding: Holding) -> dict[str, Any]:
    """A Holding's figures on the last day and its chart. Nothing is invested in a Holding, only in its Portfolio, so
    it has no amount invested or hurdle (ADR-0002).
    """
    isin = holding.isin
    currency = timeline.fund_currencies.get(isin, CZK)
    currency_value = _last(timeline.holding_currency_values.get(holding))
    return {
        "key": _key(holding),
        "isin": isin,
        "name": timeline.fund_names[isin],
        "portfolio": portfolio_name(holding.portfolio),
        "pricedIn": timeline.priced_in[isin],
        "value": _last(timeline.holding_values.get(holding)),
        # Only for funds valued in a currency other than CZK.
        "currencyValue": None if currency == CZK or currency_value is None else f"{currency_value:,.2f} {currency}",
        "units": _units(timeline.units_held[holding][-1]),
        "notValued": timeline.not_valued.get(isin),
        "chart": _holding_chart(timeline, holding),
    }


def _whole_portfolio_chart(timeline: Timeline) -> list[dict[str, Any]]:
    """The Whole Portfolio's value, the amount invested and the inflation hurdles, in CZK."""
    traces = []
    if timeline.whole_portfolio_value is not None:
        traces.append(
            _line(timeline.dates, timeline.whole_portfolio_value, "Whole Portfolio value", VALUE, line={"width": 2.5})
        )
    traces.append(_invested(timeline.dates, timeline.amount_invested))
    for series, hurdle in timeline.hurdles.items():
        traces += _hurdle(timeline.dates, hurdle, series)
    return traces


def _composition(timeline: Timeline, order: Sequence[Holding]) -> list[dict[str, Any]]:
    """`_whole_portfolio_chart` with its value split: Cash at the bottom, then each valued Holding's value, largest on
    top.

    Each is named by its fund, and by its Portfolio too when the fund is held in more than one.
    """
    held_in = [h.isin for h in order]
    traces = []
    if timeline.cash_value is not None:
        traces.append(_line(timeline.dates, timeline.cash_value, "Cash", stackgroup="value", line={"width": 0}))
    traces += [
        _holding_value(
            timeline,
            h,
            timeline.fund_names[h.isin] + (f" ({portfolio_name(h.portfolio)})" if held_in.count(h.isin) > 1 else ""),
            stackgroup="value",
            line={"width": 0},
        )
        for h in reversed(order)
        if h in timeline.holding_values
    ]
    traces.append(_invested(timeline.dates, timeline.amount_invested, width=2))
    for series, hurdle in timeline.hurdles.items():
        traces += _hurdle(timeline.dates, hurdle, series, width=2)
    return traces


def _portfolio_chart(timeline: Timeline, portfolio: Portfolio) -> list[dict[str, Any]]:
    """The Portfolio's value, amount invested and inflation hurdles, in CZK, as `_whole_portfolio_chart`."""
    series = timeline.portfolios[portfolio]
    traces = []
    if series.value is not None:
        traces.append(_line(timeline.dates, series.value, "Value", VALUE, line={"width": 3}))
    traces.append(_invested(timeline.dates, series.amount_invested))
    for index_series, hurdle in series.hurdles.items():
        traces += _hurdle(timeline.dates, hurdle, index_series)
    return traces


def _holding_chart(timeline: Timeline, holding: Holding) -> list[dict[str, Any]]:
    """The Holding's value in CZK; none when it can't be valued."""
    if holding not in timeline.holding_values:
        return []
    return [_holding_value(timeline, holding, "Value", meta=VALUE, line={"width": 3})]


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


def _by_last_value[K](every: Iterable[K], values: Mapping[K, Sequence[Decimal | None]]) -> list[K]:
    """`every` key, largest CZK value in `values` on the last day first; those with no value that day come last."""

    def key(k: K) -> tuple[bool, Decimal]:
        last = values[k][-1] if k in values else None
        return (True, Decimal(0)) if last is None else (False, -last)

    return sorted(every, key=key)


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
    """A step line: the amount invested changes only on Deposit dates."""
    return _line(dates, invested, "Amount invested", INVESTED, line={"shape": "hv", "width": width}, **extra)


def _holding_value(
    timeline: Timeline, holding: Holding, name: str, meta: str | None = None, **extra: object
) -> dict[str, Any]:
    """A Holding's CZK value, hovering with its value in the fund's own currency (unless that is CZK) and its units."""
    customdata = [
        [None if value is None else float(value), _units(units)]
        for value, units in zip(timeline.holding_currency_values[holding], timeline.units_held[holding], strict=True)
    ]
    currency = timeline.fund_currencies[holding.isin]
    in_currency = "" if currency == CZK else f" (%{{customdata[0]:,.2f}} {currency})"
    return _line(
        timeline.dates,
        timeline.holding_values[holding],
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


def portfolio_name(portfolio: Portfolio) -> str:
    """`<Platform> · <Portfolio>`, as the Portfolio's section is headed."""
    return f"{PLATFORM_NAMES[portfolio.platform]} · {portfolio.name}"


def _key(of: Portfolio | Holding) -> str:
    """A key the page picks a Portfolio or Holding by: unique, as its parts never contain a newline."""
    portfolio = of.portfolio if isinstance(of, Holding) else of
    return "\n".join([portfolio.platform, portfolio.key, *([of.isin] if isinstance(of, Holding) else [])])


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
