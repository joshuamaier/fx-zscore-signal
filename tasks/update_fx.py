"""Daily job (GitHub Actions, 08:00 UTC): load the complete EZB history, merge it into
the stored series, rerun the analysis and regenerate charts, JSON and the interactive
page.

The whole history (since 1999, ~28 yearly requests to the free EZB mirror) is fetched
every day instead of only the last days: no separate backfill, missed runs and
retroactive corrections heal themselves, and unchanged rates produce no diff in git.

    python tasks/update_fx.py               # full history
    python tasks/update_fx.py --years 5     # shorter, e.g. for a quick local run
"""

import argparse
import os
import sys
from datetime import date, timedelta

import _path  # noqa: F401

from fx_analysis import pipeline, sources, store
from fx_analysis.config import HISTORY_START


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, help="only load this many years instead of the full history")
    args = parser.parse_args()

    end = date.today()
    start = end - timedelta(days=round(365.25 * args.years) + 10) if args.years else HISTORY_START

    fetched = sources.fetch_ezb(start, end)
    if fetched.empty:
        print("EZB returned no data.", file=sys.stderr)
        return 1
    print(f"EZB delivered {len(fetched)} rows from {fetched['date'].min():%Y-%m-%d} to {fetched['date'].max():%Y-%m-%d}.")

    # Policy rates for the carry. A failure must not stop the daily run: the stored
    # rates stay in place (or the Währungsquote runs without carry).
    try:
        rates = sources.fetch_policy_rates(start)
        store.save_rates(store.upsert_rates(store.load_rates(), rates))
        print(f"Policy rates: {len(rates)} daily values for {rates['ccy'].nunique()} currencies.")
    except Exception as err:  # noqa: BLE001 – network and format errors alike
        print(f"::warning::Policy rates not updated ({err}) – using the stored ones.")

    # Fresh EZB values win over what is stored.
    merged = store.upsert(store.load(), fetched)
    store.save(merged)
    print(f"Stored {len(merged)} rows from {merged['date'].min():%Y-%m-%d} to {merged['date'].max():%Y-%m-%d}.")

    quote_params = {}
    if benchmark := os.environ.get("QUOTE_BENCHMARK"):
        quote_params["quote_benchmark"] = benchmark
    if lookback := os.environ.get("QUOTE_LOOKBACK"):
        quote_params["lookback"] = int(lookback)
    if cap := os.environ.get("QUOTE_CAP"):
        quote_params["cap"] = float(cap)
    if smoothing := os.environ.get("QUOTE_SMOOTHING"):
        quote_params["smoothing"] = int(smoothing)
    if lag := os.environ.get("QUOTE_LAG"):
        quote_params["lag"] = int(lag)
    if os.environ.get("QUOTE_CARRY") == "0":
        quote_params["carry"] = False
    if cost_bp := os.environ.get("QUOTE_COST_BP"):
        quote_params["cost_bp"] = float(cost_bp)

    result = pipeline.build_outputs(**quote_params)
    print(f"Outputs updated, data as of {result.as_of:%Y-%m-%d}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
