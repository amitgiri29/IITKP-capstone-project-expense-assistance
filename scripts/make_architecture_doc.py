"""Build the versioned Word document 'Architecture & Implementation Overview'.

    python3 scripts/make_architecture_doc.py          (needs python-docx)

Bump DOC_VERSION and add a REVISIONS entry for every new edition. Diagrams come from
architecture/diagrams/*.png (rendered by scripts/render_diagrams.sh).
"""
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
DOC_VERSION = '1.1'
DOC_DATE = '10 November 2026'
REVISIONS = [
    ('1.0', '8 November 2026', 'Capstone team', 'First edition: architecture, technology roles, implemented use cases, '
                                        'deployment, quality evidence and roadmap as of application 0.2.0.'),
    ('1.1', DOC_DATE, 'Capstone team', 'Policy-upload RAG: LangChain loaders and text splitters for PDF, Word, text and '
                                        'Markdown uploads; vectors created on upload with local FastEmbed (stand-in for '
                                        'the hosted embedding API); hybrid BM25 + vector retrieval with rank fusion.'),
]
OUT = ROOT / 'docs' / 'architecture' / ('SPARKS_Expense_Assistant_Architecture_v%s.docx' % DOC_VERSION)
INK, SLATE, MUTED, ROSE, ROSE_DARK = '0F172A', '334155', '64748B', 'E11D48', 'BE123C'
FONT = 'Arial'
STATUS_COLOURS = {'In use': '047857', 'Built': '4F46E5', 'Installed, not yet used': 'B45309', 'Planned': '64748B',
                  'Not used': '64748B'}


# ---- helpers -------------------------------------------------------------------------------------------
def rgb(hex_colour):
    return RGBColor.from_string(hex_colour)


def shade(cell, fill):
    properties = cell._tc.get_or_add_tcPr()
    element = OxmlElement('w:shd')
    element.set(qn('w:val'), 'clear')
    element.set(qn('w:color'), 'auto')
    element.set(qn('w:fill'), fill)
    properties.append(element)


def borders(table, colour='E2E8F0'):
    properties = table._tbl.tblPr
    element = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        edge = OxmlElement('w:%s' % side)
        edge.set(qn('w:val'), 'single')
        edge.set(qn('w:sz'), '6')
        edge.set(qn('w:space'), '0')
        edge.set(qn('w:color'), colour)
        element.append(edge)
    properties.append(element)


def cell_text(cell, text, bold=False, colour=SLATE, size=9.5, mono=False):
    cell.text = ''
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    run.bold, run.font.size, run.font.color.rgb = bold, Pt(size), rgb(colour)
    if mono:
        run.font.name = 'Consolas'


def table(document, header, rows, widths, status_column=None, mono_columns=()):
    grid = document.add_table(rows=1, cols=len(header))
    grid.alignment = WD_TABLE_ALIGNMENT.CENTER
    borders(grid)
    for index, title in enumerate(header):
        cell = grid.rows[0].cells[index]
        cell_text(cell, title.upper(), bold=True, colour=MUTED, size=8)
        shade(cell, 'F8FAFC')
    for row in rows:
        cells = grid.add_row().cells
        for index, value in enumerate(row):
            colour = SLATE
            bold = False
            if index == status_column:
                colour = next((c for key, c in STATUS_COLOURS.items() if str(value).startswith(key)), SLATE)
                bold = True
            if index == 0:
                colour, bold = (INK, True) if index != status_column else (colour, True)
            cell_text(cells[index], str(value), bold=bold, colour=colour, mono=index in mono_columns)
    for row in grid.rows:
        for index, width in enumerate(widths):
            row.cells[index].width = Cm(width)
    document.add_paragraph()
    return grid


def heading(document, text, level=1):
    paragraph = document.add_heading(text, level=level)
    for run in paragraph.runs:
        run.font.color.rgb = rgb(INK if level == 1 else ROSE_DARK)
        run.font.name = FONT
    return paragraph


def para(document, text, size=10.5, colour=SLATE, italic=False, after=6):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(after)
    run = paragraph.add_run(text)
    run.font.size, run.font.color.rgb, run.italic = Pt(size), rgb(colour), italic
    return paragraph


def bullets(document, items):
    for item in items:
        paragraph = document.add_paragraph(style='List Bullet')
        paragraph.paragraph_format.space_after = Pt(2)
        if isinstance(item, tuple):
            lead = paragraph.add_run(item[0] + ' ')
            lead.bold, lead.font.color.rgb, lead.font.size = True, rgb(INK), Pt(10.5)
            body = paragraph.add_run(item[1])
            body.font.color.rgb, body.font.size = rgb(SLATE), Pt(10.5)
        else:
            run = paragraph.add_run(item)
            run.font.color.rgb, run.font.size = rgb(SLATE), Pt(10.5)


def figure(document, image, caption, width_cm=17.0):
    document.add_picture(str(ROOT / 'architecture' / 'diagrams' / image), width=Cm(width_cm))
    document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph = para(document, caption, size=9, colour=MUTED, italic=True, after=12)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def page_number_footer(section):
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run('SPARKS AI Lab · Architecture & Implementation Overview · v%s · page ' % DOC_VERSION)
    run.font.size, run.font.color.rgb = Pt(8), rgb(MUTED)
    for kind, text in (('begin', None), (None, 'PAGE'), ('end', None)):
        r = footer.add_run()
        r.font.size, r.font.color.rgb = Pt(8), rgb(MUTED)
        if kind:
            char = OxmlElement('w:fldChar')
            char.set(qn('w:fldCharType'), kind)
            r._r.append(char)
        else:
            instr = OxmlElement('w:instrText')
            instr.set(qn('xml:space'), 'preserve')
            instr.text = text
            r._r.append(instr)


# ---- document -----------------------------------------------------------------------------------------
def build():
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for side in ('left_margin', 'right_margin'):
        setattr(section, side, Cm(2.0))
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.8)
    normal = document.styles['Normal']
    normal.font.name, normal.font.size = FONT, Pt(10.5)
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    for name in ('Heading 1', 'Heading 2', 'Title', 'List Bullet'):
        document.styles[name].font.name = FONT
    page_number_footer(section)

    core = document.core_properties
    core.title = 'SPARKS AI Lab Expense Policy Assistant — Architecture & Implementation Overview'
    core.subject = 'Architecture, technology roles and implemented use cases'
    core.author = 'Capstone team'
    core.version = DOC_VERSION
    core.revision = len(REVISIONS)
    core.keywords = 'architecture, RAG, Claude, FastAPI, Streamlit, expense policy, capstone'
    core.comments = 'Fictional company. Generated by scripts/make_architecture_doc.py.'

    # Title page
    document.add_picture(str(ROOT / 'assets' / 'brand' / 'sparks-ai-lab-logo.png'), width=Cm(7.5))
    para(document, '', after=40)
    title = document.add_paragraph()
    run = title.add_run('Expense Policy Assistant')
    run.bold, run.font.size, run.font.color.rgb = True, Pt(30), rgb(INK)
    sub = document.add_paragraph()
    run = sub.add_run('Architecture & Implementation Overview')
    run.font.size, run.font.color.rgb = Pt(18), rgb(ROSE)
    para(document, 'How the application is built, which technologies it uses and why, and which use cases are '
                   'implemented today.', size=12, colour=SLATE, after=30)
    table(document, ['Item', 'Value'], [
        ('Document version', DOC_VERSION), ('Date', DOC_DATE), ('Status', 'Draft for review'),
        ('Application version', '0.3.0 (milestones M0–M3 complete, with policy-upload RAG; M4–M8 not started)'),
        ('Specification · policy · golden suite', '1.6 · 1.1 · 1.1'),
        ('Audience', 'Capstone reviewers, mentors and the project team'),
        ('Classification', 'SPARKS AI Lab is a fictional company. All data is synthetic.')], [5.5, 11.5])
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # Contents
    heading(document, 'Contents', 1)
    for line in ['1. Purpose and scope', '2. Architecture overview', '3. Technology stack and roles',
                 '4. Key flows', '5. Implemented use cases', '6. Not yet implemented', '7. Deployment',
                 '8. Security, privacy and governance', '9. Quality and verification', '10. Configuration and extensibility',
                 '11. Known limitations', 'Appendix A. API endpoints', 'Appendix B. Revision history']:
        para(document, line, after=2)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # 1
    heading(document, '1. Purpose and scope', 1)
    para(document, 'The Expense Policy Assistant helps SPARKS AI Lab employees understand the travel policy, check an '
                   'expense claim against it before submission, and see the limits that apply to them. Policy answers '
                   'are generated by a large language model but grounded in retrieved policy text; every monetary '
                   'number comes from a reviewed rule registry, never from the model.')
    para(document, 'This document describes the system as built in application version 0.3.0. Where a capability is '
                   'designed but not yet implemented, it is marked as planned and listed in section 6.')

    # 2
    heading(document, '2. Architecture overview', 1)
    figure(document, '01-system-architecture.png', 'Figure 1 — System architecture (green: implemented and in use; dashed: planned).')
    para(document, 'The system is organised in five layers. Each layer depends only on the layer below it, and external '
                   'services sit behind replaceable ports.')
    bullets(document, [
        ('Presentation.', 'A Streamlit web application with seven pages, a persona card, a live AI-status card and a '
                          'top-bar ask box. It holds no business logic and never sees provider credentials.'),
        ('API and security.', 'A FastAPI service that issues server-side session tokens, takes grade and role from the '
                              'company directory, enforces a per-session rate limit, validates uploads, and returns a '
                              'single error format. Administrator routes upload, chunk and index policy documents.'),
        ('Application.', 'Workflows (request guards, the policy-question pipeline, citation validation), a plain-Python '
                         'domain core that performs every calculation with Decimal arithmetic from the rule registry, '
                         'and a hybrid retrieval service (BM25 keyword search plus vector search, fused by rank, over the policy '
                         'and the administrator library).'),
        ('Adapters.', 'A model port with three providers (Claude Code CLI, Anthropic SDK, OpenAI-compatible endpoint), '
                      'an embeddings port (local FastEmbed now, hosted OpenAI-compatible endpoint later) with a SQLite '
                      'vector cache, a telemetry adapter that writes redacted local traces, and a planned travel-search port.'),
        ('Data.', 'SQLite for sessions, receipts, assessments and library documents; private per-session uploads; and '
                  'the read-only normative sources: 20 policy sections, the rule registry and reference data.'),
    ])
    para(document, 'Design principles:', colour=INK)
    bullets(document, [
        'Numbers live in data, not code: caps and thresholds are resolved from policy_sources/rule_registry.json, and a '
        'test fails if a policy number appears as a literal in domain code.',
        'Frameworks stay at the edges: the domain core imports no web, AI or orchestration framework.',
        'Identity is server-held: grade and role come from config/profiles.toml with the session; a client cannot '
        'supply them.',
        'Answers are evidence-bound: the model sees only retrieved passages, marked as data; Python validates every '
        'citation and overrides any number that disagrees with the registry.',
        'Capabilities are reported honestly: a missing model or provider returns a clear "capability unavailable" '
        'response, and evaluation counts such cases as blocked, never as passed.',
    ])

    # 3
    heading(document, '3. Technology stack and roles', 1)
    para(document, 'Status: "In use" means exercised by the running application; "Built" means implemented and tested '
                   'but not the active default; "Installed, not yet used" means pinned for a later milestone.')
    table(document, ['Layer', 'Technology', 'Version', 'Role in the application', 'Status'], [
        ('Runtime', 'Python (CPython)', '3.14.10', 'Language runtime for UI, API, domain core and evaluation', 'In use'),
        ('UI', 'Streamlit', '1.67.0', 'Web interface: navigation, forms, chat, data editor, uploads', 'In use'),
        ('UI', 'Inter, JetBrains Mono', 'Fontsource 5.3.0', 'Self-hosted typography (SIL OFL); no third-party font calls', 'In use'),
        ('API', 'FastAPI', '0.162.0', 'REST API, request validation, authentication dependencies', 'In use'),
        ('API', 'Uvicorn', '0.54.0', 'ASGI server; one worker owns the SQLite store', 'In use'),
        ('API', 'Pydantic', '2.14.3', 'Request schemas; extra fields forbidden so clients cannot inject grade or role', 'In use'),
        ('API', 'python-multipart', '0.0.33', 'Multipart parsing for receipt images and policy documents', 'In use'),
        ('API', 'Pillow', '13.0.0', 'Decodes and validates JPEG/PNG uploads before storage; generates logo assets', 'In use'),
        ('Domain', 'Python decimal (stdlib)', '3.14', 'Money arithmetic with ROUND_HALF_UP; registry-resolved caps', 'In use'),
        ('Retrieval', 'rank-bm25', '0.2.2', 'Keyword half of hybrid retrieval, with alias normalization and query expansion', 'In use'),
        ('Retrieval', 'LangChain core', '1.7.6', 'BaseLoader, Document, BaseRetriever, Embeddings and InMemoryVectorStore interfaces', 'In use'),
        ('Retrieval', 'langchain-text-splitters', '1.1.3', 'Chunks uploads: Markdown heading splitter, then recursive splitter (1800 chars, 200 overlap)', 'In use'),
        ('Retrieval', 'pypdf · docx2txt', '7.0.0 · 0.9', 'Text extraction for PDF (per page) and Word uploads inside LangChain loaders; no OCR', 'In use'),
        ('Retrieval', 'FastEmbed (BAAI/bge-small-en-v1.5)', '0.9.1', 'Local CPU embeddings, 384-d; stand-in until the hosted embedding API', 'In use (stand-in)'),
        ('Retrieval', 'OpenAI-compatible embeddings (httpx)', '0.28.1', 'Adapter for the hosted embedding endpoint; switch by config', 'Built (tested with mocks)'),
        ('Data', 'SQLite (sqlite3)', '3.51.0', 'Sessions, receipts, assessments and the policy library', 'In use'),
        ('AI', 'Claude Sonnet 5.5', 'claude-sonnet-5-5', 'Generates cited policy answers as structured JSON', 'In use'),
        ('AI', 'Claude Code CLI', '2.1.153', 'Default local model provider: print mode, tools disabled, no session saved', 'In use (local only)'),
        ('AI', 'Anthropic Python SDK', '2.6.0', 'Claude API provider for containers and production (refusal fallback on)', 'Built (tested with mocks)'),
        ('AI', 'OpenAI-compatible adapter (httpx)', '0.28.1', 'Provider for a future externally hosted model endpoint', 'Built (not exercised live)'),
        ('Config', 'python-dotenv', '1.2.4', 'Loads secrets from a local .env named by config/settings.toml', 'In use'),
        ('Orchestration', 'LangGraph, checkpoint-sqlite', '1.2.20 · 3.1.3', 'Planner, executor and critic graph with resumable state', 'Installed, not yet used (M6)'),
        ('Observability', 'LangSmith', '0.14.17', 'Tracing and evaluation experiments; local redacted traces used instead', 'Installed, not yet used'),
        ('Retrieval', 'Qdrant', '—', 'Persistent vector store option; not needed at this corpus size', 'Not used'),
        ('Quality', 'pytest', '9.2.0', '273 unit and integration tests', 'In use'),
        ('Quality', 'Evaluation driver (in-house)', '—', 'Runs the 120 golden cases through the real application', 'In use'),
        ('Packaging', 'Docker Engine, Compose', '29.1 · v2', 'UI and API containers on python:3.14.10-slim (digest-pinned)', 'In use'),
        ('Tooling', 'playwright-cli, python-docx', '0.1.14 · 1.2.0', 'UI screenshot verification and document generation (developer tools)', 'In use'),
    ], [2.0, 3.6, 2.4, 6.4, 2.6], status_column=4)

    # 4
    heading(document, '4. Key flows', 1)
    heading(document, '4.1 Answering a policy question', 2)
    figure(document, '02-policy-question-flow.png', 'Figure 2 — The policy-question pipeline. Steps 3 and 4 can answer or refuse without calling the model.')
    para(document, 'Each question costs at most one model call. Guards refuse requests for secrets, bookings or another '
                   "person's data before any model call. Questions about dates outside the policy window are answered "
                   'deterministically. Otherwise the top six passages are retrieved, the exact cap is resolved from the '
                   'registry, and Claude returns a structured answer that Python reconciles before display.')
    heading(document, '4.2 Checking a claim', 2)
    para(document, 'The employee enters expense lines and trip context on the Claims & Verification page. The API adds '
                   'the server-held grade and calls the domain core, which removes exclusions first, then applies the '
                   'per-night, per-journey and per-local-day caps from the registry, converts currencies at documented '
                   'rates, compares the claimed total with the trip budget, checks the submission deadline and derives '
                   'readiness by precedence. The UI shows a summary ledger, a breakdown bar and one rule-check card per '
                   'line with its policy citation. No model is involved.')
    heading(document, '4.3 Adding a policy document (administrator)', 2)
    para(document, 'An administrator uploads a PDF, Word (.docx), text or Markdown document (up to 10 MB), or pastes '
                   'text, with its authority, version, geography and effective dates. The API checks the role and '
                   'duplicates. A LangChain loader parses the file (pypdf page by page, docx2txt for Word); LangChain '
                   'text splitters chunk it at Markdown headings and then into sections of about 1,800 characters '
                   'with a 200-character overlap, keeping page and offset. The sections are stored in SQLite, a vector '
                   'is created for each new section before the response returns, and the hybrid index is rebuilt. The '
                   'page reports sections, pages and vectors created, with a preview. Scanned PDFs are rejected because '
                   'OCR is not permitted. Library documents never change calculation caps; conflicts are reported for '
                   'human review.')
    heading(document, '4.4 Hybrid retrieval', 2)
    para(document, 'Every question is searched twice over the same filtered pool (organization, service date, '
                   'geography): BM25 keyword search with alias normalization and query expansion, and vector similarity '
                   'search over embeddings of the same sections. Reciprocal rank fusion (c = 60) merges the two lists '
                   'and each passage records whether it matched by keyword, meaning or both. Document vectors are cached '
                   'in SQLite per model, so restarts reuse them and a model change re-embeds automatically. If the '
                   'embedding model is unavailable, retrieval falls back to keyword-only and answers disclose it. '
                   'Required-rule recall at six on the 15 development targets is 100 percent in both modes.')

    # 5
    heading(document, '5. Implemented use cases', 1)
    table(document, ['ID', 'Use case', 'Who', 'What the user can do', 'Main components', 'Verification'], [
        ('UC01', 'Policy question answering', 'Employee, manager',
         'Ask hotel, flight and local-transport questions; get a concise answer, the applicable cap, clarification or '
         'human-review notes, and expandable cited sources.',
         'Policy Assistant page, /chat, guards, retrieval, rule registry, Claude Sonnet 5.5',
         '30 of 31 policy golden cases pass automatic checks with the live model'),
        ('UC02a', 'Claim check (manual entry)', 'Employee, manager',
         'Enter expense lines and trip details; see claimed, eligible, over-cap and excluded amounts, budget status, '
         'readiness and per-line rule checks.',
         'Claims & Verification page, /claims/review, domain core',
         'All 41 deterministic golden cases pass; the specification worked example reproduces exactly'),
        ('UC02b', 'Receipt upload and management', 'Employee, manager',
         'Upload up to five JPEG/PNG receipts (10 MiB each), list them, delete one, or delete everything by ending '
         'the session.', 'Receipts page, /receipts, Pillow validation, private storage',
         'Golden cases GT117 and GT118 plus API tests for size, type, count and ownership'),
        ('UC04', 'Personal travel band', 'Employee, manager',
         'See their own caps on Home, the full table on Travel Band Limits, and the cap for a chosen city on the '
         'travel form.', '/policy/limits, rule registry', 'API tests for server-held grade and city resolution'),
        ('UC05', 'Policy library administration', 'Administrator',
         'Upload PDF, Word, text or Markdown policies that are parsed, chunked and embedded on upload; list and '
         'remove them; other users browse read-only.',
         'Policy Documents page, /admin/policies, /policy/library, retrieval index',
         'Tests for loaders, chunking, vector creation and cache, hybrid filters, role enforcement and re-indexing'),
        ('UC06', 'Sessions, identity and privacy', 'All users',
         'Sign in as a directory traveler; grade and role are fixed by the server. Requests for secrets, bookings '
         "or another person's records are refused; ending a session deletes its data.",
         'Sessions, guards, rate limit, error envelope', 'Golden cases GT113 and GT114 plus API tests'),
    ], [1.2, 2.6, 1.9, 4.6, 3.4, 3.3])

    # 6
    heading(document, '6. Not yet implemented', 1)
    table(document, ['Capability', 'Milestone', 'Current state'], [
        ('Reading receipt images (vision/OCR), field confirmation and stateful review', 'M4',
         'Upload, validation and storage work; extraction is not built'),
        ('Travel search with a fixture provider and a configurable external travel API', 'M5',
         'Search form and cap display work; the search endpoint reports "not built yet"'),
        ('LangGraph planner, executor and critic; checkpointed resume; scheduled retention cleanup', 'M6',
         'Not started; deletion on request already works'),
        ('Full golden evaluation with human review, latency and cost reporting', 'M7',
         '76 of 120 cases executed; human review pending'),
        ('AWS deployment with ALB, Cognito, ECR and gates DEP01–DEP08', 'M8', 'Designed; no AWS resources created'),
    ], [8.5, 1.8, 6.7])

    # 7
    heading(document, '7. Deployment', 1)
    figure(document, '03-deployment.png', 'Figure 3 — Deployment views: local workstation (in use), Docker Compose (built and verified) and AWS (planned).')
    bullets(document, [
        ('Local workstation.', 'The API runs on port 8000 and the UI on port 8501. The default model provider calls the '
                               'local Claude Code CLI with the user\'s existing sign-in.'),
        ('Docker Compose.', 'Both services run from one image built on a digest-pinned python:3.14.10-slim base, as a '
                            'non-root user, with health checks and a data volume. The image excludes golden answer keys '
                            'and .env. Containers use the Anthropic SDK or a hosted endpoint, because the Claude Code CLI '
                            'is not available inside them.'),
        ('AWS (planned).', 'An EC2 host running Compose behind an Application Load Balancer with Cognito sign-in, '
                           'encrypted storage, private S3 for receipts and Secrets Manager, gated by DEP01–DEP08.'),
    ])

    # 8
    heading(document, '8. Security, privacy and governance', 1)
    bullets(document, [
        'Secrets live only in a local .env referenced by name from config/settings.toml; they never enter images, '
        'logs, error bodies or the browser.',
        'Grade and role are server-held; Pydantic models forbid extra fields, so a client cannot claim a higher grade or '
        'an administrator role.',
        'Guards refuse secret, booking and cross-session requests before any model call; the assistant cannot book, pay, '
        'approve claims or grant exceptions.',
        'Errors use one envelope with a request ID; internal details are logged locally and redacted, and the UI hides '
        'tracebacks. All dynamic text rendered as HTML is escaped.',
        'Uploads are decoded and validated before storage and kept per session; ending a session deletes them.',
        'Golden-test answer keys never reach the application, the model or the retrieval index.',
        'Only synthetic data is used. Users must not enter real employee, patient or receipt data and should follow the '
        'organization\'s PHI guidance (go/claude-phi-guidelines).',
    ])

    # 9
    heading(document, '9. Quality and verification', 1)
    table(document, ['Check', 'Result'], [
        ('Automated tests (pytest)', '273 passing'),
        ('Golden cases executed', '76 of 120 (milestones M1–M3); the other 44 need M4–M6'),
        ('Golden automatic checks', '75 pass and await human review; 1 fails (GT028, held-out: retrieval misses P09)'),
        ('Live model run', '31 policy cases against Claude Sonnet 5.5; about 14 s and USD 0.05 per answer'),
        ('Package validation', 'validate_package.py passes: registry-driven arithmetic, file hashes, derived documents'),
        ('Rule registry review', 'Draft: automated cross-check matched 22 of 22 caps; second human reviewer pending (M0)'),
        ('Container build', 'Docker Compose built and smoke-tested; non-root; no answer keys or .env in the image'),
        ('UI verification', 'Every page rendered in a headless browser and reviewed; colours validated for contrast and '
                            'colour-blind separation'),
    ], [5.0, 12.0])

    # 10
    heading(document, '10. Configuration and extensibility', 1)
    bullets(document, [
        ('Switching the model.', 'Change provider, model_id, base_url and api_key_env in config/settings.toml and '
                                 'restart the API. Providers: claude_code, anthropic, openai_compatible.'),
        ('Connecting a travel API.', 'Set travel.provider = "http" with base_url and api_key_env (M5).'),
        ('Retrieval tuning.', 'top_k, keyword_candidates, vector_candidates, chunk size and overlap, and an optional '
                              'same-model rerank in the [retrieval] section.'),
        ('Switching embeddings.', 'Set [embeddings] provider = "openai_compatible" with base_url, model_id and '
                                  'api_key_env for the hosted endpoint, or "none" for keyword-only, and restart the API.'),
        ('People and roles.', 'Edit config/profiles.toml to add travelers, grades and administrators.'),
        ('Policy content.', 'Administrators add guidance through the Policy Documents page; caps change only through a '
                            'reviewed edit of policy_sources/rule_registry.json.'),
    ])

    # 11
    heading(document, '11. Known limitations', 1)
    bullets(document, [
        'Embeddings run on a local stand-in model until the hosted endpoint is supplied; the hosted adapter is tested '
        'only with mocks. One held-out case (GT028) missed a rule under keyword-only retrieval and is left untuned.',
        'Scanned PDFs without a text layer cannot be uploaded because OCR is not permitted.',
        'Receipt images are not read yet, and travel search does not return offers yet.',
        'The Claude Code provider is for local testing; production use needs an API key or hosted endpoint.',
        'Policy 1.1 expires on 31 December 2026; later demonstrations need a reviewed policy 1.2 or a fixed clock.',
        'Golden results await human review, and the rule registry awaits its second reviewer.',
    ])

    # Appendix A
    heading(document, 'Appendix A. API endpoints', 1)
    table(document, ['Method and path', 'Access', 'Purpose'], [
        ('GET /health', 'Public', 'Liveness; no dependency calls'),
        ('GET /ready', 'Public', 'Readiness of registry, store, model, travel and index'),
        ('GET /travelers', 'Public', 'Synthetic sign-in directory (names and roles, not grades)'),
        ('POST /sessions', 'Public', 'Start a session; returns a bearer token'),
        ('GET · DELETE /sessions/{id}', 'Session owner', 'Session summary; delete session and all its data'),
        ('POST /receipts · DELETE /receipts/{id}', 'Session owner', 'Upload validated images; delete one receipt'),
        ('POST /claims/review', 'Session', 'Assess a claim with the server-held grade'),
        ('POST /chat', 'Session', 'Ask a policy question (guards, retrieval, model, reconciliation)'),
        ('GET /policy/limits', 'Session', "The traveler's caps; optionally the cap for a category, country and city"),
        ('GET /policy/library · GET /policy/rules', 'Session · Public', 'Library listing; core policy sections'),
        ('POST · GET /admin/policies · DELETE /admin/policies/{id}', 'Administrator', 'Manage library documents'),
        ('POST /travel/search', 'Session', 'Reserved for M5; currently reports capability unavailable'),
    ], [6.2, 2.8, 8.0], mono_columns=(0,))

    # Appendix B
    heading(document, 'Appendix B. Revision history', 1)
    table(document, ['Version', 'Date', 'Author', 'Changes'], REVISIONS, [1.8, 3.0, 3.0, 9.2])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUT)
    return OUT


if __name__ == '__main__':
    print('wrote', build().relative_to(ROOT))
