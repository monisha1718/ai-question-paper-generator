"""
PDF processing: extract text from uploaded PDFs, chunk the text, generate
embeddings, and persist them in a FAISS vector store per-subject.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

# Directory where FAISS indexes are saved (one per subject)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTORSTORE_DIR = os.path.join(BASE_DIR, "vectorstores")
os.makedirs(VECTORSTORE_DIR, exist_ok=True)


def _get_embeddings() -> HuggingFaceEmbeddings:
    """Return a HuggingFace embedding model instance (runs locally, no API key needed)."""
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


def _safe_subject_name(subject: str) -> str:
    """Sanitize a subject name for use as a directory name."""
    return subject.strip().lower().replace(" ", "_")


def extract_text_from_pdf(pdf_path: str) -> list:
    """Load a PDF and return a list of LangChain Document objects."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    logger.info("Extracted %d pages from %s", len(documents), pdf_path)
    return documents


def chunk_documents(documents: list, chunk_size: int = 1000, chunk_overlap: int = 200) -> list:
    """Split documents into smaller chunks for embedding."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    chunks = splitter.split_documents(documents)
    logger.info("Split into %d chunks", len(chunks))
    return chunks


def store_embeddings(chunks: list, subject: str) -> FAISS:
    """
    Create or update a FAISS vector store for a given subject.

    If a vector store already exists for the subject, the new chunks are
    merged into it; otherwise a fresh store is created.
    """
    embeddings = _get_embeddings()
    safe_name = _safe_subject_name(subject)
    store_path = os.path.join(VECTORSTORE_DIR, safe_name)

    new_store = FAISS.from_documents(chunks, embeddings)

    if os.path.exists(store_path):
        existing_store = FAISS.load_local(
            store_path, embeddings, allow_dangerous_deserialization=True
        )
        existing_store.merge_from(new_store)
        existing_store.save_local(store_path)
        logger.info("Merged new chunks into existing vector store for '%s'", subject)
        return existing_store
    else:
        new_store.save_local(store_path)
        logger.info("Created new vector store for '%s'", subject)
        return new_store


def load_vectorstore(subject: str) -> FAISS | None:
    """Load an existing FAISS vector store for a subject, or return None."""
    safe_name = _safe_subject_name(subject)
    store_path = os.path.join(VECTORSTORE_DIR, safe_name)
    if not os.path.exists(store_path):
        return None
    embeddings = _get_embeddings()
    return FAISS.load_local(store_path, embeddings, allow_dangerous_deserialization=True)


def process_pdf(pdf_path: str, subject: str) -> int:
    """
    Full pipeline: extract → chunk → embed → store.

    Returns the number of chunks created.
    """
    documents = extract_text_from_pdf(pdf_path)
    chunks = chunk_documents(documents)
    store_embeddings(chunks, subject)
    return len(chunks)
