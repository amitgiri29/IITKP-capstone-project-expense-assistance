"""Resolve reviewed caps and parameters from policy_sources/rule_registry.json."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from domain.data import rule_registry
from domain.reference import city_tier, home_country, is_supported_country, normalize_country


@dataclass(frozen=True)
class Cap:
    cap_id: str
    rule_id: str
    category: str
    country_scope: str
    city_tier: object
    grade: str
    basis: str
    currency: str
    amount: Decimal
    conversion_order: str
    effective_from: date
    effective_to: date


class RegistryLookupError(Exception):
    """Raised when no single reviewed entry applies. The caller maps it to a readiness."""

    def __init__(self, reason_code, message, missing_fields=()):
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.missing_fields = list(missing_fields)


def registry_version():
    return rule_registry()['registry_version']


def review_status():
    return rule_registry()['review_status']


def parameter(parameter_id):
    for entry in rule_registry()['parameters']:
        if entry['parameter_id'] == parameter_id:
            return entry['value']
    raise KeyError(parameter_id)


def parameter_rule(parameter_id):
    for entry in rule_registry()['parameters']:
        if entry['parameter_id'] == parameter_id:
            return entry['rule_id']
    raise KeyError(parameter_id)


def all_caps():
    return [Cap(c['cap_id'], c['rule_id'], c['category'], c['country_scope'], c['city_tier'], c['grade'],
                c['basis'], c['cap_currency'], Decimal(c['cap_amount']), c['conversion_order'],
                date.fromisoformat(c['effective_from']), date.fromisoformat(c['effective_to']))
            for c in rule_registry()['caps']]


def resolve_cap(category, country, city, grade, service_date):
    """Return the single applicable cap or raise RegistryLookupError."""
    country = normalize_country(country)
    if grade not in {c.grade for c in all_caps()}:
        raise RegistryLookupError('UNKNOWN_GRADE', 'Traveler grade must be E or M.', ['grade'])
    if country is None:
        raise RegistryLookupError('MISSING_CRITICAL_FIELD', 'Country is required.', ['country'])
    if not is_supported_country(country):
        raise RegistryLookupError('UNSUPPORTED_DESTINATION',
                                  'No policy rate is defined for %s.' % country)
    if category == 'flight':
        scope, tier = (country if country == home_country() else 'INTERNATIONAL'), None
    else:
        scope = country
        tier = city_tier(country, city) if category == 'hotel' else None
        if category == 'hotel' and tier is None and country == home_country():
            raise RegistryLookupError('MISSING_CRITICAL_FIELD', 'City is required for a domestic hotel.', ['city'])
    matches = [c for c in all_caps() if c.category == category and c.country_scope == scope
               and c.city_tier == tier and c.grade == grade]
    if len(matches) != 1:
        raise RegistryLookupError('NO_APPLICABLE_POLICY',
                                  'No single reviewed cap for %s %s %s.' % (category, scope, grade))
    cap = matches[0]
    if service_date is None:
        raise RegistryLookupError('MISSING_CRITICAL_FIELD', 'Service date is required.', ['service_date'])
    if not cap.effective_from <= service_date <= cap.effective_to:
        raise RegistryLookupError('NO_APPLICABLE_POLICY',
                                  'Service date %s is outside policy %s.' % (service_date, cap.rule_id),
                                  ['applicable_policy_version'])
    return cap
