"""Submission artefacts (Phase 10): diagram, one-page summary, Postman collection.

Three artefacts that are generated rather than hand-drawn, so they cannot drift
from the code, and so a fresh clone can rebuild them:

* ``docs/architecture.png`` + ``docs/architecture.pdf`` — the component diagram.
* ``docs/final_summary.pdf`` — the one-page problem/approach/innovations sheet,
  with the headline numbers read from ``docs/eval/report.json`` (run ``make eval``
  first; the page states plainly when no report exists rather than inventing
  numbers).
* ``docs/postman_collection.json`` — a Postman v2.1 collection derived from
  ``openapi.yaml``, so every documented endpoint is importable.

Usage::

    python scripts/make_artifacts.py --all
    python scripts/make_artifacts.py --only diagram
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"


# --------------------------------------------------------------------------
# Component diagram
# --------------------------------------------------------------------------

# (label, detail, lane) — lane 0 is the top row. Keeping this as data means the
# picture and the component list are the same object.
DIAGRAM_ROWS: list[list[tuple[str, str]]] = [
    [
        ("UI", "Next.js · chat, placement, dashboard,\nknowledge, evaluation, audit"),
    ],
    [
        ("API", "FastAPI /api/v1\nask · route · placement · ingest ·\nmonitor · evaluation"),
    ],
    [
        ("Router", "complexity classifier +\nresource-aware policy"),
        ("Monitor", "RAM / CPU / bandwidth /\ncloud quota + simulator"),
        ("Tools", "SQL templates over\nstructured records"),
    ],
    [
        ("Retriever", "BM25 + dense RRF +\nfeature reranker"),
        ("Semantic cache", "scope-keyed, source-hash\nguarded, pre-warmed"),
    ],
    [
        ("LLM", "Ollama phi3:mini →\nsmall model → extractive"),
        ("Verifier", "claim support +\nnumeric gate"),
        ("Placement engine", "eligibility · skill gap ·\nwhat-if · PDF report"),
    ],
    [
        ("MySQL", "documents, chunks, records,\nquery_log, cohort audit, cache"),
        ("Vector/lexical index", "FAISS when available,\nnumpy hash fallback"),
        ("Evaluation harness", "benchmark, ablations, sweeps,\nscenarios, load test"),
    ],
]


def make_diagram() -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 8.2), dpi=170)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 8.4)
    ax.axis("off")
    ax.set_title(
        "AMYPO — offline-first campus policy & placement copilot",
        fontsize=15,
        fontweight="bold",
        pad=14,
    )

    lane_height = 1.16
    for row_index, row in enumerate(DIAGRAM_ROWS):
        top = 7.9 - row_index * lane_height
        count = len(row)
        width = min(3.9, 12.0 / count - 0.12)
        for column_index, (label, detail) in enumerate(row):
            x = 0.5 + column_index * (12.0 / count) + (12.0 / count - width) / 2
            box = patches.FancyBboxPatch(
                (x, top - 0.86),
                width,
                0.86,
                boxstyle="round,pad=0.04,rounding_size=0.09",
                linewidth=1.1,
                edgecolor="#1f6f4a",
                facecolor="#eaf5ef",
            )
            ax.add_patch(box)
            ax.text(
                x + width / 2,
                top - 0.26,
                label,
                ha="center",
                va="center",
                fontsize=10.5,
                fontweight="bold",
                color="#12503a",
            )
            ax.text(
                x + width / 2,
                top - 0.60,
                detail,
                ha="center",
                va="center",
                fontsize=7.6,
                color="#333333",
            )
        # The vertical spine connecting the lanes stands in for the request path.
        ax.annotate(
            "",
            xy=(0.30, top - lane_height + 0.30),
            xytext=(0.30, top - 0.30),
            arrowprops={"arrowstyle": "-|>", "color": "#1f6f4a", "linewidth": 1.4},
        )

    ax.text(
        0.5,
        0.30,
        "Loopback only: MySQL and Ollama run on the host. No third-party API is called, "
        "at runtime or during evaluation.",
        fontsize=8.4,
        color="#555555",
    )

    png = DOCS / "architecture.png"
    pdf = DOCS / "architecture.pdf"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    fig.savefig(pdf, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png, pdf]


# --------------------------------------------------------------------------
# One-page summary
# --------------------------------------------------------------------------


def _headline() -> dict | None:
    report = DOCS / "eval" / "report.json"
    if not report.exists():
        return None
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (TypeError, ValueError):
        return None
    return data.get("headline") | {"generated_at": data.get("generated_at")}


def make_summary() -> list[Path]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=styles["Heading1"], fontSize=17, spaceAfter=2)
    sub = ParagraphStyle("S", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#555555"), spaceAfter=10)
    heading = ParagraphStyle("H", parent=styles["Heading2"], fontSize=11,
                             spaceBefore=9, spaceAfter=4)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=12.5)

    headline = _headline()
    story = [
        Paragraph("AMYPO — Campus Policy &amp; Placement Copilot", title),
        Paragraph(
            "Offline-first grounded question answering over college records. "
            "One command starts it; no third-party API is used at any point.",
            sub,
        ),
        Paragraph("Problem", heading),
        Paragraph(
            "Students and staff ask answerable questions of policy documents and "
            "structured records, but generic assistants are unavailable offline, cost "
            "money per call, and answer without evidence. AMYPO answers only from the "
            "campus corpus, cites the record behind every claim, abstains when the "
            "evidence is missing, and runs inside an 8 GB budget on one machine.",
            body,
        ),
        Paragraph("Approach", heading),
        Paragraph(
            "Hybrid retrieval (BM25 + dense fusion with a feature reranker) over "
            "6 300+ chunks; a complexity classifier that routes each question to the "
            "cheapest adequate path; a grounding verifier that gates every claim on "
            "lexical support and numeric fidelity; a scope-keyed semantic cache; and "
            "deterministic placement answering where eligibility must be decided, not "
            "generated. The local model degrades in three tiers — phi3:mini, a smaller "
            "model, then extractive quoting — so a RAM or bandwidth drop changes the "
            "route, never the availability.",
            body,
        ),
        Paragraph("Innovations", heading),
        Paragraph(
            "Self-optimizing router that retrains from thumbs feedback on a fixed "
            "holdout; claim-level citation highlighting with unsupported claims flagged; "
            "abstention that names the closest records and asks a clarifying question; "
            "conflict detection that surfaces a superseded policy instead of silently "
            "picking a winner; predictive cache pre-warming at ingest time; a per-query "
            "energy and INR line item against an always-cloud baseline; multilingual "
            "input detection; PDF eligibility export; and a readable audit trail for "
            "every staff cohort query.",
            body,
        ),
    ]

    if headline:
        rows = [
            ["Answer accuracy", f"{headline['accuracy'] * 100:.1f}%"],
            ["Groundedness", f"{headline['groundedness'] * 100:.1f}%"],
            ["Hallucination rate", f"{headline['hallucination_rate'] * 100:.1f}%"],
            ["Abstention (unanswerable)", f"{headline['abstention_unanswerable'] * 100:.1f}%"],
            ["Retrieval MRR / S@1",
             f"{headline['retrieval_mrr']:.3f} / {headline['retrieval_success_at_1'] * 100:.1f}%"],
            ["Routing agreement", f"{headline['routing_agreement'] * 100:.1f}%"],
            ["Cost vs always-cloud", f"{headline['cost_savings_pct']:.1f}% saved"],
            ["Peak RAM", f"{headline['peak_ram_mb']:.0f} MB of 8192 MB"],
            ["Resource scenarios", f"{headline['scenarios_passed']}/{headline['scenarios_total']} passed"],
            ["Load test p95", f"{headline['load_p95_ms']:.0f} ms at 20 users"],
        ]
        table = Table(rows, colWidths=[62 * mm, 46 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#333333")),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#12503a")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#dddddd")),
                ]
            )
        )
        story += [Paragraph("Headline numbers", heading), table]
        story.append(
            Paragraph(
                f"From <b>docs/eval/report.json</b> (run {headline.get('generated_at')}), "
                "reproduced by <b>make eval</b>.",
                sub,
            )
        )
    else:
        story.append(
            Paragraph(
                "No evaluation report has been generated yet. Run <b>make eval</b> and "
                "regenerate this page so it reports measured numbers rather than claims.",
                body,
            )
        )

    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Stack: Python 3.12 · FastAPI · MySQL 8 · scikit-learn · numpy · optional "
            "FAISS/sentence-transformers · Next.js 14 · Ollama (phi3:mini), all local. "
            "Models: phi3:mini 3.8B q4 (~2.2 GB, MIT) with a deterministic extractive "
            "fallback; see docs/model_card.md for licences and known limitations.",
            sub,
        )
    )

    out = DOCS / "final_summary.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title="AMYPO — one-page summary",
        author="AMYPO",
    )
    doc.build(story)
    return [out]


# --------------------------------------------------------------------------
# Postman collection
# --------------------------------------------------------------------------


def make_postman() -> list[Path]:
    import yaml

    spec = yaml.safe_load((PROJECT_ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    api_root = spec.get("servers", [{}])[0].get("url", "http://127.0.0.1:8000/api/v1")
    items = []
    for path, operations in sorted(spec["paths"].items()):
        for method, operation in sorted(operations.items()):
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            parameters = operation.get("parameters", []) or []
            query = [
                {"key": p["name"], "value": str(p.get("example", ""))}
                for p in parameters
                if p.get("in") == "query"
            ]
            variables = [
                p["name"] for p in parameters if p.get("in") == "path" and p.get("required")
            ]
            # Postman uses :name for path variables.
            url_path = path
            for name in variables:
                url_path = url_path.replace(f"{{{name}}}", f":{name}")
            request: dict = {
                "name": operation.get("summary", f"{method.upper()} {path}"),
                "request": {
                    "method": method.upper(),
                    "header": [{"key": "Content-Type", "value": "application/json"}],
                    "url": {
                        "raw": "{{baseUrl}}" + url_path
                        + ("?" + "&".join(f"{q['key']}={q['value']}" for q in query) if query else ""),
                        "host": ["{{baseUrl}}"],
                        "path": [p for p in url_path.strip("/").split("/") if p],
                        "query": query,
                        "variable": [{"key": name, "value": ""} for name in variables],
                    },
                    "description": (operation.get("description") or "").strip(),
                },
            }
            if method == "post" and "requestBody" in operation:
                examples = (
                    operation["requestBody"].get("content", {})
                    .get("application/json", {})
                    .get("examples")
                )
                body = next(iter(examples.values()))["value"] if examples else {}
                request["request"]["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(body, indent=2),
                    "options": {"raw": {"language": "json"}},
                }
            items.append(request)

    collection = {
        "info": {
            "name": "AMYPO API",
            "description": (
                "Derived from openapi.yaml by scripts/make_artifacts.py — regenerate "
                "rather than editing, so the collection cannot drift from the spec."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": "baseUrl", "value": api_root}],
        "item": items,
    }
    out = DOCS / "postman_collection.json"
    out.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    return [out]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the submission artefacts")
    parser.add_argument(
        "--only",
        choices=["diagram", "summary", "postman", "all"],
        default="all",
        help="which artefact to build",
    )
    args = parser.parse_args(argv)

    DOCS.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if args.only in ("diagram", "all"):
        written += make_diagram()
    if args.only in ("summary", "all"):
        written += make_summary()
    if args.only in ("postman", "all"):
        written += make_postman()
    for path in written:
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
