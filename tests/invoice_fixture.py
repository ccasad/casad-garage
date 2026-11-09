"""An invented invoice in the supported layout. Every name, number and VIN is made up."""

import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

FAKE_VIN = "1A4AA11AA1A111111"

PAGE_1 = [
    ("Example Auto Care", None),
    ("100 Sample Road, Testville, ST 00000", None),
    ("(555) 010-0100", None),
    ("Invoice for RO #12345", None),
    ("Posted Date: 02/10/26 at 3:45 PM", None),
    ("Vehicle: 2019 Acme Roadster Sport", None),
    (f"VIN: {FAKE_VIN}", None),
    ("Odometer In: 52,100 / Out: 52,104", None),
    ("Customer: Pat Example, 1 Nowhere Lane, pat@example.com", None),
    ("1 - STATE INSPECTION **Passed**", None),
    ("Note: Sticker issued for the windshield.", None),
    ("Approved on 02/10/26", "$20.00"),
    ("2 - EMISSIONS TEST", None),
    ("Authorized on 02/10/26", "$30.00"),
    ("Declined Jobs:", None),
    ("3 - REAR BRAKES **Pads at 3mm**", None),
    ("Note: Replace pads and resurface rotors.", None),
    ("Declined on 02/10/26", "Subtotal $300.00 + est. Tax $20.00   $320.00"),
    ("4 - CABIN AIR FILTER", None),
    ("Declined on 02/10/26", "$45.50"),
    ("Grand Total: $50.00", None),
]
PAGE_2 = [
    ("Payment History", None),
    ("02/10/26 Visa ending 0000 $50.00", None),
    ("Pat Example", None),
]


def make_pdf(pages=(PAGE_1, PAGE_2)) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for lines in pages:
        y = 740
        for left, right in lines:
            pdf.drawString(50, y, left)
            if right:
                pdf.drawRightString(560, y, right)
            y -= 18
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def invoice_text() -> str:
    return "\n".join(
        left + (f"   {right}" if right else "") for page in (PAGE_1, PAGE_2) for left, right in page
    )
