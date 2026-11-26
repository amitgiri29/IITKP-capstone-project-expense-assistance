"""Regenerate api/openapi.json, a derived artifact. Run with the app venv:
    .venv/bin/python scripts/export_openapi.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def generate():
    from api.main import create_app
    from core.context import build_context
    from core.settings import load_settings
    with tempfile.TemporaryDirectory() as tmp:
        context = build_context(settings=load_settings().with_overrides(data_dir=Path(tmp)), with_model=False, with_embeddings=False)
        spec = create_app(context).openapi()
        context.store.close()
    return json.dumps(spec, indent=2, sort_keys=True) + '\n'


if __name__ == '__main__':
    (ROOT / 'api' / 'openapi.json').write_text(generate(), encoding='utf-8')
    print('wrote api/openapi.json')
