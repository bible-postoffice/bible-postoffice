"""
Export bible embeddings from the local ChromaDB collection into Supabase.

Required env vars:
  - SUPABASE_URL
  - SUPABASE_SERVICE_ROLE_KEY  (service role; use only in trusted/local envs)

Optional env vars:
  - CHROMA_PATH (default: ./vectordb_e5small)
  - CHROMA_COLLECTION (default: bible)
  - SUPABASE_TABLE (default: bible_embeddings)
  - SUPABASE_ON_CONFLICT (default: reference_norm)
  - CHROMA_FETCH_BATCH (default: 1000)    # rows pulled from Chroma at once
  - SUPABASE_UPSERT_BATCH (default: 500)  # rows upserted to Supabase at once
"""

import os
from typing import Iterable, List, Dict, Any
import re

import chromadb
from supabase import create_client

# Reuse the same reference helpers the app already depends on.
from app import normalize_reference, build_reference_label


SUPABASE_URL ="https://qptkclakcrnoochmmrej.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFwdGtjbGFrY3Jub29jaG1tcmVqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NjE5Mzc2MSwiZXhwIjoyMDgxNzY5NzYxfQ.f1VLYige9PGGZNLKgcm-hPoTH4jMT8i_sEnzjNfY_VQ"
CHROMA_PATH = os.environ.get("CHROMA_PATH", "./vectordb_e5small")
CHROMA_COLLECTION = os.environ.get("CHROMA_COLLECTION", "bible")
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "bible_embeddings")
SUPABASE_ON_CONFLICT = os.environ.get("SUPABASE_ON_CONFLICT", "reference_norm")

CHROMA_FETCH_BATCH = int(os.environ.get("CHROMA_FETCH_BATCH", "1000"))
SUPABASE_UPSERT_BATCH = int(os.environ.get("SUPABASE_UPSERT_BATCH", "500"))

NULL_CHARS = re.compile("\x00")


def sanitize_strings(obj: Any) -> Any:
    """Strip null characters from any strings inside the object."""
    if isinstance(obj, str):
        return NULL_CHARS.sub("", obj)
    if isinstance(obj, list):
        return [sanitize_strings(v) for v in obj]
    if isinstance(obj, dict):
        return {k: sanitize_strings(v) for k, v in obj.items()}
    return obj


def chunked(items: Iterable[Any], size: int) -> Iterable[List[Any]]:
    batch: List[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def iter_rows(collection) -> Iterable[Dict[str, Any]]:
    total = collection.count()
    offset = 0

    while offset < total:
        data = collection.get(
            include=["documents", "metadatas", "embeddings"],
            limit=CHROMA_FETCH_BATCH,
            offset=offset,
        )
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        embs = data.get("embeddings")
        # embeddings can come back as a numpy array; avoid truthiness check
        if embs is None:
            embs = []
        if not docs:
            break

        for doc, meta, emb in zip(docs, metas, embs):
            meta = meta or {}
            doc = sanitize_strings(doc)
            meta = sanitize_strings(meta)
            reference = meta.get("reference") or build_reference_label(meta, doc)
            reference_norm = normalize_reference(reference)
            # embeddings can be numpy arrays; convert to plain list for JSON
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            yield {
                "reference": reference,
                "reference_norm": reference_norm,
                "content": doc,
                "popularity": int(meta.get("popularity", 0) or 0),
                "embedding": emb,
                "metadata": meta,
            }

        offset += len(docs)


def main():
    print(f"Connecting to ChromaDB at {CHROMA_PATH} (collection: {CHROMA_COLLECTION})")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = chroma_client.get_collection(name=CHROMA_COLLECTION)
    total = collection.count()
    print(f" - documents found: {total}")

    print(f"Connecting to Supabase table '{SUPABASE_TABLE}'")
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    inserted = 0
    for batch in chunked(iter_rows(collection), SUPABASE_UPSERT_BATCH):
        # 같은 reference_norm이 배치 안에 중복되면 ON CONFLICT 에러가 나므로 배치 내 중복 제거
        deduped = {}
        for row in batch:
            key = row.get("reference_norm")
            deduped[key] = row

        deduped_rows = list(deduped.values())
        sb.table(SUPABASE_TABLE).upsert(
            deduped_rows,
            on_conflict=SUPABASE_ON_CONFLICT,
        ).execute()
        inserted += len(deduped_rows)
        print(f" inserted {inserted}/{total}")

    print("Done.")


if __name__ == "__main__":
    main()
