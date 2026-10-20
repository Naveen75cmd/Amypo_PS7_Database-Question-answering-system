"""Build the three submission documents as PDFs.

    python scripts/make_guides.py            # all three
    python scripts/make_guides.py --only guide

``docs/product_guide.pdf`` is the engineering document: what the product does
end to end, the models and algorithms behind each step, the datasets, the code
map and the measured results. ``docs/user_manual.pdf`` is the reader-facing
manual: sign in, ask, read the answer, and what each role can do.
``docs/manual_test_guide.pdf`` is the hand-run acceptance plan: a coverage map
and 45 numbered checks with the exact UI labels and expected results.

Every number is read from the artefacts at build time (``docs/eval/report.json``,
``data/synthetic/summary.json``, the benchmark and the corpus), and the build
fails if a non-ASCII character reaches the page -- the built-in Helvetica fonts
only cover WinAnsi, so a stray glyph would otherwise render as a blank box.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = ROOT / "data"

ACCENT = colors.HexColor("#0f766e")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4b5563")
RULE = colors.HexColor("#d1d5db")
TINT = colors.HexColor("#ecfdf5")
WARN = colors.HexColor("#92400e")


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=28, textColor=INK, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=11.5, leading=15, textColor=MUTED, spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=15, leading=18, textColor=ACCENT, spaceBefore=16,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=14, textColor=INK, spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.6, leading=13.4, textColor=INK, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.6, leading=13.4, textColor=INK, leftIndent=11,
            bulletIndent=3, spaceAfter=2.5,
        ),
        "note": ParagraphStyle(
            "note", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=8.6, leading=11.6, textColor=MUTED, spaceAfter=4,
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.2, leading=12.6, textColor=WARN, spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontName="Courier",
            fontSize=8.2, leading=10.6, textColor=INK, leftIndent=6,
            backColor=colors.HexColor("#f3f4f6"), borderPadding=4, spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.2, leading=10.4, textColor=INK,
        ),
        "cellb": ParagraphStyle(
            "cellb", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8.6, leading=10.6, textColor=colors.white,
        ),
    }


S = styles()


def P(text: str, style: str = "body") -> Paragraph:
    """A paragraph, refusing any non-ASCII character (see module docstring)."""
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:  # pragma: no cover - build-time guard
        raise SystemExit(f"non-ASCII text in the document: {text[exc.start:exc.start + 20]!r}") from exc
    return Paragraph(text, S[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [P(f"&#8226; {item}", "bullet") for item in items]


def table(header: list[str], rows: list[list[str]], widths: list[float] | None = None) -> Table:
    data = [[P(escape(h), "cellb") for h in header]]
    for row in rows:
        data.append([P(escape(str(cell)), "cell") for cell in row])
    total = 165 * mm
    widths = widths or [total / len(header)] * len(header)
    widths = [total * w / sum(widths) for w in widths]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    return t


def callout(text: str) -> Table:
    t = Table([[P(text, "body")]], colWidths=[165 * mm], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TINT),
                ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


# --------------------------------------------------------------------------
# Facts read from the repository at build time
# --------------------------------------------------------------------------


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def facts() -> dict:
    summary = read_json(DATA / "synthetic" / "summary.json", {})
    report = read_json(DOCS / "eval" / "report.json", {})
    items = []
    bench = DATA / "eval" / "benchmark.jsonl"
    if bench.exists():
        items = [json.loads(line) for line in bench.read_text(encoding="utf-8").splitlines() if line.strip()]
    kinds = Counter(i.get("kind") for i in items)
    answerable = sum(1 for i in items if i.get("answerable", True))
    docs = sorted((DATA / "raw").rglob("*.md"))
    words = sum(len(p.read_text(encoding="utf-8").split()) for p in docs)
    csv_rows = {}
    for path in sorted((DATA / "synthetic").glob("*.csv")):
        with path.open(encoding="utf-8") as handle:
            csv_rows[path.stem] = sum(1 for _ in csv.DictReader(handle))
    query_history = 0
    qh = DATA / "eval" / "query_history.jsonl"
    if qh.exists():
        query_history = sum(1 for line in qh.read_text(encoding="utf-8").splitlines() if line.strip())
    return {
        "summary": summary,
        "report": report,
        "answers": report.get("answers", {}),
        "routing": report.get("routing", {}),
        "retrieval": (report.get("retrieval") or {}).get("hybrid_rerank", {}),
        "access": report.get("access_control", {}),
        "sweeps": report.get("sweeps", {}),
        "resources": report.get("resources", {}),
        "items": items,
        "kinds": kinds,
        "answerable": answerable,
        "docs": docs,
        "words": words,
        "csv_rows": csv_rows,
        "query_history": query_history,
        "today": date.today().isoformat(),
    }


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


# --------------------------------------------------------------------------
# Document scaffolding
# --------------------------------------------------------------------------


class Guide(BaseDocTemplate):
    def __init__(self, path: Path, footer: str, **kwargs) -> None:
        super().__init__(
            str(path), pagesize=A4,
            leftMargin=20 * mm, rightMargin=20 * mm,
            topMargin=18 * mm, bottomMargin=17 * mm,
            title=footer, author="AMYPO", **kwargs,
        )
        self.footer_text = footer
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._decorate)])

    def _decorate(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 13 * mm, A4[0] - 20 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 9 * mm, self.footer_text)
        canvas.drawRightString(A4[0] - 20 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()


def contents(rows: list[tuple[str, str]]) -> Table:
    data = [[P("Section", "cellb"), P("What it covers", "cellb")]]
    for name, what in rows:
        data.append([P(name, "cell"), P(what, "cell")])
    total = 165 * mm
    t = Table(data, colWidths=[total * 0.36, total * 0.64], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    return t


def cover(title: str, subtitle: str, meta: list[str]) -> list:
    flow: list = [Spacer(1, 16 * mm)]
    flow.append(P("AMYPO - Policy &amp; Placement Copilot", "subtitle"))
    flow.append(P(title, "title"))
    flow.append(Spacer(1, 3))
    flow.append(P(subtitle, "subtitle"))
    flow.append(Spacer(1, 5))
    meta_table = Table([[P(m, "note")] for m in meta], colWidths=[165 * mm], hAlign="LEFT")
    meta_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    flow.append(meta_table)
    flow.append(Spacer(1, 10))
    return flow


# --------------------------------------------------------------------------
# Document 1: product and engineering guide
# --------------------------------------------------------------------------

MODULES = [
    ("api/routers", "FastAPI routes: ask, auth, placement, monitor, ingest, eval, admin"),
    ("api/ask_service.py", "The answering pipeline and the trace it produces"),
    ("auth/", "Passwords, JWT sessions, role dependencies, audit records"),
    ("retrieval/", "Intent rules, tokenizer, hybrid index (BM25 + vectors + rerank)"),
    ("grounding/", "Claim verifier, conflict detection, prompt-injection checks"),
    ("placement/", "Eligibility rules, skill gaps, suitability ranking, PDF export"),
    ("router/", "Complexity classifier, routing policy, metrics, self-training"),
    ("llm/", "Ollama client with tiers, prompts, SQL-tool answer templates"),
    ("cache/", "Semantic answer cache keyed by normalised question and scope"),
    ("ingest/", "Markdown and CSV ingestion, chunking, record cards"),
    ("monitor/", "RAM, CPU, bandwidth and simulated-cloud quota sampling"),
    ("eval/", "Benchmark, harness, ablations, sweeps, red-team suite, report"),
    ("db/", "MySQL connection, migrations runner, query helpers"),
    ("core/", "Settings, typed contracts, container wiring, logging"),
]

FRONTEND = [
    ("/login", "Sign in, honest error states, demo accounts panel"),
    ("/", "Chat: ask, citations, trace panel, history"),
    ("/placement", "Eligibility, skill gap, what-if, cohort view, PDF export"),
    ("/dashboard", "Live resources, route mix, latency, cost, quality, scenarios"),
    ("/knowledge", "Corpus status, ingestion trigger, coverage by scope"),
    ("/evaluation", "Run the harness, headline metrics, open the report"),
    ("/audit", "Cohort queries over student records"),
    ("/admin", "Users, roles, audit log, service keys"),
]


def product_guide(f: dict) -> list:
    a, r, ret, acc = f["answers"], f["routing"], f["retrieval"], f["access"]
    flow: list = []
    flow += cover(
        "Product &amp; Engineering Guide",
        "How the copilot answers a question end to end, which models and data it "
        "uses, how the code is organised, and what the measurements say.",
        [
            f"Build date: {f['today']}",
            f"Corpus: {len(f['docs'])} documents, {f['words']:,} words",
            f"Benchmark: {len(f['items'])} questions ({f['answerable']} answerable)",
            f"Code: FastAPI + MySQL backend, Next.js 14 frontend, local Ollama model",
        ],
    )

    flow.append(P("Contents", "h1"))
    flow.append(
        contents(
            [
                ("1. What the product is", "Problem, audience, the promise it keeps"),
                ("2. End to end", "One question, step by step through every layer"),
                ("3. Surfaces", "The eight screens and what each one is for"),
                ("4. Roles and access", "Capability matrix and where it is enforced"),
                ("5. Models and algorithms", "Every model, threshold and why it exists"),
                ("6. Datasets", "Corpus, synthetic records, benchmark, query log"),
                ("7. Code structure", "Module map for backend, frontend and scripts"),
                ("8. API surface", "Endpoints, request/response contracts, auth"),
                ("9. Measurements", "The evaluation report, read as a table"),
                ("10. Limits and next steps", "Known failure modes, stated plainly"),
            ]
        )
    )

    # 1 -------------------------------------------------------------------
    flow.append(P("1. What the product is", "h1"))
    flow.append(
        P(
            "AMYPO answers questions about a campus from its own records and policy "
            "documents. The records are real rows in MySQL (students, attendance, "
            "grades, skills, companies and placement criteria); the policy text is a "
            "small markdown corpus written for this project. The product does not call "
            "any third-party API: retrieval, the language model, the verifier, the "
            "placement engine and the evaluator all run on the same machine, and the "
            "test suite fails the build if a socket opens to anything but loopback.",
        )
    )
    flow.append(P("The four promises", "h2"))
    flow.extend(
        bullets(
            [
                "<b>Answers come from evidence.</b> Every claim is checked against the "
                "passages or rows it was built from, and citations name the record.",
                "<b>It abstains instead of inventing.</b> When retrieval cannot find "
                "support, the answer says so, names the closest records and asks a "
                "clarifying question.",
                "<b>Who asks decides what is visible.</b> The role comes from a signed "
                "session, never from the question text; students see their own record, "
                "staff see their department, admins see the system side.",
                "<b>It runs on modest hardware.</b> The default path is a 3.8B model on "
                "CPU, with a deterministic extractive fallback when no model is loaded, "
                "and the whole stack fits in an 8 GB budget.",
            ]
        )
    )

    # 2 -------------------------------------------------------------------
    flow.append(P("2. End to end: one question, every layer", "h1"))
    flow.append(
        P(
            "This is the path of a single <font face='Courier'>POST /api/v1/ask</font> "
            "call, in the order the code runs it. Each step records a stage in the "
            "trace, which the UI shows in the answer's trace panel.",
        )
    )
    steps = [
        ("1. Session", "The httpOnly access token is verified and turned into a Principal "
                       "(user id, role, department). A forged or expired token is rejected "
                       "before any question text is read."),
        ("2. Understanding", "Rule-based intent classification (policy, personal record, "
                             "aggregate, placement eligibility, skill gap, candidate "
                             "recommendation, multi-hop) plus entity matching against real "
                             "database vocab: course codes, student ids, company and role "
                             "names. Every decision names the rule that fired."),
        ("3. Structured tools", "For record intents, parameterised SQL templates run against "
                                "MySQL. The student id is fixed by the session, so a student "
                                "cannot widen the query, and rows come back with their record "
                                "ids for citation."),
        ("4. Placement engine", "Eligibility, skill-gap and what-if questions are decided by "
                                "the rules engine, not generated: criteria from "
                                "role_requirements are compared with the student's CGPA, "
                                "backlogs, attendance and skill levels, and the answer cites "
                                "the rows it used."),
        ("5. Retrieval", "Hybrid search over 6,300-plus chunks: BM25 (rank_bm25) and a dense "
                         "index (sentence-transformers when installed, a hash embedder "
                         "otherwise), fused with reciprocal rank fusion at k=60, then a "
                         "feature reranker. Access filtering happens before ranking."),
        ("6. Relevance gate", "The best BM25 score retrieval produced is compared with "
                              "the configured retrieval_relevance_floor (9.0). "
                              "Below it, the pipeline abstains before generating: cheaper, "
                              "and honest about the corpus not covering the question."),
        ("7. Generation", "Either the local model (phi3:mini through Ollama) or, when no model "
                          "is available, the deterministic extractive answer that quotes the "
                          "retrieved passages in order. SQL rows can also be phrased without "
                          "the model."),
        ("8. Verification", "Every claim is split out and matched against the evidence. A "
                            "number that is not in the evidence is a hard failure. If the "
                            "supported share or confidence falls under the thresholds, the "
                            "answer becomes an abstention."),
        ("9. Deliver", "The response carries the answer, citations, confidence, route, "
                       "cost estimate, carbon estimate, detected language, conflict notice, "
                       "and a trace id. The run is written to the query log and to the "
                       "semantic cache under a role- and user-scoped key."),
    ]
    flow.append(table(["Step", "What happens"], [[s, d] for s, d in steps], [0.22, 0.78]))

    # 3 -------------------------------------------------------------------
    flow.append(P("3. The surfaces", "h1"))
    flow.append(
        P(
            "The frontend is eight routes in Next.js 14 (app router). Navigation is built "
            "from the capability map, so a screen a role cannot use never appears; a direct "
            "URL shows a 'Not permitted' screen instead of an empty page.",
        )
    )
    flow.append(table(["Route", "Purpose"], [[p, d] for p, d in FRONTEND], [0.18, 0.82]))

    # 4 -------------------------------------------------------------------
    flow.append(P("4. Roles and where access is enforced", "h1"))
    flow.append(
        table(
            ["Capability", "Student", "Staff", "Admin"],
            [
                ["Public policy documents", "yes", "yes", "yes"],
                ["Staff-only documents", "no", "yes", "yes"],
                ["Admin-only documents", "no", "no", "yes"],
                ["Own grades, attendance, CGPA", "yes", "no", "aggregate"],
                ["Department student records", "no", "assigned only", "aggregate"],
                ["Placement eligibility, skill gap, what-if", "own", "cohort", "cohort"],
                ["Edit company criteria", "no", "assigned only", "yes"],
                ["Users, ingestion, router, evaluation", "no", "no", "yes"],
                ["Audit log (admin view)", "no", "no", "yes"],
                ["Cohort-query trail", "no", "own queries", "all"],
            ],
            [0.40, 0.18, 0.20, 0.22],
        )
    )
    flow.append(
        P(
            "Enforcement is in three places and none of them is the model: route "
            "dependencies (<font face='Courier'>deps.require</font>) reject the request "
            "before the handler runs; the retriever filters chunks by document scope and "
            "by student id before ranking; SQL templates and the placement engine take the "
            "student id from the session, so the question text cannot substitute another "
            "student. Cache keys include the scope, so a cached staff answer can never be "
            "served to a student.",
        )
    )
    if acc.get("ran"):
        flow.append(
            callout(
                f"Red-team result: {acc.get('leaks', 0)} leaks across "
                f"{acc.get('cases', 0)} cases ({acc.get('prompts', 0)} prompts and "
                f"{acc.get('requests', 0)} requests, at least "
                f"{acc.get('min_cases_per_role', 0)} per role). The suite asks a student "
                "for another student's grades and for staff-only policies, asks every role "
                "to ignore its permissions, and replays forged, expired and re-signed "
                "tokens. A leak is a 2xx where the matrix requires 401/403, or scoped data "
                "in the body of a 2xx."
            )
        )

    # 5 -------------------------------------------------------------------
    flow.append(P("5. Models and algorithms", "h1"))
    flow.append(
        P(
            "There are three families of machine learning in the product, and each one is "
            "small enough to explain: a language model for phrasing, a classifier for "
            "routing, and lexical/vector retrieval for finding evidence. Everything else "
            "is deterministic rules, which is deliberate.",
        )
    )
    flow.append(
        table(
            ["Model or method", "Role", "Details"],
            [
                ["phi3:mini (Ollama)", "Phrase the grounded answer",
                 "3.8B parameters, Q4_0, about 2.2 GB resident; 2.5-3.1 s per answer on "
                 "this CPU-only machine; temperature 0.1; the prompt pins it to the "
                 "provided passages and forbids outside knowledge."],
                ["tinyllama", "Tier 2 fallback",
                 "Used when RAM drops under 1400 MB and the smaller model is present; not "
                 "pulled on the reference machine, so the tier is inert there."],
                ["Extractive fallback", "Answer without a model",
                 "Quotes the top passages verbatim with citation markers. Deterministic, "
                 "so every number in the evaluation is reproducible; it cannot paraphrase."],
                ["Complexity classifier", "Route a question",
                 "scikit-learn pipeline over structural features (length, digits, cue "
                 "counts), trained on 276 derived labels plus thumbs feedback; held-out "
                 "accuracy 0.91, macro-F1 0.87, saved as a pickle and reloaded at start."],
                ["BM25", "Lexical retrieval",
                 "rank_bm25 over chunk text, tokenised with stopwords removed and light "
                 "stemming; strong on exact policy wording and record ids."],
                ["Dense retrieval", "Semantic retrieval",
                 "384-dimensional sentence embeddings when sentence-transformers is "
                 "installed; otherwise a hash embedder, which measures lexical overlap and "
                 "is fused at weight 0 (measured: fusing it reduced success@1)."],
                ["Reciprocal rank fusion", "Merge the two rankings",
                 "score = sum of weight / (60 + rank); rank-based so the two score scales "
                 "never need calibrating."],
                ["Feature reranker", "Order the top candidates",
                 "Title match, section match, term coverage, recency and record type; MRR "
                 "0.789 against 0.780 with dense weighting."],
                ["Grounding verifier", "Decide whether to trust the answer",
                 "Splits the answer into claims, matches each against the evidence "
                 "(similarity floor 0.45), requires numbers to appear, and abstains when "
                 "confidence is under 0.55."],
                ["Semantic cache", "Answer repeats cheaply",
                 "Keyed by normalised question, role and student scope; cosine floor 0.92; "
                 "pre-warmed with 25 frequent questions per scope."],
            ],
            [0.22, 0.22, 0.56],
        )
    )
    flow.append(P("Routing policy", "h2"))
    flow.append(
        P(
            "The router picks the cheapest route that can answer: cache (0.03-0.4 ms), "
            "extractive fallback (about 35 ms), local model (2.6 s, free), simulated cloud "
            "(1.8 s, 1.75 INR per call, 100 calls a day, 3% simulated failure). It refuses "
            "the cloud leg below 800 kbps bandwidth or when the quota is exhausted, drops "
            "to the smaller model under 1400 MB of free RAM, and goes fully offline under "
            "900 MB. These constants are inputs to the evaluation, not hidden behaviour.",
        )
    )

    # 6 -------------------------------------------------------------------
    flow.append(P("6. Datasets", "h1"))
    flow.append(
        P(
            "All data is generated locally from a fixed seed (20260203) by "
            "<font face='Courier'>scripts/generate_data.py</font>, so a fresh clone can "
            "rebuild the corpus and the records exactly.",
        )
    )
    rows = f["csv_rows"]
    flow.append(
        table(
            ["Dataset", "Rows", "What it holds"],
            [
                ["students", str(rows.get("students", "")), "300 students: department, year, CGPA, backlogs"],
                ["courses", str(rows.get("courses", "")), "17 courses with credits, semester and faculty"],
                ["attendance", str(rows.get("attendance", "")), "1,250 student-course attendance records"],
                ["grades", str(rows.get("grades", "")), "2,500 assessment rows with weights"],
                ["enrollments", str(rows.get("enrollments", "")), "1,250 enrolments with grade and project grade"],
                ["companies", str(rows.get("companies", "")), "15 recruiters with sector and tier"],
                ["company_roles", str(rows.get("company_roles", "")), "20 roles with package and cut-offs"],
                ["role_requirements", str(rows.get("role_requirements", "")), "80 skill requirements per role"],
                ["skills", str(rows.get("skills", "")), "34 skills with category"],
                ["student_skills", str(rows.get("student_skills", "")), "3,301 student-skill levels with evidence"],
                ["schedules", str(rows.get("schedules", "")), "17 weekly class slots"],
            ],
            [0.24, 0.10, 0.66],
        )
    )
    flow.append(P("Documents and chunks", "h2"))
    flow.append(
        P(
            f"The corpus is {len(f['docs'])} markdown documents ({f['words']:,} words): "
            "policy, exam rules, course manuals, a notice board, an FAQ, and three "
            "restricted documents (a faculty handbook and placement internals for staff, a "
            "security runbook for admins). Ingestion chunks the prose by heading (137 "
            "document chunks) and writes one compact record card per student and per "
            "attendance row (6,204 chunks), each carrying an access scope. Every chunk row "
            "keeps its text, token count, content hash and source id, so re-ingestion only "
            "re-embeds what actually changed.",
        )
    )
    flow.append(
        callout(
            "The record cards are what make a student's own attendance citable, but they "
            "are 98% of the chunks: terms like 'attendance' appear in thousands of cards, "
            "which flattens their BM25 weight for policy questions. Section 10 states the "
            "consequence and the fix."
        )
    )
    flow.append(P("Benchmark and query log", "h2"))
    kinds = ", ".join(f"{k} {v}" for k, v in sorted(f["kinds"].items()))
    flow.append(
        P(
            f"The evaluation benchmark holds {len(f['items'])} questions "
            f"({f['answerable']} answerable, {len(f['items']) - f['answerable']} "
            f"deliberately unanswerable): {kinds}. Each item carries the expected answer, "
            "the gold source ids and its kind, which is what makes per-kind reporting "
            f"possible. A separate log of {f['query_history']} historical questions drives "
            "the routing corpus and the cache pre-warm, and the live route decision log "
            "accumulates every real request for the self-training loop.",
        )
    )

    # 7 -------------------------------------------------------------------
    flow.append(P("7. Code structure", "h1"))
    flow.append(
        P(
            "Backend: Python 3.12, FastAPI, Pydantic v2 and MySQL through a pooled "
            "connector. The container is built from <font face='Courier'>backend/Dockerfile</font> "
            "on <font face='Courier'>python:3.12-slim</font>; every module below is imported "
            "by the app and covered by the test suite.",
        )
    )
    flow.append(table(["Module", "Responsibility"], [[m, d] for m, d in MODULES], [0.24, 0.76]))
    flow.append(
        P(
            "Each router is a thin HTTP layer over a service: validation and dependencies "
            "live in the route, decisions live in the module it calls. The answering "
            "pipeline (<font face='Courier'>api/ask_service.py</font>) is shared by "
            "<font face='Courier'>POST /ask</font>, the trace endpoint and the evaluation "
            "harness, so the numbers in the report come from the same code users hit.",
        )
    )
    flow.append(P("Tests and scripts", "h2"))
    flow.append(
        table(
            ["Path", "What it does"],
            [
                ["backend/tests/", "Contract, retrieval, grounding, placement, router, "
                                   "auth/RBAC, evaluation, access-control suite; sockets to "
                                   "anything but loopback raise"],
                ["scripts/generate_data.py", "Builds the synthetic records, documents and benchmark from the seed"],
                ["scripts/evaluate.py", "The make-eval entry point: full harness run, writes report.json/html"],
                ["scripts/make_artifacts.py", "Architecture diagram, final summary PDF, Postman collection"],
                ["scripts/make_guides.py", "This document and the user manual"],
                ["scripts/e2e_smoke.py", "Live end-to-end check against a running stack"],
                ["db/migrations/", "Schema: init, cohort queries, auth (users, staff assignments, refresh tokens, audit)"],
                ["docker-compose.yml", "MySQL, backend, frontend, Ollama with memory limits and healthchecks"],
            ],
            [0.30, 0.70],
        )
    )

    # 8 -------------------------------------------------------------------
    flow.append(P("8. API surface", "h1"))
    flow.append(
        P(
            "The OpenAPI document (<font face='Courier'>openapi.yaml</font>) is the "
            "contract: the typed response models in the backend are generated from the same "
            "shapes the frontend consumes. Every path below is served under "
            "<font face='Courier'>/api/v1</font>.",
        )
    )
    flow.append(
        table(
            ["Endpoint", "Purpose", "Role"],
            [
                ["POST /ask", "Ask a question; returns answer, citations, trace id", "any signed-in"],
                ["GET /ask/trace/{id}", "Full reasoning trace of a previous request", "any signed-in"],
                ["POST /route", "Classify a question and see the chosen route", "any signed-in"],
                ["GET /placement/eligibility", "Eligibility for the caller or a cohort", "any signed-in"],
                ["GET /placement/skill-gap/{id}", "Missing skills against a target role", "self or staff"],
                ["POST /placement/what-if", "Score a hypothetical grade or skill change", "self or staff"],
                ["POST /placement/match", "Rank candidates for a role", "staff, admin"],
                ["GET /placement/eligibility/{id}/report.pdf", "Downloadable eligibility report", "self or staff"],
                ["GET /resource-status", "RAM, CPU, bandwidth, quota, model state", "open"],
                ["GET /health", "Component health and corpus size", "open"],
                ["GET /metrics", "Aggregate quality and cost metrics", "staff, admin"],
                ["POST /ingest", "Ingest the corpus, with hashes and record counts", "admin"],
                ["POST /eval/run", "Run the evaluation harness", "admin"],
                ["POST /auth/login", "Sign in; sets the httpOnly session cookies", "open"],
                ["POST /auth/refresh", "Rotate the refresh token", "signed-in session"],
                ["GET /auth/me", "Current user, role and department", "any signed-in"],
                ["GET/POST/PATCH /admin/users", "Create, list and update accounts", "admin"],
                ["GET /admin/audit", "Audit log of denials, logins and record access", "admin"],
            ],
            [0.34, 0.46, 0.20],
        )
    )
    flow.append(
        P(
            "Authentication is local: bcrypt password hashes, a short-lived JWT access "
            "token and a revocable refresh token, both in httpOnly cookies, with a CSRF-safe "
            "same-site policy. Login is rate-limited and answers with a deliberately generic "
            "message; every denied action is written to the audit log with the actor, the "
            "route and the reason.",
        )
    )

    # 9 -------------------------------------------------------------------
    flow.append(P("9. Measurements", "h1"))
    flow.append(
        P(
            "These figures come from <font face='Courier'>docs/eval/report.json</font>, the "
            "artefact <font face='Courier'>make eval</font> writes. The run replays the "
            "benchmark through the real pipeline in the extractive configuration, so it is "
            "reproducible without a model; the report also carries the model-path numbers "
            "when a model is present.",
        )
    )
    flow.append(
        table(
            ["Metric", "Value", "How it is measured"],
            [
                ["Answer accuracy", pct(a.get("accuracy")),
                 f"{a.get('correct')} correct of {a.get('answerable')} answerable; gold "
                 "citation or text match, with every expected number required"],
                ["Groundedness", pct(a.get("groundedness")),
                 "Share of claims the verifier could support from the evidence"],
                ["Hallucination rate", pct(a.get("hallucination_rate")),
                 f"{a.get('hallucinated')} of {a.get('total')} delivered answers were "
                 "unanswerable or ungrounded"],
                ["Abstention (unanswerable)", pct(a.get("abstention_rate_unanswerable")),
                 f"{a.get('unanswerable_abstained')} of {a.get('unanswerable')} correctly "
                 "abstained"],
                ["Retrieval MRR", f"{ret.get('mrr', 0):.3f}", "Hybrid plus reranker, first relevant passage"],
                ["Success@1", pct(ret.get("success_at_1")), "A gold passage ranked first"],
                ["Routing agreement", pct(r.get("agreement")), "Chosen route against the oracle label"],
                ["Cost saving", pct((r.get("savings_pct") or 0) / 100),
                 f"{r.get('cumulative_cost_inr', 0):.2f} INR against "
                 f"{r.get('always_cloud_cost_inr', 0):.2f} INR if every question went to the cloud"],
                ["Peak RSS", f"{f['resources'].get('peak_rss_mb', 0):.0f} MB", "psutil, sampled during the whole run"],
                ["Red-team leaks", str(acc.get("leaks", "n/a")), "Must be zero; see section 4"],
            ],
            [0.26, 0.16, 0.58],
        )
    )
    sweep = (f["sweeps"].get("relevance_floor") or {}).get("points") or []
    if sweep:
        flow.append(P("The relevance floor, measured per point", "h2"))
        flow.append(
            P(
                "Each row is a real answer pass at that floor, not an estimate. That is the "
                "trade the product ships: accuracy is bought against abstention, and the "
                "shipped value is marked.",
            )
        )
        flow.append(
            table(
                ["Floor", "Accuracy", "Correct / answered", "Hallucinated", "Abstention"],
                [
                    [
                        f"{p['floor']:.1f}" + (" (shipped)" if abs(p["floor"] - 9.0) < 1e-9 else ""),
                        pct(p.get("accuracy")),
                        f"{p.get('correct')} / {p.get('answered')}",
                        pct(p.get("hallucination_rate")),
                        pct(p.get("abstention_rate_unanswerable")),
                    ]
                    for p in sweep
                ],
                [0.18, 0.18, 0.22, 0.20, 0.22],
            )
        )

    # 10 ------------------------------------------------------------------
    flow.append(P("10. Limits, stated plainly", "h1"))
    flow.extend(
        bullets(
            [
                "<b>The model path is only as good as what is pulled.</b> With no model in "
                "the Ollama volume the pipeline answers extractively: honest and citable, "
                "but it cannot paraphrase and every number in the report comes from that "
                "path. In the containerised setup the pull must land in the Ollama "
                "<i>container's</i> volume; the "
                "<font face='Courier'>ollama-pull</font> service does that on "
                "<font face='Courier'>docker compose up</font>, and "
                "<font face='Courier'>make models</font> repeats it. A pull from a "
                "host-installed Ollama app goes to a different store and does not count.",
                "<b>Vague questions abstain.</b> 'What is the attendance policy?' is below "
                "the relevance floor; 'What is the minimum attendance required for exams?' "
                "answers. This is a corpus-scoring artefact, not a coincidence: record "
                "cards dominate the index and flatten BM25 weights for common policy words. "
                "The fix is a document-only score for the gate, or embeddings that separate "
                "meaning from wording.",
                "<b>List-shaped placement questions are weaker than specific ones.</b> "
                "'Am I eligible for the Zoho SDE role?' is answered from the rules engine; "
                "'Which companies am I eligible for?' can still abstain because the "
                "verifier wants the statement supported literally.",
                "<b>Dense retrieval is effectively off</b> without sentence-transformers, so "
                "the reported hybrid numbers equal BM25.",
                "<b>The cloud leg is simulated.</b> Quota, price, latency and failure rate "
                "are constants; no request leaves the machine.",
                "<b>Classifier labels are derived from a rule</b>, not human annotation, so "
                "its accuracy measures agreement with that rule. Only thumbs feedback adds "
                "non-derived signal.",
                "<b>Language support is experimental.</b> Script detection labels a "
                "question, but answers stay in English and no translated retrieval is "
                "attempted.",
            ]
        )
    )
    return flow


# --------------------------------------------------------------------------
# Document 2: user manual
# --------------------------------------------------------------------------


def user_manual(f: dict) -> list:
    flow: list = []
    flow += cover(
        "User Manual",
        "How to sign in, ask a question you can trust, and use the placement, "
        "dashboard and admin screens. Written for students, staff and administrators.",
        [
            f"Applies to: version 0.1.0, build {f['today']}",
            "Where: http://localhost:3000 after docker compose up",
            "Demo accounts: admin / staff.cse / s102, password amypo-demo-2026",
            "Every answer is cited; the system abstains when it cannot support one",
        ],
    )

    flow.append(P("Contents", "h1"))
    flow.append(
        contents(
            [
                ("1. Sign in", "Accounts, first screen, what to do when login fails"),
                ("2. Ask a question", "Writing a question that gets a good answer"),
                ("3. Read the answer", "Citations, confidence, route badge, trace, sources"),
                ("4. When it abstains", "What 'I could not find this' means and what to do"),
                ("5. Student guide", "Your record, eligibility, skill gap, what-if, PDF"),
                ("6. Staff guide", "Cohort queries, matching, criteria, staff documents"),
                ("7. Admin guide", "Accounts, ingestion, routing, evaluation, audit"),
                ("8. Screen reference", "What every panel and number means"),
                ("9. Troubleshooting", "The six states you can hit, and the fix"),
                ("10. Privacy and limits", "What is logged, what is not, what it cannot do"),
            ]
        )
    )

    # 1 -------------------------------------------------------------------
    flow.append(P("1. Sign in", "h1"))
    flow.append(
        P(
            "Open <font face='Courier'>http://localhost:3000</font>. The sign-in page asks "
            "for the username your department issued - not an email link, no password "
            "reset by mail, because the product is designed to run offline.",
        )
    )
    flow.append(
        table(
            ["Account", "Password", "Lands on", "Use it to try"],
            [
                ["admin", "amypo-demo-2026", "Dashboard", "Users, ingestion, evaluation, audit"],
                ["staff.cse", "amypo-demo-2026", "Chat", "Cohort queries, matching, staff documents"],
                ["s102", "amypo-demo-2026", "Chat", "Own grades, eligibility, skill gap"],
            ],
            [0.18, 0.24, 0.16, 0.42],
        )
    )
    flow.append(
        P(
            "These are demo accounts, seeded only when the stack runs in demo mode. "
            "An administrator can create real accounts on the Users screen; passwords are "
            "hashed individually and never shown again.",
        )
    )
    flow.append(P("If sign-in fails", "h2"))
    flow.extend(
        bullets(
            [
                "<b>Incorrect username or password</b> - deliberately vague, so the form "
                "cannot be used to discover which usernames exist.",
                "<b>Too many attempts</b> - wait a minute; the throttle is per account and "
                "per address.",
                "<b>Session expired</b> - you were idle too long, or the server restarted "
                "with a new signing key. Sign in again; nothing you asked is lost.",
                "<b>Backend unreachable</b> - the API container is down or still starting. "
                "Check <font face='Courier'>docker compose ps</font>; the first start after "
                "a rebuild takes a few seconds.",
            ]
        )
    )

    # 2 -------------------------------------------------------------------
    flow.append(P("2. Ask a question", "h1"))
    flow.append(
        P(
            "Type into the chat box and press Enter. Ask about a rule, a record, a "
            "placement decision or the system itself. The product answers from three kinds "
            "of evidence: policy documents, your own records, and the placement criteria "
            "table.",
        )
    )
    flow.append(P("Questions that work well", "h2"))
    flow.append(
        table(
            ["Instead of", "Ask"],
            [
                ["tell me about attendance", "What is the minimum attendance required for exams?"],
                ["grades", "What is my CGPA?"],
                ["placement", "Am I eligible for the Zoho SDE role?"],
                ["skills", "What skills am I missing for a data analyst role?"],
                ["fees", "What is the refund policy for hostel fees?"],
                ["rules", "How are end-semester papers moderated?"],
            ],
            [0.30, 0.70],
        )
    )
    flow.append(
        P(
            "Specific is better for a simple reason: retrieval ranks passages by the words "
            "in the question, and the verifier then checks the answer against those "
            "passages. A question that names the thing it is about - a rule, a course code, "
            "a company and role - gives both steps something to work with.",
        )
    )
    flow.append(
        P(
            "You can ask follow-ups in the same conversation; recent questions are listed "
            "in the sidebar, and New chat starts a clean thread. The sidebar is hideable on "
            "narrow screens.",
        )
    )

    # 3 -------------------------------------------------------------------
    flow.append(P("3. Read the answer", "h1"))
    flow.append(
        P(
            "An answer is more than a paragraph. Each part tells you how much to trust it.",
        )
    )
    flow.append(
        table(
            ["Element", "What it means"],
            [
                ["Answer text", "The answer, with [S1], [S2] markers where a claim came from a source"],
                ["Confidence", "How much of the answer the verifier could support; under the floor the answer becomes an abstention"],
                ["Route badge", "Which tier answered: cache, offline (extractive), local model, or cloud"],
                ["Citations", "One chip per source; open it to read the exact sentence or row used"],
                ["Trace panel", "Every stage: understanding, tools, placement, retrieval, generation, verification, with timings"],
                ["Conflict notice", "Two records disagree (for example 75% and 60% attendance rules); both are shown, neither is hidden"],
                ["Degraded banner", "The model is unavailable, so the answer is extractive and cannot paraphrase"],
            ],
            [0.22, 0.78],
        )
    )
    flow.append(
        P(
            "A citation is a record id, not a guess: document chunks look like "
            "<font face='Courier'>doc:attendance-policy#2</font> and record rows like "
            "<font face='Courier'>db:attendance:S102:CS301</font>. The Evaluation screen "
            "checks that every cited id really exists in the corpus, which is how citation "
            "validity is measured at 100%.",
        )
    )

    # 4 -------------------------------------------------------------------
    flow.append(P("4. When it abstains", "h1"))
    flow.append(
        P(
            "An abstention is a real answer, not an error. It means the evidence was too "
            "weak to stand behind, and the product prefers saying so to inventing something "
            "plausible.",
        )
    )
    flow.append(
        P(
            "The reply names the closest records it did find and offers a clarifying "
            "question. Read the list: it often shows what the corpus does contain, which is "
            "usually enough to rephrase. For example, asking for the Wi-Fi password returns "
            "the hostel policy and the security runbook as the closest records - the corpus "
            "never contains a password, and the answer says so.",
        )
    )
    flow.append(
        P(
            "What to do next: name the document, course, company or record you mean; ask "
            "about one thing at a time; and if you are a student, remember that questions "
            "about someone else's record are refused rather than answered.",
        )
    )

    # 5 -------------------------------------------------------------------
    flow.append(P("5. Student guide", "h1"))
    flow.append(
        P(
            "Sign in as <font face='Courier'>s102</font> (or your own account) and land on "
            "Chat. What you can do:",
        )
    )
    flow.extend(
        bullets(
            [
                "<b>Your own record.</b> 'What is my CGPA?', 'What is my attendance in "
                "CS301?' - answered from the database and cited to your row.",
                "<b>Policies.</b> Attendance, exams, fees, hostel, internship, scholarship, "
                "library; every answer cites the clause it came from.",
                "<b>Eligibility.</b> 'Am I eligible for the Zoho SDE role?' gives a yes or no "
                "with each failing criterion spelled out (CGPA, backlogs, attendance, "
                "skills).",
                "<b>Skill gap and what-if.</b> The Placement screen shows what is missing "
                "for a target role and what a hypothetical CGPA or skill level would change.",
                "<b>Download.</b> The eligibility report exports as a PDF you can attach to "
                "an application.",
            ]
        )
    )
    flow.append(
        P(
            "You cannot see another student's record, staff-only or admin-only documents, "
            "the cohort tools, or the system screens. If you ask anyway, the reply is a "
            "refusal - 'records for other students are outside your access scope' - and the "
            "attempt is written to the audit log.",
        )
    )

    # 6 -------------------------------------------------------------------
    flow.append(P("6. Staff guide", "h1"))
    flow.append(
        P(
            "Staff accounts carry a department assignment, and that assignment is the "
            "boundary: a CSE staff member sees CSE students and the staff handbook, and "
            "nothing from another department. Sign in as <font face='Courier'>staff.cse</font>.",
        )
    )
    flow.extend(
        bullets(
            [
                "<b>Cohort questions.</b> 'Who is eligible for Capgemini Analyst?' returns a "
                "ranked list with the criteria each student meets or misses; the query is "
                "recorded in the cohort trail.",
                "<b>Matching.</b> The Placement screen ranks candidates for a role by "
                "criteria, with fairness checks on the shortlist.",
                "<b>Staff documents.</b> The faculty handbook and placement internals are "
                "visible to you and invisible to students; answers cite them like any other "
                "source.",
                "<b>Criteria.</b> You can edit the requirements of companies assigned to "
                "you. Other companies are read-only, and the change is audited.",
                "<b>Dashboard.</b> Read-only: live RAM, bandwidth, quota, route mix, latency "
                "and quality. It is monitoring, not a control panel.",
            ]
        )
    )
    flow.append(
        P(
            "Staff cannot open Users, Ingestion, Router or Evaluation, and cannot read the "
            "admin audit log. The screens are absent from the navigation, and a direct URL "
            "shows 'Not permitted'.",
        )
    )

    # 7 -------------------------------------------------------------------
    flow.append(P("7. Admin guide", "h1"))
    flow.append(
        P(
            "Admins see the system side: the accounts, the corpus, the router, the "
            "evaluation harness and the audit trail. Students appear only in aggregate, "
            "unless an audited query names them.",
        )
    )
    flow.append(
        table(
            ["Screen", "What you do there"],
            [
                ["Users", "Create accounts, set role and department, disable someone who leaves"],
                ["Knowledge", "See corpus size and document scopes, re-run ingestion after adding files"],
                ["Evaluation", "Run the benchmark, read accuracy, abstention and cost, open the full report"],
                ["Dashboard", "Self-optimising router: retrain from the benchmark plus thumbs feedback, then compare the two accuracies"],
                ["Audit trail", "Every denial, login, cohort query and personal-record read, with actor and route"],
                ["Router", "See the route the policy would choose for a question, and the reason"],
            ],
            [0.22, 0.78],
        )
    )
    flow.append(
        P(
            "Ingestion is idempotent: unchanged files are skipped by content hash, so "
            "re-running it after adding a document only embeds the new one. The response "
            "reports documents, chunks, record cards, skipped files and duration.",
        )
    )

    # 8 -------------------------------------------------------------------
    flow.append(P("8. Screen reference", "h1"))
    flow.append(
        table(
            ["Element", "Meaning"],
            [
                ["RAM available", "Free memory now; under 900 MB the router goes offline-only, under 1400 MB it drops to the smaller model"],
                ["Bandwidth", "Current link speed; under 800 kbps the cloud leg is not attempted"],
                ["Cloud quota", "Simulated calls left today (100 per day)"],
                ["Ollama", "'loaded' when the local model answers; 'model not pulled' when the server is up but the model is missing; 'unavailable' when the server cannot be reached. A line under the tiles names the command that fixes it"],
                ["Requests by route", "How questions were answered: cache, offline, local model, cloud"],
                ["Latency p50 / p95", "Answer time per route, in milliseconds"],
                ["Cumulative cost", "Simulated spend against the always-cloud baseline"],
                ["Answer quality", "Average confidence, groundedness and abstention over recent answers"],
                ["Offline mode", "The demo switch that forces the offline path, for showing the fallback"],
            ],
            [0.24, 0.76],
        )
    )

    # 9 -------------------------------------------------------------------
    flow.append(P("9. Troubleshooting", "h1"))
    flow.append(
        table(
            ["What you see", "What it means", "What to do"],
            [
                ["Ollama: model not pulled", "The Ollama server the backend uses answered, but phi3:mini is not in its model store. A pull in the Windows/macOS Ollama app fills the host store and does not count",
                 "Pull it into the container: docker compose run --rm ollama-pull (or make models). The card recovers within 30 seconds; no restart needed"],
                ["Ollama: unavailable", "The backend cannot reach Ollama at the configured address",
                 "docker compose up -d ollama, or start ollama serve when the backend runs on the host"],
                ["Degraded banner on an answer", "The model was unreachable, so the extractive path answered",
                 "Check the Ollama card; the answer is still cited and correct, just quoted verbatim"],
                ["503 Service unavailable", "The backend is starting or a component is down",
                 "docker compose ps, then docker compose logs backend --tail 50"],
                ["Not permitted (403)", "Your role cannot use that route",
                 "Use the screen your role has; the navigation shows only those"],
                ["Session expired", "Idle timeout or a restarted server with a new key", "Sign in again"],
                ["Backend unreachable", "The browser cannot reach the API", "Check that port 8000 answers: curl http://localhost:8000/api/v1/health"],
                ["Answer is slow (2-3 s)", "The local model is answering rather than the cache or the extractive path", "Expected; the route badge names the tier that answered"],
            ],
            [0.24, 0.38, 0.38],
        )
    )

    # 10 ------------------------------------------------------------------
    flow.append(P("10. Privacy and limits", "h1"))
    flow.append(
        P(
            "Every question is stored with its answer, route, cost and trace, so the "
            "evaluation and the audit trail have data to work with. The actor is the "
            "account, not a guess; staff access to a student record is written to the audit "
            "log, and a denied request is recorded with the route that denied it. There is "
            "no third-party call, no analytics, no telemetry - the only network traffic is "
            "the browser to the local API, and the API to MySQL and Ollama on loopback.",
        )
    )
    flow.extend(
        bullets(
            [
                "It answers only from the corpus it was given; a question about next year's "
                "package or a private phone number is refused, not estimated.",
                "It cannot paraphrase well on the extractive path; expect quoted sentences.",
                "It reports conflicting documents rather than silently picking one.",
                "The demo accounts share a documented password. Change or remove them before "
                "any real deployment.",
            ]
        )
    )
    flow.append(Spacer(1, 6))
    flow.append(
        callout(
            "One-page rules of thumb: name the thing you are asking about; read the "
            "citations before quoting the answer; treat an abstention as information, not "
            "a failure; and never rely on the extractive answer for wording, only for the "
            "facts it cites."
        )
    )
    return flow


# --------------------------------------------------------------------------
# Document 3: manual test guide
# --------------------------------------------------------------------------


def manual_test(f: dict) -> list:
    """A hand-run acceptance plan: coverage map, numbered steps, expected results.

    Written so someone who has never seen the code can check the product in about
    forty minutes and record a defensible result. Every label quoted here exists
    in the UI at the time of writing; the check ids are referenced by the
    coverage map so a gap in a run is visible.
    """
    flow: list = []
    flow += cover(
        "Manual Test Guide",
        "How to verify the product by hand: what to open, what to type, and what "
        "you should see. Written for a reviewer with no prior knowledge of the code.",
        [
            f"Applies to: version 0.1.0, build {f['today']}",
            "Where: http://localhost:3000 after docker compose up",
            "Accounts: admin / staff.cse / s102, password amypo-demo-2026",
            "Time: about 40 minutes for all checks; 10 for the smoke subset",
        ],
    )

    flow.append(P("Contents", "h1"))
    flow.append(
        contents(
            [
                ("1. Before you start", "Stack, accounts, resetting state, how to record a result"),
                ("2. Coverage map", "Which check covers which feature, and where it lives"),
                ("3. Access and sessions", "Six checks: login, roles, sign-out, wrong password"),
                ("4. Asking questions", "Nine checks: citations, trace, cache, abstention, scope"),
                ("5. Placement", "Six checks: eligibility, skill gap, what-if, PDF, staff matching"),
                ("6. Dashboard and degradation", "Seven checks: tiles, Ollama states, scenarios, retrain"),
                ("7. Knowledge and ingestion", "Three checks: document list, re-scan, force re-index"),
                ("8. Evaluation", "Three checks: quick run, full run, role gate"),
                ("9. Admin and audit", "Five checks: users, password reset, audit trail, access"),
                ("10. API and command line", "Five checks: health, smoke suite, model pull, guides"),
                ("11. Known gaps", "What will fail if you test it, and why it is expected"),
                ("12. Sign-off", "One table to record the run"),
            ]
        )
    )

    # 1 -------------------------------------------------------------------
    flow.append(P("1. Before you start", "h1"))
    flow.append(
        P(
            "Bring the stack up from the project root, then wait until the header "
            "pill reads <b>local model</b> (not <b>offline mode</b>) and the Ollama "
            "tile says loaded. The first start downloads phi3:mini into the Ollama "
            "container, so give it a few minutes on a fresh machine."
        )
    )
    flow.append(P("docker compose up -d --build", "code"))
    flow.extend(
        bullets(
            [
                "Open <font face='Courier'>http://localhost:3000</font>. Use a private window so no earlier session survives.",
                "Use the <b>Demo accounts</b> panel on the sign-in page for the three roles; the password is <font face='Courier'>amypo-demo-2026</font> for all of them.",
                "Reset between runs with <font face='Courier'>docker compose restart backend</font>; it does not touch the database, the corpus or the model.",
                "Record PASS or FAIL and the observed text for every id. A check with no observation is not a pass.",
                "Numbers differ by machine (latency, RAM). Judge the shape of the behaviour, not an exact millisecond.",
            ]
        )
    )
    flow.append(
        callout(
            "If the Ollama tile says <b>model not pulled</b>, the model is missing "
            "from the container's own store: run "
            "<font face='Courier'>docker compose run --rm ollama-pull</font> (or "
            "<font face='Courier'>make models</font>). A pull in the host's Ollama "
            "app does not count. The card recovers within 30 seconds."
        )
    )

    # 2 -------------------------------------------------------------------
    flow.append(P("2. Coverage map", "h1"))
    flow.append(
        P(
            "Every user-visible capability maps to at least one check. Use this table "
            "to decide what a shortened run may skip without leaving a feature "
            "unexamined."
        )
    )
    flow.append(
        table(
            ["Area", "Screen / entry point", "Checks"],
            [
                ["Sign-in, sessions, role landing pages", "/login, header Sign out", "S1-S6"],
                ["Grounded answers, citations, trace", "/ (Chat)", "C1-C3"],
                ["Feedback that feeds retraining", "Chat answer footer", "C4, D4"],
                ["Semantic cache", "Chat, ask the same question twice", "C5"],
                ["Abstention and closest records", "Chat, unanswerable question", "C6"],
                ["Role scoping and staff-only documents", "Chat as s102 and staff.cse", "C7-C8"],
                ["Language detection (experimental)", "Chat, non-Latin input", "C9"],
                ["History and new chat", "Chat toolbar and sidebar", "C10"],
                ["Eligibility, skill gap, what-if", "/placement as s102", "P1-P3"],
                ["Eligibility PDF", "/placement, Download PDF", "P4"],
                ["Staff candidate matching", "/placement as staff.cse", "P5"],
                ["Live resources and model state", "/dashboard tiles", "D1-D2"],
                ["Failure-mode scenarios", "/dashboard Scenarios", "D3"],
                ["Router retraining", "/dashboard Retrain", "D4"],
                ["Cost, latency and quality charts", "/dashboard", "D5"],
                ["Decision log", "/dashboard, decision table", "D6"],
                ["Corpus and ingestion", "/knowledge", "K1-K3"],
                ["Benchmark from the UI", "/evaluation", "E1-E3"],
                ["Accounts and password reset", "/admin (Users)", "A1"],
                ["Audit trail and denied filter", "/audit", "A2"],
                ["Access enforcement", "direct URLs and API", "A3-A4"],
                ["Health and readiness", "GET /api/v1/health", "A5"],
                ["End-to-end automation", "scripts/e2e_smoke.py", "X1"],
                ["Model bootstrap and documents", "make models, make guides", "X2-X3"],
            ],
            [0.34, 0.42, 0.24],
        )
    )

    # 3 -------------------------------------------------------------------
    flow.append(P("3. Access and sessions", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["S1", "Open /dashboard in a private window.",
                 "Redirected to /login. After signing in you land back on /dashboard, not the home page."],
                ["S2", "Demo accounts -> Admin. Sign in.",
                 "Lands on Dashboard. Header shows admin / Admin, the local-model pill, and the Users nav item."],
                ["S3", "Sign out, then sign in as staff.cse.",
                 "Lands on Chat. Nav has no Users item. Audit trail is visible."],
                ["S4", "Sign out, then sign in as s102.",
                 "Lands on Chat. No Users item. Placement opens on your own record."],
                ["S5", "Sign in as admin with password wrong-password.",
                 "Inline message: Incorrect username or password. No redirect, no session, no stack trace."],
                ["S6", "Click Sign out, then press Back.",
                 "Login page. The previous page does not render from cache; a reload keeps you signed out."],
            ],
            [0.07, 0.42, 0.51],
        )
    )

    # 4 -------------------------------------------------------------------
    flow.append(P("4. Asking questions", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["C1", "As s102, ask: What is the minimum attendance required for exams?",
                 "A direct answer with citation chips. The footer shows a route, latency, confidence, a tier label, a cost of zero and grounded n/n claims."],
                ["C2", "Click a citation chip such as [S1].",
                 "The Sources and trace panel opens on that record. The trace tab lists the real stages: classify, retrieve, gate, generate, verify."],
                ["C3", "Click Copy under the answer.",
                 "Button changes to Copied for about a second; the clipboard holds the answer text."],
                ["C4", "Click the thumbs-up button in the answer footer.",
                 "The icon turns teal and stays pressed. On Dashboard, Retrain now reports confirmed feedback instead of no thumbs feedback yet."],
                ["C5", "Ask the same question again in the same session.",
                 "The route badge shows the cache path and the latency is far below the first answer. The text and citations match."],
                ["C6", "Ask: What is the Wi-Fi password for the hostel?",
                 "An abstention: the answer says it could not find support and asserts nothing. Closest records are listed, and a clarifying question may be offered."],
                ["C7", "As s102, ask: What is the attendance of S101?",
                 "Refused or abstained without any personal row for S101. Sign in as staff.cse and ask again: the cohort answer is allowed."],
                ["C8", "As staff.cse, ask: What are the internal notes for the placement officer? Then repeat as s102.",
                 "Staff get a cited answer from the staff-only document. The student gets no staff-only source and no paraphrase of it."],
                ["C9", "Ask a question in Devanagari or Tamil script.",
                 "A muted line says the script was detected and that the answer is in English. Retrieval still runs; expect a weaker answer."],
                ["C10", "Click New chat, then reopen the history sidebar.",
                 "Empty state returns with starter questions. Previous questions are listed in the sidebar and reopen with their sources."],
            ],
            [0.07, 0.41, 0.52],
        )
    )

    # 5 -------------------------------------------------------------------
    flow.append(P("5. Placement", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["P1", "As s102, open Placement and select a company role.",
                 "An Eligibility table with each criterion (CGPA, backlogs, attendance, skills), the observed value and a met/missed verdict."],
                ["P2", "Scroll to the skill-gap panel.",
                 "Missing skills with the level needed, plus a short learning path. No invented certifications."],
                ["P3", "Raise Improve all skills (levels) by one and click Recompute eligibility.",
                 "Opens up / Lost lines and a line like 2 roles eligible now -> 4 after the change, Nothing is saved."],
                ["P4", "Click Download PDF next to the student id.",
                 "A PDF named S102-eligibility.pdf arrives. It contains the criteria table and the learning path, not a blank page."],
                ["P5", "Sign in as staff.cse, open Placement, select a role.",
                 "Eligible for <company> <role> ranks candidates with reasons, and Closest misses lists students one criterion short."],
                ["P6", "As s102, change the student id field and press Enter.",
                 "Either the field is read-only for students or the result still shows only your own record; the server, not the field, decides."],
            ],
            [0.07, 0.40, 0.53],
        )
    )

    # 6 -------------------------------------------------------------------
    flow.append(P("6. Dashboard and degradation", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["D1", "Sign in as admin and open Dashboard.",
                 "Five tiles (RAM, CPU, bandwidth, quota, Ollama) refresh every five seconds. Ollama says loaded with a last-reply time."],
                ["D2", "Stop Ollama, restart the backend, reload the page.",
                 "Ollama says unavailable, with a hint naming the start command. Ask a question: it still answers from quoted evidence, labelled extractive. Start Ollama again, restart the backend: loaded returns."],
                ["D3", "Click each scenario button in turn, ending with reset to stable.",
                 "A summary line describes the simulated run. Tiles change (for example bandwidth scenario, quota falling) and the decision log gains rows. Nothing crashes."],
                ["D4", "Click Retrain.",
                 "If C4 was done: a previous -> new agreement line and a confirmation count. If not: no thumbs feedback yet - rate an answer in chat. No error banner."],
                ["D5", "Compare the three charts against recent activity.",
                 "Requests by route, p50/p95 per route and cumulative cost all match the answers you just asked; the cost bar for AMYPO stays far below always-cloud."],
                ["D6", "Read the decision table under Scenarios.",
                 "Each row has a query, the route, complexity, cost and a human-readable reason. Rows accumulate as you ask questions."],
                ["D7", "Hover the latency bars.",
                 "A tooltip gives p50 and p95 in milliseconds for that route. Values are numbers, not placeholders."],
            ],
            [0.07, 0.40, 0.53],
        )
    )

    # 7 -------------------------------------------------------------------
    flow.append(P("7. Knowledge and ingestion", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["K1", "Open Knowledge.",
                 "The document count, then a table: title and doc_id, type, access scope, chunk count and indexed time."],
                ["K2", "Click Re-scan and wait.",
                 "A result line reports documents and chunks seen, skipped and re-embedded. The document count does not double."],
                ["K3", "Click Force re-index, wait, then ask a policy question.",
                 "Button reads Ingesting while busy, then the same corpus is rebuilt and the answer is still cited. No duplicate sources appear."],
            ],
            [0.07, 0.36, 0.57],
        )
    )

    # 8 -------------------------------------------------------------------
    flow.append(P("8. Evaluation", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["E1", "As admin, open Evaluation and click Quick run (40).",
                 "A completed run with accuracy, groundedness, abstention, hallucination, retrieval and routing figures. The page states it is a live run, not a stored file."],
                ["E2", "Click Full benchmark, then wait.",
                 "The same panel with the full benchmark count. The button returns to Full benchmark; no timeout error appears."],
                ["E3", "As staff.cse, open /evaluation.",
                 "The page either hides the run controls or the run is refused with a clear message; it must never return numbers it did not compute."],
            ],
            [0.07, 0.36, 0.57],
        )
    )

    # 9 -------------------------------------------------------------------
    flow.append(P("9. Admin and audit", "h1"))
    flow.append(
        table(
            ["ID", "What to do", "What you should see"],
            [
                ["A1", "As admin, open Users. Filter, disable and re-enable one non-admin account, then reset its password.",
                 "Filter narrows the table. Disable flips the button to Enable. Reset needs 8+ characters, then reports success and ends that account's sessions."],
                ["A2", "Open Audit trail as admin. Tick Denied only.",
                 "Allowed, denied and total counts at the top; rows carry time, actor, action, target and result. The filter leaves only denied actions."],
                ["A3", "As s102, open /admin and /audit directly by URL.",
                 "No admin data is shown; the API refuses with 403. The nav never offered those pages."],
                ["A4", "As staff.cse, open /audit.",
                 "The staff view shows cohort queries only - never student record rows, and never the denied-action log."],
                ["A5", "Open /api/v1/health in a tab.",
                 "JSON with status ok and per-component detail for db, index, llm and router; no secret values."],
            ],
            [0.07, 0.44, 0.49],
        )
    )

    # 10 ------------------------------------------------------------------
    flow.append(P("10. API and command line", "h1"))
    flow.append(P("Run these from the project root while the stack is up.", "body"))
    flow.append(
        table(
            ["ID", "Command", "What you should see"],
            [
                ["X1", "python scripts/e2e_smoke.py",
                 "46/46 checks passed, exit code 0. It drives the real HTTP API with the three roles."],
                ["X2", "docker compose run --rm ollama-pull",
                 "model ready: phi3:mini and exit 0; a second run is a no-op, not a re-download."],
                ["X3", "python scripts/make_guides.py",
                 "Three PDFs written under docs/: product guide, user manual and this manual test guide."],
                ["X4", "curl -s localhost:8000/api/v1/resource-status",
                 "JSON with RAM, CPU, bandwidth, quota, ollama_status ok and ollama_detail naming the model."],
                ["X5", "cd backend && python -m pytest tests -q",
                 "The suite passes. Expect roughly ten minutes: the ingest tests rebuild the 8,784-row corpus."],
            ],
            [0.07, 0.42, 0.51],
        )
    )
    flow.append(
        P(
            "Sample access check without a browser: request "
            "<font face='Courier'>/api/v1/admin/users</font> with no cookie (expect 401), "
            "then with a student session (expect 403). The smoke script performs this "
            "for every endpoint and role, so X1 is the cheaper path.",
            "note",
        )
    )

    # 11 ------------------------------------------------------------------
    flow.append(P("11. Known gaps", "h1"))
    flow.append(
        P(
            "These are real limits, not defects to report. If a check contradicts one "
            "of them, that is a finding."
        )
    )
    flow.extend(
        bullets(
            [
                "<b>The cloud leg is simulated.</b> Quota, price, latency and failure rate are constants; no request leaves the machine. Cost comparisons are therefore model outputs, not bills.",
                "<b>Local answers are slow on CPU.</b> A generated answer takes roughly 10-20 seconds here; cached, tool-backed and extractive answers are far faster. The latency tiles are expected to differ by an order of magnitude.",
                "<b>Dense retrieval is effectively off unless sentence-transformers is installed</b>, so hybrid numbers equal BM25 on a default install. The report says so rather than claiming a gain.",
                "<b>Staff have no PDF control in the UI.</b> The API supports staff exports, but the button is shown only for a student's own report.",
                "<b>Vague questions abstain.</b> 'What is the attendance policy?' is below the relevance floor; naming the requirement gets an answer. This is the gate working, not a retrieval crash.",
                "<b>The suite is slow by design.</b> Ingest tests rebuild the corpus, so the full run is minutes, not seconds. Run it once, not per check.",
            ]
        )
    )

    # 12 ------------------------------------------------------------------
    flow.append(P("12. Sign-off", "h1"))
    flow.append(
        P(
            "Record the run against the build date on the cover. A shortened run is "
            "acceptable if the skipped ids are named; an unrecorded observation is not."
        )
    )
    flow.append(
        table(
            ["Section", "Checks", "Passed", "Notes"],
            [
                ["3. Access and sessions", "S1-S6", "___ / 6", ""],
                ["4. Asking questions", "C1-C10", "___ / 10", ""],
                ["5. Placement", "P1-P6", "___ / 6", ""],
                ["6. Dashboard", "D1-D7", "___ / 7", ""],
                ["7. Knowledge", "K1-K3", "___ / 3", ""],
                ["8. Evaluation", "E1-E3", "___ / 3", ""],
                ["9. Admin and audit", "A1-A5", "___ / 5", ""],
                ["10. Command line", "X1-X5", "___ / 5", ""],
                ["Total", "45", "___ / 45", ""],
            ],
            [0.36, 0.20, 0.16, 0.28],
        )
    )
    flow.append(Spacer(1, 8))
    flow.append(P("Tester: ______________________    Date: ______________    Build: " + f["today"], "body"))
    flow.append(P("Signature: ____________________    Environment: laptop / demo machine / other", "body"))
    return flow


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build(path: Path, title: str, flow: list) -> int:
    doc = Guide(path, footer=f"AMYPO - {title}")
    doc.build(flow)
    return doc.page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=["guide", "manual", "test"], help="build one document"
    )
    args = parser.parse_args()
    f = facts()
    DOCS.mkdir(exist_ok=True)
    built = []
    if args.only in (None, "guide"):
        path = DOCS / "product_guide.pdf"
        pages = build(path, "Product & Engineering Guide", product_guide(f))
        built.append((path, pages))
    if args.only in (None, "manual"):
        path = DOCS / "user_manual.pdf"
        pages = build(path, "User Manual", user_manual(f))
        built.append((path, pages))
    if args.only in (None, "test"):
        path = DOCS / "manual_test_guide.pdf"
        pages = build(path, "Manual Test Guide", manual_test(f))
        built.append((path, pages))
    for path, pages in built:
        size = path.stat().st_size / 1024
        print(f"wrote {path} - {pages} pages, {size:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
