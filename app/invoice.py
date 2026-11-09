"""Reading a shop invoice PDF (FR-19, FR-22, NFR-16).

Text extraction only, inside the upload request. One supported layout (see
REQUIREMENTS.md); anything else is reported as not recognised so the user can enter the
record by hand. Only vehicle and job information is kept: the customer block and the
payment history are skipped and never stored."""

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.service_types import guess_type

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 30

AMOUNT = re.compile(r"\$\s*(-?[\d,]+(?:\.\d{1,2})?)")
RO_LINE = re.compile(r"Invoice\s+for\s+RO\s*#\s*([A-Za-z0-9-]+)", re.IGNORECASE)
DATE_LINE = re.compile(r"Posted\s+Date:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", re.IGNORECASE)
VEHICLE_LINE = re.compile(r"Vehicle:\s*(\d{4})\s+(.+)", re.IGNORECASE)
VIN_LINE = re.compile(r"VIN:\s*([A-Z0-9]{5,17})\b", re.IGNORECASE)
ODOMETER_LINE = re.compile(r"Odometer\s+In:\s*([\d,]+)(?:\s*/\s*Out:\s*([\d,]+))?", re.IGNORECASE)
JOB_LINE = re.compile(r"^\s*(\d{1,3})\s+-\s+([A-Za-z].*?)\s*$")
STATUS_LINE = re.compile(
    r"^\s*[✓✔✘✗xX]?\s*(Approved|Authorized|Declined)\s+on\b(.*)$", re.IGNORECASE
)
GRAND_TOTAL = re.compile(r"Grand\s+Total:?\s*\$\s*(-?[\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
SHOP_NOTE = re.compile(r"\*\*(.+?)\*\*")
TWO_WORD_MAKES = ("land rover", "alfa romeo", "aston martin", "mercedes benz", "rolls royce")


class InvoiceError(Exception):
    """The PDF couldn't be read. The message is safe to show."""


@dataclass
class Job:
    title: str
    status: str  # "approved" or "declined"
    price_cents: int | None = None
    note: str = ""
    shop_note: str = ""
    type: str = "other"


@dataclass
class ParsedInvoice:
    ro_number: str
    on: str | None = None  # ISO date
    shop: str = ""
    vin: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    trim: str = ""
    odometer: int | None = None
    grand_total_cents: int | None = None
    jobs: list[Job] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "ParsedInvoice":
        return cls(**{**data, "jobs": [Job(**j) for j in data.get("jobs", [])]})

    @property
    def approved(self) -> list[Job]:
        return [j for j in self.jobs if j.status == "approved"]

    @property
    def declined(self) -> list[Job]:
        return [j for j in self.jobs if j.status == "declined"]


def extract_text(data: bytes) -> str:
    """All text in the PDF, or '' when it has none (a scan or photo). InvoiceError if the
    file isn't a readable PDF."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise InvoiceError("The PDF is password protected.")
        pages = reader.pages[:MAX_PAGES]
        return "\n".join((page.extract_text() or "") for page in pages)
    except InvoiceError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
        raise InvoiceError("That file couldn't be read as a PDF.") from exc


def cents(text: str) -> int:
    return round(float(text.replace(",", "")) * 100)


def last_amount(text: str) -> int | None:
    found = AMOUNT.findall(text)
    return cents(found[-1]) if found else None


def parse_date(month: str, day: str, year: str) -> str | None:
    y = int(year)
    y += 2000 if y < 100 else 0
    try:
        return date(y, int(month), int(day)).isoformat()
    except ValueError:
        return None


def tidy_title(title: str) -> str:
    title = re.sub(r"\s+", " ", SHOP_NOTE.sub("", title)).strip(" -:")
    return title.title() if title.isupper() else title


def split_vehicle(rest: str) -> tuple[str, str, str]:
    words = rest.split()
    if not words:
        return "", "", ""
    take = 2 if len(words) > 2 and " ".join(words[:2]).lower() in TWO_WORD_MAKES else 1
    make = " ".join(words[:take])
    return make, words[take] if len(words) > take else "", " ".join(words[take + 1 :])


def is_price_line(line: str) -> bool:
    """A line holding only amounts, like '$59.99' or 'Subtotal $50 + est. Tax $4 $54'."""
    if not AMOUNT.search(line):
        return False
    rest = re.sub(r"(?i)subtotal|est\.?|tax|total|[+\s]", "", AMOUNT.sub("", line))
    return rest == ""


def parse_invoice(text: str) -> ParsedInvoice | None:
    """The invoice's vehicle and jobs, or None when the layout isn't recognised."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ro = next((m.group(1) for line in lines if (m := RO_LINE.search(line))), None)
    if ro is None:
        return None
    invoice = ParsedInvoice(ro_number=ro)
    if not RO_LINE.search(lines[0]):
        invoice.shop = lines[0]

    job: dict | None = None  # the job being read, until its status line
    awaiting: Job | None = None  # a finished job whose total is on the next line
    for line in lines:
        if re.match(r"Payment\s+History", line, re.IGNORECASE):
            break  # nothing after this is stored (customer and payment details)
        if m := DATE_LINE.search(line):
            invoice.on = parse_date(*m.groups())
        if m := VEHICLE_LINE.search(line):
            invoice.year = m.group(1)
            invoice.make, invoice.model, invoice.trim = split_vehicle(m.group(2))
        if m := VIN_LINE.search(line):
            invoice.vin = m.group(1).upper()
        if m := ODOMETER_LINE.search(line):
            invoice.odometer = int(m.group(1).replace(",", ""))
        if m := GRAND_TOTAL.search(line):
            invoice.grand_total_cents = cents(m.group(1))
            job = awaiting = None
            continue
        if re.match(r"Declined\s+Jobs\s*:?", line, re.IGNORECASE):
            job = awaiting = None
            continue

        if awaiting is not None:
            if is_price_line(line):
                awaiting.price_cents = last_amount(line)
                awaiting = None
                continue
            awaiting = None

        if m := STATUS_LINE.match(line):
            if job is not None:
                finished = Job(
                    title=tidy_title(job["title"]),
                    status="declined" if m.group(1).lower() == "declined" else "approved",
                    price_cents=last_amount(m.group(2))
                    if AMOUNT.search(m.group(2))
                    else job["price"],
                    note=" ".join(job["note"]).strip(),
                    shop_note=job["shop_note"],
                    type=guess_type(job["title"]),
                )
                invoice.jobs.append(finished)
                if finished.price_cents is None:
                    awaiting = finished
                job = None
            continue
        if m := JOB_LINE.match(line):
            title = AMOUNT.sub("", m.group(2)).strip()
            shop_note = SHOP_NOTE.search(title)
            job = {
                "title": title,
                "shop_note": shop_note.group(1).strip() if shop_note else "",
                "note": [],
                "price": last_amount(m.group(2)),
            }
            continue
        if job is not None:
            if line.lower().startswith("note:"):
                job["note"].append(line[5:].strip())
            elif job["note"]:
                job["note"].append(line)  # the note's next line
            elif is_price_line(line):
                job["price"] = last_amount(line)
    if not invoice.jobs:
        return None
    return invoice
