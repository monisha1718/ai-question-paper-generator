"""
Retrieval-Augmented Generation (RAG) pipeline.

Retrieves relevant document chunks from the FAISS vector store and feeds
them alongside the user query to the Groq LLM.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain.chains import RetrievalQA
from langchain_groq import ChatGroq

from .pdf_processor import load_vectorstore

logger = logging.getLogger(__name__)

# Default LLM parameters
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TEMPERATURE = 0.3


def get_llm(model: str = DEFAULT_MODEL, temperature: float = DEFAULT_TEMPERATURE) -> ChatGroq:
    """Return a ChatGroq instance."""
    return ChatGroq(model=model, temperature=temperature)


def retrieve_relevant_chunks(subject: str, query: str, k: int = 8) -> list[str]:
    """
    Retrieve the top-k most relevant text chunks for a query from the
    subject's vector store.  Returns a list of plain-text strings.
    """
    vectorstore = load_vectorstore(subject)
    if vectorstore is None:
        logger.warning("No vector store found for subject '%s'", subject)
        return []

    docs = vectorstore.similarity_search(query, k=k)
    return [doc.page_content for doc in docs]


def query_rag(subject: str, query: str, k: int = 8) -> str:
    """
    End-to-end RAG: retrieve context from the vector store and generate an
    answer via the LLM.  Returns the LLM's response text.
    """
    vectorstore = load_vectorstore(subject)
    if vectorstore is None:
        return (
            "No study material has been uploaded for this subject yet. "
            "Please upload a PDF first."
        )

    llm = get_llm()
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=False,
    )

    result = qa_chain.invoke({"query": query})
    return result["result"]


def generate_with_context(context_chunks: list[str], prompt: str) -> str:
    """
    Given pre-fetched context chunks and an explicit prompt, call the LLM
    and return its response.  This is used by the question generator where
    we need fine-grained control over the prompt.
    """
    llm = get_llm(temperature=0.5)
    context = "\n\n---\n\n".join(context_chunks)

    full_prompt = (
        f"You are an expert academic question paper setter.\n\n"
        f"Use ONLY the following study material to generate questions. "
        f"Do not use any external knowledge.\n\n"
        f"### Study Material ###\n{context}\n\n"
        f"### Instructions ###\n{prompt}"
    )

    response = llm.invoke(full_prompt)
    return response.content
