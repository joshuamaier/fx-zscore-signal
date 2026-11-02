"""Währungsquote: over-/underweight each currency of a basket by its z-score and
backtest that against the basket itself.

Works on the public data stored in `data/fx_timeseries.csv` (EZB reference rates) and,
optionally, on central bank policy rates (`data/policy_rates.csv`) for the carry.
The rules:

    z      = (log(price) - rolling mean) / rolling std (ddof=0)   per currency
    factor = 1 - clip(z, -cap, +cap) / cap                          0 … 2
    weight = SMA(factor, smoothing).shift(lag) × base weight, renormalised to sum 1

At its own mean (z = 0) a currency sits exactly at its base weight; strong against its
history (z = +cap) it drops to 0 %, weak (z = -cap) it rises to twice its base weight.
The basket is always fully invested: the raw weights are renormalised to 100 % every
day, so "cheap" means a larger share of the same basket, not extra exposure.

Perspective is the analysis base (`ANALYSIS_BASE`, EUR): prices are the value of one
unit in EUR, returns are what a EUR investor earns holding the currency: the spot
return, plus – when policy rates are passed as `rates` – the interest of that currency
(carry, deposit at the policy rate). The base currency itself is part of the basket
as the numeraire: its price is constantly 1, its z-score is 0 by definition, so it
always stays at its base weight; it earns the EUR rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import store
from .analysis import cross_prices, universe
from .config import (
    ANALYSIS_BASE,
    BENCHMARKS,
    CURRENCIES,
    CURRENCY_NAMES,
    QUOTE_CAP,
    QUOTE_LAG,
    QUOTE_LOOKBACK,
    QUOTE_COST_BP,
    QUOTE_SMOOTHING,
    TRADE_SHARES,
    TRADING_DAYS,
    pair,
)


# --- 1  Signal ----------------------------------------------------------------

def basket_prices(matrix: pd.DataFrame, base: str = ANALYSIS_BASE, include_base: bool = True) -> pd.DataFrame:
    """Value of one unit of each basket currency in `base`, from the stored USD matrix.

    With `include_base` the base currency joins the basket as numeraire (constant 1.0),
    as the numeraire.
    """
    required = [pair(c) for c in CURRENCIES]
    missing = [p for p in required if p not in matrix.columns]
    if missing:
        raise ValueError(f"Missing pairs in time series: {missing}")
    prices = cross_prices(matrix[required], base)
    if include_base:
        prices.insert(0, base, 1.0)
    return prices[([base] if include_base else []) + universe(base)]


def signal(prices: pd.DataFrame, lookback: int = QUOTE_LOOKBACK, numeraire: str | None = ANALYSIS_BASE) -> pd.DataFrame:
    """z-score of each currency's log price against its own rolling mean and std.

    Log prices keep up- and down-moves symmetric; std is biased (ddof=0).
    The numeraire's log price is constantly 0, its std 0 – its z-score is set to 0
    instead of NaN: by definition it sits exactly at itself.
    """
    log_prices = np.log(prices.astype(float))
    lookback = int(lookback)
    mean = log_prices.rolling(lookback).mean()
    std = log_prices.rolling(lookback).std(ddof=0)
    z = (log_prices - mean) / std.where(std > 0)
    if numeraire in z.columns:
        z[numeraire] = 0.0
    return z


def weight_factor(z: pd.DataFrame, cap: float = QUOTE_CAP) -> pd.DataFrame:
    """Position table as one line: z = -cap → 2.0, z = 0 → 1.0, z = +cap → 0.0.

    The end points 0 and 2 do not depend on `cap`; it only sets how many standard
    deviations it takes to reach them.
    """
    cap = float(cap)
    if cap <= 0:
        raise ValueError("cap must be greater than 0.")
    return 1.0 - pd.DataFrame(z).clip(lower=-cap, upper=cap) / cap


def base_weights(currencies: list[str], benchmark: str = "equal") -> pd.Series:
    """Base weight per currency: `equal` (1/N) or `trade` (BIS turnover shares,
    renormalised over the selected currencies so the basket is always complete)."""
    currencies = list(currencies)
    if benchmark == "trade":
        raw = pd.Series({c: TRADE_SHARES.get(c, 0.0) for c in currencies}, dtype=float)
        if raw.sum() <= 0:
            raise ValueError("No trade shares for the selected currencies.")
        return raw / raw.sum()
    if benchmark != "equal":
        raise ValueError(f"Unknown benchmark {benchmark!r}: expected 'equal' or 'trade'.")
    return pd.Series(1.0 / len(currencies), index=currencies)


# --- 2  Backtest ----------------------------------------------------------------

def backtest(
    prices: pd.DataFrame,
    lookback: int = QUOTE_LOOKBACK,
    cap: float = QUOTE_CAP,
    smoothing: int = QUOTE_SMOOTHING,
    lag: int = QUOTE_LAG,
    benchmark: str = "equal",
    cost_bp: float = QUOTE_COST_BP,
    numeraire: str | None = ANALYSIS_BASE,
    freq: int = TRADING_DAYS,
    rates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Währungsquote against the basket with fixed base weights (the "buy and hold").

    Returns one row per business day with `strategy` and `benchmark` (daily returns),
    `turnover`, `costs`, the value lines `value_*` and drawdowns `dd_*`. `.attrs`
    carries the settings plus the per-currency matrices `weights`, `z` and `factor`.

    The backtest starts on the first day on which every currency has a weight –
    roughly lookback + smoothing + lag business days after the shortest history
    begins – so both lines start together. A later gap in one currency (after the
    store's own 5-day forward fill) keeps the previous weights rather than silently
    dropping below 100 %.

    `rates` (date × currency, decimals p. a., see `store.rates_wide`) switches the
    carry on: each currency then also earns its policy rate, accrued on every calendar
    day (act/365, weekends included). Without it, returns are pure spot returns.
    """
    prices = prices.astype(float).sort_index()
    currencies = list(prices.columns)
    if len(currencies) < 2:
        raise ValueError("The backtest needs at least two currencies.")

    z = signal(prices, lookback, numeraire)
    factor = weight_factor(z, cap).rolling(int(smoothing)).mean()
    base = base_weights(currencies, benchmark)
    returns = prices.pct_change(fill_method=None)
    if rates is not None:
        missing = [c for c in currencies if c not in rates.columns]
        if missing:
            raise ValueError(f"No policy rates for: {missing}")
        # Interest runs on every calendar day (act/365): the Monday return also carries
        # the weekend, so each business-day step accrues for the days since the previous one.
        days = prices.index.to_series().diff().dt.days.fillna(1).astype(float)
        accrual = rates.reindex(prices.index).ffill().shift(1)[currencies].mul(days, axis=0) / 365.0
        returns = returns + accrual.fillna(0.0)

    raw = factor.shift(int(lag)) * base
    # skipna=False keeps warm-up days NaN so the start detection below works.
    total = raw.sum(axis=1, skipna=False)
    weights = raw.div(total.where(total > 0), axis=0)
    all_zero = total.notna() & (total <= 0)  # practically never: every factor at 0
    if all_zero.any():
        weights.loc[all_zero] = np.tile(base.to_numpy(), (int(all_zero.sum()), 1))

    complete = weights.dropna(how="any")
    if complete.empty:
        raise ValueError(
            "No usable weights: the history is too short. The signal needs about "
            f"lookback + smoothing + lag = {int(lookback) + int(smoothing) + int(lag)} "
            "business days for the currency with the shortest history."
        )
    start = complete.index[0]
    weights = weights.loc[start:].ffill()
    returns = returns.loc[start:].fillna(0.0)

    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = float(weights.iloc[0].sum())  # building the first position
    costs = turnover * (float(cost_bp) / 1e4)

    d = pd.DataFrame({"turnover": turnover, "costs": costs})
    d["strategy"] = (weights * returns).sum(axis=1) - costs
    d["benchmark"] = (base * returns).sum(axis=1)
    # First day: the position is built at the close, there is no return yet.
    d.loc[d.index[0], ["strategy", "benchmark"]] = 0.0
    for col in ("strategy", "benchmark"):
        growth = (1.0 + d[col]).clip(lower=0.0)
        d[f"value_{col}"] = growth.cumprod()
        d[f"dd_{col}"] = d[f"value_{col}"] / d[f"value_{col}"].cummax() - 1.0

    d.attrs.update(
        lookback=int(lookback), cap=float(cap), smoothing=int(smoothing), lag=int(lag),
        benchmark=benchmark, cost_bp=float(cost_bp), freq=int(freq), numeraire=numeraire,
        carry=rates is not None,
        base_weights=base, weights=weights, z=z.loc[start:], factor=factor.loc[start:],
        prices=prices.loc[start:],
    )
    return d


def run(
    matrix: pd.DataFrame,
    base: str = ANALYSIS_BASE,
    include_base: bool = True,
    rates: pd.DataFrame | None = None,
    **params,
) -> pd.DataFrame:
    """Stored USD matrix → basket prices → backtest (keyword args go to `backtest`).
    `rates` is the long policy-rate table from `store.load_rates()`; with it the
    backtest includes the carry."""
    prices = basket_prices(matrix, base, include_base)
    wide = None if rates is None or rates.empty else store.rates_wide(rates, prices.index)
    return backtest(prices, numeraire=base if include_base else None, rates=wide, **params)


# --- 3  Evaluation ---------------------------------------------------------------

def metrics(returns: pd.Series, freq: int = TRADING_DAYS) -> dict:
    """Usual key figures of a daily return series."""
    r = pd.Series(returns, dtype=float).dropna()
    empty = dict(days=0, years=np.nan, total=np.nan, cagr=np.nan, vol=np.nan,
                 sharpe=np.nan, sortino=np.nan, max_dd=np.nan, calmar=np.nan,
                 worst_day=np.nan, hit_rate=np.nan)
    if len(r) < 2:
        return empty
    years = len(r) / freq
    value = float((1.0 + r).prod())
    cagr = value ** (1.0 / years) - 1.0 if value > 0 else np.nan
    std = r.std(ddof=1)
    curve = (1.0 + r).cumprod()
    max_dd = float((curve / curve.cummax() - 1.0).min())
    downside = float(np.sqrt((r.clip(upper=0.0) ** 2).mean()))
    return dict(
        days=int(len(r)), years=years, total=value - 1.0, cagr=cagr,
        vol=float(std * np.sqrt(freq)),
        # Risk-free rate is 0: the backtest is spot-only, so returns are excess-like.
        sharpe=float(r.mean() / std * np.sqrt(freq)) if std > 0 else np.nan,
        sortino=float(r.mean() / downside * np.sqrt(freq)) if downside > 0 else np.nan,
        max_dd=max_dd,
        calmar=float(cagr / -max_dd) if max_dd < 0 and not np.isnan(cagr) else np.nan,
        worst_day=float(r.min()),
        hit_rate=float((r > 0).mean()),
    )


METRIC_LABELS = {
    "years": "Zeitraum (Jahre)",
    "total": "Gesamtrendite",
    "cagr": "Rendite p. a.",
    "vol": "Volatilität p. a.",
    "sharpe": "Sharpe-Ratio",
    "sortino": "Sortino-Ratio",
    "max_dd": "Max. Drawdown",
    "calmar": "Calmar-Ratio",
    "worst_day": "Schlechtester Tag",
    "hit_rate": "Positive Tage",
}


def annual_returns(bt: pd.DataFrame) -> pd.DataFrame:
    """Calendar-year returns of strategy and benchmark (first/last year are partial)."""
    out = {col: (1.0 + bt[col]).groupby(bt.index.year).prod() - 1.0 for col in ("strategy", "benchmark")}
    d = pd.DataFrame(out)
    d["diff"] = d["strategy"] - d["benchmark"]
    d.index.name = "year"
    return d


def benchmark_label(bt: pd.DataFrame) -> str:
    return BENCHMARKS.get(bt.attrs.get("benchmark", "equal"), BENCHMARKS["equal"])


def comparison(bt: pd.DataFrame) -> pd.DataFrame:
    """Key figures Währungsquote vs. basket, rows = metric (raw numbers)."""
    freq = bt.attrs.get("freq", TRADING_DAYS)
    s, b = metrics(bt["strategy"], freq), metrics(bt["benchmark"], freq)
    label = benchmark_label(bt)
    d = pd.DataFrame(
        [(name, s[key], b[key]) for key, name in METRIC_LABELS.items()],
        columns=["Kennzahl", "Währungsquote", label],
    ).set_index("Kennzahl")
    d["Differenz"] = d["Währungsquote"] - d[label]
    return d


def signal_status(bt: pd.DataFrame) -> pd.DataFrame:
    """Latest state per currency, sorted from strongest underweight (z high,
    "expensive") to strongest overweight (z low, "cheap")."""
    z = bt.attrs["z"].iloc[-1]
    d = pd.DataFrame({
        "Währung": [CURRENCY_NAMES.get(c, c) for c in z.index],
        "Kurs": bt.attrs["prices"].iloc[-1].reindex(z.index),
        "z-Score": z,
        "Gewichtsfaktor": bt.attrs["factor"].iloc[-1],
        "Grundgewicht": bt.attrs["base_weights"].reindex(z.index),
        "Gewicht": bt.attrs["weights"].iloc[-1],
    }, index=z.index)
    return d.sort_values("z-Score", ascending=False)


def summary(bt: pd.DataFrame, base: str = ANALYSIS_BASE) -> dict:
    """JSON-ready digest for the blog: settings, key figures and current weights."""
    def clean(x):
        if pd.isna(x):
            return None
        return int(x) if isinstance(x, (int, np.integer)) else round(float(x), 6)

    freq = bt.attrs["freq"]
    status = signal_status(bt)
    return {
        "as_of": bt.index[-1].strftime("%Y-%m-%d"),
        "start": bt.index[0].strftime("%Y-%m-%d"),
        "base": base,
        "benchmark": bt.attrs["benchmark"],
        "benchmark_name": benchmark_label(bt),
        "settings": {k: bt.attrs[k] for k in ("lookback", "cap", "smoothing", "lag", "cost_bp", "carry")},
        "strategy": {k: clean(v) for k, v in metrics(bt["strategy"], freq).items()},
        "benchmark_metrics": {k: clean(v) for k, v in metrics(bt["benchmark"], freq).items()},
        "turnover_pa": clean(bt["turnover"].sum() / (len(bt) / freq)),
        "annual_returns": [
            {"year": int(y), **{k: clean(v) for k, v in row.items()}}
            for y, row in annual_returns(bt).iterrows()
        ],
        "currencies": [
            {
                "code": code,
                "name": row["Währung"],
                "price": clean(row["Kurs"]),
                "zscore": clean(row["z-Score"]),
                "factor": clean(row["Gewichtsfaktor"]),
                "base_weight": clean(row["Grundgewicht"]),
                "weight": clean(row["Gewicht"]),
            }
            for code, row in status.iterrows()
        ],
    }
