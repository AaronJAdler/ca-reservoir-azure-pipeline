from __future__ import annotations

import httpx
import pytest

from resflow import cdec


def test_csv_url_matches_the_url_the_fixtures_came_from() -> None:
    assert cdec.csv_url(["ORO", "DNP", "EXC", "SHA"], "2026-07-12", "2026-07-31") == (
        "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"
        "?Stations=ORO,DNP,EXC,SHA&SensorNums=15&dur_code=D&Start=2026-07-12&End=2026-07-31"
    )


def test_fetch_retries_5xx_then_returns_body() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"STATION_ID,...")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    body = cdec.fetch_csv(["SHA"], "2026-07-12", "2026-07-12", client=client, backoff_s=0)
    assert body == b"STATION_ID,..."
    assert calls["n"] == 2


def test_fetch_does_not_retry_4xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        cdec.fetch_csv(["SHA"], "2026-07-12", "2026-07-12", client=client, backoff_s=0)
    assert calls["n"] == 1


def test_default_stations_match_reference_file() -> None:
    from conftest import REFERENCE

    ids = [line.split(",")[0] for line in REFERENCE.read_text().splitlines()[1:]]
    assert ids == cdec.DEFAULT_STATIONS
