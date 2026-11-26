"""LangChain ingestion (loaders + splitters), cached embeddings and hybrid retrieval (offline fakes only)."""
import io
import zipfile

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from adapters.embeddings import CachedEmbeddings
from core.context import refresh_library
from retrieval.chunking import split_documents
from retrieval.loaders import IngestError, MAX_PAGES, load_upload
from retrieval.service import PolicyRetriever

ORG = {'organization_id': 'demo-company'}
TEXT = ('Visa fees for approved business travel are reimbursed in full when the travel desk files the application. '
        'Keep the embassy receipt with the claim.')
FIELDS = {'title': 'Visa handling note', 'effective_from': '2026-01-01', 'effective_to': '2026-12-31',
          'authority': 'guidance', 'geography': 'international', 'version': '1.0'}


def make_pdf(pages):
    """A minimal valid PDF with one Helvetica text line per page, built by hand (no PDF writer needed)."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = 'BT /F1 11 Tf 40 760 Td (%s) Tj ET' % text
        objects.append('<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream))
        objects.append('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R '
                       '/Resources << /Font << /F1 3 0 R >> >> >>' % len(objects))
        kids.append('%d 0 R' % len(objects))
    objects[1] = '<< /Type /Pages /Kids [%s] /Count %d >>' % (' '.join(kids), len(kids))
    out, offsets = io.BytesIO(), []
    out.write(b'%PDF-1.4\n')
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(('%d 0 obj\n%s\nendobj\n' % (number, body)).encode('latin-1'))
    xref = out.tell()
    out.write(('xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)).encode())
    for offset in offsets:
        out.write(('%010d 00000 n \n' % offset).encode())
    out.write(('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)).encode())
    return out.getvalue()


def make_docx(paragraphs):
    body = ''.join('<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % p for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                         'package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/'
                         'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.'
                         'org/wordprocessingml/2006/main"><w:body>%s</w:body></w:document>' % body)
    return buffer.getvalue()


def blank_pdf(count, password=None):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(612, 792)
    if password:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ---- loaders ------------------------------------------------------------------------------------------------
def test_pdf_with_an_empty_open_password_is_read():
    """Permissions-only encryption (empty user password) opens for anyone; a real open password is still refused."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf([TEXT]))))
    writer.encrypt(user_password='', owner_password='synthetic-owner-password')
    buffer = io.BytesIO()
    writer.write(buffer)
    file_type, documents = load_upload('published.pdf', buffer.getvalue())
    assert file_type == 'pdf' and 'Visa fees' in documents[0].page_content


def test_pdf_loader_yields_one_document_per_page():
    file_type, documents = load_upload('note.pdf', make_pdf(['Visa fees are reimbursed for business travel.',
                                                             'Embassy receipts must be attached to the claim.']))
    assert file_type == 'pdf'
    assert [d.metadata['page'] for d in documents] == [1, 2]
    assert 'Embassy receipts' in documents[1].page_content


def test_docx_loader_reads_paragraphs():
    file_type, documents = load_upload('note.docx', make_docx(['Visa handling', TEXT]))
    assert file_type == 'docx' and 'embassy receipt' in documents[0].page_content


def test_text_and_markdown_loaders():
    assert load_upload('note.txt', TEXT.encode())[0] == 'text'
    assert load_upload('note.MD', ('# Visa\n\n' + TEXT).encode())[0] == 'markdown'


@pytest.mark.parametrize('name,data,code', [
    ('scan.pdf', blank_pdf(1), 'VALIDATION_FAILED'),
    ('locked.pdf', blank_pdf(1, password='synthetic-test-password'), 'UNSUPPORTED_MEDIA_TYPE'),
    ('huge.pdf', blank_pdf(MAX_PAGES + 1), 'PAYLOAD_TOO_LARGE'),
    ('broken.pdf', b'%PDF-1.4 not really a pdf', 'UNSUPPORTED_MEDIA_TYPE'),
    ('broken.docx', b'not a zip archive', 'UNSUPPORTED_MEDIA_TYPE'),
    ('sheet.xlsx', b'anything', 'UNSUPPORTED_MEDIA_TYPE'),
    ('binary.txt', b'abc\x00def' * 20, 'UNSUPPORTED_MEDIA_TYPE'),
    ('short.txt', b'too short', 'VALIDATION_FAILED'),
])
def test_loader_rejections(name, data, code):
    with pytest.raises(IngestError) as caught:
        load_upload(name, data)
    assert caught.value.code == code


# ---- chunking -----------------------------------------------------------------------------------------------
def test_chunks_keep_page_heading_and_start_index():
    _, pages = load_upload('note.pdf', make_pdf(['Visa fees are reimbursed for business travel.',
                                                 'Embassy receipts must be attached to the claim.']))
    chunks = split_documents(pages, 'pdf', 'Visa note')
    assert [(c.metadata['section'], c.metadata['page'], c.metadata['start_index']) for c in chunks] == [
        ('Page 1', 1, 0), ('Page 2', 2, 0)]
    _, docs = load_upload('n.md', ('# Visa\n\nIntro text for visas.\n\n## Fees\n\n' + TEXT).encode())
    assert [c.metadata['section'] for c in split_documents(docs, 'markdown', 'Visa')] == ['Visa', 'Visa › Fees']


def test_long_text_is_split_with_overlap():
    words = ' '.join('w%d' % i for i in range(1200))
    _, docs = load_upload('long.txt', words.encode())
    chunks = split_documents(docs, 'text', 'Long', chunk_size=1000, chunk_overlap=200)
    assert len(chunks) > 1 and all(len(c.page_content) <= 1000 for c in chunks)
    first_tail = chunks[0].page_content.split()[-1]
    assert first_tail in chunks[1].page_content.split()  # overlap carries context across the boundary


# ---- cached embeddings and hybrid retrieval ---------------------------------------------------------------
@pytest.fixture
def hybrid(context):
    embeddings = CachedEmbeddings(DeterministicFakeEmbedding(size=32), context.store, 'fake:deterministic-32',
                                  context.events)
    context.retriever = PolicyRetriever(events=context.events, embeddings=embeddings)
    refresh_library(context)
    return context


def test_core_policy_is_embedded_once_and_cached(hybrid, context):
    retriever = hybrid.retriever
    assert retriever.mode == 'hybrid' and retriever.vector_count() == len(retriever.core)
    assert context.store.count_vectors('fake:deterministic-32') == len(retriever.core)
    again = CachedEmbeddings(DeterministicFakeEmbedding(size=32), context.store, 'fake:deterministic-32')
    PolicyRetriever(embeddings=again)
    assert again.created == 0  # every core vector came from the SQLite cache


def test_hybrid_results_carry_match_source_and_respect_filters(hybrid):
    hits = hybrid.retriever.retrieve('hotel cap per night', ORG)
    assert hits and all(hit['match'] in ('keyword', 'semantic', 'keyword+semantic') for hit in hits)
    assert any('semantic' in hit['match'] for hit in hits)
    assert hybrid.retriever.retrieve('hotel cap per night', {'organization_id': 'other-company'}) == []


def test_embedding_failure_falls_back_to_keyword_search(context):
    class Broken(DeterministicFakeEmbedding):
        def embed_documents(self, texts):
            raise RuntimeError('model download blocked')

    retriever = PolicyRetriever(embeddings=Broken(size=8))
    assert retriever.mode == 'bm25_only' and 'download blocked' in retriever.vector_error
    assert retriever.retrieve('hotel cap per night', ORG)[0]['match'] == 'keyword'


@pytest.fixture
def admin(client):
    body = client.post('/sessions', json={'traveler_id': 'admin-P'}).json()
    return {'Authorization': 'Bearer ' + body['token']}


@pytest.mark.parametrize('name,data', [('visa.pdf', make_pdf([TEXT[:90], TEXT[90:]])),
                                       ('visa.docx', make_docx(['Visa handling', TEXT]))])
def test_upload_parses_chunks_and_creates_vectors_immediately(hybrid, client, admin, name, data):
    before = hybrid.retriever.vector_count()
    response = client.post('/admin/policies', headers=admin, data=FIELDS, files={'file': (name, data)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['file_type'] == name.rsplit('.', 1)[1]
    assert body['vectors_created'] == body['chunk_count'] > 0
    assert body['retrieval_mode'] == 'hybrid' and body['embedding_model'] == 'fake:deterministic-32'
    assert body['preview'][0]['position'] == 1 and 'Searchable now' in body['message']
    assert hybrid.retriever.vector_count() == before + body['chunk_count']
    if name.endswith('.pdf'):
        assert body['page_count'] == 2 and body['preview'][0]['page'] == 1
    hits = hybrid.retriever.retrieve('embassy receipt visa fees', ORG)
    assert hits[0]['document_id'] == body['document_id']
    assert client.delete('/admin/policies/' + body['document_id'], headers=admin).status_code == 204
    assert hybrid.retriever.vector_count() == before


def test_upload_without_embeddings_is_keyword_only(client, admin):
    response = client.post('/admin/policies', headers=admin, data=FIELDS,
                           files={'file': ('visa.txt', TEXT.encode())})
    body = response.json()
    assert response.status_code == 201 and body['vectors_created'] == 0 and body['retrieval_mode'] == 'bm25_only'
    assert 'embeddings are not configured' in body['message']


def test_upload_rejections_map_to_error_envelope(client, admin):
    scanned = client.post('/admin/policies', headers=admin, data=FIELDS, files={'file': ('scan.pdf', blank_pdf(1))})
    assert scanned.status_code == 422 and 'OCR' in scanned.text
    wrong = client.post('/admin/policies', headers=admin, data=FIELDS, files={'file': ('sheet.xlsx', b'abc' * 30)})
    assert wrong.status_code == 415


def test_ready_reports_embedding_component(client):
    components = client.get('/ready').json()['components']
    assert components['embeddings']['retrieval_mode'] == 'bm25_only'
    assert components['policy_index']['sections'] >= 20
