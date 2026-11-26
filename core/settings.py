"""Load config/settings.toml. Secrets are read from the environment variable each setting names."""
import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PROVIDERS = {'anthropic', 'openai_compatible', 'claude_code', 'fake'}
EMBEDDING_PROVIDERS = {'none', 'fastembed', 'openai_compatible'}
EMBEDDING_FALLBACKS = {'', 'none', 'fastembed'}
TRAVEL_PROVIDERS = {'fixture', 'http'}


def _bool(value):
    if value.strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if value.strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    raise SettingsError('expected true or false, got %r' % value)


# Per-machine overrides read from the environment (or .env), so the committed settings.toml stays
# unchanged. Used for a hosted model whose URL changes per session, e.g. the Colab notebook in colab/.
MODEL_ENV = {
    'EXPENSE_MODEL_PROVIDER': ('provider', str),
    'EXPENSE_MODEL_ID': ('model_id', str),
    'EXPENSE_MODEL_BASE_URL': ('base_url', str),
    'EXPENSE_MODEL_API_KEY_ENV': ('api_key_env', str),
    'EXPENSE_MODEL_MAX_OUTPUT_TOKENS': ('max_output_tokens', int),
    'EXPENSE_MODEL_TIMEOUT_SECONDS': ('timeout_seconds', float),
    'EXPENSE_MODEL_SUPPORTS_VISION': ('supports_vision', _bool),
}
EMBEDDINGS_ENV = {
    'EXPENSE_EMBEDDINGS_PROVIDER': ('provider', str),
    'EXPENSE_EMBEDDINGS_MODEL_ID': ('model_id', str),
    'EXPENSE_EMBEDDINGS_BASE_URL': ('base_url', str),
    'EXPENSE_EMBEDDINGS_API_KEY_ENV': ('api_key_env', str),
    'EXPENSE_EMBEDDINGS_FALLBACK_PROVIDER': ('fallback_provider', str),
}


def _apply_env(section, mapping):
    for env_name, (key, convert) in mapping.items():
        value = os.environ.get(env_name)
        if value is not None and value.strip():
            try:
                section = section | {key: convert(value.strip())}
            except ValueError as exc:
                raise SettingsError('%s: %s' % (env_name, exc)) from exc
    return section


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSettings:
    provider: str
    model_id: str
    base_url: str = ''
    api_key_env: str = ''
    timeout_seconds: float = 60
    max_output_tokens: int = 16000
    effort: str = 'medium'
    supports_vision: bool = True
    server_side_fallback: bool = True
    cli_path: str = 'claude'
    max_budget_usd_per_call: float = 0.5


@dataclass(frozen=True)
class TravelSettings:
    provider: str
    base_url: str = ''
    api_key_env: str = ''
    timeout_seconds: float = 20
    fixture_dir: str = 'fixtures/search'


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int = 6
    keyword_candidates: int = 15
    vector_candidates: int = 15
    rerank: bool = False
    chunk_size_chars: int = 1800
    chunk_overlap_chars: int = 200


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str = 'none'
    model_id: str = ''
    base_url: str = ''
    api_key_env: str = ''
    cache_dir: str = 'runtime/models'
    batch_size: int = 64
    timeout_seconds: float = 60
    # Used only when provider is openai_compatible and the endpoint does not answer at startup.
    fallback_provider: str = ''
    fallback_model_id: str = ''


@dataclass(frozen=True)
class TelemetrySettings:
    langsmith_enabled: bool = False
    local_trace: bool = True


@dataclass(frozen=True)
class Settings:
    environment: str
    organization_id: str
    data_dir: Path
    api_base_url: str
    session_ttl_hours: float
    model: ModelSettings
    travel: TravelSettings
    telemetry: TelemetrySettings
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    embeddings: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    secret_overrides: dict = field(default_factory=dict, repr=False, compare=False)

    def secret(self, env_name):
        """Value of a secret by its environment-variable name, or None when unset."""
        if not env_name:
            return None
        if env_name in self.secret_overrides:
            return self.secret_overrides[env_name]
        value = os.environ.get(env_name)
        return value or None

    def with_overrides(self, **changes):
        return replace(self, **changes)


def _load_dotenv():
    env_file = ROOT / '.env'
    if env_file.is_file():
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)


def load_settings(path=None):
    _load_dotenv()
    path = Path(path or os.environ.get('EXPENSE_CONFIG') or ROOT / 'config' / 'settings.toml')
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    app, model, travel = raw.get('app', {}), raw.get('model', {}), raw.get('travel', {})
    embeddings = raw.get('embeddings', {})
    # Local per-machine choice without editing the committed file (setup.sh writes these into .env).
    model = _apply_env(model, MODEL_ENV)
    embeddings = _apply_env(embeddings, EMBEDDINGS_ENV)
    settings = Settings(
        environment=app.get('environment', 'local'),
        organization_id=app.get('organization_id', 'demo-company'),
        data_dir=(ROOT / app.get('data_dir', 'runtime')).resolve(),
        api_base_url=os.environ.get('EXPENSE_API_BASE_URL', app.get('api_base_url', 'http://127.0.0.1:8000')),
        session_ttl_hours=float(app.get('session_ttl_hours', 24)),
        model=ModelSettings(**model),
        travel=TravelSettings(**travel),
        telemetry=TelemetrySettings(**raw.get('telemetry', {})),
        retrieval=RetrievalSettings(**raw.get('retrieval', {})),
        embeddings=EmbeddingSettings(**embeddings),
    )
    validate(settings)
    return settings


def validate(settings):
    if settings.model.provider not in MODEL_PROVIDERS:
        raise SettingsError('model.provider must be one of %s' % sorted(MODEL_PROVIDERS))
    if not settings.model.model_id:
        raise SettingsError('model.model_id is required')
    if settings.model.provider == 'openai_compatible' and not settings.model.base_url:
        raise SettingsError('model.base_url is required for an openai_compatible provider')
    if settings.embeddings.provider not in EMBEDDING_PROVIDERS:
        raise SettingsError('embeddings.provider must be one of %s' % sorted(EMBEDDING_PROVIDERS))
    if settings.embeddings.provider != 'none' and not settings.embeddings.model_id:
        raise SettingsError('embeddings.model_id is required when embeddings are enabled')
    if settings.embeddings.provider == 'openai_compatible' and not settings.embeddings.base_url:
        raise SettingsError('embeddings.base_url is required for an openai_compatible embeddings provider')
    if settings.embeddings.fallback_provider not in EMBEDDING_FALLBACKS:
        raise SettingsError('embeddings.fallback_provider must be one of %s' % sorted(EMBEDDING_FALLBACKS - {''}))
    if settings.embeddings.fallback_provider == 'fastembed' and not settings.embeddings.fallback_model_id:
        raise SettingsError('embeddings.fallback_model_id is required when fallback_provider is "fastembed"')
    if settings.travel.provider not in TRAVEL_PROVIDERS:
        raise SettingsError('travel.provider must be one of %s' % sorted(TRAVEL_PROVIDERS))
    if settings.travel.provider == 'http' and not settings.travel.base_url:
        raise SettingsError('travel.base_url is required when travel.provider is "http"')
    return settings


def load_profiles(path=None):
    path = Path(path or ROOT / 'config' / 'profiles.toml')
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    return raw['organization'], {t['traveler_id']: t for t in raw.get('travelers', [])}
