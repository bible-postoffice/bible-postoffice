# inspect_popularity.py
import chromadb

client = chromadb.PersistentClient(path="./vectordb2")
col = client.get_collection("bible")

data = col.get(include=["metadatas"], limit=20)

print("📋 샘플 20개 popularity 확인\n")
for i, m in enumerate(data["metadatas"], 1):
    print(f"{i:2d}. source={m.get('source')} | popularity={m.get('popularity')}")
    
# 전체 통계
all_data = col.get(include=["metadatas"])
scores = [m.get("popularity", 0) for m in all_data["metadatas"]]
print("\n총 개수:", len(scores))
print("고유 popularity 값들:", sorted(set(scores)))
print("50 이상 개수:", sum(1 for s in scores if s >= 50))
print("80 이상 개수:", sum(1 for s in scores if s >= 80))
