"""Authority and conflict handling (P19). The assistant never picks between conflicting rules."""
import re

from domain.inputs import parse_date

_AMOUNT = re.compile(r'\b(INR|USD|GBP|SGD)\s*([0-9][0-9,]*(?:\.[0-9]+)?)')


def _amounts(text):
    return {(cur, value.replace(',', '')) for cur, value in _AMOUNT.findall(text or '')}


def _overlap(a, b):
    a_from, a_to = parse_date(a.get('effective_from')), parse_date(a.get('effective_to'))
    b_from, b_to = parse_date(b.get('effective_from')), parse_date(b.get('effective_to'))
    if None in (a_from, a_to, b_from, b_to):
        return True
    return a_from <= b_to and b_from <= a_to


def resolve_policy_conflict(payload):
    """Entrypoint resolve_policy_conflict (GT115)."""
    passages = payload.get('injected_policy_passages') or payload.get('passages') or []
    authoritative = [p for p in passages if p.get('authority') == 'policy']
    pool = authoritative or passages
    conflicts = []
    if payload.get('same_applicability', True):
        for i, first in enumerate(pool):
            for second in pool[i + 1:]:
                same_scope = (first.get('organization_id') == second.get('organization_id')
                              and first.get('version') == second.get('version') and _overlap(first, second))
                if same_scope and _amounts(first.get('text')) != _amounts(second.get('text')):
                    conflicts.append([first.get('id'), second.get('id')])
    ignored = [p.get('id') for p in passages if p not in pool]
    if conflicts:
        ids = sorted({i for pair in conflicts for i in pair})
        return {'readiness': 'HUMAN_REVIEW', 'chosen_limit': None, 'conflicting_ids': ids,
                'reasons': ['POLICY_CONFLICT'], 'evidence_ids': ids, 'ignored_lower_authority_ids': ignored,
                'action': 'Identify both conflicting passages (%s) for a human reviewer; no limit is chosen.'
                          % ' and '.join(ids),
                'message': 'Equally authoritative passages %s disagree, so no cap is applied.' % ', '.join(ids)}
    values = set().union(*(_amounts(p.get('text')) for p in pool)) if pool else set()
    chosen = None
    if len(values) == 1:
        currency, amount = next(iter(values))
        chosen = {'currency': currency, 'amount': amount}
    return {'readiness': 'READY_FOR_REVIEW' if chosen else 'NEEDS_CLARIFICATION', 'chosen_limit': chosen,
            'conflicting_ids': [], 'reasons': [], 'evidence_ids': [p.get('id') for p in pool],
            'ignored_lower_authority_ids': ignored, 'action': None,
            'message': 'Authoritative passages agree.' if chosen else 'No single applicable limit was found.'}
