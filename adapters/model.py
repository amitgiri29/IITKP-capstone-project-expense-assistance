"""ModelPort and its adapters. Every model role uses the one configured model.

Providers (config/settings.toml [model].provider):
  claude_code        the local Claude Code CLI in print mode, using its existing sign-in (local testing)
  anthropic          Claude API through the official anthropic SDK (default claude-sonnet-5-5)
  openai_compatible  an externally hosted chat-completions endpoint at model.base_url
  fake               scripted replies for tests only

Every attempt is recorded as a 'model_call' event. Attempts are bounded by
IMPLEMENTATION_CONTRACT.json operational_defaults, and one format repair is allowed.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

import httpx

from domain.data import ROOT


def _limits():
    defaults = json.loads((ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text())['operational_defaults']
    return defaults['provider_attempts_per_operation'], defaults['format_repairs']


@dataclass
class ModelReply:
    text: str
    data: object = None
    model: str = ''
    provider: str = ''
    stop_reason: str = ''
    usage: dict = field(default_factory=dict)
    attempts: int = 1


class ModelError(Exception):
    """A bounded model failure; never retried by callers."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def image_block(data, mime):
    return {'data': base64.standard_b64encode(data).decode('ascii'), 'mime': mime}


class _BaseModel:
    provider = ''

    def __init__(self, settings, api_key, events):
        self.settings, self.api_key, self.events = settings, api_key, events
        self.max_attempts, self.format_repairs = _limits()

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        raise NotImplementedError

    def _retryable(self, exc):
        return False

    def generate(self, purpose, system, user_text, images=(), schema=None, max_tokens=None, validate=None):
        """Return a ModelReply. With a schema, reply.data holds the parsed JSON object."""
        reply = self._attempt(purpose, system, user_text, images, schema, max_tokens)
        if schema is None:
            return reply
        problem = self._check(reply, validate)
        repairs = 0
        while problem and repairs < self.format_repairs:
            repairs += 1
            self.events.emit('format_repair', purpose=purpose, problem=problem[:200])
            repair_text = (user_text + '\n\nYour previous reply was rejected: %s\nReturn only a JSON object that '
                           'matches the required schema.' % problem)
            reply = self._attempt(purpose, system, repair_text, images, schema, max_tokens)
            problem = self._check(reply, validate)
        if problem:
            raise ModelError('format', 'Model output failed validation after %d repair: %s' % (repairs, problem))
        return reply

    def _check(self, reply, validate):
        try:
            reply.data = json.loads(reply.text)
        except (TypeError, ValueError) as exc:
            return 'invalid JSON (%s)' % exc
        if not isinstance(reply.data, dict):
            return 'expected a JSON object'
        return validate(reply.data) if validate else None

    def _attempt(self, purpose, system, user_text, images, schema, max_tokens):
        last = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                reply = self._call(purpose, system, user_text, images, schema,
                                   max_tokens or self.settings.max_output_tokens)
                reply.attempts = attempt
                self.events.emit('model_call', purpose=purpose, provider=self.provider, model=reply.model,
                                 attempt=attempt, outcome='ok', stop_reason=reply.stop_reason,
                                 duration_ms=round((time.perf_counter() - started) * 1000, 1), **reply.usage)
                if reply.stop_reason == 'refusal':
                    raise ModelError('refusal', 'The model declined this request.')
                if reply.stop_reason == 'max_tokens':
                    raise ModelError('truncated', 'The model reply was cut off at the output limit.')
                return reply
            except ModelError:
                raise
            except Exception as exc:  # provider error: record, then retry only if transient
                last = exc
                self.events.emit('model_call', purpose=purpose, provider=self.provider, model=self.settings.model_id,
                                 attempt=attempt, outcome=type(exc).__name__,
                                 duration_ms=round((time.perf_counter() - started) * 1000, 1))
                if not self._retryable(exc) or attempt == self.max_attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 4))
        raise ModelError('provider', 'Model provider failed after bounded attempts (%s).' % type(last).__name__)


class AnthropicModel(_BaseModel):
    """Claude API via the official SDK. SDK-internal retries are off so every attempt is observable."""
    provider = 'anthropic'
    FALLBACK_BETA = 'server-side-fallback-2026-07-01'

    def __init__(self, settings, api_key, events, client=None):
        super().__init__(settings, api_key, events)
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key, base_url=settings.base_url or None,
                                         timeout=settings.timeout_seconds, max_retries=0)
        self.client = client

    def _retryable(self, exc):
        import anthropic
        if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APITimeoutError,
                            anthropic.InternalServerError)):
            return True
        return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500

    def request(self, system, user_text, images, schema, max_tokens):
        content = [{'type': 'image', 'source': {'type': 'base64', 'media_type': i['mime'], 'data': i['data']}}
                   for i in images]
        content.append({'type': 'text', 'text': user_text})
        output_config = {'effort': self.settings.effort}
        if schema is not None:
            output_config['format'] = {'type': 'json_schema', 'schema': schema}
        kwargs = {'model': self.settings.model_id, 'max_tokens': max_tokens,
                  'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                  'messages': [{'role': 'user', 'content': content}], 'output_config': output_config}
        use_fallback = self.settings.server_side_fallback and not self.settings.base_url
        if use_fallback:
            kwargs.update(betas=[self.FALLBACK_BETA], fallbacks='default')
        return kwargs, use_fallback

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        kwargs, use_fallback = self.request(system, user_text, images, schema, max_tokens)
        create = self.client.beta.messages.create if use_fallback else self.client.messages.create
        response = create(**kwargs)
        text = ''.join(block.text for block in response.content if getattr(block, 'type', '') == 'text')
        usage = getattr(response, 'usage', None)
        tokens = {'input_tokens': getattr(usage, 'input_tokens', None),
                  'output_tokens': getattr(usage, 'output_tokens', None),
                  'cache_read_input_tokens': getattr(usage, 'cache_read_input_tokens', None)} if usage else {}
        return ModelReply(text=text, model=getattr(response, 'model', self.settings.model_id), provider=self.provider,
                          stop_reason=getattr(response, 'stop_reason', '') or '', usage=tokens)


class OpenAICompatibleModel(_BaseModel):
    """An externally hosted chat-completions endpoint. Configure model.base_url, model_id and api_key_env.

    Not yet exercised against a live endpoint; verify against the provider's documentation when it arrives.
    """
    provider = 'openai_compatible'

    def __init__(self, settings, api_key, events, transport=None):
        super().__init__(settings, api_key, events)
        self.http = httpx.Client(base_url=settings.base_url.rstrip('/'), timeout=settings.timeout_seconds,
                                 transport=transport)

    def reachable(self, timeout=5.0):
        """Cheap liveness check for /ready: GET {base_url}/models. Returns (ok, error). No model tokens are spent.
        A tunnel URL (e.g. the Colab trycloudflare host) can disappear while the API keeps running, so the
        status card must not claim the model is online just because credentials are configured."""
        headers = {'Authorization': 'Bearer ' + self.api_key} if self.api_key else {}
        try:
            response = self.http.get('/models', headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            return False, 'endpoint unreachable (%s)' % type(exc).__name__
        if response.status_code >= 500 or response.status_code in (401, 403):
            return False, 'endpoint answered HTTP %d' % response.status_code
        return True, None

    def _retryable(self, exc):
        if isinstance(exc, (httpx.TransportError,)):
            return True
        return isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429
                                                           or exc.response.status_code >= 500)

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        content = [{'type': 'text', 'text': user_text}]
        content += [{'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (i['mime'], i['data'])}}
                    for i in images]
        body = {'model': self.settings.model_id, 'max_tokens': max_tokens,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
        if schema is not None:
            body['response_format'] = {'type': 'json_schema',
                                       'json_schema': {'name': purpose, 'schema': schema, 'strict': True}}
        headers = {'Authorization': 'Bearer ' + self.api_key} if self.api_key else {}
        response = self.http.post('/chat/completions', json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        choice = data['choices'][0]
        usage = data.get('usage') or {}
        stop = {'length': 'max_tokens', 'content_filter': 'refusal'}.get(choice.get('finish_reason'), 'end_turn')
        return ModelReply(text=choice['message'].get('content') or '', model=data.get('model', self.settings.model_id),
                          provider=self.provider, stop_reason=stop,
                          usage={'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens')})


class ClaudeCodeModel(_BaseModel):
    """Claude Code CLI in non-interactive print mode, for local testing without an API key.

    Every call runs with all tools disabled, no MCP servers, no settings files, no saved session and an
    empty working directory, so the model sees only the system prompt and the user message given here.
    """
    provider = 'claude_code'

    class CliError(Exception):
        def __init__(self, message, status=None):
            super().__init__(message)
            self.status = status

    def __init__(self, settings, events, runner=None):
        super().__init__(settings, None, events)
        self.runner = runner or subprocess.run

    def _retryable(self, exc):
        if isinstance(exc, subprocess.TimeoutExpired):
            return True
        return isinstance(exc, self.CliError) and (exc.status in (429, 529) or (exc.status or 0) >= 500)

    def command(self, system, schema):
        args = [self.settings.cli_path, '-p', '--output-format', 'json', '--model', self.settings.model_id,
                '--system-prompt', system, '--tools', '', '--no-session-persistence', '--disable-slash-commands',
                '--strict-mcp-config', '--setting-sources', '', '--effort', self.settings.effort,
                '--max-budget-usd', str(self.settings.max_budget_usd_per_call)]
        if schema is not None:
            args += ['--json-schema', json.dumps(schema)]
        return args

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        if images:
            raise ModelError('capability', 'Image input through the Claude Code provider is added in milestone M4.')
        env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE_CODE_') and k != 'CLAUDECODE'}
        with tempfile.TemporaryDirectory(prefix='expense-model-') as workdir:
            completed = self.runner(self.command(system, schema), input=user_text, capture_output=True, text=True,
                                    timeout=self.settings.timeout_seconds, cwd=workdir, env=env)
        try:
            data = json.loads(completed.stdout)
        except ValueError:
            raise self.CliError('Claude Code returned no JSON (exit %s).' % completed.returncode)
        if data.get('is_error') or data.get('subtype') != 'success':
            raise self.CliError('Claude Code call failed: %s' % (data.get('subtype') or 'error'),
                                status=data.get('api_error_status'))
        text = json.dumps(data['structured_output']) if schema is not None and 'structured_output' in data \
            else data.get('result', '')
        usage = data.get('usage') or {}
        return ModelReply(text=text, model=next(iter(data.get('modelUsage') or {}), self.settings.model_id),
                          provider=self.provider, stop_reason=data.get('stop_reason') or 'end_turn',
                          usage={'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
                                 'cache_read_input_tokens': usage.get('cache_read_input_tokens'),
                                 'cost_usd': data.get('total_cost_usd')})


class FakeModel(_BaseModel):
    """Scripted replies for tests. Each reply is a dict (returned as JSON), a string, or an Exception."""
    provider = 'fake'

    def __init__(self, settings, events, replies=None, responder=None):
        super().__init__(settings, None, events)
        self.replies, self.responder, self.calls = list(replies or []), responder, []

    def _call(self, purpose, system, user_text, images, schema, max_tokens):
        self.calls.append({'purpose': purpose, 'system': system, 'user_text': user_text, 'images': len(images),
                           'schema': schema})
        reply = self.responder(purpose, user_text, schema) if self.responder else self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return ModelReply(text=text, model='fake', provider='fake', stop_reason='end_turn',
                          usage={'input_tokens': 0, 'output_tokens': 0})


def build_model(context):
    """The configured model, or None when its credentials are missing (reported as CAPABILITY_UNAVAILABLE)."""
    settings = context.settings.model
    if settings.provider == 'fake':
        return None
    if settings.provider == 'claude_code':
        return ClaudeCodeModel(settings, context.events) if shutil.which(settings.cli_path) else None
    key = context.settings.secret(settings.api_key_env)
    if not key:
        return None
    if settings.provider == 'anthropic':
        return AnthropicModel(settings, key, context.events)
    return OpenAICompatibleModel(settings, key, context.events)
