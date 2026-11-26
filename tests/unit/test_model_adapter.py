"""Model adapters: request shape, bounded attempts, one format repair (retry_contract)."""
import json
from types import SimpleNamespace

import httpx
import pytest

from adapters import model as model_module
from adapters.model import AnthropicModel, FakeModel, ModelError, OpenAICompatibleModel
from core.events import EventLog
from core.settings import ModelSettings


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(model_module.time, 'sleep', lambda seconds: None)


def claude_settings(**overrides):
    return ModelSettings(**{'provider': 'anthropic', 'model_id': 'claude-sonnet-5-5', 'effort': 'medium', **overrides})


class CapturingClient:
    def __init__(self, text='{"ok": true}', stop='end_turn'):
        self.calls, self.text, self.stop = [], text, stop
        self.messages = SimpleNamespace(create=self._create('plain'))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create('beta')))

    def _create(self, surface):
        def create(**kwargs):
            self.calls.append((surface, kwargs))
            return SimpleNamespace(content=[SimpleNamespace(type='text', text=self.text)], model=kwargs['model'],
                                   stop_reason=self.stop,
                                   usage=SimpleNamespace(input_tokens=11, output_tokens=7, cache_read_input_tokens=0))
        return create


def test_claude_request_uses_structured_output_effort_fallback_and_images():
    client, events = CapturingClient(), EventLog()
    model = AnthropicModel(claude_settings(), 'key', events, client=client)
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}
    reply = model.generate('test', 'system text', 'question', images=[{'data': 'AAA', 'mime': 'image/png'}], schema=schema)
    surface, kwargs = client.calls[0]
    assert surface == 'beta' and kwargs['fallbacks'] == 'default'
    assert kwargs['betas'] == ['server-side-fallback-2026-07-01']
    assert kwargs['model'] == 'claude-sonnet-5-5'
    assert kwargs['output_config'] == {'effort': 'medium', 'format': {'type': 'json_schema', 'schema': schema}}
    assert 'temperature' not in kwargs and 'thinking' not in kwargs
    content = kwargs['messages'][0]['content']
    assert content[0]['type'] == 'image' and content[0]['source']['media_type'] == 'image/png'
    assert reply.data == {'ok': True}
    call = events.all('model_call')[0]
    assert call['input_tokens'] == 11 and call['outcome'] == 'ok'


def test_custom_base_url_skips_server_side_fallback():
    client = CapturingClient()
    AnthropicModel(claude_settings(base_url='https://gateway.example.com'), 'key', EventLog(), client=client) \
        .generate('t', 's', 'u')
    assert client.calls[0][0] == 'plain' and 'fallbacks' not in client.calls[0][1]


def test_refusal_is_not_retried_or_reported_as_an_answer():
    client = CapturingClient(stop='refusal')
    with pytest.raises(ModelError) as error:
        AnthropicModel(claude_settings(), 'key', EventLog(), client=client).generate('t', 's', 'u')
    assert error.value.kind == 'refusal' and len(client.calls) == 1


def hosted(handler):
    settings = ModelSettings(provider='openai_compatible', model_id='hosted-1', base_url='https://models.example.com/v1')
    events = EventLog()
    return OpenAICompatibleModel(settings, 'token', events, transport=httpx.MockTransport(handler)), events


def test_hosted_model_retries_transient_errors_at_most_three_attempts():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) < 3:
            return httpx.Response(503, json={'error': 'busy'})
        return httpx.Response(200, json={'model': 'hosted-1', 'choices': [{'message': {'content': 'hi'},
                                                                         'finish_reason': 'stop'}],
                                         'usage': {'prompt_tokens': 3, 'completion_tokens': 1}})
    model, events = hosted(handler)
    reply = model.generate('t', 'sys', 'user')
    assert reply.text == 'hi' and reply.attempts == 3 and events.count('model_call') == 3
    assert seen[0]['messages'][0] == {'role': 'system', 'content': 'sys'}


def test_hosted_model_gives_up_after_bounded_attempts_and_does_not_retry_400():
    model, events = hosted(lambda request: httpx.Response(503))
    with pytest.raises(ModelError):
        model.generate('t', 's', 'u')
    assert events.count('model_call') == 3
    model, events = hosted(lambda request: httpx.Response(400))
    with pytest.raises(ModelError):
        model.generate('t', 's', 'u')
    assert events.count('model_call') == 1


def test_one_format_repair_then_failed_validation():
    events = EventLog()
    settings = ModelSettings(provider='fake', model_id='fake')
    fixed = FakeModel(settings, events, replies=['not json', {'ok': True}])
    assert fixed.generate('t', 's', 'u', schema={}).data == {'ok': True}
    assert events.count('format_repair') == 1
    broken = FakeModel(settings, EventLog(), replies=['not json', 'still not json', 'never used'])
    with pytest.raises(ModelError) as error:
        broken.generate('t', 's', 'u', schema={})
    assert error.value.kind == 'format' and len(broken.replies) == 1


def test_claude_code_cli_runs_locked_down_and_parses_structured_output():
    from adapters.model import ClaudeCodeModel
    seen = {}

    def runner(args, **kwargs):
        seen['args'], seen['kwargs'] = args, kwargs
        body = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'Paris\n\nReminder: ...',
                'structured_output': {'city': 'Paris'}, 'stop_reason': 'end_turn', 'total_cost_usd': 0.01,
                'usage': {'input_tokens': 5, 'output_tokens': 3}, 'modelUsage': {'claude-sonnet-5-5': {}}}
        return SimpleNamespace(stdout=json.dumps(body), returncode=0)

    settings = ModelSettings(provider='claude_code', model_id='claude-sonnet-5-5')
    events = EventLog()
    reply = ClaudeCodeModel(settings, events, runner=runner).generate('t', 'SYSTEM', 'question', schema={'type': 'object'})
    args = seen['args']
    assert reply.data == {'city': 'Paris'}
    assert args[args.index('--tools') + 1] == '' and '--no-session-persistence' in args
    assert args[args.index('--setting-sources') + 1] == '' and '--strict-mcp-config' in args
    assert args[args.index('--system-prompt') + 1] == 'SYSTEM' and '--json-schema' in args
    assert seen['kwargs']['input'] == 'question' and seen['kwargs']['cwd'] != '.'
    assert events.all('model_call')[0]['cost_usd'] == 0.01


def test_claude_code_errors_are_bounded():
    from adapters.model import ClaudeCodeModel
    calls = []

    def runner(args, **kwargs):
        calls.append(1)
        return SimpleNamespace(stdout=json.dumps({'is_error': True, 'subtype': 'error', 'api_error_status': 529}),
                               returncode=1)

    with pytest.raises(ModelError):
        ClaudeCodeModel(ModelSettings(provider='claude_code', model_id='m'), EventLog(), runner=runner).generate('t', 's', 'u')
    assert len(calls) == 3
