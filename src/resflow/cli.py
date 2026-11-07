"""Command line: ``resflow run``, ``resflow gold``, ``resflow render``."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from resflow import cdec, synapse
from resflow.lake import LocalLake
from resflow.sqlgen import GOLD_VIEWS

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LAKE = REPO / "lake"
DEFAULT_REFERENCE = REPO / "reference" / "stations.csv"
GENERATED = REPO / "infra" / "generated"


def _cmd_run(args: argparse.Namespace) -> int:
    end = args.end or (date.today() - timedelta(days=1)).isoformat()
    start = args.start or (date.fromisoformat(end) - timedelta(days=args.lookback_days)).isoformat()
    stations = args.stations.split(",")
    print(f"Fetching CDEC storage for {len(stations)} stations, {start} to {end}")
    raw = cdec.fetch_csv(stations, start, end)
    lake = LocalLake(Path(args.lake), Path(args.reference))
    result = lake.run(
        raw,
        run_id=str(uuid.uuid4()),
        ingested_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_start=start,
        window_end=end,
        stations=stations,
    )
    for c in result.checks:
        mark = "FAIL" if c.failed and c.severity == "fatal" else ("warn" if c.failed else "ok")
        print(f"  {c.rule_id:<20} {c.severity:<8} {c.failed:>6}  {mark}")
    print(f"run {result.run_id}: {'published' if result.published else 'NOT published'}")
    if result.error:
        print(result.error, file=sys.stderr)
    return 0 if result.published else 1


def _cmd_gold(args: argparse.Namespace) -> int:
    lake = LocalLake(Path(args.lake), Path(args.reference))
    rows = lake.gold(args.view)
    print(json.dumps(rows, default=str, indent=2))
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.check:
        bad = synapse.stale(out)
        if bad:
            print(f"Out of date in {out}: {', '.join(bad)}. Run `resflow render`.", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0
    for path in synapse.write(out):
        print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="resflow")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="fetch real CDEC data and run the pipeline locally")
    run.add_argument("--start", help="YYYY-MM-DD, inclusive")
    run.add_argument("--end", help="YYYY-MM-DD, inclusive (default: yesterday)")
    run.add_argument("--lookback-days", type=int, default=30)
    run.add_argument("--stations", default=",".join(cdec.DEFAULT_STATIONS))
    run.add_argument("--lake", default=str(DEFAULT_LAKE))
    run.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    run.set_defaults(func=_cmd_run)

    gold = sub.add_parser("gold", help="print a gold view from the local lake")
    gold.add_argument("view", choices=GOLD_VIEWS)
    gold.add_argument("--lake", default=str(DEFAULT_LAKE))
    gold.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    gold.set_defaults(func=_cmd_gold)

    render = sub.add_parser("render", help="write Synapse SQL to infra/generated")
    render.add_argument("--out", default=str(GENERATED))
    render.add_argument("--check", action="store_true", help="fail if committed files are stale")
    render.set_defaults(func=_cmd_render)

    args = p.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
