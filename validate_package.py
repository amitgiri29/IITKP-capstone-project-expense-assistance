"""Validate the test package only. Does not run or evaluate an AI assistant."""
import json
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from collections import Counter

root = Path(__file__).resolve().parent
suite = json.loads((root / 'tests/golden_cases.json').read_text())
cases = suite['cases']
rules = {x['id'] for x in json.loads((root / 'policy_sources/policy.json').read_text())['rules']}
assert len(cases) >= 100 and len(cases) == suite['count']
assert len({c['id'] for c in cases}) == len(cases)
groups = {}
for c in cases:
    assert c['execution_status'] == 'NOT_RUN'
    assert c['input'] and c['expected'] and c['assertions']
    assert set(c['required_rule_ids']).issubset(rules), c['id']
    for f in c['fixtures']:
        assert (root / f).is_file(), (c['id'], f)
    groups.setdefault(c['scenario_group'], set()).add(c['split'])
assert all(len(splits) == 1 for splits in groups.values())
jsonl = [json.loads(line) for line in (root / 'tests/golden_cases.jsonl').read_text().splitlines()]
assert jsonl == cases

# Every number comes from the reviewed rule registry. No cap is written into this file.
rule_registry = json.loads((root / 'policy_sources/rule_registry.json').read_text())
reference = json.loads((root / 'policy_sources/reference_data.json').read_text())
assert rule_registry['policy_version'] == '1.1'
assert rule_registry['review_status'] in {'DRAFT_PENDING_SECOND_REVIEWER', 'REVIEWED'}
cap_ids = {c['cap_id'] for c in rule_registry['caps']}
assert len(cap_ids) == len(rule_registry['caps'])
param_ids = {p['parameter_id'] for p in rule_registry['parameters']}
assert len(param_ids) == len(rule_registry['parameters'])
for entry in rule_registry['caps'] + rule_registry['parameters']:
    assert entry['rule_id'] in rules, entry
for entry in rule_registry['caps']:
    assert Decimal(entry['cap_amount']) > 0, entry['cap_id']
    assert entry['conversion_order'] in {'before_conversion', 'after_conversion'}, entry['cap_id']
    assert entry['effective_from'] == rule_registry['effective_from'], entry['cap_id']
    assert entry['effective_to'] == rule_registry['effective_to'], entry['cap_id']

cap_by_group = {c['scenario_group']: c for c in rule_registry['caps'] if c['scenario_group']}
assert len(cap_by_group) == len([c for c in rule_registry['caps'] if c['scenario_group']])

def rounded(value):
    return Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
calculation_cases = 0
for c in cases:
    if c['category'] != 'calculation':
        continue
    calculation_cases += 1
    x, e = c['input'], c['expected']
    entry = cap_by_group.get(c['scenario_group'])
    assert entry, (c['id'], 'no registry cap for scenario group ' + c['scenario_group'])
    amount, rate = Decimal(str(x['amount'])), Decimal(str(x['fx_rate']))
    cap = Decimal(entry['cap_amount'])
    claimed = rounded(amount * rate)
    if entry['conversion_order'] == 'before_conversion':
        assert x['currency'] in {entry['cap_currency'], 'INR'}, (c['id'], x['currency'])
        eligible = rounded(min(amount, cap) * rate)
    else:
        eligible = rounded(min(claimed, cap))
    assert claimed == Decimal(str(e['claimed_total_inr'])), (c['id'], 'claimed')
    assert eligible == Decimal(str(e['eligible_total_inr'])), (c['id'], 'eligible')
    assert claimed - eligible == Decimal(str(e['over_cap_total_inr'])), (c['id'], 'over cap')
    expected_budget = 'OVER_BUDGET' if claimed > Decimal(str(x['budget_inr'])) else 'WITHIN_BUDGET'
    assert e['budget_status'] == expected_budget, c['id']
assert calculation_cases == 30, calculation_cases

# Reference data must cover every value the suite actually uses.
countries = {c['code'] for c in reference['countries']}
currencies = {c['code'] for c in reference['currencies']}
vocab = reference['vocabularies']
fx_rates = {f['fx_reference']: f['rates'] for f in reference['fx']['fixtures']}

def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)

for c in cases:
    for key, value in walk(c['input']):
        if key == 'country' and isinstance(value, str):
            assert value in countries, (c['id'], value)
        if key == 'currency' and isinstance(value, str):
            assert value in currencies, (c['id'], value)
    for key, value in walk(c['expected']):
        if key == 'readiness':
            assert value in vocab['readiness'], (c['id'], value)
        if key == 'compliance_status':
            assert value in vocab['compliance_status'], (c['id'], value)
        if key == 'budget_status':
            assert value in vocab['budget_status'], (c['id'], value)
        if key == 'run_status':
            assert value in vocab['run_status'], (c['id'], value)
    if c['input'].get('fx_reference') in fx_rates and c['input'].get('currency'):
        documented = fx_rates[c['input']['fx_reference']].get(c['input']['currency'])
        if documented is not None and 'fx_rate' in c['input']:
            assert Decimal(documented) == Decimal(str(c['input']['fx_rate'])), (c['id'], 'fx rate')
for city in reference['city_tiers']['metro']:
    assert reference['city_aliases'].get(city) == city, city
for alias, canonical in reference['city_aliases'].items():
    assert canonical in reference['city_aliases'], alias

for c in cases:
    if c['category'] == 'search':
        fixture = json.loads((root / c['fixtures'][0]).read_text())
        ids = {o['id'] for o in fixture['offers']}
        for field in ['recommended_ids', 'noncompliant_ids', 'provisional_ids']:
            assert set(c['expected'].get(field, [])).issubset(ids), c['id']
        assert len(c['expected'].get('recommended_ids', [])) <= 3

for name in ['01_Project_Specification.docx', '02_Fictional_Travel_Policy.docx',
             '03_Beginner_Team_Plan.docx', 'START_HERE.html']:
    assert (root / name).is_file(), name
assert len(list((root / 'fixtures/receipts').glob('*.png'))) == 20
assert len(list((root / 'fixtures/search').glob('*.json'))) == 20
# Documentation-only cross-file and traceability checks. No assistant is invoked.
import re
from urllib.parse import unquote
policy = json.loads((root / 'policy_sources/policy.json').read_text())
contract = json.loads((root / 'IMPLEMENTATION_CONTRACT.json').read_text())
assert policy['version'] == suite['policy_version'] == contract['policy_version'] == '1.1'
assert suite['suite_version'] == contract['test_suite_version'] == '1.1'
assert suite['spec_version'] == contract['spec_version'] == '1.6'
assert contract['stage'] in {'DOCUMENTATION_ONLY', 'IMPLEMENTATION_M0_M8'}
assert len(cases) == 120
case_by_id = {c['id']: c for c in cases}
core = json.loads((root / 'tests/golden_100.json').read_text())['cases']
supplemental = json.loads((root / 'tests/supplemental_20.json').read_text())['cases']
assert len(core) == 100 and len(supplemental) == 20
assert not ({c['id'] for c in core} & {c['id'] for c in supplemental})
assert {c['id'] for c in core + supplemental} == set(case_by_id)
for collection, name in [(core, 'golden_100'), (supplemental, 'supplemental_20')]:
    assert all(c == case_by_id[c['id']] for c in collection)
    lines = [json.loads(x) for x in (root / ('tests/' + name + '.jsonl')).read_text().splitlines()]
    assert lines == collection
registry = json.loads((root / 'docs/REQUIREMENTS.json').read_text())
requirements = {r['id']: r for r in registry['requirements']}
trace = json.loads((root / 'tests/TRACEABILITY.json').read_text())['cases']
assert len(trace) == 120 and {t['case_id'] for t in trace} == set(case_by_id)
for t in trace:
    c = case_by_id[t['case_id']]
    assert t['requirement_ids'] == c['requirement_ids'], c['id']
    assert t['policy_rule_ids'] == c['required_rule_ids'], c['id']
    assert t['fixtures'] == c['fixtures'] and t['entrypoint'] == c['entrypoint'], c['id']

def leaves(obj, prefix=''):
    for key, value in obj.items():
        path = prefix + '/' + key
        if isinstance(value, dict):
            yield from leaves(value, path)
        else:
            yield path, value

for c in cases:
    assert c['requirement_ids'] and set(c['requirement_ids']) <= set(requirements), c['id']
    assert c['steps'] and c['entrypoint'] and (c['automatic_checks'] or c['human_checks']), c['id']
    for rid in c['requirement_ids']:
        assert c['id'] in requirements[rid]['golden_case_ids'], (c['id'], rid)
    checks = {x['path'].removeprefix('/result').removeprefix('/observations'): x for x in c['automatic_checks']}
    human = {x['expected_path']: x for x in c['human_checks'] if 'expected_path' in x}
    expected_leaves = dict(leaves(c['expected']))
    assert set(checks) | set(human) == set(expected_leaves), c['id']
    assert not set(checks) & set(human), c['id']
    for path, value in expected_leaves.items():
        if path in checks:
            assert checks[path]['expected'] == value, (c['id'], path)
        else:
            assert human[path]['expected_meaning'] == value, (c['id'], path)
    if 'base_claim_fixture' in c.get('setup', {}):
        assert c['setup']['base_claim_fixture'] in c['fixtures']
for r in requirements.values():
    assert set(r['policy_rule_ids']) <= rules, r['id']
    assert r['verification'] in {'golden_suite', 'implementation_test'}, r['id']
    if r['verification'] == 'golden_suite':
        assert r['golden_case_ids'], r['id']
    else:
        assert not r['golden_case_ids'] and r['implementation_checks'], r['id']
    assert all(r['id'] in case_by_id[cid]['requirement_ids'] for cid in r['golden_case_ids'])
for r in policy['rules']:
    text = (root / 'policy_sources' / (r['id'] + '.txt')).read_text()
    assert r['text'] in text and 'Policy 1.1' in text
manifest = json.loads((root / 'policy_sources/corpus_manifest.json').read_text())
assert {d['rule_id'] for d in manifest['documents']} == rules
for d in manifest['documents']:
    assert (root / 'policy_sources' / d['path']).is_file()
LOCAL_ONLY_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'runtime', 'node_modules', '.playwright-cli'}
def package_files(pattern):
    return [f for f in root.rglob(pattern) if not set(f.relative_to(root).parts) & LOCAL_ONLY_DIRS]
for f in package_files('*.json'):
    json.loads(f.read_text())
for f in package_files('*.md'):
    for href in re.findall(r'\]\(([^)]+)\)', f.read_text()):
        if '://' not in href and not href.startswith('#'):
            assert (f.parent / unquote(href.split('#')[0])).exists(), (f, href)
for href in re.findall(r'href="([^"]+)"', (root / 'START_HERE.html').read_text()):
    if '://' not in href and not href.startswith('#'):
        assert (root / unquote(href)).exists(), href
for name in ['README.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', '.gitignore', '.gitattributes', '.env.example',
             'docs/BEFORE_IMPLEMENTATION.txt', 'docs/REPOSITORY_WORKFLOW.txt', 'docs/TEST_PROTOCOL.txt',
             'schemas/domain.schema.json', 'schemas/evaluation.schema.json']:
    assert (root / name).is_file(), name
assert 'Version 1.6' in (root / 'SPECIFICATION.txt').read_text()
langsmith = json.loads((root / 'docs/LANGSMITH_CONTRACT.json').read_text())
assert langsmith['sdk']['version'] == '0.14.17'
assert len(langsmith['acceptance_checks']) == 6
assert langsmith['golden_datasets']['target_receives_reference_outputs'] is False
stack = json.loads((root / 'TECH_STACK.json').read_text())
assert any(p['name'] == 'langsmith' and p['version'] == '0.14.17' for p in stack['packages'])
assert 'langsmith==0.14.17' in (root / 'requirements-proposed.txt').read_text()
assert 'LANGSMITH_TRACING=false' in (root / '.env.example').read_text()
assert 'No mandatory paid tracing service' not in (root / 'SPECIFICATION.txt').read_text()
deployment = json.loads((root / 'docs/DEPLOYMENT_CONTRACT.json').read_text())
assert deployment['status'] == 'NOT_DEPLOYED'
assert len(deployment['acceptance_checks']) == 8
assert deployment['versions']['docker_engine'] == '29.9.3'
assert 'boto3==1.43.126' in (root / 'requirements-aws-proposed.txt').read_text()
assert 'Docker is optional' not in (root / 'SPECIFICATION.txt').read_text()
assert (root / deployment['diagram']).is_file()

# --- new in 1.6: entrypoint contracts, derived-artifact freshness, schema shape ---
entrypoints = {e['name']: e for e in contract['entrypoints']}
assert len(entrypoints) == len(contract['entrypoints'])
used = {c['entrypoint'] for c in cases}
assert used == set(entrypoints), used ^ set(entrypoints)
for c in cases:
    e = entrypoints[c['entrypoint']]
    assert c['test_layer'] == e['test_layer'], (c['id'], c['entrypoint'])
    assert set(c['input']) <= set(e['input_fields']), (c['id'], set(c['input']) - set(e['input_fields']))
    declared = set(e['result_fields']) | set(e['observation_fields'])
    assert set(c['expected']) <= declared, (c['id'], set(c['expected']) - declared)
    assert set(c['requirement_ids']) <= set(e['requirement_ids']), c['id']
for e in entrypoints.values():
    assert e['route'] in {None, 'policy_simple', 'receipt_review', 'travel_search'}, e['name']
    assert e['maps_to'] and '.' in e['maps_to'], e['name']
    assert e['golden_case_count'] == sum(1 for c in cases if c['entrypoint'] == e['name']), e['name']
assert set(contract['router']['decision_order']), 'router decision order must be documented'
assert contract['identity']['grade_authority'], 'grade authority must be documented'
for code in reference['vocabularies']['error_code']:
    assert code['http_status'] in {400, 401, 403, 404, 413, 415, 422, 429, 500, 503, 504}, code

# Lightweight structural check of the two new data files against their schemas.
def check_schema(data, schema, defs, path='$'):
    if '$ref' in schema:
        return check_schema(data, defs[schema['$ref'].split('/')[-1]], defs, path)
    if 'enum' in schema:
        assert data in schema['enum'], (path, data)
    if 'pattern' in schema and isinstance(data, str):
        assert re.match(schema['pattern'], data), (path, data)
    if schema.get('type') == 'object' or 'properties' in schema:
        assert isinstance(data, dict), path
        for required in schema.get('required', []):
            assert required in data, (path, required)
        if schema.get('additionalProperties') is False:
            unexpected = set(data) - set(schema.get('properties', {}))
            assert not unexpected, (path, unexpected)
        for key, value in data.items():
            if key in schema.get('properties', {}):
                check_schema(value, schema['properties'][key], defs, path + '.' + key)
    elif schema.get('type') == 'array' or 'items' in schema:
        assert isinstance(data, list), path
        assert len(data) >= schema.get('minItems', 0), path
        for index, item in enumerate(data):
            check_schema(item, schema.get('items', {}), defs, '%s[%d]' % (path, index))

for data_path, schema_path in [('policy_sources/rule_registry.json', 'schemas/rule_registry.schema.json'),
                               ('policy_sources/reference_data.json', 'schemas/reference_data.schema.json')]:
    schema = json.loads((root / schema_path).read_text())
    check_schema(json.loads((root / data_path).read_text()), schema, schema.get('$defs', {}), data_path)

# Derived artifacts must be rebuilt whenever one of their sources changes.
package_manifest = json.loads((root / 'manifest.json').read_text())
import hashlib
def digest(relative):
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()
tracked = {entry['path'] for entry in package_manifest['files']}
drifted = [entry['path'] for entry in package_manifest['files'] if digest(entry['path']) != entry['sha256']]
assert not drifted, 'manifest.json is out of date for: %s — run python build_package.py' % drifted
stale = []
for derived, provenance in package_manifest['derived_artifacts'].items():
    assert derived in tracked, derived
    for source, recorded in provenance['source_sha256'].items():
        assert source in tracked, (derived, source)
        if digest(source) != recorded:
            stale.append('%s (source %s changed)' % (derived, source))
assert not stale, 'derived artifacts are stale: %s — run python build_package.py' % stale
outlines = json.loads((root / 'docs/docx_outlines.json').read_text())['documents']
for source, entry in outlines.items():
    text_lines = {line.strip() for line in (root / source).read_text().splitlines()}
    for heading in entry['headings']:
        assert heading['text'] in text_lines, (source, heading['text'])
    assert (root / entry['derived']).is_file(), entry['derived']
    for image in entry['images']:
        assert (root / image['path']).is_file(), image['path']
for name in ['policy_sources/rule_registry.json', 'policy_sources/reference_data.json',
             'schemas/rule_registry.schema.json', 'schemas/reference_data.schema.json',
             'docs/docx_outlines.json', 'build_package.py']:
    assert (root / name).is_file(), name

# Every repository data path named in the specification must exist.
spec_text = (root / 'SPECIFICATION.txt').read_text()
referenced = set(re.findall(
    r'(?:docs|policy_sources|schemas|tests|architecture|fixtures)/[A-Za-z0-9_./-]+'
    r'\.(?:json|txt|png|mmd|jsonl)', spec_text))
absent = sorted(path for path in referenced if not (root / path).is_file())
assert not absent, 'SPECIFICATION.txt references missing files: %s' % absent

# Version strings that live in prose must agree with the contract.
spec_version = contract['spec_version']
for path, needle in [('SPECIFICATION.txt', 'Version ' + spec_version),
                     ('START_HERE.html', 'Specification ' + spec_version),
                     ('TECH_STACK.txt', 'Specification ' + spec_version),
                     ('docs/TEST_PROTOCOL.txt', 'Specification ' + spec_version),
                     ('docs/BEFORE_IMPLEMENTATION.txt', 'Specification ' + spec_version),
                     ('docs/TEAM_PLAN.txt', 'Specification ' + spec_version),
                     ('tests/GOLDEN_100.txt', 'Specification ' + spec_version),
                     ('tests/SUPPLEMENTAL_20.txt', 'Specification ' + spec_version)]:
    assert needle in (root / path).read_text(), (path, needle)
assert json.loads((root / 'TECH_STACK.json').read_text())['spec_version'] == spec_version
assert json.loads((root / 'docs/REQUIREMENTS.json').read_text())['spec_version'] == spec_version
assert json.loads((root / 'policy_sources/rule_registry.json').read_text())['spec_version'] == spec_version
assert json.loads((root / 'policy_sources/reference_data.json').read_text())['spec_version'] == spec_version
for section in ['technology_stack', 'observability', 'deployment']:
    assert contract[section]['spec_version'] == spec_version, section
for path in ['README.txt', 'docs/AWS_DEPLOYMENT_PLAN.txt', 'docs/LANGSMITH_PLAN.txt']:
    assert ('Specification ' + spec_version) in (root / path).read_text(), path
assert package_manifest['package_version'] == spec_version
assert json.loads((root / 'docs/DECISIONS.json').read_text())['documentation_version'] == spec_version
assert ('Specification ' + spec_version) in (root / 'docs/CHANGELOG.txt').read_text()

print('PASS: 100 core + 20 supplemental cases; versions, assertions, traceability, fixtures and local links')
print('Registry:', len(rule_registry['caps']), 'caps and', len(rule_registry['parameters']),
      'parameters, review status', rule_registry['review_status'],
      '|', len(cap_by_group), 'caps have golden boundary coverage')
print('Entrypoints:', len(entrypoints), '| derived artifacts verified:', len(package_manifest['derived_artifacts']),
      '| files hashed:', len(package_manifest['files']))
print('Cases:', len(cases), '| Categories:', dict(Counter(c['category'] for c in cases)))
print('Core categories:', dict(Counter(c['category'] for c in core)))
print('Splits:', dict(Counter(c['split'] for c in cases)))
print('Stage:', contract['stage'], '| golden master execution_status stays NOT_RUN; run results live in runtime/evaluation/.')
print('Package validation is not assistant evaluation; run python -m evaluation.driver for that.')
