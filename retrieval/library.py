"""Admin policy library ingestion: LangChain loaders parse the upload, LangChain splitters chunk it.

Library documents are searchable and citable. They never change calculation caps, which come
only from the reviewed rule registry (AC21).
"""
from retrieval.chunking import split_documents
from retrieval.corpus import library_documents
from retrieval.loaders import IngestError, load_upload

__all__ = ['IngestError', 'ingest', 'library_documents']


def ingest(filename, data, title, chunk_size, chunk_overlap):
    """Return (file_type, page_count, chunks) where chunks are dicts ready for the store."""
    file_type, documents = load_upload(filename, data)
    pieces = split_documents(documents, file_type, title, chunk_size, chunk_overlap)
    page_count = len(documents) if file_type == 'pdf' else None
    chunks = [{'section': p.metadata['section'], 'text': p.page_content, 'page': p.metadata.get('page'),
               'start_index': p.metadata.get('start_index')} for p in pieces]
    return file_type, page_count, chunks
