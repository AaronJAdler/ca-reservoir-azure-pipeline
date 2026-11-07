"""End-to-end runs of the local lake on real CDEC responses.

Tests that alter a real response say so; the altered bytes are generated
from the real file in the test itself, so the change is visible here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from conftest import FIXTURES, JULY, JULY_STATIONS, NOV, NOV_STATIONS, july_bytes, nov_bytes

from resflow.lake import LocalLake, RunResult


def run_july(lake: LocalLake, raw: bytes, run_id: str = "r1", at: str = "2026-08-01T15:00:00Z") -> RunResult:
    return lake.run(
        raw,
        run_id=run_id,
        ingested_at=at,
        window_start="2026-07-12",
        window_end="2026-07-31",
        stations=JULY_STATIONS,
    )


# --- The fixtures are the real bytes -----------------------------------------


def test_fixtures_match_hashes_recorded_when_downloaded() -> None:
    # SHA-256 computed in the browser on cdec.water.ca.gov on 2026-11-07,
    # over the response body before it was saved.
    assert hashlib.sha256(JULY.read_bytes()).hexdigest() == (
        "a0e5b0b953a86cff09a3386a157ddb0faa15709ff48abfcfc68428a92d43108b"
    )
    assert hashlib.sha256(NOV.read_bytes()).hexdigest() == (
        "56a8265971cde557b8e7a2d4c78b80d076f46fa87f40cbd932d03d7a6081e594"
    )
    assert b"\r\n" in JULY.read_bytes()


# --- A clean real run --------------------------------------------------------


def test_real_july_window_publishes_with_expected_warnings(lake: LocalLake) -> None:
    r = lake.run(
        july_bytes(),
        run_id="r1",
        ingested_at="2026-08-01T15:00:00Z",
        window_start="2026-07-12",
        window_end="2026-07-31",
        stations=JULY_STATIONS,
    )
    assert r.published
    assert r.fatal_failures == ()
    # DNP 24-26 July and EXC 26 July are --- in the source.
    assert r.check("W1_missing_value") == 4
    # ORO 21 Jul, DNP 15-16 Jul and EXC 17 Jul carry flag e.
    assert r.check("W2_estimated") == 4
    assert r.check("W4_rejected_row") == 0

    daily = lake.gold("reservoir_daily")
    assert len(daily) == 80
    missing = sorted((d["station_id"], str(d["reading_date"])) for d in daily if d["is_missing"])
    assert missing == [
        ("DNP", "2026-07-24"),
        ("DNP", "2026-07-25"),
        ("DNP", "2026-07-26"),
        ("EXC", "2026-07-26"),
    ]


def test_reading_date_comes_from_date_time_not_obs_date(lake: LocalLake) -> None:
    # CDEC's OBS DATE is usually the next day, but for ORO on 21 July it is the
    # same day. Keying on OBS DATE would put two ORO readings on 21 July and none on 22 July.
    run_july(lake, july_bytes())
    daily = lake.gold("reservoir_daily")
    oro = {d["reading_date"]: d["storage_af"] for d in daily if d["station_id"] == "ORO"}
    assert oro[date(2026, 7, 21)] == 2709398
    assert oro[date(2026, 7, 22)] == 2692954
    assert len(oro) == 20


def test_pct_capacity_and_statewide_total(lake: LocalLake) -> None:
    run_july(lake, july_bytes())
    latest = {d["station_id"]: d for d in lake.gold("reservoir_latest")}
    # 2,512,790 / 3,424,753 (Oroville capacity from CDEC's RES report)
    assert latest["ORO"]["pct_capacity"] == 73.4
    assert latest["ORO"]["change_7d_af"] == 2512790 - 2652658

    state = {d["reading_date"]: d for d in lake.gold("statewide_daily")}
    assert state[date(2026, 7, 12)]["total_storage_af"] == 2853511 + 1810457 + 779077 + 3371339


def test_statewide_total_is_null_on_days_with_gaps(lake: LocalLake) -> None:
    run_july(lake, july_bytes())
    state = {d["reading_date"]: d for d in lake.gold("statewide_daily")}
    gap_days = sorted(str(d) for d, row in state.items() if row["total_storage_af"] is None)
    assert gap_days == ["2026-07-24", "2026-07-25", "2026-07-26"]
    assert state[date(2026, 7, 26)]["stations_reporting"] == 2
    assert state[date(2026, 7, 26)]["partial_storage_af"] == 3137784 + 2608424


def test_seven_day_change_is_null_when_week_ago_is_missing(lake: LocalLake) -> None:
    # DNP's latest is 31 July; 24 July is --- in the source.
    run_july(lake, july_bytes())
    dnp = next(d for d in lake.gold("reservoir_latest") if d["station_id"] == "DNP")
    assert dnp["storage_af_7d_ago"] is None
    assert dnp["change_7d_af"] is None


# --- Latency at the end of the feed and reconciliation ------------------------


def test_latest_skips_trailing_missing_day_and_reports_lag(lake: LocalLake) -> None:
    r = lake.run(
        nov_bytes(),
        run_id="n1",
        ingested_at="2026-11-07T15:00:00Z",
        window_start="2026-11-01",
        window_end="2026-11-06",
        stations=NOV_STATIONS,
    )
    assert r.published
    latest = {d["station_id"]: d for d in lake.gold("reservoir_latest")}
    # Camanche's 6 Nov value had not arrived yet: show 5 Nov, one day behind.
    assert latest["CMN"]["latest_date"] == date(2026, 11, 5)
    assert latest["CMN"]["storage_af"] == 320340
    assert latest["CMN"]["days_behind"] == 1
    assert latest["ORO"]["days_behind"] == 0


def test_latest_matches_cdec_reservoir_conditions_report(lake: LocalLake) -> None:
    # An independent CDEC page (the RES report) read on the same day.
    report = json.loads((FIXTURES / "cdec_res_report_2026-11-07.json").read_text())["storage_af"]
    lake.run(
        nov_bytes(),
        run_id="n1",
        ingested_at="2026-11-07T15:00:00Z",
        window_start="2026-11-01",
        window_end="2026-11-06",
        stations=NOV_STATIONS,
    )
    daily = {(d["station_id"], d["reading_date"]): d["storage_af"] for d in lake.gold("reservoir_daily")}
    assert daily[("ORO", date(2026, 11, 6))] == report["ORO"]
    # The report also shows --- for Camanche on that day.
    assert daily[("CMN", date(2026, 11, 6))] is None
    assert report["CMN"] is None


# --- Reruns, revisions, append-only history ------------------------------------


def test_rerunning_same_window_does_not_duplicate_gold(lake: LocalLake) -> None:
    run_july(lake, july_bytes(), "r1", "2026-08-01T15:00:00Z")
    run_july(lake, july_bytes(), "r2", "2026-08-02T15:00:00Z")
    assert lake.published_runs() == ["r1", "r2"]
    assert len(lake.gold("reservoir_daily")) == 80
    assert lake.gold("revisions") == []


def test_reusing_a_run_id_is_refused(lake: LocalLake) -> None:
    run_july(lake, july_bytes(), "r1")
    try:
        run_july(lake, july_bytes(), "r1")
    except FileExistsError:
        return
    raise AssertionError("second run with the same id should fail")


def test_later_revision_wins_and_is_listed(lake: LocalLake) -> None:
    run_july(lake, july_bytes(), "r1", "2026-08-01T15:00:00Z")
    # Generated: the real file with Shasta 20 July changed, as a CDEC revision.
    revised = july_bytes().replace(
        b"SHA,D,15,STORAGE,20260720 0000,20260721 0000,3249502, ,AF",
        b"SHA,D,15,STORAGE,20260720 0000,20260721 0000,3249900,r,AF",
    )
    assert revised != july_bytes()
    r2 = run_july(lake, revised, "r2", "2026-08-02T15:00:00Z")
    assert r2.check("W3_revised_flag") == 1

    sha = next(
        d
        for d in lake.gold("reservoir_daily")
        if d["station_id"] == "SHA" and d["reading_date"] == date(2026, 7, 20)
    )
    assert sha["storage_af"] == 3249900
    assert sha["source_run_id"] == "r2"
    assert sha["is_revised"] == 1
    revs = lake.gold("revisions")
    assert [(r["station_id"], r["min_storage_af"], r["max_storage_af"]) for r in revs] == [
        ("SHA", 3249502, 3249900)
    ]


def test_later_missing_value_does_not_erase_earlier_reading(lake: LocalLake) -> None:
    run_july(lake, july_bytes(), "r1", "2026-08-01T15:00:00Z")
    # Generated: a later pull where Shasta 20 July came back as ---.
    blanked = july_bytes().replace(b"20260721 0000,3249502, ,AF", b"20260721 0000,---, ,AF")
    run_july(lake, blanked, "r2", "2026-08-02T15:00:00Z")
    sha = next(
        d
        for d in lake.gold("reservoir_daily")
        if d["station_id"] == "SHA" and d["reading_date"] == date(2026, 7, 20)
    )
    assert sha["storage_af"] == 3249502
    assert sha["source_run_id"] == "r1"
    assert len(lake.gold("revisions")) == 1


# --- Fatal checks: nothing is published ---------------------------------------


def test_error_page_with_status_200_is_rejected(lake: LocalLake) -> None:
    html = b"<html><body>Service temporarily unavailable</body></html>\r\n"
    r = run_july(lake, html)
    assert not r.published
    assert lake.published_runs() == []
    assert lake.gold("reservoir_daily") == []


def test_changed_header_is_fatal(lake: LocalLake) -> None:
    raw = july_bytes().replace(b"DATA_FLAG,UNITS", b"FLAG,UNITS", 1)
    r = run_july(lake, raw)
    assert r.check("F1_header") == 1
    assert not r.published
    # Staging is kept for inspection; silver is untouched.
    assert lake.staging_dir("r1").exists()
    assert lake.published_runs() == []


def test_truncated_response_fails_completeness(lake: LocalLake) -> None:
    lines = july_bytes().split(b"\r\n")
    truncated = b"\r\n".join(lines[:61]) + b"\r\n"  # header + 60 of 80 rows
    r = run_july(lake, truncated)
    assert r.check("F4_completeness") == 20
    assert not r.published


def test_duplicate_station_day_is_fatal(lake: LocalLake) -> None:
    extra = b"SHA,D,15,STORAGE,20260731 0000,20260801 0000,3054369, ,AF\r\n"
    r = run_july(lake, july_bytes() + extra)
    assert r.check("F3_duplicate_keys") == 1
    assert not r.published


def test_wrong_units_or_unknown_station_is_fatal(lake: LocalLake) -> None:
    raw = july_bytes().replace(b"0000,2853511, ,AF", b"0000,2853511, ,FT", 1)
    raw = raw.replace(b"SHA,D,15,STORAGE,20260712", b"XYZ,D,15,STORAGE,20260712", 1)
    r = run_july(lake, raw)
    assert r.check("F2_contract") == 2
    assert not r.published


def test_rows_outside_requested_window_are_fatal(lake: LocalLake) -> None:
    r = lake.run(
        july_bytes(),
        run_id="r1",
        ingested_at="2026-08-01T15:00:00Z",
        window_start="2026-07-13",  # file starts on the 12th
        window_end="2026-07-31",
        stations=JULY_STATIONS,
    )
    assert r.check("F2_contract") == 4
    assert not r.published


def test_cdec_silently_drops_unknown_station_and_completeness_catches_it(lake: LocalLake) -> None:
    # Real response for Stations=SHA,ZZZ: status 200, ZZZ simply left out.
    raw = (FIXTURES / "cdec_unknown_station_SHA_ZZZ.csv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "12ab035b1ff7c67ed6268cff08155a10adfad97e5e6c7bc704406b22648d1664"
    )
    r = lake.run(
        raw,
        run_id="z1",
        ingested_at="2026-11-07T15:00:00Z",
        window_start="2026-11-01",
        window_end="2026-11-03",
        stations=["SHA", "ZZZ"],
    )
    assert r.check("F1_header") == 0
    assert r.check("F4_completeness") == 3
    assert not r.published


def test_window_that_ends_before_it_starts_is_fatal(lake: LocalLake) -> None:
    header_only = july_bytes().split(b"\r\n")[0] + b"\r\n"
    r = lake.run(
        header_only,
        run_id="r1",
        ingested_at="2026-08-01T15:00:00Z",
        window_start="2026-07-31",
        window_end="2026-07-12",
        stations=JULY_STATIONS,
    )
    assert r.check("F5_window") == 1
    assert not r.published


# --- Row-level rejects: run publishes, row is quarantined ---------------------


def test_implausible_value_is_quarantined_not_fatal(lake: LocalLake) -> None:
    # Generated: an extra digit on Shasta 12 July, about 10x its capacity.
    raw = july_bytes().replace(b"20260713 0000,3371339,", b"20260713 0000,45520000,", 1)
    r = run_july(lake, raw)
    assert r.published
    assert r.check("W4_rejected_row") == 1
    q = lake.gold("quarantine")
    assert [(x["station_id"], x["reject_reason"], x["storage_af"]) for x in q] == [
        ("SHA", "implausible_value", 45520000)
    ]
    daily = lake.gold("reservoir_daily")
    assert len(daily) == 79
    assert not any(d["station_id"] == "SHA" and d["reading_date"] == date(2026, 7, 12) for d in daily)


def test_non_numeric_value_is_quarantined(lake: LocalLake) -> None:
    # Generated: a non-numeric value in an otherwise valid row.
    raw = july_bytes().replace(b"20260713 0000,2853511,", b"20260713 0000,N/A,", 1)
    r = run_july(lake, raw)
    assert r.published
    assert [(x["station_id"], x["reject_reason"]) for x in lake.gold("quarantine")] == [("ORO", "bad_value")]


def test_extra_columns_fail_the_run(lake: LocalLake) -> None:
    # Generated: thousands separators split the value into three columns.
    raw = july_bytes().replace(b"20260713 0000,2853511,", b"20260713 0000,2,853,511,", 1)
    r = run_july(lake, raw)
    assert not r.published
    assert r.fatal_failures
