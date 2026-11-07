"""The Synapse rendering of the shared SQL.

These tests check that the T-SQL parses (with sqlglot's T-SQL dialect) and
that the generated files committed under infra/generated are current. They
do not prove Synapse accepts the SQL; only a run in Azure does that.
"""

from __future__ import annotations

import re

import pytest
import sqlglot
from conftest import ROOT

from resflow import synapse
from resflow.sqlgen import ADF_RUN_VARS, GOLD_VIEWS, _synapse_macros, render

# Replace Data Factory expressions with sample values so the SQL can be parsed.
SAMPLE = {
    ADF_RUN_VARS.run_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
    ADF_RUN_VARS.ingested_at: "2026-11-07T15:00:00Z",
    ADF_RUN_VARS.window_start: "2026-10-07",
    ADF_RUN_VARS.window_end: "2026-11-06",
    ADF_RUN_VARS.station_count: "12",
}


# sqlglot does not know Synapse's OPENROWSET(BULK ...) form, so each file
# reader is swapped for a table name before parsing. Their exact text is
# checked against the documented shape in test_openrowset_readers.
_M = _synapse_macros()
READERS = {_M[k](): f"ext_{k}" for k in ("bronze", "reference", "staging", "silver")}


def substitute(sql: str) -> str:
    for reader, table in READERS.items():
        sql = sql.replace(reader, table)
    for expr, value in SAMPLE.items():
        sql = sql.replace(expr, value)
    leftover = re.findall(r"@\{[^}]*\}", sql)
    assert leftover == [], f"unexpected ADF expressions: {leftover}"
    return sql


def parse_tsql(sql: str) -> None:
    statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
    assert statements


@pytest.mark.parametrize("name", ["stg_parsed", "checks", *[f"gold_{v}" for v in GOLD_VIEWS]])
def test_synapse_rendering_parses_as_tsql(name: str) -> None:
    parse_tsql(substitute(render(name, "synapse")))


def test_stage_script_parses_as_tsql() -> None:
    parse_tsql(substitute(synapse.stage_run_sql()))


def test_gold_views_script_parses_as_tsql() -> None:
    batches = [b for b in synapse.gold_views_sql().split("\nGO\n") if "CREATE" in b]
    assert len(batches) == len(GOLD_VIEWS)
    for batch in batches:
        parse_tsql(substitute(batch))


def test_synapse_sql_has_no_duckdb_functions() -> None:
    text = "\n".join(synapse.outputs().values())
    for token in ("read_csv", "read_parquet", "date_diff(", "chr(13)", "INTERVAL"):
        assert token not in text


def test_committed_generated_sql_is_current() -> None:
    assert synapse.stale(ROOT / "infra" / "generated") == []


def test_openrowset_readers() -> None:
    bronze = _M["bronze"]()
    assert "PARSER_VERSION = '2.0'" in bronze and "HEADER_ROW = FALSE" in bronze
    # Columns bound by ordinal 1..9, the 9 columns of the CDEC CSV.
    assert re.findall(r"c(\d) VARCHAR\(100\) COLLATE \S+ (\d)", bronze) == [
        (str(i), str(i)) for i in range(1, 10)
    ]
    for k in ("staging", "silver"):
        assert "FORMAT = 'PARQUET'" in _M[k]()


def test_only_known_adf_expressions_appear() -> None:
    for text in synapse.outputs().values():
        substitute(text)
