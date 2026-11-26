"""Regenerate every derived artifact in this package from its source of truth.

Derived artifacts are never hand-edited. Run this after changing SPECIFICATION.txt,
policy_sources/policy.json, docs/TEAM_PLAN.txt or any tracked file, then run
python validate_package.py.

This script needs python-docx. validate_package.py deliberately does not: it
verifies freshness from the source hashes recorded in manifest.json, so the
documentation CI job keeps running on the standard library alone.
"""
import hashlib
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent
TOTAL_TABLE_TWIPS = 9648
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'runtime', 'node_modules', '.playwright-cli'}
SKIP_NAMES = {'.DS_Store', 'manifest.json', '.env'}   # .env is local secrets: never hashed or published


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def tracked_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS or rel.name in SKIP_NAMES:
            continue
        yield rel


# --------------------------------------------------------------------------
# Flat-text documents (SPECIFICATION.txt, docs/TEAM_PLAN.txt) -> Word
# --------------------------------------------------------------------------
def parse_flat_text(path, heading_levels, layout, stop_prefix=None):
    """Return (title, subtitle, blocks) from a flattened text document.

    layout gives the zero-based line numbers of the title and subtitle and the
    first body line, because SPECIFICATION.txt carries a three-line plain-text
    banner that the Word copy does not.

    A line present in heading_levels is a heading. Consecutive lines containing
    ' | ' form one table whose first row is the header. A line beginning
    'DIAGRAM DESCRIPTION:' is replaced by the next architecture image. Blank
    lines separate blocks; a second consecutive blank line becomes one empty
    paragraph, which is how the original Word documents were laid out.
    """
    lines = pathlib.Path(path).read_text(encoding='utf-8').splitlines()
    title = lines[layout['title_line']]
    subtitle = lines[layout['subtitle_line']]
    i = layout['body_start']
    blocks, pending = [], 0
    while i < len(lines):
        line = lines[i]
        if stop_prefix and line.startswith(stop_prefix):
            break
        if line == '':
            pending += 1
            i += 1
            continue
        blocks.extend([('empty', '')] * max(0, pending - 1))
        pending = 0
        if line.startswith('DIAGRAM DESCRIPTION:'):
            blocks.append(('img', line))
            i += 1
        elif ' | ' in line:
            rows = []
            while i < len(lines) and ' | ' in lines[i]:
                rows.append([cell.strip() for cell in lines[i].split('|')])
                i += 1
            blocks.append(('tbl', rows))
        elif line in heading_levels:
            blocks.append(('h%d' % heading_levels[line], line))
            i += 1
        else:
            blocks.append(('text', line))
            i += 1
    return title, subtitle, blocks


def column_widths(rows):
    widths = []
    for col in range(len(rows[0])):
        longest = max(len(row[col]) for row in rows if col < len(row))
        widths.append(min(max(longest, 8), 60))
    total = sum(widths)
    return [max(int(TOTAL_TABLE_TWIPS * w / total), 700) for w in widths]


def render_docx(template, title, subtitle, blocks, images, out_path):
    import docx
    from docx.oxml.ns import qn
    from docx.shared import Emu, Twips

    document = docx.Document(template)          # reuse the original styles only
    body = document.element.body
    for child in list(body.iterchildren()):
        if child.tag != qn('w:sectPr'):
            body.remove(child)

    sect = body.find(qn('w:sectPr'))

    def append(element):
        if sect is not None:
            sect.addprevious(element)
        else:
            body.append(element)

    def paragraph(text, style):
        para = document.add_paragraph(text, style=style)
        append(para._p)
        return para

    paragraph(title, 'Title')
    paragraph(subtitle, 'Subtitle')
    image_index = 0
    for kind, value in blocks:
        if kind == 'empty':
            paragraph('', 'Normal')
        elif kind == 'text':
            paragraph(value, 'Normal')
        elif kind.startswith('h'):
            paragraph(value, 'Heading %s' % kind[1:])
        elif kind == 'img':
            para = paragraph('', 'Normal')
            run = para.add_run()
            image = images[image_index]
            run.add_picture(str(ROOT / image['path']), width=Emu(image['width_emu']))
            image_index += 1
        elif kind == 'tbl':
            columns = max(len(row) for row in value)
            table = document.add_table(rows=len(value), cols=columns, style='Normal Table')
            table.autofit = False
            widths = column_widths(value)
            for r, row in enumerate(value):
                for c in range(columns):
                    cell = table.cell(r, c)
                    cell.width = Twips(widths[c])
                    cell.text = row[c] if c < len(row) else ''
                    if r == 0:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
            append(table._tbl)
    assert image_index == len(images), 'diagram count does not match the text'
    document.save(out_path)


def build_specification(outlines):
    entry = outlines['SPECIFICATION.txt']
    levels = {h['text']: h['level'] for h in entry['headings']}
    title, subtitle, blocks = parse_flat_text(
        ROOT / 'SPECIFICATION.txt', levels, entry['layout'], stop_prefix='EDITABLE DIAGRAM')
    seen = {text for kind, text in blocks if kind.startswith('h')}
    missing = sorted(set(levels) - seen)
    assert not missing, 'outline lists headings absent from the specification: %s' % missing
    render_docx(ROOT / '01_Project_Specification.docx', title, subtitle, blocks,
                entry['images'], ROOT / '01_Project_Specification.docx')
    return ['SPECIFICATION.txt', 'docs/docx_outlines.json'] + [i['path'] for i in entry['images']]


def build_team_plan(outlines):
    entry = outlines['docs/TEAM_PLAN.txt']
    levels = {h['text']: h['level'] for h in entry['headings']}
    title, subtitle, blocks = parse_flat_text(ROOT / 'docs/TEAM_PLAN.txt', levels, entry['layout'])
    render_docx(ROOT / '03_Beginner_Team_Plan.docx', title, subtitle, blocks,
                entry['images'], ROOT / '03_Beginner_Team_Plan.docx')
    return ['docs/TEAM_PLAN.txt', 'docs/docx_outlines.json']


def build_policy():
    policy = json.loads((ROOT / 'policy_sources/policy.json').read_text(encoding='utf-8'))
    spec_version = json.loads(
        (ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text(encoding='utf-8'))['spec_version']
    blocks = [('text', 'This invented policy defines the business rules for specification %s '
                       'and golden suite 1.1. It describes no real company and no real prices. '
                       'policy_sources/rule_registry.json holds the same numbers in reviewed '
                       'machine-readable form and is the authority for calculation.' % spec_version)]
    for rule in policy['rules']:
        blocks.append(('h2', '%s %s' % (rule['id'], rule['title'])))
        blocks.append(('text', rule['text']))
    render_docx(ROOT / '02_Fictional_Travel_Policy.docx',
                'Fictional Travel Expense Policy',
                '%s | Version %s | Capstone demonstration only' % (policy['company'], policy['version']),
                blocks, [], ROOT / '02_Fictional_Travel_Policy.docx')
    return ['policy_sources/policy.json', 'IMPLEMENTATION_CONTRACT.json']


def build_golden_exports():
    suite = json.loads((ROOT / 'tests/golden_cases.json').read_text(encoding='utf-8'))
    cases = suite['cases']
    core = [c for c in cases if c['tier'] == 'core_100']
    supplemental = [c for c in cases if c['tier'] == 'supplemental']
    assert len(core) == 100 and len(supplemental) == 20
    for name, subset, count_key in [('golden_100', core, 'core_count'),
                                    ('supplemental_20', supplemental, 'supplemental_count')]:
        export = dict(suite)
        export['cases'] = subset
        export['count'] = len(subset)
        (ROOT / ('tests/%s.json' % name)).write_text(
            json.dumps(export, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for name, subset in [('golden_cases', cases), ('golden_100', core),
                         ('supplemental_20', supplemental)]:
        (ROOT / ('tests/%s.jsonl' % name)).write_text(
            ''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in subset), encoding='utf-8')
    return ['tests/golden_cases.json']


def build_requirements_text():
    registry = json.loads((ROOT / 'docs/REQUIREMENTS.json').read_text(encoding='utf-8'))
    lines = ['SPECIFICATION REQUIREMENTS ANNEX', 'Version %s' % registry['spec_version'], '']
    for req in registry['requirements']:
        lines.append('%s | %s | %s' % (req['id'], req['parent_requirement'], req['title']))
        lines.append(req['requirement'])
        lines.append('Policy: ' + ', '.join(req['policy_rule_ids']))
        if req.get('verification') == 'implementation_test':
            lines.append('Tests: implementation tests; see docs/TEST_PROTOCOL.txt section 8')
            lines.append('Checks: ' + '; '.join(req['implementation_checks']))
        else:
            lines.append('Tests: ' + ', '.join(req['golden_case_ids']))
        lines.append('')
    (ROOT / 'docs/REQUIREMENTS.txt').write_text(
        '\n'.join(lines).rstrip('\n') + '\n', encoding='utf-8')
    return ['docs/REQUIREMENTS.json']


def write_manifest(provenance):
    path = ROOT / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    contract = json.loads((ROOT / 'IMPLEMENTATION_CONTRACT.json').read_text(encoding='utf-8'))
    suite = json.loads((ROOT / 'tests/golden_cases.json').read_text(encoding='utf-8'))
    manifest['package_version'] = contract['spec_version']
    manifest['updated_date'] = date.today().isoformat()
    manifest['policy_version'] = suite['policy_version']
    manifest['suite_version'] = suite['suite_version']
    manifest['derived_artifacts'] = {
        derived: {
            'sources': sorted(sources),
            'source_sha256': {s: sha256(ROOT / s) for s in sorted(sources)},
        }
        for derived, sources in sorted(provenance.items())
    }
    manifest['files'] = [
        {'path': rel.as_posix(), 'bytes': (ROOT / rel).stat().st_size, 'sha256': sha256(ROOT / rel)}
        for rel in tracked_files()
    ]
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return len(manifest['files'])


def main():
    outlines = json.loads((ROOT / 'docs/docx_outlines.json').read_text(encoding='utf-8'))['documents']
    provenance = {}
    provenance['01_Project_Specification.docx'] = build_specification(outlines)
    provenance['02_Fictional_Travel_Policy.docx'] = build_policy()
    provenance['03_Beginner_Team_Plan.docx'] = build_team_plan(outlines)
    provenance['docs/REQUIREMENTS.txt'] = build_requirements_text()
    exports = build_golden_exports()
    for name in ['tests/golden_100.json', 'tests/supplemental_20.json', 'tests/golden_cases.jsonl',
                 'tests/golden_100.jsonl', 'tests/supplemental_20.jsonl']:
        provenance[name] = exports
    count = write_manifest(provenance)
    print('Regenerated 3 Word documents, the requirements annex text and 5 golden '
          'exports; manifest covers %d files.' % count)
    print('Now run: python validate_package.py')


if __name__ == '__main__':
    sys.exit(main())
