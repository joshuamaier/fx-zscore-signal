"""Glue between store, analysis and outputs – shared by all tasks and the notebook."""

import json

from . import analysis, blog, charts, interactive, quote, store
from .config import BLOG_MD, CHART_PNG, INTERACTIVE_HTML, QUOTE_BACKTEST_PNG, QUOTE_JSON, QUOTE_WEIGHTS_PNG, SUMMARY_JSON

SOURCE_NOTE = "Daten: EZB-Referenzkurse, BIS-Leitzinsen · Code: github.com/joshuamaier/fx-zscore-signal"


def build_outputs(quote_benchmark: str = "equal", carry: bool = True, **quote_params) -> analysis.Result:
    matrix = store.wide(store.load())
    result = analysis.run(matrix)
    charts.render(result, CHART_PNG, SOURCE_NOTE)
    summary = analysis.summary(result)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rates = store.load_rates()
    if not carry or rates.empty:
        if carry:
            print("No policy rates stored – Währungsquote runs without carry.")
        rates = None
    bt = build_quote_outputs(matrix, benchmark=quote_benchmark, rates=rates, **quote_params)
    interactive.render(result, bt, INTERACTIVE_HTML, SOURCE_NOTE)
    if bt is not None:
        blog.render(matrix, bt, rates, BLOG_MD)
    return result


def build_quote_outputs(matrix, **params):
    """Währungsquote backtest + charts + JSON. Returns the backtest, or None when the
    stored history is still shorter than the signal's warm-up – the daily run must
    not fail because of it."""
    try:
        bt = quote.run(matrix, **params)
    except ValueError as err:
        print(f"Währungsquote skipped: {err}")
        return None
    charts.render_quote_backtest(bt, QUOTE_BACKTEST_PNG, SOURCE_NOTE)
    charts.render_quote_weights(bt, QUOTE_WEIGHTS_PNG, SOURCE_NOTE)
    QUOTE_JSON.write_text(json.dumps(quote.summary(bt), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bt
