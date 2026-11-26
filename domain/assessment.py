"""Claim assessment: calculation, evidence, deadline, budget and readiness (FR04, FR05, P09, P12, P13, P20)."""
from datetime import timedelta

from domain.budget import budget_outcome
from domain.calculation import Line, calculate
from domain.deadline import deadline_outcome
from domain.errors import DomainIssue
from domain.fx import documented_rate
from domain.inputs import normalize, parse_date
from domain.money import money_str, to_decimal, zero
from domain.reference import canonical_city, home_currency, normalize_country
from domain.registry import all_caps, registry_version, review_status
from domain.status import compliance_status, highest_readiness

BLOCKING = {'INPUT_ERROR', 'NEEDS_CLARIFICATION'}


def _rate(data, currency, on_date, line=None):
    line = line or {}
    try:
        return documented_rate(currency, line.get('fx_rate', data.get('fx_rate')),
                               line.get('fx_reference', data.get('fx_reference')), on_date), None
    except DomainIssue as issue:
        return None, issue


def _amount(value, issues, field):
    try:
        return to_decimal(value)
    except ValueError:
        issues.append(DomainIssue('INPUT_ERROR', 'INVALID_AMOUNT', 'Invalid %s.' % field, [field]))
        return None


def build_lines(data):
    """Expand a payload into one line per night, journey or local charge (TEST_PROTOCOL section 9)."""
    issues, lines = [], []
    category = data.get('category')
    country, city = normalize_country(data.get('country')), canonical_city(data.get('city'))
    currency = data.get('currency')
    service_date = parse_date(data.get('service_date'))
    tx_date = parse_date(data.get('transaction_date')) or service_date
    excluded = _amount(data.get('excluded_amount'), issues, 'excluded_amount') or zero()

    def make(line_id, amount, day, extra=None):
        extra = extra or {}
        cur = extra.get('currency', currency)
        rate, issue = _rate(data, cur, parse_date(extra.get('transaction_date')) or tx_date or day, extra)
        if issue:
            issues.append(issue)
        return Line(line_id=line_id, category=extra.get('category', category),
                    country=normalize_country(extra.get('country', country)),
                    city=canonical_city(extra.get('city', city)), currency=cur,
                    amount=_amount(amount, issues, 'amount'),
                    excluded=_amount(extra.get('excluded_amount'), issues, 'excluded_amount') or zero(),
                    service_date=parse_date(extra.get('service_date')) or day, fx_rate=rate,
                    journey_id=extra.get('journey_id'), receipt_id=extra.get('receipt_id'),
                    cabin=extra.get('cabin', data.get('cabin')),
                    business_purpose=extra.get('business_purpose', data.get('business_purpose', True)))

    if data.get('lines'):
        for index, raw in enumerate(data['lines']):
            lines.append(make(raw.get('line_id') or 'L%d' % (index + 1), raw.get('amount'),
                              parse_date(raw.get('service_date')) or service_date, raw))
        return lines, issues

    if data.get('amounts_inr') is not None:
        dates = data.get('service_dates') or []
        for index, amount in enumerate(data['amounts_inr']):
            day = parse_date(dates[index]) if index < len(dates) else service_date
            lines.append(make('L%d' % (index + 1), amount, day, {'currency': currency or home_currency()}))
        if lines:
            lines[0].excluded = excluded
        return lines, issues

    if data.get('nightly_amounts') is not None and category == 'hotel':
        for index, amount in enumerate(data['nightly_amounts']):
            day = service_date + timedelta(days=index) if service_date else None
            lines.append(make('N%d' % (index + 1), amount, day))
        if lines:
            lines[0].excluded = excluded
        return lines, issues

    if category == 'hotel' and 'nights' in data:
        nights = data.get('nights')
        if nights is None or int(nights) <= 0:
            issues.append(DomainIssue('NEEDS_CLARIFICATION', 'INCONSISTENT_DATES',
                                      'Hotel dates must define a positive number of nights.', ['nights'],
                                      ['valid check-in and check-out dates']))
            return [], issues
        if int(nights) > 1:
            issues.append(DomainIssue('NEEDS_CLARIFICATION', 'MISSING_CRITICAL_FIELD',
                                      'Each hotel night is capped independently; provide the nightly amounts.',
                                      ['nights'], ['amount for each night']))
            return [], issues
    if category == 'flight' and data.get('journeys') not in (None, 1):
        issues.append(DomainIssue('NEEDS_CLARIFICATION', 'MISSING_CRITICAL_FIELD',
                                  'Each one-way journey is capped separately; provide the amount per journey.',
                                  ['journey_id']))
        return [], issues
    if data.get('taxes_and_fees_included') is False:
        issues.append(DomainIssue('NEEDS_CLARIFICATION', 'INCOMPLETE_PRICE',
                                  'Caps are all-inclusive; confirm the amount including taxes and mandatory fees.',
                                  ['amount']))
    line = make('L1', data.get('amount'), service_date)
    line.excluded = excluded
    lines.append(line)
    return lines, issues


def assess(payload):
    data = normalize(payload)
    grade = data.get('grade')
    lines, issues = build_lines(data)
    if grade not in {c.grade for c in all_caps()}:
        issues.append(DomainIssue('NEEDS_CLARIFICATION', 'UNKNOWN_GRADE', 'Traveler grade must be E or M.', ['grade'],
                                  ['traveler grade (E or M)']))
        calc = calculate([], grade)
        calc.compliance_unknown = True
    else:
        calc = calculate(lines, grade)
    issues.extend(i for i in calc.issues if i not in issues)
    evidence = list(calc.evidence_ids)

    if data.get('user_confirmed') is False:
        issues.append(DomainIssue('NEEDS_CLARIFICATION', 'UNCONFIRMED_FIELDS',
                                  'Confirm the extracted critical fields before a final calculation.',
                                  ['user_confirmed']))
    if data.get('required_documents_present') is False:
        issues.append(DomainIssue('NEEDS_EVIDENCE', 'MISSING_EVIDENCE',
                                  'Required receipts or boarding passes are missing.', ['itemized_invoice']))
        evidence.append('P09')
    deadline = None
    if data.get('trip_end') is not None and data.get('submitted_on') is not None:
        deadline = deadline_outcome(data['trip_end'], data['submitted_on'])
        evidence.append('P13')
        if deadline['reason']:
            issues.append(DomainIssue(deadline['readiness'], deadline['reason'],
                                      'Submission is late.' if deadline['late'] else 'Submission dates are inconsistent.',
                                      deadline['missing_fields']))

    blocking = any(i.readiness in BLOCKING for i in issues)
    claimed = calc.total('claimed_inr')
    eligible, excluded = calc.total('eligible_inr'), calc.total('excluded_inr')
    over, rounding = calc.total('over_cap_inr'), calc.total('rounding_inr')
    unknown = calc.compliance_unknown or blocking
    finals = {'claimed_total_inr': claimed, 'eligible_total_inr': None if unknown else eligible,
              'excluded_total_inr': None if unknown else excluded, 'over_cap_total_inr': None if unknown else over,
              'rounding_adjustment_inr': None if unknown else rounding}
    provisional = {}
    if blocking:
        provisional = {k: money_str(v) for k, v in (('claimed_total_inr', claimed), ('eligible_total_inr', eligible),
                                                     ('excluded_total_inr', excluded), ('over_cap_total_inr', over))
                       if v is not None}
        finals = dict.fromkeys(finals)

    policy_review = []
    if not unknown and (calc.over_cap or calc.excluded):
        policy_review.append('HUMAN_REVIEW')
    readiness = highest_readiness([i.readiness for i in issues] + policy_review)
    budget = budget_outcome(finals['claimed_total_inr'], data.get('budget_inr'), data.get('coverage_complete', True))
    if budget['budget_status'] != 'UNKNOWN' or data.get('budget_inr') is not None:
        evidence.append('P12')
    evidence.append('P20')
    reasons = list(dict.fromkeys(calc.reasons + [i.reason_code for i in issues]))
    if data.get('coverage_complete') is False:
        reasons.append('PARTIAL_TRIP_COVERAGE')
    if rounding not in (None, zero()):
        reasons.append('ROUNDING_RESIDUAL')
    missing = list(dict.fromkeys(f for i in issues for f in i.missing_fields))
    ask_for = list(dict.fromkeys(a for i in issues for a in i.ask_for))
    return {
        'claimed_total_inr': money_str(finals['claimed_total_inr']),
        'eligible_total_inr': money_str(finals['eligible_total_inr']),
        'excluded_total_inr': money_str(finals['excluded_total_inr']),
        'over_cap_total_inr': money_str(finals['over_cap_total_inr']),
        'rounding_adjustment_inr': money_str(finals['rounding_adjustment_inr']),
        'budget_status': budget['budget_status'],
        'remaining_budget_inr': budget['remaining_budget_inr'],
        'budget_excess_inr': budget['budget_excess_inr'],
        'display_label': budget['display_label'],
        'compliance_status': compliance_status(calc.over_cap, calc.excluded, unknown),
        'readiness': readiness,
        'late': deadline['late'] if deadline else None,
        'reasons': reasons,
        'evidence_ids': list(dict.fromkeys(evidence)),
        'missing_fields': missing,
        'ask_for': ask_for,
        'provisional_amounts': provisional,
        'lines': [r.as_dict() for r in calc.lines],
        'registry': {'version': registry_version(), 'review_status': review_status()},
        'issues': [i.as_dict() for i in issues],
        'message': _message(readiness, reasons, finals),
    }


def _message(readiness, reasons, finals):
    parts = ['Readiness %s.' % readiness]
    if finals['claimed_total_inr'] is not None:
        parts.append('Claimed INR %s.' % money_str(finals['claimed_total_inr']))
    if finals['eligible_total_inr'] is not None:
        parts.append('Policy-eligible INR %s.' % money_str(finals['eligible_total_inr']))
    if reasons:
        parts.append('Reasons: %s.' % ', '.join(reasons))
    parts.append('This is an assessment for review, not a claim approval.')
    return ' '.join(parts)


def assess_confirmed_claim(payload):
    """Entrypoint assess_confirmed_claim (GT031-GT060)."""
    return assess(payload)


def aggregate_local_transport(payload):
    """Entrypoint aggregate_local_transport (GT104): same-day local charges share one daily cap."""
    data = dict(payload)
    data.setdefault('category', 'local_transport')
    return assess(data)
