"""Hosted (e.g. Colab-served) model and embeddings: .env overrides and the startup embeddings fallback.

Offline only: the hosted endpoint is an httpx.MockTransport and the fastembed fallback is never loaded
(FastEmbedEmbeddings loads its model lazily on first use).
"""
import json
import os
from types import SimpleNamespace

import httpx
import pytest

from adapters.embeddings import FastEmbedEmbeddings, OpenAICompatibleEmbeddings, build_embeddings
from core.events import EventLog
from core.settings import EmbeddingSettings, SettingsError, load_settings, validate

HOSTED = {
    'EXPENSE_MODEL_PROVIDER': 'openai_compatible',
    'EXPENSE_MODEL_ID': 'Qwen/Qwen3-4B-Instruct-2507',
    'EXPENSE_MODEL_BASE_URL': 'https://example.trycloudflare.com/v1',
    'EXPENSE_MODEL_API_KEY_ENV': 'COLAB_API_KEY',
    'EXPENSE_MODEL_MAX_OUTPUT_TOKENS': '4096',
    'EXPENSE_MODEL_SUPPORTS_VISION': 'false',
    'EXPENSE_EMBEDDINGS_PROVIDER': 'openai_compatible',
    'EXPENSE_EMBEDDINGS_MODEL_ID': 'BAAI/bge-small-en-v1.5',
    'EXPENSE_EMBEDDINGS_BASE_URL': 'https://example.trycloudflare.com/v1',
    'EXPENSE_EMBEDDINGS_API_KEY_ENV': 'COLAB_API_KEY',
}


@pytest.fixture
def clean_env(monkeypatch):
    """No EXPENSE_* variables from this machine's shell or .env leak into the test."""
    monkeypatch.setattr('core.settings._load_dotenv', lambda: None)
    for name in list(os.environ):
        if name.startswith('EXPENSE_'):
            monkeypatch.delenv(name)
    return monkeypatch


def test_env_overrides_configure_a_hosted_model_and_embeddings(clean_env):
    for name, value in HOSTED.items():
        clean_env.setenv(name, value)
    settings = load_settings()
    assert settings.model.provider == 'openai_compatible'
    assert settings.model.model_id == 'Qwen/Qwen3-4B-Instruct-2507'
    assert settings.model.base_url == 'https://example.trycloudflare.com/v1'
    assert settings.model.api_key_env == 'COLAB_API_KEY'
    assert settings.model.max_output_tokens == 4096 and settings.model.supports_vision is False
    assert settings.embeddings.provider == 'openai_compatible'
    assert settings.embeddings.base_url == 'https://example.trycloudflare.com/v1'
    assert settings.embeddings.fallback_provider == 'fastembed'          # from config/settings.toml


def test_blank_override_keeps_the_config_file_value(clean_env):
    clean_env.setenv('EXPENSE_MODEL_ID', '   ')
    assert load_settings().model.model_id == 'claude-sonnet-5-5'


@pytest.mark.parametrize('name,value', [('EXPENSE_MODEL_MAX_OUTPUT_TOKENS', 'lots'),
                                        ('EXPENSE_MODEL_SUPPORTS_VISION', 'maybe'),
                                        ('EXPENSE_EMBEDDINGS_FALLBACK_PROVIDER', 'openai_compatible')])
def test_invalid_override_is_rejected(clean_env, name, value):
    clean_env.setenv(name, value)
    with pytest.raises(SettingsError):
        load_settings()


def test_fastembed_fallback_needs_a_model_id(clean_env):
    settings = load_settings()
    broken = settings.with_overrides(embeddings=EmbeddingSettings(provider='none', fallback_provider='fastembed'))
    with pytest.raises(SettingsError):
        validate(broken)


def _context(tmp_path, fallback='fastembed'):
    settings = load_settings().with_overrides(
        data_dir=tmp_path,
        embeddings=EmbeddingSettings(provider='openai_compatible', model_id='BAAI/bge-small-en-v1.5',
                                     base_url='https://example.trycloudflare.com/v1', api_key_env='COLAB_API_KEY',
                                     fallback_provider=fallback, fallback_model_id='BAAI/bge-small-en-v1.5'),
        secret_overrides={'COLAB_API_KEY': 'test-key'})
    return SimpleNamespace(settings=settings, store=None, events=EventLog())


def _endpoint(status, calls):
    def handler(request):
        calls.append(request)
        if status != 200:
            return httpx.Response(status, json={'error': 'down'})
        count = len(json.loads(request.content)['input'])
        return httpx.Response(200, json={'data': [{'index': i, 'embedding': [0.1, 0.2, 0.3]} for i in range(count)]})
    return httpx.MockTransport(handler)


def test_hosted_embeddings_are_used_when_the_endpoint_answers(clean_env, tmp_path):
    calls = []
    embeddings = build_embeddings(_context(tmp_path), transport=_endpoint(200, calls))
    assert embeddings.model_key == 'openai_compatible:BAAI/bge-small-en-v1.5'
    assert isinstance(embeddings.underlying, OpenAICompatibleEmbeddings)
    assert embeddings.fallback_reason is None
    assert calls[0].headers['Authorization'] == 'Bearer test-key'
    assert embeddings.embed_query('hotel cap') == [0.1, 0.2, 0.3]


def test_unreachable_endpoint_falls_back_to_local_fastembed(clean_env, tmp_path):
    calls = []
    context = _context(tmp_path)
    embeddings = build_embeddings(context, transport=_endpoint(503, calls))
    assert len(calls) == 1                                               # one probe, no retry storm at startup
    assert embeddings.model_key == 'fastembed:BAAI/bge-small-en-v1.5'
    assert isinstance(embeddings.underlying, FastEmbedEmbeddings)
    assert 'unavailable' in embeddings.fallback_reason and 'test-key' not in embeddings.fallback_reason
    assert context.events.count('embedding_fallback') == 1


def test_no_fallback_keeps_the_hosted_endpoint_without_probing(clean_env, tmp_path):
    calls = []
    embeddings = build_embeddings(_context(tmp_path, fallback='none'), transport=_endpoint(503, calls))
    assert calls == [] and embeddings.model_key == 'openai_compatible:BAAI/bge-small-en-v1.5'


def test_model_reachability_probe_reports_a_dead_tunnel(clean_env):
    """/ready must not show 'AI online' when the hosted URL has gone away (Colab tunnels change on restart)."""
    from adapters.model import OpenAICompatibleModel
    for name, value in HOSTED.items():
        clean_env.setenv(name, value)
    settings = load_settings().model

    def dead(request):
        raise httpx.ConnectError('name not resolved', request=request)

    def alive(request):
        assert request.url.path.endswith('/models')
        return httpx.Response(200, json={'data': [{'id': settings.model_id}]})

    down = OpenAICompatibleModel(settings, 'key', EventLog(), transport=httpx.MockTransport(dead))
    up = OpenAICompatibleModel(settings, 'key', EventLog(), transport=httpx.MockTransport(alive))
    ok, error = down.reachable()
    assert ok is False and 'ConnectError' in error
    assert up.reachable() == (True, None)
