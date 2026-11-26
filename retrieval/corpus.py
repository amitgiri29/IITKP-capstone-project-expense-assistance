"""The searchable corpus as LangChain Documents: 20 core policy sections plus admin library chunks.

Core sections are loaded one Document per rule so rule IDs P01-P20 stay intact for citations and
golden evaluation. policy.json and the manifest supply metadata; nothing under tests/ is read.
"""
from langchain_core.documents import Document

from domain.data import POLICY_DIR, _load
from retrieval.loaders import TextLoader


# Library documents from another organisation are ingested under this title prefix (corpus/ingest_plan.json:
# "GoI reference (not SPARKS policy): ..."). They answer questions about Government of India rules only.
REFERENCE_PREFIX = 'GoI reference'


def is_reference(metadata):
    return metadata.get('origin') == 'library' and str(metadata.get('section') or '').startswith(REFERENCE_PREFIX)


def geography(section):
    lowered = section.lower()
    if lowered.startswith('domestic'):
        return 'domestic'
    if lowered.startswith('international'):
        return 'international'
    return 'general'


def core_documents():
    documents = []
    for entry in _load('corpus_manifest.json')['documents']:
        path = POLICY_DIR / entry['path']
        text = TextLoader(path.read_bytes(), entry['path']).load()[0].page_content.strip()
        documents.append(Document(id=entry['rule_id'], page_content=text, metadata={
            'rule_id': entry['rule_id'], 'document_id': entry['document_id'], 'version': entry['version'],
            'section': entry['section'], 'organization_id': entry['organization_id'], 'authority': entry['authority'],
            'effective_from': entry['effective_from'], 'effective_to': entry['effective_to'],
            'geography': geography(entry['section']), 'source_location': 'policy_sources/%s' % entry['path'],
            'origin': 'core', 'page': None}))
    return documents


def library_documents(rows):
    documents = []
    for row in rows:
        section = row['title'] if row['section'] in (None, '', row['title']) else '%s — %s' % (row['title'], row['section'])
        documents.append(Document(id=row['chunk_id'], page_content=row['text'], metadata={
            'rule_id': row['chunk_id'], 'document_id': row['document_id'], 'version': row['version'], 'section': section,
            'organization_id': row['organization_id'], 'authority': row['authority'],
            'effective_from': row['effective_from'], 'effective_to': row['effective_to'], 'geography': row['geography'],
            'source_location': 'policy_library/%s' % row['document_id'] + ('#page=%d' % row['page'] if row.get('page') else ''),
            'origin': 'library', 'page': row.get('page'), 'file_type': row.get('file_type')}))
    return documents


def evidence(document, score=None, match=None):
    m = document.metadata
    record = {'rule_id': m['rule_id'], 'document_id': m['document_id'], 'version': m['version'], 'section': m['section'],
              'text': document.page_content, 'source_location': m['source_location'], 'authority': m['authority'],
              'origin': m['origin']}
    if m.get('page'):
        record['page'] = m['page']
    if score is not None:
        record['score'] = round(float(score), 5)
    if match:
        record['match'] = match
    return record
