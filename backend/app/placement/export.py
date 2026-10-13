"""Downloadable PDF eligibility report (Phase 8, item 11).

Produces a self-contained PDF for one student: which roles they qualify for,
which they miss and why, and the top of their learning path. It is generated
server-side so the artefact is identical regardless of the browser, and it is
plain text throughout — no external assets, so it opens offline like the
evaluation report does.

``reportlab`` is an explicit dependency in ``requirements.txt``. It was present
in this environment only as an undeclared stray, which would have silently
broken ``pip install -r requirements.txt`` on a fresh clone; declaring it is
what makes the DoD ("fresh clone -> one command -> working demo") true.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """Escape for reportlab's PDF text operators."""
    return (text or "").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_eligibility_pdf(
    student_id: str,
    student_name: str,
    results: list[Any],
    learning_path: list[Any] | None = None,
) -> bytes:
    """Render an eligibility report to PDF bytes.

    ``results`` are ``EligibilityResult`` models (or anything with the same
    attributes). Returns raw PDF bytes; callers set the response media type.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError(
            "reportlab is required for PDF export; "
            "install backend/requirements.txt"
        ) from exc

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Eligibility report — {student_id}",
        author="AMYPO",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=4
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#666666"), spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=9, leading=12,
    )
    heading_style = ParagraphStyle(
        "Sub", parent=styles["Heading2"], fontSize=11, spaceBefore=12, spaceAfter=6,
    )

    story = [
        Paragraph("Eligibility report", title_style),
        Paragraph(
            f"{_esc(student_name)} ({_esc(student_id)}) &middot; "
            f"generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            meta_style,
        ),
        Paragraph(
            "Deterministic evaluation against every on-record role. "
            "Eligibility is decided from the criteria, never generated.",
            body_style,
        ),
        Spacer(1, 8),
    ]

    if not results:
        story.append(
            Paragraph(
                "No roles matched this student, so there is nothing to report.",
                body_style,
            )
        )
    else:
        story.append(Paragraph("Roles", heading_style))
        rows: list[list[str]] = [["Company", "Role", "Verdict", "Missing"]]
        for r in results:
            eligible = bool(getattr(r, "eligible", False))
            failing = list(getattr(r, "failing", []) or [])
            rows.append(
                [
                    _esc(str(getattr(r, "company", "") or "")),
                    _esc(str(getattr(r, "role", "") or "")),
                    "ELIGIBLE" if eligible else "not eligible",
                    _esc(", ".join(failing)) if failing else "-",
                ]
            )

        table = Table(rows, colWidths=[38 * mm, 46 * mm, 26 * mm, 54 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    # Green/red verdict column so the eye finds it immediately.
                    (
                        "TEXTCOLOR",
                        (2, 1),
                        (2, -1),
                        colors.HexColor("#166534"),
                    ),
                ]
            )
        )
        story.append(table)

        eligible_count = sum(1 for r in results if getattr(r, "eligible", False))
        story.append(Spacer(1, 8))
        story.append(
            Paragraph(
                f"{eligible_count} of {len(results)} roles eligible.",
                body_style,
            )
        )

    if learning_path:
        story.append(Paragraph("Suggested next steps", heading_style))
        for i, step in enumerate(learning_path, start=1):
            title = getattr(step, "title", "")
            weeks = getattr(step, "effort_weeks", None)
            suffix = f" (~{weeks} weeks)" if weeks else ""
            story.append(
                Paragraph(f"{i}. {_esc(str(title))}{_esc(suffix)}", body_style)
            )

    story.append(Spacer(1, 14))
    story.append(
        Paragraph(
            "Generated locally by AMYPO. No data left this machine.",
            meta_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()


def pdf_filename(student_id: str) -> str:
    """A filesystem-safe download name."""
    safe = "".join(c for c in student_id if c.isalnum() or c in "-_") or "report"
    return f"eligibility-{safe}.pdf"
