"""PDF export of an agent answer -- a polished executive report, not a
chat-log dump (Phase 4 continuation section 31-32).

Charts are rendered here as their underlying data table plus chart-type
label, not as a rasterized image: the actual charts are interactive SVG
rendered client-side (app/components/charts.tsx), and reproducing that
server-side would need a new rendering dependency (e.g. a headless browser
or an SVG rasterizer) this phase's "don't introduce unnecessary
infrastructure" instruction rules out. Every number in this PDF still
traces to the same deterministic tool results the UI shows.
"""

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.agent.schemas import AgentAnswer, Finding

LABEL_COLORS = {
    "VERIFIED_FROM_DATA": colors.HexColor("#1baf7a"),
    "CALCULATED": colors.HexColor("#2a78d6"),
    "DERIVED": colors.HexColor("#4a3aa7"),
    "DOCUMENT_EVIDENCE": colors.HexColor("#e87ba4"),
    "VERIFIED_FROM_WEB": colors.HexColor("#0e9bb0"),
    "AI_INTERPRETATION": colors.HexColor("#eda100"),
    "INSUFFICIENT_DATA": colors.HexColor("#898781"),
}

MAX_RECOMMENDATIONS = 5


def _finding_paragraph(finding: Finding, styles) -> Paragraph:
    color = LABEL_COLORS.get(finding.label.value, colors.grey)
    label_html = f'<font color="{color.hexval()}"><b>[{finding.label.value}]</b></font>'
    return Paragraph(f"{label_html} {finding.text}", styles["BodyText"])


def _chart_table(data: list[dict], styles, max_rows: int = 12) -> Table:
    if not data:
        return None
    columns = list(data[0].keys())
    rows = [columns] + [[str(row.get(c, "")) for c in columns] for row in data[:max_rows]]
    table = Table(rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e0d9")),
            ]
        )
    )
    return table


def render_answer_pdf(answer: AgentAnswer, *, dataset_name: str | None = None, dataset_version: int | None = None) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DWTitle", parent=styles["Title"], fontSize=22)
    subtitle_style = ParagraphStyle("DWSubtitle", parent=styles["Normal"], fontSize=12, textColor=colors.HexColor("#6b6a63"))
    heading_style = ParagraphStyle("DWHeading", parent=styles["Heading2"], spaceBefore=14)
    small_style = ParagraphStyle("DWSmall", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#6b6a63"))

    generated_at = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    # -- Cover page --
    story: list = [
        Spacer(1, 1.5 * inch),
        Paragraph("DataWise AI", title_style),
        Spacer(1, 6),
        Paragraph("Executive Analysis Report", subtitle_style),
        Spacer(1, 40),
        Paragraph(answer.question, ParagraphStyle("DWCoverQ", parent=styles["Heading2"], fontSize=14)),
    ]
    if dataset_name:
        version_str = f" (version {dataset_version})" if dataset_version else ""
        story.append(Paragraph(f"Dataset: {dataset_name}{version_str}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {generated_at}", small_style))
    story.append(PageBreak())

    if answer.error:
        story.append(Paragraph(f"<b>Error:</b> {answer.error}", styles["BodyText"]))
        doc.build(story)
        return buffer.getvalue()

    if answer.executive_summary:
        story.append(Paragraph("Executive Summary", heading_style))
        story.append(Paragraph(answer.executive_summary, styles["BodyText"]))

    # -- KPI overview: numeric CALCULATED/VERIFIED_FROM_DATA findings, shown
    # up front the way an executive skim would want them --
    kpi_findings = [f for f in answer.key_findings if f.label.value in ("CALCULATED", "VERIFIED_FROM_DATA") and any(ch.isdigit() for ch in f.text)]
    if kpi_findings:
        story.append(Paragraph("KPI Overview", heading_style))
        for f in kpi_findings[:6]:
            story.append(_finding_paragraph(f, styles))
            story.append(Spacer(1, 3))

    for title, findings in (
        ("Key Findings", answer.key_findings),
        ("Risks", answer.risks),
    ):
        if not findings:
            continue
        story.append(Paragraph(title, heading_style))
        for f in findings:
            story.append(_finding_paragraph(f, styles))
            story.append(Spacer(1, 4))

    # -- Visual analysis: the underlying data for each chart the answer
    # produced, labeled with its chart type (see module docstring for why
    # this is a table, not a rendered image) --
    if answer.charts:
        story.append(Paragraph("Visual Analysis", heading_style))
        for chart in answer.charts:
            chart_type = str(chart.get("chart_type", "chart")).replace("_", " ").title()
            story.append(Paragraph(f"<i>{chart_type}</i>", styles["BodyText"]))
            data = chart.get("data")
            if isinstance(data, list):
                table = _chart_table(data, styles)
                if table is not None:
                    story.append(table)
            story.append(Spacer(1, 8))

    if answer.claim_comparisons:
        story.append(Paragraph("Management Claims vs. Data", heading_style))
        rows = [["Document claim", "Label", "Explanation"]]
        for c in answer.claim_comparisons:
            rows.append([c.document_claim, c.label.value, c.explanation])
        table = Table(rows, colWidths=[2.2 * inch, 1.3 * inch, 2.5 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e1e0d9")),
                ]
            )
        )
        story.append(table)

    if answer.recommendations:
        story.append(Paragraph("Recommendations", heading_style))
        story.append(Paragraph("Every item below is an AI interpretation, not a verified fact.", small_style))
        for f in answer.recommendations[:MAX_RECOMMENDATIONS]:
            story.append(_finding_paragraph(f, styles))
            story.append(Spacer(1, 4))

    if answer.citations:
        story.append(Paragraph("Sources", heading_style))
        for c in answer.citations:
            location_bits = [f"{k}={v}" for k, v in c.location.items() if v is not None]
            location_str = f" ({', '.join(location_bits)})" if location_bits else ""
            story.append(
                Paragraph(f"- {c.document_name}{location_str}: “{c.excerpt[:200]}…”", styles["BodyText"])
            )

    story.append(Paragraph("Evidence & Methodology", heading_style))
    story.append(
        Paragraph(
            "Every calculated figure above was computed by DataWise's deterministic analysis engine directly "
            "from the uploaded data -- the AI model never performs the calculation itself, only selects which "
            "tool to run and narrates the result. Document-grounded claims are backed by a citation to the "
            "specific source passage, shown under Sources above. Findings labeled AI INTERPRETATION are the "
            "model's own reasoning about the verified findings and are never presented as calculated facts.",
            small_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()
