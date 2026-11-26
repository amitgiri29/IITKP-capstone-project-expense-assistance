"""Documented FX only (P11). Never invent a rate."""
from domain.errors import DomainIssue
from domain.inputs import parse_date
from domain.money import money_str, round_money, to_decimal, zero
from domain.reference import fx_fixture_rate, home_currency


def documented_rate(currency, fx_rate=None, fx_reference=None, on_date=None):
    """Home-currency units per one unit of currency, or None when nothing is documented."""
    if currency == home_currency():
        return to_decimal(1)
    supplied = to_decimal(fx_rate)
    if supplied is not None:
        if supplied <= zero():
            raise DomainIssue('INPUT_ERROR', 'INVALID_AMOUNT', 'FX rate must be positive.', ['fx_rate'])
        return supplied
    return fx_fixture_rate(fx_reference, currency, on_date)


def missing_fx_issue(currency, on_date):
    when = on_date.isoformat() if on_date else 'the transaction date'
    return DomainIssue('NEEDS_CLARIFICATION', 'UNDOCUMENTED_FX',
                       'A documented %s to %s rate for %s is required before conversion.'
                       % (currency, home_currency(), when),
                       missing_fields=['fx_rate'],
                       ask_for=['documented transaction-date FX rate (%s per %s on %s)'
                                % (home_currency(), currency, when)])


def resolve_fx(payload):
    """Entrypoint resolve_fx (GT109)."""
    currency = payload.get('currency')
    on_date = parse_date(payload.get('transaction_date') or payload.get('service_date'))
    amount = to_decimal(payload.get('amount'))
    try:
        rate = documented_rate(currency, payload.get('fx_rate'), payload.get('fx_reference'), on_date)
    except DomainIssue as issue:
        return {**issue.as_dict(), 'final_amounts': None}
    if rate is None:
        issue = missing_fx_issue(currency, on_date)
        return {**issue.as_dict(), 'reasons': [issue.reason_code], 'final_amounts': None}
    converted = None if amount is None else round_money(amount * rate)
    return {'readiness': 'READY_FOR_REVIEW', 'fx_rate_inr': str(rate),
            'final_amounts': {'amount_inr': money_str(converted)}, 'missing_fields': [], 'ask_for': [],
            'reasons': [], 'message': 'Converted at the documented rate %s.' % rate}


def convert_currency_lines(payload):
    """Entrypoint convert_currency_lines (GT110): round each converted line, then sum (P11)."""
    on_date = parse_date(payload.get('transaction_date'))
    converted = []
    for line in payload.get('lines') or []:
        currency = line.get('currency')
        rate = documented_rate(currency, line.get('fx_rate', payload.get('documented_fx_rate')),
                               line.get('fx_reference', payload.get('fx_reference')), on_date)
        if rate is None:
            issue = missing_fx_issue(currency, on_date)
            return {**issue.as_dict(), 'converted_lines_inr': None, 'claimed_total_inr': None}
        converted.append(round_money(to_decimal(line['amount']) * rate))
    total = sum(converted, zero())
    confirmed = payload.get('confirmed', payload.get('user_confirmed', True))
    result = {'converted_lines_inr': [money_str(v) for v in converted],
              'claimed_total_inr': money_str(total) if confirmed else None,
              'reasons': [], 'missing_fields': [] if confirmed else ['user_confirmed']}
    if not confirmed:
        result['provisional_amounts'] = {'claimed_total_inr': money_str(total)}
    return result
