import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_analysis import charts, config, quote, store  # noqa: E402

START_RATES = {"EUR": 0.9, "JPY": 140, "GBP": 0.78, "CNY": 7.1, "CHF": 0.88,
               "CAD": 1.35, "AUD": 1.5, "NZD": 1.65, "SEK": 10.5, "NOK": 10.6}

FAST = dict(lookback=126, smoothing=5, lag=1)


def synthetic_matrix(days: int = 800, seed: int = 3) -> pd.DataFrame:
    """Mean-reverting USD rates (OU in log space) – the property the signal lives on."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-09-28", periods=days)
    cols = {}
    for ccy, start in START_RATES.items():
        level = np.zeros(days)
        for i in range(1, days):
            level[i] = 0.99 * level[i - 1] + rng.normal(0, 0.006)
        cols[config.pair(ccy)] = start * np.exp(level)
    return pd.DataFrame(cols, index=dates)


def prices(days: int = 800) -> pd.DataFrame:
    return quote.basket_prices(synthetic_matrix(days))


def test_basket_contains_base_as_numeraire():
    p = prices(50)
    assert list(p.columns[:2]) == ["EUR", "USD"]
    assert len(p.columns) == 11
    assert (p["EUR"] == 1.0).all()
    m = synthetic_matrix(50)
    assert np.isclose(p["JPY"].iloc[-1], m["USDEUR"].iloc[-1] / m["USDJPY"].iloc[-1])
    assert "EUR" not in quote.basket_prices(m, include_base=False).columns


@pytest.mark.parametrize("cap", [0.5, 2.0, 3.0])
def test_weight_factor_hits_corners_for_any_cap(cap):
    z = pd.DataFrame({"X": [-cap * 2, -cap, 0.0, cap, cap * 2]})
    assert list(quote.weight_factor(z, cap)["X"]) == [2.0, 2.0, 1.0, 0.0, 0.0]


def test_weight_factor_rejects_nonpositive_cap():
    with pytest.raises(ValueError):
        quote.weight_factor(pd.DataFrame({"X": [0.0]}), 0)


def test_signal_matches_definition_and_numeraire_is_zero():
    p = prices(300)
    z = quote.signal(p, lookback=100)
    tail = np.log(p["USD"].iloc[-100:])
    expected = (tail.iloc[-1] - tail.mean()) / tail.std(ddof=0)
    assert np.isclose(z["USD"].iloc[-1], expected)
    assert (z["EUR"] == 0.0).all()
    assert z["USD"].iloc[:99].isna().all()


def test_base_weights():
    eq = quote.base_weights(["EUR", "USD", "JPY", "GBP"])
    assert np.allclose(eq, 0.25)
    tr = quote.base_weights(["USD", "EUR"], "trade")
    assert np.isclose(tr.sum(), 1.0)
    assert np.isclose(tr["USD"] / tr["EUR"], 89.2 / 28.9)
    with pytest.raises(ValueError):
        quote.base_weights(["USD"], "market")


@pytest.mark.parametrize("benchmark", ["equal", "trade"])
def test_backtest_is_always_fully_invested(benchmark):
    bt = quote.backtest(prices(), benchmark=benchmark, **FAST)
    assert np.allclose(bt.attrs["weights"].sum(axis=1), 1.0)
    assert (bt.attrs["weights"] >= 0).all().all()
    assert bt["strategy"].iloc[0] == 0.0 and bt["value_benchmark"].iloc[0] == 1.0
    assert bt.index[0] == prices().index[FAST["lookback"] + FAST["smoothing"] - 2 + FAST["lag"]]


def test_numeraire_stays_near_its_base_weight_share():
    bt = quote.backtest(prices(), **FAST)
    # Its raw factor is exactly 1; only the renormalisation moves its weight.
    assert np.allclose(bt.attrs["factor"]["EUR"], 1.0)


def test_no_look_ahead():
    p = prices()
    bt = quote.backtest(p, **FAST)
    shocked = p.copy()
    shocked.iloc[-1, 1:] *= 1.5          # today's close must not move today's weights
    bt2 = quote.backtest(shocked, **FAST)
    pd.testing.assert_series_equal(bt.attrs["weights"].iloc[-1], bt2.attrs["weights"].iloc[-1])


def test_truncated_history_gives_same_weights():
    p = prices()
    full = quote.backtest(p, **FAST).attrs["weights"]
    cut = quote.backtest(p.iloc[:-100], **FAST).attrs["weights"]
    pd.testing.assert_frame_equal(full.loc[cut.index], cut)


def test_benchmark_is_base_weighted_return():
    p = prices()
    bt = quote.backtest(p, benchmark="trade", **FAST)
    r = p.pct_change().loc[bt.index[1:]]
    expected = (r * bt.attrs["base_weights"]).sum(axis=1)
    assert np.allclose(bt["benchmark"].iloc[1:], expected)


def test_costs_reduce_strategy():
    p = prices()
    free = quote.backtest(p, **FAST)
    paid = quote.backtest(p, cost_bp=10, **FAST)
    assert paid["value_strategy"].iloc[-1] < free["value_strategy"].iloc[-1]
    assert np.allclose(paid["costs"], free["turnover"] * 10 / 1e4)


def test_too_short_history_raises():
    with pytest.raises(ValueError, match="too short"):
        quote.backtest(prices(100), lookback=1008)
    with pytest.raises(ValueError, match="two currencies"):
        quote.backtest(prices(300)[["USD"]], **FAST)


def test_comparison_status_summary():
    bt = quote.backtest(prices(), **FAST)
    comp = quote.comparison(bt)
    assert list(comp.columns) == ["Währungsquote", "Gleichgewichteter Korb", "Differenz"]
    assert np.isclose(comp.loc["Rendite p. a.", "Differenz"],
                      comp.loc["Rendite p. a.", "Währungsquote"] - comp.loc["Rendite p. a.", "Gleichgewichteter Korb"])
    status = quote.signal_status(bt)
    assert status["z-Score"].is_monotonic_decreasing
    assert np.isclose(status["Gewicht"].sum(), 1.0)
    s = quote.summary(bt)
    json.dumps(s)
    assert s["as_of"] == "2026-09-28" and len(s["currencies"]) == 11


def test_quote_charts_render(tmp_path):
    bt = quote.run(synthetic_matrix(), **FAST)
    for render, name in ((charts.render_quote_backtest, "bt.png"), (charts.render_quote_weights, "w.png")):
        render(bt, tmp_path / name, "test")
        assert (tmp_path / name).stat().st_size > 10_000


def test_pipeline_skips_quote_on_short_history(capsys):
    from fx_analysis import pipeline

    assert pipeline.build_quote_outputs(synthetic_matrix(100)) is None
    assert "skipped" in capsys.readouterr().out


def test_run_on_stored_long_format(tmp_path):
    m = synthetic_matrix(400)
    long = m.stack().rename("close").rename_axis(["date", "pair"]).reset_index()
    csv = tmp_path / "fx.csv"
    store.save(long, csv)
    bt = quote.run(store.wide(store.load(csv)), **FAST)
    assert bt.index[-1] == m.index[-1]


def test_extended_metrics_and_annual_returns():
    bt = quote.backtest(prices(), **FAST)
    m = quote.metrics(bt["strategy"])
    for key in ("sortino", "calmar", "worst_day"):
        assert key in m
    assert m["worst_day"] == bt["strategy"].min()
    assert np.isclose(m["calmar"], m["cagr"] / -m["max_dd"])
    annual = quote.annual_returns(bt)
    assert np.isclose((1 + annual["strategy"]).prod(), 1 + m["total"])
    assert "annual_returns" in quote.summary(bt)


def test_interactive_page_is_self_contained(tmp_path):
    from fx_analysis import analysis, interactive

    matrix = synthetic_matrix()
    bt = quote.run(matrix, **FAST)
    html_path = tmp_path / "page.html"
    interactive.render(analysis.run(matrix), bt, html_path, "Daten: EZB-Referenzkurse")
    html = html_path.read_text(encoding="utf-8")
    assert "__DATA__" not in html and "__PLOTLY__" not in html
    assert "EZB-Referenzkurse" in html and "Währungsquote" in html
    # short history: the page still renders, without the Währungsquote section
    interactive.render(analysis.run(matrix), None, html_path, "x")
    assert '"quote":null' in html_path.read_text(encoding="utf-8")


def synthetic_rates(matrix: pd.DataFrame, level: dict[str, float]) -> pd.DataFrame:
    """Long policy-rate table (% p. a.) with one constant rate per currency."""
    rows = [(matrix.index[0], ccy, r) for ccy, r in level.items()]
    return pd.DataFrame(rows, columns=store.RATE_COLUMNS)


ALL_RATES = {"USD": 4.0, "EUR": 2.0, "JPY": 0.0, "GBP": 4.5, "CNY": 2.0, "CHF": 0.5,
             "CAD": 3.0, "AUD": 4.0, "NZD": 5.0, "SEK": 2.5, "NOK": 4.5}


def test_carry_adds_interest_to_returns():
    m = synthetic_matrix()
    rates = synthetic_rates(m, ALL_RATES)
    spot = quote.run(m, benchmark="equal", **FAST)
    carry = quote.run(m, rates=rates, benchmark="equal", **FAST)
    assert carry.attrs["carry"] and not spot.attrs["carry"]
    # equal-weight benchmark earns the average policy rate on top of the spot return,
    # on every calendar day: a Monday step carries three days of interest
    extra = (carry["benchmark"] - spot["benchmark"]).iloc[1:]
    days = carry.index.to_series().diff().dt.days.iloc[1:]
    assert np.allclose(extra, np.mean(list(ALL_RATES.values())) / 100 * days / 365, rtol=1e-6)
    assert extra[carry.index[1:].dayofweek == 0].mean() > 2.5 * extra[carry.index[1:].dayofweek == 2].mean()


def test_carry_needs_rates_for_every_currency():
    m = synthetic_matrix()
    rates = synthetic_rates(m, {k: v for k, v in ALL_RATES.items() if k != "NOK"})
    with pytest.raises(ValueError, match="NOK"):
        quote.run(m, rates=rates, **FAST)


def test_policy_rates_are_stored_as_changes_only(tmp_path):
    days = pd.bdate_range("2024-01-01", periods=6)
    long = pd.DataFrame({"date": list(days) * 2, "ccy": ["USD"] * 6 + ["EUR"] * 6,
                         "rate": [5, 5, 5, 4.75, 4.75, 4.75, 4, 4, 4, 4, 4, 4]})
    path = tmp_path / "rates.csv"
    store.save_rates(long, path)
    stored = store.load_rates(path)
    assert len(stored) == 3  # USD start, USD cut, EUR start
    wide = store.rates_wide(stored, pd.DatetimeIndex(days))
    assert list(wide["USD"]) == [0.05, 0.05, 0.05, 0.0475, 0.0475, 0.0475]
    assert (wide["EUR"] == 0.04).all()


def test_fetch_policy_rates_parses_bis_csv():
    from datetime import date
    from unittest import mock

    from fx_analysis import sources

    csv = ("FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
           "D,US,2024-01-02,5.5\nD,XM,2024-01-02,4.5\nD,US,2024-01-03,5.5\nD,XX,2024-01-03,1\n")

    class Resp:
        text = csv

        def raise_for_status(self):
            pass

    with mock.patch.object(sources.requests, "get", return_value=Resp()) as get:
        df = sources.fetch_policy_rates(date(2024, 1, 1))
    assert "WS_CBPOL" in get.call_args.args[0]
    assert sorted(df["ccy"].unique()) == ["EUR", "USD"]  # unknown area dropped
    assert df.loc[df.ccy == "EUR", "rate"].iloc[0] == 4.5


def test_blog_is_rendered_with_current_numbers(tmp_path):
    from fx_analysis import blog

    m = synthetic_matrix()
    rates = synthetic_rates(m, ALL_RATES)
    bt = quote.run(m, rates=rates, benchmark="equal", **FAST)
    out = tmp_path / "post.md"
    blog.render(m, bt, rates, out)
    text = out.read_text(encoding="utf-8")
    assert "{{" not in text
    assert f"{bt.index[-1]:%d.%m.%Y}" in text
    assert "mit Carry" in text and "Bloomberg" not in text
    # without rates the text says so instead of failing
    blog.render(m, quote.run(m, benchmark="equal", **FAST), None, out)
    assert "keine Leitzinsen" in out.read_text(encoding="utf-8")
