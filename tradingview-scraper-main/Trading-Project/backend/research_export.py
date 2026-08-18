"""Research-grade export adapter for the existing chart engine.

This module deliberately REUSES ``dukascopy_seeder.py`` instead of implementing a
second Dukascopy downloader.  It converts the seeder's decoded 1-minute BID records
into a reproducible, UTC-canonical Parquet dataset for representation learning.

Operational chart storage (SQLite/RAM) and research storage (partitioned Parquet)
remain separate because they have different scaling and reproducibility needs.

Output layout under ``--data-root``::

    raw/dukascopy/EURUSD/1m/bid/year=2024/month=01/2024-01-02.json.gz
    canonical/dukascopy/EURUSD/1m/bid/year=2024/month=01/part.parquet
    manifests/dukascopy/EURUSD/1m/bid/year=2024/month=01.json

The raw archive stores the decoded BI5 source records (integer OHLC + millisecond
UTC-day offset + volume) before price scaling or resampling. Existing raw archives
are immutable: a different payload for an existing path is a hard error.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

import dukascopy_seeder


CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
EXPORT_VERSION = "engine-research-export-v1"


class ResearchExportError(RuntimeError):
    """Raised when a source or canonical-data invariant is violated."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def _raw_archive_path(data_root: Path, symbol: str, day: date) -> Path:
    return (
        Path(data_root)
        / "raw"
        / "dukascopy"
        / symbol
        / "1m"
        / "bid"
        / f"year={day.year:04d}"
        / f"month={day.month:02d}"
        / f"{day.isoformat()}.json.gz"
    )


def _canonical_month_path(data_root: Path, symbol: str, year: int, month: int) -> Path:
    return (
        Path(data_root)
        / "canonical"
        / "dukascopy"
        / symbol
        / "1m"
        / "bid"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "part.parquet"
    )


def _manifest_path(data_root: Path, symbol: str, year: int, month: int) -> Path:
    return (
        Path(data_root)
        / "manifests"
        / "dukascopy"
        / symbol
        / "1m"
        / "bid"
        / f"year={year:04d}"
        / f"month={month:02d}.json"
    )


def _write_immutable_raw(path: Path, records: list[dict]) -> str:
    """Persist decoded source records once and refuse silent mutation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _stable_json_bytes(records)
    expected_payload_hash = hashlib.sha256(payload).hexdigest()

    if path.exists():
        with gzip.open(path, "rb") as fh:
            existing = fh.read()
        existing_hash = hashlib.sha256(existing).hexdigest()
        if existing_hash != expected_payload_hash:
            raise ResearchExportError(
                f"Immutable source archive differs from newly fetched data: {path}"
            )
        return sha256_file(path)

    temp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temp, "wb", compresslevel=6) as fh:
        fh.write(payload)
    temp.replace(path)
    return sha256_file(path)


def _read_raw_archive(path: Path) -> list[dict]:
    with gzip.open(path, "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ResearchExportError(f"Expected list in raw archive: {path}")
    return payload


def load_or_fetch_day(symbol: str, day: date, data_root: Path) -> tuple[list[dict], Path]:
    """Return raw decoded BI5 records, reusing an immutable local archive when present."""
    symbol = symbol.upper()
    if symbol not in dukascopy_seeder.INSTRUMENTS:
        raise ResearchExportError(
            f"{symbol} is not mapped in dukascopy_seeder.INSTRUMENTS. "
            "Add and verify its Dukascopy price multiplier before export."
        )

    raw_path = _raw_archive_path(data_root, symbol, day)
    if raw_path.exists():
        return _read_raw_archive(raw_path), raw_path

    instrument, _pip_mult = dukascopy_seeder.INSTRUMENTS[symbol]
    raw_records = dukascopy_seeder._fetch_day_1m(instrument, day)
    _write_immutable_raw(raw_path, raw_records)
    return raw_records, raw_path


def records_to_canonical(symbol: str, raw_records: list[dict]) -> pd.DataFrame:
    """Scale the existing seeder records and enforce the canonical UTC schema."""
    symbol = symbol.upper()
    _instrument, pip_mult = dukascopy_seeder.INSTRUMENTS[symbol]
    decoded = dukascopy_seeder._decode_prices(raw_records, pip_mult)

    if not decoded:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    frame = pd.DataFrame(decoded)
    frame["timestamp"] = pd.to_datetime(frame["ts"], unit="s", utc=True)
    frame = frame[CANONICAL_COLUMNS].copy()

    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise").astype("float64")

    return validate_canonical(frame)


def validate_canonical(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply research-data invariants without inventing missing observations."""
    missing = set(CANONICAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ResearchExportError(f"Missing canonical columns: {sorted(missing)}")

    out = frame[CANONICAL_COLUMNS].copy()
    if out.empty:
        return out

    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="raise")
    out = out.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    duplicate_mask = out.duplicated(subset=["timestamp"], keep=False)
    if duplicate_mask.any():
        for ts, group in out.loc[duplicate_mask].groupby("timestamp", sort=False):
            values = group[["open", "high", "low", "close", "volume"]].drop_duplicates()
            if len(values) != 1:
                raise ResearchExportError(f"Conflicting duplicate candle at {ts}")
        out = out.drop_duplicates(subset=["timestamp"], keep="first").reset_index(drop=True)

    invalid_ohlc = (
        (out["high"] < out[["open", "close", "low"]].max(axis=1))
        | (out["low"] > out[["open", "close", "high"]].min(axis=1))
        | (out["low"] > out["high"])
    )
    if invalid_ohlc.any():
        raise ResearchExportError(
            f"{int(invalid_ohlc.sum())} rows violate OHLC constraints"
        )

    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise ResearchExportError("FX OHLC prices must be positive")
    if (out["volume"] < 0).any():
        raise ResearchExportError("Volume must be non-negative")

    return out


def _month_days(year: int, month: int) -> list[date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    days = []
    cur = start
    while cur < end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _iter_months(start: date, end_exclusive: date) -> Iterable[tuple[int, int]]:
    cur = date(start.year, start.month, 1)
    while cur < end_exclusive:
        yield cur.year, cur.month
        cur = date(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)


@dataclass(frozen=True)
class MonthExport:
    symbol: str
    year: int
    month: int
    rows: int
    first_timestamp: str | None
    last_timestamp: str | None
    canonical_path: str
    canonical_sha256: str
    raw_files: list[dict]


def export_month(
    symbol: str,
    year: int,
    month: int,
    data_root: Path,
    *,
    requested_start: date | None = None,
    requested_end_exclusive: date | None = None,
    overwrite: bool = False,
) -> MonthExport:
    """Build one atomic monthly canonical Parquet partition."""
    symbol = symbol.upper()
    output = _canonical_month_path(data_root, symbol, year, month)
    manifest_path = _manifest_path(data_root, symbol, year, month)

    if output.exists() and manifest_path.exists() and not overwrite:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return MonthExport(**manifest["export"])

    frames: list[pd.DataFrame] = []
    raw_entries: list[dict] = []

    for day in _month_days(year, month):
        if requested_start and day < requested_start:
            continue
        if requested_end_exclusive and day >= requested_end_exclusive:
            continue

        raw_records, raw_path = load_or_fetch_day(symbol, day, data_root)
        raw_entries.append(
            {
                "date": day.isoformat(),
                "path": str(raw_path),
                "sha256": sha256_file(raw_path),
                "records": len(raw_records),
            }
        )
        if raw_records:
            frames.append(records_to_canonical(symbol, raw_records))

    if frames:
        frame = validate_canonical(pd.concat(frames, ignore_index=True))
    else:
        frame = pd.DataFrame(columns=CANONICAL_COLUMNS)

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    frame.to_parquet(temp, index=False, engine="pyarrow")
    temp.replace(output)

    export = MonthExport(
        symbol=symbol,
        year=year,
        month=month,
        rows=len(frame),
        first_timestamp=None if frame.empty else frame["timestamp"].iloc[0].isoformat(),
        last_timestamp=None if frame.empty else frame["timestamp"].iloc[-1].isoformat(),
        canonical_path=str(output),
        canonical_sha256=sha256_file(output),
        raw_files=raw_entries,
    )

    manifest = {
        "export_version": EXPORT_VERSION,
        "source": "Dukascopy datafeed BID_candles_min_1.bi5",
        "source_adapter": "backend/dukascopy_seeder.py",
        "raw_archive_format": "gzip JSON of decoded BI5 integer records before price scaling",
        "canonical_schema": CANONICAL_COLUMNS,
        "timestamp_timezone": "UTC",
        "missing_data_policy": "preserve gaps; never synthesize source candles",
        "export": asdict(export),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return export


def export_range(
    symbol: str,
    start: date,
    end_exclusive: date,
    data_root: Path,
    *,
    overwrite: bool = False,
) -> list[MonthExport]:
    if start >= end_exclusive:
        raise ValueError("start must be earlier than end")
    return [
        export_month(
            symbol,
            year,
            month,
            data_root,
            requested_start=start,
            requested_end_exclusive=end_exclusive,
            overwrite=overwrite,
        )
        for year, month in _iter_months(start, end_exclusive)
    ]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export existing Dukascopy engine data into canonical research Parquet."
    )
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date, help="exclusive YYYY-MM-DD")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    results = export_range(
        args.symbol,
        args.start,
        args.end,
        args.data_root,
        overwrite=args.overwrite,
    )
    for result in results:
        print(
            f"{result.symbol} {result.year:04d}-{result.month:02d}: "
            f"rows={result.rows} path={result.canonical_path}"
        )


if __name__ == "__main__":
    main()
