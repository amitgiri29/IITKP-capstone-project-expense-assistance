"""Input validation that blocks a final decision (P01, P20)."""
from domain.inputs import parse_date
from domain.money import money_str, to_decimal, zero
from domain.reference import is_known_currency, is_supported_country
from domain.registry import all_caps
from domain.status import highest_readiness

ASK_FOR = {'grade': 'traveler grade (E or M)', 'country': 'destination country', 'city': 'destination city',
           'currency': 'currency of the amount', 'service_date': 'service date',
           'trip_start': 'trip start date', 'trip_end': 'trip end date', 'submitted_on': 'submission date',
           'amount': 'payable amount'}


def validate_amount(payload):
    """Entrypoint validate_amount (GT108)."""
    try:
        amount = to_decimal(payload.get('amount'))
    except ValueError:
        amount = None
        invalid = True
    else:
        invalid = amount is not None and amount < zero()
    if invalid:
        return {'readiness': 'INPUT_ERROR', 'final_amounts': None, 'reasons': ['INVALID_AMOUNT'],
                'missing_fields': ['amount'], 'message': 'Amounts must be finite nonnegative decimals.'}
    if amount is None:
        return {'readiness': 'NEEDS_CLARIFICATION', 'final_amounts': None, 'reasons': ['MISSING_CRITICAL_FIELD'],
                'missing_fields': ['amount'], 'message': 'The amount is missing.'}
    currency = payload.get('currency')
    if not is_known_currency(currency):
        return {'readiness': 'NEEDS_CLARIFICATION', 'final_amounts': None, 'reasons': ['MISSING_CRITICAL_FIELD'],
                'missing_fields': ['currency'], 'message': 'A supported currency is required.'}
    return {'readiness': 'READY_FOR_REVIEW', 'final_amounts': {'amount': money_str(amount), 'currency': currency},
            'reasons': [], 'missing_fields': [], 'message': 'Amount is valid.'}


def context_issues(payload):
    """Check only the context fields the caller supplied (TEST_PROTOCOL section 2)."""
    missing, invalid = [], []
    grades = {c.grade for c in all_caps()}
    for name in ('grade', 'country', 'city', 'currency', 'service_date', 'trip_start', 'trip_end', 'submitted_on'):
        if name in payload and payload[name] is None:
            missing.append(name)
    if payload.get('grade') is not None and payload['grade'] not in grades:
        invalid.append('grade')
    if payload.get('country') is not None and not is_supported_country(payload['country']):
        invalid.append('country')
    if payload.get('currency') is not None and not is_known_currency(payload['currency']):
        invalid.append('currency')
    start, end = parse_date(payload.get('trip_start')), parse_date(payload.get('trip_end'))
    if start and end and start > end:
        invalid.append('trip_end')
    return missing, invalid


def validate_claim_context(payload):
    """Entrypoint validate_claim_context (GT101)."""
    missing, invalid = context_issues(payload)
    reasons = []
    if 'grade' in missing or 'grade' in invalid:
        reasons.append('UNKNOWN_GRADE')
    if 'country' in invalid:
        reasons.append('UNSUPPORTED_DESTINATION')
    if set(missing) - {'grade'}:
        reasons.append('MISSING_CRITICAL_FIELD')
    if 'trip_end' in invalid:
        reasons.append('INCONSISTENT_DATES')
    readiness = highest_readiness(['NEEDS_CLARIFICATION'] if (missing or set(invalid) - {'country'}) else
                                  ['HUMAN_REVIEW'] if invalid else [])
    fields = list(dict.fromkeys(missing + [f for f in invalid if f != 'country']))
    return {'readiness': readiness, 'missing_fields': fields, 'ask_for': [ASK_FOR.get(f, f) for f in fields],
            'reasons': reasons,
            'message': ('Please provide: %s.' % ', '.join(ASK_FOR.get(f, f) for f in fields)) if fields else
                       'Context is complete.'}
