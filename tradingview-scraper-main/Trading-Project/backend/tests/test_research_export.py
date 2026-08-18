from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json

import pandas as pd
import pytest

from research_export import (
    ResearchExportError,
    _read_raw_archive,
    _write_immutable_raw,
    records_to_canonical,
    validate_canonical,
)


def _frame(rows):
    return pd.DataFrame(rows)


def test_records_to_canonical_reuses_eurusd_price_scaling():
    # One raw record in the exact shape emitted by dukascopy_seeder._fetch_day_1m.
    raw = [
        {
            "ms_off": 0,
            "ts": 1_700_000_000,
            "open_raw": 110000,
            "high_raw": 110050,
            "low_raw": 109950,
            "close_raw": 110025,
            "volume": 2.5,
        }
    ]
    out = records_to_canonical("EURUSD", raw)
    assert list(out.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert str(out["timestamp"].dt.tz) == "UTC"
    assert out.iloc[0]["open"] == pytest.approx(1.1)
    assert out.iloc[0]["close"] == pytest.approx(1.10025)


def test_identical_duplicates_collapse_deterministically():
    ts = pd.Timestamp("2026-01-05T00:00:00Z")
    frame = _frame(
        [
            {"timestamp": ts, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 1.0},
            {"timestamp": ts, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 1.0},
        ]
    )
    out = validate_canonical(frame)
    assert len(out) == 1


def test_conflicting_duplicates_are_hard_error():
    ts = pd.Timestamp("2026-01-05T00:00:00Z")
    frame = _frame(
        [
            {"timestamp": ts, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 1.0},
            {"timestamp": ts, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.16, "volume": 1.0},
        ]
    )
    with pytest.raises(ResearchExportError, match="Conflicting duplicate"):
        validate_canonical(frame)


def test_invalid_ohlc_is_rejected():
    frame = _frame(
        [
            {
                "timestamp": pd.Timestamp("2026-01-05T00:00:00Z"),
                "open": 1.2,
                "high": 1.1,
                "low": 1.0,
                "close": 1.05,
                "volume": 1.0,
            }
        ]
    )
    with pytest.raises(ResearchExportError, match="OHLC"):
        validate_canonical(frame)


def test_raw_archive_is_immutable(tmp_path):
    path = tmp_path / "day.json.gz"
    first = [{"ts": 1, "open_raw": 100}]
    second = [{"ts": 1, "open_raw": 101}]

    _write_immutable_raw(path, first)
    assert _read_raw_archive(path) == first

    with pytest.raises(ResearchExportError, match="Immutable source archive"):
        _write_immutable_raw(path, second)
