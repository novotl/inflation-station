# Recorded Eurostat responses

`prc_hicp_minr-cz.json` is the response of `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr?geo=CZ&coicop18=TOTAL&unit=I15&format=JSON&lang=EN`, recorded on 2026-10-10 and trimmed to December 2019 to May 2021, like the ČSÚ fixture: May 2021 was the last month published on 2021-07-01 (the tests' "today"). Trimming rewrote the JSON-stat `value` keys, the `time` dimension and `size` to match, and re-serialised the JSON compactly (so `110.60` reads `110.6`).
