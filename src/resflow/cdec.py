"""Fetch daily reservoir storage from CDEC (California Data Exchange Center).

CDEC's CSV servlet returns one row per station per day, including days with
no reading (value ``---``). Sensor 15 is reservoir storage in acre-feet, and
``dur_code=D`` asks for daily values. Start and End are inclusive.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import httpx

BASE_URL = "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"
STORAGE_SENSOR = 15

# The 12 reservoirs in reference/stations.csv.
DEFAULT_STATIONS = ["SHA", "CLE", "ORO", "BUL", "FOL", "CMN", "NML", "DNP", "EXC", "MIL", "SNL", "PNF"]


def csv_url(stations: list[str], start: str, end: str) -> str:
    query = urlencode(
        {
            "Stations": ",".join(stations),
            "SensorNums": STORAGE_SENSOR,
            "dur_code": "D",
            "Start": start,
            "End": end,
        },
        safe=",",
    )
    return f"{BASE_URL}?{query}"


def fetch_csv(
    stations: list[str],
    start: str,
    end: str,
    *,
    attempts: int = 3,
    backoff_s: float = 5.0,
    client: httpx.Client | None = None,
) -> bytes:
    """Return the raw response body. Retries on network errors and 5xx.

    The body is returned as-is. Whether it is really CDEC data (and not, say,
    an error page served with status 200) is decided by the header check,
    the same as in Azure.
    """
    url = csv_url(stations, start, end)
    own = client is None
    http = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = http.get(url)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                if attempt < attempts:
                    time.sleep(backoff_s * attempt)
        assert last is not None
        raise last
    finally:
        if own:
            http.close()
