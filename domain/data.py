"""Read-only access to the normative data files under policy_sources/.

The domain never reads tests/ or any golden expectation.
"""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / 'policy_sources'


@lru_cache(maxsize=None)
def _load(name):
    return json.loads((POLICY_DIR / name).read_text(encoding='utf-8'))


def rule_registry():
    return _load('rule_registry.json')


def reference_data():
    return _load('reference_data.json')


def policy():
    return _load('policy.json')
