"""Embedding providers behind the LangChain ``Embeddings`` interface, plus a SQLite vector cache.

Providers (config/settings.toml [embeddings].provider):
  fastembed          free local ONNX model on CPU (approved stand-in until hosted embeddings arrive)
  openai_compatible  a hosted /embeddings endpoint (base_url, model_id, api_key_env)
  none               no vectors; retrieval stays keyword-only

Document vectors are cached per model in SQLite, so a vector is created once per chunk and model.
"""
import hashlib
import time
from array import array

import httpx
from langchain_core.embeddings import Embeddings


class EmbeddingError(Exception):
    pass


class FastEmbedEmbeddings(Embeddings):
    """Local embeddings with fastembed (ONNX Runtime). The model downloads on first use."""

    def __init__(self, model_id, cache_dir, batch_size=64):
        self.model_id, self.cache_dir, self.batch_size = model_id, cache_dir, batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding
            try:
                self._model = TextEmbedding(self.model_id, cache_dir=str(self.cache_dir))
            except Exception as exc:  # download blocked, unknown model, corrupt cache
                raise EmbeddingError('Could not load embedding model %s (%s).' % (self.model_id, type(exc).__name__)) from exc
        return self._model

    def embed_documents(self, texts):
        return [vector.tolist() for vector in self._load().embed(list(texts), batch_size=self.batch_size)]

    def embed_query(self, text):
        return next(iter(self._load().query_embed([text]))).tolist()


class OpenAICompatibleEmbeddings(Embeddings):
    """A hosted ``POST {base_url}/embeddings`` endpoint in the common OpenAI-compatible format.

    Tested against a mock server only; run the smoke test in README when real keys arrive.
    """

    def __init__(self, base_url, model_id, api_key, timeout_seconds=60, batch_size=64, transport=None, attempts=3):
        self.model_id, self.batch_size, self.attempts = model_id, batch_size, attempts
        self.http = httpx.Client(base_url=base_url.rstrip('/'), timeout=timeout_seconds, transport=transport,
                                 headers={'Authorization': 'Bearer ' + api_key} if api_key else {})

    def _post(self, inputs):
        last = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.http.post('/embeddings', json={'model': self.model_id, 'input': inputs})
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError('retryable', request=response.request, response=response)
                response.raise_for_status()
                data = sorted(response.json()['data'], key=lambda item: item.get('index', 0))
                return [item['embedding'] for item in data]
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status is not None and status < 500 and status != 429:
                    break
                time.sleep(min(2 ** (attempt - 1), 4))
        raise EmbeddingError('Embedding endpoint failed after bounded attempts (%s).' % type(last).__name__)

    def embed_documents(self, texts):
        texts, vectors = list(texts), []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._post(texts[start:start + self.batch_size]))
        return vectors

    def embed_query(self, text):
        return self._post([text])[0]


class CachedEmbeddings(Embeddings):
    """Caches document vectors in SQLite by (model key, text hash). Query vectors are not cached."""

    def __init__(self, underlying, store, model_key, events=None):
        self.underlying, self.store, self.model_key, self.events = underlying, store, model_key, events
        self.created = 0
        self.fallback_reason = None

    @staticmethod
    def digest(text):
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def embed_documents(self, texts):
        texts = list(texts)
        keys = [self.digest(t) for t in texts]
        cached = self.store.get_vectors(self.model_key, keys)
        missing = [i for i, key in enumerate(keys) if key not in cached]
        if missing:
            started = time.perf_counter()
            fresh = self.underlying.embed_documents([texts[i] for i in missing])
            self.store.put_vectors(self.model_key, {keys[i]: array('f', v).tobytes() for i, v in zip(missing, fresh)})
            self.created += len(missing)
            if self.events:
                self.events.emit('embedding_call', target='documents', count=len(missing), model=self.model_key,
                                 duration_ms=round((time.perf_counter() - started) * 1000, 1))
            cached.update({keys[i]: array('f', v).tobytes() for i, v in zip(missing, fresh)})
        return [list(array('f', cached[key])) for key in keys]

    def embed_query(self, text):
        if self.events:
            self.events.emit('embedding_call', target='query', count=1, model=self.model_key)
        return self.underlying.embed_query(text)


PROBE_TIMEOUT_SECONDS = 15


def _fastembed(settings, model_id):
    from core.settings import ROOT
    return FastEmbedEmbeddings(model_id, (ROOT / settings.cache_dir).resolve(), settings.batch_size)


def build_embeddings(context, transport=None):
    """The configured embeddings wrapped in the SQLite cache, or None for keyword-only retrieval.

    A hosted (openai_compatible) endpoint is probed once here. If it does not answer and
    [embeddings].fallback_provider is "fastembed", the local fallback model is used for this run and
    the reason is kept on ``fallback_reason``. The check runs at startup only: vectors from different
    models cannot be mixed in one index, so restart the API after the endpoint comes back.
    """
    settings = context.settings.embeddings
    if settings.provider == 'none':
        return None
    if settings.provider == 'fastembed':
        return CachedEmbeddings(_fastembed(settings, settings.model_id), context.store,
                                'fastembed:%s' % settings.model_id, context.events)
    api_key = context.settings.secret(settings.api_key_env)
    hosted = OpenAICompatibleEmbeddings(settings.base_url, settings.model_id, api_key, settings.timeout_seconds,
                                        settings.batch_size, transport=transport)
    if settings.fallback_provider in ('', 'none'):
        return CachedEmbeddings(hosted, context.store, 'openai_compatible:%s' % settings.model_id, context.events)
    probe = OpenAICompatibleEmbeddings(settings.base_url, settings.model_id, api_key,
                                       min(settings.timeout_seconds, PROBE_TIMEOUT_SECONDS), 1,
                                       transport=transport, attempts=1)
    try:
        probe.embed_query('readiness probe')
    except (EmbeddingError, KeyError, IndexError, TypeError, ValueError) as exc:
        reason = 'hosted embeddings at %s unavailable (%s); using %s:%s' % (
            settings.base_url, type(exc).__name__, settings.fallback_provider, settings.fallback_model_id)
        if context.events:
            context.events.emit('embedding_fallback', detail=reason[:200])
        cached = CachedEmbeddings(_fastembed(settings, settings.fallback_model_id), context.store,
                                  'fastembed:%s' % settings.fallback_model_id, context.events)
        cached.fallback_reason = reason
        return cached
    return CachedEmbeddings(hosted, context.store, 'openai_compatible:%s' % settings.model_id, context.events)
