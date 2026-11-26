"""Calculation boundaries beyond the golden suite (TEST_PROTOCOL section 8, AC03, AC04, AC11)."""
from decimal import Decimal

from domain.assessment import assess

BASE = {'grade': 'E', 'trip_end': '2026-11-15', 'submitted_on': '2026-11-16', 'user_confirmed': True,
        'required_documents_present': True, 'coverage_complete': True, 'service_date': '2026-11-15',
        'transaction_date': '2026-11-15'}


def claim(**fields):
    return assess({**BASE, **fields})


def identity_holds(result):
    parts = [result[k] for k in ('eligible_total_inr', 'excluded_total_inr', 'over_cap_total_inr',
                                 'rounding_adjustment_inr')]
    return Decimal(result['claimed_total_inr']) == sum(Decimal(p) for p in parts)


def test_specification_worked_example():
    """SPECIFICATION.txt: two Bengaluru nights at 6000 plus 2000 local transport, budget 15000."""
    result = claim(budget_inr=15000, lines=[
        {'category': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR', 'amount': 6000,
         'service_date': '2026-11-14'},
        {'category': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR', 'amount': 6000,
         'service_date': '2026-11-15'},
        {'category': 'local_transport', 'country': 'IN', 'currency': 'INR', 'amount': 2000,
         'service_date': '2026-11-15'}])
    assert result['claimed_total_inr'] == '14000.00'
    assert result['eligible_total_inr'] == '11500.00'
    assert result['over_cap_total_inr'] == '2500.00'
    assert result['budget_status'] == 'WITHIN_BUDGET'
    assert result['remaining_budget_inr'] == '1000.00'
    assert result['compliance_status'] == 'EXCEEDS_POLICY'
    assert result['readiness'] == 'HUMAN_REVIEW'
    assert identity_holds(result)


def test_nights_must_be_positive():
    for nights in (0, -1):
        result = claim(category='hotel', country='IN', city='Delhi', currency='INR', amount=4000, nights=nights)
        assert result['readiness'] == 'NEEDS_CLARIFICATION'
        assert result['claimed_total_inr'] is None


def test_multi_night_single_amount_asks_for_nightly_breakdown():
    result = claim(category='hotel', country='IN', city='Delhi', currency='INR', amount=9000, nights=2)
    assert result['readiness'] == 'NEEDS_CLARIFICATION'
    assert 'nights' in result['missing_fields']


def test_each_night_capped_independently():
    result = claim(category='hotel', country='IN', city='Delhi', currency='INR', nightly_amounts=[4000, 6000])
    assert result['eligible_total_inr'] == '9000.00'
    assert result['over_cap_total_inr'] == '1000.00'


def test_connecting_segments_share_one_journey_cap_and_round_trip_gets_two():
    segments = [{'category': 'flight', 'country': 'IN', 'currency': 'INR', 'amount': 7000, 'journey_id': 'OUT'},
                {'category': 'flight', 'country': 'IN', 'currency': 'INR', 'amount': 7000, 'journey_id': 'OUT'},
                {'category': 'flight', 'country': 'IN', 'currency': 'INR', 'amount': 9000, 'journey_id': 'BACK'}]
    result = claim(cabin='economy', lines=segments)
    assert result['claimed_total_inr'] == '23000.00'
    assert result['eligible_total_inr'] == '21000.00'
    assert result['over_cap_total_inr'] == '2000.00'


def test_international_flight_cap_applies_after_conversion():
    result = claim(category='flight', country='US', city='New York', currency='USD', amount=1000, fx_rate=84,
                   cabin='economy')
    assert result['claimed_total_inr'] == '84000.00'
    assert result['eligible_total_inr'] == '80000.00'
    assert result['over_cap_total_inr'] == '4000.00'


def test_business_cabin_is_excluded_not_capped():
    result = claim(category='flight', country='IN', currency='INR', amount=9000, cabin='business')
    assert result['excluded_total_inr'] == '9000.00'
    assert result['compliance_status'] == 'HAS_EXCLUSIONS'
    assert 'CABIN_NOT_PERMITTED' in result['reasons']


def test_exclusions_come_off_before_caps_and_mixed_status():
    result = claim(category='hotel', country='IN', city='Mumbai', currency='INR', amount=5600, excluded_amount=300)
    assert result['excluded_total_inr'] == '300.00'
    assert result['eligible_total_inr'] == '5000.00'
    assert result['over_cap_total_inr'] == '300.00'
    assert result['compliance_status'] == 'MIXED'


def test_multiple_currencies_in_one_claim():
    result = claim(lines=[
        {'category': 'hotel', 'country': 'US', 'city': 'Boston', 'currency': 'USD', 'amount': 181, 'fx_rate': 84},
        {'category': 'local_transport', 'country': 'SG', 'currency': 'SGD', 'amount': 50, 'fx_rate': 63}])
    assert result['claimed_total_inr'] == '18354.00'
    assert result['over_cap_total_inr'] == '84.00'


def test_mixed_currency_shared_daily_cap_needs_clarification():
    result = claim(lines=[
        {'category': 'local_transport', 'country': 'US', 'currency': 'USD', 'amount': 40, 'fx_rate': 84},
        {'category': 'local_transport', 'country': 'US', 'currency': 'INR', 'amount': 500}])
    assert result['readiness'] == 'NEEDS_CLARIFICATION'
    assert 'CURRENCY_MISMATCH' in result['reasons']


def test_rounding_residual_is_reported_not_a_violation():
    result = claim(category='hotel', country='US', city='Boston', currency='USD', amount='180.00',
                   excluded_amount='0.01', fx_rate='84.5')
    assert result['claimed_total_inr'] == '15210.00'
    assert result['rounding_adjustment_inr'] == '-0.01'
    assert result['over_cap_total_inr'] == '0.00'
    assert 'ROUNDING_RESIDUAL' in result['reasons']
    assert 'OVER_CATEGORY_CAP' not in result['reasons']
    assert identity_holds(result)


def test_unknown_fx_blocks_final_amounts_but_keeps_provisional():
    result = claim(category='hotel', country='US', city='Boston', currency='USD', amount=150,
                   transaction_date='2026-11-14', service_date='2026-11-14')
    assert result['readiness'] == 'NEEDS_CLARIFICATION'
    assert result['claimed_total_inr'] is None
    assert 'UNDOCUMENTED_FX' in result['reasons']


def test_unsupported_destination_goes_to_human_review():
    result = claim(category='hotel', country='FR', city='Paris', currency='INR', amount=9000)
    assert result['readiness'] == 'HUMAN_REVIEW'
    assert result['compliance_status'] == 'UNKNOWN'
    assert result['eligible_total_inr'] is None


def test_missing_evidence_and_late_claim_precedence():
    late = claim(category='hotel', country='IN', city='Delhi', currency='INR', amount=3000,
                 trip_end='2026-10-01', submitted_on='2026-11-15')
    assert late['readiness'] == 'HUMAN_REVIEW' and late['late'] is True
    both = claim(category='hotel', country='IN', city='Delhi', currency='INR', amount=3000,
                 trip_end='2026-10-01', submitted_on='2026-11-15', required_documents_present=False)
    assert both['readiness'] == 'NEEDS_EVIDENCE'


def test_lines_record_cap_and_registry_version():
    result = claim(category='hotel', country='IN', city='Delhi', currency='INR', amount=3000)
    assert result['lines'][0]['cap_id'] == 'CAP-HOTEL-IN-METRO-E'
    assert result['lines'][0]['registry_version'] == '1.1'
