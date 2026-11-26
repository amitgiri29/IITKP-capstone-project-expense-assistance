"""Per-case harness: a fresh authorized application context, harness-only seeding and canaries,
and observations derived from captured events (TEST_PROTOCOL sections 2 and 5)."""
import inspect
import json
import tempfile
from pathlib import Path

from core.context import build_context
from core.settings import load_settings

APP_SETUP_KEYS = {'base_claim_fixture', 'overrides'}


class CaseHarness:
    def __init__(self, case, allow_model=False, embeddings=False):
        self.case = case
        self.setup = case.get('setup') or {}
        # ignore_cleanup_errors: a file still locked on Windows must not abort a 120-case run
        self._tmp = tempfile.TemporaryDirectory(prefix='golden-%s-' % case['id'], ignore_cleanup_errors=True)
        settings = load_settings()
        secret_canary = self.setup.get('synthetic_secret_canary')
        overrides = {}
        if secret_canary:
            overrides = {settings.model.api_key_env: secret_canary, settings.travel.api_key_env: secret_canary}
        settings = settings.with_overrides(data_dir=Path(self._tmp.name), secret_overrides=overrides)
        self.context = build_context(settings=settings, with_model=allow_model, with_embeddings=embeddings)
        self.context.system_prompt_suffix = self.setup.get('synthetic_hidden_prompt_canary', '')
        self._seed()

    def _seed(self):
        store, now = self.context.store, self.context.clock()
        for record in self.setup.get('seed_records', []):
            if store.get_session(record['session_id']) is None:
                traveler = next(iter(self.context.travelers))
                store.create_session(record['organization_id'], traveler, self.context.travelers[traveler]['grade'],
                                     now, self.context.settings.session_ttl_hours, session_id=record['session_id'])
            store.add_receipt(record['session_id'], record['organization_id'], None, None, None, now,
                              image_id=record.get('receipt_id'), merchant=record.get('merchant'),
                              amount=record.get('amount'))

    def call(self, function, payload):
        if len(inspect.signature(function).parameters) >= 2:
            return function(payload, self.context)
        return function(payload)

    def secret_canaries(self):
        return [v for k, v in self.setup.items() if 'canary' in k and isinstance(v, str)]

    def record_canaries(self):
        return [[str(v) for k, v in r.items() if k in ('merchant', 'receipt_id') and v]
                for r in self.setup.get('seed_records', [])]

    def observations(self, envelope):
        events = self.context.events.all()
        haystack = json.dumps([envelope.get('result'), envelope.get('response_text'), events], default=str)
        attempts = {}
        for event in self.context.events.all('provider_call'):
            key = event.get('operation', 'default')
            attempts[key] = attempts.get(key, 0) + 1
        statuses = [e['status'] for e in self.context.events.all('http_response')]
        observed = {
            'model_calls': self.context.events.count('model_call'),
            'provider_calls': self.context.events.count('provider_call'),
            'maximum_provider_attempts': max(attempts.values()) if attempts else 0,
            'tool_side_effects': self.context.events.count('tool_side_effect'),
            'booking_performed': self.context.events.count('booking') > 0,
            'format_repair_attempts': self.context.events.count('format_repair'),
            'leaked_records': sum(1 for values in self.record_canaries() if any(v in haystack for v in values)),
            'disclose_secrets': any(c in haystack for c in self.secret_canaries()),
        }
        if statuses:
            observed['http_status'] = statuses[-1]
        for event in self.context.events.all('observation'):
            observed[event['name']] = event['value']
        return observed

    def close(self):
        from workflows.agent_graph import close_checkpointer
        close_checkpointer(self.context)          # the per-case agent checkpoint database lives in the temp folder
        self.context.store.close()
        self._tmp.cleanup()
