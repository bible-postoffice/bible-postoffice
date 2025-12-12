# update_popularity.py (실제 업데이트 버전)
import chromadb
from popular_verses import get_popularity_score, extract_chapter_verse

client = chromadb.PersistentClient(path="./vectordb2")
col = client.get_collection("bible")

data = col.get(include=["documents", "metadatas"])
ids = data["ids"]
metas = data["metadatas"]
docs = data["documents"]

print("📊 총 구절 수:", len(ids))
high = 0

for i, (id_, m, doc) in enumerate(zip(ids, metas, docs), 1):
    book_name = m.get("source", "")
    score = get_popularity_score(book_name, doc)
    m["popularity"] = score
    col.update(ids=[id_], metadatas=[m])

    if score >= 50:
        high += 1
        if high <= 10:  # 처음 10개만 찍어보기
            cv = extract_chapter_verse(doc)
            print(f"⭐ [{book_name} {cv}] -> {score}")

    if i % 1000 == 0:
        print(f"{i}/{len(ids)} 완료")

print("\n✅ 완료")
print("50 이상 개수:", high)
