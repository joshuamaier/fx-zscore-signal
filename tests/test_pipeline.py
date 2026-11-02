import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_analysis import analysis, charts, config, store  # noqa: E402

START_RATES = {"EUR": 0.9, "JPY": 140, "GBP": 0.78, "CNY": 7.1, "CHF": 0.88,
               "CAD": 1.35, "AUD": 1.5, "NZD": 1.65, "SEK": 10.5, "NOK": 10.6}


def synthetic_history(days: int = 1400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-09-28", periods=days)
    rows = []
    for ccy, start in START_RATES.items():
        path = start * np.exp(np.cumsum(rng.normal(0, 0.005, days)))
        rows += [(d, config.pair(ccy), v) for d, v in zip(dates, path)]
    return pd.DataFrame(rows, columns=store.COLUMNS)


def test_upsert_prefers_new_values():
    old = synthetic_history(10)
    new = old.tail(1).assign(close=1.0)
    merged = store.upsert(old, new)
    assert len(merged) == len(old)
    last = merged[(merged.date == new.date.iloc[0]) & (merged.pair == new.pair.iloc[0])]
    assert last.close.iloc[0] == 1.0


def test_cross_prices_against_eur():
    matrix = store.wide(synthetic_history(5))
    prices = analysis.cross_prices(matrix, "EUR")
    row = matrix.iloc[-1]
    # 1 USD in EUR is the stored USDEUR rate; 1 JPY in EUR = USDEUR / USDJPY.
    assert np.isclose(prices["USD"].iloc[-1], row["USDEUR"])
    assert np.isclose(prices["JPY"].iloc[-1], row["USDEUR"] / row["USDJPY"])
    assert "EUR" not in prices.columns


def test_run_and_outputs(tmp_path):
    hist = synthetic_history()
    csv = tmp_path / "fx.csv"
    store.save(hist, csv)
    result = analysis.run(store.wide(store.load(csv)))
    assert list(result.returns.columns) == list(config.HORIZONS)
    assert result.returns.notna().all().all()
    summary = analysis.summary(result)
    json.dumps(summary)
    assert summary["as_of"] == "2026-09-28"
    assert len(summary["currencies"]) == 10
    assert "stärkste" in summary["interpretation"]
    png = tmp_path / "chart.png"
    charts.render(result, png, "test")
    assert png.stat().st_size > 10_000


def test_short_history_yields_nan_not_error():
    result = analysis.run(store.wide(synthetic_history(30)))
    assert result.returns["5J"].isna().all()
    assert analysis.summary(result)["currencies"][0]["returns"]["5J"] is None


def test_sqlite_export(tmp_path):
    import sqlite3
    hist = synthetic_history(10)
    db = tmp_path / "fx.sqlite"
    store.to_sqlite(hist, db)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM fx_timeseries").fetchone()[0] == len(hist)


def test_zscore_matches_definition():
    prices = pd.DataFrame({"X": np.r_[np.ones(251), 2.0], "Y": np.linspace(1, 2, 252)})
    z = analysis.zscores(prices, window=252)
    tail = prices["X"]
    assert np.isclose(z["X"], (2.0 - tail.mean()) / tail.std())
    assert z["X"] > config.ZSCORE_THRESHOLD
    assert analysis.zscore_signal(z["X"]) == "stark"
    assert analysis.zscore_signal(-2.5) == "schwach"
    assert analysis.zscore_signal(0.3) == "neutral"
    assert analysis.zscore_signal(float("nan")) == "n/a"


def test_zscore_needs_full_window():
    z = analysis.zscores(pd.DataFrame({"X": np.arange(10.0)}), window=252)
    assert z.isna().all()


def test_summary_contains_zscore():
    summary = analysis.summary(analysis.run(store.wide(synthetic_history())))
    first = summary["currencies"][0]
    assert first["zscore"] is not None
    assert first["signal"] in {"stark", "schwach", "neutral"}
    assert "Z-Score" in summary["interpretation"] or "Extremsignale" in summary["interpretation"]


def test_upsert_drops_weekends():
    rows = pd.DataFrame({"date": pd.to_datetime(["2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28"]),
                         "pair": "USDEUR", "close": [0.9, 0.91, 0.92, 0.93]})
    merged = store.upsert(pd.DataFrame(columns=store.COLUMNS), rows)
    assert list(merged.date.dt.strftime("%Y-%m-%d")) == ["2026-09-25", "2026-09-28"]


def test_chart_with_short_history(tmp_path):
    result = analysis.run(store.wide(synthetic_history(40)))
    png = tmp_path / "short.png"
    charts.render(result, png, "test")
    assert png.stat().st_size > 10_000


def test_ezb_is_fetched_in_yearly_chunks():
    from datetime import date
    from unittest import mock

    from fx_analysis import sources

    calls = []

    class Resp:
        def __init__(self, url):
            self.day = url.rsplit("/", 1)[1].split("..")[0]

        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {self.day: {"EUR": 0.9}}}

    def fake_get(url, params, timeout):
        calls.append(url)
        return Resp(url)

    with mock.patch.object(sources.requests, "get", side_effect=fake_get):
        df = sources.fetch_ezb(date(2021, 9, 20), date(2026, 9, 29), ["EUR"])
    assert len(calls) == 6
    assert calls[0].endswith("2021-09-20..2022-09-19")
    assert calls[-1].endswith("..2026-09-29")
    assert len(df) == 6
