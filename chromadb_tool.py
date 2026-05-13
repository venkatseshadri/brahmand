"""
ChromaDB Tool — Custom CrewAI Tool for semantic memory queries.

Wraps chromadb.PersistentClient with:
- Metadata filtering (date ranges, strategy types, tickers, failure modes)
- SentenceTransformer embeddings (all-MiniLM-L6-v2, free, config-driven)
- ResearchNotes ingestion + similarity search

Used exclusively by the Post-Mortem Agent.
"""

import json
from pathlib import Path
from typing import Type, Optional

import chromadb
from chromadb.utils import embedding_functions
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from persistence import DB_DIR

CHROMA_DIR = DB_DIR / "chroma"
COLLECTION_NAME = "brahmand_notes"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

_client: Optional[chromadb.PersistentClient] = None
_collection = None


def _get_collection():
    """Lazy-init ChromaDB persistent client + collection."""
    global _client, _collection
    if _collection is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def store_research_note(
    observation: str,
    metadata: dict,
    note_id: str,
) -> str:
    """Store a research note in ChromaDB. Returns the note_id."""
    coll = _get_collection()
    coll.upsert(
        documents=[observation],
        metadatas=[metadata],
        ids=[note_id],
    )
    return note_id


def query_similar_notes(
    query_text: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """Query ChromaDB for semantically similar research notes."""
    coll = _get_collection()
    results = coll.query(
        query_texts=[query_text],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    notes = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            notes.append(
                {
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i]
                    if results["documents"]
                    else "",
                    "metadata": results["metadatas"][0][i]
                    if results["metadatas"]
                    else {},
                    "distance": results["distances"][0][i]
                    if results["distances"]
                    else 0,
                }
            )
    return notes


def get_collection_stats() -> dict:
    """Return collection size for audit/health check."""
    coll = _get_collection()
    return {"count": coll.count(), "name": COLLECTION_NAME}


# ── CrewAI Tool ──────────────────────────────────────────────────────────


class QueryChromaDBInput(BaseModel):
    query: str = Field(
        ...,
        description="Natural language query to find similar past research notes.",
    )
    n_results: int = Field(
        default=5,
        description="How many similar notes to return (max 20).",
    )
    strategy: str = Field(
        default="",
        description="Filter by strategy type (e.g., IRON_BUTTERFLY).",
    )
    min_date: int = Field(
        default=0,
        description="Filter: minimum context_date as YYYYMMDD integer.",
    )
    max_date: int = Field(
        default=0,
        description="Filter: maximum context_date as YYYYMMDD integer.",
    )


class QueryChromaDBTool(BaseTool):
    name: str = "query_chromadb"
    description: str = (
        "Search the semantic memory (ChromaDB) for similar past trading "
        "observations, failure patterns, and improvement notes. "
        "Use this during Post-Mortem to find what happened on similar past days. "
        "Filter by strategy (IRON_BUTTERFLY), date range (min_date/max_date as "
        "YYYYMMDD integers). Returns ranked similar notes with distance scores."
    )
    args_schema: Type[BaseModel] = QueryChromaDBInput

    def _run(
        self,
        query: str,
        n_results: int = 5,
        strategy: str = "",
        min_date: int = 0,
        max_date: int = 0,
    ) -> str:
        where = {}
        if strategy:
            where["strategy"] = strategy
        if min_date > 0 and max_date > 0:
            where["$and"] = [
                {"context_date": {"$gte": min_date}},
                {"context_date": {"$lte": max_date}},
            ]
        elif min_date > 0:
            where["context_date"] = {"$gte": min_date}

        notes = query_similar_notes(
            query_text=query,
            n_results=min(n_results, 20),
            where=where if where else None,
        )
        return json.dumps(notes, indent=2, default=str)


class StoreResearchNoteInput(BaseModel):
    observation: str = Field(
        ...,
        description="The research observation to store in ChromaDB.",
    )
    source: str = Field(
        default="new_insight",
        description="Source: new_insight, sl_breach, pnl_event, chromadb_query.",
    )
    context_date: int = Field(
        ...,
        description="Date as YYYYMMDD integer for filtering.",
    )
    strategy: str = Field(
        default="IRON_BUTTERFLY",
        description="Strategy type for metadata filtering.",
    )
    ticker: str = Field(default="NIFTY", description="Underlying ticker.")


class StoreResearchNoteTool(BaseTool):
    name: str = "store_chromadb_note"
    description: str = (
        "Store a research observation in ChromaDB semantic memory. "
        "Called by the Post-Mortem Agent after analyzing today's trades. "
        "Each note gets embedded and becomes searchable by meaning. "
        "Include context_date (YYYYMMDD integer) for date filtering."
    )
    args_schema: Type[BaseModel] = StoreResearchNoteInput

    def _run(
        self,
        observation: str,
        source: str = "new_insight",
        context_date: int = 0,
        strategy: str = "IRON_BUTTERFLY",
        ticker: str = "NIFTY",
    ) -> str:
        coll = _get_collection()
        note_id = f"note-{context_date}-{source}-{coll.count() + 1}"
        new_id = store_research_note(
            observation=observation,
            metadata={
                "source": source,
                "context_date": context_date,
                "strategy": strategy,
                "ticker": ticker,
            },
            note_id=note_id,
        )
        return json.dumps(
            {"status": "STORED", "id": new_id, "observation": observation[:100]}
        )
