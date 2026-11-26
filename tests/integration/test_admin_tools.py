"""Admin tools: search inspector, reconnect without restart, evaluation results; and receipt lines in a claim."""
import json

import pytest

from ui.claim_tools import receipt_to_claim_lines


@pytest.fixture
def admin(client):
    body = client.post('/sessions', json={'traveler_id': 'admin-P'}).json()
    return {'Authorization': 'Bearer ' + body['token']}


def test_admin_tools_are_admin_only(client, session):
    for response in (client.post('/admin/search-inspect', headers=session['headers'], json={'query': 'hotel cap'}),
                     client.post('/admin/reconnect', headers=session['headers']),
                     client.get('/admin/evaluations', headers=session['headers'])):
        assert response.status_code == 403


def test_search_inspector_shows_each_ranking_and_the_top_k(client, admin):
    body = client.post('/admin/search-inspect', headers=admin,
                       json={'query': 'What is my hotel cap in Bengaluru?', 'service_date': '2026-11-15'}).json()
    assert body['mode'] == 'bm25_only' and body['top_k'] == 6           # tests run without embeddings
    assert body['applicability']['geography'] == 'domestic'             # parsed from the city
    top = [r for r in body['results'] if r['selected']]
    assert len(top) == 6 and 'P02' in [r['id'] for r in top]
    assert all(r['keyword_rank'] for r in top) and all(r['semantic_rank'] is None for r in top)
    assert 'nightly' in body['expanded_query']                           # query expansion is visible


def test_reconnect_rebuilds_model_and_index_without_restart(client, admin, context, monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda *a, **k: None)     # never read this machine's .env in tests
    monkeypatch.setattr('core.context.load_settings', lambda: context.settings)
    monkeypatch.setattr('adapters.model.build_model', lambda ctx: None)
    monkeypatch.setattr('adapters.embeddings.build_embeddings', lambda ctx: None)
    before = context.retriever
    body = client.post('/admin/reconnect', headers=admin).json()
    assert context.retriever is not before and len(context.retriever.documents) == len(before.documents)
    assert body['model']['reachable'] is False and 'no model configured' in body['model']['error']
    assert body['embeddings']['retrieval_mode'] == 'bm25_only'
    assert context.events.count('providers_reconnected') == 1
    assert client.get('/ready').json()['components']['model']['ok'] is False


def test_evaluation_results_are_listed_without_answer_keys(client, admin, context):
    run = context.settings.data_dir / 'evaluation' / 'run-1'
    run.mkdir(parents=True)
    (run / 'summary.json').write_text(json.dumps({'generated_at': '2026-11-20T10:00:00+00:00', 'cases_selected': 1,
                                                  'model_calls_allowed': True, 'status_counts': {'PASS': 1},
                                                  'automatic_counts': {'PASS': 1}, 'by_category': {}}))
    (run / 'envelopes.jsonl').write_text(json.dumps({'case_id': 'GT001', 'run_metadata': {
        'status': 'PASS', 'automatic_status': 'PASS', 'duration_ms': 12.5}}) + '\n')
    (run / 'checks.jsonl').write_text(json.dumps({'case_id': 'GT001', 'error': None,
                                                  'checks': [{'path': '/result/limit', 'passed': True}]}) + '\n')
    assert [r['run'] for r in client.get('/admin/evaluations', headers=admin).json()['runs']] == ['run-1']
    detail = client.get('/admin/evaluations/run-1', headers=admin).json()
    case = detail['cases'][0]
    assert case['title'] == 'Metro hotel employee' and case['checks_passed'] == 1
    assert 'expected' not in json.dumps(detail)
    assert client.get('/admin/evaluations/..', headers=admin).status_code == 404


def test_receipt_lines_are_accepted_by_claim_review(client, session):
    lines = receipt_to_claim_lines({'category': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR',
                                    'service_date': '2026-11-14', 'nights': 2, 'payable_total': 11000,
                                    'receipt_id': 'R-7', 'excluded_items': [{'amount': 500}]})
    payload = [{k: (str(v) if k == 'service_date' else v) for k, v in l.items() if v not in ('', None)} for l in lines]
    body = client.post('/claims/review', headers=session['headers'], json={
        'claim': {'trip_start': '2026-11-14', 'trip_end': '2026-11-16', 'submitted_on': '2026-11-17',
                  'user_confirmed': True, 'required_documents_present': True}, 'lines': payload}).json()
    result = body['assessment']
    assert result['claimed_total_inr'] == '11000.00' and result['excluded_total_inr'] == '500.00'
    assert len(result['lines']) == 2
