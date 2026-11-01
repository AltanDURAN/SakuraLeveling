"""Graphiques de la surveillance, dessinés côté serveur (SVG / HTML).

Pas de bibliothèque JavaScript : chaque graphique est du balisage dont les
couleurs viennent de variables CSS (`monitoring.css` : thème clair et
sombre, palette validée pour le daltonisme — ordre FIXE des séries). Le
survol (`monitoring.js`) lit les attributs `data-tip` (barres, cases) ou
`data-series` (courbes : un réticule et une infobulle avec toutes les séries).

Règles suivies : traits fins (2 px), barres ≤ 24 px arrondies au bout, grille
en filet discret, une seule échelle par graphique, étiquettes en encre de
texte (jamais de la couleur de la série), valeur lisible sans survol.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from datetime import date

from markupsafe import Markup, escape

from app.shared.formatters import format_int

MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


# ============================================================= nombres
def compact(value: float | None) -> str:
    """1 284 · 12,9 k · 4,2 M (séparateurs français)."""
    if value is None:
        return "—"
    v = float(value)
    sign = "−" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        s = f"{v / 1e9:.1f} Md"
    elif v >= 1_000_000:
        s = f"{v / 1e6:.1f} M"
    elif v >= 10_000:
        s = f"{v / 1e3:.0f} k"
    elif v >= 1000:
        s = f"{v / 1e3:.1f} k"
    elif v >= 10 or v == int(v):
        s = format_int(round(v))
    else:
        s = f"{v:.1f}"
    return sign + s.replace(".0 ", " ").replace(".", ",")


def full(value: float | None) -> str:
    if value is None:
        return "—"
    return ("−" if value < 0 else "") + format_int(abs(round(value)))


def pct(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f} %".replace(".", ",")


def duration(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = round(minutes)
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d}" if m else f"{h} h"


DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def when(t, weekday: bool = True) -> str:
    """« sam. 31/10 18h23 » (heure déjà locale)."""
    if t is None:
        return "—"
    return (f"{DAYS[t.weekday()]} " if weekday else "") + t.strftime("%d/%m %Hh%M")


def day_label(d: date, short: bool = True) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}" if short else d.strftime("%d/%m/%Y")


def nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    """Graduations rondes couvrant [lo, hi]."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        ticks.append(round(v, 10))
        v += step
    return ticks


def _attr(value) -> str:
    return str(escape(value))


# ============================================================ courbes
def line_chart(labels: Sequence[str], series: Sequence[dict], *, width: int = 560, height: int = 220,
               y_format=compact, y_min: float | None = 0, end_labels: bool = True, area: bool = False,
               title: str = "", x_every: int | None = None, partial_last: bool = False) -> Markup:
    """Courbes sur une même échelle. `series` : [{"name", "values", "slot"
    (1-8, couleur), "emphasis" (bool), "faint" (bool), "dashed" (bool)}] ;
    une valeur None coupe la courbe. `partial_last` : le dernier point est
    une journée EN COURS (tracé en pointillé, « en cours » à la fin)."""
    n = len(labels)
    if n == 0:
        return Markup('<p class="viz-empty">Pas encore de données.</p>')
    right = 74 if end_labels else 14
    left, top, bottom = 50, 12, 26
    pw, ph = width - left - right, height - top - bottom
    values = [v for s in series for v in s["values"] if v is not None]
    if not values:
        return Markup('<p class="viz-empty">Pas encore de données.</p>')
    lo = min(values) if y_min is None else min(y_min, min(values))
    hi = max(values)
    ticks = nice_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]

    def x(i: int) -> float:
        return left + (pw * i / (n - 1) if n > 1 else pw / 2)

    def y(v: float) -> float:
        return top + ph - (v - lo) / (hi - lo) * ph if hi > lo else top + ph / 2

    out = [f'<div class="viz-wrap" style="--vw:{width}px">'
           f'<svg class="viz viz-line" viewBox="0 0 {width} {height}" role="img" aria-label="{_attr(title)}"'
           f' data-series="{_attr(json.dumps(_series_payload(labels, series)))}"'
           f' data-left="{left}" data-plot="{pw}" data-n="{n}">']
    for t in ticks:
        out.append(f'<line class="viz-grid" x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="viz-tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{escape(y_format(t))}</text>')
    every = x_every or max(1, math.ceil(n / (width / 70)))
    for i in range(0, n, every):
        out.append(f'<text class="viz-tick" x="{x(i):.1f}" y="{height - 6}" text-anchor="middle">{escape(labels[i])}</text>')
    out.append(f'<line class="viz-axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    ends = []
    for s in sorted(series, key=lambda s: (bool(s.get("emphasis")), not s.get("faint"))):
        cls = "viz-faint" if s.get("faint") else f"s{s.get('slot', 1)}"
        segs, cur = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append((x(i), y(v)))
        if cur:
            segs.append(cur)
        tail = None
        if partial_last and segs and len(segs[-1]) > 2 and s["values"][-1] is not None:
            tail = segs[-1][-2:]
            segs[-1] = segs[-1][:-1]
        for seg in segs:
            pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in seg)
            if area and not s.get("faint") and len(seg) > 1:
                poly = f"{seg[0][0]:.1f},{top + ph} {pts} {seg[-1][0]:.1f},{top + ph}"
                out.append(f'<polygon class="viz-area {cls}" points="{poly}"/>')
            dash = ' stroke-dasharray="6 5"' if s.get("dashed") else ""
            width_cls = " viz-strong" if s.get("emphasis") else ""
            out.append(f'<polyline class="viz-stroke {cls}{width_cls}" points="{pts}"{dash}/>')
        if tail:
            pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in tail)
            out.append(f'<polyline class="viz-stroke {cls} viz-partial" points="{pts}" stroke-dasharray="3 4"/>')
        last = next(((i, v) for i in range(n - 1, -1, -1) if (v := s["values"][i]) is not None), None)
        if last and not s.get("faint"):
            out.append(f'<circle class="viz-dot {cls}" cx="{x(last[0]):.1f}" cy="{y(last[1]):.1f}" r="4"/>')
            if end_labels:
                ends.append([y(last[1]), s["name"], y_format(last[1]), x(last[0])])
    # Étiquettes de fin : écartées si elles se chevauchent, avec un filet de rappel.
    ends.sort()
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < 26:
            ends[k][0] = ends[k - 1][0] + 26
    for ly, name, val, lx in ends:
        out.append(f'<text class="viz-end-value" x="{left + pw + 10}" y="{ly + 1:.1f}">{escape(val)}</text>')
        sub = "en cours" if partial_last and len(series) == 1 else _short(name, 11)
        out.append(f'<text class="viz-end-name" x="{left + pw + 10}" y="{ly + 13:.1f}">{escape(sub)}</text>')
    out.append(f'<line class="viz-cross" x1="0" x2="0" y1="{top}" y2="{top + ph}" visibility="hidden"/>')
    out.append(f'<rect class="viz-hit" x="{left}" y="{top}" width="{pw}" height="{ph}"/>')
    out.append("</svg></div>")
    return Markup("".join(out))


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _series_payload(labels, series) -> dict:
    return {"labels": list(labels),
            "series": [{"name": s["name"], "slot": s.get("slot", 1), "values": s["values"],
                        "fmt": s.get("fmt", "compact")}
                       for s in series if not s.get("faint")]}


# ============================================================ colonnes
def columns(labels: Sequence[str], values: Sequence[float], *, width: int = 560, height: int = 200,
            y_format=compact, slot: int = 1, tips: Sequence[str] | None = None, highlight_last: bool = False,
            x_every: int | None = None, label_values: bool = False, title: str = "",
            partial_last: bool = False) -> Markup:
    n = len(values)
    if n == 0 or not any(values):
        return Markup('<p class="viz-empty">Pas encore de données.</p>')
    left, right, top, bottom = 50, 10, 14, 26
    pw, ph = width - left - right, height - top - bottom
    ticks = nice_ticks(0, max(values))
    hi = ticks[-1] or 1
    band = pw / n
    bar = min(24.0, band * 0.7)
    out = [f'<div class="viz-wrap" style="--vw:{width}px">'
           f'<svg class="viz viz-cols" viewBox="0 0 {width} {height}" role="img" aria-label="{_attr(title)}">']
    for t in ticks:
        yy = top + ph - t / hi * ph
        out.append(f'<line class="viz-grid" x1="{left}" x2="{left + pw}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<text class="viz-tick" x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end">{escape(y_format(t))}</text>')
    every = x_every or max(1, math.ceil(n / (width / 60)))
    for i, v in enumerate(values):
        cx = left + band * (i + 0.5)
        h = max(0.0, (v or 0) / hi * ph)
        cls = f"s{slot}" + (" viz-muted" if (highlight_last and i < n - 1) or (partial_last and i == n - 1) else "")
        tip = tips[i] if tips else f"{labels[i]} : {y_format(v)}" + (" (en cours)" if partial_last and i == n - 1 else "")
        out.append(f'<path class="viz-bar {cls}" d="{_bar_path(cx - bar / 2, top + ph - h, bar, h)}" data-tip="{_attr(tip)}"/>')
        out.append(f'<rect class="viz-hitbar" x="{cx - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{ph}" data-tip="{_attr(tip)}"/>')
        if label_values and v and band >= 26:
            out.append(f'<text class="viz-value" x="{cx:.1f}" y="{top + ph - h - 5:.1f}" text-anchor="middle">{escape(y_format(v))}</text>')
        if i % every == 0:
            out.append(f'<text class="viz-tick" x="{cx:.1f}" y="{height - 6}" text-anchor="middle">{escape(labels[i])}</text>')
    out.append(f'<line class="viz-axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    out.append("</svg></div>")
    return Markup("".join(out))


def _bar_path(x0: float, y0: float, w: float, h: float, r: float = 4.0) -> str:
    """Barre verticale au bout arrondi (4 px), carrée sur la ligne de base."""
    if h <= 0:
        return f"M{x0:.1f},{y0:.1f}h{w:.1f}"
    r = min(r, w / 2, h)
    return (f"M{x0:.1f},{y0 + h:.1f}V{y0 + r:.1f}Q{x0:.1f},{y0:.1f} {x0 + r:.1f},{y0:.1f}"
            f"H{x0 + w - r:.1f}Q{x0 + w:.1f},{y0:.1f} {x0 + w:.1f},{y0 + r:.1f}V{y0 + h:.1f}Z")


def _bar_path_down(x0: float, y0: float, w: float, h: float, r: float = 4.0) -> str:
    if h <= 0:
        return f"M{x0:.1f},{y0:.1f}h{w:.1f}"
    r = min(r, w / 2, h)
    return (f"M{x0:.1f},{y0:.1f}V{y0 + h - r:.1f}Q{x0:.1f},{y0 + h:.1f} {x0 + r:.1f},{y0 + h:.1f}"
            f"H{x0 + w - r:.1f}Q{x0 + w:.1f},{y0 + h:.1f} {x0 + w:.1f},{y0 + h - r:.1f}V{y0:.1f}Z")


def diverging_stack(labels: Sequence[str], up: Sequence[dict], down: Sequence[dict], *, width: int = 1080,
                    height: int = 280, y_format=compact, net: Sequence[float] | None = None,
                    title: str = "", x_every: int | None = None, partial_last: bool = False) -> Markup:
    """Colonnes empilées de part et d'autre de zéro (or créé au-dessus, or
    détruit en dessous). `up` / `down` : [{"name", "values", "slot"}]. Un
    espace de 2 px sépare les segments. `net` : marqueur du solde du jour."""
    n = len(labels)
    tops = [sum(s["values"][i] for s in up) for i in range(n)]
    bots = [sum(s["values"][i] for s in down) for i in range(n)]
    if not any(tops) and not any(bots):
        return Markup('<p class="viz-empty">Pas encore de mouvement d\'or.</p>')
    left, right, top, bottom = 56, 10, 12, 26
    pw, ph = width - left - right, height - top - bottom
    ticks = nice_ticks(-max(bots + [1]), max(tops + [1]), 6)
    lo, hi = ticks[0], ticks[-1]

    def y(v: float) -> float:
        return top + ph - (v - lo) / (hi - lo) * ph

    band = pw / n
    bar = min(24.0, band * 0.72)
    out = [f'<div class="viz-wrap" style="--vw:{width}px">'
           f'<svg class="viz viz-cols" viewBox="0 0 {width} {height}" role="img" aria-label="{_attr(title)}">']
    for t in ticks:
        out.append(f'<line class="viz-grid{" viz-zero" if t == 0 else ""}" x1="{left}" x2="{left + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        out.append(f'<text class="viz-tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{escape(y_format(t))}</text>')
    every = x_every or max(1, math.ceil(n / (width / 64)))
    for i in range(n):
        cx = left + band * (i + 0.5)
        x0 = cx - bar / 2
        partial = partial_last and i == n - 1
        lines = [labels[i] + (" (en cours)" if partial else "")]
        if partial:
            out.append('<g class="viz-muted">')
        acc = 0.0
        stack = [s for s in up if s["values"][i] > 0]
        for k, s in enumerate(stack):
            v = s["values"][i]
            y1, y0 = y(acc), y(acc + v)
            h = max(0.0, y1 - y0 - (2 if k else 0))
            d = _bar_path(x0, y0, bar, h) if k == len(stack) - 1 else f"M{x0:.1f},{y0:.1f}h{bar:.1f}v{h:.1f}h{-bar:.1f}Z"
            out.append(f'<path class="viz-bar s{s["slot"]}" d="{d}"/>')
            acc += v
            lines.append(f"+{y_format(v)} {s['name']}")
        acc = 0.0
        stack = [s for s in down if s["values"][i] > 0]
        for k, s in enumerate(stack):
            v = s["values"][i]
            y0, y1 = y(-acc), y(-acc - v)
            h = max(0.0, y1 - y0 - (2 if k else 0))
            y0 += 2 if k else 0
            d = _bar_path_down(x0, y0, bar, h) if k == len(stack) - 1 else f"M{x0:.1f},{y0:.1f}h{bar:.1f}v{h:.1f}h{-bar:.1f}Z"
            out.append(f'<path class="viz-bar s{s["slot"]}" d="{d}"/>')
            acc += v
            lines.append(f"−{y_format(v)} {s['name']}")
        if net is not None:
            lines.append(f"Solde du jour : {'+' if net[i] >= 0 else ''}{y_format(net[i])}")
            out.append(f'<line class="viz-net" x1="{x0 - 2:.1f}" x2="{x0 + bar + 2:.1f}" y1="{y(net[i]):.1f}" y2="{y(net[i]):.1f}"/>')
        if partial:
            out.append("</g>")
        out.append(f'<rect class="viz-hitbar" x="{cx - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{ph}" data-tip="{_attr(chr(10).join(lines))}"/>')
        if i % every == 0:
            out.append(f'<text class="viz-tick" x="{cx:.1f}" y="{height - 6}" text-anchor="middle">{escape(labels[i])}</text>')
    out.append("</svg></div>")
    return Markup("".join(out))


# ================================================================ HTML
def ranked_bars(items: Sequence[tuple], *, value_format=compact, slot: int = 1, limit: int | None = None,
                note_format=None, empty: str = "Pas encore de données.") -> Markup:
    """Barres horizontales classées. `items` : (libellé, valeur[, note[,
    lien]]) — la note s'affiche à droite (part en %, joueurs…)."""
    rows = list(items)[:limit] if limit else list(items)
    if not rows or not any(r[1] for r in rows):
        return Markup(f'<p class="viz-empty">{escape(empty)}</p>')
    top = max(r[1] for r in rows) or 1
    out = ['<ol class="rbars">']
    for r in rows:
        label, value = r[0], r[1]
        note = r[2] if len(r) > 2 else None
        link = r[3] if len(r) > 3 else None
        w = max(0.6, 100 * value / top)
        note_html = f'<span class="rbar-note">{escape(note_format(note) if note_format else note)}</span>' if note is not None else ""
        name = f'<a href="{_attr(link)}">{escape(label)}</a>' if link else escape(label)
        out.append(f'<li class="rbar" data-tip="{_attr(f"{label} : {value_format(value)}")}" tabindex="0">'
                   f'<span class="rbar-label">{name}</span>'
                   f'<span class="rbar-track"><span class="rbar-fill s{slot}" style="width:{w:.1f}%"></span></span>'
                   f'<span class="rbar-value">{escape(value_format(value))}</span>{note_html}</li>')
    out.append("</ol>")
    return Markup("".join(out))


def segmented(parts: Sequence[tuple], *, tall: bool = True, value_format=compact, legend: bool = True) -> Markup:
    """Un tout découpé en parts (≤ 6) : (libellé, valeur, slot)."""
    parts = [p for p in parts if p[1] > 0]
    total = sum(p[1] for p in parts)
    if not total:
        return Markup('<p class="viz-empty">Pas encore de données.</p>')
    cls = "seg seg-tall" if tall else "seg"
    out = [f'<div class="{cls}" role="img">']
    for label, value, slot in parts:
        share = 100 * value / total
        text = f"{share:.0f} %" if tall and share >= 9 else ""
        out.append(f'<span class="seg-part s{slot}" style="flex:{value}" tabindex="0" '
                   f'data-tip="{_attr(f"{label} : {value_format(value)} ({share:.0f} %)")}">'
                   f'<span class="seg-text">{text}</span></span>')
    out.append("</div>")
    if legend:
        out.append('<ul class="legend">')
        for label, value, slot in parts:
            out.append(f'<li><span class="key s{slot}"></span>{escape(label)}</li>')
        out.append("</ul>")
    return Markup("".join(out))


def heatmap(grid: Sequence[Sequence[float]], *, rows: Sequence[str], unit: str = "actions",
            cols: Sequence[str] | None = None) -> Markup:
    """Carte de chaleur jour × heure : une teinte, du clair (peu) au foncé
    (beaucoup), 7 niveaux + vide."""
    peak = max((v for r in grid for v in r), default=0)
    cols = cols or [f"{h}h" for h in range(24)]
    out = ['<div class="heat" role="table">', '<div class="heat-row heat-head"><span></span>']
    for k, c in enumerate(cols):
        out.append(f'<span class="heat-col">{escape(c) if k % 3 == 0 else ""}</span>')
    out.append("</div>")
    for name, row in zip(rows, grid):
        out.append(f'<div class="heat-row"><span class="heat-name">{escape(name)}</span>')
        for k, v in enumerate(row):
            level = 0 if not v or not peak else 1 + min(6, int(6 * v / peak))
            out.append(f'<span class="heat-cell h{level}" tabindex="0" '
                       f'data-tip="{_attr(f"{name} {cols[k]} : {full(v)} {unit}")}"></span>')
        out.append("</div>")
    out.append('<div class="heat-scale"><span>moins</span>')
    out.extend(f'<span class="heat-cell h{i}"></span>' for i in range(1, 8))
    out.append("<span>plus</span></div></div>")
    return Markup("".join(out))


def sparkline(values: Sequence[float], *, width: int = 120, height: int = 32) -> Markup:
    vals = [v or 0 for v in values]
    if len(vals) < 2 or not any(vals):
        return Markup("")
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = []
    for i, v in enumerate(vals):
        pts.append(f"{2 + (width - 6) * i / (len(vals) - 1):.1f},{height - 3 - (v - lo) / span * (height - 6):.1f}")
    last = pts[-1].split(",")
    return Markup(f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true">'
                  f'<polyline class="spark-line" points="{" ".join(pts)}"/>'
                  f'<circle class="spark-dot" cx="{last[0]}" cy="{last[1]}" r="3"/></svg>')


def strip(values: Sequence[float], mine: float, *, label_format=compact) -> Markup:
    """Où se place un joueur parmi les autres : tous en points discrets,
    lui en accent, sur une échelle du plus bas au plus haut."""
    vals = [v for v in values if v is not None]
    if not vals:
        return Markup("")
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    dots = "".join(f'<span class="strip-dot" style="left:{100 * (v - lo) / span:.1f}%"></span>' for v in vals)
    me = 100 * (mine - lo) / span
    return Markup(f'<span class="strip" data-tip="{_attr(f"Lui : {label_format(mine)} · min {label_format(lo)} · max {label_format(hi)}")}">'
                  f'{dots}<span class="strip-me" style="left:{me:.1f}%"></span></span>')


def meter(value: float, *, maximum: float = 100, level: str = "") -> Markup:
    w = max(0.0, min(100.0, 100 * value / maximum if maximum else 0))
    return Markup(f'<span class="meter {level}"><span class="meter-fill" style="width:{w:.1f}%"></span></span>')
