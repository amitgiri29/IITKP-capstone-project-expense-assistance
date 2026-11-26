"""Per-machine provider overrides from the environment (written to .env by setup.sh)."""
import pytest

from core.settings import SettingsError, load_settings


def test_environment_overrides_model_and_embeddings_provider(monkeypatch):
    monkeypatch.setenv('EXPENSE_MODEL_PROVIDER', 'anthropic')
    monkeypatch.setenv('EXPENSE_EMBEDDINGS_PROVIDER', 'none')
    settings = load_settings()
    assert settings.model.provider == 'anthropic' and settings.embeddings.provider == 'none'


def test_unknown_override_is_rejected(monkeypatch):
    monkeypatch.setenv('EXPENSE_MODEL_PROVIDER', 'not-a-provider')
    with pytest.raises(SettingsError):
        load_settings()


def test_no_override_keeps_the_config_file(monkeypatch):
    monkeypatch.delenv('EXPENSE_MODEL_PROVIDER', raising=False)
    monkeypatch.delenv('EXPENSE_EMBEDDINGS_PROVIDER', raising=False)
    monkeypatch.setattr('core.settings._load_dotenv', lambda: None)  # ignore this machine's .env
    assert load_settings().model.provider == 'claude_code'
