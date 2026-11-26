"""SQLite application store. One API process owns the database (DEPLOYMENT_CONTRACT)."""
import hashlib
import json
import secrets
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    traveler_id TEXT NOT NULL,
    grade TEXT NOT NULL,
    token_sha256 TEXT UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    image_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL,
    filename TEXT,
    mime TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    path TEXT,
    merchant TEXT,
    amount TEXT,
    extraction_json TEXT,
    confirmed_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_documents (
    document_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    authority TEXT NOT NULL,
    geography TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT NOT NULL,
    filename TEXT,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, sha256)
);
CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES policy_documents(document_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding_cache (
    model_key TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model_key, text_sha256)
);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def token_digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = self.data_dir / 'uploads'
        self.upload_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / 'app.sqlite3', check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('PRAGMA foreign_keys = ON')
        self._db.execute('PRAGMA journal_mode = WAL')
        self._db.executescript(SCHEMA)
        self._migrate('sessions', {'role': "TEXT NOT NULL DEFAULT 'employee'"})
        self._migrate('policy_documents', {'file_type': "TEXT NOT NULL DEFAULT 'text'", 'page_count': 'INTEGER'})
        self._migrate('policy_chunks', {'page': 'INTEGER', 'start_index': 'INTEGER'})

    def _migrate(self, table, columns):
        """Forward migration: add columns that older stores lack."""
        existing = {row[1] for row in self._db.execute('PRAGMA table_info(%s)' % table)}
        for name, definition in columns.items():
            if name not in existing:
                self._db.execute('ALTER TABLE %s ADD COLUMN %s %s' % (table, name, definition))

    def _run(self, sql, params=()):
        with self._lock, self._db:
            return self._db.execute(sql, params).fetchall()

    # sessions -----------------------------------------------------------
    def create_session(self, organization_id, traveler_id, grade, now, ttl_hours, session_id=None, role='employee'):
        token = secrets.token_urlsafe(32)
        session_id = session_id or 'S-' + uuid.uuid4().hex[:16]
        expires = now + timedelta(hours=ttl_hours)
        self._run('INSERT INTO sessions (session_id, organization_id, traveler_id, grade, token_sha256, created_at, '
                  'expires_at, role) VALUES (?,?,?,?,?,?,?,?)',
                  (session_id, organization_id, traveler_id, grade, token_digest(token), iso(now), iso(expires), role))
        return token, self.get_session(session_id)

    def get_session(self, session_id):
        rows = self._run('SELECT * FROM sessions WHERE session_id = ?', (session_id,))
        return dict(rows[0]) if rows else None

    def session_for_token(self, token):
        rows = self._run('SELECT * FROM sessions WHERE token_sha256 = ?', (token_digest(token),))
        return dict(rows[0]) if rows else None

    def delete_session(self, session_id):
        receipts = self.list_receipts(session_id)
        self._run('DELETE FROM sessions WHERE session_id = ?', (session_id,))
        shutil.rmtree(self.upload_dir / session_id, ignore_errors=True)
        return len(receipts)

    # receipts ------------------------------------------------------------
    def add_receipt(self, session_id, organization_id, filename, mime, data, now, image_id=None,
                    merchant=None, amount=None):
        image_id = image_id or 'IMG-' + uuid.uuid4().hex[:16]
        path = None
        if data is not None:
            folder = self.upload_dir / session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (image_id + ('.png' if mime == 'image/png' else '.jpg'))
            path.write_bytes(data)
        self._run('INSERT INTO receipts (image_id, session_id, organization_id, filename, mime, size_bytes, sha256, '
                  'path, merchant, amount, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (image_id, session_id, organization_id, filename, mime, len(data) if data else None,
                   hashlib.sha256(data).hexdigest() if data else None, str(path) if path else None,
                   merchant, amount, iso(now)))
        return self.get_receipt(image_id)

    def get_receipt(self, image_id):
        rows = self._run('SELECT * FROM receipts WHERE image_id = ?', (image_id,))
        return dict(rows[0]) if rows else None

    def list_receipts(self, session_id):
        return [dict(r) for r in self._run('SELECT * FROM receipts WHERE session_id = ? ORDER BY created_at, image_id',
                                           (session_id,))]

    def update_receipt(self, image_id, extraction=None, confirmed=None):
        if extraction is not None:
            self._run('UPDATE receipts SET extraction_json = ? WHERE image_id = ?', (json.dumps(extraction), image_id))
        if confirmed is not None:
            self._run('UPDATE receipts SET confirmed_json = ? WHERE image_id = ?', (json.dumps(confirmed), image_id))
        return self.get_receipt(image_id)

    def delete_receipt(self, image_id):
        receipt = self.get_receipt(image_id)
        if receipt and receipt['path']:
            Path(receipt['path']).unlink(missing_ok=True)
        self._run('DELETE FROM receipts WHERE image_id = ?', (image_id,))
        if receipt:
            self._run('DELETE FROM assessments WHERE session_id = ?', (receipt['session_id'],))
        return receipt

    # assessments -----------------------------------------------------------
    def save_assessment(self, session_id, request, result, now):
        assessment_id = 'A-' + uuid.uuid4().hex[:16]
        self._run('INSERT INTO assessments VALUES (?,?,?,?,?)',
                  (assessment_id, session_id, json.dumps(request, default=str), json.dumps(result), iso(now)))
        return assessment_id

    def list_assessments(self, session_id):
        return [{'assessment_id': r['assessment_id'], 'created_at': r['created_at'],
                 'result': json.loads(r['result_json'])}
                for r in self._run('SELECT * FROM assessments WHERE session_id = ? ORDER BY created_at', (session_id,))]

    # policy library -----------------------------------------------------------
    def add_policy_document(self, organization_id, meta, chunks, data, uploaded_by, now):
        """chunks: iterable of dicts with section, text, page and start_index."""
        document_id = 'LIB-' + uuid.uuid4().hex[:8].upper()
        digest = hashlib.sha256(data).hexdigest()
        chunks = list(chunks)
        with self._lock, self._db:
            self._db.execute('INSERT INTO policy_documents (document_id, organization_id, title, version, authority, '
                             'geography, effective_from, effective_to, filename, sha256, size_bytes, chunk_count, '
                             'uploaded_by, created_at, file_type, page_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (document_id, organization_id, meta['title'], meta['version'], meta['authority'],
                              meta['geography'], meta['effective_from'], meta['effective_to'], meta.get('filename'),
                              digest, len(data), len(chunks), uploaded_by, iso(now), meta.get('file_type', 'text'),
                              meta.get('page_count')))
            for position, chunk in enumerate(chunks, start=1):
                self._db.execute('INSERT INTO policy_chunks (chunk_id, document_id, position, section, text, page, '
                                 'start_index) VALUES (?,?,?,?,?,?,?)',
                                 ('%s-%02d' % (document_id, position), document_id, position, chunk['section'],
                                  chunk['text'], chunk.get('page'), chunk.get('start_index')))
        return self.get_policy_document(document_id)

    def policy_document_exists(self, organization_id, data):
        return bool(self._run('SELECT 1 FROM policy_documents WHERE organization_id = ? AND sha256 = ?',
                              (organization_id, hashlib.sha256(data).hexdigest())))

    def get_policy_document(self, document_id):
        rows = self._run('SELECT * FROM policy_documents WHERE document_id = ?', (document_id,))
        return dict(rows[0]) if rows else None

    def list_policy_documents(self, organization_id):
        return [dict(r) for r in self._run('SELECT * FROM policy_documents WHERE organization_id = ? '
                                           'ORDER BY created_at, document_id', (organization_id,))]

    def library_chunks(self):
        return [dict(r) for r in self._run(
            'SELECT c.chunk_id, c.position, c.section, c.text, c.page, c.start_index, d.document_id, d.organization_id, '
            'd.title, d.version, d.authority, d.geography, d.effective_from, d.effective_to, d.file_type FROM policy_chunks c '
            'JOIN policy_documents d ON d.document_id = c.document_id ORDER BY d.created_at, c.position')]

    def delete_policy_document(self, document_id):
        document = self.get_policy_document(document_id)
        self._run('DELETE FROM policy_documents WHERE document_id = ?', (document_id,))
        return document

    # embedding cache ------------------------------------------------------------
    def get_vectors(self, model_key, digests):
        found = {}
        digests = list(digests)
        for start in range(0, len(digests), 500):
            batch = digests[start:start + 500]
            rows = self._run('SELECT text_sha256, vector FROM embedding_cache WHERE model_key = ? AND text_sha256 IN (%s)'
                             % ','.join('?' * len(batch)), (model_key, *batch))
            found.update({r['text_sha256']: r['vector'] for r in rows})
        return found

    def put_vectors(self, model_key, vectors):
        with self._lock, self._db:
            self._db.executemany('INSERT OR REPLACE INTO embedding_cache VALUES (?,?,?)',
                                 [(model_key, digest, blob) for digest, blob in vectors.items()])

    def count_vectors(self, model_key):
        return self._run('SELECT COUNT(*) AS n FROM embedding_cache WHERE model_key = ?', (model_key,))[0]['n']

    # retention -------------------------------------------------------------
    def purge_expired_uploads(self, cutoff):
        expired = [dict(r) for r in self._run('SELECT * FROM receipts WHERE created_at < ? AND path IS NOT NULL',
                                              (iso(cutoff),))]
        for receipt in expired:
            Path(receipt['path']).unlink(missing_ok=True)
            self._run('UPDATE receipts SET path = NULL WHERE image_id = ?', (receipt['image_id'],))
        return len(expired)

    def close(self):
        self._db.close()


def utcnow():
    return datetime.now(timezone.utc)
