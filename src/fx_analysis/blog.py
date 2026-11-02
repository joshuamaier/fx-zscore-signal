"""Blog post: `blog/waehrungsquote.template.md` with {{placeholders}} is rendered to
`blog/waehrungsquote.md` on every run, so the numbers in the text always match the
charts. Wording that depends on the data (better/worse than the basket …) is chosen
here, not hard-coded in the template."""

import re
from pathlib import Path

import pandas as pd

from . import quote
from .config import BLOG_TEMPLATE, CURRENCY_NAMES, TRADING_DAYS


def _p(x: float, d: int = 1, sign: bool = False) -> str:
    if pd.isna(x):
        return "–"
    return f"{x * 100:{'+' if sign else ''}.{d}f} %".replace(".", ",").replace("-", "−")


def _n(x: float, d: int = 2) -> str:
    return "–" if pd.isna(x) else f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def _date(ts: pd.Timestamp) -> str:
    return f"{ts:%d.%m.%Y}"


def _rerun(matrix: pd.DataFrame, bt: pd.DataFrame, rates, **override) -> pd.DataFrame:
    a = bt.attrs
    params = dict(lookback=a["lookback"], cap=a["cap"], smoothing=a["smoothing"], lag=a["lag"],
                  benchmark=a["benchmark"], cost_bp=a["cost_bp"])
    params.update(override)
    return quote.run(matrix, rates=rates, **params)


def _metrics_table(bt: pd.DataFrame) -> str:
    comp = quote.comparison(bt)
    label = quote.benchmark_label(bt)
    rows = [
        ("Gesamtrendite", lambda v: _p(v, 1, True)), ("Rendite p. a.", lambda v: _p(v, 2, True)),
        ("Volatilität p. a.", lambda v: _p(v, 1)), ("Sharpe-Ratio", _n), ("Sortino-Ratio", _n),
        ("Max. Drawdown", lambda v: _p(v, 1)), ("Calmar-Ratio", _n), ("Schlechtester Tag", lambda v: _p(v, 2)),
    ]
    lines = [f"| Kennzahl | Währungsquote | {label} |", "|---|---:|---:|"]
    lines += [f"| {name} | {fmt(comp.loc[name, 'Währungsquote'])} | {fmt(comp.loc[name, label])} |" for name, fmt in rows]
    return "\n".join(lines)


def _result_sentence(bt: pd.DataFrame) -> str:
    comp = quote.comparison(bt)
    label = quote.benchmark_label(bt)
    g = lambda name, col: comp.loc[name, col]  # noqa: E731
    diff = g("Rendite p. a.", "Differenz")
    dd_diff = g("Max. Drawdown", "Differenz")  # positive = shallower drawdown
    sharpe_s, sharpe_b = g("Sharpe-Ratio", "Währungsquote"), g("Sharpe-Ratio", label)
    return (
        f"Die Währungsquote erzielt {_p(g('Rendite p. a.', 'Währungsquote'), 2)} pro Jahr, der Korb "
        f"{_p(g('Rendite p. a.', label), 2)} – {'ein Vorsprung' if diff > 0 else 'ein Rückstand'} von "
        f"{_n(abs(diff) * 100)} Prozentpunkten. Die Sharpe-Ratio liegt bei {_n(sharpe_s)} gegenüber {_n(sharpe_b)}, "
        f"der maximale Drawdown bei {_p(g('Max. Drawdown', 'Währungsquote'))} gegenüber {_p(g('Max. Drawdown', label))}"
        f" ({'die Strategie fällt weniger tief' if dd_diff > 0.001 else 'die Strategie fällt tiefer' if dd_diff < -0.001 else 'praktisch gleich'})."
    )


def _carry_paragraph(matrix, bt, rates) -> str:
    if not bt.attrs.get("carry"):
        return ("**Zinsen (Carry):** In diesem Lauf sind keine Leitzinsen hinterlegt; gerechnet wird nur die "
                "Kursveränderung. Zinsunterschiede zwischen den Währungen fehlen deshalb.")
    spot = _rerun(matrix, bt, None)
    s_all, b_all = quote.metrics(bt["strategy"])["cagr"], quote.metrics(bt["benchmark"])["cagr"]
    s_spot, b_spot = quote.metrics(spot["strategy"])["cagr"], quote.metrics(spot["benchmark"])["cagr"]
    return (
        "**Zinsen (Carry):** Jede Währung verdient zusätzlich ihren Leitzins (Notenbank-Leitzinsen der BIS, "
        "täglich abgerufen). Ohne Zinsen lägen Währungsquote und Korb bei "
        f"{_p(s_spot, 2)} bzw. {_p(b_spot, 2)} pro Jahr, mit Zinsen bei {_p(s_all, 2)} bzw. {_p(b_all, 2)}. "
        "Die Sharpe-Ratio ist eine Bruttogröße ohne Abzug eines risikolosen Zinses."
    )


def _cost_sentence(matrix, bt, rates) -> str:
    freq = bt.attrs["freq"]
    turnover = bt["turnover"].sum() / (len(bt) / freq)
    cost = bt.attrs["cost_bp"]
    free = _rerun(matrix, bt, rates, cost_bp=0.0)
    m_cost, m_free = quote.metrics(bt["strategy"]), quote.metrics(free["strategy"])
    return (
        f"**Kosten:** Die Strategie schichtet um – pro Jahr wird das {_n(turnover, 1)}-Fache des Korbwerts bewegt. "
        f"Gerechnet ist mit {_n(cost, 0)} Basispunkten je Umschichtung: Ohne Kosten läge die Rendite p. a. bei "
        f"{_p(m_free['cagr'], 2)} und die Sharpe-Ratio bei {_n(m_free['sharpe'])}, mit Kosten bei "
        f"{_p(m_cost['cagr'], 2)} bzw. {_n(m_cost['sharpe'])}. Der Korb selbst wird nicht umgeschichtet und trägt keine Kosten."
    )


def _today_paragraph(bt: pd.DataFrame) -> str:
    status = quote.signal_status(bt)
    status["diff"] = status["Gewicht"] - status["Grundgewicht"]
    over = status.sort_values("diff", ascending=False).head(3)
    under = status.sort_values("diff").head(3)
    fmt_pp = lambda df: ", ".join(f"{CURRENCY_NAMES.get(c, c)} ({(_n(r['diff'] * 100, 1) if r['diff'] < 0 else '+' + _n(r['diff'] * 100, 1))} pp)" for c, r in df.iterrows())  # noqa: E731
    top = status.iloc[0]
    bottom = status.iloc[-1]
    return (
        f"Am {_date(bt.index[-1])} ist der Korb am stärksten in {fmt_pp(over)} **übergewichtet** und in "
        f"{fmt_pp(under)} **untergewichtet**. Am „teuersten“ gegenüber dem eigenen Vierjahres-Verlauf ist "
        f"{CURRENCY_NAMES.get(status.index[0], status.index[0])} (z = {_n(top['z-Score'])}), am „billigsten“ "
        f"{CURRENCY_NAMES.get(status.index[-1], status.index[-1])} (z = {_n(bottom['z-Score'])})."
    )


def _month_paragraph(bt: pd.DataFrame) -> str:
    prices = bt.attrs["prices"].drop(columns=[bt.attrs["numeraire"]], errors="ignore")
    if len(prices) < 22:
        return ""
    r = (prices.iloc[-1] / prices.iloc[-22] - 1).sort_values()
    name = lambda c: CURRENCY_NAMES.get(c, c)  # noqa: E731
    return (
        f"In den letzten vier Wochen gegenüber dem Euro am stärksten: {name(r.index[-1])} ({_p(r.iloc[-1], 1, True)}), "
        f"am schwächsten: {name(r.index[0])} ({_p(r.iloc[0], 1, True)})."
    )


def values(matrix: pd.DataFrame, bt: pd.DataFrame, rates) -> dict[str, str]:
    a = bt.attrs
    years = len(bt) / a["freq"]
    return {
        "stand": _date(bt.index[-1]),
        "start": _date(bt.index[0]),
        "jahre": _n(years, 1),
        "korb": quote.benchmark_label(bt),
        "lookback_jahre": _n(a["lookback"] / TRADING_DAYS, 0),
        "einstellungen": (
            f"Lookback {_n(a['lookback'] / TRADING_DAYS, 0)} Jahre, Kappung {_n(a['cap'])}σ, Glättung {a['smoothing']} Tage, "
            f"Versatz {a['lag']} Tag(e), Kosten {_n(a['cost_bp'], 0)} bp, {'mit' if a['carry'] else 'ohne'} Carry"
        ),
        "kennzahlen_tabelle": _metrics_table(bt),
        "ergebnis_satz": _result_sentence(bt),
        "carry_absatz": _carry_paragraph(matrix, bt, rates),
        "kosten_absatz": _cost_sentence(matrix, bt, rates),
        "heute_absatz": _today_paragraph(bt),
        "monat_absatz": _month_paragraph(bt),
    }


def render(matrix: pd.DataFrame, bt: pd.DataFrame, rates, path: Path, template: Path = BLOG_TEMPLATE) -> None:
    if not template.exists():
        return
    vals = values(matrix, bt, rates)
    text = template.read_text(encoding="utf-8")
    unknown = set(re.findall(r"\{\{(\w+)\}\}", text)) - set(vals)
    if unknown:
        raise ValueError(f"Unknown placeholders in {template.name}: {sorted(unknown)}")
    text = re.sub(r"<!--.*?-->\n*", "", text, count=1, flags=re.S)  # the template's own note
    path.write_text(re.sub(r"\{\{(\w+)\}\}", lambda m: vals[m.group(1)], text), encoding="utf-8")
