"""M5 travel search and M6 planner/executor/critic graph, with a scripted fake model (no network, no credits)."""
import json

import pytest

from adapters.model import FakeModel, ModelError
from core.settings import ModelSettings
from workflows.agent_graph import run_travel_agent
from workflows.planner import parse_planner_output
from workflows.travel_search import run_tools, search_and_assess_offers

HOTEL = {'search_type': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'checkin': '2026-11-20',
         'checkout': '2026-11-21', 'rooms': 1, 'travelers': 1, 'fixture_paths': ['fixtures/search/search_02.json']}
FLIGHT = {'search_type': 'flight', 'country': 'IN', 'origin': 'BLR', 'destination': 'DEL',
          'departure_date': '2026-11-20', 'cabin': 'economy', 'journey_type': 'one_way', 'travelers': 1,
          'fixture_paths': ['fixtures/search/search_01.json']}
GOOD_PLAN = {'intent': 'travel_search', 'tools': ['validate_criteria', 'search_offers', 'assess_offers',
                                                  'retrieve_policy'],
             'criteria': {k: None for k in ('search_type', 'origin', 'destination', 'country', 'city', 'checkin',
                                            'checkout', 'departure_date', 'return_date', 'cabin', 'journey_type')},
             'missing_fields': []}


def scripted(context, planner=None, writers=(), critics=(), fail=None):
    """A fake model answering by role. Lists are consumed in order; the last item repeats."""
    queues = {'writer': list(writers), 'critic': list(critics)}

    def respond(purpose, user_text, schema):
        if fail and purpose in fail:
            return fail[purpose]
        if purpose == 'planner':
            return planner if planner is not None else GOOD_PLAN
        queue = queues[purpose]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    context.model = FakeModel(ModelSettings(provider='fake', model_id='fake'), context.events, responder=respond)
    return context.model


def writer(text, ids=('P02', 'P16')):
    return {'explanation': text, 'evidence_ids': list(ids)}


PASS = {'decision': 'PASS', 'issues': [], 'evidence_ids': ['P02']}
REPAIR = {'decision': 'REPAIR', 'issues': ['H1 is described as compliant but is provisional'], 'evidence_ids': []}


# ---- M5: deterministic tools ------------------------------------------------------------------------------------
def test_deterministic_path_without_model(context):
    result = search_and_assess_offers(HOTEL | {'grade': 'E'}, context)
    assert result['recommended_ids'] == ['H2', 'H1', 'H3'] and result['mode'] == 'DEMO'
    assert result['planner'].startswith('deterministic')
    assert context.events.count('model_call') == 0


def test_missing_date_asks_before_any_provider_call(context):
    result = run_tools(FLIGHT | {'departure_date': None}, context, 'E', 'demo-company')
    assert result['missing_fields'] == ['departure_date'] and context.events.count('provider_call') == 0


def test_provider_outage_is_bounded_and_reported(context):
    result = run_tools(FLIGHT | {'injected_error': 'timeout on initial request and both retries'}, context, 'E',
                       'demo-company')
    assert result['run_status'] == 'PROVIDER_UNAVAILABLE' and result['recommended_ids'] == []
    assert context.events.count('provider_call') == 3


def test_booking_is_declined_but_information_shown(context):
    result = run_tools(FLIGHT | {'message': 'Book F1 and charge my card'}, context, 'E', 'demo-company')
    assert result['booking_declined'] and result['recommended_ids']
    assert context.events.count('booking') == 0


def test_api_uses_the_session_grade_and_refuses_test_hooks(client, session):
    ok = client.post('/travel/search', headers=session['headers'],
                     json={k: v for k, v in HOTEL.items() if k != 'fixture_paths'})
    assert ok.status_code == 200 and ok.json()['mode'] == 'DEMO' and ok.json()['criteria']['grade'] == 'E'
    hooked = client.post('/travel/search', headers=session['headers'], json=HOTEL)    # fixture_paths not allowed
    assert hooked.status_code in (400, 422)


# ---- M6: agent graph --------------------------------------------------------------------------------------------
def test_agent_pass_uses_the_model_draft_and_tool_ids(context):
    scripted(context, writers=[writer('H2, H1 and H3 are within policy. These are DEMO offers.')], critics=[PASS])
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['recommended_ids'] == ['H2', 'H1', 'H3']
    assert result['message'].startswith('H2, H1 and H3') and result['agent']['repair_count'] == 0
    assert [t['step'] for t in result['agent']['trace']] == ['planner', 'executor', 'writer', 'critic', 'finalize']


def test_agent_repairs_once_then_passes(context):
    scripted(context, writers=[writer('First draft. These are DEMO offers.'),
                               writer('Second draft: H2, H1, H3. These are DEMO offers.')], critics=[REPAIR, PASS])
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['agent']['repair_count'] == 1 and result['message'].startswith('Second draft')


def test_agent_never_repairs_more_than_once_and_falls_back(context):
    scripted(context, writers=[writer('Still wrong. These are DEMO offers.')], critics=[REPAIR])
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['agent']['repair_count'] == 1
    assert result['message'].startswith('Recommended')                       # verified deterministic summary
    assert any('did not pass review' in l for l in result['limitations'])
    assert result['recommended_ids'] == ['H2', 'H1', 'H3']


def test_critic_catches_invented_offers_and_cannot_change_results(context):
    scripted(context, writers=[writer('Book H9 at a special rate. These are DEMO offers.')], critics=[PASS])
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['agent']['critique']['decision'] == 'REPAIR'               # code check, despite the model PASS
    assert 'H9' not in result['message'] and result['recommended_ids'] == ['H2', 'H1', 'H3']


def test_invalid_planner_output_twice_stops_without_tools(context):
    scripted(context, planner={'intent': 'travel_search', 'tools': ['book_flight'], 'criteria': {},
                               'missing_fields': []})
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['run_status'] == 'FAILED_VALIDATION'
    assert context.events.count('provider_call') == 0 and context.events.count('format_repair') == 1


def test_model_outage_falls_back_and_is_disclosed(context):
    outage = ModelError('provider', 'Colab is down')
    scripted(context, writers=[outage], critics=[outage], fail={'planner': outage, 'writer': outage})
    result = run_travel_agent(HOTEL, context, 'E', 'demo-company')
    assert result['recommended_ids'] == ['H2', 'H1', 'H3']
    assert result['planner'] == 'deterministic fallback'
    assert any('unavailable' in l for l in result['limitations'])


def test_clarification_resumes_from_the_session_checkpoint(context):
    scripted(context, writers=[writer('F2 is the cheapest compliant option. These are DEMO offers.')], critics=[PASS])
    first = run_travel_agent(FLIGHT | {'departure_date': None}, context, 'E', 'demo-company', session_id='s-1')
    assert first['missing_fields'] == ['departure_date'] and context.events.count('provider_call') == 0
    second = run_travel_agent({'search_type': 'flight', 'departure_date': '2026-11-20',
                               'fixture_paths': FLIGHT['fixture_paths']}, context, 'E', 'demo-company',
                              session_id='s-1')
    assert second['recommended_ids'] and second['criteria']['origin'] == 'BLR'
    planner_step = next(t for t in second['agent']['trace'] if t['step'] == 'planner')
    assert planner_step['filled_from']['origin'] == 'earlier in this conversation'


def test_a_different_search_does_not_inherit_earlier_details(context):
    scripted(context, writers=[writer('Done. These are DEMO offers.')], critics=[PASS])
    run_travel_agent(FLIGHT, context, 'E', 'demo-company', session_id='s-2')
    result = run_travel_agent({'search_type': 'hotel', 'checkin': '2026-11-20', 'checkout': '2026-11-21'}, context,
                              'E', 'demo-company', session_id='s-2')
    assert 'country' in result['missing_fields'] and 'city' in result['missing_fields']


def test_planner_fills_missing_fields_only_from_the_message(context):
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan['criteria'].update(destination='DEL', origin='XXX')                  # origin is already on the form
    scripted(context, planner=plan, writers=[writer('F2 first. These are DEMO offers.')], critics=[PASS])
    result = run_travel_agent(FLIGHT | {'destination': None, 'message': 'to Delhi'}, context, 'E', 'demo-company')
    assert result['criteria']['destination'] == 'DEL' and result['criteria']['origin'] == 'BLR'


def test_deleting_the_session_deletes_agent_checkpoints(client, session, context):
    from workflows.agent_graph import checkpointer
    scripted(context, writers=[writer('Done. These are DEMO offers.')], critics=[PASS])
    run_travel_agent(HOTEL, context, 'E', 'demo-company', session_id=session['session_id'])
    config = {'configurable': {'thread_id': session['session_id']}}
    assert checkpointer(context).get_tuple(config) is not None
    assert client.delete('/sessions/' + session['session_id'], headers=session['headers']).status_code == 204
    assert checkpointer(context).get_tuple(config) is None


def test_offers_for_other_dates_are_disclosed(context):
    same = run_tools(FLIGHT, context, 'E', 'demo-company')
    assert same['date_mismatch'] is None
    other = run_tools(FLIGHT | {'departure_date': '2026-12-10'}, context, 'E', 'demo-company')
    note = other['date_mismatch']['note']
    assert other['date_mismatch']['offered'] == [['2026-11-20']] and '2026-12-10' in note
    assert note in other['message'] and note in other['limitations'] and other['recommended_ids']


def test_critic_rejects_a_draft_that_moves_demo_offers_to_the_requested_date(context):
    scripted(context, writers=[writer('F2 and F1 fly on 2026-12-10 as requested. These are DEMO offers.', ('P04',)),
                               writer('F2 and F1 are DEMO offers for 2026-11-20, not your date.', ('P04',))],
             critics=[PASS])
    result = run_travel_agent(FLIGHT | {'departure_date': '2026-12-10'}, context, 'E', 'demo-company')
    assert result['agent']['repair_count'] == 1 and result['agent']['critique']['decision'] == 'PASS'
    assert result['message'].startswith('F2 and F1 are DEMO offers for 2026-11-20')
    assert result['date_mismatch']['note'] not in result['message']         # the draft already disclosed the date


def test_date_note_is_added_when_a_passing_draft_leaves_the_dates_out(context):
    scripted(context, writers=[writer('F2 is the cheapest compliant option. These are DEMO offers.', ('P04',))],
             critics=[PASS])
    result = run_travel_agent(FLIGHT | {'departure_date': '2026-12-10'}, context, 'E', 'demo-company')
    assert result['agent']['critique']['decision'] == 'PASS'
    assert result['message'].endswith(result['date_mismatch']['note'])


# ---- planner output contract (AC15) -----------------------------------------------------------------------------
def test_parse_planner_output_accepts_a_valid_plan(context):
    assert parse_planner_output({'injected_model_outputs': [GOOD_PLAN]}, context)['run_status'] == 'OK'


@pytest.mark.parametrize('outputs', [['not json', 'still not json'],
                                     [GOOD_PLAN | {'tools': ['book_flight']}, GOOD_PLAN | {'tools': ['pay']}]])
def test_parse_planner_output_fails_after_one_repair(context, outputs):
    result = parse_planner_output({'injected_model_outputs': outputs}, context)
    assert result['run_status'] == 'FAILED_VALIDATION' and result['executed_tools'] == []
    assert context.events.count('format_repair') == 1 and context.events.count('tool_side_effect') == 0


def test_parse_planner_output_repair_can_succeed(context):
    result = parse_planner_output({'injected_model_outputs': ['broken', GOOD_PLAN]}, context)
    assert result['run_status'] == 'OK' and context.events.count('format_repair') == 1
