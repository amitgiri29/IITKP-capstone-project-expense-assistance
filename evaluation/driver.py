"""Golden-case evaluation driver (TEST_PROTOCOL sections 2-7).

The application receives only the case input, its setup fixtures and fixture
paths. Expected values, automatic checks, requirement IDs and gold rule IDs
are read only after the application has returned.

    python -m evaluation.driver --milestone M1
    python -m evaluation.driver --through M1
    python -m evaluation.driver --case GT033
"""
import argparse
import copy
import csv
import hashlib
import importlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evaluation.compare import evaluate_checks, resolve_pointer
from core.errors import CapabilityUnavailable
from evaluation.harness import CaseHarness
from evaluation.milestones import MILESTONE_ENTRYPOINTS, entrypoints_through

ROOT = Path(__file__).resolve().parent.parent
# Only base_claim_fixture and overrides become application input. Every other setup key
# (seed records, canaries, notes) belongs to the harness; see evaluation/harness.py.


def load_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def contract():
    return load_json('IMPLEMENTATION_CONTRACT.json')


def load_cases():
    return load_json('tests/golden_cases.json')


def build_payload(case):
    """Base fixture, then setup overrides, then explicit input. Explicit null always wins."""
    setup = case.get('setup') or {}
    payload = {}
    base = setup.get('base_claim_fixture')
    if base:
        payload.update(load_json(base))
    payload.update(copy.deepcopy(setup.get('overrides') or {}))
    payload.update(copy.deepcopy(case['input']))
    fixtures = [f for f in case['fixtures'] if f != base]
    if fixtures:
        payload['fixture_paths'] = fixtures
    return payload


def resolve_entrypoint(name):
    entry = next(e for e in contract()['entrypoints'] if e['name'] == name)
    module_name, function_name = entry['maps_to'].rsplit('.', 1)
    return getattr(importlib.import_module(module_name), function_name)


def lock_hash():
    lock = ROOT / 'requirements.lock.txt'
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None


def run_case(case, suite, allow_model=False, embeddings=False):
    payload = build_payload(case)
    harness = CaseHarness(case, allow_model=allow_model, embeddings=embeddings)
    started = time.perf_counter()
    error = None
    blocked = None
    try:
        result = harness.call(resolve_entrypoint(case['entrypoint']), payload)
    except CapabilityUnavailable as exc:  # visible, never counted as PASS or FAIL
        result, blocked = {}, str(exc)
    except Exception as exc:  # recorded as ERROR, never as PASS
        result, error = {}, '%s: %s' % (type(exc).__name__, exc)
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    envelope = {
        'case_id': case['id'],
        'result': result,
        'observations': {},
        'response_text': (result.get('message') or '') if isinstance(result, dict) else '',
        'evidence': [{'rule_id': rule} for rule in (result.get('evidence_ids') or [])],
        'run_metadata': {
            'spec_version': suite['spec_version'], 'policy_version': suite['policy_version'],
            'suite_version': suite['suite_version'], 'app_commit': None, 'model_id': None, 'prompt_hash': None,
            'lock_hash': lock_hash(), 'clock': case['preconditions']['clock'], 'status': 'NOT_RUN',
            'duration_ms': duration_ms, 'reviewer': None, 'version_control': 'none',
            'model_calls_allowed': allow_model, 'embeddings': embeddings,
        },
    }
    envelope['observations'] = harness.observations(envelope)
    harness.close()
    # Expectations are read only from here on.
    checks = [] if (error or blocked) else evaluate_checks(envelope, case['automatic_checks'])
    if blocked:
        automatic = 'BLOCKED_CAPABILITY'
        error = blocked
    elif error:
        automatic = 'ERROR'
    elif all(c['passed'] for c in checks):
        automatic = 'PASS'
    else:
        automatic = 'FAIL'
    human = 'PENDING' if case['human_checks'] else 'NOT_REQUIRED'
    status = {'ERROR': 'ERROR', 'FAIL': 'FAIL', 'BLOCKED_CAPABILITY': 'BLOCKED_CAPABILITY'}.get(
        automatic, 'PENDING_REVIEW' if human == 'PENDING' else 'PASS')
    envelope['run_metadata'].update(status=status, automatic_status=automatic, human_review_status=human)
    return envelope, checks, error


def select_cases(cases, args):
    if args.case:
        return [c for c in cases if c['id'] in set(args.case)]
    if args.milestone:
        names = set(MILESTONE_ENTRYPOINTS[args.milestone])
    elif args.through:
        names = set(entrypoints_through(args.through))
    else:
        names = {e['name'] for e in contract()['entrypoints']}
    return [c for c in cases if c['entrypoint'] in names]


def write_outputs(out, rows, suite):
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'envelopes.jsonl').open('w', encoding='utf-8') as handle:
        for case, envelope, checks, error in rows:
            handle.write(json.dumps(envelope, ensure_ascii=False) + '\n')
    with (out / 'checks.jsonl').open('w', encoding='utf-8') as handle:
        for case, envelope, checks, error in rows:
            handle.write(json.dumps({'case_id': case['id'], 'error': error, 'checks': checks},
                                    ensure_ascii=False, default=str) + '\n')
    with (out / 'human_review.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['case_id', 'criterion_or_expected_path', 'expected_meaning', 'actual', 'response_text',
                         'reviewer_decision', 'reviewer_reason'])
        for case, envelope, checks, error in rows:
            for human in case['human_checks']:
                path = human.get('expected_path')
                actual = resolve_pointer(envelope, '/result' + path) if path else ''
                writer.writerow([case['id'], path or human.get('criterion'), json.dumps(human.get('expected_meaning')),
                                 json.dumps(actual, default=str) if path else '', envelope['response_text'], '', ''])
    statuses = Counter(e['run_metadata']['status'] for _, e, _, _ in rows)
    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'spec_version': suite['spec_version'], 'suite_version': suite['suite_version'],
        'cases_selected': len(rows), 'status_counts': dict(statuses),
        'automatic_counts': dict(Counter(e['run_metadata']['automatic_status'] for _, e, _, _ in rows)),
        'model_calls_allowed': any(e['run_metadata'].get('model_calls_allowed') for _, e, _, _ in rows),
        'by_category': {k: dict(Counter(e['run_metadata']['status'] for c, e, _, _ in rows if c['category'] == k))
                        for k in sorted({c['category'] for c, *_ in rows})},
        'by_split': {k: dict(Counter(e['run_metadata']['status'] for c, e, _, _ in rows if c['split'] == k))
                     for k in sorted({c['split'] for c, *_ in rows})},
        'not_selected': len(load_cases()['cases']) - len(rows),
        'note': 'PENDING_REVIEW cases passed every automatic check and await the human rubric; they are not PASS.',
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--milestone', choices=sorted(MILESTONE_ENTRYPOINTS))
    group.add_argument('--through', choices=sorted(MILESTONE_ENTRYPOINTS))
    group.add_argument('--case', action='append')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--allow-model', action='store_true',
                        help='Permit real model calls (designated model evaluation runs only; spends API credit).')
    parser.add_argument('--embeddings', action='store_true',
                        help='Use the configured embedding provider (hybrid retrieval). Default is keyword-only so '
                             'offline runs never download a model.')
    args = parser.parse_args(argv)
    suite = load_cases()
    rows = []
    for case in select_cases(suite['cases'], args):
        envelope, checks, error = run_case(case, suite, allow_model=args.allow_model, embeddings=args.embeddings)
        rows.append((case, envelope, checks, error))
    label = args.milestone or args.through or 'cases'
    out = args.out or ROOT / 'runtime' / 'evaluation' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + label)
    summary = write_outputs(out, rows, suite)
    for case, envelope, checks, error in rows:
        failed = [c for c in checks if not c['passed']]
        detail = error or '; '.join('%s expected %r got %r' % (c['path'], c['expected'], c['actual']) for c in failed)
        print('%-6s %-30s %-15s %s' % (case['id'], case['entrypoint'], envelope['run_metadata']['status'], detail))
    print('Selected %d cases | status %s | automatic %s' % (
        summary['cases_selected'], summary['status_counts'], summary['automatic_counts']))
    print('Results written to %s' % out.relative_to(ROOT) if out.is_relative_to(ROOT) else out)
    if summary['automatic_counts'].get('BLOCKED_CAPABILITY'):
        print('BLOCKED_CAPABILITY cases need a configured model and --allow-model; they are not failures or passes.')
    return 1 if summary['automatic_counts'].get('FAIL') or summary['automatic_counts'].get('ERROR') else 0


if __name__ == '__main__':
    sys.exit(main())
