"""A local copy of the Azure data lake, run on DuckDB.

``LocalLake.run`` performs the same steps as the Data Factory pipeline, in the
same order and with the same SQL:

1. land the raw CDEC response in ``bronze/`` (immutable, one folder per run);
2. parse it into ``staging/`` (the Synapse CETAS step);
3. run the checks query (the Lookup step);
4. if no fatal check failed, move staging to ``silver/`` (the Copy + Delete steps);
   otherwise leave staging in place for inspection and publish nothing.

Gold is a set of views over ``silver/``, as in Synapse serverless.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from resflow.sqlgen import GOLD_VIEWS, LocalPaths, RunVars, render

STAGING_DIR = "staging/reservoir_storage"
SILVER_DIR = "silver/reservoir_storage"
BRONZE_DIR = "bronze/cdec/sensor=15"


@dataclass(frozen=True)
class CheckResult:
    rule_id: str
    severity: str
    failed: int


@dataclass(frozen=True)
class RunResult:
    run_id: str
    published: bool
    checks: tuple[CheckResult, ...]
    error: str | None = None

    @property
    def fatal_failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.severity == "fatal" and c.failed > 0)

    def check(self, rule_id: str) -> int:
        for c in self.checks:
            if c.rule_id == rule_id:
                return c.failed
        raise KeyError(rule_id)


@dataclass
class LocalLake:
    root: Path
    reference_file: Path
    _con: duckdb.DuckDBPyConnection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect()

    def close(self) -> None:
        self._con.close()

    # Paths -------------------------------------------------------------

    def bronze_file(self, run_id: str) -> Path:
        return self.root / BRONZE_DIR / f"run_id={run_id}" / "cdec.csv"

    def staging_dir(self, run_id: str) -> Path:
        return self.root / STAGING_DIR / f"run_id={run_id}"

    def silver_dir(self, run_id: str) -> Path:
        return self.root / SILVER_DIR / f"run_id={run_id}"

    def _paths(self, run_id: str) -> LocalPaths:
        return LocalPaths(
            bronze_file=self.bronze_file(run_id),
            staging_glob=str(self.staging_dir(run_id) / "*.parquet"),
            silver_glob=str(self.root / SILVER_DIR / "*" / "*.parquet"),
            reference_file=self.reference_file,
        )

    def published_runs(self) -> list[str]:
        base = self.root / SILVER_DIR
        if not base.exists():
            return []
        return sorted(p.name.removeprefix("run_id=") for p in base.iterdir() if p.is_dir())

    # Pipeline ----------------------------------------------------------

    def run(
        self,
        raw: bytes,
        *,
        run_id: str,
        ingested_at: str,
        window_start: str,
        window_end: str,
        stations: list[str],
    ) -> RunResult:
        bronze = self.bronze_file(run_id)
        if bronze.exists():
            raise FileExistsError(f"run {run_id} already landed; run ids are single-use")
        bronze.parent.mkdir(parents=True, exist_ok=True)
        bronze.write_bytes(raw)

        run = RunVars(
            run_id=run_id,
            ingested_at=ingested_at,
            window_start=window_start,
            window_end=window_end,
            station_count=str(len(stations)),
        )
        paths = self._paths(run_id)

        staging = self.staging_dir(run_id)
        staging.mkdir(parents=True, exist_ok=True)
        parsed_sql = render("stg_parsed", "duckdb", run, paths)
        target = str(staging / "part-0.parquet").replace("'", "''")
        try:
            self._con.execute(f"COPY ({parsed_sql}) TO '{target}' (FORMAT PARQUET)")
        except duckdb.Error as exc:
            # A file DuckDB cannot read with the contract's 9 columns (for
            # example an HTML error page with a comma in it) fails the run.
            shutil.rmtree(staging)
            return RunResult(run_id, False, (CheckResult("F0_unreadable", "fatal", 1),), str(exc))

        rows = self._con.execute(render("checks", "duckdb", run, paths)).fetchall()
        checks = tuple(CheckResult(str(r[0]), str(r[1]), int(r[2])) for r in rows)
        result = RunResult(run_id, False, checks)
        if result.fatal_failures:
            return result

        silver = self.silver_dir(run_id)
        silver.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(silver))
        self._refresh_gold()
        return RunResult(run_id, True, checks)

    # Gold --------------------------------------------------------------

    def _refresh_gold(self) -> None:
        paths = self._paths("_gold_")
        for name in GOLD_VIEWS:
            body = render(f"gold_{name}", "duckdb", None, paths)
            self._con.execute(f"CREATE OR REPLACE VIEW gold_{name} AS {body}")

    def gold(self, name: str) -> list[dict[str, object]]:
        if name not in GOLD_VIEWS:
            raise KeyError(name)
        if not self.published_runs():
            return []
        self._refresh_gold()
        cur = self._con.execute(f"SELECT * FROM gold_{name}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
