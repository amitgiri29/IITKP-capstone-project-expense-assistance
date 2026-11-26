"""SPARKS AI Lab · Expense Policy Assistant (Streamlit). Run: python -m streamlit run ui/app.py

Layout, navigation and theme follow the approved mock-ups (DESIGN.md); features follow the specification.
All arithmetic, policy selection and authorization happen behind the FastAPI service.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from ui import theme  # noqa: E402
from ui.claim_tools import claim_check_csv, claim_check_html, receipt_to_claim_lines  # noqa: E402
from ui.client import ApiFailure, call  # noqa: E402

BRAND = Path(__file__).resolve().parent.parent / 'assets' / 'brand'
LOGO, MARK, FAVICON = (str(BRAND / n) for n in ('sparks-ai-lab-logo.png', 'sparks-ai-lab-mark.png',
                                                  'sparks-ai-lab-favicon.png'))
COMPANY, POLICY = 'SPARKS AI Lab', 'SPARKS AI Lab policy 1.1'

st.set_page_config(page_title='%s · Expense Policy Assistant' % COMPANY, page_icon=FAVICON, layout='wide')
st.logo(LOGO, icon_image=MARK, size='large')
theme.inject()

state = st.session_state
for key, default in (('token', None), ('session', None), ('chat', []), ('assessment', None), ('claim_lines', []),
                     ('search', None), ('pending_question', None), ('goto', None), ('last_ingest', None),
                     ('receipt_extract', None), ('receipt_assessment', None), ('cache', {}),
                     ('signin_notice', None), ('last_error', None), ('claim_draft', None), ('claim_draft_version', 0),
                     ('receipt_confirmed', None), ('reconnect_result', None), ('inspect_result', None)):
    state.setdefault(key, default)


def end_session_locally(notice=None):
    """Forget everything this browser tab holds for the session (the server copy is deleted separately)."""
    for key in ('token', 'session', 'assessment', 'search', 'last_ingest', 'receipt_extract', 'receipt_assessment',
                'pending_question', 'goto', 'claim_draft', 'receipt_confirmed', 'reconnect_result', 'inspect_result'):
        state[key] = None
    state.chat, state.claim_lines, state.cache = [], [], {}
    state.signin_notice = notice


def api(method, path, quiet=False, **kwargs):
    try:
        return call(method, path, token=state.token, **kwargs)
    except ApiFailure as failure:
        body = failure.body
        code = body.get('error_code', 'ERROR')
        state.last_error = body                             # callers that rerun can still show what went wrong
        if code == 'UNAUTHENTICATED' and state.session is not None:
            # expired or deleted session: back to the sign-in screen instead of failing on every page
            end_session_locally('Your session has ended. Please sign in again.')
            st.rerun()
        if not quiet:
            if code == 'RATE_LIMITED':
                st.warning('**Slow down a little** — this session is limited to a few requests per minute. '
                           'Try again in %s seconds.' % body.get('retry_after_seconds', 'a few'),
                           icon=':material/hourglass_top:')
            else:
                st.error('**%s** — %s' % (code.replace('_', ' ').title(), body.get('message', 'Request failed')),
                         icon=':material/error:')
        return None


def cached(path, params=None, quiet=False):
    """Read-only GETs that do not change during a session (caps, library, session summary) are fetched once and kept
    in this tab's session state. Streamlit re-runs the whole script on every click, and the API allows only a few
    requests per session per minute, so re-fetching them on every rerun would exhaust the limit while browsing."""
    key = path + ('?' + '&'.join('%s=%s' % kv for kv in sorted(params.items())) if params else '')
    if key not in state.cache:
        body = api('GET', path, quiet=quiet, params=params) if params else api('GET', path, quiet=quiet)
        if body is None:
            return None                                    # failures are not cached, so the next click retries
        state.cache[key] = body
    return state.cache[key]


def invalidate(prefix):
    """Drop cached reads after a change (an upload, a deletion) so the next view fetches fresh data."""
    state.cache = {k: v for k, v in state.cache.items() if not k.startswith(prefix)}


@st.cache_data(ttl=30, show_spinner=False)
def readiness_status():
    """/ready is public (no session), but it probes the model; one check every 30 s is enough for the status card."""
    try:
        return call('GET', '/ready')
    except ApiFailure as failure:
        return failure.body


@st.cache_data(ttl=300, show_spinner=False)
def directory():
    """The fixed sign-in accounts (public endpoint, no session)."""
    try:
        return call('GET', '/travelers')
    except ApiFailure as failure:
        return {'error': failure.body}


def retrieval_label(components):
    """'Hybrid retrieval' when semantic vectors are live, else 'Keyword retrieval' (honest fallback label)."""
    embeddings = (components or {}).get('embeddings') or {}
    return 'Hybrid retrieval' if embeddings.get('retrieval_mode') == 'hybrid' else 'Keyword retrieval'


MIME = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'md': 'text/markdown', 'markdown': 'text/markdown', 'txt': 'text/plain'}


def ask(question):
    """Queue a question for the assistant and go there (used by the top bar, hero and chips)."""
    if question and question.strip():
        state.pending_question = question.strip()
        state.goto = 'assistant'


def ask_from(key):
    """Widget callback: callbacks run before the script, so the page switch happens on this click (not the next one),
    and the widget is cleared so a chosen suggestion does not fire again on later visits."""
    value = state.get(key)
    state[key] = None if key.endswith('pills') else ''
    ask(value)


# ---- pages --------------------------------------------------------------------------------------------
def home():
    signed_in = state.session is not None
    theme.hero('Travel & expense, reimagined', 'Policy answers, claim checks and travel options in one place',
               'Ask about hotel, flight and local transport limits, check a claim against policy and your budget, and '
               'find compliant travel — with every answer traced to the policy it came from.', 'in one place')
    if signed_in:
        with st.form('hero_ask', border=False):
            c1, c2 = st.columns([6, 1])
            c1.text_input('Ask', placeholder="Ask e.g. 'What is my hotel cap in Bengaluru?'",
                          label_visibility='collapsed', key='hero_q')
            c2.form_submit_button('Evaluate', type='primary', icon=':material/arrow_forward:', width='stretch',
                                  on_click=ask_from, args=('hero_q',))
        st.pills('Try asking', ['Bengaluru hotel cap for my grade', 'Is business class allowed on long flights?',
                                'Do taxi rides share a daily cap?', 'How long do I have to submit a claim?'],
                 key='home_pills', on_change=ask_from, args=('home_pills',))
    columns = st.columns(4)
    cards = [('chat', 'rose', 'Cited policy answers', 'Grounded in %s, with sources you can open and verify.' % POLICY,
              'assistant', 'Ask the assistant'),
             ('clipboard', 'amber', 'Instant claim checks', 'Per-night, per-journey and per-day caps applied exactly, '
              'with exclusions kept separate.', 'claims', 'Review a claim'),
             ('globe', 'cyan', 'Compliant travel', 'Flight and hotel options checked against the caps for your grade.',
              'travel', 'Search travel'),
             ('shield', 'indigo', 'Private by design', 'Your session, your data. Nothing is booked, paid or approved for '
              'you, and ending a session deletes it.', 'limits', 'View your travel band')]
    for column, (icon, tone, title, text, page, link) in zip(columns, cards):
        with column:
            theme.feature(icon, tone, title, text)
            if signed_in:
                st.page_link(PAGES[page], label=link, icon=':material/arrow_forward:')
    limits = cached('/policy/limits', quiet=True) or {'caps': []}
    find = {(c['category'], c['scope'], c['city_tier']): c for c in limits['caps']}

    def cap(category, scope, tier=None):
        item = find.get((category, scope, tier))
        return (theme.money(item['amount'], item['currency']), 'per %s' % item['unit']) if item else ('—', '')
    theme.html('<div class="sp-section"><span class="sp-title">Your limits</span><span class="sp-eyebrow">grade %s · '
               'reviewed registry</span></div>' % theme.escape(limits.get('grade', '')))
    metro = cap('hotel', 'IN', 'metro')
    theme.tiles([('Metro hotel', metro[0], '%s · Bengaluru, Delhi, Mumbai' % metro[1]),
                 ('Other Indian cities', *cap('hotel', 'IN', 'other')), ('Domestic flight', *cap('flight', 'IN')),
                 ('Local transport · India', *cap('local_transport', 'IN'))])
    if state.assessment:
        result = state.assessment['assessment']
        with st.container(key='card-latest'):
            theme.html('<div class="sp-section"><span class="sp-title">Latest claim check</span>%s</div>'
                       % theme.badge(*theme.READINESS.get(result['readiness'], ('neutral', result['readiness']))))
            theme.tiles([('Claimed', theme.money(result['claimed_total_inr']), result['display_label']),
                         ('Policy eligible', theme.money(result['eligible_total_inr']), ''),
                         ('Over category caps', theme.money(result['over_cap_total_inr']), ''),
                         ('Trip budget', theme.BUDGET.get(result['budget_status'], ('', ''))[1], '')])
            st.page_link(PAGES['claims'], label='Open claim check', icon=':material/arrow_forward:')


SUGGESTIONS = ['What is my hotel cap in Bengaluru?', 'Can I fly business class on a 12-hour flight?',
               'Do taxi rides share one daily allowance?', 'What documents do I need for a flight claim?']


CHAT_ERRORS = {
    'PROVIDER_UNAVAILABLE': 'The AI model is not reachable right now. If it runs on Colab, check that the notebook is '
                            'still running and that .env has its current URL, then restart the API. Your limits, claim '
                            'checks and receipts still work without it.',
    'CAPABILITY_UNAVAILABLE': 'No AI model is configured, so policy chat is off. Claims, receipts entered by hand, travel '
                              'search and travel band limits still work.',
    'RATE_LIMITED': 'This session is limited to a few requests per minute. Wait a moment and ask again.',
}


def render_error(turn):
    error = turn.get('error') or {}
    code = error.get('error_code', 'ERROR')
    theme.rule_card('warn', 'Could not answer this question', CHAT_ERRORS.get(code) or error.get('message')
                    or 'The request failed.', tag=code.replace('_', ' '))


def render_answer(turn):
    if 'error' in turn:
        render_error(turn)
        return
    body = turn.get('body') or {}
    meta = '%d source%s' % (len(body.get('evidence') or []), '' if len(body.get('evidence') or []) == 1 else 's')
    markup = theme.ai_card_open('Policy evaluation summary', meta) + theme.paragraphs(turn['text'])
    theme.html(markup + '</div></div>')
    citations = ['%s · %s' % (e['rule_id'], e['section']) for e in (body.get('evidence') or [])][:3]
    if body.get('limit') is not None:
        theme.rule_card('ok', 'Applicable limit', '%s per %s for grade %s, from the reviewed rule registry.' % (
            theme.money(body['limit'], body.get('currency') or ''), (body.get('unit') or '').replace('_', ' '),
            (body.get('applicability') or {}).get('grade', '')), tag='REGISTRY', citations=citations)
    if body.get('refused'):
        theme.rule_card('warn', 'Outside what the assistant can do', body.get('action') or '', tag='DECLINED')
    elif body.get('readiness') in ('HUMAN_REVIEW', 'NEEDS_CLARIFICATION'):
        tone, label = theme.READINESS[body['readiness']]
        detail = 'To answer fully I need: %s.' % ', '.join(body['missing_fields']) if body.get('missing_fields') else \
            (body.get('action') or 'A human reviewer must decide this case.')
        theme.rule_card(tone, label, detail, tag=label.upper(), citations=citations)
    if body.get('evidence'):
        with st.expander('Sources · %d' % len(body['evidence']), icon=':material/menu_book:'):
            for item in body['evidence']:
                origin = 'Library · %s' % item.get('authority') if item.get('origin') == 'library' else 'Core policy %s' % item.get('version', '')
                theme.rule_card('neutral', item['section'], item['text'], tag=origin, citations=[item['rule_id']])


def assistant():
    components = readiness_status().get('components') or {}
    model = components.get('model') or {}
    with st.container(key='card-assistant-head'):
        c1, c2 = st.columns([3, 2])
        c1.markdown('##### Policy Assistant')
        c1.caption('Context: grade %s · %s' % (state.session['traveler']['grade'], model.get('model_id', 'model offline')))
        with c2:
            theme.html('<div class="sp-badges" style="justify-content:flex-end">%s%s</div>'
                       % (theme.badge('ok', 'Grounded · %s' % POLICY), theme.badge('ai', retrieval_label(components))))
    if not state.chat:
        st.pills('Try asking', SUGGESTIONS, key='assistant_pills', on_change=ask_from, args=('assistant_pills',))
    name = state.session['traveler']['display_name'] or state.session['traveler']['traveler_id']
    for turn in state.chat:
        if turn['role'] == 'user':
            theme.user_bubble(name, turn['time'], turn['text'])
        else:
            render_answer(turn)
    question = st.chat_input("Ask a follow-up or a new policy question…") or state.pending_question
    if question:
        state.pending_question = None
        state.chat.append({'role': 'user', 'text': question, 'time': datetime.now().strftime('%H:%M')})
        state.last_error = None
        with st.status('Searching policy and drafting a cited answer…', expanded=False) as status:
            body = api('POST', '/chat', quiet=True, json={'message': question})
            status.update(label='Answer ready' if body else 'Could not answer', state='complete' if body else 'error')
        if body:
            state.chat.append({'role': 'assistant', 'text': body.get('answer', ''), 'body': body})
        else:
            # keep the failure in the thread: st.rerun() below would otherwise wipe a plain st.error at once,
            # leaving the question with no answer and no explanation
            state.chat.append({'role': 'assistant', 'error': state.get('last_error') or {}})
            readiness_status.clear()                        # refresh the AI online/offline badge
        st.rerun()
    c1, c2 = st.columns([1, 3])
    if state.chat and c1.button('Reset thread', icon=':material/refresh:'):
        state.chat = []
        st.rerun()
    theme.html('<div class="sp-badges" style="justify-content:space-between;margin-top:8px">%s<span style="font-size:11.5px;'
               'color:#64748B">Press Enter to send</span></div>' % theme.badge('ok', 'Answers cite %s' % POLICY))


def claims():
    theme.hero('Claims & verification', 'Check a claim before you submit it',
               'Each hotel line is one night, each flight line one journey, each local transport line one charge. '
               'Caps come from the reviewed rule registry.', compact=True)
    draft = state.get('claim_draft') or []
    if draft:
        c1, c2 = st.columns([4, 1])
        c1.info('%d line%s added from your receipts. Check them, then assess the claim.'
                % (len(draft), '' if len(draft) == 1 else 's'), icon=':material/receipt_long:')
        if c2.button('Clear receipt lines', icon=':material/clear_all:', width='stretch'):
            state.claim_draft = None
            state.claim_draft_version += 1
            st.rerun()
    with st.container(key='card-lines'):
        theme.html('<div class="sp-section"><span class="sp-title">Expense lines</span>'
                   '<span class="sp-eyebrow">editable</span></div>')
        sample = [
            {'category': 'hotel', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR', 'amount': 6000.0,
             'excluded_amount': 0.0, 'service_date': date(2026, 11, 14), 'fx_rate': None, 'journey_id': '', 'cabin': '',
             'business_purpose': True, 'receipt_id': ''},
            {'category': 'local_transport', 'country': 'IN', 'city': 'Bengaluru', 'currency': 'INR', 'amount': 2000.0,
             'excluded_amount': 0.0, 'service_date': date(2026, 11, 14), 'fx_rate': None, 'journey_id': '', 'cabin': '',
             'business_purpose': True, 'receipt_id': ''}]
        default_lines = pd.DataFrame(draft or sample, columns=list(sample[0]))   # same column order either way
        # a new key whenever receipt lines are added or cleared, so the grid starts from the new rows
        lines = st.data_editor(default_lines, key='claim-lines-%d' % state.claim_draft_version, num_rows='dynamic',
                               width='stretch', hide_index=True, column_config={
            'category': st.column_config.SelectboxColumn('Category', options=['hotel', 'flight', 'local_transport',
                                                                              'out_of_scope']),
            'country': st.column_config.SelectboxColumn('Country', options=['IN', 'US', 'UK', 'SG']),
            'city': st.column_config.TextColumn('City'),
            'currency': st.column_config.SelectboxColumn('Currency', options=['INR', 'USD', 'GBP', 'SGD']),
            'amount': st.column_config.NumberColumn('Amount', min_value=0.0, format='%.2f'),
            'excluded_amount': st.column_config.NumberColumn('Excluded', min_value=0.0, format='%.2f'),
            'service_date': st.column_config.DateColumn('Service date'),
            'fx_rate': st.column_config.NumberColumn('FX (INR per unit)', help='Documented rate; blank for INR'),
            'journey_id': st.column_config.TextColumn('Journey ID'),
            'cabin': st.column_config.SelectboxColumn('Cabin', options=['', 'economy', 'premium_economy', 'business',
                                                                        'first']),
            'business_purpose': st.column_config.CheckboxColumn('Business'),
            'receipt_id': st.column_config.TextColumn('Receipt ID', help='Used to spot the same receipt claimed twice')})
        if draft:                                           # trip dates follow the receipts: first day to checkout
            days = [d['service_date'] for d in draft]
            first_day = min(days)
            last_day = max(days) + timedelta(days=1 if any(d['category'] == 'hotel' for d in draft) else 0)
        else:
            first_day, last_day = date(2026, 11, 14), date(2026, 11, 15)
        with st.form('claim', border=False):
            c1, c2, c3, c4 = st.columns(4)
            trip_start = c1.date_input(':material/flight_takeoff: Trip start', first_day)
            trip_end = c2.date_input(':material/flight_land: Trip end', last_day)
            submitted_on = c3.date_input(':material/event: Submitted on', date(2026, 11, 16))
            budget = c4.number_input(':material/account_balance_wallet: Trip budget (INR)', min_value=0.0, value=15000.0,
                                     step=500.0, help='0 means no budget comparison')
            t1, t2, t3 = st.columns(3)
            coverage = t1.toggle('Lines cover the whole trip', value=True)
            confirmed = t2.toggle('I confirm these amounts', value=True)
            documents = t3.toggle('Invoices and boarding passes attached', value=True)
            submitted = st.form_submit_button('Assess claim', type='primary', icon=':material/fact_check:')
    if submitted:
        payload_lines = []
        for row in lines.to_dict('records'):
            if row.get('amount') in (None, '') or pd.isna(row.get('amount')):
                continue
            line = {k: v for k, v in row.items() if v not in ('', None) and not (isinstance(v, float) and pd.isna(v))}
            if 'service_date' not in line or pd.isna(line['service_date']):
                st.error('Every line needs a service date.', icon=':material/error:')
                return
            line['service_date'] = str(pd.Timestamp(line['service_date']).date())
            payload_lines.append(line)
        claim = {'trip_start': str(trip_start), 'trip_end': str(trip_end), 'submitted_on': str(submitted_on),
                 'budget_inr': budget or None, 'coverage_complete': coverage, 'user_confirmed': confirmed,
                 'required_documents_present': documents}
        with st.spinner('Applying policy caps…'):
            state.assessment = api('POST', '/claims/review', json={'claim': claim, 'lines': payload_lines})
        state.claim_lines = payload_lines
        state.claim_trip = (str(trip_start), str(trip_end))
    if state.assessment:
        render_claim_check()


def render_claim_check():
    result, evidence = state.assessment['assessment'], state.assessment['evidence']
    caps = {c['cap_id']: c for c in (cached('/policy/limits', quiet=True) or {'caps': []})['caps']}
    sections = {e['rule_id']: e['section'] for e in evidence}
    with st.container(key='card-check'):
        tone, label = theme.READINESS.get(result['readiness'], ('neutral', result['readiness']))
        theme.html('<div class="sp-section"><span><span class="sp-title">Claim check</span> '
                   '<span class="sp-badge mono" style="color:#475569;background:#F1F5F9;border-color:#E2E8F0">%d lines · '
                   'policy 1.1</span></span><span style="font-size:12px;color:#64748B">Overall status: %s</span></div>'
                   % (len(result['lines']), theme.badge(tone, label)))
        left, right = st.columns([5, 7], gap='large')
        with left:
            start, end = getattr(state, 'claim_trip', ('', ''))
            theme.html('<div class="sp-eyebrow">Claim summary</div><div class="sp-title" style="margin:4px 0 2px">Trip %s → %s'
                       '</div><div style="font-size:12px;color:#64748B;margin-bottom:10px">Grade %s · %s</div>'
                       % (theme.escape(start), theme.escape(end), theme.escape(state.session['traveler']['grade']),
                          theme.escape(theme.COMPLIANCE.get(result['compliance_status'], ('', ''))[1])))
            budget = ('Remaining trip budget', theme.money(result['remaining_budget_inr'])) if result['remaining_budget_inr'] \
                else ('Over trip budget', theme.money(result['budget_excess_inr'])) if result['budget_excess_inr'] \
                else ('Trip budget', 'not compared')
            claimed_label = 'Claimed' if result['display_label'] == 'claimed total' else 'Claimed (%s)' % result['display_label']
            theme.ledger([(claimed_label, theme.money(result['claimed_total_inr'])),
                          ('Over category caps', theme.money(result['over_cap_total_inr'])),
                          ('Excluded', theme.money(result['excluded_total_inr'])),
                          ('Rounding adjustment', theme.money(result['rounding_adjustment_inr'])), budget],
                         total=('Policy-eligible amount', theme.money(result['eligible_total_inr'])))
            theme.segmented_bar({k: float(result[f]) if result[f] else 0 for k, f in (
                ('eligible', 'eligible_total_inr'), ('over_cap', 'over_cap_total_inr'), ('excluded', 'excluded_total_inr'))})
            theme.badges([theme.COMPLIANCE.get(result['compliance_status'], ('neutral', '')),
                          theme.BUDGET.get(result['budget_status'], ('neutral', ''))])
            st.caption('An assessment for review, not an approval.')
        with right:
            theme.html('<div class="sp-section"><span class="sp-eyebrow">Policy rule validations</span>'
                       '<span style="font-size:11px;color:#64748B">Registry %s</span></div>'
                       % theme.escape(result['registry']['version']))
            inputs = state.claim_lines
            for index, line in enumerate(result['lines']):
                source = inputs[index] if index < len(inputs) else {}
                place = source.get('city') or source.get('country') or ''
                title = '%s · %s · %s' % (line['category'].replace('_', ' ').capitalize(), place, source.get('service_date', ''))
                claimed, over, excluded = (float(line[k] or 0) for k in ('claimed_inr', 'over_cap_inr', 'excluded_inr'))
                cap = caps.get(line['cap_id'])
                cap_text = ('the %s per %s cap' % (theme.money(cap['amount'], cap['currency']), cap['unit'])) if cap else 'no applicable cap'
                cites = ['%s · %s' % (line['rule_id'], sections.get(line['rule_id'], ''))] if line['rule_id'] else []
                if line['cap_id'] is None:
                    theme.rule_card('neutral' if not excluded else 'bad', title,
                                    'Claimed %s; no cap applies. %s' % (theme.money(claimed),
                                                                       'Excluded from the eligible amount.' if excluded else ''),
                                    tag='EXCLUDED' if excluded else 'NEEDS ATTENTION', citations=cites)
                elif excluded and over:
                    theme.rule_card('bad', title, 'Claimed %s against %s: %s over cap and %s excluded.' % (
                        theme.money(claimed), cap_text, theme.money(over), theme.money(excluded)), tag='OVER CAP + EXCLUDED',
                        citations=cites)
                elif over:
                    theme.rule_card('warn', title, 'Claimed %s against %s. %s over the cap needs human review.' % (
                        theme.money(claimed), cap_text, theme.money(over)), tag='OVER CAP +%s' % theme.money(over),
                        citations=cites)
                elif excluded:
                    theme.rule_card('bad', title, '%s of %s is excluded before the cap is applied.' % (
                        theme.money(excluded), theme.money(claimed)), tag='EXCLUDED', citations=cites)
                else:
                    theme.rule_card('ok', title, 'Claimed %s is within %s.' % (theme.money(claimed), cap_text),
                                    tag='COMPLIANT', citations=cites)
            for issue in result.get('issues', []):
                if issue['reason'] in ('OVER_CATEGORY_CAP', 'EXCLUDED_ITEM'):
                    continue
                tone = 'bad' if issue['readiness'] == 'INPUT_ERROR' else 'warn'
                theme.rule_card(tone, issue['reason'].replace('_', ' ').capitalize(), issue['message'],
                                tag=issue['readiness'].replace('_', ' '))
    if result['provisional_amounts']:
        st.warning('Provisional, not final: %s' % ', '.join('%s %s' % (k.replace('_', ' '), v)
                                                           for k, v in result['provisional_amounts'].items()),
                   icon=':material/hourglass_top:')
    with st.expander('Policy sources · %d' % len(evidence), icon=':material/menu_book:'):
        for item in evidence:
            theme.rule_card('neutral', item['section'], item['text'], tag='Core policy %s' % item['version'],
                            citations=[item['rule_id']])
    trip = getattr(state, 'claim_trip', ('', ''))
    grade = state.session['traveler']['grade']
    name = state.session['traveler'].get('display_name') or state.session['traveler']['traveler_id']
    stem = 'claim-check-%s' % state.assessment.get('assessment_id', 'latest')
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button('Download CSV', claim_check_csv(state.assessment, state.claim_lines, grade, trip),
                       file_name=stem + '.csv', mime='text/csv', icon=':material/table_view:', width='stretch')
    d2.download_button('Download report', claim_check_html(state.assessment, state.claim_lines, grade, trip, name,
                                                           evidence).encode('utf-8'),
                       file_name=stem + '.html', mime='text/html', icon=':material/print:', width='stretch',
                       help='A printable page: open it and use Print > Save as PDF.')


def _blank_receipt():
    return {'merchant': None, 'receipt_id': None, 'category': 'hotel', 'country': 'IN', 'city': None, 'currency': 'INR',
            'service_date': None, 'nights': 1, 'nightly_amounts': None, 'payable_total': None, 'taxes_included': None,
            'excluded_items': [], 'uncertainties': []}


def _receipt_review():
    """Text receipt review: read -> traveler confirms or edits -> Python assessment. No image reading."""
    with st.container(key='card-text-receipt'):
        theme.html('<div class="sp-section"><span class="sp-title">Review a receipt from text</span>'
                   '<span class="sp-eyebrow">paste or upload</span></div>')
        with st.form('receipt_read', clear_on_submit=False, border=False):
            text = st.text_area('Paste the receipt text', height=160,
                                placeholder='Hotel name, dates, room charge, taxes, total payable ...')
            upload = st.file_uploader('…or upload a text receipt or a digital PDF invoice (scans cannot be read)',
                                      type=['txt', 'md', 'pdf', 'docx'])
            c1, c2 = st.columns(2)
            read = c1.form_submit_button('Read receipt', type='primary', icon=':material/document_scanner:')
            manual = c2.form_submit_button('Enter the fields by hand', icon=':material/edit_note:')
        if read:
            with st.spinner('Reading the receipt text …'):
                files = None
                if upload is not None:
                    suffix = upload.name.rsplit('.', 1)[-1].lower()
                    files = {'file': (upload.name, upload.getvalue(), MIME.get(suffix, 'text/plain'))}
                body = api('POST', '/receipts/extract', data={'text': text or ''}, files=files)
            state.receipt_extract = body
            state.receipt_assessment = None
        if manual:
            state.receipt_extract = {'extraction': _blank_receipt(), 'missing_fields': [],
                                     'message': 'Fill in the fields from your receipt, then confirm.'}
            state.receipt_assessment = None

    extract = state.get('receipt_extract')
    if extract and not extract.get('extraction'):
        st.info(extract.get('message', 'Nothing could be read.'), icon=':material/info:')
    if extract and extract.get('extraction'):
        fields = extract['extraction']
        with st.container(key='card-receipt-confirm'):
            theme.html('<div class="sp-section"><span class="sp-title">Check and confirm the fields</span>'
                       '<span class="sp-eyebrow">nothing is calculated until you confirm</span></div>')
            if extract.get('agent'):
                theme.badges([('ai', 'Receipt agent: reader → verifier → your confirmation'),
                              ('neutral', 'Verifier: %s' % ((extract['agent'].get('critique') or {})
                                                            .get('decision') or 'n/a').lower())])
            st.caption(extract.get('message', ''))
            for note in fields.get('uncertainties') or []:
                st.warning(note, icon=':material/warning:')
            if extract.get('missing_fields'):
                st.warning('Missing: %s' % ', '.join(m.replace('_', ' ') for m in extract['missing_fields']),
                           icon=':material/help:')
            with st.form('receipt_confirm', border=False):
                c1, c2, c3 = st.columns(3)
                categories = ['hotel', 'flight', 'local_transport', 'out_of_scope']
                category = c1.selectbox('Category', categories, index=categories.index(fields['category'])
                                        if fields.get('category') in categories else 0,
                                        format_func=lambda v: v.replace('_', ' ').capitalize())
                countries = ['IN', 'US', 'UK', 'SG']
                country = c2.selectbox('Country', countries, index=countries.index(fields['country'])
                                       if fields.get('country') in countries else 0)
                city = c3.text_input('City', fields.get('city') or '')
                currencies = ['INR', 'USD', 'GBP', 'SGD']
                currency = c1.selectbox('Currency', currencies, index=currencies.index(fields['currency'])
                                        if fields.get('currency') in currencies else 0)
                try:
                    default_day = date.fromisoformat(fields.get('service_date') or fields.get('checkin') or '')
                except ValueError:
                    default_day = date.today()
                service_date = c2.date_input('Service / check-in date', default_day)
                total = c3.number_input('Payable total (incl. taxes)', min_value=0.0,
                                        value=float(fields.get('payable_total') or 0), step=100.0)
                nights = c1.number_input('Nights (hotels)', min_value=1, value=int(fields.get('nights') or 1))
                nightly = c2.text_input('Each night\'s amount, comma-separated (hotels)',
                                        ', '.join(str(n) for n in fields.get('nightly_amounts') or []))
                taxes = c3.selectbox('Taxes and fees included?', ['Yes', 'No', 'Not stated'],
                                     index={True: 0, False: 1}.get(fields.get('taxes_included'), 2))
                excluded = st.text_input('Personal extras to exclude (description: amount; …)',
                                         '; '.join('%s: %s' % (i.get('description', ''), i.get('amount'))
                                                   for i in fields.get('excluded_items') or []))
                theme.html('<div class="sp-section"><span class="sp-title">Claim details</span></div>')
                d1, d2, d3, d4 = st.columns(4)
                try:
                    trip_end_default = date.fromisoformat(fields.get('checkout') or '')
                except ValueError:
                    trip_end_default = service_date
                trip_end = d1.date_input('Trip end', trip_end_default)
                submitted_on = d2.date_input('Submitted on', date.today())
                budget = d3.number_input('Trip budget (INR, 0 = none)', min_value=0.0, value=0.0, step=500.0)
                boarding = d4.toggle('Boarding pass attached (flights)', value=False)
                fx = st.number_input('Documented exchange rate, INR per unit (only for non-INR receipts)',
                                     min_value=0.0, value=0.0, help='Totals are reported in INR. A foreign-currency '
                                     'receipt needs the documented rate for its transaction date (policy P11); the '
                                     'assistant never invents one.')
                confirmed = st.checkbox('I confirm these fields match my receipt')
                go = st.form_submit_button('Confirm and assess', type='primary', icon=':material/fact_check:')
            if extract.get('agent'):
                agent_trace(extract['agent'], 'code (fixed receipt plan)',
                            'The model reads the receipt; the verifier (code) checks that every amount, date, '
                            'currency and city is actually written on it. Anything it cannot find is left blank '
                            'for you to fill in. Nothing is calculated until you confirm.')
            if go:
                if not confirmed:
                    st.error('Please tick the confirmation box first.', icon=':material/error:')
                else:
                    items = []
                    for part in [p for p in excluded.split(';') if p.strip()]:
                        desc, _, amount = part.rpartition(':')
                        try:
                            items.append({'description': desc.strip() or part.strip(),
                                          'amount': float(amount.strip().replace(',', ''))})
                        except ValueError:
                            pass
                    try:
                        nightly_list = [float(n.strip().replace(',', '')) for n in nightly.split(',') if n.strip()] \
                            if category == 'hotel' and nightly.strip() else None
                    except ValueError:
                        nightly_list = None
                    payload = {'fields': {'merchant': fields.get('merchant'), 'receipt_id': fields.get('receipt_id'),
                                          'category': category, 'country': country, 'city': city or None,
                                          'currency': currency, 'service_date': str(service_date),
                                          'nights': int(nights) if category == 'hotel' else None,
                                          'nightly_amounts': nightly_list, 'payable_total': total or None,
                                          'taxes_included': {'Yes': True, 'No': False}.get(taxes),
                                          'excluded_items': items, 'user_confirmed': True},
                               'claim': {'trip_end': str(trip_end), 'submitted_on': str(submitted_on),
                                         'budget_inr': budget or None,
                                         'boarding_pass_present': boarding if category == 'flight' else None,
                                         'fx_rate': fx if fx > 0 and currency != 'INR' else None}}
                    with st.spinner('Applying policy caps …'):
                        body = api('POST', '/receipts/assess', json=payload)
                    state.receipt_assessment = body['assessment'] if body else None
                    state.receipt_confirmed = payload if body else None

    result = state.get('receipt_assessment')
    if result:
        with st.container(key='card-receipt-result'):
            tone = {'READY_FOR_REVIEW': 'ok', 'HUMAN_REVIEW': 'warn'}.get(result['readiness'], 'warn')
            theme.badges([(tone, 'Readiness: %s' % result['readiness'].replace('_', ' ').lower()),
                          ('neutral', 'Compliance: %s' % result['compliance_status'].replace('_', ' ').lower()),
                          ('neutral', 'Budget: %s' % result['budget_status'].replace('_', ' ').lower())])
            m1, m2, m3, m4 = st.columns(4)
            for column, label, key in ((m1, 'Claimed (INR)', 'claimed_total_inr'),
                                       (m2, 'Policy-eligible (INR)', 'eligible_total_inr'),
                                       (m3, 'Over the cap (INR)', 'over_cap_total_inr'),
                                       (m4, 'Excluded extras (INR)', 'excluded_total_inr')):
                column.metric(label, result.get(key) or '—')
            st.markdown(result.get('explanation') or result.get('message', ''))
            for note in result.get('limitations') or []:
                st.caption(note)
            if result.get('corrections'):
                st.caption('Calculated with your corrections to: %s' % ', '.join(
                    c.replace('_', ' ') for c in result['corrections']))
            if result.get('ask_for'):
                st.caption('Still needed: %s' % ', '.join(result['ask_for']))
            st.caption('Policy rules applied: %s · This is an assessment for review, not an approval.'
                       % ', '.join(result.get('evidence_ids') or []))
            confirmed = state.get('receipt_confirmed')
            if confirmed and st.button('Add to claim', type='primary', icon=':material/playlist_add:',
                                       help='Turns this receipt into lines on Claims & Verification (one per hotel '
                                            'night), so several receipts can be checked as one claim.'):
                new_lines = receipt_to_claim_lines(confirmed['fields'], confirmed.get('claim'))
                existing = state.get('claim_draft') or []
                receipt_id = confirmed['fields'].get('receipt_id')
                if not new_lines:
                    st.warning('This receipt has no amount to add.', icon=':material/warning:')
                elif receipt_id and any(l.get('receipt_id') == receipt_id for l in existing):
                    st.warning('Receipt %s is already in your claim.' % receipt_id, icon=':material/content_copy:')
                else:
                    state.claim_draft = existing + new_lines
                    state.claim_draft_version += 1
                    state.assessment = None                     # the old claim check no longer matches the lines
                    st.toast('%d line%s added to your claim' % (len(new_lines), '' if len(new_lines) == 1 else 's'),
                             icon=':material/check_circle:')
                    st.switch_page(PAGES['claims'])
            if result.get('agent'):
                agent_trace(result['agent'], 'code (fixed receipt plan)',
                            'Amounts, statuses and readiness are calculated in Python from your confirmed fields. '
                            'The model writes the explanation; the critic checks every amount and rule in it '
                            'against the calculation.')


def receipts():
    theme.hero('Receipts', 'Review a receipt against policy',
               'Paste a receipt or upload a text receipt or digital PDF invoice. The receipt agent reads it, you '
               'check the fields, then the policy caps are applied in Python.', compact=True,
               extra=theme.badge('ok', 'Text receipts only') +
               theme.badge('ai', 'Receipt agent: reader → verifier → calculator → writer → critic'))
    _receipt_review()


def travel():
    theme.hero('Travel search', 'Find options that fit your policy',
               "Every option is checked against your grade's limits. The assistant never books or pays.", compact=True)
    kind = st.segmented_control('Search for', [':material/hotel: Hotels', ':material/flight: Flights'],
                                default=':material/hotel: Hotels', label_visibility='collapsed')
    is_flight = bool(kind) and 'Flights' in kind
    with st.container(key='card-travel'):
        with st.form('travel', border=False):
            criteria = {'search_type': 'flight' if is_flight else 'hotel', 'travelers': 1}
            if is_flight:
                c1, c2, c3 = st.columns(3)
                criteria['origin'] = c1.text_input(':material/flight_takeoff: From', 'BLR')
                criteria['destination'] = c2.text_input(':material/flight_land: To', 'DEL')
                criteria['journey_type'] = c3.selectbox(':material/sync_alt: Trip type', ['one_way', 'return'],
                                                        format_func=lambda v: v.replace('_', ' ').title())
                criteria['departure_date'] = str(c1.date_input(':material/calendar_month: Departure', date.today() + timedelta(days=7)))
                criteria['return_date'] = str(c2.date_input(':material/calendar_month: Return', date.today() + timedelta(days=9)))
                criteria['cabin'] = c3.selectbox(':material/airline_seat_recline_normal: Cabin',
                                                 ['economy', 'premium_economy', 'business', 'first'],
                                                 format_func=lambda v: v.replace('_', ' ').title())
                criteria['country'] = st.selectbox(':material/public: Destination country', ['IN', 'US', 'UK', 'SG'],
                                                   format_func=lambda v: {'IN': 'IN — India (domestic)',
                                                                          'US': 'US — United States',
                                                                          'UK': 'UK — United Kingdom',
                                                                          'SG': 'SG — Singapore'}[v])
                with st.expander('Add details (preferences, exchange rate)', icon=':material/tune:'):
                    criteria['notes'] = st.text_input('Preferences (airline, time of day)', '')
                    fx = st.number_input('Documented exchange rate (INR per unit of the offer currency)', min_value=0.0,
                                         value=0.0, help='Needed to confirm international fares against the INR cap. '
                                                         'Leave 0 if you do not have a documented rate.')
                    if fx > 0:
                        criteria['fx_rate'] = fx
                cap_query = {'category': 'flight', 'country': criteria['country'],
                             'service_date': criteria['departure_date']}
            else:
                c1, c2 = st.columns(2)
                criteria['country'] = c1.selectbox(':material/public: Destination country', ['IN', 'US', 'UK', 'SG'],
                                                   format_func=lambda v: {'IN': 'IN — India', 'US': 'US — United States',
                                                                          'UK': 'UK — United Kingdom',
                                                                          'SG': 'SG — Singapore'}[v])
                criteria['city'] = c2.text_input(':material/location_on: City', 'Bengaluru')
                criteria['checkin'] = str(c1.date_input(':material/calendar_month: Check-in', date.today() + timedelta(days=7)))
                criteria['checkout'] = str(c2.date_input(':material/calendar_month: Check-out', date.today() + timedelta(days=8)))
                criteria['rooms'] = 1
                with st.expander('Add details (meeting venue, preferences)', icon=':material/tune:'):
                    criteria['venue'] = st.text_input('Meeting venue or area (ranks by distance)', '')
                    criteria['notes'] = st.text_input('Other preferences', '')
                cap_query = {'category': 'hotel', 'country': criteria['country'], 'city': criteria['city'],
                             'service_date': criteria['checkin']}
            limits = cached('/policy/limits', params=cap_query, quiet=True) or {}
            applicable = limits.get('applicable')
            cap_badge = theme.badge('ok', 'Your cap here: %s / %s' % (theme.money(applicable['amount'], applicable['currency']),
                                                                      applicable['unit'])) if applicable else \
                theme.badge('neutral', 'No cap resolved for these details')
            b1, b2 = st.columns([3, 1])
            with b1:
                theme.html('<div class="sp-badges" style="margin-top:10px">%s%s%s</div>' % (
                    theme.badge('neutral', '1 adult traveler', dot=False),
                    theme.badge('neutral', '1 room', dot=False) if not is_flight else '', cap_badge))
            go = b2.form_submit_button('Search hotel options' if not is_flight else 'Search flight options',
                                       type='primary', icon=':material/search:', width='stretch')
    if go:
        if is_flight and criteria['journey_type'] == 'one_way':
            criteria.pop('return_date')
        criteria = {k: v for k, v in criteria.items() if v not in ('', None)}
        with st.spinner('Searching providers…'):
            state.search = api('POST', '/travel/search', json=criteria)
    if state.search:
        result = state.search
        agent = result.get('agent') or {}
        fell_back = any('fallback' in str(t.get('source', '')) for t in agent.get('trace') or [])
        badges = [('warn', 'Agents ran on code fallbacks (model unavailable)') if agent and fell_back else
                  ('ai', 'Agents: planner → tools → writer → critic') if agent else
                  ('neutral', 'Deterministic search (no model configured)')]
        if result.get('mode') == 'DEMO':
            badges.append(('warn', 'DEMO offers — not live inventory'))
        if result.get('missing_fields'):
            badges.append(('warn', 'Needs: %s' % ', '.join(f.replace('_', ' ') for f in result['missing_fields'])))
        theme.badges(badges)
        date_note = (result.get('date_mismatch') or {}).get('note')
        st.markdown(result.get('message', '').replace(date_note, '').strip() if date_note else result.get('message', ''))
        if date_note:
            st.warning(date_note, icon=':material/event_busy:')
        for note in result.get('limitations') or []:
            if note != date_note:
                st.caption(note)
        offers = {o['id']: o for o in result.get('offers', [])}
        columns = ['id', 'policy_status', 'departure_date', 'checkin', 'checkout', 'currency', 'total',
                   'comparison_amount', 'nightly_totals', 'cabin',
                   'baggage_kg', 'duration_minutes', 'distance_km', 'freshness', 'reasons', 'retrieved_at', 'expires_at']
        for label, key in (('Recommended', 'recommended_ids'), ('Provisional — cost details missing', 'provisional_ids'),
                           ('Not compliant', 'noncompliant_ids')):
            if result.get(key):
                st.markdown('##### %s' % label)
                rows = [{c: offers[i].get(c) for c in columns if c in offers[i]} for i in result[key] if i in offers]
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        if result.get('evidence_ids'):
            st.caption('Policy rules applied: %s' % ', '.join(result['evidence_ids']))
        if agent:
            agent_trace(agent, result.get('planner', 'model'),
                        'Offer IDs, statuses and amounts always come from the tools. The model writes the '
                        'explanation, and the critic checks it against the tool results.')


def agent_trace(agent, planner, caption):
    """The agent's steps (planner, tools, critic decision, repairs) in an expander."""
    with st.expander('How the agents handled this', icon=':material/account_tree:'):
        critique = agent.get('critique') or {}
        st.markdown('**Planner:** %s · **Critic:** %s · **Repairs:** %d (max 1)'
                    % (planner, critique.get('decision', 'not needed'), agent.get('repair_count', 0)))
        for item in agent.get('trace') or []:
            detail = ', '.join('%s=%s' % (k, v) for k, v in item.items() if k != 'step' and v not in (None, []))
            st.markdown('- `%s` %s' % (item['step'], detail))
        if critique.get('issues'):
            st.caption('Critic issues: ' + ' · '.join(critique['issues']))
        st.caption(caption)


def limits():
    theme.hero('Travel band limits', 'Your travel band at a glance',
               'Every cap for grade %s, straight from the reviewed rule registry. Calculations use exactly these numbers.'
               % state.session['traveler']['grade'], compact=True)
    data = cached('/policy/limits') or {'caps': []}
    names = {'IN': 'India', 'US': 'United States', 'UK': 'United Kingdom', 'SG': 'Singapore', 'INTERNATIONAL': 'International'}
    rows = []
    for c in sorted(data['caps'], key=lambda c: (c['category'], c['scope'] != 'IN', c['scope'], c['city_tier'] or '')):
        where = names.get(c['scope'], c['scope']) + (' · %s cities' % c['city_tier'] if c['city_tier'] else '')
        rows.append((c['category'].replace('_', ' ').capitalize(), where, theme.money(c['amount'], c['currency']),
                     'per ' + c['unit'], c['rule_id'], c['cap_id']))
    theme.table(['Category', 'Where', 'Cap', 'Basis', 'Rule', 'Registry ID'], rows, numeric=(2, 5))
    theme.badges([('ai', 'Registry %s' % data.get('registry_version', '')),
                  ('warn' if data.get('review_status') != 'REVIEWED' else 'ok',
                   'Review status: %s' % (data.get('review_status') or '').replace('_', ' ').lower())])


def library():
    is_admin = state.session['traveler'].get('role') == 'admin'
    theme.hero('Policy documents', '%s policy library' % COMPANY,
               'Documents here are searched and cited by the assistant. Calculation caps always come from the reviewed '
               'rule registry.', compact=True,
               extra=theme.badge('neutral', 'Read only — administrators manage this library') if not is_admin else
               theme.badge('ai', 'Administrator'))
    if is_admin:
        with st.container(key='card-add-policy'):
            theme.html('<div class="sp-section"><span class="sp-title">Add a policy document</span></div>')
            with st.form('add_policy', clear_on_submit=True, border=False):
                title = st.text_input('Title', placeholder='e.g. Conference travel guidance')
                c1, c2, c3 = st.columns(3)
                authority = c1.selectbox('Authority', ['guidance', 'policy'],
                                         help='Supplements policy; never overrides the rule registry.')
                geography = c2.selectbox('Applies to', ['general', 'domestic', 'international'])
                version = c3.text_input('Version', '1.0')
                effective_from = c1.date_input('Effective from', date(2026, 1, 1))
                effective_to = c2.date_input('Effective to', date(2026, 12, 31))
                upload = st.file_uploader('Document (PDF, Word .docx, .txt or .md · up to 10 MB)',
                                          type=['pdf', 'docx', 'txt', 'md', 'markdown'])
                pasted = st.text_area('…or paste the text', height=140)
                add = st.form_submit_button('Upload, chunk & index', type='primary', icon=':material/library_add:')
            if add:
                fields = {'title': title, 'authority': authority, 'geography': geography, 'version': version,
                          'effective_from': str(effective_from), 'effective_to': str(effective_to)}
                with st.spinner('Parsing, chunking and creating vectors…'):
                    if upload is not None:
                        suffix = upload.name.rsplit('.', 1)[-1].lower()
                        result = api('POST', '/admin/policies', data=fields,
                                     files={'file': (upload.name, upload.getvalue(), MIME.get(suffix, 'text/plain'))})
                    else:
                        result = api('POST', '/admin/policies', data=fields | {'text': pasted})
                if result:
                    state.last_ingest = result
                    invalidate('/policy/library')
                    st.toast('%s added — searchable now' % result['document_id'], icon=':material/check_circle:')
            result = state.get('last_ingest')
            if result:
                pages = ' · %d pages' % result['page_count'] if result.get('page_count') else ''
                vectors = ('%d vectors created (%s)' % (result['vectors_created'], result['embedding_model'])
                           if result['retrieval_mode'] == 'hybrid' else 'keyword index only')
                theme.html('<div class="sp-section"><span class="sp-title">%s · %s</span><span class="sp-eyebrow">'
                           '%s</span></div><div class="sp-badges">%s%s%s</div>'
                           % (theme.escape(result['document_id']), theme.escape(result['title']),
                              theme.escape(result['file_type'].upper()),
                              theme.badge('ok', '%d sections%s' % (result['chunk_count'], pages)),
                              theme.badge('ai' if result['retrieval_mode'] == 'hybrid' else 'warn', vectors),
                              theme.badge('ok', 'Searchable now')))
                st.caption(result['message'])
                theme.table(['#', 'Section', 'Page', 'Chars', 'Excerpt'],
                            [(c['position'], c['section'], c['page'] or '—', c['characters'], c['excerpt'] + '…')
                             for c in result['preview']], numeric=(0, 2, 3))
    data = cached('/policy/library')
    if not data:
        return
    theme.html('<div class="sp-section"><span class="sp-title">Added documents</span><span class="sp-eyebrow">%d documents'
               '</span></div>' % len(data['library']))
    if data['library']:
        theme.table(['ID', 'Title', 'Type', 'Version', 'Authority', 'Effective', 'Pages', 'Sections', 'Added by'],
                    [(d['document_id'], d['title'], (d.get('file_type') or 'text').upper(), d['version'], d['authority'],
                      '%s → %s' % (d['effective_from'], d['effective_to']), d.get('page_count') or '—',
                      d['chunk_count'], d['uploaded_by'])
                     for d in data['library']], numeric=(0, 6, 7))
        if is_admin:
            with st.expander('Remove a document', icon=':material/delete:'):
                titles = {d['document_id']: d['title'] for d in data['library']}
                chosen = st.selectbox('Document', list(titles), format_func=lambda i: '%s · %s' % (i, titles[i]))
                sure = st.checkbox('I understand this removes the document and its vectors from search',
                                   key='confirm_remove')
                if st.button('Remove document', icon=':material/delete:', disabled=not sure):
                    if api('DELETE', '/admin/policies/' + chosen) is not None:
                        state.last_ingest = None
                        invalidate('/policy/library')
                        state.pop('confirm_remove', None)
                        st.toast('%s removed from the library' % chosen, icon=':material/check_circle:')
                        st.rerun()
    else:
        st.caption('No documents have been added yet.')
    for core in data['core']:
        with st.expander('Core policy · %s %s · 1 document, %d sections' % (core['title'], core['version'],
                                                                           core['section_count']),
                         icon=':material/gavel:'):
            st.caption('One policy document, split into rule sections. Each section is searched and cited by its rule '
                       'ID (for example P02), and every cap comes from the reviewed rule registry.')
            theme.table(['Rule', 'Section'], [(s['rule_id'], s['title']) for s in core['sections']], numeric=(0,))
    st.caption('Library total: %d documents, %d searchable sections.' % (data.get('document_count', 0),
                                                                          data.get('section_count', 0)))


def reconnect_ai():
    """Admin: ask the API to re-read .env and reconnect the model and embeddings (no restart)."""
    with st.spinner('Re-reading .env and reconnecting the model and embeddings…'):
        result = api('POST', '/admin/reconnect')
    if result:
        state.reconnect_result = result
        readiness_status.clear()
        st.rerun()


def _connection_tab():
    components = readiness_status().get('components') or {}
    model, embeddings = components.get('model') or {}, components.get('embeddings') or {}
    theme.badges([('ok' if model.get('ok') else 'warn', 'Model %s' % ('reachable' if model.get('ok') else 'offline')),
                  ('ai' if embeddings.get('retrieval_mode') == 'hybrid' else 'warn', retrieval_label(components)),
                  ('neutral', 'Provider %s' % model.get('provider', 'unknown'))])
    theme.table(['Part', 'Setting', 'Status'], [
        ('Language model', model.get('model_id') or '—', model.get('error') or ('reachable' if model.get('ok') else
                                                                                 'not configured')),
        ('Embeddings', embeddings.get('active_model') or '—',
         embeddings.get('fallback_reason') or embeddings.get('error') or '%s vectors' % embeddings.get('vectors', 0))])
    st.markdown('**When Colab restarts and prints a new URL:** paste its block into `.env` (replace the old hosted '
                'block), then press **Reconnect AI**. Uploaded documents, sessions and claims are kept.')
    if st.button('Reconnect AI (re-read .env)', type='primary', icon=':material/sync:'):
        reconnect_ai()
    result = state.get('reconnect_result')
    if result:
        tone = 'success' if result['model']['reachable'] and result['embeddings']['retrieval_mode'] == 'hybrid' else 'warning'
        getattr(st, tone)('%s Took %.1f s.' % (result['message'], result['duration_ms'] / 1000),
                          icon=':material/check_circle:' if tone == 'success' else ':material/warning:')
        if result['embeddings'].get('fallback_reason'):
            st.caption(result['embeddings']['fallback_reason'])


def _inspector_tab():
    st.caption('Runs the same search as policy chat (filters, BM25, vectors, reciprocal rank fusion) without calling '
               'the model, so you can see why a passage was or was not used.')
    with st.form('inspect', border=False):
        query = st.text_input('Question', placeholder='e.g. Do taxi rides share one daily allowance?')
        c1, c2 = st.columns(2)
        day = c1.date_input('Service date', date.today())
        geography = c2.selectbox('Geography', ['from the question', 'domestic', 'international'])
        go = st.form_submit_button('Inspect search', type='primary', icon=':material/manage_search:')
    if go and query.strip():
        body = {'query': query.strip(), 'service_date': str(day)}
        if geography != 'from the question':
            body['geography'] = geography
        state.inspect_result = api('POST', '/admin/search-inspect', json=body)
    result = state.get('inspect_result')
    if not result:
        return
    theme.badges([('ai' if result['mode'] == 'hybrid' else 'warn', 'Mode: %s' % result['mode']),
                  ('neutral', 'Searched %d of %d sections' % (result['pool_size'], result['corpus_size'])),
                  ('neutral', 'Keyword %d · semantic %d candidates' % (result['keyword_candidates'],
                                                                       result['semantic_candidates'])),
                  ('ok', 'Top %d go to the model' % result['top_k'])])
    st.caption('Filters: %s · parsed topic: %s · expanded keyword query: “%s”' % (
        ', '.join('%s=%s' % kv for kv in result['applicability'].items() if kv[1]),
        result['parsed'].get('topic') or 'none', result['expanded_query']))
    if result.get('semantic_error'):
        st.warning('Vector search failed: %s' % result['semantic_error'], icon=':material/warning:')
    frame = pd.DataFrame(result['results'])
    if frame.empty:
        st.info('No section matched these filters.', icon=':material/info:')
        return
    st.dataframe(frame[['position', 'selected', 'id', 'section', 'match', 'rrf_score', 'keyword_rank', 'bm25_score',
                        'semantic_rank', 'similarity', 'origin']], hide_index=True, width='stretch',
                 column_config={'selected': st.column_config.CheckboxColumn('Sent to model'),
                                'match': st.column_config.TextColumn('Found by'),
                                'rrf_score': st.column_config.NumberColumn('RRF score', format='%.5f'),
                                'similarity': st.column_config.NumberColumn('Cosine similarity', format='%.4f')})
    with st.expander('Text of the passages sent to the model', icon=':material/article:'):
        for row in result['results'][:result['top_k']]:
            theme.rule_card('neutral', '%s · %s' % (row['id'], row['section']), row['excerpt'] + '…',
                            tag=row['match'].upper())


EVAL_STATUS = {'PASS': 'passed every automatic check, no human review needed',
               'PENDING_REVIEW': 'passed every automatic check; a human rubric is still to be scored',
               'FAIL': 'at least one automatic check failed', 'ERROR': 'the run raised an error',
               'BLOCKED_CAPABILITY': 'needs a capability this build does not have (e.g. reading receipt images)'}


def _evaluation_tab():
    c1, c2 = st.columns([4, 1])
    if c2.button('Refresh', icon=':material/refresh:', width='stretch'):
        invalidate('/admin/evaluations')
    listing = cached('/admin/evaluations') or {'runs': []}
    if not listing['runs']:
        st.info('No evaluation runs yet. Run: `%s`' % listing.get('command', ''), icon=':material/info:')
        return
    runs = {r['run']: r for r in listing['runs']}
    chosen = c1.selectbox('Run', list(runs), format_func=lambda r: '%s · %s · %s' % (
        r, (runs[r]['generated_at'] or '')[:16].replace('T', ' '), 'live model' if runs[r]['model_calls_allowed']
        else 'offline'))
    detail = cached('/admin/evaluations/' + chosen)
    if not detail:
        return
    summary, cases = detail['summary'], pd.DataFrame(detail['cases'])
    automatic = summary.get('automatic_counts') or {}
    runnable = summary['cases_selected'] - automatic.get('BLOCKED_CAPABILITY', 0)
    passed = automatic.get('PASS', 0)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric('Cases', summary['cases_selected'])
    m2.metric('Automatic pass', passed, help='PASS + PENDING_REVIEW: every automatic check passed')
    m3.metric('Pass rate (runnable)', '%.0f%%' % (100 * passed / runnable) if runnable else '—',
              help='Automatic passes divided by cases that could run (blocked cases excluded)')
    m4.metric('Failed / error', automatic.get('FAIL', 0) + automatic.get('ERROR', 0))
    m5.metric('Blocked', automatic.get('BLOCKED_CAPABILITY', 0))
    by_category = pd.DataFrame(summary.get('by_category') or {}).T.fillna(0).astype(int)
    if not by_category.empty:
        st.markdown('##### By category')
        st.dataframe(by_category, width='stretch')
    st.markdown('##### Cases')
    statuses = sorted(cases['status'].dropna().unique()) if not cases.empty else []
    keep = st.multiselect('Status', statuses, default=[s for s in statuses if s in ('FAIL', 'ERROR')] or statuses)
    view = cases[cases['status'].isin(keep)] if keep else cases
    st.dataframe(view[['case_id', 'title', 'category', 'split', 'status', 'checks_passed', 'checks_total',
                       'failed_checks', 'duration_ms', 'error']], hide_index=True, width='stretch')
    st.caption(' · '.join('**%s**: %s' % kv for kv in EVAL_STATUS.items()))
    st.caption('Run a new evaluation from the project folder: `%s`. Expected answers stay in tests/ and are never '
               'shown to the model.' % listing.get('command', ''))


def admin_tools():
    if state.session['traveler'].get('role') != 'admin':
        theme.hero('Admin tools', 'Administrators only', 'This page is for the policy administrator.', compact=True)
        return
    theme.hero('Admin tools', 'Connection, search and quality',
               'Reconnect the AI after a Colab restart, see exactly what the policy search finds, and review golden-case '
               'evaluation results.', compact=True, extra=theme.badge('ai', 'Administrator'))
    connection, inspector, evaluation = st.tabs(['AI connection', 'Search inspector', 'Evaluation results'])
    with connection:
        _connection_tab()
    with inspector:
        _inspector_tab()
    with evaluation:
        _evaluation_tab()


PAGES = {
    'home': st.Page(home, title='Home', icon=':material/home:', default=True),
    'assistant': st.Page(assistant, title='Policy Assistant', icon=':material/forum:', url_path='assistant'),
    'claims': st.Page(claims, title='Claims & Verification', icon=':material/assignment_turned_in:', url_path='claims'),
    'receipts': st.Page(receipts, title='Receipts', icon=':material/photo_camera:', url_path='receipts'),
    'travel': st.Page(travel, title='Travel Search', icon=':material/flight_takeoff:', url_path='travel'),
    'limits': st.Page(limits, title='Travel Band Limits', icon=':material/travel_explore:', url_path='limits'),
    'library': st.Page(library, title='Policy Documents', icon=':material/menu_book:', url_path='library'),
    'admin': st.Page(admin_tools, title='Admin Tools', icon=':material/admin_panel_settings:', url_path='admin'),
}
ADMIN_ONLY = {'admin'}
ROLE_LABEL = {'admin': 'Administrator', 'employee': 'Employee'}


def sign_in():
    """Full-page sign-in. The three accounts are fixed in config/profiles.toml; nobody can type a name, grade or role.
    Starting a session asks the API, which takes grade and role from the server-held directory."""
    theme.hide_sidebar()
    ready = readiness_status()
    model = (ready.get('components') or {}).get('model') or {}
    brand, panel = st.columns([5, 6], gap='large')
    with brand:
        st.image(LOGO, width=190)
        check = theme.svg('check', '#E11D48')
        theme.html(
            '<div class="sp-signin-brand"><span class="sp-tag">%s Expense Policy Assistant</span>'
            '<h1>Travel &amp; expense, <span class="sp-grad">done right</span></h1>'
            '<p>Cited policy answers, exact claim checks and compliant travel options for %s employees.</p>'
            '<ul class="sp-points"><li>%s<span>Answers traced to %s, with sources you can open</span></li>'
            '<li>%s<span>Caps applied exactly from the reviewed rule registry</span></li>'
            '<li>%s<span>Nothing is booked, paid or approved for you; ending a session deletes its data</span></li>'
            '</ul></div>' % (theme.spark_svg(), COMPANY, check, POLICY, check, check))
    with panel:
        with st.container(key='card-signin'):
            theme.html('<div class="sp-signin-head"><div class="sp-title">Sign in</div>'
                       '<p>Choose your account to continue.</p></div>')
            if state.signin_notice:
                st.info(state.signin_notice, icon=':material/info:')
            people = directory()
            if 'error' in people:
                st.error('**The API is not reachable** — %s Start it with run.bat, then reload this page.'
                         % people['error'].get('message', ''), icon=':material/cloud_off:')
                if st.button('Try again', icon=':material/refresh:'):
                    directory.clear()
                    st.rerun()
                return
            for person in people['travelers']:
                with st.container(key='acct-%s' % person['traveler_id']):
                    info, action = st.columns([5, 2])
                    with info:
                        role = person.get('role', 'employee')
                        theme.html('<div class="sp-account">%s<div><div class="n">%s %s</div><div class="t">%s · %s'
                                   '%s</div><div class="e">%s</div></div></div>'
                                   % (theme.avatar(person['display_name'], person['traveler_id']),
                                      theme.escape(person['display_name']),
                                      theme.badge('ai' if role == 'admin' else 'neutral', ROLE_LABEL.get(role, role),
                                                  mono=True, dot=False),
                                      theme.escape(person.get('job_title') or ''),
                                      theme.escape(person.get('department') or ''),
                                      (' · %s' % theme.escape(person['location'])) if person.get('location') else '',
                                      theme.escape(person.get('email') or '')))
                    if action.button('Sign in', key='signin-%s' % person['traveler_id'], type='primary',
                                     width='stretch', icon=':material/login:'):
                        body = api('POST', '/sessions', json={'traveler_id': person['traveler_id']})
                        if body:
                            state.token = body.pop('token')
                            state.session = body
                            state.signin_notice = None
                            state.cache = {}
                            st.rerun()
            ok = model.get('ok')
            theme.html('<div class="sp-signin-note">Fixed demo accounts for a fictional company. Grade and role come '
                       'from the company directory on the server, never from the browser.</div>'
                       '<div class="sp-badges" style="margin-top:10px">%s%s</div>'
                       % (theme.badge('ok' if ok else 'neutral', 'AI online · %s' % model.get('model_id', '')
                                      if ok else 'AI offline'),
                          theme.badge('neutral', POLICY, dot=False)))
    theme.footer(COMPANY)


current = st.navigation(list(PAGES.values()), position='hidden')
if state.session is None:
    # Signed out: only the sign-in screen. The requested page (e.g. /claims) opens right after signing in.
    sign_in()
    st.stop()

# ---- sidebar ---------------------------------------------------------------------------------------------
ready = readiness_status()
model = (ready.get('components') or {}).get('model') or {}
with st.sidebar:
    traveler = state.session['traveler']
    name = traveler.get('display_name') or traveler['traveler_id']
    theme.html('<div class="sp-persona"><div class="k"><span>Signed in</span>%s</div><div class="who">%s<div>'
               '<div class="n">%s</div><div class="r">%s</div></div></div><div class="r" style="margin-top:6px">'
               'Grade %s · %s</div><div class="f"><span>Session expires</span><b>%s UTC</b></div></div>'
               % (theme.badge('ok', 'Session active', mono=True, dot=False),
                  theme.avatar(name, traveler['traveler_id']), theme.escape(name),
                  theme.escape(traveler.get('job_title') or ''), theme.escape(traveler['grade']),
                  theme.escape(ROLE_LABEL.get(traveler.get('role', 'employee'), 'Employee')),
                  theme.escape(state.session['expires_at'][11:16])))
    theme.html('<div style="height:12px"></div>')
    if st.button('Ask the assistant', type='primary', width='stretch', icon=':material/bolt:'):
        state.goto = 'assistant'
    library_data = cached('/policy/library', quiet=True) or {}
    badges = {'assistant': ('ai', 'AI'), 'receipts': ('ok', 'Text')}
    if library_data.get('document_count'):
        badges['library'] = ('neutral', '%d docs' % library_data['document_count'])
    theme.html('<div class="sp-navlabel">Workspace</div>')
    is_admin = traveler.get('role') == 'admin'
    for key, page in PAGES.items():
        if key in ADMIN_ONLY and not is_admin:
            continue
        with st.container(key=('nav-active-%s' if page is current else 'nav-%s') % key):
            st.page_link(page, label=page.title, icon=page.icon)
            if key in badges:
                theme.html('<div class="sp-navbadge">%s</div>' % theme.badge(*badges[key], mono=True, dot=False))
    ok = model.get('ok')
    theme.html('<div class="sp-status"><div class="h"><span class="d" style="background:%s"></span>%s</div><p>%s</p>'
               '<p>Fixed demo accounts. Grade and role come from the company directory on the server.</p></div>'
               % ('#10B981' if ok else '#94A3B8',
                  theme.escape('AI online · %s' % model.get('model_id', '') if ok else 'AI offline'),
                  theme.escape('%s · %s · provider %s' % (POLICY, retrieval_label(ready.get('components')).lower(),
                                                            model.get('provider', 'unknown')))))
    if is_admin and not ok and st.button('Reconnect AI', width='stretch', icon=':material/sync:',
                                         help='Re-read .env (e.g. a new Colab URL) without restarting the API'):
        reconnect_ai()
    if st.button('Sign out · delete session data', width='stretch', icon=':material/logout:'):
        api('DELETE', '/sessions/' + state.session['session_id'], quiet=True)
        end_session_locally('You have signed out and this session\'s data was deleted.')
        st.rerun()

# ---- top bar ------------------------------------------------------------------------------------------------
with st.container(key='topbar'):
    left, right = st.columns([3, 2])
    with left:
        theme.html('<div class="sp-crumbs"><span>%s</span><span style="color:#CBD5E1">/</span><b>%s</b>%s</div>'
                   % (COMPANY, theme.escape(current.title), theme.badge('ok', 'Policy grounded: %s' % POLICY)))
    if state.session is not None and current is not PAGES['assistant']:
        right.text_input('Ask', placeholder='Ask a policy question…', label_visibility='collapsed', key='ask_box',
                         icon=':material/search:', on_change=ask_from, args=('ask_box',))

if state.goto:
    target, state.goto = state.goto, None
    st.switch_page(PAGES[target])

current.run()
theme.footer(COMPANY)
