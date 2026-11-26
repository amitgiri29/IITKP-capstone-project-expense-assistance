"""UC02 receipt review (route receipt_review), TEXT receipts only.

    text receipt -> extract fields (model, structured; never guesses) -> traveler confirms or edits the critical fields
    -> domain.assessment.assess (Python: caps, exclusions, evidence, deadline, budget, readiness)

Images are not read: that needs a vision model or OCR, and OCR is not permitted (adapters/vision.py). Image requests
report CAPABILITY_UNAVAILABLE and offer transcription instead. Amounts are never taken from the model unconfirmed:
the extraction is always returned with user_confirmed = false, and only confirmed fields reach the calculation.
"""
import re
from decimal import Decimal, InvalidOperation

from adapters.vision import INTERIM_PATH, vision_available
from core.errors import CapabilityUnavailable
from domain.assessment import assess
from domain.evidence import evidence_for
from workflows.planner import prompt

CATEGORIES = ['hotel', 'flight', 'local_transport', 'out_of_scope']
_NUMBER = {'type': ['number', 'null']}
_STRING = {'type': ['string', 'null']}
EXTRACTION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['merchant', 'receipt_id', 'category', 'country', 'city', 'currency', 'service_date', 'checkin',
                 'checkout', 'nights', 'nightly_amounts', 'payable_total', 'taxes_included', 'excluded_items',
                 'uncertainties'],
    'properties': {
        'merchant': _STRING, 'receipt_id': _STRING,
        'category': {'type': ['string', 'null'], 'enum': CATEGORIES + [None]},
        'country': _STRING, 'city': _STRING, 'currency': _STRING,
        'service_date': _STRING, 'checkin': _STRING, 'checkout': _STRING,
        'nights': {'type': ['integer', 'null']},
        'nightly_amounts': {'type': ['array', 'null'], 'items': {'type': 'number'}},
        'payable_total': _NUMBER,
        'taxes_included': {'type': ['boolean', 'null']},
        'excluded_items': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['description', 'amount'],
            'properties': {'description': {'type': 'string'}, 'amount': _NUMBER}}},
        'uncertainties': {'type': 'array', 'items': {'type': 'string'}},
    },
}
CRITICAL = ('category', 'currency', 'payable_total', 'service_date')
_INSTRUCTION = re.compile(r'\b(ignore|disregard|approve|override|bypass)\b.{0,40}\b(policy|rules?|claim|limit|cap|'
                          r'instructions?)\b', re.I)


def _decimal(value):
    try:
        return None if value in (None, '') else Decimal(str(value))
    except InvalidOperation:
        return None


def country_code(country, city=None):
    """Package country code from a code, an ISO alias or a country name (reference_data country_names); when the
    country is missing, from a known city (city_gazetteer)."""
    from domain.data import reference_data
    from domain.reference import canonical_city, is_supported_country, normalize_country
    data = reference_data()
    if country:
        code = normalize_country(country)
        if is_supported_country(code):
            return code
        text = str(country).strip().casefold()
        for code, names in data['country_names'].items():
            if code != 'purpose' and text in {n.casefold() for n in names}:
                return code
        return str(country).strip()
    if city:
        name = canonical_city(city)
        for code, cities in data['city_gazetteer'].items():
            if code != 'purpose' and isinstance(cities, list) and name in {canonical_city(c) for c in cities}:
                return code
    return None


def nightly_breakdown(fields):
    """Per-night amounts to cap, or None. Used only for multi-night stays whose listed nights, plus excluded extras,
    add up to the all-inclusive payable total; a single night is always the payable total (never a pre-tax rate)."""
    nightly = [_decimal(n) for n in (fields.get('nightly_amounts') or [])]
    nights = int(fields.get('nights') or len(nightly) or 1)
    total = _decimal(fields.get('payable_total'))
    excluded = sum((_decimal(i.get('amount')) or Decimal(0)) for i in (fields.get('excluded_items') or []))
    if nights <= 1 or not nightly or None in nightly or len(nightly) != nights:
        return None
    if total is not None and sum(nightly) + excluded != total:
        return None
    return nightly


def check_extraction(fields, text=''):
    """Code-side checks on an extraction: what the traveler must look at before confirming."""
    fields['country'] = country_code(fields.get('country'), fields.get('city'))
    notes = list(fields.get('uncertainties') or [])
    nightly = [_decimal(n) for n in (fields.get('nightly_amounts') or [])]
    total = _decimal(fields.get('payable_total'))
    excluded = sum((_decimal(i.get('amount')) or Decimal(0)) for i in (fields.get('excluded_items') or []))
    nights = int(fields.get('nights') or 1)
    if nights > 1 and nightly and total is not None and None not in nightly and sum(nightly) + excluded != total:
        notes.append('The nightly amounts (%s) plus excluded extras (%s) do not add up to the payable total (%s); '
                     'enter each night\'s all-inclusive amount.' % (sum(nightly), excluded, total))
    if nights > 1 and nightly and len(nightly) != nights:
        notes.append('%d nightly amounts were listed for %d nights.' % (len(nightly), nights))
    if nights <= 1:
        fields['nightly_amounts'] = None          # one night is capped on the all-inclusive payable total
    if _INSTRUCTION.search(text or ''):
        notes.append('The receipt text contains instructions (for example to ignore the policy). They were ignored.')
    missing = [f for f in CRITICAL if fields.get(f) in (None, '')]
    if fields.get('category') == 'hotel' and not fields.get('city'):
        missing.append('city')
    if not fields.get('country'):
        missing.append('country')
    return list(dict.fromkeys(notes)), list(dict.fromkeys(missing))


def extract_receipt_text(text, context, session_id=None):
    """Read receipt text through the receipt agent (workflows/receipt_agent.py): reader -> verifier -> one repair ->
    pause. Always unconfirmed; the traveler confirms before any calculation."""
    text = (text or '').strip()
    if len(text) < 10:
        return {'run_status': 'OK', 'extraction': None, 'missing_fields': ['receipt_text'],
                'message': 'Paste the receipt text or upload a text or digital PDF receipt.'}
    if context.model is None:
        raise CapabilityUnavailable('Reading receipt text needs the configured language model ([model] in '
                                    'config/settings.toml). You can still enter the fields by hand.')
    from workflows.receipt_agent import read_receipt
    return read_receipt(text, context, session_id)


def receipt_text_from_upload(filename, data):
    """Text of an uploaded receipt (.txt, .md, .docx or a PDF with a text layer). Scans are refused: no OCR."""
    from retrieval.loaders import IngestError, load_upload
    try:
        _, documents = load_upload(filename, data)
    except IngestError as exc:
        if exc.code == 'VALIDATION_FAILED' and str(filename).lower().endswith('.pdf'):
            raise IngestError('VALIDATION_FAILED', 'This PDF is a scan with no text layer. Scanned receipts need '
                                                   'image reading, which this build does not have. ' + INTERIM_PATH)
        raise
    return '\n'.join(d.page_content for d in documents)


def claim_payload(fields, claim, grade):
    """Map confirmed receipt fields plus claim context to the assessment input (one receipt = one claim)."""
    excluded = sum((_decimal(i.get('amount')) or Decimal(0)) for i in (fields.get('excluded_items') or []))
    country = country_code(fields.get('country'), fields.get('city'))
    payload = {'grade': grade, 'category': fields.get('category'), 'country': country,
               'city': fields.get('city'), 'currency': fields.get('currency'),
               'service_date': fields.get('service_date') or fields.get('checkin'),
               'transaction_date': fields.get('service_date') or fields.get('checkin'),
               'amount': fields.get('payable_total'), 'excluded_amount': str(excluded),
               'user_confirmed': bool(fields.get('user_confirmed')),
               'taxes_and_fees_included': fields.get('taxes_included') if fields.get('taxes_included') is not None
               else True,
               'receipt_id': fields.get('receipt_id')}
    if fields.get('category') == 'hotel':
        nightly = nightly_breakdown(fields)
        if nightly:
            # assess() subtracts excluded extras from the first night's line, so that line must contain them: the
            # claimed total then equals the payable total and the extras are excluded exactly once.
            nightly = [nightly[0] + excluded] + nightly[1:]
            payload['nightly_amounts'] = [str(n) for n in nightly]
            payload['excluded_amount'] = str(excluded)
        payload['nights'] = int(fields.get('nights') or 1)
        # A multi-night stay without a consistent nightly breakdown is left for assess() to ask about (P02).
    for key in ('budget_inr', 'trip_start', 'trip_end', 'submitted_on', 'coverage_complete', 'business_purpose',
                'fx_rate', 'fx_reference'):
        if claim.get(key) not in (None, ''):
            payload[key] = claim[key]
    documents = claim.get('required_documents_present')
    if documents is None:
        documents = True if fields.get('category') != 'flight' else bool(claim.get('boarding_pass_present'))
    payload['required_documents_present'] = documents
    return payload


def assess_receipt(fields, claim, grade):
    """Python assessment of a confirmed receipt."""
    result = assess(claim_payload(fields, claim, grade))
    return result | {'evidence': evidence_for(result['evidence_ids'])}


def parse_image_then_review(payload, context):
    """Evaluation entrypoint parse_image_then_review (GT061-GT080). Receipt IMAGES need a vision model or OCR; this
    build has neither, so the request is reported as an unavailable capability (never a guessed extraction)."""
    if not vision_available(context):
        raise CapabilityUnavailable('Reading receipt images needs a vision-capable model; OCR is not permitted. '
                                    + INTERIM_PATH)
    raise CapabilityUnavailable('Image extraction is not implemented in this text-only build. ' + INTERIM_PATH)


def correct_claim(payload, context=None):
    """Evaluation entrypoint correct_claim (GT112): a confirmed correction invalidates the earlier calculation and
    the claim is recalculated from the corrected facts."""
    base = {k: v for k, v in payload.items() if k not in ('initial', 'correction', 'fixture_paths')}
    claim = base | dict(payload.get('initial') or {})
    corrections = {}
    for key, value in (payload.get('correction') or {}).items():
        field = key[len('confirmed_'):] if key.startswith('confirmed_') else key
        corrections[field] = value
    if 'amount' in corrections and claim.get('nights') in (None, 1) and claim.get('category', 'hotel') == 'hotel':
        claim.pop('nightly_amounts', None)
    before = assess(claim)
    claim.update(corrections)
    claim['user_confirmed'] = True
    after = assess(claim)
    if context is not None:
        context.events.emit('invalidated', scope='assessment', fields=sorted(corrections))
    return after | {'invalidated': {'fields': sorted(corrections),
                                    'previous': {k: before.get(k) for k in ('claimed_total_inr', 'eligible_total_inr',
                                                                             'budget_status', 'compliance_status')}}}
