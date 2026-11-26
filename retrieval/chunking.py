"""Chunking with LangChain text splitters (langchain-text-splitters)."""
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from retrieval.loaders import IngestError

MAX_CHUNKS = 300
HEADERS = [('#', 'h1'), ('##', 'h2'), ('###', 'h3')]


def split_documents(documents, file_type, title, chunk_size=1800, chunk_overlap=200):
    """Markdown is split at headings first; every document is then split recursively with overlap.

    Each chunk keeps a readable section label (heading path, page number or document title).
    """
    if file_type == 'markdown':
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS, strip_headers=False)
        sections = []
        for document in documents:
            for part in header_splitter.split_text(document.page_content):
                part.metadata = {**document.metadata, **part.metadata}
                sections.append(part)
    else:
        sections = list(documents)
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True)
    chunks = [c for c in splitter.split_documents(sections) if c.page_content.strip()]
    if not chunks:
        raise IngestError('VALIDATION_FAILED', 'The document has no usable text.')
    if len(chunks) > MAX_CHUNKS:
        raise IngestError('PAYLOAD_TOO_LARGE', 'The document splits into more than %d sections.' % MAX_CHUNKS)
    for chunk in chunks:
        headings = [chunk.metadata[h] for _, h in HEADERS if chunk.metadata.get(h)]
        if headings:
            label = ' › '.join(headings)
        elif chunk.metadata.get('page'):
            label = 'Page %d' % chunk.metadata['page']
        else:
            label = title
        chunk.metadata['section'] = label
    return chunks
