"""Country codes, city tiers, aliases, currencies, FX fixtures and vocabularies."""
from datetime import date
from decimal import Decimal

from domain.data import reference_data


def _countries():
    return reference_data()['countries']


def vocabulary(name):
    return list(reference_data()['vocabularies'][name])


def reason_codes():
    return {entry['code'] for entry in reference_data()['vocabularies']['reason_code']}


def require_reason(code):
    if code not in reason_codes():
        raise ValueError('reason code %r is not defined in reference_data.json' % code)
    return code


def missing_field_codes():
    return set(reference_data()['vocabularies']['missing_field_code'])


def readiness_precedence():
    """Readiness values ordered from highest to lowest precedence (P20)."""
    return vocabulary('readiness')


def home_country():
    return next(c['code'] for c in _countries() if c['is_home'])


def home_currency():
    return country_currency(home_country())


def normalize_country(code):
    """Return the package country code, accepting ISO aliases such as GB for UK."""
    if code is None:
        return None
    value = str(code).strip().upper()
    for country in _countries():
        if value in (country['code'], country['iso_3166_alpha_2']):
            return country['code']
    return value


def is_supported_country(code):
    return normalize_country(code) in {c['code'] for c in _countries() if c['supported']}


def country_currency(code):
    code = normalize_country(code)
    for country in _countries():
        if country['code'] == code:
            return country['currency']
    return None


def is_known_currency(code):
    return code in {c['code'] for c in reference_data()['currencies']}


def canonical_city(city):
    if city is None:
        return None
    text = str(city).strip()
    aliases = {k.casefold(): v for k, v in reference_data()['city_aliases'].items()}
    return aliases.get(text.casefold(), text)


def city_tier(country, city):
    """Hotel rate tier for a domestic city, or None outside the tiered country."""
    tiers = reference_data()['city_tiers']
    if normalize_country(country) != tiers['applies_to']:
        return None
    if city is None:
        return None
    return 'metro' if canonical_city(city) in tiers['metro'] else tiers['default_tier']


def fx_fixture_rate(fx_reference, currency, on_date):
    """Documented fixture rate in home currency per unit, or None when not documented."""
    if not fx_reference or currency is None:
        return None
    for fixture in reference_data()['fx']['fixtures']:
        if fixture['fx_reference'] != fx_reference:
            continue
        if on_date is not None and date.fromisoformat(fixture['date']) != on_date:
            return None
        rate = fixture['rates'].get(currency)
        return Decimal(rate) if rate is not None else None
    return None
