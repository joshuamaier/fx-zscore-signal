"""Chart rendering. Colours follow the joshuamaier.de palette so the PNG sits
naturally inside the blog post."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from .analysis import Result  # noqa: E402
from .config import CURRENCY_NAMES, ZSCORE_THRESHOLD, ZSCORE_WINDOW  # noqa: E402

PAPER = "#fbfaf6"
INK = "#1b2330"
INK_SOFT = "#5b6472"
LINE = "#dcdad3"
GOLD = "#b8944a"
NEG = "#b5523b"
POS = "#2f7d6d"

CMAP = LinearSegmentedColormap.from_list("fx", [NEG, "#f3e3dc", PAPER, "#d9ebe6", POS])


def _fmt(x: float) -> str:
    return "–" if np.isnan(x) else f"{x * 100:+.1f}".replace(".", ",").replace("-", "−")


def render(result: Result, path: Path, source_note: str) -> None:
    # Horizons longer than the stored history would only show dashes.
    returns = result.returns.dropna(axis=1, how="all")
    returns = returns.sort_values("3M" if "3M" in returns else returns.columns[0], ascending=False)
    zs = result.trend.loc[returns.index, "zscore"]
    values = returns.to_numpy(dtype=float)

    # Scale each horizon separately: a 2 % move over a week matters more than over five years.
    scale = np.nanmax(np.abs(values), axis=0)
    scale[~np.isfinite(scale) | (scale == 0)] = 1
    normed = values / scale

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig = plt.figure(figsize=(12, 7.2), dpi=150, facecolor=PAPER)
    grid = fig.add_gridspec(1, 2, width_ratios=[4.2, 1.3], wspace=0.06, left=0.2, right=0.97, top=0.8, bottom=0.12)
    ax = fig.add_subplot(grid[0])
    ax_t = fig.add_subplot(grid[1], sharey=ax)

    base_name = CURRENCY_NAMES[result.base]
    fig.text(0.03, 0.935, f"Währungen gegenüber dem {base_name}", fontsize=18, fontweight="bold", color=INK)
    fig.text(
        0.03, 0.885,
        f"Wertentwicklung in % je Horizont und Z-Score über {ZSCORE_WINDOW} Handelstage · "
        f"sortiert nach 3M · Stand {result.as_of:%d.%m.%Y}",
        fontsize=11, color=INK_SOFT,
    )

    ax.imshow(np.nan_to_num(normed), cmap=CMAP, vmin=-1, vmax=1, aspect="auto")
    for (i, j), v in np.ndenumerate(values):
        strong = not np.isnan(v) and abs(normed[i, j]) > 0.65
        ax.text(j, i, _fmt(v), ha="center", va="center", fontsize=10.5,
                color="white" if strong else INK, fontweight="bold" if strong else "normal")

    ax.set_xticks(range(len(returns.columns)), returns.columns)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(returns.index)), [f"{CURRENCY_NAMES[c]}  {c}" for c in returns.index])
    ax.tick_params(length=0, colors=INK, labelsize=10.5)
    ax.set_xticks(np.arange(-.5, len(returns.columns)), minor=True)
    ax.set_yticks(np.arange(-.5, len(returns.index)), minor=True)
    ax.grid(which="minor", color=PAPER, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Z-score panel: bars are muted inside the ±threshold band and saturated beyond it.
    y = np.arange(len(zs))
    zv = zs.to_numpy(dtype=float)
    colors = [
        (POS if v >= 0 else NEG) if abs(v) >= ZSCORE_THRESHOLD else ("#9cc4ba" if v >= 0 else "#dba99c")
        for v in np.nan_to_num(zv)
    ]
    lim = max(3.2, np.nanmax(np.abs(zv)) * 1.45) if np.isfinite(zv).any() else 3.2
    ax_t.axvspan(-ZSCORE_THRESHOLD, ZSCORE_THRESHOLD, color=LINE, alpha=0.35, linewidth=0)
    ax_t.barh(y, np.nan_to_num(zv), color=colors, height=0.55)
    ax_t.axvline(0, color=INK, linewidth=0.8)
    for yi, v in zip(y, zv):
        label = "–" if np.isnan(v) else f"{v:+.1f}".replace(".", ",").replace("-", "−")
        ax_t.text(0 if np.isnan(v) else v, yi, f" {label} ", va="center", ha="left" if np.isnan(v) or v >= 0 else "right",
                  fontsize=9.5, color=INK, fontweight="bold" if abs(np.nan_to_num(v)) >= ZSCORE_THRESHOLD else "normal")
    ax_t.set_xlim(-lim, lim)
    ax_t.set_facecolor(PAPER)
    ax_t.set_title(f"Z-Score ({ZSCORE_WINDOW} T)", fontsize=10.5, color=INK, pad=11)
    ax_t.tick_params(which="both", left=False, labelleft=False, bottom=False, labelbottom=False)
    for spine in ax_t.spines.values():
        spine.set_visible(False)

    fig.add_artist(plt.Line2D([0.03, 0.97], [0.07, 0.07], color=LINE, linewidth=1, transform=fig.transFigure))
    fig.text(0.03, 0.035, source_note, fontsize=9, color=INK_SOFT)
    fig.text(0.97, 0.035, "joshuamaier.de", fontsize=9, color=GOLD, ha="right", fontweight="bold")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=PAPER)
    plt.close(fig)


# --- Währungsquote (fx_analysis.quote) ------------------------------------------

def _pct_axis(x: float, _pos=None) -> str:
    return f"{round(x * 100, 2):g} %".replace(".", ",").replace("-", "−")


def _pct(x: float) -> str:
    return "–" if np.isnan(x) else f"{x * 100:+.1f} %".replace(".", ",").replace("-", "−")


def _quote_settings(bt) -> str:
    a = bt.attrs
    return (
        f"Lookback {a['lookback']} T · Kappung {a['cap']:.2f}σ · Glättung {a['smoothing']} T · "
        f"Versatz {a['lag']} T · Kosten {a['cost_bp']:.0f} bp · {'mit' if a.get('carry') else 'ohne'} Carry"
    ).replace(".", ",")


def _frame_figure(title: str, subtitle: str, source_note: str):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig = plt.figure(figsize=(12, 7.2), dpi=150, facecolor=PAPER)
    fig.text(0.03, 0.935, title, fontsize=18, fontweight="bold", color=INK)
    fig.text(0.03, 0.885, subtitle, fontsize=11, color=INK_SOFT)
    fig.add_artist(plt.Line2D([0.03, 0.97], [0.07, 0.07], color=LINE, linewidth=1, transform=fig.transFigure))
    fig.text(0.03, 0.035, source_note, fontsize=9, color=INK_SOFT)
    fig.text(0.97, 0.035, "joshuamaier.de", fontsize=9, color=GOLD, ha="right", fontweight="bold")
    return fig


def _style(ax) -> None:
    ax.set_facecolor(PAPER)
    ax.grid(axis="y", color=LINE, linewidth=0.8)
    ax.tick_params(colors=INK_SOFT, length=0)
    for side, spine in ax.spines.items():
        spine.set_visible(side == "bottom")
        spine.set_color(LINE)


def render_quote_backtest(bt, path: Path, source_note: str) -> None:
    """Value lines (log scale) of Währungsquote and basket, drawdowns below."""
    from matplotlib.ticker import FuncFormatter, MaxNLocator, NullLocator

    from .quote import benchmark_label, metrics

    label = benchmark_label(bt)
    s, b = metrics(bt["strategy"], bt.attrs["freq"]), metrics(bt["benchmark"], bt.attrs["freq"])
    fig = _frame_figure(
        f"Währungsquote vs. {label}",
        f"{_quote_settings(bt)} · {bt.index[0]:%d.%m.%Y} – {bt.index[-1]:%d.%m.%Y}",
        source_note,
    )
    grid = fig.add_gridspec(2, 1, height_ratios=[2.3, 1], hspace=0.08, left=0.08, right=0.97, top=0.8, bottom=0.12)
    ax = fig.add_subplot(grid[0])
    ax_dd = fig.add_subplot(grid[1], sharex=ax)

    ax.plot(bt.index, bt["value_benchmark"], color=INK_SOFT, linewidth=1.3,
            label=f"{label}  {_pct(b['cagr'])} p. a.")
    ax.plot(bt.index, bt["value_strategy"], color=POS, linewidth=1.8,
            label=f"Währungsquote  {_pct(s['cagr'])} p. a.")
    # Log scale, but with plain evenly spaced labels: over one or two years the range
    # stays far below a decade, where matplotlib's log ticks label next to nothing.
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(MaxNLocator(6))
    ax.yaxis.set_minor_locator(NullLocator())
    values = bt[["value_strategy", "value_benchmark"]].to_numpy()
    digits = 3 if values.max() / values.min() < 1.1 else 2
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.{digits}f}".replace(".", ",")))
    ax.set_ylabel("Wert (log, Start = 1)", color=INK_SOFT)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK)
    ax.tick_params(labelbottom=False)

    ax_dd.fill_between(bt.index, bt["dd_strategy"], 0, color=NEG, alpha=0.18, linewidth=0)
    ax_dd.plot(bt.index, bt["dd_strategy"], color=NEG, linewidth=1)
    ax_dd.plot(bt.index, bt["dd_benchmark"], color=INK_SOFT, linewidth=1)
    ax_dd.yaxis.set_major_formatter(FuncFormatter(_pct_axis))
    ax_dd.set_ylabel("Rücksetzer", color=INK_SOFT)
    for a in (ax, ax_dd):
        _style(a)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=PAPER)
    plt.close(fig)


def render_quote_weights(bt, path: Path, source_note: str, freq: str | None = "W-FRI") -> None:
    """Stacked area of the daily weights from `quote.backtest` – always 100 % in total,
    current weights annotated on the right with over-/underweight vs. benchmark. `freq` thins the time axis (None = daily)."""
    from matplotlib.ticker import FuncFormatter

    weights = bt.attrs["weights"]
    base_weights = bt.attrs["base_weights"]
    if freq:
        weights = weights.resample(freq).last().dropna(how="all")
    last = weights.iloc[-1].sort_values(ascending=False)
    weights = weights[last.index]

    fig = _frame_figure(
        "Währungsgewichte über die Zeit",
        f"{len(last)} Währungen · Summe immer 100 % · {_quote_settings(bt)}",
        source_note,
    )
    ax = fig.add_axes([0.08, 0.12, 0.8, 0.68])
    colors = LinearSegmentedColormap.from_list("w", [INK, POS, GOLD, LINE])(np.linspace(0, 1, len(last)))
    ax.stackplot(weights.index, weights.T.to_numpy(), colors=colors, edgecolor=PAPER, linewidth=0.4)

    # Labels at the right edge, centred on each band; bands thinner than ~2 % would
    # collide, so labels are pushed apart to a minimum spacing.
    centres = last.cumsum() - last / 2
    placed, prev = [], -1.0
    for c in centres:
        y = max(c, prev + 0.028)
        placed.append(y)
        prev = y
    for (code, w), y in zip(last.items(), placed):
        diff_pp = (w - base_weights.get(code, 0.0)) * 100
        diff_str = f"{diff_pp:+.1f}" if abs(diff_pp) >= 0.05 else "±0"
        label = f"{code} {w * 100:.0f} % ({diff_str} pp)" if abs(diff_pp) >= 0.05 else f"{code} {w * 100:.0f} %"
        ax.annotate(label, xy=(weights.index[-1], y), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK,
                    annotation_clip=False)

    ax.set_ylim(0, 1)
    ax.set_xlim(weights.index[0], weights.index[-1])
    ax.yaxis.set_major_formatter(FuncFormatter(_pct_axis))
    ax.set_ylabel("Gewicht am Währungskorb", color=INK_SOFT)
    _style(ax)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=PAPER)
    plt.close(fig)
