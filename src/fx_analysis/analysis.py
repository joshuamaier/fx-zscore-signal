"""FX analysis: performance of each currency against the analysis base across several
horizons plus a simple trend filter (distance to the 200-day moving average)."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    ANALYSIS_BASE,
    CURRENCIES,
    CURRENCY_NAMES,
    HORIZONS,
    STORE_BASE,
    TREND_WINDOW,
    ZSCORE_THRESHOLD,
    ZSCORE_WINDOW,
    pair,
)


@dataclass
class Result:
    as_of: pd.Timestamp
    base: str
    prices: pd.DataFrame  # date × currency: value of 1 unit in base currency
    returns: pd.DataFrame  # currency × horizon, decimal returns
    trend: pd.DataFrame  # currency × [dist_ma, above_ma, ma_fast_above_slow, zscore, signal]


def universe(base: str = ANALYSIS_BASE) -> list[str]:
    return [c for c in [STORE_BASE, *CURRENCIES] if c != base]


def cross_prices(matrix: pd.DataFrame, base: str = ANALYSIS_BASE) -> pd.DataFrame:
    """Convert USD-quoted rates (units per USD) into the value of 1 unit in `base`."""
    per_usd = matrix.rename(columns=lambda p: p[len(STORE_BASE):])
    per_usd[STORE_BASE] = 1.0
    base_per_usd = per_usd[base]
    prices = pd.DataFrame(
        {c: base_per_usd / per_usd[c] for c in universe(base)}, index=matrix.index
    )
    return prices.dropna(how="all")


def horizon_returns(prices: pd.DataFrame) -> pd.DataFrame:
    last = prices.iloc[-1]
    as_of = prices.index[-1]
    out = {}
    for label, days in HORIZONS.items():
        if days is None:
            prior = prices[prices.index.year < as_of.year]
            ref = prior.iloc[-1] if len(prior) else pd.Series(np.nan, index=prices.columns)
        elif len(prices) > days:
            ref = prices.iloc[-1 - days]
        else:
            ref = pd.Series(np.nan, index=prices.columns)
        out[label] = last / ref - 1
    return pd.DataFrame(out)


def zscores(prices: pd.DataFrame, window: int = ZSCORE_WINDOW) -> pd.Series:
    tail = prices.tail(window)
    if len(tail) < window:
        return pd.Series(np.nan, index=prices.columns)
    return (tail.iloc[-1] - tail.mean()) / tail.std()


def zscore_signal(z: float, threshold: float = ZSCORE_THRESHOLD) -> str:
    if pd.isna(z):
        return "n/a"
    if z >= threshold:
        return "stark"
    if z <= -threshold:
        return "schwach"
    return "neutral"


def trend_signals(prices: pd.DataFrame, window: int = TREND_WINDOW) -> pd.DataFrame:
    ma_slow = prices.rolling(window, min_periods=window).mean().iloc[-1]
    ma_fast = prices.rolling(50, min_periods=50).mean().iloc[-1]
    last = prices.iloc[-1]
    z = zscores(prices)
    return pd.DataFrame(
        {
            "dist_ma": last / ma_slow - 1,
            "above_ma": last > ma_slow,
            "ma_fast_above_slow": ma_fast > ma_slow,
            "zscore": z,
            "signal": z.map(zscore_signal),
        }
    )


def run(matrix: pd.DataFrame, base: str = ANALYSIS_BASE) -> Result:
    required = [pair(c) for c in CURRENCIES]
    missing = [p for p in required if p not in matrix.columns]
    if missing:
        raise ValueError(f"Missing pairs in time series: {missing}")
    prices = cross_prices(matrix[required], base)
    return Result(
        as_of=prices.index[-1],
        base=base,
        prices=prices,
        returns=horizon_returns(prices),
        trend=trend_signals(prices),
    )


def _num(x: float, signed: bool = False) -> str:
    return f"{x:{'+' if signed else ''}.1f}".replace(".", ",").replace("-", "−")


def _pct(x: float) -> str:
    return f"{x * 100:+.1f} %".replace(".", ",").replace("-", "−")


def interpretation(result: Result, horizon: str = "1M") -> str:
    """Short, data-driven reading in German for the blog post."""
    base_name = CURRENCY_NAMES[result.base]
    r = result.returns[horizon].dropna().sort_values()
    if r.empty:
        return ""
    best, worst = r.index[-1], r.index[0]
    above = int(result.trend["above_ma"].sum())
    total = len(result.trend)
    text = (
        f"Über den letzten Monat war {CURRENCY_NAMES[best]} ({best}) mit {_pct(r[best])} "
        f"die stärkste und {CURRENCY_NAMES[worst]} ({worst}) mit {_pct(r[worst])} die schwächste "
        f"Währung gegenüber dem {base_name}. {above} von {total} Währungen notieren über ihrem "
        f"{TREND_WINDOW}-Tage-Durchschnitt."
    )
    flagged = result.trend[result.trend["signal"].isin(["stark", "schwach"])]["zscore"]
    if flagged.empty:
        text += f" Kein Z-Score liegt jenseits von ±{_num(ZSCORE_THRESHOLD)} – aktuell keine Extremsignale."
    else:
        items = ", ".join(f"{c} ({_num(z, signed=True)})" for c, z in flagged.sort_values().items())
        text += f" Z-Score-Signal (|z| ≥ {_num(ZSCORE_THRESHOLD)}): {items}."
    return text


def summary(result: Result) -> dict:
    def clean(x):
        return None if pd.isna(x) else round(float(x), 6)

    return {
        "as_of": result.as_of.strftime("%Y-%m-%d"),
        "base": result.base,
        "horizons": list(HORIZONS),
        "zscore_window": ZSCORE_WINDOW,
        "zscore_threshold": ZSCORE_THRESHOLD,
        "interpretation": interpretation(result),
        "currencies": [
            {
                "code": c,
                "name": CURRENCY_NAMES[c],
                "returns": {h: clean(result.returns.at[c, h]) for h in HORIZONS},
                "dist_ma200": clean(result.trend.at[c, "dist_ma"]),
                "above_ma200": bool(result.trend.at[c, "above_ma"]),
                "zscore": clean(result.trend.at[c, "zscore"]),
                "signal": result.trend.at[c, "signal"],
            }
            for c in result.returns.index
        ],
    }
