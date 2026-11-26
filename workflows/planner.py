"""M6 planner and critic contracts: JSON schemas, validation, one format repair, terminal FAILED_VALIDATION.

The planner names registered tools only; anything else (for example a booking tool) is invalid output and is never
executed. A second invalid output ends the run as FAILED_VALIDATION without executing the malformed plan (P20).
"""
import json

from adapters.model import ModelError, _BaseModel, ModelReply
from domain.data import ROOT
from domain.reference import vocabulary

TOOLS = ('validate_criteria', 'search_offers', 'assess_offers', 'retrieve_policy')
INTENTS = ('travel_search', 'booking_request', 'unsupported')
CRITERIA_FIELDS = ('search_type', 'origin', 'destination', 'country', 'city', 'checkin', 'checkout', 'departure_date',
                   'return_date', 'cabin', 'journey_type')

_NULLABLE_STRING = {'type': ['string', 'null']}
PLANNER_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    # No free-text field: with strict JSON decoding a small model can pad an optional-looking field with whitespace
    # until the token limit (observed live with Qwen3-4B), so the plan ends right after missing_fields.
    'required': ['intent', 'tools', 'criteria', 'missing_fields'],
    'properties': {
        'intent': {'type': 'string', 'enum': list(INTENTS)},
        'tools': {'type': 'array', 'items': {'type': 'string', 'enum': list(TOOLS)}},
        'criteria': {'type': 'object', 'additionalProperties': False, 'required': list(CRITERIA_FIELDS),
                     'properties': {f: _NULLABLE_STRING for f in CRITERIA_FIELDS}},
        'missing_fields': {'type': 'array', 'items': {'type': 'string'}},
    },
}
CRITIC_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['decision', 'issues', 'evidence_ids'],
    'properties': {
        'decision': {'type': 'string', 'enum': vocabulary('critic_decision')},
        'issues': {'type': 'array', 'items': {'type': 'string'}},
        'evidence_ids': {'type': 'array', 'items': {'type': 'string'}},
    },
}
WRITER_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['explanation', 'evidence_ids'],
    'properties': {'explanation': {'type': 'string'}, 'evidence_ids': {'type': 'array', 'items': {'type': 'string'}}},
}


def prompt(name):
    return (ROOT / 'prompts' / ('%s.md' % name)).read_text(encoding='utf-8')


def validate_plan(data):
    """Return a problem description, or None when the plan is acceptable to execute."""
    if data.get('intent') not in INTENTS:
        return 'intent must be one of %s' % list(INTENTS)
    tools = data.get('tools')
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        return 'tools must be a list of tool names'
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        return 'unregistered tools %s; only %s exist' % (unknown, list(TOOLS))
    criteria = data.get('criteria')
    if not isinstance(criteria, dict) or any(k not in CRITERIA_FIELDS for k in criteria):
        return 'criteria must be an object with only %s' % list(CRITERIA_FIELDS)
    if not isinstance(data.get('missing_fields', []), list):
        return 'missing_fields must be a list'
    return None


def validate_critique(data):
    if data.get('decision') not in vocabulary('critic_decision'):
        return 'decision must be one of %s' % vocabulary('critic_decision')
    if not isinstance(data.get('issues'), list) or not isinstance(data.get('evidence_ids'), list):
        return 'issues and evidence_ids must be lists'
    return None


def plan_request(model, request, prior_facts):
    """One planner call (plus at most one format repair). Raises ModelError('format') after a second bad output."""
    shown = {k: v for k, v in request.items() if k in CRITERIA_FIELDS + ('travelers', 'rooms', 'message', 'notes')
             and v not in (None, '')}
    user = ('Travel search request (structured fields from the form):\n%s\n\nDetails confirmed earlier in this '
            'conversation:\n%s\n\nPlan the tool calls.' % (json.dumps(shown, ensure_ascii=False, indent=1),
                                                          json.dumps(prior_facts or {}, ensure_ascii=False)))
    reply = model.generate('planner', prompt('agent_planner'), user, schema=PLANNER_SCHEMA, max_tokens=600,
                           validate=validate_plan)
    return reply.data, reply.model


class ReplayModel(_BaseModel):
    """Feeds pre-recorded model outputs through the real generate/validate/repair path (evaluation hook)."""
    provider = 'replay'

    def __init__(self, outputs, events):
        from core.settings import ModelSettings
        super().__init__(ModelSettings(provider='fake', model_id='replay'), None, events)
        self.outputs = list(outputs)

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        if not self.outputs:
            raise ModelError('format', 'no more recorded outputs')
        value = self.outputs.pop(0)
        text = value if isinstance(value, str) else json.dumps(value)
        return ModelReply(text=text, model='replay', provider='replay', stop_reason='end_turn', usage={})


def parse_planner_output(payload, context):
    """Evaluation entrypoint parse_planner_output (GT116): recorded outputs go through the same validation and single
    format repair as live planner/critic calls. Invalid twice -> FAILED_VALIDATION and no tool is executed."""
    stage = payload.get('stage') or 'planner'
    model = ReplayModel(payload.get('injected_model_outputs') or [], context.events)
    schema, validate = (CRITIC_SCHEMA, validate_critique) if stage == 'critic' else (PLANNER_SCHEMA, validate_plan)
    try:
        reply = model.generate(stage, prompt('agent_critic' if stage == 'critic' else 'agent_planner'),
                               'Recorded output under test.', schema=schema, validate=validate)
    except ModelError as exc:
        return {'run_status': 'FAILED_VALIDATION', 'stage': stage, 'executed_tools': [],
                'message': 'The %s output was invalid after one repair, so nothing was executed.' % stage,
                'limitations': [str(exc)]}
    return {'run_status': 'OK', 'stage': stage, 'parsed': reply.data, 'executed_tools': [],
            'message': 'The %s output is valid.' % stage}
