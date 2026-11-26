"""Receipt review agent (route receipt_review, TEXT receipts only): a bounded LangGraph workflow in two stages that
share one checkpointed thread per session, with the traveler's confirmation as the pause between them.

  stage "read"    planner (code)  -> reader (model: extract fields)
                  -> verifier (code: every value must be written on the receipt; arithmetic; instructions)
                  -> [one repair: the reader re-reads with the verifier's issues] -> pause for confirmation
  stage "assess"  calculator (Python: caps, exclusions, deadline, budget, readiness; corrections vs the extraction)
                  -> writer (model: plain-language explanation) -> critic (code + model)
                  -> [one repair: the writer re-drafts] -> final assessment

Boundaries (SPECIFICATION "UC02" and "State and agent boundaries"):
- Amounts, statuses and readiness always come from domain.assessment; no model output can change them. The writer's
  text is shown only after the critic passes it; otherwise the verified summary is shown with a disclosed limitation.
- A value the verifier cannot find on the receipt is set to null after the one repair, so the traveler must enter it;
  the model never supplies an unconfirmed amount, date or currency.
- At most one repair per stage (operational_defaults.executor_repairs). The model never chooses the route.
- The receipt text is not kept in the checkpoint after the read stage; deleting the session deletes the thread.
"""
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from adapters.model import ModelError
from workflows.agent_graph import _executor_repairs, checkpointer, delete_agent_thread
from workflows.planner import CRITIC_SCHEMA, WRITER_SCHEMA, prompt, validate_critique
from workflows.receipt_review import EXTRACTION_SCHEMA, assess_receipt, check_extraction

READ_TOOLS = ('read_receipt_text', 'verify_fields', 'pause_for_confirmation')
ASSESS_TOOLS = ('calculate_assessment', 'retrieve_policy_evidence', 'write_explanation', 'critic')
NOT_APPROVAL = 'This is an assessment for review, not a claim approval.'
COMPARED = ('category', 'country', 'city', 'currency', 'service_date', 'payable_total', 'nights', 'nightly_amounts',
            'taxes_included', 'excluded_items', 'merchant', 'receipt_id')
_MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov',
                                       'dec'), 1)}
_CURRENCY_MARKS = {'INR': r'\bINR\b|₹|\bRs\.?(?=\s|\d)|\brupees?\b', 'USD': r'\bUSD\b|US\$|\$',
                   'GBP': r'\bGBP\b|£', 'SGD': r'\bSGD\b|S\$'}
_EXTRAS = re.compile(r'\b(mini-?bar|alcohol|laundry|tips?|upgrades?|room service|spa|bar tab|movies?)\b', re.I)
_MONEY = re.compile(r'(?:\bINR|\bUSD|\bGBP|\bSGD|₹|US\$|S\$|\$|£|\bRs\.?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)', re.I)


def thread_id(session_id):
    return '%s:receipt' % session_id


# ---- verifier helpers (code, no model) ----------------------------------------------------------------------------
def _decimal(value):
    try:
        return None if value in (None, '') else Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        return None


def numbers_in(text):
    """Every number written on the receipt (1,23,456.00 and 123456 both count)."""
    found = set()
    for raw in re.findall(r'(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?', text or ''):
        value = _decimal(raw)
        if value is not None:
            found.add(value)
    return found


def dates_in(text):
    """Every calendar date written on the receipt, in ISO, day-first, month-first or month-name formats."""
    found = set()

    def add(y, m, d):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    text = text or ''
    for y, m, d in re.findall(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', text):
        add(y, m, d)
    for a, b, y in re.findall(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', text):
        add(y, b, a)                                   # day-first (India, UK)
        add(y, a, b)                                   # month-first (US); the reader nulls ambiguous dates
    for d, mon, y in re.findall(r'\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})\.?,?[\s-]+(\d{4})\b', text):
        if mon[:3].lower() in _MONTHS:
            add(y, _MONTHS[mon[:3].lower()], d)
    for mon, d, y in re.findall(r'\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', text):
        if mon[:3].lower() in _MONTHS:
            add(y, _MONTHS[mon[:3].lower()], d)
    return found


def _city_names(city):
    from domain.data import reference_data
    from domain.reference import canonical_city
    target = canonical_city(city)
    names = {city}
    for code, cities in reference_data()['city_gazetteer'].items():
        if code != 'purpose' and isinstance(cities, list):
            names.update(n for n in cities if canonical_city(n) == target)
    return names


def grounding_issues(fields, text):
    """Values the reader returned that are not written on the receipt. Returns {field: problem}."""
    issues = {}
    numbers, dates = numbers_in(text), dates_in(text)
    flat = ' '.join((text or '').split()).casefold()
    total = _decimal(fields.get('payable_total'))
    if total is not None and total not in numbers:
        issues['payable_total'] = 'the payable total %s is not written on the receipt' % fields['payable_total']
    nightly = fields.get('nightly_amounts') or []
    missing_nights = [n for n in nightly if _decimal(n) not in numbers]
    if missing_nights:
        issues['nightly_amounts'] = 'nightly amounts %s are not written on the receipt' % missing_nights
    bad_items = [i for i in (fields.get('excluded_items') or []) if _decimal(i.get('amount')) is not None
                 and _decimal(i.get('amount')) not in numbers]
    if bad_items:
        issues['excluded_items'] = 'excluded item amounts %s are not written on the receipt' % [
            i.get('amount') for i in bad_items]
    for key in ('service_date', 'checkin', 'checkout'):
        if fields.get(key) and str(fields[key])[:10] not in dates:
            issues[key] = 'the %s %s is not written on the receipt' % (key.replace('_', ' '), fields[key])
    currency = (fields.get('currency') or '').upper()
    if currency and currency in _CURRENCY_MARKS and not re.search(_CURRENCY_MARKS[currency], text or '', re.I):
        issues['currency'] = 'the currency %s is not shown on the receipt' % currency
    if fields.get('city') and not any(n.casefold() in flat for n in _city_names(fields['city'])):
        issues['city'] = 'the city %s is not written on the receipt' % fields['city']
    if fields.get('merchant') and ' '.join(str(fields['merchant']).split()).casefold() not in flat:
        issues['merchant'] = 'the merchant name "%s" is not written on the receipt as given' % fields['merchant']
    return issues


# ---- assessment critic helpers --------------------------------------------------------------------------------------
def _walk_numbers(value, out):
    if isinstance(value, dict):
        for v in value.values():
            _walk_numbers(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk_numbers(v, out)
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        out.add(Decimal(str(value)))
    elif isinstance(value, str):
        number = _decimal(value)
        if number is not None:
            out.add(number)


def allowed_amounts(assessment, fields, claim):
    """Every amount the explanation may state: assessment money fields, the confirmed receipt values, the budget and
    the caps that were applied."""
    from domain.registry import all_caps
    out = set()
    _walk_numbers({k: v for k, v in assessment.items() if k not in ('evidence', 'registry')}, out)
    _walk_numbers(fields, out)
    _walk_numbers(claim, out)
    used = {line.get('cap_id') for line in assessment.get('lines') or []}
    out.update(Decimal(str(c.amount)) for c in all_caps() if c.cap_id in used)
    return out


def explanation_checks(text, cited, assessment, fields, claim):
    """Code-side critic checks for the receipt explanation."""
    issues = []
    allowed = allowed_amounts(assessment, fields, claim)
    unknown = sorted({m for m in _MONEY.findall(text or '') if _decimal(m) not in allowed})
    if unknown:
        issues.append('The draft states amounts that are not in the assessment: %s.' % ', '.join(unknown))
    bad = [c for c in cited if c not in (assessment.get('evidence_ids') or [])]
    if bad:
        issues.append('The draft cites rules that the assessment did not use: %s.' % ', '.join(bad))
    if re.search(r'\b(is|has been|was|are|been)\s+approved\b|\bapprove[sd]?\s+(your|this|the)\s+claim\b|'
                 r'\breimbursed\s+in\s+full\b', text or '', re.I):
        issues.append('The draft claims an approval or full reimbursement; the assistant only assesses for review.')
    if assessment.get('compliance_status') not in ('WITHIN_POLICY', None) and \
            re.search(r'(?<!not )\bwithin (the )?policy\b', text or '', re.I):
        issues.append('The draft says the claim is within policy, but the compliance status is %s.'
                      % assessment.get('compliance_status'))
    listed = ' '.join(str(i.get('description') or '') for i in fields.get('excluded_items') or []).lower()
    invented = sorted({m.group(0).lower() for m in _EXTRAS.finditer(text or '')
                       if not re.search(r'\b%s' % re.escape(m.group(0).lower().rstrip('s')), listed)})
    if invented:
        issues.append('The draft mentions extras that are not on the receipt: %s (the receipt lists: %s).'
                      % (', '.join(invented), listed or 'none'))
    wrong_places = other_cities_named(text, fields.get('city'))
    if wrong_places:
        issues.append('The draft names %s, but the receipt is for %s.' % (', '.join(wrong_places),
                                                                         fields.get('city') or 'another place'))
    return issues


def _norm(value):
    """Comparable form of a field value: numbers and numeric strings as normalized decimals, recursively."""
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    number = _decimal(value) if isinstance(value, (int, float, Decimal, str)) else None
    if number is not None:
        return str(number.normalize())
    return str(value).strip().casefold() if isinstance(value, str) else value


def corrected_fields(before, after):
    """Critical fields the traveler changed between the extraction and the confirmation."""
    changed = []
    for key in COMPARED:
        old, new = before.get(key), after.get(key)
        if old in (None, '', []) and new in (None, '', []):
            continue
        if json.dumps(_norm(old), sort_keys=True) != json.dumps(_norm(new), sort_keys=True):
            changed.append(key)
    return changed


def filter_model_notes(notes, text):
    """Model uncertainty notes are advisory. Whether the receipt contains instructions is decided by code
    (check_extraction), and notes about the receipt being fictional are noise, so such model notes are dropped."""
    from workflows.receipt_review import _INSTRUCTION
    has_instructions = bool(_INSTRUCTION.search(text or ''))
    kept = []
    for note in notes or []:
        lowered = str(note).lower()
        if 'fictional' in lowered or 'test receipt' in lowered or 'synthetic' in lowered:
            continue
        if 'instruction' in lowered and not has_instructions:
            continue
        kept.append(note)
    return kept


def other_cities_named(text, city):
    """Known city names in the draft other than the receipt's city (catches an explanation about the wrong place)."""
    from domain.data import reference_data
    from domain.reference import canonical_city
    own = canonical_city(city) if city else None
    named = set()
    for code, cities in reference_data()['city_gazetteer'].items():
        if code == 'purpose' or not isinstance(cities, list):
            continue
        for name in cities:
            if re.search(r'\b%s\b' % re.escape(name), text or '', re.I) and canonical_city(name) != own:
                named.add(name)
    return sorted(named)


def _receipt_digest(fields):
    keep = ('merchant', 'category', 'country', 'city', 'currency', 'service_date', 'nights', 'nightly_amounts',
            'payable_total', 'taxes_included', 'excluded_items')
    return {k: fields.get(k) for k in keep}


def _assessment_digest(assessment, corrections, fields=None):
    keep = ('claimed_total_inr', 'eligible_total_inr', 'over_cap_total_inr', 'excluded_total_inr',
            'rounding_adjustment_inr', 'remaining_budget_inr', 'budget_excess_inr', 'compliance_status', 'readiness',
            'budget_status', 'late', 'reasons', 'missing_fields', 'ask_for', 'provisional_amounts', 'evidence_ids')
    digest = {k: assessment.get(k) for k in keep}
    digest['lines'] = [{k: v for k, v in line.items() if k not in ('registry_version',)}
                       for line in assessment.get('lines') or []]
    digest['issues'] = [{k: i.get(k) for k in ('reason', 'message', 'readiness')} for i in assessment.get('issues') or []]
    digest['policy_evidence'] = [{'rule_id': e['rule_id'], 'section': e['section'], 'text': e['text'][:600]}
                                 for e in assessment.get('evidence') or []]
    digest['corrected_by_traveler'] = corrections or []
    if fields is not None:
        digest['confirmed_receipt'] = _receipt_digest(fields)
    return digest


class ReceiptState(TypedDict, total=False):
    session_id: str
    stage: str
    receipt_text: str
    plan: dict
    extraction: dict
    notes: list
    missing_fields: list
    grounding: dict
    confirmed_fields: dict
    claim: dict
    grade: str
    assessment: dict
    corrections: list
    draft: dict
    critique: dict
    repair_count: int
    run_status: str
    model_id: str
    trace: list
    limitations: list


def build_receipt_graph(context):
    model = context.model
    max_repairs = _executor_repairs()

    def step(state, name, **data):
        context.events.emit('agent_step', route='receipt_review', step=name,
                            **{k: v for k, v in data.items() if v is not None})
        return list(state.get('trace') or []) + [dict(step=name, **{k: v for k, v in data.items() if v is not None})]

    # ---- stage "read" ----------------------------------------------------------------------------------------------
    def planner(state):
        if state['stage'] == 'read':
            plan = {'intent': 'receipt_review', 'stage': 'read', 'tools': list(READ_TOOLS), 'source': 'code'}
        else:
            plan = {'intent': 'receipt_review', 'stage': 'assess', 'tools': list(ASSESS_TOOLS), 'source': 'code'}
        return {'plan': plan, 'trace': step(state, 'planner', source='code', stage=plan['stage'], tools=plan['tools'])}

    def reader(state):
        issues = list((state.get('grounding') or {}).values())
        user = 'Receipt text:\n' + state['receipt_text'][:8000]
        if issues:
            user += ('\n\nYour previous extraction had values that are not written on the receipt. Read the receipt '
                     'again and copy values exactly as written, or use null:\n- ' + '\n- '.join(issues))
        try:
            reply = model.generate('receipt_extract', prompt('receipt_extract'), user, schema=EXTRACTION_SCHEMA,
                                   max_tokens=900)
        except ModelError as exc:
            status = 'FAILED_VALIDATION' if exc.kind in ('format', 'truncated', 'refusal') else 'PROVIDER_UNAVAILABLE'
            return {'run_status': status, 'limitations': ['The reader could not extract the receipt (%s).' % exc.kind],
                    'trace': step(state, 'reader', outcome=status, repair=bool(issues) or None)}
        fields = dict(reply.data)
        fields['user_confirmed'] = False
        return {'extraction': fields, 'model_id': reply.model, 'run_status': 'OK',
                'trace': step(state, 'reader', source='model', repair=bool(issues) or None)}

    def verifier(state):
        fields = dict(state['extraction'])
        text = state['receipt_text']
        fields['uncertainties'] = filter_model_notes(fields.get('uncertainties'), text)
        notes, _ = check_extraction(fields, text)             # arithmetic, injected instructions, nightly cleanup
        grounding = grounding_issues(fields, text)
        decision = 'PASS' if not grounding else (
            'REPAIR' if (state.get('repair_count') or 0) < max_repairs else 'CLARIFY')
        return {'extraction': fields, 'notes': notes, 'grounding': grounding,
                'critique': {'decision': decision, 'issues': list(grounding.values()), 'source': 'code'},
                'trace': step(state, 'verifier', decision=decision, source='code',
                              ungrounded=sorted(grounding) or None)}

    def repair(state):
        count = (state.get('repair_count') or 0) + 1
        return {'repair_count': count, 'trace': step(state, 'repair', attempt=count)}

    def pause_for_confirmation(state):
        fields = dict(state.get('extraction') or {})
        notes = list(state.get('notes') or [])
        if fields:
            for key, problem in (state.get('grounding') or {}).items():
                if key == 'merchant':
                    notes.append('Check the merchant name: %s.' % problem)
                    continue
                fields[key] = [] if key == 'excluded_items' else None
                notes.append('Left blank because %s; please enter it from your receipt.' % problem)
            more_notes, missing = check_extraction(fields, '')
            fields['uncertainties'] = list(dict.fromkeys(notes + more_notes))
        else:
            missing = []
        return {'extraction': fields, 'missing_fields': missing, 'receipt_text': '',
                'trace': step(state, 'pause_for_confirmation', run_status=state.get('run_status'),
                              missing=missing or None)}

    # ---- stage "assess" ---------------------------------------------------------------------------------------------
    def calculator(state):
        fields, claim = state['confirmed_fields'], state.get('claim') or {}
        result = assess_receipt(fields, claim, state['grade'])
        before = state.get('extraction') or {}
        corrections = None
        if before:
            corrections = corrected_fields(before, fields)
            if corrections:
                context.events.emit('invalidated', scope='receipt_extraction', fields=corrections)
        return {'assessment': result, 'corrections': corrections or [], 'run_status': 'OK',
                'trace': step(state, 'calculator', source='python', readiness=result['readiness'],
                              compliance=result['compliance_status'], evidence=result['evidence_ids'],
                              corrected=corrections or None)}

    def writer(state):
        issues = (state.get('critique') or {}).get('issues') or [] if state.get('repair_count') else []
        user = 'Assessment (authoritative):\n%s' % json.dumps(
            _assessment_digest(state['assessment'], state.get('corrections'), state.get('confirmed_fields') or {}),
            ensure_ascii=False, indent=1, default=str)
        if issues:
            user += '\n\nYour previous draft was rejected for these reasons; fix them:\n- ' + '\n- '.join(issues)
        try:
            reply = model.generate('receipt_writer', prompt('receipt_writer'), user, schema=WRITER_SCHEMA,
                                   max_tokens=700)
            draft = {'explanation': reply.data['explanation'], 'evidence_ids': list(reply.data['evidence_ids']),
                     'source': 'model'}
        except ModelError as exc:
            draft = {'explanation': state['assessment'].get('message', ''),
                     'evidence_ids': state['assessment'].get('evidence_ids', []),
                     'source': 'deterministic fallback (%s)' % exc.kind}
        return {'draft': draft, 'trace': step(state, 'writer', source=draft['source'], repair=bool(issues) or None)}

    def critic(state):
        assessment, draft = state['assessment'], state['draft']
        issues = explanation_checks(draft['explanation'], draft['evidence_ids'], assessment,
                                    state.get('confirmed_fields') or {}, state.get('claim') or {})
        decision, source = ('REPAIR' if issues else 'PASS'), 'code'
        if draft['source'] == 'model':
            user = ('Assessment (authoritative):\n%s\n\nDraft explanation:\n%s\n\nDraft citations: %s'
                    % (json.dumps(_assessment_digest(assessment, state.get('corrections'),
                                                     state.get('confirmed_fields') or {}),
                                  ensure_ascii=False, indent=1, default=str), draft['explanation'],
                       draft['evidence_ids']))
            try:
                reply = model.generate('receipt_critic', prompt('receipt_critic'), user, schema=CRITIC_SCHEMA,
                                       max_tokens=500, validate=validate_critique)
                source = 'code + model'
                if reply.data['decision'] == 'REPAIR':
                    issues += [i for i in reply.data['issues'] if i not in issues]
                    decision = 'REPAIR'
            except ModelError as exc:
                source = 'code (model critic unavailable: %s)' % exc.kind
        return {'critique': {'decision': decision, 'issues': issues, 'source': source},
                'trace': step(state, 'critic', decision=decision, source=source, issues=len(issues) or None)}

    def finalize(state):
        return {'trace': step(state, 'finalize', run_status=state.get('run_status'))}

    # ---- routing ----------------------------------------------------------------------------------------------------
    def after_planner(state):
        return 'reader' if state['stage'] == 'read' else 'calculator'

    def after_reader(state):
        return 'verifier' if state.get('run_status') == 'OK' else 'pause_for_confirmation'

    def after_verifier(state):
        return 'repair' if state['critique']['decision'] == 'REPAIR' else 'pause_for_confirmation'

    def after_critic(state):
        if state['critique']['decision'] == 'REPAIR' and (state.get('repair_count') or 0) < max_repairs:
            return 'repair_writer'
        return 'finalize'

    def repair_writer(state):
        count = (state.get('repair_count') or 0) + 1
        return {'repair_count': count, 'trace': step(state, 'repair', attempt=count)}

    graph = StateGraph(ReceiptState)
    for name, node in (('planner', planner), ('reader', reader), ('verifier', verifier), ('repair', repair),
                       ('pause_for_confirmation', pause_for_confirmation), ('calculator', calculator),
                       ('writer', writer), ('critic', critic), ('repair_writer', repair_writer),
                       ('finalize', finalize)):
        graph.add_node(name, node)
    graph.add_edge(START, 'planner')
    graph.add_conditional_edges('planner', after_planner, ['reader', 'calculator'])
    graph.add_conditional_edges('reader', after_reader, ['verifier', 'pause_for_confirmation'])
    graph.add_conditional_edges('verifier', after_verifier, ['repair', 'pause_for_confirmation'])
    graph.add_edge('repair', 'reader')
    graph.add_edge('pause_for_confirmation', END)
    graph.add_edge('calculator', 'writer')
    graph.add_edge('writer', 'critic')
    graph.add_conditional_edges('critic', after_critic, ['repair_writer', 'finalize'])
    graph.add_edge('repair_writer', 'writer')
    graph.add_edge('finalize', END)
    return graph.compile(checkpointer=checkpointer(context))


def _agent_view(state):
    critique = state.get('critique') or {}
    return {'route': 'receipt_review', 'stage': state.get('stage'), 'thread': 'receipt',
            'repair_count': state.get('repair_count') or 0,
            'critique': {k: critique.get(k) for k in ('decision', 'issues', 'source')} if critique else None,
            'trace': state.get('trace') or []}


def _run(context, session_id, inputs):
    thread = thread_id(session_id) if session_id else 'ephemeral-receipt-%s' % uuid.uuid4().hex
    state = build_receipt_graph(context).invoke(
        inputs | {'session_id': thread, 'repair_count': 0, 'trace': [], 'limitations': [], 'critique': {},
                  'run_status': 'OK'}, {'configurable': {'thread_id': thread}})
    context.events.emit('observation', name='repair_count', value=state.get('repair_count') or 0)
    context.events.emit('agent_run', route='receipt_review', stage=inputs['stage'],
                        repair_count=state.get('repair_count') or 0, steps=[t['step'] for t in state['trace']])
    if not session_id:
        delete_agent_thread(context, thread)
    return state


def read_receipt(text, context, session_id=None):
    """Stage "read": extract and verify the fields, then pause for the traveler's confirmation."""
    state = _run(context, session_id, {'stage': 'read', 'receipt_text': text, 'extraction': {}, 'grounding': {},
                                       'notes': [], 'missing_fields': [], 'draft': {}, 'assessment': {},
                                       'confirmed_fields': {}, 'corrections': []})
    agent = _agent_view(state)
    if state.get('run_status') != 'OK' or not state.get('extraction'):
        reason = '; '.join(state.get('limitations') or []) or 'no fields were read'
        return {'run_status': state.get('run_status'), 'extraction': None, 'missing_fields': [], 'agent': agent,
                'message': 'I could not read this receipt reliably (%s). Please enter the fields by hand.' % reason}
    return {'run_status': 'OK', 'extraction': state['extraction'], 'missing_fields': state.get('missing_fields') or [],
            'readiness': 'NEEDS_CLARIFICATION', 'reasons': ['UNCONFIRMED_FIELDS'], 'model_id': state.get('model_id'),
            'agent': agent,
            'message': 'Please check these fields against your receipt and correct anything that is wrong, then '
                       'confirm. Nothing is calculated until you confirm.'}


def assess_confirmed_receipt(fields, claim, grade, context, session_id=None):
    """Stage "assess": resumes the session's receipt thread with the confirmed fields."""
    state = _run(context, session_id, {'stage': 'assess', 'confirmed_fields': fields, 'claim': claim or {},
                                       'grade': grade, 'draft': {}, 'assessment': {}, 'corrections': []})
    result = dict(state['assessment'])
    critique, draft = state.get('critique') or {}, state.get('draft') or {}
    limitations = []
    if draft.get('source') == 'model' and critique.get('decision') == 'PASS':
        explanation = draft['explanation'].strip()
    else:
        explanation = result.get('message', '')
        if draft.get('source') == 'model':
            limitations.append('The written explanation did not pass the critic after one rewrite, so the verified '
                               'summary is shown instead (the critic\'s reasons are under "How the agents handled '
                               'this").')
    if 'not a claim approval' not in explanation and 'not an approval' not in explanation:
        explanation += ' ' + NOT_APPROVAL
    result.update(explanation=explanation, corrections=state.get('corrections') or [],
                  limitations=limitations, agent=_agent_view(state))
    return result
