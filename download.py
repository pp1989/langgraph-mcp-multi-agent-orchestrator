from io import BytesIO
from datetime import datetime
from html import escape
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable


def build_travel_pdf(travel_data: dict) -> BytesIO:

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="TripMate AI Travel Report",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TripMateTitle",
        parent=styles["Title"],
        fontSize=22,
        alignment=1,
        textColor=colors.HexColor("#172554"),
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#1e40af"),
        spaceBefore=12,
        spaceAfter=8,
    )

    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontSize=9, leading=14
    )

    story = []

    story.append(Paragraph("TRIPMATE AI", title_style))

    story.append(Paragraph("Personalized Travel Planning Report", body_style))

    sections = [
        ("Flight Information", "flight_results"),
        ("Hotel Suggestions", "hotel_results"),
        ("Weather Information", "weather_results"),
        ("Budget Analysis", "budget_results"),
        ("Travel Itinerary", "itinerary"),
    ]

    def extract_text(value):

        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if hasattr(value, "content"):
            return extract_text(value.content)

        if isinstance(value, list):
            return "\n".join(filter(None, [extract_text(item) for item in value]))

        if isinstance(value, dict):
            return str(value.get("text", value))

        return str(value)

    for title, key in sections:

        content = extract_text(travel_data.get(key))

        if not content.strip():
            continue

        story.append(Paragraph(escape(title), section_style))

        for line in content.splitlines():

            line = line.strip()

            if line:
                story.append(Paragraph(escape(line), body_style))

            story.append(Spacer(1, 4))

    def add_footer(canvas, document):

        canvas.saveState()

        canvas.setFont("Helvetica", 8)

        canvas.drawString(18 * mm, 10 * mm, "TripMate AI")

        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {document.page}")

        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)

    buffer.seek(0)

    return buffer
