"""Small parsers for form fields. Each returns a cleaned value or raises ValueError
with a message that is safe to show next to the field."""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def parse_date(text: str, *, required: bool = True) -> date | None:
    text = text.strip()
    if not text:
        if required:
            raise ValueError("Enter a date.")
        return None
    try:
        value = date.fromisoformat(text)
    except ValueError:
        raise ValueError("Enter a valid date.") from None
    if not (date(1950, 1, 1) <= value <= date.today() + timedelta(days=366 * 30)):
        raise ValueError("That date looks wrong.")
    return value


def parse_miles(text: str, *, required: bool = True) -> int | None:
    text = re.sub(r"[,\s]|mi$", "", text.strip().lower())
    if not text:
        if required:
            raise ValueError("Enter the miles.")
        return None
    if not text.isdigit() or int(text) > 2_000_000:
        raise ValueError("Enter miles as a whole number.")
    return int(text)


def parse_cents(text: str, *, required: bool = False) -> int | None:
    """'$1,234.50' -> 123450"""
    text = text.strip().replace("$", "").replace(",", "")
    if not text:
        if required:
            raise ValueError("Enter an amount.")
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("Enter an amount like 89.99.") from None
    if value < 0 or value > Decimal(10000000):
        raise ValueError("Enter an amount like 89.99.")
    return int((value * 100).quantize(Decimal(1)))


def parse_months(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if not text.isdigit() or not 1 <= int(text) <= 600:
        raise ValueError("Enter whole months, like 36.")
    return int(text)


def cents_text(cents: int | None) -> str:
    return "" if cents is None else f"{cents / 100:.2f}"
