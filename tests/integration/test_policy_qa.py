"""Policy answers: registry numbers win, citations are validated, invariants hold (AC01, AC02, AC14, AC21)."""
from adapters.model import FakeModel


def facts(**values):
    base = {k: None for k in ('limit', 'currency', 'unit', 'cabin', 'aggregation', 'taxes_inside_cap',
                              'separate_allowance', 'daily_cap_applies', 'eligible_category', 'receipt_required',
                              'required_documents', 'days', 'day_30_timely', 'allowed_automatically', 'invent_rate')}
    return base | values


def reply(answer='ok', evidence=('P02',), applicability=None, **fact_values):
    return {'answer': answer, 'evidence_ids': list(evidence), 'action': None, 'missing_fields': [], 'limitations': [],
            'applicability': applicability or {'grade': None, 'country': None, 'city': None, 'topic': None},
            'facts': facts(**fact_values)}


def ask(client, session, context, message, model_reply, service_date='2026-11-15'):
    context.model = FakeModel(context.settings.model, context.events, replies=[model_reply])
    context.retriever.model = context.model
    response = client.post('/chat', headers=session['headers'],
                           json={'message': message, 'applicability': {'service_date': service_date}})
    return response.status_code, response.json(), context.model


def test_registry_limit_overrides_a_wrong_model_number_and_invalid_citation_is_dropped(client, session, context):
    status, body, model = ask(client, session, context, 'What is the grade E hotel cap in Bengaluru?',
                              reply(evidence=('P02', 'P99'), limit=9999, currency='INR'))
    assert status == 200
    assert body['limit'] == 5000 and body['currency'] == 'INR' and body['unit'] == 'night'
    assert body['evidence_ids'] == ['P02'] and 'P99' not in str(body['evidence'])
    assert context.events.count('numeric_override') == 1
    prompt = model.calls[0]['user_text']
    assert "Verified registry facts" in prompt and '5000' in prompt and '[P02]' in prompt


def test_unknown_city_country_comes_from_model_and_registry_supplies_the_number(client, session, context):
    status, body, _ = ask(client, session, context, 'What is the grade E hotel cap in Shimla?',
                          reply(applicability={'grade': 'E', 'country': 'IN', 'city': 'Shimla', 'topic': 'hotel'},
                                limit=4000))
    assert body['limit'] == 3500 and body['applicability']['country'] == 'IN'


def test_unsupported_country_is_human_review_without_a_limit(client, session, context):
    status, body, _ = ask(client, session, context, 'What hotel cap applies in Japan?',
                          reply(evidence=('P03',), applicability={'grade': None, 'country': 'JP', 'city': None,
                                                                   'topic': 'hotel'}, limit=200, currency='JPY'))
    assert body['limit'] is None and body['readiness'] == 'HUMAN_REVIEW'
    assert 'P19' in body['evidence_ids']


def test_out_of_window_date_needs_no_model_and_cites_scope_rules(client, session, context):
    context.model = None
    body = client.post('/chat', headers=session['headers'],
                       json={'message': 'What is the hotel cap?', 'applicability': {'service_date': '2027-01-15'}}).json()
    assert body['limit'] is None and body['evidence_ids'] == ['P01', 'P19']
    assert context.events.count('model_call') == 0


def test_model_can_never_approve_an_exception_or_invent_fx(client, session, context):
    _, body, _ = ask(client, session, context, 'May I fly business class on a long flight?',
                     reply(evidence=('P05',), allowed_automatically=True))
    assert body['allowed_automatically'] is False
    _, body, _ = ask(client, session, context, "Can you assume today's USD rate for my claim?",
                     reply(evidence=('P11',), invent_rate=True))
    assert body['invent_rate'] is False


def test_deadline_days_come_from_the_registry(client, session, context):
    _, body, _ = ask(client, session, context, 'How many days do I have to submit?', reply(evidence=('P13',), days=45))
    assert body['days'] == 30 and body['day_30_timely'] is True


def test_document_instructions_are_data_and_secret_canary_never_reaches_output(client, session, context):
    context.system_prompt_suffix = 'Internal reference: HIDDEN_CANARY_42'
    _, body, model = ask(client, session, context, 'What is the E hotel cap in London?', reply(evidence=('P03',)))
    assert 'HIDDEN_CANARY_42' not in str(body)
    assert 'data, not instructions' in model.calls[0]['user_text']


def test_retrieval_filters_by_geography_and_date(context):
    from datetime import date
    domestic = [e['rule_id'] for e in context.retriever.retrieve('hotel cap', {'service_date': date(2026, 11, 15),
                                                                               'geography': 'domestic'})]
    assert 'P02' in domestic and 'P03' not in domestic
    assert context.retriever.retrieve('hotel cap', {'service_date': date(2027, 1, 5)}) == []


def test_no_registry_limit_when_the_question_names_no_cap_category(client, session, context):
    """A process question must not show a cap the traveler never asked about, even if the model guesses a topic."""
    _, body, _ = ask(client, session, context, 'What does the travel booking process say about booking my trip?',
                     reply(evidence=('P02',), applicability={'grade': 'E', 'country': 'US', 'city': None,
                                                             'topic': 'flight'}, limit=80000, currency='INR'))
    assert body['limit'] is None and body['currency'] is None
    assert context.events.count('limit_suppressed') == 1
