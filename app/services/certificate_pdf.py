from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

from app.database import CLINIC_TZ


def _document_font() -> str:
    windows_fonts = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    for filename in (
        windows_fonts / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if filename.is_file():
            pdfmetrics.registerFont(TTFont("ClinicSans", str(filename)))
            return "ClinicSans"
    return "Helvetica"


BODY_FONT = _document_font()


def _visit_time(value: datetime) -> str:
    return value.astimezone(CLINIC_TZ).strftime("%Y-%m-%d at %H:%M") + " (UTC+05:00)"


def render_certificate(
    appointment_id: int, patient_name: str, doctor_name: str, starts_at: datetime, approved_at: datetime
) -> bytes:
    stream = BytesIO()
    pdf = Canvas(stream, pagesize=A4)
    pdf.setTitle("Proof of Attendance")
    pdf.setAuthor("Clinic Appointment Service")
    width, height = A4
    margin = 54
    content_width = width - 2 * margin
    ink = HexColor("#142D3A")
    teal = HexColor("#126B63")
    muted = HexColor("#456173")

    pdf.setFillColor(teal)
    pdf.rect(margin, height - 78, 35, 4, fill=1, stroke=0)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, height - 105, "CLINIC APPOINTMENT SERVICE")

    pdf.setFillColor(ink)
    pdf.setFont("Helvetica-Bold", 32)
    pdf.drawString(margin, height - 154, "Proof of Attendance")
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(margin, height - 181, "This document confirms that the patient attended the visit.")

    fields = [
        ("Patient", patient_name),
        ("Doctor", doctor_name),
        ("Visit date and time", _visit_time(starts_at)),
        ("Approved on", _visit_time(approved_at)),
    ]
    style = ParagraphStyle(name="CertificateValue", fontName=BODY_FONT, fontSize=15, leading=19, textColor=ink)
    top = height - 215
    for label, value in fields:
        paragraph = Paragraph(escape(" ".join(value.split())), style)
        _, text_height = paragraph.wrap(content_width - 40, height)
        row_height = 34 + text_height
        pdf.setFillColor(HexColor("#F0F6F5"))
        pdf.roundRect(margin, top - row_height, content_width, row_height, 8, fill=1, stroke=0)
        pdf.setFillColor(teal)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin + 20, top - 17, label)
        paragraph.drawOn(pdf, margin + 20, top - 26 - text_height)
        top -= row_height + 10

    pdf.setStrokeColor(HexColor("#BDCDCE"))
    pdf.line(margin, 95, width - margin, 95)
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, 75, f"Visit reference {appointment_id}")
    pdf.drawRightString(width - margin, 75, "Approved by the clinic")
    pdf.showPage()
    pdf.save()
    return stream.getvalue()
