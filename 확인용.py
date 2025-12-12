import chromadb
import numpy as np

chroma_client = chromadb.PersistentClient(path="./vectordb2")
collection = chroma_client.get_collection(name="bible")

print("컬렉션 메타데이터:", collection.metadata)
print(f"총 구절 수: {collection.count()}")

# 샘플 데이터 확인
sample = collection.get(limit=1, include=['embeddings', 'metadatas', 'documents'])

print("\n=== 샘플 데이터 ===")
if sample['documents']:
    print(f"문서: {sample['documents'][0][:100]}...")
    print(f"메타데이터: {sample['metadatas'][0]}")

# 임베딩 확인 (수정됨)
if sample.get('embeddings') is not None and len(sample['embeddings']) > 0:
    embedding = sample['embeddings'][0]
    if embedding is not None:
        if isinstance(embedding, (list, np.ndarray)):
            print(f"\n✅ 임베딩 차원: {len(embedding)}")
            print(f"   임베딩 타입: {type(embedding)}")
            print(f"   임베딩 샘플 (처음 5개): {embedding[:5]}")
        else:
            print(f"❌ 임베딩 타입 이상: {type(embedding)}")
    else:
        print("❌ 임베딩이 None입니다")
else:
    print("❌ 임베딩 데이터가 없습니다")
