"""Configuration loading and provider validation."""
import pytest

from core.settings import SettingsError, load_settings, validate


def write(tmp_path, model='provider = "anthropic"\nmodel_id = "claude-sonnet-5-5"\napi_key_env = "X_KEY"',
          travel='provider = "fixture"'):
    path = tmp_path / 'settings.toml'
    path.write_text('[app]\n[model]\n%s\n[travel]\n%s\n' % (model, travel))
    return path


def test_default_settings_use_claude_sonnet_through_claude_code():
    settings = load_settings()
    assert settings.model.provider == 'claude_code'
    assert settings.model.model_id == 'claude-sonnet-5-5'
    assert settings.model.api_key_env == 'ANTHROPIC_API_KEY'


def test_secret_is_read_from_named_environment_variable(tmp_path, monkeypatch):
    settings = load_settings(write(tmp_path))
    monkeypatch.delenv('X_KEY', raising=False)
    assert settings.secret('X_KEY') is None
    monkeypatch.setenv('X_KEY', 'value-from-env')
    assert settings.secret('X_KEY') == 'value-from-env'


def test_swapping_to_an_external_model_only_needs_config(tmp_path):
    settings = load_settings(write(tmp_path, model='provider = "openai_compatible"\nmodel_id = "hosted-model"\n'
                                                   'base_url = "https://models.example.com/v1"\napi_key_env = "HOSTED_KEY"'))
    assert settings.model.provider == 'openai_compatible' and settings.model.base_url.startswith('https://')


@pytest.mark.parametrize('model,travel', [
    ('provider = "nope"\nmodel_id = "m"', 'provider = "fixture"'),
    ('provider = "openai_compatible"\nmodel_id = "m"', 'provider = "fixture"'),
    ('provider = "anthropic"\nmodel_id = "m"', 'provider = "http"'),
])
def test_invalid_provider_configuration_is_rejected(tmp_path, model, travel):
    with pytest.raises(SettingsError):
        load_settings(write(tmp_path, model=model, travel=travel))


def test_config_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv('EXPENSE_CONFIG', str(write(tmp_path, model='provider = "anthropic"\nmodel_id = "other-model"')))
    assert load_settings().model.model_id == 'other-model'
