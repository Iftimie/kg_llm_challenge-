"""Semantic transcript search backed by the persistent ChromaDB collection."""
import chromadb

from app import config

_COLLECTION = "transcripts"


def _get_collection():
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return client.get_or_create_collection(_COLLECTION)


def semantic_search(query, top_k=3) -> list:
    """Return the nearest transcript chunks as ``{id, distance, metadata, snippet}``."""
    n_results = min(max(int(top_k), 1), 10)
    collection = _get_collection()
    hits = collection.query(query_texts=[query], n_results=n_results)

    results = []
    for doc_id, dist, meta, doc in zip(
        hits["ids"][0],
        hits["distances"][0],
        hits["metadatas"][0],
        hits["documents"][0],
    ):
        results.append(
            {
                "id": doc_id,
                "distance": dist,
                "metadata": meta,
                "snippet": (doc or "")[:200],
            }
        )
    return results
