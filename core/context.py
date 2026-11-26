"""The application context: settings, store, clock, event log and provider ports.

The API, the UI-facing workflows and the evaluation harness all build one of these,
so tests and golden runs exercise the same code paths as production.
"""
from dataclasses import dataclass, field

from core.events import EventLog
from core.settings import load_profiles, load_settings
from core.store import Store, utcnow


@dataclass
class AppContext:
    settings: object
    store: Store
    organization: dict
    travelers: dict
    events: EventLog = field(default_factory=EventLog)
    clock: object = utcnow
    system_prompt_suffix: str = ''
    model: object = None
    travel: object = None
    retriever: object = None

    def secrets(self):
        """Every configured secret value, for redaction."""
        names = [self.settings.model.api_key_env, self.settings.travel.api_key_env,
                 self.settings.embeddings.api_key_env]
        return [v for v in (self.settings.secret(n) for n in names) if v]


def build_context(settings=None, data_dir=None, clock=None, with_model=True, with_embeddings=True):
    settings = settings or load_settings()
    if data_dir is not None:
        settings = settings.with_overrides(data_dir=data_dir)
    organization, travelers = load_profiles()
    context = AppContext(settings=settings, store=Store(settings.data_dir), organization=organization,
                         travelers=travelers, clock=clock or utcnow)
    if with_model:
        from adapters.model import build_model
        context.model = build_model(context)
    from adapters.travel import build_travel
    context.travel = build_travel(context)
    embeddings = None
    if with_embeddings:
        from adapters.embeddings import build_embeddings
        embeddings = build_embeddings(context)
    from retrieval.service import PolicyRetriever
    context.retriever = PolicyRetriever(events=context.events, model=context.model,
                                        rerank=settings.retrieval.rerank,
                                        keyword_candidates=settings.retrieval.keyword_candidates,
                                        vector_candidates=settings.retrieval.vector_candidates,
                                        embeddings=embeddings)
    refresh_library(context)
    return context


def reconnect_providers(context):
    """Re-read .env and settings, then rebuild the model, embeddings and search index in place, without restarting
    the API. Used after the Colab notebook prints a new tunnel URL. The new objects are built first and swapped in
    at the end, so requests already running keep the old ones and a failed rebuild leaves the app as it was.
    Store, sessions, travel provider and uploaded documents are untouched."""
    from dotenv import load_dotenv

    from adapters.embeddings import build_embeddings
    from adapters.model import build_model
    from core.settings import ROOT
    from retrieval.corpus import library_documents
    from retrieval.service import PolicyRetriever

    env_file = ROOT / '.env'
    if env_file.is_file():
        load_dotenv(env_file, override=True)              # the new URL and key replace the values read at startup
    settings = load_settings().with_overrides(data_dir=context.settings.data_dir)
    staging = AppContext(settings=settings, store=context.store, organization=context.organization,
                         travelers=context.travelers, events=context.events, clock=context.clock)
    model = build_model(staging)
    staging.model = model
    embeddings = build_embeddings(staging)                 # probes the hosted endpoint; falls back to local if down
    retriever = PolicyRetriever(events=context.events, model=model, rerank=settings.retrieval.rerank,
                                keyword_candidates=settings.retrieval.keyword_candidates,
                                vector_candidates=settings.retrieval.vector_candidates, embeddings=embeddings)
    retriever.refresh(library_documents(context.store.library_chunks()))
    context.settings, context.model, context.retriever = settings, model, retriever
    context.events.emit('providers_reconnected', model=settings.model.model_id,
                        embeddings=retriever.embedding_model, mode=retriever.mode)
    return retriever


def refresh_library(context):
    """Re-index admin library documents from the store (startup and after every change).
    New chunks are embedded here; cached vectors are reused."""
    from retrieval.corpus import library_documents
    return context.retriever.refresh(library_documents(context.store.library_chunks()))
