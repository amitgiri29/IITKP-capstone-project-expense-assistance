"""Download the Government of India reference orders listed in corpus/india_references/sources.json.

Each file is fetched from its official URL, checked to be a PDF, and inspected with pypdf for a text layer
(OCR is not permitted, so scanned orders cannot be ingested). Results go to
corpus/india_references/fetch_report.json. Already-downloaded files are skipped. Run from the project folder:

    .venv\\Scripts\\python.exe -m scripts.fetch_india_references                       (text-layer orders only)
    .venv\\Scripts\\python.exe -m scripts.fetch_india_references --include-excluded    (also the excluded scans)
"""
import hashlib
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / 'corpus' / 'india_references'
PDF_DIR = FOLDER / 'pdf'
USER_AGENT = 'Mozilla/5.0 (compatible; capstone-corpus-fetch/1.0)'   # generic; no personal details
MAX_BYTES = 15 * 1024 * 1024
MIN_TEXT_CHARS = 200          # below this a PDF is treated as a scan without a usable text layer


def fetch(url, attempts=3):
    """Download with certificate verification ON. Uses the operating system's trust store (truststore),
    because some government sites send an incomplete certificate chain that browsers repair but Python
    does not. Transient resets are retried."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('larger than %d MB' % (MAX_BYTES // 1024 // 1024))
            return data
        except (OSError, ValueError) as exc:          # URLError, SSL EOF, connection reset
            last = exc
            if isinstance(exc, ValueError):
                break
            time.sleep(3 * attempt)
    raise last


def inspect(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    texts = [(page.extract_text() or '') for page in reader.pages]
    chars = sum(len(t.strip()) for t in texts)
    return {'pages': len(texts), 'text_chars': chars, 'text_layer': chars >= MIN_TEXT_CHARS,
            'first_line': next((line.strip() for t in texts for line in t.splitlines() if line.strip()), '')[:120]}


def main():
    try:
        import truststore                       # in requirements.lock.txt
        truststore.inject_into_ssl()
    except ImportError:
        pass
    sources = json.loads((FOLDER / 'sources.json').read_text(encoding='utf-8'))
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    report = []
    include_excluded = '--include-excluded' in sys.argv
    for doc in sources['documents']:
        if doc.get('excluded') and not include_excluded:
            print('%-4s %-11s %-22s %s' % (doc['id'], doc['date'], 'skipped (excluded)', doc.get('excluded_reason', '')))
            continue
        target = PDF_DIR / ('%s_%s.pdf' % (doc['id'], doc['date']))
        entry = {'id': doc['id'], 'file': target.relative_to(ROOT).as_posix(), 'url': doc['url']}
        try:
            if target.exists():
                data = target.read_bytes()
                entry['downloaded'] = 'already present'
            else:
                data = fetch(doc['url'])
                if not data.startswith(b'%PDF'):
                    raise ValueError('not a PDF (starts with %r)' % data[:15])
                target.write_bytes(data)
                entry['downloaded'] = 'ok'
                time.sleep(1)                                    # be polite to the government servers
            entry.update({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, **inspect(data))
        except Exception as exc:                                 # report and continue with the next file
            entry.update({'downloaded': 'FAILED', 'error': '%s: %s' % (type(exc).__name__, str(exc)[:200])})
        report.append(entry)
        status = entry['downloaded'] if entry['downloaded'] == 'FAILED' else (
            'text layer' if entry.get('text_layer') else 'SCAN (no text layer)')
        print('%-4s %-11s %-22s %s' % (doc['id'], doc['date'], status,
                                        entry.get('error') or '%d pages, %d chars' % (entry['pages'],
                                                                                      entry['text_chars'])))
    (FOLDER / 'fetch_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                                              encoding='utf-8')
    ok = [e for e in report if e.get('text_layer')]
    scans = [e['id'] for e in report if e.get('downloaded') != 'FAILED' and not e.get('text_layer')]
    failed = [e['id'] for e in report if e.get('downloaded') == 'FAILED']
    print('\n%d with a text layer | %d scans: %s | %d failed: %s' % (len(ok), len(scans), scans or '-',
                                                                     len(failed), failed or '-'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
