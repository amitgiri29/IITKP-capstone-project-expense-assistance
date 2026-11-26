"""Resolve rule IDs to Evidence records (schemas/domain.schema.json Evidence) from policy_sources only."""
from domain.data import policy, _load


def evidence_for(rule_ids):
    rules = {r['id']: r for r in policy()['rules']}
    documents = {d['rule_id']: d for d in _load('corpus_manifest.json')['documents']}
    records = []
    for rule_id in rule_ids:
        if rule_id not in rules:
            continue
        document = documents.get(rule_id, {})
        records.append({'rule_id': rule_id, 'document_id': document.get('document_id', rule_id),
                        'version': document.get('version', policy()['version']),
                        'section': document.get('section', rules[rule_id]['title']),
                        'text': rules[rule_id]['text'],
                        'source_location': 'policy_sources/%s' % document.get('path', rule_id + '.txt')})
    return records
