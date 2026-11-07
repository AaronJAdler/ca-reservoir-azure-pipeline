"""Render the shared SQL templates for one of two engines.

The templates in ``sql/`` are written in the subset of SQL that DuckDB and
Synapse serverless (T-SQL) both accept. The few places where the engines
differ (reading files, date arithmetic, the carriage-return character) are
macros supplied here. Local runs use the DuckDB rendering; the Synapse
rendering is written to ``infra/generated/`` and embedded in the Data Factory
pipeline by Bicep.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import jinja2

Engine = Literal["duckdb", "synapse"]

SQL_DIR = Path(__file__).parent / "sql"

# Gold views in dependency order: a view may only ref() views listed before it.
GOLD_VIEWS: tuple[str, ...] = (
    "reservoir_daily",
    "reservoir_latest",
    "statewide_daily",
    "revisions",
    "quarantine",
)

BRONZE_COLUMNS = tuple(f"c{i}" for i in range(1, 10))


@dataclass(frozen=True)
class RunVars:
    """Values that differ per run. For Synapse they are Data Factory expressions."""

    run_id: str
    ingested_at: str
    window_start: str
    window_end: str
    station_count: str


# What a Data Factory run substitutes at execution time. The pipeline sets the
# windowStart, windowEnd and stations variables before running any SQL.
ADF_RUN_VARS = RunVars(
    run_id="@{pipeline().RunId}",
    ingested_at="@{formatDateTime(pipeline().TriggerTime, 'yyyy-MM-ddTHH:mm:ssZ')}",
    window_start="@{variables('windowStart')}",
    window_end="@{variables('windowEnd')}",
    station_count="@{length(split(variables('stations'), ','))}",
)


@dataclass(frozen=True)
class LocalPaths:
    """File locations for a local (DuckDB) run."""

    bronze_file: Path
    staging_glob: str
    silver_glob: str
    reference_file: Path


def _sq(path: Path | str) -> str:
    """A path as a SQL string literal (single quotes doubled)."""
    return "'" + str(path).replace("'", "''") + "'"


def _duckdb_macros(paths: LocalPaths | None) -> dict[str, Callable[..., str]]:
    def need() -> LocalPaths:
        if paths is None:
            raise ValueError("DuckDB rendering of this template needs LocalPaths")
        return paths

    columns = ", ".join(f"'{c}': 'VARCHAR'" for c in BRONZE_COLUMNS)
    return {
        "clean": lambda col: f"NULLIF(TRIM(REPLACE({col}, chr(13), '')), '')",
        "bronze": lambda: (
            f"read_csv({_sq(need().bronze_file)}, header = false, auto_detect = false, "
            f"delim = ',', quote = '\"', columns = {{{columns}}})"
        ),
        "reference": lambda: (
            f"read_csv({_sq(need().reference_file)}, header = true, auto_detect = false, "
            "delim = ',', columns = {'station_id': 'VARCHAR', 'station_name': 'VARCHAR', "
            "'capacity_af': 'BIGINT'})"
        ),
        "staging": lambda: f"read_parquet({_sq(need().staging_glob)})",
        "silver": lambda: f"read_parquet({_sq(need().silver_glob)}, union_by_name = true)",
        "ref": lambda name: f"gold_{name}",
        "days_between": lambda a, b: f"date_diff('day', {a}, {b})",
        "add_days": lambda expr, n: f"CAST({expr} + INTERVAL ({int(n)}) DAY AS DATE)",
    }


def _synapse_macros() -> dict[str, Callable[..., str]]:
    with_cols = ", ".join(
        f"{c} VARCHAR(100) COLLATE Latin1_General_100_BIN2_UTF8 {i}"
        for i, c in enumerate(BRONZE_COLUMNS, start=1)
    )
    run_id = ADF_RUN_VARS.run_id
    return {
        "clean": lambda col: f"NULLIF(TRIM(REPLACE({col}, CHAR(13), '')), '')",
        "bronze": lambda: (
            f"OPENROWSET(BULK 'bronze/cdec/sensor=15/run_id={run_id}/cdec.csv', "
            "DATA_SOURCE = 'lake', FORMAT = 'CSV', PARSER_VERSION = '2.0', "
            f"FIELDTERMINATOR = ',', HEADER_ROW = FALSE) WITH ({with_cols})"
        ),
        "reference": lambda: (
            "OPENROWSET(BULK 'reference/stations.csv', DATA_SOURCE = 'lake', "
            "FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) "
            "WITH (station_id VARCHAR(10) COLLATE Latin1_General_100_BIN2_UTF8, "
            "station_name VARCHAR(100) COLLATE Latin1_General_100_BIN2_UTF8, "
            "capacity_af BIGINT)"
        ),
        "staging": lambda: (
            f"OPENROWSET(BULK 'staging/reservoir_storage/run_id={run_id}/*.parquet', "
            "DATA_SOURCE = 'lake', FORMAT = 'PARQUET')"
        ),
        "silver": lambda: (
            "OPENROWSET(BULK 'silver/reservoir_storage/*/*.parquet', "
            "DATA_SOURCE = 'lake', FORMAT = 'PARQUET')"
        ),
        "ref": lambda name: f"gold.{name}",
        "days_between": lambda a, b: f"DATEDIFF(day, {a}, {b})",
        "add_days": lambda expr, n: f"DATEADD(day, {int(n)}, {expr})",
    }


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(SQL_DIR),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


def render(
    template: str,
    engine: Engine,
    run: RunVars | None = None,
    paths: LocalPaths | None = None,
) -> str:
    """Render ``sql/<template>.sql.j2`` for ``engine``."""
    macros = _duckdb_macros(paths) if engine == "duckdb" else _synapse_macros()
    if engine == "synapse":
        run = ADF_RUN_VARS
    context: dict[str, object] = dict(macros)
    if run is not None:
        context.update(
            run_id=run.run_id,
            ingested_at=run.ingested_at,
            window_start=run.window_start,
            window_end=run.window_end,
            station_count=run.station_count,
        )
    return _env().get_template(f"{template}.sql.j2").render(**context).strip() + "\n"
