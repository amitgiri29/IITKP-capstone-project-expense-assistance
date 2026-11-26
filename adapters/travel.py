"""Travel search providers (TravelPort). Search and refresh only: there is no booking or payment method (P18).

Providers (config/settings.toml [travel].provider):
  fixture  offline DEMO offers from fixtures/search (labelled DEMO, never described as live inventory, P17)
  http     an external read-only search API at travel.base_url (not yet exercised against a live endpoint)

Every attempt is recorded as a 'provider_call' event. Attempts are bounded by IMPLEMENTATION_CONTRACT.json
operational_defaults.provider_attempts_per_operation (one attempt plus at most two retries).
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from domain.data import ROOT


def _attempt_limit():
    return json.loads((ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text(encoding='utf-8'))[
        'operational_defaults']['provider_attempts_per_operation']


class ProviderUnavailable(Exception):
    """The provider failed after the bounded attempts. Never replaced by invented offers."""


@dataclass
class SearchResult:
    offers: list
    mode: str                      # DEMO or LIVE (reference_data vocabularies.offer_mode)
    as_of: datetime                # the provider's clock for freshness checks
    source: str = ''
    refresh_result: object = None  # fixture hook: what a refresh request returns
    attempts: int = 1
    notes: list = field(default_factory=list)


def _parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def failing_attempts(fault, limit):
    """How many leading attempts an injected fault makes fail (fixture / evaluation hook)."""
    if not fault:
        return 0
    text = str(fault).lower()
    if 'both retries' in text or 'all attempts' in text or 'every attempt' in text or 'all retries' in text:
        return limit
    if 'first retry' in text or 'one retry' in text:
        return 2
    return 1


class _BaseProvider:
    name = ''

    def __init__(self, events):
        self.events = events
        self.limit = _attempt_limit()

    def _bounded(self, operation, call, fault=None):
        failures = failing_attempts(fault, self.limit)
        last = None
        for attempt in range(1, self.limit + 1):
            started = time.perf_counter()
            try:
                if attempt <= failures:
                    raise TimeoutError('injected fault: %s' % fault)
                result = call()
                self.events.emit('provider_call', operation=operation, provider=self.name, attempt=attempt,
                                 outcome='ok', duration_ms=round((time.perf_counter() - started) * 1000, 1))
                return result, attempt
            except (TimeoutError, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                self.events.emit('provider_call', operation=operation, provider=self.name, attempt=attempt,
                                 outcome=type(exc).__name__,
                                 duration_ms=round((time.perf_counter() - started) * 1000, 1))
        raise ProviderUnavailable('%s failed after %d attempts (%s).' % (operation, self.limit, type(last).__name__))


class FixtureTravelProvider(_BaseProvider):
    """DEMO offers from JSON fixtures. Each fixture carries its own frozen clock, which is the time its offers are
    judged against, so DEMO results are reproducible."""
    name = 'fixture'

    def __init__(self, fixture_dir, events):
        super().__init__(events)
        self.fixture_dir = Path(fixture_dir) if Path(fixture_dir).is_absolute() else ROOT / fixture_dir

    def _load(self, path):
        path = Path(path)
        return json.loads((path if path.is_absolute() else ROOT / path).read_text(encoding='utf-8'))

    def _matches(self, offer, criteria):
        if offer.get('type') != criteria['search_type']:
            return False
        if criteria['search_type'] == 'hotel':
            from domain.reference import canonical_city
            return canonical_city(offer.get('city')) == canonical_city(criteria.get('city'))
        return (offer.get('origin'), offer.get('destination')) == (criteria.get('origin'), criteria.get('destination'))

    def _pick_fixture(self, criteria):
        """Interactive use (no fixture named): the first clean fixture whose offers match the request."""
        for path in sorted(self.fixture_dir.glob('*.json')):
            data = self._load(path)
            if data.get('fault') or data.get('refresh_result'):
                continue
            if any(self._matches(o, criteria) for o in data.get('offers', [])):
                return path, data
        return None, {'clock': None, 'mode': 'DEMO', 'offers': [], 'fault': None, 'refresh_result': None}

    def search(self, criteria, fixture_paths=None, injected_error=None):
        if fixture_paths:
            path = fixture_paths[0]
            data = self._load(path)
        else:
            path, data = self._pick_fixture(criteria)

        def call():
            return [o for o in data.get('offers', []) if o.get('type') == criteria['search_type']]

        offers, attempts = self._bounded('search', call, injected_error or data.get('fault'))
        as_of = _parse_time(data.get('clock')) or datetime.now(timezone.utc)
        return SearchResult(offers=offers, mode=data.get('mode', 'DEMO'), as_of=as_of,
                            source=str(path).replace('\\', '/') if path else '', attempts=attempts,
                            refresh_result=data.get('refresh_result'))

    def refresh(self, result, offer_ids):
        """Re-quote stale offers. The fixture's refresh_result decides the outcome: an error string fails every
        attempt; a list of offers replaces the stale ones; null means the provider cannot re-quote."""
        outcome = result.refresh_result

        def call():
            if isinstance(outcome, str):
                raise TimeoutError(outcome)
            if isinstance(outcome, dict):
                return [o for o in outcome.get('offers', []) if o.get('id') in offer_ids]
            if isinstance(outcome, list):
                return [o for o in outcome if o.get('id') in offer_ids]
            return []

        fault = outcome if isinstance(outcome, str) else None
        offers, _ = self._bounded('refresh', call, None if fault is None else 'all attempts: ' + fault)
        return offers


class HttpTravelProvider(_BaseProvider):
    """An external read-only search API: POST {base_url}/search with the criteria, expecting {"offers": [...]}.
    Not yet exercised against a live endpoint; verify against the provider's documentation when it arrives."""
    name = 'http'

    def __init__(self, settings, api_key, events, transport=None):
        super().__init__(events)
        self.http = httpx.Client(base_url=settings.base_url.rstrip('/'), timeout=settings.timeout_seconds,
                                 transport=transport,
                                 headers={'Authorization': 'Bearer ' + api_key} if api_key else {})

    def search(self, criteria, fixture_paths=None, injected_error=None):
        def call():
            response = self.http.post('/search', json=criteria)
            response.raise_for_status()
            return response.json().get('offers', [])

        offers, attempts = self._bounded('search', call, injected_error)
        return SearchResult(offers=offers, mode='LIVE', as_of=datetime.now(timezone.utc), source='http',
                            attempts=attempts)

    def refresh(self, result, offer_ids):
        def call():
            response = self.http.post('/refresh', json={'offer_ids': list(offer_ids)})
            response.raise_for_status()
            return response.json().get('offers', [])

        offers, _ = self._bounded('refresh', call)
        return offers


def build_travel(context):
    """The configured provider, or None when the http provider has no key (reported as CAPABILITY_UNAVAILABLE)."""
    settings = context.settings.travel
    if settings.provider == 'fixture':
        return FixtureTravelProvider(settings.fixture_dir, context.events)
    key = context.settings.secret(settings.api_key_env)
    if not key:
        return None
    return HttpTravelProvider(settings, key, context.events)
