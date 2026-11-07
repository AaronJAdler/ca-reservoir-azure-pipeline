from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from resflow.lake import LocalLake

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REFERENCE = ROOT / "reference" / "stations.csv"

# Real CDEC responses, saved byte for byte (CRLF line endings included).
JULY = FIXTURES / "cdec_2026-07-12_2026-07-31.csv"
JULY_STATIONS = ["ORO", "DNP", "EXC", "SHA"]
NOV = FIXTURES / "cdec_2026-11-01_2026-11-06.csv"
NOV_STATIONS = ["ORO", "CMN"]


@pytest.fixture
def lake(tmp_path: Path) -> Iterator[LocalLake]:
    lk = LocalLake(tmp_path / "lake", REFERENCE)
    yield lk
    lk.close()


def july_bytes() -> bytes:
    return JULY.read_bytes()


def nov_bytes() -> bytes:
    return NOV.read_bytes()
