"""Citation validation and repair (FR08, AC14). Model-generated IDs are never trusted."""
import re
from datetime import date

from domain.registry import RegistryLookupError, resolve_cap
from retrieval.interpret import location

CITE = re.compile(r'\[([A-Z][0-9]{2}[A-Za-z0-9-]*)\]')
AMOUNT = re.compile(r'\b(INR|USD|GBP|SGD)\s*([0-9][0-9,]*(?:\.[0-9]+)?)')


def cited_ids(text):
    return list(dict.fromkeys(CITE.findall(text or '')))


def validate_and_repair_citations(payload, context):
    """Entrypoint validate_and_repair_citations (GT120). The repair text is an injected model output."""
    retrieved = list(payload.get('retrieved_ids') or [])
    draft_ids = cited_ids(payload.get('draft'))
    invalid = [i for i in draft_ids if i not in retrieved]
    context.events.emit('observation', name='invalid_citation_detected', value=bool(invalid))
    final_text = payload.get('draft', '')
    if invalid and payload.get('repair_output'):
        context.events.emit('format_repair', purpose='citation_repair')
        final_text = payload['repair_output']
    final_ids = [i for i in cited_ids(final_text) if i in retrieved]
    country, city = location(payload.get('city') or '')
    stated = AMOUNT.search(final_text)
    registry_limit, note = None, None
    try:
        cap = resolve_cap('hotel', country, city or payload.get('city'), payload.get('grade'),
                          date.fromisoformat(payload['service_date']) if payload.get('service_date') else
                          context.clock().date())
        registry_limit = cap.amount
        if stated and stated.group(1) == cap.currency and str(cap.amount) != stated.group(2).replace(',', '') \
                and float(cap.amount) != float(stated.group(2).replace(',', '')):
            note = 'Repaired text stated %s %s; the registry value is used.' % stated.groups()
    except RegistryLookupError as error:
        note = error.message
    return {'invalid_citation_ids': invalid, 'final_evidence_ids': final_ids,
            'final_limit_inr': str(registry_limit) if registry_limit is not None else None,
            'final_text': final_text, 'note': note, 'message': final_text, 'evidence_ids': final_ids}
