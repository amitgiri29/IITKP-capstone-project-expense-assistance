"""Document loaders on the LangChain ``BaseLoader`` interface (langchain-core).

langchain-community, which used to ship these loaders, was archived in June 2026, so the
loaders live here on the maintained core interface and use pypdf and docx2txt directly.
"""
import io
import zipfile

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 200
MIN_TEXT_CHARS = 40
FILE_TYPES = {'.pdf': 'pdf', '.docx': 'docx', '.txt': 'text', '.md': 'markdown', '.markdown': 'markdown'}


class IngestError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class PdfLoader(BaseLoader):
    """One Document per page, with the page number in metadata. Needs a text layer (no OCR)."""

    def __init__(self, data, source):
        self.data, self.source = data, source

    def lazy_load(self):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(io.BytesIO(self.data))
            # Many published PDFs are encrypted with an EMPTY open password (permissions only): anyone can open them.
            # Only PDFs that really need a password to open are refused.
            if reader.is_encrypted and not reader.decrypt(''):
                raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'Password-protected PDFs are not supported.')
            pages = reader.pages
            if len(pages) > MAX_PAGES:
                raise IngestError('PAYLOAD_TOO_LARGE', 'PDFs are limited to %d pages.' % MAX_PAGES)
            for number, page in enumerate(pages, start=1):
                yield Document(page_content=page.extract_text() or '', metadata={'source': self.source, 'page': number})
        except IngestError:
            raise
        except (PdfReadError, ValueError, KeyError, TypeError) as exc:
            raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'The file is not a readable PDF.') from exc


class DocxLoader(BaseLoader):
    def __init__(self, data, source):
        self.data, self.source = data, source

    def lazy_load(self):
        import docx2txt
        try:
            text = docx2txt.process(io.BytesIO(self.data))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'The file is not a readable Word (.docx) document.') from exc
        yield Document(page_content=text or '', metadata={'source': self.source})


class TextLoader(BaseLoader):
    def __init__(self, data, source):
        self.data, self.source = data, source

    def lazy_load(self):
        try:
            text = self.data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'The document is not valid UTF-8 text.') from exc
        if '\x00' in text:
            raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'The document contains binary data.')
        yield Document(page_content=text, metadata={'source': self.source})


LOADERS = {'pdf': PdfLoader, 'docx': DocxLoader, 'text': TextLoader, 'markdown': TextLoader}


def file_type_for(filename):
    suffix = ('.' + filename.rsplit('.', 1)[-1].lower()) if filename and '.' in filename else ''
    if suffix not in FILE_TYPES:
        raise IngestError('UNSUPPORTED_MEDIA_TYPE', 'Upload a PDF, Word (.docx), text (.txt) or Markdown (.md) document.')
    return FILE_TYPES[suffix]


def load_upload(filename, data):
    """Return (file_type, documents) for an uploaded policy document, or raise IngestError."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError('PAYLOAD_TOO_LARGE', 'Policy documents are limited to %d bytes.' % MAX_UPLOAD_BYTES)
    file_type = file_type_for(filename)
    documents = LOADERS[file_type](data, filename).load()
    if sum(len(d.page_content.strip()) for d in documents) < MIN_TEXT_CHARS:
        if file_type == 'pdf':
            raise IngestError('VALIDATION_FAILED', 'No text could be extracted. Scanned PDFs need a text layer; OCR is '
                                                   'not supported.')
        raise IngestError('VALIDATION_FAILED', 'The document has no usable text.')
    return file_type, documents
