"""Data providers. Every fetcher returns a long DataFrame (date, pair, close) quoted
as units of currency per 1 USD, i.e. pair "USDEUR"."""

import io
import time
from datetime import date, timedelta

import pandas as pd
import requests

from .config import CURRENCIES, POLICY_RATE_AREAS, pair

TIMEOUT = 30


def _frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", "pair", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


# --- ECB reference rates ---------------------------------------------------

def _get(url: str, params: dict, attempts: int = 3) -> requests.Response:
    """GET with a few retries – the job downloads ~28 yearly chunks every day, so one
    hiccup must not fail the whole run."""
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_ezb(start: date, end: date, currencies: list[str] = CURRENCIES) -> pd.DataFrame:
    """EZB reference rates (via the free api.frankfurter.app mirror, no API key).
    Requested in yearly chunks so long ranges stay at daily granularity."""
    rows = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=364), end)
        resp = _get(
            f"https://api.frankfurter.app/{chunk_start}..{chunk_end}",
            {"base": "USD", "symbols": ",".join(currencies)},
        )
        rows += [
            (day, pair(ccy), value)
            for day, rates in resp.json()["rates"].items()
            for ccy, value in rates.items()
        ]
        chunk_start = chunk_end + timedelta(days=1)
    return _frame(rows)


# --- Policy rates (carry) --------------------------------------------------

def fetch_policy_rates(start: date, currencies: list[str] | None = None) -> pd.DataFrame:
    """Central bank policy rates in % p. a. from the BIS data portal (free, no key),
    daily, as long DataFrame (date, ccy, rate). One request for all currencies."""
    currencies = currencies or list(POLICY_RATE_AREAS)
    area_to_ccy = {POLICY_RATE_AREAS[c]: c for c in currencies}
    resp = _get(
        f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.{'+'.join(area_to_ccy)}",
        {"startPeriod": start.isoformat(), "format": "csv"},
    )
    raw = pd.read_csv(io.StringIO(resp.text))
    needed = {"REF_AREA", "TIME_PERIOD", "OBS_VALUE"}
    if not needed <= set(raw.columns):
        raise ValueError(f"Unexpected BIS response, columns: {list(raw.columns)}")
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["TIME_PERIOD"]),
        "ccy": raw["REF_AREA"].map(area_to_ccy),
        "rate": pd.to_numeric(raw["OBS_VALUE"], errors="coerce"),
    })
    return df.dropna().sort_values(["ccy", "date"]).reset_index(drop=True)
