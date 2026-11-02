"""Persistent FX time series.

The history lives in a long-format CSV (date, pair, close) that mirrors the table

    CREATE TABLE fx_timeseries (
        date  DATE,
        pair  VARCHAR(10),
        close FLOAT,
        PRIMARY KEY (date, pair)
    );

CSV instead of a SQLite file keeps the daily commits small and diffable – each run
only appends a handful of lines. `to_sqlite()` materialises the same table on demand.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from .config import RATES_CSV, TIMESERIES_CSV

COLUMNS = ["date", "pair", "close"]


def load(path: Path = TIMESERIES_CSV) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS).astype({"close": float})
    df = pd.read_csv(path, parse_dates=["date"])
    return df[COLUMNS]


def upsert(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge `new` into `existing`; on (date, pair) conflicts the new value wins.
    Weekend quotes (some providers deliver them) are dropped."""
    new = new[COLUMNS].copy()
    new["date"] = pd.to_datetime(new["date"])
    merged = pd.concat([existing, new], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged[merged["date"].dt.dayofweek < 5]
    merged = merged.drop_duplicates(subset=["date", "pair"], keep="last")
    return merged.sort_values(["date", "pair"]).reset_index(drop=True)


def save(df: pd.DataFrame, path: Path = TIMESERIES_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, float_format="%.8g")


def wide(df: pd.DataFrame) -> pd.DataFrame:
    """date × pair matrix of closes, business days only, small gaps forward-filled."""
    matrix = df.pivot(index="date", columns="pair", values="close").sort_index()
    matrix = matrix[matrix.index.dayofweek < 5]
    return matrix.ffill(limit=5)


def to_sqlite(df: pd.DataFrame, db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fx_timeseries ("
            "date DATE, pair VARCHAR(10), close FLOAT, PRIMARY KEY (date, pair))"
        )
        rows = [
            (d.strftime("%Y-%m-%d"), p, float(c))
            for d, p, c in df[COLUMNS].itertuples(index=False)
        ]
        con.executemany("INSERT OR REPLACE INTO fx_timeseries VALUES (?, ?, ?)", rows)


# --- Policy rates ---------------------------------------------------------------
# Stored as changes only (date, ccy, rate in % p. a.): a policy rate is constant for
# weeks, so the file stays tiny. `rates_wide` expands it onto a date index.

RATE_COLUMNS = ["date", "ccy", "rate"]


def load_rates(path: Path = RATES_CSV) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=RATE_COLUMNS).astype({"rate": float})
    return pd.read_csv(path, parse_dates=["date"])[RATE_COLUMNS]


def save_rates(df: pd.DataFrame, path: Path = RATES_CSV) -> None:
    df = df.sort_values(["ccy", "date"])
    changed = df[df.groupby("ccy")["rate"].diff().fillna(1.0) != 0]
    path.parent.mkdir(parents=True, exist_ok=True)
    out = changed.sort_values(["date", "ccy"]).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, float_format="%.6g")


def rates_wide(df: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """date × currency matrix of policy rates as decimals p. a. (5 % → 0.05),
    each rate valid until the next change."""
    wide = df.pivot_table(index="date", columns="ccy", values="rate", aggfunc="last").sort_index()
    return wide.reindex(wide.index.union(index)).ffill().reindex(index) / 100.0


def upsert_rates(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Merge daily policy rates; fresh values win on (date, ccy)."""
    merged = pd.concat([existing, new], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    return merged.drop_duplicates(subset=["date", "ccy"], keep="last").sort_values(["ccy", "date"]).reset_index(drop=True)
