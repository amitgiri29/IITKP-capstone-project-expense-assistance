"""Ingest the documents in corpus/ingest_plan.json into the policy library.

Each file goes through the real POST /admin/policies route as the demo administrator, so parsing (LangChain loaders),
chunking (LangChain splitters), vectors and the duplicate check are exactly those of an upload in the UI. Documents that
are already in the library are skipped, so the script is safe to re-run. Writes to the app's data folder (runtime/).

    .venv\\Scripts\\python.exe -m scripts.ingest_documents            ingest the plan
    .venv\\Scripts\\python.exe -m scripts.ingest_documents --list     show what is in the library

Restart the API afterwards (run.bat) so a running app rebuilds its search index with the new documents.
"""
import json
import sys
from pathlib import Path

from api.main import local_client
from core.context import build_context

ROOT = Path(__file__).resolve().parent.parent
MIME = {'.pdf': 'application/pdf', '.md': 'text/markdown', '.txt': 'text/plain',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def polite(call):
    """Respect the API's per-session rate limit: on 429, wait the advertised time and try again."""
    import time
    for _ in range(5):
        response = call()
        if response.status_code != 429:
            return response
        wait = int(response.json().get('retry_after_seconds') or 10) + 1
        print('        (rate limit reached; waiting %d s)' % wait)
        time.sleep(wait)
    return response


def admin_headers(client, context):
    admin = next(t for t in context.travelers.values() if t.get('role') == 'admin')
    token = client.post('/sessions', json={'traveler_id': admin['traveler_id']}).json()['token']
    return {'Authorization': 'Bearer ' + token}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    plan = json.loads((ROOT / 'corpus' / 'ingest_plan.json').read_text(encoding='utf-8'))
    context = build_context(with_model=False)
    try:
        with local_client(context) as client:
            headers = admin_headers(client, context)
            if '--list' not in sys.argv:
                for doc in plan['documents']:
                    path = ROOT / doc['path']
                    fields = {k: doc[k] for k in ('title', 'authority', 'geography', 'version', 'effective_from',
                                                  'effective_to')}
                    response = polite(lambda: client.post('/admin/policies', headers=headers, data=fields, files={
                        'file': (path.name, path.read_bytes(), MIME.get(path.suffix.lower(), 'text/plain'))}))
                    body = response.json()
                    if response.status_code == 201:
                        print('ADDED   %-9s %-70s %2d sections, %d vectors' % (
                            body['document_id'], doc['title'][:70], body['chunk_count'], body.get('vectors_created', 0)))
                    elif 'already in the policy library' in body.get('message', ''):
                        print('SKIPPED %-9s %-70s already in the library' % ('', doc['title'][:70]))
                    else:
                        print('FAILED  %-9s %-70s %s %s' % ('', doc['title'][:70], response.status_code,
                                                             body.get('message')))
            library = polite(lambda: client.get('/policy/library', headers=headers)).json()
            print('\nLibrary: %d documents, %d searchable sections (core policy: 1 document, %d sections)' % (
                library['document_count'], library['section_count'], library['core'][0]['section_count']))
            for doc in library['library']:
                print('  %-9s %-72s %2d sections' % (doc['document_id'], doc['title'][:72], doc['chunk_count'] or 0))
            print('\nLeft for you to upload on Policy Documents:')
            for doc in plan['left_for_manual_upload']:
                print('  %s  (title "%s", authority %s, applies to %s)' % (doc['path'], doc['title'], doc['authority'],
                                                                           doc['geography']))
            print('Restart the API (run.bat) so the running app picks up the new documents.')
    finally:
        context.store.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
