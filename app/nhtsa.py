"""VIN decoding through NHTSA's free vPIC service (FR-2). Read-only, no key.

Only called when a user taps "Look up"; pages never wait on it (NFR-10)."""

from dataclasses import dataclass

import httpx2

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}"


class NhtsaError(Exception):
    """The lookup failed. The message is safe to show; it never contains the VIN."""


@dataclass
class Decoded:
    year: str = ""
    make: str = ""
    model: str = ""
    trim: str = ""
    engine: str = ""


def http_client() -> httpx2.Client:
    return httpx2.Client(timeout=httpx2.Timeout(10.0), headers={"Accept": "application/json"})


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"not applicable", "null", "none"} else text


def _engine(row: dict) -> str:
    parts = []
    try:
        parts.append(f"{float(_clean(row.get('DisplacementL'))):.1f}L")
    except ValueError:
        pass
    cylinders = _clean(row.get("EngineCylinders"))
    if cylinders:
        parts.append(f"{cylinders}-cyl")
    fuel = _clean(row.get("FuelTypePrimary"))
    if fuel and fuel.lower() != "gasoline":
        parts.append(fuel.lower())
    return " ".join(parts)


def decode_vin(vin: str) -> Decoded:
    """Year, make, model, trim and engine for a VIN, or NhtsaError."""
    try:
        with http_client() as client:
            response = client.get(VPIC_URL.format(vin=vin), params={"format": "json"})
            response.raise_for_status()
            row = response.json()["Results"][0]
    except (httpx2.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise NhtsaError("The VIN lookup isn't available right now.") from exc
    decoded = Decoded(
        year=_clean(row.get("ModelYear")),
        make=_clean(row.get("Make")).title(),
        model=_clean(row.get("Model")),
        trim=_clean(row.get("Trim")) or _clean(row.get("Series")),
        engine=_engine(row),
    )
    if not (decoded.make and decoded.model):
        raise NhtsaError("No vehicle was found for that VIN.")
    return decoded
