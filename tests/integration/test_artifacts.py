"""Derived API schema stays in sync; local traces are redacted (AC20, OBS04)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_committed_openapi_matches_the_app():
    from scripts.export_openapi import generate
    assert (ROOT / 'api' / 'openapi.json').read_text() == generate(), 'run scripts/export_openapi.py'


def test_local_trace_never_contains_configured_secrets(tmp_path):
    from fastapi.testclient import TestClient
    from api.main import create_app
    from core.context import build_context
    from core.settings import load_settings
    settings = load_settings().with_overrides(data_dir=tmp_path,
                                              secret_overrides={'ANTHROPIC_API_KEY': 'sk-ant-TESTCANARY123456'})
    context = build_context(settings=settings, with_model=False, with_embeddings=False)
    with TestClient(create_app(context)) as client:
        client.get('/health', headers={'Authorization': 'Bearer sk-ant-TESTCANARY123456'})
        client.get('/sessions/x', headers={'Authorization': 'Bearer sk-ant-TESTCANARY123456'})
    traces = ''.join(p.read_text() for p in (tmp_path / 'traces').glob('*.jsonl'))
    assert traces and 'TESTCANARY' not in traces
    context.store.close()
