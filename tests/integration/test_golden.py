"""M1 and M2 golden cases through the evaluation driver: every automatic check must pass."""
import pytest

from evaluation.driver import build_payload, load_cases, run_case
from evaluation.milestones import MILESTONE_ENTRYPOINTS

SUITE = load_cases()
M1_CASES = [c for c in SUITE['cases'] if c['entrypoint'] in MILESTONE_ENTRYPOINTS['M1'] + MILESTONE_ENTRYPOINTS['M2']]
ANSWER_KEYS = {'expected', 'automatic_checks', 'human_checks', 'required_rule_ids', 'requirement_ids',
               'citation_check', 'assertions'}


def test_m1_m2_select_45_cases():
    assert len(M1_CASES) == 45


@pytest.mark.parametrize('case', M1_CASES, ids=[c['id'] for c in M1_CASES])
def test_m1_case_automatic_checks(case):
    envelope, checks, error = run_case(case, SUITE)
    assert error is None, error
    failed = [c for c in checks if not c['passed']]
    assert not failed, failed
    assert envelope['run_metadata']['status'] in {'PENDING_REVIEW', 'PASS'}


@pytest.mark.parametrize('case', SUITE['cases'], ids=[c['id'] for c in SUITE['cases']])
def test_payload_never_carries_answer_keys(case):
    payload = build_payload(case)
    assert not ANSWER_KEYS & set(payload)
    for value in case['expected'].values():
        if isinstance(value, str) and len(value) > 12:
            assert value not in repr(payload), value
