"""Central configuration: currency universe, analysis base and file locations."""

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CHART_DIR = ROOT / "charts"
WEB_DIR = ROOT / "docs"  # GitHub Pages root: the interactive chart lives here

TIMESERIES_CSV = DATA_DIR / "fx_timeseries.csv"
RATES_CSV = DATA_DIR / "policy_rates.csv"
CHART_PNG = CHART_DIR / "fx_analysis.png"
SUMMARY_JSON = CHART_DIR / "fx_summary.json"
INTERACTIVE_HTML = WEB_DIR / "fx_interactive.html"
BLOG_TEMPLATE = ROOT / "blog" / "waehrungsquote.template.md"
BLOG_MD = ROOT / "blog" / "waehrungsquote.md"

# First day with EZB euro reference rates. The daily job always loads the complete
# history from here, so there is no separate backfill.
HISTORY_START = date(1999, 1, 4)

# All rates are stored against USD (EZB rates are requested with USD as base):
# pair "USDEUR" with close 0.92 means 1 USD = 0.92 EUR.
STORE_BASE = "USD"

CURRENCIES = ["EUR", "JPY", "GBP", "CNY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]

# Perspective of the analysis. With EUR the chart answers: "How did each currency
# perform against the euro?" – USD then joins the universe in place of EUR.
ANALYSIS_BASE = "EUR"

CURRENCY_NAMES = {
    "USD": "US-Dollar",
    "EUR": "Euro",
    "JPY": "Japanischer Yen",
    "GBP": "Britisches Pfund",
    "CNY": "Chinesischer Renminbi",
    "CHF": "Schweizer Franken",
    "CAD": "Kanadischer Dollar",
    "AUD": "Australischer Dollar",
    "NZD": "Neuseeland-Dollar",
    "SEK": "Schwedische Krone",
    "NOK": "Norwegische Krone",
}

# Lookback horizons in business days (YTD is computed from the calendar).
HORIZONS = {
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "YTD": None,
    "1J": 252,
    "3J": 756,
    "5J": 1260,
}

TREND_WINDOW = 200

# Z-score of the current level against its rolling mean/std: how unusual is today's
# rate relative to the last year? |z| >= threshold is flagged as a signal.
ZSCORE_WINDOW = 252
ZSCORE_THRESHOLD = 2.0

# --- Währungsquote (see fx_analysis.quote) ---------------------------------------
QUOTE_BACKTEST_PNG = CHART_DIR / "fx_quote_backtest.png"
QUOTE_WEIGHTS_PNG = CHART_DIR / "fx_quote_weights.png"
QUOTE_JSON = CHART_DIR / "fx_quote.json"

TRADING_DAYS = 252

# Defaults for calls without explicit parameters. The z-score window is four years –
# note that the backtest only starts once lookback + smoothing + lag business days of
# history exist.
QUOTE_LOOKBACK = 252 * 4
QUOTE_CAP = 2.0  # sigma at which a currency reaches 0 % (+cap) or 2x its base weight (-cap)
QUOTE_SMOOTHING = 15  # SMA over the raw weight factor
QUOTE_LAG = 1  # business days between signal and position (1 = previous close decides)
QUOTE_COST_BP = 5.0  # trading costs in basis points of the daily turnover

# Share of global FX turnover in % (each trade counts two currencies, total 200 %),
# BIS Triennial Survey April 2025. SEK and NOK as reported for 2025; NZD is the
# 2022 figure (1.7 %) until the 2025 value is checked. Only the ratios matter:
# `quote.base_weights` renormalises over the selected basket.
TRADE_SHARES = {
    "USD": 89.2, "EUR": 28.9, "JPY": 16.8, "GBP": 10.2, "CNY": 8.5, "CHF": 6.4,
    "AUD": 6.1, "CAD": 5.8, "SEK": 1.6, "NZD": 1.7, "NOK": 1.3,
}

# Central bank policy rates (BIS data portal, dataset WS_CBPOL) as the carry proxy:
# currency → BIS reference area. The euro area is "XM".
POLICY_RATE_AREAS = {
    "USD": "US", "EUR": "XM", "JPY": "JP", "GBP": "GB", "CNY": "CN", "CHF": "CH",
    "CAD": "CA", "AUD": "AU", "NZD": "NZ", "SEK": "SE", "NOK": "NO",
}

BENCHMARKS = {
    "equal": "Gleichgewichteter Korb",
    "trade": "Handelsgewichteter Korb",
}


def pair(ccy: str) -> str:
    return f"{STORE_BASE}{ccy}"
