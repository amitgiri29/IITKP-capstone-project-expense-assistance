import os

import pytest

from api.main import create_app
from core.context import build_context
from core.settings import load_settings


@pytest.fixture(autouse=True)
def hermetic_settings(monkeypatch):
    """Tests use config/settings.toml as committed: this machine's .env and EXPENSE_* overrides (for example a hosted
    model block) must not change test outcomes."""
    monkeypatch.setattr('core.settings._load_dotenv', lambda: None)
    for name in list(os.environ):
        if name.startswith('EXPENSE_'):
            monkeypatch.delenv(name)


@pytest.fixture
def context(tmp_path):
    settings = load_settings().with_overrides(data_dir=tmp_path)
    ctx = build_context(settings=settings, with_model=False, with_embeddings=False)  # tests never call a live model or download an embedding model
    yield ctx
    ctx.store.close()


@pytest.fixture
def client(context):
    from fastapi.testclient import TestClient
    with TestClient(create_app(context)) as test_client:
        yield test_client


@pytest.fixture
def session(client):
    body = client.post('/sessions', json={'traveler_id': 'employee-A'}).json()
    return body | {'headers': {'Authorization': 'Bearer ' + body['token']}}
