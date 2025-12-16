# rebuild_chroma.py
import chromadb
from sentence_transformers import SentenceTransformer

OLD_DB_PATH = "./vectordb2"
OLD_COLLECTION = "bible"

# ✅ 여기에서 모델/새 DB 경로만 바꿔가며 사용
NEW_MODEL_NAME = "intfloat/multilingual-e5-small"  # 또는 "intfloat/multilingual-e5-base"
NEW_DB_PATH = "./vectordb_e5small"               # base면 "./vectordb_e5base" 추천
NEW_COLLECTION = "bible"

BATCH = 512  # 메모리 부족하면 128~256으로 낮추기

def main():
    print("1) 기존 ChromaDB 로드")
    old_client = chromadb.PersistentClient(path=OLD_DB_PATH)
    old_col = old_client.get_collection(name=OLD_COLLECTION)
    total = old_col.count()
    print(f"   - old count: {total}")

    print("2) 새 임베딩 모델 로드:", NEW_MODEL_NAME)
    model = SentenceTransformer(NEW_MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"   - embedding dim: {dim}")

    print("3) 새 ChromaDB 생성:", NEW_DB_PATH)
    new_client = chromadb.PersistentClient(path=NEW_DB_PATH)

    # 이미 있으면 삭제 후 재생성 (안전)
    try:
        new_client.delete_collection(name=NEW_COLLECTION)
        print("   - 기존 NEW 컬렉션 삭제 완료")
    except Exception:
        pass

    new_col = new_client.create_collection(name=NEW_COLLECTION)
    print("   - NEW 컬렉션 생성 완료")

    print("4) 배치로 문서/메타 가져와서 재임베딩 후 저장")
    offset = 0
    inserted = 0

    while offset < total:
        got = old_col.get(
            include=["documents", "metadatas"],
            limit=BATCH,
            offset=offset
        )
        docs = got["documents"]
        metas = got["metadatas"]

        # 기존 ids가 필요하면 include=["ids", ...]로 가져오면 되지만,
        # 여기선 새로 id를 만들어도 검색엔 문제 없음 (메타데이터 기반 출력이면 OK).
        ids = [f"v2_{offset+i}" for i in range(len(docs))]

        # 임베딩 계산
        embeds = model.encode(
            docs,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True
        ).tolist()

        new_col.add(
            ids=ids,
            documents=docs,
            metadatas=metas,
            embeddings=embeds
        )

        inserted += len(docs)
        offset += len(docs)
        print(f"   - {inserted}/{total} 저장 완료")

    print("✅ 완료")
    print("   - new count:", new_col.count())
    print("   - new db path:", NEW_DB_PATH)

if __name__ == "__main__":
    main()
