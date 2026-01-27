import os
import chromadb
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
import config

# 1. Supabase 초기화
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
supabase_vec: Client = None
if config.SUPABASE_VEC_URL and config.SUPABASE_VEC_KEY:
    supabase_vec = create_client(config.SUPABASE_VEC_URL, config.SUPABASE_VEC_KEY)

# 2. 임베딩 모델 초기화
print("🔄 임베딩 모델 로딩 중...")
embedding_model = SentenceTransformer('intfloat/multilingual-e5-small')
print(f"✅ 임베딩 모델 로드 완료")

# 3. ChromaDB 초기화
IS_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
USE_CHROMA = str(os.environ.get("USE_CHROMA", "1")).lower() not in ("0", "false", "no")

bible_collection = None
if not IS_CLOUD_RUN and USE_CHROMA:
    try:
        chroma_client = chromadb.PersistentClient(path="./vectordb_e5small")
        bible_collection = chroma_client.get_collection(name="bible")
        print(f"✅ ChromaDB 컬렉션 로드 성공: {bible_collection.count()} 구절")
    except Exception as e:
        print(f"❌ ChromaDB 에러: {e}")
else:
    print("ℹ️ ChromaDB 초기화 건너뜀 (Cloud Run/Supabase 모드)")

# 공통 헤더 함수 (기존 app.py에서 가져옴)
def get_supabase_headers():
    return {
        "apikey": config.SUPABASE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }