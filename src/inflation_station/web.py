"""The only way out to the network: every fetcher downloads through `fetch`, and tests replace it."""

import urllib.request
from urllib.error import URLError

from inflation_station.errors import InflationStationError

# Some sites turn away Python's default User-Agent.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
TIMEOUT_SECONDS = 30


def fetch(url: str) -> bytes:
    """The body of a GET of `url`. Raises unless the response is 2xx."""
    if not url.startswith(("https://", "http://")):
        msg = f"refusing to download {url}: not an http(s) URL"
        raise InflationStationError(msg)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - scheme checked above
            # urlopen raises on 4xx and 5xx and follows redirects; anything else that isn't 2xx is unexpected too.
            if not 200 <= response.status < 300:  # noqa: PLR2004 - the 2xx range
                msg = f"cannot download {url}: HTTP {response.status}"
                raise InflationStationError(msg)
            return response.read()
    except (URLError, TimeoutError) as e:
        msg = f"cannot download {url}: {e}"
        raise InflationStationError(msg) from e
