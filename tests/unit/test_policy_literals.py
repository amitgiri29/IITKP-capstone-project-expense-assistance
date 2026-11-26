"""AC21: no policy number is hard-coded in domain code."""
import io
import json
import tokenize
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def policy_numbers():
    registry = json.loads((ROOT / 'policy_sources/rule_registry.json').read_text())
    numbers = {Decimal(c['cap_amount']) for c in registry['caps']}
    for parameter in registry['parameters']:
        value = parameter['value']
        if isinstance(value, (int, str)) and not isinstance(value, bool):
            try:
                numbers.add(Decimal(str(value)))
            except Exception:
                pass
    return {n for n in numbers if n not in (Decimal(0), Decimal(1), Decimal(2))}


def test_domain_has_no_policy_numeric_literals():
    forbidden = policy_numbers()
    found = []
    for path in sorted((ROOT / 'domain').glob('*.py')):
        for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
            if token.type == tokenize.NUMBER and Decimal(token.string.replace('_', '')) in forbidden:
                found.append('%s:%d %s' % (path.name, token.start[0], token.string))
    assert not found, found


def test_domain_imports_no_framework():
    banned = ('langchain', 'langgraph', 'fastapi', 'streamlit', 'langsmith')
    for path in (ROOT / 'domain').glob('*.py'):
        text = path.read_text()
        assert not any(('import %s' % b) in text or ('from %s' % b) in text for b in banned), path.name


def test_domain_never_reads_tests():
    for path in (ROOT / 'domain').glob('*.py'):
        assert "'tests" not in path.read_text() and '"tests' not in path.read_text(), path.name


def test_unknown_reason_code_is_rejected():
    import pytest
    from domain.errors import DomainIssue
    with pytest.raises(ValueError):
        DomainIssue('NEEDS_CLARIFICATION', 'NOT_A_REAL_CODE', 'x')
