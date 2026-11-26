"""Receipt -> claim lines and claim-check exports (ui/claim_tools.py). Pure functions, no API or model."""
from datetime import date

from ui.claim_tools import claim_check_csv, claim_check_html, receipt_to_claim_lines


def hotel(**overrides):
    return {'category': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR', 'service_date': '2026-11-14',
            'nights': 2, 'nightly_amounts': None, 'payable_total': 11000, 'receipt_id': 'R-1',
            'excluded_items': [{'description': 'minibar', 'amount': 500}]} | overrides


def test_hotel_total_is_split_per_night_and_extras_excluded_once():
    lines = receipt_to_claim_lines(hotel())
    assert [l['amount'] for l in lines] == [5500.0, 5500.0]
    assert [l['excluded_amount'] for l in lines] == [500.0, 0.0]
    assert [l['service_date'] for l in lines] == [date(2026, 11, 14), date(2026, 11, 15)]
    assert sum(l['amount'] for l in lines) == 11000 and all(l['receipt_id'] == 'R-1' for l in lines)


def test_nightly_amounts_are_used_and_extras_added_to_the_first_night():
    lines = receipt_to_claim_lines(hotel(nightly_amounts=[5000, 5200], excluded_items=[{'amount': 300}]))
    assert [l['amount'] for l in lines] == [5300.0, 5200.0]
    assert [l['excluded_amount'] for l in lines] == [300.0, 0.0]


def test_uneven_split_keeps_the_receipt_total_to_the_paisa():
    lines = receipt_to_claim_lines(hotel(nights=3, payable_total=10000, excluded_items=[]))
    assert [l['amount'] for l in lines] == [3333.33, 3333.33, 3333.34]


def test_flight_and_taxi_are_one_line_and_no_amount_means_no_line():
    flight = receipt_to_claim_lines({'category': 'flight', 'country': 'IN', 'currency': 'INR',
                                     'service_date': '2026-11-14', 'payable_total': 9000, 'receipt_id': 'PNR9'})
    assert len(flight) == 1 and flight[0]['journey_id'] == 'PNR9' and flight[0]['amount'] == 9000.0
    assert receipt_to_claim_lines({'category': 'local_transport', 'service_date': '2026-11-14',
                                   'payable_total': None}) == []
    assert receipt_to_claim_lines(hotel(service_date='not a date')) == []


ASSESSMENT = {'assessment_id': 'A-1', 'assessment': {
    'lines': [{'category': 'hotel', 'claimed_inr': '6000.00', 'eligible_inr': '5000.00', 'over_cap_inr': '1000.00',
               'excluded_inr': '0.00', 'rule_id': 'P02', 'cap_id': 'CAP-HOTEL-IN-METRO-E'}],
    'claimed_total_inr': '6000.00', 'eligible_total_inr': '5000.00', 'over_cap_total_inr': '1000.00',
    'excluded_total_inr': '0.00', 'readiness': 'HUMAN_REVIEW', 'compliance_status': 'EXCEEDS_POLICY',
    'budget_status': 'WITHIN_BUDGET', 'registry': {'version': '1.1'},
    'issues': [{'reason': 'OVER_CATEGORY_CAP', 'readiness': 'HUMAN_REVIEW', 'message': '<over> cap'}]}}
INPUTS = [{'city': 'Bengaluru', 'service_date': '2026-11-14', 'currency': 'INR', 'amount': 6000}]


def test_csv_export_has_lines_totals_and_disclaimer():
    text = claim_check_csv(ASSESSMENT, INPUTS, 'E', ('2026-11-14', '2026-11-15')).decode('utf-8')
    assert text.startswith('﻿')                                         # Excel-friendly
    assert 'CAP-HOTEL-IN-METRO-E' in text and 'Policy-eligible (INR),5000.00' in text
    assert 'not an approval' in text


def test_html_report_escapes_text():
    page = claim_check_html(ASSESSMENT, INPUTS, 'E', ('2026-11-14', '2026-11-15'), 'Arjun <b>', [])
    assert '&lt;over&gt; cap' in page and 'Arjun &lt;b&gt;' in page and '<over>' not in page
