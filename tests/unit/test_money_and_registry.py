"""Money rounding and registry resolution (AC03, AC11, AC21)."""
from datetime import date
from decimal import Decimal

import pytest

from domain.money import money_str, round_money, to_decimal
from domain.reference import canonical_city, city_tier, normalize_country
from domain.registry import RegistryLookupError, all_caps, resolve_cap

IN_WINDOW = date(2026, 11, 15)


def test_round_half_up_and_two_place_strings():
    assert money_str(Decimal('0.845')) == '0.85'
    assert money_str(Decimal('22260')) == '22260.00'
    assert money_str(None) is None
    assert round_money(Decimal('-0.005')) == Decimal('-0.01')


@pytest.mark.parametrize('bad', [True, 'abc', 'NaN', 'Infinity'])
def test_to_decimal_rejects_non_amounts(bad):
    with pytest.raises(ValueError):
        to_decimal(bad)


def test_every_registry_cap_resolves_uniquely():
    for cap in all_caps():
        country = 'IN' if cap.country_scope == 'IN' else ('US' if cap.country_scope == 'INTERNATIONAL' else cap.country_scope)
        city = {'metro': 'Mumbai', 'other': 'Jaipur'}.get(cap.city_tier, 'Anywhere')
        assert resolve_cap(cap.category, country, city, cap.grade, IN_WINDOW).cap_id == cap.cap_id


def test_aliases_and_iso_country_codes():
    assert canonical_city('bangalore') == 'Bengaluru'
    assert city_tier('IN', 'Bangalore') == 'metro'
    assert city_tier('IN', 'Jaipur') == 'other'
    assert normalize_country('GB') == 'UK'
    assert resolve_cap('hotel', 'GB', 'London', 'M', IN_WINDOW).cap_id == 'CAP-HOTEL-UK-M'


def test_unsupported_destination_has_no_invented_rate():
    with pytest.raises(RegistryLookupError) as error:
        resolve_cap('hotel', 'FR', 'Paris', 'E', IN_WINDOW)
    assert error.value.reason_code == 'UNSUPPORTED_DESTINATION'


def test_service_date_outside_policy_window_blocks():
    with pytest.raises(RegistryLookupError) as error:
        resolve_cap('hotel', 'IN', 'Delhi', 'E', date(2027, 1, 1))
    assert error.value.reason_code == 'NO_APPLICABLE_POLICY'


def test_unknown_grade_blocks():
    with pytest.raises(RegistryLookupError) as error:
        resolve_cap('hotel', 'IN', 'Delhi', 'X', IN_WINDOW)
    assert error.value.reason_code == 'UNKNOWN_GRADE'
