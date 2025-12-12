import chromadb

# ChromaDB 클라이언트 초기화
chroma_client = chromadb.PersistentClient(path="./vectordb2")

# 모든 컬렉션 목록 확인
collections = chroma_client.list_collections()
print("사용 가능한 컬렉션들:")
for collection in collections:
    print(f"- 이름: {collection.name}")
    print(f"  ID: {collection.id}")
    print(f"  메타데이터: {collection.metadata}")
    print(f"  총 개수: {collection.count()}")
    print()
