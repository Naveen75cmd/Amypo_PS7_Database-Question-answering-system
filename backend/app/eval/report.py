"""Render the Phase 9 evaluation report: JSON numbers + a standalone HTML page.

No template engine (the dependency budget has no Jinja/matplotlib), so the HTML
is assembled here from escaped strings. ``docs/eval/report.html`` is completely
self-contained — inline CSS, inline SVG plot — and opens in any browser;
``docs/eval/report.json`` carries the raw numbers for tooling and diffing.

Usage::

    from app.eval.report import write_report

    json_path, html_path = write_report(report)  # report from run_harness()

The file names are canonical (``report.json`` / ``report.html``) so ``make
eval`` and any stored link stay stable across runs; the run id is recorded
*inside* the JSON rather than in the file name.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Sequence

from ..core.settings import settings


def report_paths() -> tuple[Path, Path]:
    """``(report.json, report.html)`` under ``docs/eval``, creating the dir."""
    target = settings.docs_dir / "eval"
    target.mkdir(parents=True, exist_ok=True)
    return target / "report.json", target / "report.html"


def report_path_for(run_id: str | None = None) -> Path:
    """HTML report path for a run (canonical name; run id lives inside)."""
    return report_paths()[1]


# --------------------------------------------------------------------------
# Tiny rendering helpers
# --------------------------------------------------------------------------


class _Raw(str):
    """A cell that is already HTML and must not be escaped again."""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:.{digits}f}"
    return _esc(value)


def _pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def _pctv(value: Any, digits: int = 1) -> str:
    """Format a value that is *already* in percent units (e.g. savings_pct)."""
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}%"


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    classes: Sequence[str | None] | None = None,
) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body: list[str] = []
    for index, row in enumerate(rows):
        cls = ""
        if classes and index < len(classes) and classes[index]:
            cls = f' class="{_esc(classes[index])}"'
        cells = "".join(
            f"<td>{cell if isinstance(cell, _Raw) else _esc(cell)}</td>" for cell in row
        )
        body.append(f"<tr{cls}>{cells}</tr>")
    return (
        f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _grid(cards: Sequence[tuple[str, str, str]]) -> str:
    """``(label, value, hint)`` triplets rendered as headline tiles."""
    tiles = []
    for label, value, hint in cards:
        tiles.append(
            '<div class="card">'
            f'<div class="card-label">{_esc(label)}</div>'
            f'<div class="card-value">{value}</div>'
            f'<div class="card-hint">{_esc(hint)}</div>'
            "</div>"
        )
    return f'<div class="grid">{"".join(tiles)}</div>'


def _defs(pairs: Sequence[tuple[str, Any]]) -> str:
    items = []
    for key, value in pairs:
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        items.append(f"<div><dt>{_esc(key)}</dt><dd>{_esc(value)}</dd></div>")
    return f'<dl class="defs">{"".join(items)}</dl>'


def _routes(routes: dict[str, Any] | None) -> str:
    if not routes:
        return "—"
    return ", ".join(f"{key}×{count}" for key, count in sorted(routes.items()))


# --------------------------------------------------------------------------
# The accuracy-vs-hallucination plot (inline SVG, no plotting library)
# --------------------------------------------------------------------------


def _verifier_plot(
    sweep: dict[str, Any],
    key: str = "threshold",
    label: str = "verifier threshold",
) -> str:
    """Accuracy against hallucination across a sweep's points.

    ``key`` is the point's own name for the swept value: ``threshold`` for the
    verifier and cache sweeps, ``floor`` for the relevance floor; ``label``
    names it in the accessible description.
    """
    points = sweep.get("points") or []
    if len(points) < 2:
        return '<p class="note">Not enough sweep points to plot.</p>'
    xs = [float(p["hallucination_rate"]) for p in points]
    ys = [float(p["accuracy"]) for p in points]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    if x_hi - x_lo < 1e-9:
        x_lo, x_hi = max(0.0, x_lo - 0.05), min(1.0, x_hi + 0.05)
    if y_hi - y_lo < 1e-9:
        y_lo, y_hi = max(0.0, y_lo - 0.05), min(1.0, y_hi + 0.05)

    width, height = 640, 360
    left, right, top, bottom = 62, 18, 18, 52
    plot_w = width - left - right
    plot_h = height - top - bottom

    def sx(value: float) -> float:
        return left + (value - x_lo) / (x_hi - x_lo) * plot_w

    def sy(value: float) -> float:
        return top + (1.0 - (value - y_lo) / (y_hi - y_lo)) * plot_h

    chosen = sweep.get("chosen")
    dots = []
    for point in points:
        x, y = sx(float(point["hallucination_rate"])), sy(float(point["accuracy"]))
        is_chosen = chosen is not None and abs(float(point[key]) - chosen) < 1e-9
        radius = 7 if is_chosen else 5
        color = "var(--bad)" if is_chosen else "var(--accent)"
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}"/>'
            f'<text x="{x + 9:.1f}" y="{y + 4:.1f}" class="dot-label">'
            f"{float(point[key]):.2f}</text>"
        )
    polyline = " ".join(
        f"{sx(float(p['hallucination_rate'])):.1f},{sy(float(p['accuracy'])):.1f}"
        for p in points
    )
    return (
        f'<svg class="plot" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Accuracy versus hallucination rate across {_esc(label)} values">'
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" '
        'class="axis"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" class="axis"/>'
        f'<text x="{left + plot_w / 2:.0f}" y="{height - 12}" class="axis-label">'
        "hallucination rate →</text>"
        f'<text x="16" y="{top + plot_h / 2:.0f}" class="axis-label" '
        f'transform="rotate(-90 16 {top + plot_h / 2:.0f})">accuracy →</text>'
        f'<text x="{left - 10}" y="{top + 4:.0f}" class="tick" text-anchor="end">'
        f"{y_hi:.2f}</text>"
        f'<text x="{left - 10}" y="{top + plot_h:.0f}" class="tick" text-anchor="end">'
        f"{y_lo:.2f}</text>"
        f'<text x="{left}" y="{top + plot_h + 18:.0f}" class="tick">{x_lo:.3f}</text>'
        f'<text x="{left + plot_w}" y="{top + plot_h + 18:.0f}" class="tick" '
        f'text-anchor="end">{x_hi:.3f}</text>'
        f'<polyline points="{polyline}" class="line" fill="none"/>'
        f'{"".join(dots)}'
        "</svg>"
        f'<p class="note">Each dot is one {_esc(label)} (labelled); the red dot '
        "is the configured operating point. Down and right is worse.</p>"
    )


# --------------------------------------------------------------------------
# HTML assembly
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#f6f7f9;--card:#ffffff;--border:#e3e5ea;--fg:#18181b;--muted:#6b7280;
  --accent:#2563eb;--good:#15803d;--bad:#b91c1c;--mark:#fef9c3;
}
@media (prefers-color-scheme:dark){        :root{--bg:#0f1115;--card:#171a21;--border:#272b34;--fg:#e7e9ee;--muted:#9aa1ad;
        --accent:#60a5fa;--good:#4ade80;--bad:#f87171;--mark:#3a3406;}
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 20px 64px}
header{border-bottom:1px solid var(--border);background:var(--card)}
header .inner{max-width:1000px;margin:0 auto;padding:22px 20px}
h1{margin:0 0 4px;font-size:22px;letter-spacing:-.01em}
h2{font-size:16px;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid var(--border)}
section{margin-top:26px}
.meta{color:var(--muted);margin:0;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.card-label{color:var(--muted);font-size:12px}
.card-value{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums;margin-top:2px}
.card-hint{color:var(--muted);font-size:11px;margin-top:2px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--border);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--border);
  font-variant-numeric:tabular-nums;white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;background:rgba(127,127,127,.06)}
tr:last-child td{border-bottom:none}
tr.chosen{background:var(--mark)}
tr.pass td:first-child{color:var(--good);font-weight:600}
tr.fail td:first-child{color:var(--bad);font-weight:600}
.badge{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:600}
.badge.good{background:color-mix(in srgb,var(--good) 14%,transparent);color:var(--good)}
.badge.bad{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}
.badge.plain{background:rgba(127,127,127,.14);color:var(--muted)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:760px){.cols{grid-template-columns:1fr}}
.note{color:var(--muted);font-size:12px;margin:8px 2px}
.defs{margin:0;background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:6px 12px}
.defs>div{display:grid;grid-template-columns:230px 1fr;gap:10px;padding:5px 0;
  border-bottom:1px solid var(--border)}
.defs>div:last-child{border-bottom:none}
.defs dt{color:var(--muted);font-size:12px}
.defs dd{margin:0;font-size:13px;word-break:break-word}
blockquote{margin:6px 0;padding:6px 10px;border-left:3px solid var(--accent);
  background:rgba(127,127,127,.07);font-size:13px}
.failure{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;margin-top:10px}
.failure h3{margin:0 0 6px;font-size:13px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kv{color:var(--muted);font-size:12px;margin:4px 0}
.kv b{color:var(--fg);font-weight:600}
.plot{width:100%;height:auto;background:var(--card);border:1px solid var(--border);
  border-radius:10px;margin-top:10px}
.axis{stroke:var(--muted);stroke-width:1}
.line{stroke:var(--accent);stroke-width:2}
.dot-label{fill:var(--muted);font-size:11px;font-family:ui-monospace,Menlo,Consolas,monospace}
.axis-label{fill:var(--muted);font-size:12px}
.tick{fill:var(--muted);font-size:11px;font-family:ui-monospace,Menlo,Consolas,monospace}
footer{max-width:1000px;margin:0 auto;padding:0 20px 30px;color:var(--muted);font-size:12px}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
"""


def _render_html(report: dict[str, Any]) -> str:
    headline = report.get("headline", {})
    answers = report.get("answers", {})
    routing = report.get("routing", {})
    retrieval = report.get("retrieval", {})
    citation = report.get("citation_validity", {})
    scenarios = report.get("scenarios", [])
    sweeps = report.get("sweeps", {})
    load = report.get("load_test", {})
    resources = report.get("resources", {})
    config = report.get("config", {})
    failures = report.get("failure_analysis", [])
    ablations = report.get("ablations", {})
    verifier_ablation = (ablations.get("verifier") or {}) if ablations else {}

    sections: list[str] = []

    # ---- headline ---------------------------------------------------------
    sections.append(
        "<section><h2>Headline</h2>"
        + _grid(
            [
                ("Answer accuracy", _pct(headline.get("accuracy")), "answerable items"),
                ("Groundedness", _pct(headline.get("groundedness")), "claims supported"),
                (
                    "Hallucination rate",
                    _pct(headline.get("hallucination_rate")),
                    "of all items",
                ),
                (
                    "Abstention (unanswerable)",
                    _pct(headline.get("abstention_unanswerable")),
                    "correct refusals",
                ),
                ("Retrieval MRR", _num(headline.get("retrieval_mrr"), 3), "hybrid+rerank"),
                ("Success@1", _pct(headline.get("retrieval_success_at_1")), "gold at rank 1"),
                ("Routing agreement", _pct(headline.get("routing_agreement")), "vs oracle"),
                (
                    "Cost savings",
                    _pctv(headline.get("cost_savings_pct")),
                    "vs always-cloud",
                ),
                ("Peak RAM", _num(headline.get("peak_ram_mb"), 0) + " MB", "budget 8192 MB"),
                (
                    "Load p95",
                    _num(headline.get("load_p95_ms"), 0) + " ms"
                    if headline.get("load_p95_ms") is not None
                    else "—",
                    "20 concurrent users",
                ),
                (
                    "Scenarios",
                    f"{headline.get('scenarios_passed', 0)}/{headline.get('scenarios_total', 0)}",
                    "resource suite",
                ),
                (
                    "Access-control leaks",
                    str(headline.get("access_control_leaks", 0)),
                    f"{headline.get('access_control_cases', 0)} red-team cases",
                ),
            ]
        )
        + "</section>"
    )

    # ---- access control (Phase 9, item 5) ----------------------------------
    access = report.get("access_control") or {}
    if access:
        role_rows = [
            [
                role,
                bucket.get("cases", 0),
                bucket.get("prompts", 0),
                bucket.get("requests", 0),
                bucket.get("prompts", 0) + bucket.get("requests", 0),
                bucket.get("leaks", 0),
            ]
            for role, bucket in sorted((access.get("per_role") or {}).items())
        ]
        vector_rows = [
            [vector, bucket.get("cases", 0), bucket.get("leaks", 0),
             bucket.get("inconclusive", 0)]
            for vector, bucket in sorted(
                (access.get("by_vector") or {}).items()
            )
        ]
        verdict = (
            '<span class="badge good">pass</span>'
            if access.get("passed")
            else '<span class="badge bad">fail</span>'
        )
        part = [
            "<section><h2>Access control (red team)</h2>",
            '<p class="kv">' + verdict + " " + _esc(access.get("method", "")) +
            "</p>",
            _grid(
                [
                    ("Leaks", str(access.get("leaks", 0)), "must be 0"),
                    ("Cases", str(access.get("cases", 0)), "prompts + requests"),
                    (
                        "Prompts answered",
                        str(access.get("prompts_answered", 0)),
                        "real answers inspected",
                    ),
                    (
                        "Roles with 30+",
                        f"{sum(1 for ok in (access.get('roles_meet_min') or {}).values() if ok)}/3",
                        "plan Ph.9 item 5",
                    ),
                    (
                        "Inconclusive",
                        str(access.get("inconclusive_count", 0)),
                        "neither leak nor proof",
                    ),
                    (
                        "Skipped",
                        str(access.get("skipped_count", 0)),
                        "cases that could not run",
                    ),
                ]
            ),
            _table(
                ["role", "cases", "prompts", "requests", "total", "leaks"],
                role_rows or [["—", 0, 0, 0, 0, 0]],
            ),
            _table(
                ["attack vector", "cases", "leaks", "inconclusive"],
                vector_rows or [["—", 0, 0, 0]],
            ),
        ]
        failures = access.get("failures") or []
        if failures:
            part.append(
                _table(
                    ["role", "case", "status", "why it leaked"],
                    [
                        [f.get("role"), f.get("case"), f.get("status"),
                         f.get("detail")]
                        for f in failures
                    ],
                )
            )
        skipped = access.get("skipped") or []
        if skipped:
            part.append(
                _table(
                    ["role", "case", "why it did not run"],
                    [
                        [f.get("role"), f.get("case"), f.get("detail")]
                        for f in skipped
                    ],
                )
            )
        part.append("</section>")
        sections.append("".join(part))

    # ---- answers ----------------------------------------------------------
    per_kind = answers.get("per_kind", {})
    kind_rows = [
        [
            kind,
            bucket.get("n"),
            bucket.get("answered"),
            bucket.get("correct"),
            bucket.get("abstained"),
            _pct(bucket.get("accuracy")),
        ]
        for kind, bucket in sorted(per_kind.items())
    ]
    sections.append(
        "<section><h2>Answers</h2>"
        + _table(
            ["metric", "value"],
            [
                ["items", answers.get("total")],
                ["answerable / unanswerable", f"{answers.get('answerable', 0)} / {answers.get('unanswerable', 0)}"],
                ["delivered / abstained (answerable)", f"{answers.get('answered', 0)} / {answers.get('abstained_answerable', 0)}"],
                ["correct", answers.get("correct")],
                ["accuracy", _pct(answers.get("accuracy"))],
                ["groundedness", _pct(answers.get("groundedness"))],
                ["claim support rate", _pct(answers.get("claim_support_rate"))],
                ["citation rate (gold cited)", _pct(answers.get("citation_rate"))],
                ["hallucinated / rate", f"{answers.get('hallucinated', 0)} · {_pct(answers.get('hallucination_rate'))}"],
                [
                    "abstention on unanswerable",
                    f"{answers.get('unanswerable_abstained', 0)} · {_pct(answers.get('abstention_rate_unanswerable'))}",
                ],
                [
                    "citation validity",
                    f"{citation.get('valid', 0)}/{citation.get('cited', 0)}"
                    + (f" · {_pct(citation.get('validity'))}" if citation.get("validity") is not None else ""),
                ],
                [
                    "latency p50 / p95",
                    f"{_num(answers.get('latency_p50_ms'), 0)} / {_num(answers.get('latency_p95_ms'), 0)} ms",
                ],
            ],
        )
        + '<h2 style="margin-top:16px">Per kind</h2>'
        + _table(
            ["kind", "n", "answered", "correct", "abstained", "accuracy"],
            kind_rows or [["—", "—", "—", "—", "—", "—"]],
        )
        + "</section>"
    )

    # ---- ablations --------------------------------------------------------
    retrieval_rows = []
    for mode in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        metrics = retrieval.get(mode)
        if not metrics:
            continue
        retrieval_rows.append(
            [
                mode,
                _num(metrics.get("success_at_1"), 3),
                _num(metrics.get("success_at_3"), 3),
                _num(metrics.get("success_at_5"), 3),
                _num(metrics.get("precision_at_1"), 3),
                _num(metrics.get("precision_at_3"), 3),
                _num(metrics.get("precision_at_5"), 3),
                _num(metrics.get("recall_at_k"), 3),
                _num(metrics.get("mrr"), 3),
                _num(metrics.get("latency_p50_ms"), 1),
                _num(metrics.get("latency_p95_ms"), 1),
            ]
        )
    ablation_html = (
        "<section><h2>Ablations</h2>"
        '<p class="note">Retrieval: same questions, four fusion/rerank configurations.</p>'
        + _table(
            [
                "mode", "S@1", "S@3", "S@5", "P@1", "P@3", "P@5",
                "recall@k", "MRR", "p50 ms", "p95 ms",
            ],
            retrieval_rows,
        )
    )
    if verifier_ablation:
        on = verifier_ablation.get("on", {})
        off = verifier_ablation.get("off", {})
        def delta(key: str) -> str:
            try:
                value = float(on.get(key, 0)) - float(off.get(key, 0))
            except (TypeError, ValueError):
                return "—"
            return f"{value:+.4f}"
        ablation_html += (
            '<p class="note" style="margin-top:16px">Verifier: same items, gate on vs off.</p>'
            + _table(
                ["metric", "with verifier", "without", "delta"],
                [
                    ["accuracy", _num(on.get("accuracy")), _num(off.get("accuracy")), delta("accuracy")],
                    ["groundedness", _num(on.get("groundedness")), _num(off.get("groundedness")), delta("groundedness")],
                    [
                        "hallucination rate",
                        _num(on.get("hallucination_rate")),
                        _num(off.get("hallucination_rate")),
                        delta("hallucination_rate"),
                    ],
                    [
                        "abstention (unanswerable)",
                        _num(on.get("abstention_rate_unanswerable")),
                        _num(off.get("abstention_rate_unanswerable")),
                        delta("abstention_rate_unanswerable"),
                    ],
                    ["answers delivered", _num(on.get("answered")), _num(off.get("answered")), delta("answered")],
                ],
            )
            + f'<p class="note">{_esc(verifier_ablation.get("note", ""))}</p>'
        )
    ablation_html += (
        '<p class="note" style="margin-top:16px">Router: policy vs no policy '
        "(always-cloud baseline pays the cloud price for every question).</p>"
        + _table(
            ["route policy", "cost (INR)", "note"],
            [
                [
                    "with router",
                    _num(routing.get("cumulative_cost_inr")),
                    _routes(routing.get("routes")),
                ],
                [
                    "without router (always cloud)",
                    _num(routing.get("always_cloud_cost_inr")),
                    f"saves {_num(routing.get('savings_inr'))} INR "
                    f"({_pctv(routing.get('savings_pct'))})",
                ],
            ],
        )
        + "</section>"
    )
    sections.append(ablation_html)

    # ---- routing ----------------------------------------------------------
    latency_rows = [
        [route, values.get("n"), _num(values.get("p50_ms"), 1), _num(values.get("p95_ms"), 1)]
        for route, values in sorted((routing.get("per_route_latency_ms") or {}).items())
    ]
    sections.append(
        "<section><h2>Routing</h2>"
        + _grid(
            [
                ("Agreement vs oracle", _pct(routing.get("agreement")), f"{routing.get('questions', 0)} questions"),
                ("Cache hit rate", _pct(routing.get("cache_hit_rate")), "semantic cache"),
                ("Savings vs always-cloud", _pctv(routing.get("savings_pct")), "cost, not quality"),
                ("Policy cost", f"{_num(routing.get('cumulative_cost_inr'))} INR", "this run"),
            ]
        )
        + '<p class="note" style="margin-top:12px">Per-route answer latency (p50/p95, ms).</p>'
        + _table(["route", "n", "p50 ms", "p95 ms"], latency_rows or [["—", "—", "—", "—"]])
        + "</section>"
    )

    # ---- sweeps -----------------------------------------------------------
    verifier_sweep = sweeps.get("verifier_threshold") or {}
    relevance_sweep = sweeps.get("relevance_floor") or {}
    cache_sweep = sweeps.get("cache_cosine") or {}
    ram_sweep = sweeps.get("ram_floor") or {}
    sweep_parts = ["<section><h2>Threshold sweeps</h2>"]
    if verifier_sweep.get("points"):
        rows, classes = [], []
        for point in verifier_sweep["points"]:
            chosen = abs(float(point["threshold"]) - float(verifier_sweep.get("chosen", -1))) < 1e-9
            rows.append(
                [
                    f"{point['threshold']:.2f}" + (" ← chosen" if chosen else ""),
                    _num(point.get("accuracy")),
                    _num(point.get("hallucination_rate")),
                    _num(point.get("abstention_rate_unanswerable")),
                    point.get("answered"),
                ]
            )
            classes.append("chosen" if chosen else None)
        # A flat sweep means the gate decides nothing in this configuration, and
        # a plot of eight coincident dots would hide that instead of saying it.
        flat = len(
            {
                (p.get("accuracy"), p.get("hallucination_rate"), p.get("answered"))
                for p in verifier_sweep["points"]
            }
        ) == 1
        flat_note = ""
        if flat:
            highest = max(float(p["threshold"]) for p in verifier_sweep["points"])
            flat_note = (
                '<p class="note"><strong>This sweep is flat by construction.</strong> '
                "Every delivered answer in this run scored at or above the highest "
                f"swept threshold ({highest:.2f}), so moving the confidence gate "
                "changes no decision. Abstentions here are produced before "
                "generation by the retrieval relevance floor below; the confidence "
                "gate is what protects the model path.</p>"
            )
        sweep_parts.append(
            '<p class="note">Verifier confidence threshold (offline re-derivation).</p>'
            + _table(
                ["threshold", "accuracy", "hallucination rate", "abstention (unans.)", "answered"],
                rows,
                classes,
            )
            + ("" if flat else _verifier_plot(verifier_sweep))
            + flat_note
            + f'<p class="note">{_esc(verifier_sweep.get("note", ""))}</p>'
        )
    if relevance_sweep.get("points"):
        rows, classes = [], []
        for point in relevance_sweep["points"]:
            chosen = abs(
                float(point["floor"]) - float(relevance_sweep.get("chosen", -1))
            ) < 1e-9
            rows.append(
                [
                    f"{point['floor']:.1f}" + (" ← chosen" if chosen else ""),
                    _num(point.get("accuracy")),
                    f"{point.get('correct')}/{point.get('answered')}",
                    _num(point.get("hallucination_rate")),
                    _num(point.get("abstention_rate_unanswerable")),
                ]
            )
            classes.append("chosen" if chosen else None)
        sweep_parts.append(
            '<p class="note" style="margin-top:16px">Retrieval relevance floor: the '
            "best BM25 score retrieval must reach before passages are used at all. "
            "Each point is a real answer pass at that floor.</p>"
            + _table(
                [
                    "floor",
                    "accuracy",
                    "correct/answered",
                    "hallucination rate",
                    "abstention (unans.)",
                ],
                rows,
                classes,
            )
            + _verifier_plot(relevance_sweep, key="floor", label="retrieval relevance floor")
            + f'<p class="note">{_esc(relevance_sweep.get("note", ""))}</p>'
        )
    if cache_sweep.get("points"):
        rows, classes = [], []
        for point in cache_sweep["points"]:
            chosen = abs(float(point["threshold"]) - float(cache_sweep.get("chosen", -1))) < 1e-9
            rows.append(
                [
                    f"{point['threshold']:.2f}" + (" ← chosen" if chosen else ""),
                    _num(point.get("collision_rate")),
                    point.get("collisions"),
                    _num(point.get("max_similarity")),
                ]
            )
            classes.append("chosen" if chosen else None)
        sweep_parts.append(
            '<p class="note" style="margin-top:16px">Cache cosine floor: sharing an '
            "answer across two different benchmark questions.</p>"
            + _table(["threshold", "collision rate", "collisions", "max similarity"], rows, classes)
            + f'<p class="note">{_esc(cache_sweep.get("note", ""))}</p>'
        )
    if ram_sweep.get("points"):
        rows, classes = [], []
        for point in ram_sweep["points"]:
            rows.append(
                [
                    f"{point['floor_mb']} MB" + (" ← chosen" if point.get("is_current") else ""),
                    _num(point.get("fallback_share_logged")),
                    _num(point.get("cost_inr_for_sample")),
                    _routes(point.get("routes")),
                ]
            )
            classes.append("chosen" if point.get("is_current") else None)
        sweep_parts.append(
            '<p class="note" style="margin-top:16px">RAM floor: when the local path is '
            "declared unavailable.</p>"
            + _table(["floor", "fallback share (logged)", "cost (INR, sample)", "routes"], rows, classes)
            + f'<p class="note">{_esc(ram_sweep.get("note", ""))}</p>'
        )
    if not sweeps:
        sweep_parts.append('<p class="note">Sweeps skipped for this run.</p>')
    sweep_parts.append("</section>")
    sections.append("".join(sweep_parts))

    # ---- scenarios --------------------------------------------------------
    scenario_rows = []
    scenario_classes: list[str | None] = []
    for scenario in scenarios:
        scenario_rows.append(
            [
                scenario.get("scenario"),
                _Raw(
                    '<span class="badge good">PASS</span>'
                    if scenario.get("passed")
                    else '<span class="badge bad">FAIL</span>'
                ),
                scenario.get("steps"),
                _routes(scenario.get("routes")),
                scenario.get("detail"),
            ]
        )
        scenario_classes.append("pass" if scenario.get("passed") else "fail")
    sections.append(
        "<section><h2>Resource scenarios</h2>"
        + _table(
            ["scenario", "result", "steps", "routes", "detail"],
            scenario_rows,
            scenario_classes,
        )
        + "</section>"
    )

    # ---- load test --------------------------------------------------------
    if load.get("ran"):
        load_html = (
            "<section><h2>Load test</h2>"
            + _grid(
                [
                    ("Users", str(load.get("users", "—")), "concurrent"),
                    ("Requests", f"{load.get('completed', 0)}/{load.get('requests', 0)}", "completed, errors " + str(load.get("errors", 0))),
                    ("Throughput", f"{_num(load.get('throughput_rps'), 2)} rps", "wall " + _num(load.get("wall_seconds"), 1) + " s"),
                    ("Latency p50 / p95", f"{_num(load.get('p50_ms'), 0)} / {_num(load.get('p95_ms'), 0)} ms", "max " + _num(load.get("max_ms"), 0) + " ms"),
                    ("p95 / p50", _num(load.get("p95_over_p50"), 2), "queueing signature"),
                    ("Graceful", "yes" if load.get("graceful") else "no", "no crashes"),
                ]
            )
            + f'<p class="note">{_esc(load.get("queueing_note", ""))}</p>'
        )
        if load.get("error_samples"):
            load_html += '<p class="note">Errors: ' + _esc("; ".join(load["error_samples"])) + "</p>"
        sections.append(load_html + "</section>")
    else:
        sections.append(
            "<section><h2>Load test</h2>"
            f'<p class="note">{_esc(load.get("reason", "skipped"))}</p></section>'
        )

    # ---- resources --------------------------------------------------------
    sections.append(
        "<section><h2>Resources</h2>"
        + _grid(
            [
                ("Peak RSS", _num(resources.get("peak_rss_mb"), 0) + " MB", f"budget {_num(resources.get('budget_mb'), 0)} MB"),
                ("Within budget", "yes" if resources.get("within_budget") else "NO", "8 GB constraint"),
                ("Min host free RAM", _num(resources.get("host_min_available_mb"), 0) + " MB", "during the run"),
                ("Samples", str(resources.get("samples", 0)), "psutil, 100 ms interval"),
            ]
        )
        + "</section>"
    )

    # ---- failure analysis -------------------------------------------------
    failure_parts = [
        "<section><h2>Failure analysis — 10 worst</h2>",
        '<p class="note">Sorted by severity: answered wrongly on unanswerable '
        "questions, retrieval misses, missing numbers, then weak text matches.</p>",
    ]
    if not failures:
        failure_parts.append('<p class="note">No failures in this run.</p>')
    for index, failure in enumerate(failures, start=1):
        kind_badge = (
            '<span class="badge bad">hallucination</span>'
            if failure.get("kind_of") == "hallucination"
            else '<span class="badge plain">wrong</span>'
        )
        expected = failure.get("expected") or ""
        failure_parts.append(
            '<article class="failure">'
            f"<h3>#{index} <code>{_esc(failure.get('id'))}</code> "
            f'<span class="badge plain">{_esc(failure.get("kind"))}</span>{kind_badge}</h3>'
            f'<p class="kv">cause: <b>{_esc(failure.get("cause"))}</b> · fix: '
            f'<b>{_esc(failure.get("fix"))}</b></p>'
            f"<blockquote>{_esc(failure.get('question'))}</blockquote>"
            f'<p class="kv">delivered: <b>{_esc(failure.get("answer"))}</b></p>'
            + (f'<p class="kv">expected: <b>{_esc(expected)}</b></p>' if expected else "")
            + "</article>"
        )
    failure_parts.append("</section>")
    sections.append("".join(failure_parts))

    # ---- config + methodology --------------------------------------------
    sections.append(
        "<section><h2>Configuration</h2>"
        + _defs(
            [
                (key, value)
                for key, value in config.items()
                if not isinstance(value, (dict, list)) or key in {"index"}
            ]
        )
        + "</section>"
    )
    sections.append(
        "<section><h2>Methodology</h2>"
        + _defs(sorted((report.get("methodology") or {}).items()))
        + "</section>"
    )

    meta = (
        f"run <code>{_esc(report.get('run_id'))}</code> · "
        f"generated {_esc(report.get('generated_at'))} · "
        f"scope {_esc(report.get('scope'))} · "
        f"wall {_esc(report.get('wall_seconds'))} s"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>AMYPO evaluation report — {_esc(report.get('run_id'))}</title>"
        f"<style>{CSS}</style></head><body>"
        f"<header><div class='inner'><h1>AMYPO evaluation report</h1>"
        f'<p class="meta">{meta}</p></div></header>'
        f'<main>{"".join(sections)}</main>'
        f"<footer>Generated by <code>app.eval.report</code> from "
        f"<code>run_harness()</code> — full data in <code>report.json</code>.</footer>"
        "</body></html>\n"
    )


def write_report(report: dict[str, Any]) -> tuple[Path, Path]:
    """Write ``docs/eval/report.json`` and ``docs/eval/report.html``.

    Returns ``(json_path, html_path)``. Both files are overwritten every run so
    ``make eval`` is reproducible and links stay stable.
    """
    json_path, html_path = report_paths()
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(_render_html(report), encoding="utf-8")
    return json_path, html_path
