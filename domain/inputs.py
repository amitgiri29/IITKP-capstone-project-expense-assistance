"""Normalize caller payloads: documented aliases and date parsing (TEST_PROTOCOL section 2)."""
from datetime import date

ALIASES = {'confirmed': 'user_confirmed', 'evidence_complete': 'required_documents_present'}


def normalize(payload):
    """Copy payload applying aliases. An explicitly supplied canonical key wins over its alias."""
    data = dict(payload)
    for alias, canonical in ALIASES.items():
        if alias in data and canonical not in data:
            data[canonical] = data[alias]
    return data


def parse_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
