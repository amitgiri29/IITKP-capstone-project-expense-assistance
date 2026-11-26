"""Deterministic request routing (IMPLEMENTATION_CONTRACT router). The model never chooses the route.

Decision order, first match wins:
1. an attached image or a pending receipt confirmation -> receipt_review
2. a travel search intent with a search type, route or destination plus dates -> travel_search
3. a correction or follow-up that invalidates stored results -> the route that produced them
4. equally authoritative conflicting rules for the asked applicability -> escalate the current route (see note below)
5. otherwise -> policy_simple
"""
from domain.data import reference_data

ROUTES = tuple(reference_data()['routes'])


def _has_travel_details(request):
    kind = request.get('search_type')
    if kind == 'flight':
        return bool(request.get('origin') or request.get('destination')) and bool(request.get('departure_date'))
    if kind == 'hotel':
        return bool(request.get('city') or request.get('country')) and bool(request.get('checkin'))
    return False


def route(request, session_state=None):
    """Return (route, reason). Pure function of the validated request and stored session state."""
    state = session_state or {}
    if request.get('images') or state.get('pending_receipt_confirmation'):
        return 'receipt_review', 'image attached or receipt confirmation pending'
    if request.get('search_type') in ('flight', 'hotel') and _has_travel_details(request):
        return 'travel_search', 'travel search with route or destination and dates'
    if request.get('search_type') in ('flight', 'hotel'):
        return 'travel_search', 'travel search intent; the executor asks for the missing details'
    if request.get('correction_of') and state.get('last_route') in ROUTES:
        return state['last_route'], 'correction invalidates the stored %s result' % state['last_route']
    return 'policy_simple', 'policy question'


# Condition 4 (escalation on equally authoritative conflicting rules) is decided after retrieval by
# domain.policy_rules.resolve_policy_conflict for passages that share one applicability; it is not wired into the
# policy_simple route yet, because comparing amounts across different rules (P02 vs P03) would flag false conflicts.
