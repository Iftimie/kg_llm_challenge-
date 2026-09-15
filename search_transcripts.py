"""Search transcripts by meaning. Run: python search_transcripts.py "pricing negotiation" """
import sys

import chromadb

query = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()

client = chromadb.PersistentClient(path="chroma_db")
collection = client.get_or_create_collection("transcripts")

hits = collection.query(query_texts=[query], n_results=3)
for doc_id, dist, meta, doc in zip(hits["ids"][0], hits["distances"][0],
                                   hits["metadatas"][0], hits["documents"][0]):
    print(f"{doc_id}  distance={dist:.4f}  {meta}")
    print(f"  {doc[:200]}...")
    print()
