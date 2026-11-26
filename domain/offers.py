"""Deterministic offer assessment and ranking (P02-P05, P11, P16, P17). Plain Python: no model, no RAG.

Every cap, threshold and enumeration is resolved from the reviewed rule registry and reference data.
Untrusted offer text (descriptions, terms) is never read here, so it cannot influence status or ranking (FR09).
"""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from domain.reference import home_currency, require_reason, vocabulary
from domain.registry import RegistryLookupError, parameter, parameter_rule, resolve_cap

COMPLIANT, NONCOMPLIANT, PROVISIONAL, UNKNOWN = vocabulary('offer_policy_status')


def _money(value):
    return None if value is None else Decimal(str(value))


def _quantize(amount):
    scale = Decimal(1).scaleb(-int(parameter('PARAM-MONEY-SCALE')))
    return amount.quantize(scale, rounding=parameter('PARAM-MONEY-ROUNDING'))


def _time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def freshness(offer, now):
    """'fresh', 'stale' (older than the freshness window) or 'expired' (expires_at at or before now). P17."""
    retrieved = _time(offer.get('retrieved_at'))
    expires = _time(offer.get('expires_at'))
    if expires is not None and expires <= now:
        return 'expired'
    if retrieved is None:
        return 'stale'                       # retrieved_at is required; without it the offer cannot be current
    window = timedelta(minutes=int(parameter('PARAM-OFFER-FRESHNESS-MINUTES')))
    return 'stale' if now - retrieved > window else 'fresh'


def nights_between(checkin, checkout):
    return (date.fromisoformat(str(checkout)) - date.fromisoformat(str(checkin))).days


def _convert(amount, currency, cap_currency, fx_rate):
    """Amount in the cap currency, or None when a documented rate is needed and missing. FX rates are quoted in home
    currency per unit (P11)."""
    if currency == cap_currency:
        return amount
    if fx_rate is None:
        return None
    rate = _money(fx_rate)
    if cap_currency == home_currency():
        return _quantize(amount * rate)
    if currency == home_currency():
        return _quantize(amount / rate)
    return None


def assess_offer(offer, criteria, grade, fx_rate=None):
    """Policy status of one offer, with reason codes and the rule IDs used. Freshness is judged separately."""
    reasons, rules = [], []
    kind = criteria['search_type']
    service_date = date.fromisoformat(str(criteria['checkin'] if kind == 'hotel' else criteria['departure_date']))
    try:
        cap = resolve_cap(kind, criteria.get('country'), criteria.get('city'), grade, service_date)
    except RegistryLookupError as exc:
        return {'status': UNKNOWN, 'reasons': [require_reason(exc.reason_code)], 'rule_ids': [],
                'comparison_amount': None, 'comparison_currency': None, 'cap': None}
    rules.append(cap.rule_id)
    currency = offer.get('currency')
    total = _money(offer.get('total'))
    incomplete = False
    over = False

    if kind == 'flight':
        allowed = parameter('PARAM-ALLOWED-CABIN')
        if offer.get('cabin') not in allowed:
            reasons.append(require_reason('CABIN_NOT_PERMITTED'))
            rules.append(parameter_rule('PARAM-ALLOWED-CABIN'))
            over = True
        bag_limit = int(parameter('PARAM-CHECKED-BAG-KG'))
        if offer.get('baggage_kg') is None or offer.get('baggage_fee_included') is not True \
                or int(offer.get('baggage_kg')) < bag_limit:
            incomplete = True
        capped = [total] if total is not None else []        # the cap is per traveler per one-way journey
    else:
        nights = nights_between(criteria['checkin'], criteria['checkout'])
        nightly = offer.get('nightly_totals')
        if nightly and len(nightly) == nights:
            capped = [_money(n) for n in nightly]            # each night capped independently (P02/P03)
        elif total is not None and nights == 1:
            capped = [total]
        else:
            capped = []                                      # no per-night breakdown: cannot compare to a nightly cap
            incomplete = True
    if offer.get('taxes_included') is not True or offer.get('mandatory_fees_included') is not True:
        incomplete = True
    if total is None:
        incomplete = True

    converted = [_convert(a, currency, cap.currency, fx_rate) for a in capped]
    if currency != cap.currency and (total is None or _convert(total, currency, cap.currency, fx_rate) is None):
        reasons.append(require_reason('UNDOCUMENTED_FX'))
        rules.append('P11')
        incomplete = True
    if any(c is not None and c > cap.amount for c in converted):
        over = True
        reasons.append(require_reason('OVER_CAP_OFFER'))

    if over:
        status = NONCOMPLIANT
    elif incomplete:
        status = PROVISIONAL
        reasons.append(require_reason('PROVISIONAL_PRICE'))
    else:
        status = COMPLIANT
    comparison = None
    if total is not None:
        comparison = _convert(total, currency, cap.currency, fx_rate)
    return {'status': status, 'reasons': reasons, 'rule_ids': sorted(set(rules)),
            'comparison_amount': None if comparison is None else str(_quantize(comparison)),
            'comparison_currency': cap.currency,
            'cap': {'cap_id': cap.cap_id, 'amount': str(cap.amount), 'currency': cap.currency, 'basis': cap.basis,
                    'rule_id': cap.rule_id}}


def rank_key(kind):
    """P16: hotels by all-inclusive stay total, then known venue distance before unknown (ascending), then offer ID;
    flights by all-inclusive price, then duration, then offer ID."""
    def key(item):
        offer, assessment = item
        amount = assessment['comparison_amount']
        price = Decimal(amount) if amount is not None else Decimal('Infinity')
        if kind == 'hotel':
            distance = offer.get('distance_km')
            return (price, distance is None, Decimal(str(distance)) if distance is not None else Decimal(0),
                    str(offer.get('id')))
        duration = offer.get('duration_minutes')
        return (price, duration if duration is not None else float('inf'), str(offer.get('id')))
    return key


def classify(offers, criteria, grade, now, fx_rate=None):
    """Assess, judge freshness and rank. Returns the ordered ID lists and per-offer details."""
    kind = criteria['search_type']
    assessed = [(o, assess_offer(o, criteria, grade, fx_rate)) for o in offers]
    for offer, assessment in assessed:
        assessment['freshness'] = freshness(offer, now)
        if assessment['freshness'] != 'fresh':
            assessment['reasons'].append(require_reason('OFFER_STALE'))
            assessment['rule_ids'] = sorted(set(assessment['rule_ids']) | {parameter_rule(
                'PARAM-OFFER-FRESHNESS-MINUTES')})
    assessed.sort(key=rank_key(kind))
    limit = int(parameter('PARAM-MAX-RECOMMENDATIONS'))
    fresh = [(o, a) for o, a in assessed if a['freshness'] == 'fresh']
    recommended = [o['id'] for o, a in fresh if a['status'] == COMPLIANT][:limit]
    provisional = [o['id'] for o, a in fresh if a['status'] == PROVISIONAL]
    noncompliant = [o['id'] for o, a in assessed if a['status'] == NONCOMPLIANT]
    needs_refresh = [o['id'] for o, a in assessed if a['freshness'] != 'fresh' and a['status'] != NONCOMPLIANT]
    return {'recommended_ids': recommended, 'provisional_ids': provisional, 'noncompliant_ids': noncompliant,
            'needs_refresh_ids': needs_refresh, 'assessed': assessed}
