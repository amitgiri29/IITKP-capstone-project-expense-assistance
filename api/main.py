"""FastAPI application.

Run locally:  python -m uvicorn api.main:app --port 8000
"""
import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.errors import ApiError, envelope, status_for
from api.security import ensure_owner, require_admin, session_from_request
from adapters.telemetry import Telemetry
from api.uploads import inspect_image, limits
from core.context import build_context, refresh_library
from core.redaction import redact
from domain.assessment import assess
from domain.data import ROOT, rule_registry
from domain.evidence import evidence_for
from domain.registry import review_status

APP_VERSION = '0.3.0'
log = logging.getLogger('expense_assistant.api')


def _operational_defaults():
    return json.loads((ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text())['operational_defaults']


class RateLimiter:
    """Sliding one-minute window per session (operational_defaults in IMPLEMENTATION_CONTRACT.json)."""

    def __init__(self, limit, window_seconds=60):
        self.limit, self.window = limit, window_seconds
        self._hits, self._lock = {}, threading.Lock()

    def check(self, key):
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, int(self.window - (now - hits[0])) + 1)
                raise ApiError('RATE_LIMITED', 'Too many requests for this session. Try again shortly.',
                               retry_after_seconds=retry)
            hits.append(now)


# ---- request models ---------------------------------------------------------
class SessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    traveler_id: str = Field(min_length=1, max_length=64)


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trip_start: Optional[date] = None
    trip_end: Optional[date] = None
    submitted_on: Optional[date] = None
    budget_inr: Optional[Decimal] = None
    coverage_complete: bool = True
    user_confirmed: bool = False
    required_documents_present: bool = False


class LineIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    line_id: Optional[str] = None
    category: Literal['hotel', 'flight', 'local_transport', 'out_of_scope']
    country: Optional[str] = None
    city: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[Decimal] = None
    excluded_amount: Decimal = Decimal(0)
    service_date: Optional[date] = None
    transaction_date: Optional[date] = None
    fx_rate: Optional[Decimal] = None
    fx_reference: Optional[str] = None
    journey_id: Optional[str] = None
    receipt_id: Optional[str] = None
    cabin: Optional[str] = None
    business_purpose: bool = True


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim: ClaimIn
    lines: list[LineIn] = Field(min_length=1, max_length=50)


class ChatIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=4000)
    applicability: Optional[dict] = None


class TravelSearchIn(BaseModel):
    """Search criteria from the UI or a client. No grade (server-held) and no test hooks."""
    model_config = ConfigDict(extra='forbid')
    search_type: Literal['flight', 'hotel']
    country: Optional[str] = Field(default=None, max_length=8)
    city: Optional[str] = Field(default=None, max_length=80)
    checkin: Optional[date] = None
    checkout: Optional[date] = None
    rooms: Optional[int] = Field(default=None, ge=1, le=9)
    travelers: Optional[int] = Field(default=None, ge=1, le=9)
    origin: Optional[str] = Field(default=None, max_length=8)
    destination: Optional[str] = Field(default=None, max_length=8)
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    journey_type: Optional[Literal['one_way', 'return']] = None
    cabin: Optional[Literal['economy', 'premium_economy', 'business', 'first']] = None
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)
    venue: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=500)
    message: Optional[str] = Field(default=None, max_length=2000)


class ExcludedItemIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(default='', max_length=200)
    amount: Optional[Decimal] = Field(default=None, ge=0)


class ReceiptFieldsIn(BaseModel):
    """Receipt fields as the traveler confirmed or corrected them."""
    model_config = ConfigDict(extra='forbid')
    merchant: Optional[str] = Field(default=None, max_length=200)
    receipt_id: Optional[str] = Field(default=None, max_length=100)
    category: Literal['hotel', 'flight', 'local_transport', 'out_of_scope']
    country: Optional[str] = Field(default=None, max_length=8)
    city: Optional[str] = Field(default=None, max_length=80)
    currency: Optional[str] = Field(default=None, max_length=3)
    service_date: Optional[date] = None
    checkin: Optional[date] = None
    checkout: Optional[date] = None
    nights: Optional[int] = Field(default=None, ge=1, le=60)
    nightly_amounts: Optional[list[Decimal]] = Field(default=None, max_length=60)
    payable_total: Optional[Decimal] = Field(default=None, ge=0)
    taxes_included: Optional[bool] = None
    excluded_items: list[ExcludedItemIn] = Field(default_factory=list, max_length=30)
    uncertainties: list[str] = Field(default_factory=list, max_length=30)   # echoed from extraction; not calculated
    user_confirmed: bool = False


class ReceiptClaimIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    budget_inr: Optional[Decimal] = Field(default=None, ge=0)
    trip_start: Optional[date] = None
    trip_end: Optional[date] = None
    submitted_on: Optional[date] = None
    coverage_complete: bool = True
    business_purpose: bool = True
    boarding_pass_present: Optional[bool] = None
    required_documents_present: Optional[bool] = None
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)
    fx_reference: Optional[str] = Field(default=None, max_length=40)


class ReceiptAssessIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fields: ReceiptFieldsIn
    claim: ReceiptClaimIn = Field(default_factory=ReceiptClaimIn)


def _plain(model):
    return json.loads(model.model_dump_json())


def create_app(context=None):
    context = context or build_context()
    limiter = RateLimiter(_operational_defaults()['rate_limit_requests_per_session_per_minute'])
    app = FastAPI(title='Expense Policy Assistant API', version=APP_VERSION,
                  description='Fictional SPARKS AI Lab policy. Search and review only; no booking.')
    app.state.context = context
    telemetry = Telemetry(context)

    def error_response(request, code, message, field=None, retry_after=None, status=None):
        body = envelope(code, message, getattr(request.state, 'request_id', None), field, retry_after)
        headers = {'Retry-After': str(retry_after)} if retry_after else None
        return JSONResponse(redact(body, context.secrets()), status_code=status or status_for(code), headers=headers)

    @app.middleware('http')
    async def instrument(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # never leak internals to the client; log them locally, redacted
            log.exception('request %s failed', request.state.request_id)
            context.events.emit('server_error', path=request.url.path, error=type(exc).__name__,
                                detail=redact(str(exc), context.secrets()))
            response = error_response(request, 'INTERNAL_ERROR', 'Unexpected server error.')
        response.headers['X-Request-ID'] = request.state.request_id
        duration = round((time.perf_counter() - started) * 1000, 2)
        context.events.emit('http_response', method=request.method, path=request.url.path,
                            status=response.status_code, duration_ms=duration)
        telemetry.record('http_request', request_id=request.state.request_id, method=request.method,
                         route=request.url.path, status=response.status_code, duration_ms=duration)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error_response(request, exc.code, exc.message, exc.field, exc.retry_after_seconds)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        first = exc.errors()[0] if exc.errors() else {}
        pointer = '/' + '/'.join(str(p) for p in first.get('loc', ())[1:]) if first.get('loc') else None
        return error_response(request, 'VALIDATION_FAILED', first.get('msg', 'Invalid request.'), pointer)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        code = 'NOT_FOUND' if exc.status_code == 404 else 'INVALID_REQUEST'
        return error_response(request, code, str(exc.detail), status=exc.status_code)

    def current_session(request: Request):
        session = session_from_request(request, context)
        limiter.check(session['session_id'])
        return session

    # ---- operational -------------------------------------------------------
    liveness = {'checked': 0.0, 'result': (True, None)}

    def model_liveness(ttl_seconds=30):
        """Hosted-model reachability, probed at most once per ttl so /ready stays cheap."""
        now = time.monotonic()
        if not liveness['checked'] or now - liveness['checked'] >= ttl_seconds:
            liveness['result'] = context.model.reachable()
            liveness['checked'] = now
        return liveness['result']

    @app.get('/health')
    def health():
        return {'status': 'ok', 'app_version': APP_VERSION, 'commit': None}

    @app.get('/ready')
    def ready():
        components = {}
        try:
            rule_registry()
            components['rule_registry'] = {'ok': True, 'review_status': review_status()}
        except Exception:
            components['rule_registry'] = {'ok': False}
        try:
            context.store.get_session('__readiness__')
            components['store'] = {'ok': True}
        except Exception:
            components['store'] = {'ok': False}
        model = context.settings.model
        if model.provider == 'claude_code':
            credentials = 'claude_code_login' if context.model is not None else 'cli_not_found'
        else:
            credentials = 'present' if context.settings.secret(model.api_key_env) else 'missing'
        components['model'] = {'ok': context.model is not None, 'provider': model.provider,
                               'model_id': model.model_id, 'credentials': credentials}
        if context.model is not None and hasattr(context.model, 'reachable'):
            reachable, error = model_liveness()
            components['model'].update(ok=reachable, reachable=reachable, error=error)
        travel = context.settings.travel
        components['travel'] = {'ok': context.travel is not None, 'provider': travel.provider}
        retriever = getattr(context, 'retriever', None)
        components['policy_index'] = {'ok': retriever is not None,
                                      'sections': len(retriever.documents) if retriever else 0}
        embeddings = context.settings.embeddings
        components['embeddings'] = {'ok': embeddings.provider == 'none' or bool(retriever and retriever.vectors_active),
                                    'provider': embeddings.provider, 'model_id': embeddings.model_id or None,
                                    'retrieval_mode': retriever.mode if retriever else None,
                                    'vectors': retriever.vector_count() if retriever else 0,
                                    'error': retriever.vector_error if retriever else None,
                                    'active_model': retriever.embedding_model if retriever else None,
                                    'fallback_reason': getattr(getattr(retriever, 'embeddings', None),
                                                               'fallback_reason', None)}
        components['telemetry'] = {'ok': True, 'status': telemetry.status}
        failing = [name for name, state in components.items() if not state['ok']]
        body = {'status': 'ready' if not failing else 'not_ready', 'failing': failing, 'components': components}
        return JSONResponse(body, status_code=200 if not failing else 503)

    # ---- sessions -----------------------------------------------------------
    def _person(profile):
        """Public directory fields for a traveler (synthetic). Grade is added only inside an authenticated session."""
        return {'traveler_id': profile['traveler_id'], 'display_name': profile.get('display_name'),
                'job_title': profile.get('job_title'), 'department': profile.get('department'),
                'location': profile.get('location'), 'email': profile.get('email'),
                'role': profile.get('role', 'employee')}

    @app.get('/travelers')
    def travelers():
        """Synthetic demo directory for the sign-in screen: the fixed accounts. Grades are not listed here."""
        return {'organization': context.organization,
                'travelers': [_person(t) for t in context.travelers.values()]}

    @app.post('/sessions', status_code=201)
    def create_session(body: SessionCreate):
        profile = context.travelers.get(body.traveler_id)
        if profile is None:
            raise ApiError('UNAUTHENTICATED', 'Unknown traveler for this organization.', field='/traveler_id')
        token, session = context.store.create_session(context.organization['id'], profile['traveler_id'],
                                                      profile['grade'], context.clock(),
                                                      context.settings.session_ttl_hours,
                                                      role=profile.get('role', 'employee'))
        return {'session_id': session['session_id'], 'organization_id': session['organization_id'],
                'token': token, 'expires_at': session['expires_at'],
                'traveler': _person(profile) | {'grade': profile['grade'], 'role': session['role']}}

    @app.get('/sessions/{session_id}')
    def get_session(session_id: str, session=Depends(current_session)):
        ensure_owner(session, session_id)
        receipts = [{k: r[k] for k in ('image_id', 'filename', 'mime', 'size_bytes', 'created_at')} |
                    {'extraction': json.loads(r['extraction_json']) if r['extraction_json'] else None,
                     'confirmed': json.loads(r['confirmed_json']) if r['confirmed_json'] else None}
                    for r in context.store.list_receipts(session_id)]
        traveler = context.travelers.get(session['traveler_id'], {'traveler_id': session['traveler_id']})
        return {'session_id': session_id, 'organization_id': session['organization_id'],
                'traveler': _person(traveler) | {'grade': session['grade'], 'role': session['role']},
                'expires_at': session['expires_at'], 'receipts': receipts,
                'assessments': context.store.list_assessments(session_id)}

    @app.delete('/sessions/{session_id}', status_code=204)
    def delete_session(session_id: str, session=Depends(current_session)):
        ensure_owner(session, session_id)
        removed = context.store.delete_session(session_id)
        from workflows.agent_graph import delete_agent_thread
        delete_agent_thread(context, session_id)              # agent checkpoints go with the session (retention)
        context.events.emit('storage_delete', scope='session', receipts=removed)
        return Response(status_code=204)

    # ---- receipts -------------------------------------------------------------
    @app.post('/receipts', status_code=201)
    async def upload_receipts(files: list[UploadFile] = File(...), session=Depends(current_session)):
        max_bytes, max_files = limits()
        if len(files) > max_files:
            raise ApiError('PAYLOAD_TOO_LARGE', 'At most %d images per claim.' % max_files, field='/files')
        accepted = []
        for upload in files:
            data = await upload.read(max_bytes + 1)
            mime, width, height = inspect_image(data, upload.filename)
            accepted.append((upload.filename, mime, data, width, height))
        stored = []
        for filename, mime, data, width, height in accepted:
            receipt = context.store.add_receipt(session['session_id'], session['organization_id'], filename, mime,
                                                data, context.clock())
            context.events.emit('storage_write', record='receipt', image_id=receipt['image_id'])
            stored.append({'image_id': receipt['image_id'], 'filename': filename, 'mime': mime,
                           'size_bytes': len(data), 'width': width, 'height': height})
        return {'receipts': stored, 'extractions': [], 'missing_fields': [],
                'message': 'Images validated and stored privately for this session.'}

    @app.delete('/receipts/{image_id}', status_code=204)
    def delete_receipt(image_id: str, session=Depends(current_session)):
        receipt = context.store.get_receipt(image_id)
        if receipt is None:
            raise ApiError('NOT_FOUND', 'No such receipt in your session.')
        ensure_owner(session, receipt['session_id'])
        context.store.delete_receipt(image_id)
        context.events.emit('storage_delete', scope='receipt', image_id=image_id)
        return Response(status_code=204)

    # ---- claims ------------------------------------------------------------------
    @app.post('/claims/review')
    def review_claim(body: ClaimReview, session=Depends(current_session)):
        payload = _plain(body.claim) | {'grade': session['grade'], 'lines': [_plain(l) for l in body.lines]}
        result = assess(payload)
        assessment_id = context.store.save_assessment(session['session_id'], payload, result, context.clock())
        return {'assessment_id': assessment_id, 'assessment': result, 'evidence': evidence_for(result['evidence_ids'])}

    # ---- text receipt review (no image reading in this build) --------------------------
    @app.post('/receipts/extract')
    async def extract_receipt(text: Optional[str] = Form(default=None, max_length=20000),
                              file: Optional[UploadFile] = File(default=None), session=Depends(current_session)):
        """Read receipt fields from pasted text or an uploaded text receipt / digital PDF. Returns UNCONFIRMED fields;
        nothing is calculated until the traveler confirms them through POST /receipts/assess."""
        from core.errors import CapabilityUnavailable
        from retrieval.loaders import IngestError
        from workflows.receipt_review import extract_receipt_text, receipt_text_from_upload
        if file is not None and file.filename:
            data = await file.read()
            try:
                text = receipt_text_from_upload(file.filename, data)
            except IngestError as exc:
                raise ApiError(exc.code, str(exc), field='/file')
        try:
            return extract_receipt_text(text or '', context, session_id=session['session_id'])
        except CapabilityUnavailable as exc:
            raise ApiError('CAPABILITY_UNAVAILABLE', str(exc))

    @app.post('/receipts/assess')
    def assess_receipt_route(body: ReceiptAssessIn, session=Depends(current_session)):
        """Assessment of confirmed receipt fields for the signed-in traveler (server-held grade). The amounts are
        always calculated in Python; with a model configured, the receipt agent resumes the session's receipt thread
        and adds a critic-checked explanation."""
        from workflows.receipt_review import assess_receipt
        payload = _plain(body)
        if context.model is not None:
            from workflows.receipt_agent import assess_confirmed_receipt
            result = assess_confirmed_receipt(payload['fields'], payload['claim'], session['grade'], context,
                                              session_id=session['session_id'])
        else:
            result = assess_receipt(payload['fields'], payload['claim'], session['grade'])
        assessment_id = context.store.save_assessment(session['session_id'], payload, result, context.clock())
        return {'assessment_id': assessment_id, 'assessment': result}

    # ---- policy chat and travel search ---------------------------------------------
    @app.post('/chat')
    def chat(body: ChatIn, session=Depends(current_session)):
        from workflows.policy_qa import answer
        return answer(context, session, body.message, body.applicability)

    @app.post('/travel/search')
    def travel_search(body: TravelSearchIn, session=Depends(current_session)):
        """Search and assess offers for the signed-in traveler. Grade comes from the server-held profile; test hooks
        (fixture paths, injected faults) are not part of this request model, so a client can never set them."""
        from core.errors import CapabilityUnavailable
        from workflows.travel_search import run_tools
        payload = _plain(body)
        try:
            if context.model is not None:
                from workflows.agent_graph import run_travel_agent
                return run_travel_agent(payload, context, session['grade'], session['organization_id'],
                                        session_id=session['session_id'])
            return run_tools(payload, context, session['grade'], session['organization_id']) | {
                'planner': 'deterministic (no model configured)'}
        except CapabilityUnavailable as exc:
            raise ApiError('CAPABILITY_UNAVAILABLE', str(exc))

    # ---- policy library -----------------------------------------------------------
    def library_view(document):
        return {k: document.get(k) for k in ('document_id', 'title', 'version', 'authority', 'geography',
                                              'effective_from', 'effective_to', 'filename', 'size_bytes', 'chunk_count',
                                              'uploaded_by', 'created_at', 'file_type', 'page_count')}

    @app.get('/policy/library')
    def policy_library(session=Depends(current_session)):
        from domain.data import policy
        source = policy()
        sections = [{'rule_id': r['id'], 'title': r['title']} for r in source['rules']]
        # The core policy is ONE document split into rule sections (P01-P20); each section is a retrieval unit with a
        # stable rule ID for citations, not a separate document (SPECIFICATION: do not inflate counts by splitting).
        core = [{'document_id': 'POLICY-%s' % source['version'], 'title': '%s Travel Policy' % source['company'],
                 'version': source['version'], 'authority': 'policy', 'origin': 'core',
                 'effective_from': source['effective_from'], 'effective_to': source['effective_to'],
                 'section_count': len(sections), 'sections': sections}]
        uploaded = [library_view(d) | {'origin': 'library'}
                    for d in context.store.list_policy_documents(session['organization_id'])]
        return {'organization': context.organization['name'], 'core': core, 'library': uploaded,
                'document_count': len(core) + len(uploaded),
                'section_count': len(sections) + sum(d.get('chunk_count') or 0 for d in uploaded),
                'note': 'Library documents are searchable and citable. Calculation caps come only from the reviewed '
                        'rule registry.'}

    @app.post('/admin/policies', status_code=201)
    async def add_policy_document(title: str = Form(..., min_length=3, max_length=120),
                                  effective_from: date = Form(...), effective_to: date = Form(...),
                                  authority: Literal['policy', 'guidance'] = Form('guidance'),
                                  geography: Literal['general', 'domestic', 'international'] = Form('general'),
                                  version: str = Form('1.0', min_length=1, max_length=20),
                                  text: Optional[str] = Form(None), file: Optional[UploadFile] = File(None),
                                  session=Depends(current_session)):
        """Admin upload: LangChain loaders parse the file, LangChain splitters chunk it, vectors are created,
        and the retrieval index is rebuilt before the response returns."""
        from retrieval.library import IngestError, ingest
        from retrieval.loaders import MAX_UPLOAD_BYTES
        require_admin(session)
        if effective_to < effective_from:
            raise ApiError('VALIDATION_FAILED', 'effective_to must not be before effective_from.', field='/effective_to')
        if (file is None) == (not text):
            raise ApiError('VALIDATION_FAILED', 'Provide exactly one of a file or pasted text.', field='/file')
        if file is not None:
            data, filename = await file.read(MAX_UPLOAD_BYTES + 1), file.filename
        else:
            data, filename = text.encode('utf-8'), 'pasted.md'
        retrieval = context.settings.retrieval
        try:
            file_type, page_count, chunks = ingest(filename, data, title.strip(), retrieval.chunk_size_chars,
                                                   retrieval.chunk_overlap_chars)
        except IngestError as error:
            raise ApiError(error.code, str(error), field='/file')
        if context.store.policy_document_exists(session['organization_id'], data):
            raise ApiError('VALIDATION_FAILED', 'This document is already in the policy library.', field='/file')
        meta = {'title': title.strip(), 'version': version.strip(), 'authority': authority, 'geography': geography,
                'effective_from': effective_from.isoformat(), 'effective_to': effective_to.isoformat(),
                'filename': filename if file is not None else None, 'file_type': file_type, 'page_count': page_count}
        document = context.store.add_policy_document(session['organization_id'], meta, chunks, data,
                                                     session['traveler_id'], context.clock())
        indexed = refresh_library(context)
        retriever = context.retriever
        vectors = retriever.last_vectors_created
        context.events.emit('policy_document_added', document_id=document['document_id'], chunks=len(chunks),
                            vectors=vectors)
        if retriever.vectors_active:
            vector_note = '%d vectors created with %s' % (vectors, retriever.embedding_model)
        elif retriever.vector_error:
            vector_note = 'vectors not created: %s' % retriever.vector_error
        else:
            vector_note = 'vectors not created: embeddings are not configured'
        return library_view(document) | {
            'indexed_sections': indexed, 'vectors_created': vectors, 'embedding_model': retriever.embedding_model,
            'retrieval_mode': retriever.mode,
            'preview': [{'position': i + 1, 'section': c['section'], 'page': c['page'], 'characters': len(c['text']),
                         'excerpt': c['text'][:160]} for i, c in enumerate(chunks[:8])],
            'message': 'Parsed %s, split into %d sections%s; %s. Searchable now.' % (
                file_type.upper() if file_type in ('pdf', 'docx') else file_type, len(chunks),
                ' from %d pages' % page_count if page_count else '', vector_note)}

    # ---- golden-case evaluation results (read-only; runs are started from the CLI) ----------------------------
    evaluation_dir = context.settings.data_dir / 'evaluation'

    def _runs():
        if not evaluation_dir.is_dir():
            return {}
        return {p.name: p for p in evaluation_dir.iterdir() if (p / 'summary.json').is_file()}

    @app.get('/admin/evaluations')
    def list_evaluations(session=Depends(current_session)):
        """Admin: every golden-case run under runtime/evaluation, newest first, with its status counts."""
        require_admin(session)
        runs = []
        for name, path in _runs().items():
            summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
            runs.append({'run': name, 'generated_at': summary.get('generated_at'),
                         'cases_selected': summary.get('cases_selected'),
                         'model_calls_allowed': summary.get('model_calls_allowed'),
                         'status_counts': summary.get('status_counts'),
                         'automatic_counts': summary.get('automatic_counts')})
        runs.sort(key=lambda r: r['generated_at'] or '', reverse=True)
        return {'runs': runs, 'command': 'python -m evaluation.driver --through M6 --allow-model --embeddings'}

    @app.get('/admin/evaluations/{run}')
    def evaluation_detail(run: str, session=Depends(current_session)):
        """Admin: one run's summary and per-case results. Only case id, title, category, split and entrypoint are
        read from the suite; expected answers stay in the test files (they are never shown or sent to the model)."""
        require_admin(session)
        path = _runs().get(run)                               # only names listed above: no path traversal
        if path is None:
            raise ApiError('NOT_FOUND', 'No such evaluation run.')
        summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
        suite = {c['id']: c for c in json.loads((ROOT / 'tests' / 'golden_cases.json').read_text(encoding='utf-8'))['cases']}
        checks = {}
        if (path / 'checks.jsonl').is_file():
            for line in (path / 'checks.jsonl').read_text(encoding='utf-8').splitlines():
                row = json.loads(line)
                checks[row['case_id']] = row
        cases = []
        if (path / 'envelopes.jsonl').is_file():
            for line in (path / 'envelopes.jsonl').read_text(encoding='utf-8').splitlines():
                envelope = json.loads(line)
                case, meta = suite.get(envelope['case_id'], {}), envelope['run_metadata']
                check = checks.get(envelope['case_id'], {})
                failed = [c.get('path') for c in check.get('checks') or [] if not c.get('passed')]
                cases.append({'case_id': envelope['case_id'], 'title': case.get('title'),
                              'category': case.get('category'), 'split': case.get('split'),
                              'entrypoint': case.get('entrypoint'), 'status': meta.get('status'),
                              'automatic_status': meta.get('automatic_status'),
                              'duration_ms': meta.get('duration_ms'),
                              'checks_passed': sum(1 for c in check.get('checks') or [] if c.get('passed')),
                              'checks_total': len(check.get('checks') or []),
                              'failed_checks': failed, 'error': (check.get('error') or '')[:300] or None})
        return {'run': run, 'summary': summary, 'cases': cases}

    class SearchProbeIn(BaseModel):
        model_config = ConfigDict(extra='forbid')
        query: str = Field(min_length=1, max_length=500)
        service_date: Optional[date] = None
        geography: Optional[Literal['domestic', 'international']] = None

    @app.post('/admin/search-inspect')
    def search_inspect(body: SearchProbeIn, session=Depends(current_session)):
        """Admin: run the policy search for a question and show both rankings and the fused top passages.
        No model call; the same filters as policy chat (organization, service date, geography)."""
        require_admin(session)
        from retrieval.interpret import interpret
        parsed = interpret(body.query)
        geography = body.geography or parsed['geography']
        applicability = {'organization_id': session['organization_id'],
                         'service_date': body.service_date or context.clock().date(), 'geography': geography}
        if parsed['organization_scope'] == 'goi_reference':
            applicability = {k: v for k, v in applicability.items() if k != 'geography'} | {'reference_only': True}
        result = context.retriever.explain(body.query, applicability, k=context.settings.retrieval.top_k)
        return result | {'applicability': {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                                           for k, v in applicability.items()},
                         'parsed': {k: parsed[k] for k in ('topic', 'country', 'city', 'organization_scope')}}

    @app.post('/admin/reconnect')
    def reconnect(session=Depends(current_session)):
        """Admin: re-read .env and reconnect the model and embeddings without restarting the API (a new Colab URL)."""
        from core.context import reconnect_providers
        require_admin(session)
        started = time.perf_counter()
        retriever = reconnect_providers(context)
        liveness['checked'] = 0.0                            # force a fresh reachability probe
        model = context.settings.model
        reachable, error = (False, 'no model configured (missing provider or key)') if context.model is None else \
            (context.model.reachable() if hasattr(context.model, 'reachable') else (True, None))
        liveness.update(checked=time.monotonic(), result=(reachable, error))
        fallback = getattr(retriever.embeddings, 'fallback_reason', None)
        return {'model': {'provider': model.provider, 'model_id': model.model_id, 'base_url': model.base_url or None,
                          'reachable': reachable, 'error': error},
                'embeddings': {'active_model': retriever.embedding_model, 'retrieval_mode': retriever.mode,
                               'vectors': retriever.vector_count(), 'vectors_created': retriever.last_vectors_created,
                               'fallback_reason': fallback, 'error': retriever.vector_error},
                'duration_ms': round((time.perf_counter() - started) * 1000, 1),
                'message': 'Model %s; search is %s with %s.' % (
                    'reachable' if reachable else 'NOT reachable (%s)' % error,
                    'hybrid' if retriever.mode == 'hybrid' else 'keyword-only', retriever.embedding_model or 'no vectors')}

    @app.get('/admin/policies')
    def list_policy_documents(session=Depends(current_session)):
        require_admin(session)
        return {'documents': [library_view(d) for d in context.store.list_policy_documents(session['organization_id'])]}

    @app.delete('/admin/policies/{document_id}', status_code=204)
    def delete_policy_document(document_id: str, session=Depends(current_session)):
        require_admin(session)
        document = context.store.get_policy_document(document_id)
        if document is None or document['organization_id'] != session['organization_id']:
            raise ApiError('NOT_FOUND', 'No such document in your organization\'s policy library.')
        context.store.delete_policy_document(document_id)
        refresh_library(context)
        context.events.emit('policy_document_removed', document_id=document_id)
        return Response(status_code=204)

    @app.get('/policy/limits')
    def policy_limits(category: Optional[str] = None, country: Optional[str] = None, city: Optional[str] = None,
                      service_date: Optional[date] = None, session=Depends(current_session)):
        """The signed-in traveler's own caps from the reviewed rule registry (server-held grade). With category and
        country, also resolves the single applicable cap, e.g. for a travel search form."""
        from domain.registry import RegistryLookupError, all_caps, registry_version, resolve_cap, review_status
        units = {'per_night': 'night', 'per_one_way_journey': 'one-way journey', 'per_local_day': 'local day'}

        def view(c):
            return {'cap_id': c.cap_id, 'rule_id': c.rule_id, 'category': c.category, 'scope': c.country_scope,
                    'city_tier': c.city_tier, 'currency': c.currency, 'amount': str(c.amount), 'unit': units[c.basis]}
        body = {'grade': session['grade'], 'registry_version': registry_version(), 'review_status': review_status(),
                'caps': [view(c) for c in all_caps() if c.grade == session['grade']]}
        if category and country:
            try:
                body['applicable'] = view(resolve_cap(category, country, city, session['grade'],
                                                      service_date or context.clock().date()))
            except RegistryLookupError as error:
                body['applicable'] = None
                body['unresolved'] = {'reason': error.reason_code, 'message': error.message}
        return body

    @app.get('/policy/rules')
    def policy_rules():
        from domain.data import policy
        return {'version': policy()['version'], 'fictional': True,
                'rules': evidence_for([r['id'] for r in policy()['rules']])}

    return app


def local_client(context):
    """In-process client used by evaluation entrypoints and tests. Exercises the real routes."""
    from fastapi.testclient import TestClient
    return TestClient(create_app(context))


_app = None


def __getattr__(name):
    """Build the default app lazily so importing this module has no side effects."""
    global _app
    if name == 'app':
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
