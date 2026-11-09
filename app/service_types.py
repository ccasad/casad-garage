"""The kinds of service a car gets (FR-12)."""

SERVICE_TYPES = [
    ("oil_change", "Oil change"),
    ("tires", "Tires"),
    ("alignment", "Alignment"),
    ("brakes", "Brakes"),
    ("engine_air_filter", "Engine air filter"),
    ("cabin_air_filter", "Cabin air filter"),
    ("battery", "Battery"),
    ("fluids", "Fluids"),
    ("state_inspection", "State inspection"),
    ("emissions_inspection", "Emissions inspection"),
    ("other", "Other"),
]
SERVICE_TYPE_LABELS = dict(SERVICE_TYPES)

# Guess a type from a job title on an imported invoice (FR-19).
# Order matters: the first match wins, so specific words come before general ones.
KEYWORDS = [
    ("oil_change", ("oil change", "oil & filter", "oil and filter", "lube")),
    ("cabin_air_filter", ("cabin",)),
    ("engine_air_filter", ("air filter", "engine filter")),
    ("fluids", ("flush", "coolant", "fluid", "transmission service")),
    ("emissions_inspection", ("emission",)),
    ("state_inspection", ("inspection",)),
    ("alignment", ("alignment",)),
    ("tires", ("tire", "tyre")),
    ("brakes", ("brake", "rotor")),
    ("battery", ("battery",)),
]


def guess_type(title: str) -> str:
    text = title.lower()
    for key, words in KEYWORDS:
        if any(word in text for word in words):
            return key
    return "other"
