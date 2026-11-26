"""Smoke-test the configured hosted model and embeddings endpoint through the app's own adapters.

Reads config/settings.toml plus the EXPENSE_* overrides in .env (for example the block printed by
colab/qwen_vllm_server.ipynb). Makes one structured chat call and one embeddings call, and never prints
the API key. Run from the project folder:

    .venv\\Scripts\\python.exe -m scripts.check_hosted_model        (Windows)
    .venv/bin/python -m scripts.check_hosted_model                  (macOS/Linux)
"""
import sys
import time

from adapters.embeddings import EmbeddingError, OpenAICompatibleEmbeddings
from adapters.model import ModelError, OpenAICompatibleModel
from core.events import EventLog
from core.settings import load_settings

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['answer', 'confidence'],
          'properties': {'answer': {'type': 'string'}, 'confidence': {'type': 'string', 'enum': ['low', 'high']}}}


def check_model(settings):
    model = settings.model
    print('Model      : %s  %s  (%s)' % (model.provider, model.model_id, model.base_url or 'default endpoint'))
    if model.provider != 'openai_compatible':
        print('  skipped  : set EXPENSE_MODEL_PROVIDER=openai_compatible in .env to use the hosted model')
        return True
    key = settings.secret(model.api_key_env)
    if not key:
        print('  FAIL     : %s is empty in .env' % model.api_key_env)
        return False
    started = time.perf_counter()
    try:
        reply = OpenAICompatibleModel(model, key, EventLog()).generate(
            'smoke_test', 'You are a concise assistant. Reply in JSON only.',
            'In one short sentence, what does a travel expense policy assistant do?', schema=SCHEMA, max_tokens=200)
    except ModelError as exc:
        print('  FAIL     : %s' % exc)
        return False
    print('  OK       : %.1fs  structured reply=%s' % (time.perf_counter() - started, reply.data))
    return True


def check_embeddings(settings):
    emb = settings.embeddings
    print('Embeddings : %s  %s  (%s)' % (emb.provider, emb.model_id, emb.base_url or 'local'))
    if emb.provider != 'openai_compatible':
        print('  skipped  : local provider; nothing hosted to check')
        return True
    started = time.perf_counter()
    try:
        vectors = OpenAICompatibleEmbeddings(emb.base_url, emb.model_id, settings.secret(emb.api_key_env),
                                             emb.timeout_seconds, attempts=1).embed_documents(
            ['Hotel cap for grade E in Bengaluru', 'Local taxi limit per day'])
    except (EmbeddingError, KeyError, ValueError) as exc:
        print('  FAIL     : %s  -> the API will fall back to %s:%s' % (exc, emb.fallback_provider or 'keyword-only',
                                                                       emb.fallback_model_id))
        return False
    print('  OK       : %.1fs  %d vectors of dimension %d' % (time.perf_counter() - started, len(vectors),
                                                              len(vectors[0])))
    return True


def main():
    settings = load_settings()
    ok = check_model(settings)
    ok = check_embeddings(settings) and ok
    print('Result     : %s' % ('all checks passed - restart the API (run.bat) to use them' if ok else 'see FAIL lines'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
