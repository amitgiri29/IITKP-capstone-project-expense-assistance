"""M6: bounded LangGraph planner -> executor -> writer -> critic for the travel_search route.

    planner (model)  chooses registered tools and fills missing criteria only from what the traveler wrote
    executor (code)  runs the registered tools: validate -> search -> assess (Python) -> retrieve policy
    writer (model)   drafts the explanation from the tool results
    critic (code + model) checks the draft against the tool results: PASS, REPAIR or CLARIFY

Boundaries (SPECIFICATION "State and agent boundaries"):
- Offer IDs, statuses, amounts and rankings in the result always come from the tools; no model output can change them.
- At most one format repair per model call (adapters/model.py) and at most one executor repair (the writer re-drafts
  once after a REPAIR); a second failure ends with the deterministic summary and a disclosed limitation.
- A model or provider outage is disclosed, never hidden: the run falls back to the deterministic plan or summary.
- There are no booking or payment tools.
- State is checkpointed per session (SQLite), so details confirmed earlier carry over when the traveler answers a
  clarification. Deleting the session deletes its checkpoints (retention).
"""
import json
import re
import sqlite3
import threading
import uuid
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from adapters.model import ModelError
from domain.data import ROOT
from workflows import travel_search as tools
from workflows.planner import (CRITERIA_FIELDS, CRITIC_SCHEMA, TOOLS, WRITER_SCHEMA, plan_request, prompt,
                               validate_critique)

_SAVERS = {}
_LOCK = threading.Lock()
OFFER_ID = re.compile(r'\b[A-Z]{1,2}\d{1,3}\b')
UNTRUSTED_OFFER_FIELDS = ('description', 'cancellation_terms')


def _executor_repairs():
    return json.loads((ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text(encoding='utf-8'))[
        'operational_defaults']['executor_repairs']


class AgentState(TypedDict, total=False):
    session_id: str
    intent: str
    request: dict
    grade: str
    organization_id: str
    plan: dict
    confirmed_facts: dict
    missing_fields: list
    evidence_ids: list
    tool_results: dict
    draft: dict
    critique: dict
    repair_count: int
    run_status: str
    trace: list
    limitations: list


def checkpointer(context):
    """One SQLite checkpointer per data folder (runtime/agent_checkpoints.sqlite)."""
    path = context.settings.data_dir / 'agent_checkpoints.sqlite'
    with _LOCK:
        saver = _SAVERS.get(str(path))
        if saver is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            saver = SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))
            saver.setup()
            _SAVERS[str(path)] = saver
        return saver


def close_checkpointer(context):
    """Close and forget the data folder's checkpointer connection (end of a golden case, or shutdown). Windows
    cannot delete a folder while the SQLite file in it is still open."""
    path = str(context.settings.data_dir / 'agent_checkpoints.sqlite')
    with _LOCK:
        saver = _SAVERS.pop(path, None)
    if saver is not None:
        try:
            saver.conn.close()
        except Exception:                      # already closed
            pass


def delete_agent_thread(context, session_id):
    """Retention: remove every checkpoint of a session's conversations (travel thread and receipt thread)."""
    for thread in (session_id, '%s:receipt' % session_id):
        try:
            checkpointer(context).delete_thread(thread)
        except Exception:                      # nothing stored for this thread
            pass


def _merge(request, planner_criteria, prior):
    """Explicit form fields win; earlier confirmed facts and the planner fill only fields that are still empty."""
    merged = dict(request)
    sources = {}
    if prior and request.get('search_type') and prior.get('search_type') != request.get('search_type'):
        prior = {}                                 # a different kind of search starts fresh
    for source, values in (('earlier in this conversation', prior or {}), ('your message', planner_criteria or {})):
        for key in CRITERIA_FIELDS:
            if merged.get(key) in (None, '') and values.get(key) not in (None, ''):
                merged[key] = values[key]
                sources[key] = source
    return merged, sources


def _tool_digest(result):
    """What the writer and critic may see: tool outputs without untrusted offer text."""
    return {
        'recommended_ids': result.get('recommended_ids', []), 'provisional_ids': result.get('provisional_ids', []),
        'noncompliant_ids': result.get('noncompliant_ids', []), 'needs_refresh_ids': result.get('needs_refresh_ids', []),
        'offers': [{k: v for k, v in o.items() if k not in UNTRUSTED_OFFER_FIELDS} for o in result.get('offers', [])],
        'evidence_ids': result.get('evidence_ids', []), 'mode': result.get('mode'),
        'booking_declined': result.get('booking_declined', False), 'notes': result.get('message', ''),
        'date_note': (result.get('date_mismatch') or {}).get('note'),
    }


def deterministic_checks(draft_text, cited, result):
    """Code-side critic checks that do not depend on the model."""
    issues = []
    known_ids = {o['id'] for o in result.get('offers', [])}
    mentioned = set(OFFER_ID.findall(draft_text or '')) - set(result.get('evidence_ids', []))
    unknown = sorted(i for i in mentioned if i not in known_ids and re.fullmatch(r'[HF]\d+', i))
    if unknown:
        issues.append('The draft mentions offers that the tools did not return: %s.' % ', '.join(unknown))
    bad_cites = [c for c in cited if c not in result.get('evidence_ids', [])]
    if bad_cites:
        issues.append('The draft cites rules that are not in the tool evidence: %s.' % ', '.join(bad_cites))
    if result.get('mode') == 'DEMO' and 'demo' not in (draft_text or '').lower():
        issues.append('The draft must say these are DEMO offers, not live inventory.')
    if re.search(r'\b(i have|i\'ve|we have|successfully)\s+(booked|reserved|paid)\b', draft_text or '', re.I):
        issues.append('The draft claims a booking or payment, which is never possible.')
    mismatch = result.get('date_mismatch')
    if mismatch:
        requested = [d for d in mismatch['requested'] if d]
        offered = {d for dates in mismatch['offered'] for d in dates if d}
        if any(d in (draft_text or '') for d in requested) and not any(d in (draft_text or '') for d in offered):
            issues.append('The draft presents the offers as being on the requested date (%s), but the offers are for '
                          '%s.' % (', '.join(requested), ', '.join(sorted(offered))))
    return issues


def build_graph(context):
    model = context.model
    max_repairs = _executor_repairs()

    def step(state, name, **data):
        context.events.emit('agent_step', step=name, **{k: v for k, v in data.items() if v is not None})
        return list(state.get('trace') or []) + [dict(step=name, **data)]

    def planner(state):
        request, prior = state['request'], state.get('confirmed_facts') or {}
        limitations = []
        try:
            plan, model_id = plan_request(model, request, prior)
            planner_info = 'model'
        except ModelError as exc:
            if exc.kind == 'format':
                return {'run_status': 'FAILED_VALIDATION', 'plan': {},
                        'limitations': ['The planner output was invalid after one repair, so no tool was executed.'],
                        'trace': step(state, 'planner', outcome='FAILED_VALIDATION')}
            plan = {'intent': 'travel_search', 'tools': list(TOOLS), 'criteria': {}, 'missing_fields': []}
            model_id, planner_info = None, 'deterministic fallback'
            limitations.append('The planning model was unavailable (%s); the standard search plan was used.' % exc.kind)
        merged, sources = _merge(request, plan.get('criteria'), prior)
        return {'plan': plan | {'source': planner_info, 'model_id': model_id}, 'intent': plan.get('intent'),
                'request': merged, 'limitations': limitations,
                'trace': step(state, 'planner', source=planner_info, intent=plan.get('intent'),
                              tools=plan.get('tools'), filled_from=sources or None)}

    def executor(state):
        result = tools.run_tools(state['request'], context, state['grade'], state['organization_id'])
        executed = ['validate_criteria'] if result.get('missing_fields') or result.get('refused') else list(TOOLS)
        facts = {k: v for k, v in (result.get('criteria') or {}).items() if k in CRITERIA_FIELDS and v not in (None, '')}
        return {'tool_results': result, 'missing_fields': result.get('missing_fields', []),
                'evidence_ids': result.get('evidence_ids', []), 'confirmed_facts': facts,
                'run_status': result.get('run_status', 'OK'),
                'trace': step(state, 'executor', tools=executed, run_status=result.get('run_status'),
                              recommended=result.get('recommended_ids'))}

    def writer(state):
        result = state['tool_results']
        issues = (state.get('critique') or {}).get('issues') or []
        user = 'Tool results:\n%s' % json.dumps(_tool_digest(result), ensure_ascii=False, indent=1)
        if issues:
            user += '\n\nYour previous draft was rejected for these reasons; fix them:\n- ' + '\n- '.join(issues)
        try:
            reply = model.generate('writer', prompt('agent_writer'), user, schema=WRITER_SCHEMA, max_tokens=700)
            draft = {'explanation': reply.data['explanation'], 'evidence_ids': list(reply.data['evidence_ids']),
                     'source': 'model'}
        except ModelError as exc:
            draft = {'explanation': result.get('message', ''), 'evidence_ids': result.get('evidence_ids', []),
                     'source': 'deterministic fallback (%s)' % exc.kind}
        return {'draft': draft, 'trace': step(state, 'writer', source=draft['source'],
                                               repair=bool(issues) or None)}

    def critic(state):
        result, draft = state['tool_results'], state['draft']
        issues = deterministic_checks(draft['explanation'], draft['evidence_ids'], result)
        decision = 'REPAIR' if issues else 'PASS'
        source = 'code'
        if draft['source'] == 'model':
            user = ('Tool results (authoritative):\n%s\n\nDraft explanation:\n%s\n\nDraft citations: %s'
                    % (json.dumps(_tool_digest(result), ensure_ascii=False, indent=1), draft['explanation'],
                       draft['evidence_ids']))
            try:
                reply = model.generate('critic', prompt('agent_critic'), user, schema=CRITIC_SCHEMA, max_tokens=500,
                                       validate=validate_critique)
                source = 'code + model'
                if reply.data['decision'] == 'REPAIR':
                    issues += [i for i in reply.data['issues'] if i not in issues]
                    decision = 'REPAIR'
                elif reply.data['decision'] == 'CLARIFY' and not issues:
                    decision = 'CLARIFY'
                    issues += reply.data['issues']
            except ModelError as exc:
                source = 'code (model critic unavailable: %s)' % exc.kind
        critique = {'decision': decision, 'issues': issues,
                    'evidence_ids': [e for e in draft['evidence_ids'] if e in result.get('evidence_ids', [])],
                    'source': source}
        return {'critique': critique, 'trace': step(state, 'critic', decision=decision, source=source,
                                                     issues=len(issues) or None)}

    def repair(state):
        count = (state.get('repair_count') or 0) + 1
        return {'repair_count': count, 'trace': step(state, 'executor_repair', attempt=count)}

    def after_planner(state):
        return 'finalize' if state.get('run_status') == 'FAILED_VALIDATION' else 'executor'

    def after_executor(state):
        result = state['tool_results']
        if result.get('missing_fields') or result.get('refused') or result.get('run_status') != 'OK' \
                or not result.get('offers'):
            return 'finalize'                      # clarification pause, refusal, outage or no offers: no drafting
        return 'writer'

    def after_critic(state):
        decision = state['critique']['decision']
        if decision == 'REPAIR' and (state.get('repair_count') or 0) < max_repairs:
            return 'repair'
        return 'finalize'

    def finalize(state):
        return {'trace': step(state, 'finalize', run_status=state.get('run_status'))}

    graph = StateGraph(AgentState)
    for name, node in (('planner', planner), ('executor', executor), ('writer', writer), ('critic', critic),
                       ('repair', repair), ('finalize', finalize)):
        graph.add_node(name, node)
    graph.add_edge(START, 'planner')
    graph.add_conditional_edges('planner', after_planner, ['executor', 'finalize'])
    graph.add_conditional_edges('executor', after_executor, ['writer', 'finalize'])
    graph.add_edge('writer', 'critic')
    graph.add_conditional_edges('critic', after_critic, ['repair', 'finalize'])
    graph.add_edge('repair', 'writer')
    graph.add_edge('finalize', END)
    return graph.compile(checkpointer=checkpointer(context))


def _compose(state):
    """Final response: tool results are authoritative; the model draft is used only after the critic passed it."""
    result = dict(state.get('tool_results') or {})
    limitations = list(result.get('limitations') or []) + list(state.get('limitations') or [])
    critique, draft = state.get('critique') or {}, state.get('draft') or {}
    if state.get('run_status') == 'FAILED_VALIDATION' and not result:
        result = {'route': 'travel_search', 'recommended_ids': [], 'provisional_ids': [], 'noncompliant_ids': [],
                  'offers': [], 'evidence_ids': [], 'missing_fields': [],
                  'message': 'I could not plan this request reliably, so nothing was searched. Please try again.',
                  'action': 'Retry the search.'}
    if draft and critique.get('decision') == 'PASS':
        result['message'] = draft['explanation']
        mismatch = result.get('date_mismatch') or {}
        offered = {d for dates in mismatch.get('offered') or [] for d in dates if d}
        if mismatch and not any(d in result['message'] for d in offered):
            result['message'] += ' ' + mismatch['note']   # the disclosure never depends on the model remembering it
        result['evidence_ids'] = [e for e in draft['evidence_ids'] if e in result.get('evidence_ids', [])] or \
            result.get('evidence_ids', [])
    elif draft:
        limitations.append('The written explanation did not pass review (%s); the verified summary is shown instead.'
                           % '; '.join(critique.get('issues') or ['no detail']))
    from domain.evidence import evidence_for
    result['evidence'] = evidence_for(result.get('evidence_ids', []))
    result.update(run_status=state.get('run_status') or result.get('run_status', 'OK'),
                  limitations=list(dict.fromkeys(limitations)),
                  planner=(state.get('plan') or {}).get('source', 'model'),
                  agent={'session_id': state.get('session_id'), 'intent': state.get('intent'),
                         'repair_count': state.get('repair_count') or 0,
                         'critique': {k: critique.get(k) for k in ('decision', 'issues', 'source')} if critique else None,
                         'trace': state.get('trace') or []})
    return result


def run_travel_agent(payload, context, grade, organization_id, session_id=None):
    """Run the travel_search route through the agent graph. Same inputs and result fields as the deterministic path."""
    thread = session_id or 'ephemeral-%s' % uuid.uuid4().hex
    graph = build_graph(context)
    config = {'configurable': {'thread_id': thread}}
    request = {k: v for k, v in payload.items() if k != 'session_id'}
    state = graph.invoke({'session_id': thread, 'request': request, 'grade': grade, 'organization_id': organization_id,
                          'tool_results': {}, 'draft': {}, 'critique': {}, 'repair_count': 0, 'trace': [],
                          'limitations': [], 'run_status': 'OK', 'missing_fields': []}, config)
    context.events.emit('observation', name='repair_count', value=state.get('repair_count') or 0)
    context.events.emit('agent_run', route='travel_search', repair_count=state.get('repair_count') or 0,
                        steps=[t['step'] for t in state.get('trace') or []])
    if not session_id:
        delete_agent_thread(context, thread)
    return _compose(state)
