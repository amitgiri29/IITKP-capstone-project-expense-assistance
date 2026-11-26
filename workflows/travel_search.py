"""UC03 travel search (route travel_search): validate criteria, search the provider, assess and rank offers.

The steps are plain functions so the M6 agent executor can call them as registered tools. Offer status, ranking and
every amount come from domain/offers.py (Python); no model and no RAG operation decides them. Search and recommend
only: there is no booking or payment tool anywhere (P18).
"""
from datetime import date

from adapters.travel import ProviderUnavailable
from domain.evidence import evidence_for
from domain.offers import classify, nights_between
from domain.reference import canonical_city, home_country, normalize_country
from domain.registry import parameter, parameter_rule
from workflows.guards import screen

SEARCH_TYPES = ('flight', 'hotel')
REQUIRED = {'flight': ('origin', 'destination', 'departure_date', 'cabin', 'country'),
            'hotel': ('country', 'city', 'checkin', 'checkout')}


def _date(value):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return 'invalid'


def normalize_criteria(payload, grade):
    """Search criteria from the request. Grade always comes from the server-held profile, never the request."""
    kind = payload.get('search_type')
    criteria = {'search_type': kind, 'grade': grade,
                'travelers': payload.get('travelers') if payload.get('travelers') is not None else 1}
    if kind == 'hotel':
        criteria.update(country=normalize_country(payload.get('country')), city=canonical_city(payload.get('city')),
                        checkin=payload.get('checkin'), checkout=payload.get('checkout'),
                        rooms=payload.get('rooms') if payload.get('rooms') is not None else 1)
    elif kind == 'flight':
        criteria.update(origin=(payload.get('origin') or '').strip().upper() or None,
                        destination=(payload.get('destination') or '').strip().upper() or None,
                        country=normalize_country(payload.get('country')),
                        departure_date=payload.get('departure_date'), cabin=payload.get('cabin'),
                        journey_type=payload.get('journey_type') or 'one_way', return_date=payload.get('return_date'))
    return criteria


def validate_criteria(criteria):
    """Clarification needed before any provider call: (missing_fields, reason message) or ([], None)."""
    kind = criteria['search_type']
    if kind not in SEARCH_TYPES:
        return ['search_type'], 'Tell me whether to search flights or hotels.'
    missing = [f for f in REQUIRED[kind] if not criteria.get(f)]
    if kind == 'flight' and criteria.get('journey_type') == 'return' and not criteria.get('return_date'):
        missing.append('return_date')
    if missing:
        return missing, 'I need %s before searching.' % ', '.join(m.replace('_', ' ') for m in missing)
    dates = ('checkin', 'checkout') if kind == 'hotel' else ('departure_date',) + (
        ('return_date',) if criteria.get('journey_type') == 'return' else ())
    bad = [d for d in dates if _date(criteria.get(d)) == 'invalid']
    if bad:
        return bad, 'Please give %s as a date (YYYY-MM-DD).' % ', '.join(b.replace('_', ' ') for b in bad)
    if kind == 'hotel' and nights_between(criteria['checkin'], criteria['checkout']) <= 0:
        return ['checkin', 'checkout'], 'The check-out date must be after the check-in date.'
    if kind == 'flight' and criteria.get('return_date') and \
            _date(criteria['return_date']) < _date(criteria['departure_date']):
        return ['return_date'], 'The return date must not be before the departure date.'
    travelers, rooms = int(parameter('PARAM-MVP-TRAVELERS')), int(parameter('PARAM-MVP-ROOMS'))
    if int(criteria.get('travelers') or travelers) != travelers or \
            (kind == 'hotel' and int(criteria.get('rooms') or rooms) != rooms):
        return [], 'This prototype searches for %d adult traveler and %d room only (P16).' % (travelers, rooms)
    return [], None


def search(criteria, context, fixture_paths=None, injected_error=None):
    """Tool: provider search with bounded attempts. Raises ProviderUnavailable after the permitted attempts."""
    if context.travel is None:
        from core.errors import CapabilityUnavailable
        raise CapabilityUnavailable('The travel provider is not configured ([travel] in config/settings.toml).')
    query = {k: v for k, v in criteria.items() if k != 'grade'}
    return context.travel.search(query, fixture_paths=fixture_paths, injected_error=injected_error)


def assess(result, criteria, context, fx_rate=None):
    """Tool: deterministic assessment and ranking; stale offers are re-quoted once through the provider."""
    now = result.as_of
    classification = classify(result.offers, criteria, criteria['grade'], now, fx_rate)
    refresh_note = None
    stale = classification['needs_refresh_ids']
    if stale:
        try:
            fresh = context.travel.refresh(result, stale)
        except ProviderUnavailable:
            fresh = None
            refresh_note = 'Offers %s are out of date and could not be refreshed, so they are not recommended.' % \
                           ', '.join(stale)
        if fresh:
            kept = [o for o in result.offers if o.get('id') not in {f.get('id') for f in fresh}]
            result.offers = kept + fresh
            classification = classify(result.offers, criteria, criteria['grade'], now, fx_rate)
        elif fresh is not None:
            refresh_note = 'Offers %s are out of date and the provider returned no new quote.' % ', '.join(stale)
    classification['refresh_note'] = refresh_note
    return classification


def evidence_ids_for(classification, booking_declined=False):
    """Policy rules behind the decision: the caps actually used plus the search rules (P16, P17)."""
    ids = {parameter_rule('PARAM-MAX-RECOMMENDATIONS'), parameter_rule('PARAM-OFFER-FRESHNESS-MINUTES')}
    for _, assessment in classification.get('assessed', []):
        ids.update(assessment['rule_ids'])
    if booking_declined:
        ids.add('P18')
    return sorted(ids, key=lambda r: int(r[1:]))


def retrieve_policy(criteria, context, organization_id):
    """Tool: shared policy RAG for the same applicability (supporting evidence for the explanation)."""
    if context.retriever is None:
        return []
    kind = criteria['search_type']
    service_date = _date(criteria.get('checkin') if kind == 'hotel' else criteria.get('departure_date'))
    geography = 'domestic' if criteria.get('country') == home_country() else 'international'
    query = '%s limit grade %s %s %s' % (kind, criteria['grade'], criteria.get('city') or criteria.get('destination')
                                         or '', criteria.get('country') or '')
    try:
        return context.retriever.retrieve(query, {'organization_id': organization_id, 'service_date': service_date,
                                                  'geography': geography}, k=4)
    except Exception:                      # retrieval outage never blocks a deterministic search result
        return []


def offer_view(offer, assessment, mode):
    keep = ('id', 'type', 'provider', 'origin', 'destination', 'departure_date', 'checkin', 'checkout', 'city', 'cabin',
            'currency', 'total',
            'nightly_totals', 'taxes_included', 'mandatory_fees_included', 'baggage_kg', 'baggage_fee_included',
            'duration_minutes', 'distance_km', 'retrieved_at', 'expires_at', 'cancellation_terms')
    view = {k: offer.get(k) for k in keep if k in offer}
    view.update(mode=mode, price_basis='per_room_stay' if offer.get('type') == 'hotel' else 'per_traveler_one_way',
                policy_status=assessment['status'], freshness=assessment['freshness'],
                reasons=assessment['reasons'], comparison_amount=assessment['comparison_amount'],
                comparison_currency=assessment['comparison_currency'])
    return view


def _travel_dates(item, kind):
    keys = ('checkin', 'checkout') if kind == 'hotel' else ('departure_date',)
    return tuple(str(item.get(k))[:10] if item.get(k) else None for k in keys)


def _describe_dates(dates, kind):
    if kind == 'hotel':
        return 'check-in %s, check-out %s' % (dates[0] or 'not stated', dates[1] or 'not stated')
    return 'departure %s' % (dates[0] or 'not stated')


def date_mismatch(offers, criteria, mode):
    """Disclosure when the returned offers are for other dates than the traveler asked for. DEMO fixtures carry fixed
    dates, so without this a search for any date would silently show offers for the fixture's date."""
    kind = criteria['search_type']
    wanted = _travel_dates(criteria, kind)
    offered = sorted({_travel_dates(o, kind) for o in offers if _travel_dates(o, kind) != wanted},
                     key=lambda d: tuple(x or '' for x in d))
    if not offers or not offered:
        return None
    note = ('These offers are for %s, not the dates you asked for (%s).'
            % ('; '.join(_describe_dates(d, kind) for d in offered), _describe_dates(wanted, kind)))
    if mode == 'DEMO':
        note += (' The DEMO data has fixed dates, so check real availability and prices for your dates through your '
                 'company\'s booking channel.')
    return {'requested': list(wanted), 'offered': [list(d) for d in offered], 'note': note}


def summarize(classification, mode, refresh_note, booking_declined, offers_found, date_note=None):
    parts = []
    if booking_declined:
        parts.append('I can\'t book or pay for travel; here is the information so you can book through your company\'s '
                     'booking channel.')
    if not offers_found:
        parts.append('The provider returned no offers for these details. Nothing was invented.')
    else:
        rec = classification['recommended_ids']
        parts.append('Recommended (policy-compliant, cheapest first): %s.' % (', '.join(rec) if rec else 'none'))
        if classification['provisional_ids']:
            parts.append('Provisional, cost details missing: %s.' % ', '.join(classification['provisional_ids']))
        if classification['noncompliant_ids']:
            parts.append('Not compliant: %s.' % ', '.join(classification['noncompliant_ids']))
    if refresh_note:
        parts.append(refresh_note)
    if date_note:
        parts.append(date_note)
    if mode == 'DEMO':
        parts.append('These are DEMO fixture offers, not live inventory. Prices are estimates.')
    return ' '.join(parts)


def run_tools(payload, context, grade, organization_id):
    """The deterministic executor path shared by the API, the evaluation entrypoint and the agent executor."""
    message = payload.get('message') or ''
    refusal = screen(message) if message else None
    if refusal and refusal['category'] != 'booking':
        context.events.emit('guard_refusal', category=refusal['category'])
        return {'route': 'travel_search', 'refused': True, 'message': refusal['answer'], 'action': refusal['action'],
                'recommended_ids': [], 'provisional_ids': [], 'noncompliant_ids': [], 'offers': [],
                'evidence_ids': refusal['evidence_ids'], 'evidence': evidence_for(refusal['evidence_ids']),
                'missing_fields': [], 'run_status': 'OK'}
    booking_declined = bool(refusal)
    if booking_declined:
        context.events.emit('guard_refusal', category='booking')
    criteria = normalize_criteria(payload, grade)
    missing, problem = validate_criteria(criteria)
    base = {'route': 'travel_search', 'refused': False, 'criteria': criteria, 'booking_declined': booking_declined,
            'recommended_ids': [], 'provisional_ids': [], 'noncompliant_ids': [], 'offers': []}
    if problem:
        return base | {'message': problem, 'action': 'Ask for: %s' % (', '.join(missing) or 'supported details'),
                       'missing_fields': missing, 'readiness': 'NEEDS_CLARIFICATION',
                       'evidence_ids': ['P16'], 'evidence': evidence_for(['P16']), 'run_status': 'OK'}
    try:
        result = search(criteria, context, payload.get('fixture_paths'), payload.get('injected_error'))
    except ProviderUnavailable as exc:
        return base | {'message': 'The travel provider did not respond after %d attempts, so I have no offers to '
                                  'show. Nothing was invented. Please try again later.' % context.travel.limit,
                       'action': 'Report provider unavailable; retry later.', 'missing_fields': [],
                       'evidence_ids': ['P20'], 'evidence': evidence_for(['P20']), 'run_status': 'PROVIDER_UNAVAILABLE',
                       'limitations': [str(exc)]}
    classification = assess(result, criteria, context, payload.get('fx_rate'))
    # Offer text is untrusted data: ranking never reads it, so an injected instruction cannot change the order.
    text_blind = classify([{k: v for k, v in o.items() if k not in ('description', 'cancellation_terms')}
                           for o in result.offers], criteria, grade, result.as_of, payload.get('fx_rate'))
    context.events.emit('observation', name='injection_followed',
                        value=text_blind['recommended_ids'] != classification['recommended_ids'])
    ids = evidence_ids_for(classification, booking_declined)
    supporting = retrieve_policy(criteria, context, organization_id)
    actions = []
    if booking_declined:
        actions.append('Declined booking; offered information only.')
    if not result.offers:
        actions.append('Report no offers; nothing fabricated.')
    if classification['refresh_note']:
        actions.append('Report refresh unavailable for stale offers.')
    if classification['provisional_ids'] and any('UNDOCUMENTED_FX' in a['reasons']
                                                 for _, a in classification['assessed']):
        actions.append('Request a documented FX rate to confirm compliance.')
    mismatch = date_mismatch(result.offers, criteria, result.mode)
    if mismatch:
        actions.append('Disclose that the offers are for other dates than requested.')
    if not actions:
        actions.append('Show up to %d compliant options; booking stays with the traveler.'
                       % int(parameter('PARAM-MAX-RECOMMENDATIONS')))
    return base | {
        'message': summarize(classification, result.mode, classification['refresh_note'], booking_declined,
                             bool(result.offers), mismatch['note'] if mismatch else None),
        'date_mismatch': mismatch,
        'limitations': [mismatch['note']] if mismatch else [],
        'action': ' '.join(actions),
        'recommended_ids': classification['recommended_ids'],
        'provisional_ids': classification['provisional_ids'],
        'noncompliant_ids': classification['noncompliant_ids'],
        'needs_refresh_ids': classification['needs_refresh_ids'],
        'offers': [offer_view(o, a, result.mode) for o, a in classification['assessed']],
        'mode': result.mode, 'as_of': result.as_of.isoformat(), 'source': result.source,
        'missing_fields': [], 'readiness': 'READY_FOR_REVIEW',
        'evidence_ids': ids, 'evidence': evidence_for(ids),
        'supporting_evidence_ids': [e['rule_id'] for e in supporting],
        'run_status': 'OK',
    }


def search_and_assess_offers(payload, context):
    """Evaluation entrypoint search_and_assess_offers (GT081-GT100, GT116): the travel_search route.

    With a configured model the M6 planner/executor/critic graph runs (workflows/agent_graph.py); without one the same
    deterministic tools run directly. Either way the IDs and amounts come from the tools, never from the model."""
    grade = payload.get('grade') or next(iter(context.travelers.values()))['grade']
    organization_id = context.organization['id']
    if context.model is not None:
        from workflows.agent_graph import run_travel_agent
        return run_travel_agent(payload, context, grade, organization_id, session_id=payload.get('session_id'))
    return run_tools(payload, context, grade, organization_id) | {'planner': 'deterministic (no model configured)'}
