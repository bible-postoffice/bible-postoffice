# app.py
from flask import Flask, render_template, request, jsonify
import chromadb
import uuid
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sentence_transformers import SentenceTransformer
import os
import re
import requests
from dotenv import load_dotenv

from popular_verses import (
    get_popularity_score,
    extract_chapter_verse,
    normalize_korean,
    BOOK_NAME_MAP,
)  # ⭐ 추가

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

app = Flask(__name__)

# 1024차원 임베딩 모델 로드
print("🔄 임베딩 모델 로딩 중...")
embedding_model = SentenceTransformer('intfloat/multilingual-e5-small')
print(f"✅ 임베딩 모델 로드 완료: {embedding_model.get_sentence_embedding_dimension()}차원")

# ChromaDB 초기화
try:
    chroma_client = chromadb.PersistentClient(path="./vectordb_e5small")
    bible_collection = chroma_client.get_collection(name="bible")
    print(f"✅ 컬렉션 로드 성공: {bible_collection.name}")
    print(f"   총 구절 수: {bible_collection.count()}")
except Exception as e:
    print(f"❌ ChromaDB 에러: {e}")
    bible_collection = None

# 검색 주제를 문맥/대표 구절과 함께 확장하기 위한 힌트 세트
DEFAULT_CONTEXT_DESCRIPTION = (
    '위로와 격려, 하나님의 신실하심, 회복과 소망, 두려움을 이기는 믿음, 사랑과 용기'
)

THEME_CONTEXT_RULES = [
    {
        "tokens": ['취업', '진로', '직장', '커리어', '회사'],
        "description": '취업과 진로, 장래의 길, 하나님의 공급과 인도, 두려움 대신 담대함',
        "curated_references": [
            "잠언 16:3",
            "잠언 3:5-6",
            "예레미야 29:11",
            "시편 37:23",
            "빌립보서 4:13",
        ],
    },
    {
        "tokens": ['시험', '공부', '학업', '입시'],
        "description": '지혜와 인내, 성실하게 준비하는 마음, 하나님께 맡기는 믿음',
        "curated_references": [
            "야고보서 1:5",
            "고린도전서 10:13",
            "빌립보서 4:6",
            "빌립보서 4:13",
            "잠언 2:6",
        ],
    },
    {
        "tokens": ['위로', '슬픔', '눈물', '상실', '아픔', '고통'],
        "description": '위로와 회복, 함께하시는 하나님, 눈물을 닦아주시는 사랑',
        "curated_references": [
            "시편 119:50",
            "이사야 41:10",
            "시편 34:18",
            "마태복음 11:28",
            "시편 147:3",
        ],
    },
    {
        "tokens": ['소망', '희망', '미래', '장래'],
        "description": '소망과 미래에 대한 약속, 하나님이 예비하신 계획을 신뢰함',
        "curated_references": [
            "예레미야 29:11",
            "고린도전서 13:13",
            "로마서 15:13",
            "히브리서 11:1",
            "시편 71:14",
        ],
    },
    {
        "tokens": ['두려움', '걱정', '근심', '불안'],
        "description": '두려움을 이기는 믿음, 평안, 담대함, 염려를 맡김',
        "curated_references": [
            "이사야 41:10",
            "빌립보서 4:6-7",
            "마태복음 6:34",
            "시편 56:3",
            "디모데후서 1:7",
        ],
    },
    {
        "tokens": ['감사', '기쁨', '찬양'],
        "description": '감사와 찬양, 기쁨과 즐거움, 하나님의 선하심',
        "curated_references": [
            "시편 100:4",
            "데살로니가전서 5:18",
            "시편 16:11",
            "빌립보서 4:4",
            "느헤미야 8:10",
        ],
    },
    {
        "tokens": ['용서', '죄책감', '회개'],
        "description": '용서와 회개, 새 마음, 은혜로 다시 시작함',
        "curated_references": [
            "요한일서 1:9",
            "누가복음 17:3-4",
            "에베소서 4:32",
            "시편 103:12",
            "미가 7:19",
        ],
    },
    {
        "tokens": ['사랑', '연애', '결혼', '부부', '가정', '부모', '자녀', '가족'],
        "description": '사랑과 연합, 가정과 관계 회복, 서로를 세워 줌',
        "curated_references": [
            "고린도전서 13:4-7",
            "요한일서 4:8",
            "에베소서 5:25",
            "잠언 17:17",
            "골로새서 3:13",
        ],
    },
    {
        "tokens": ['우정', '공동체', '교회', '형제'],
        "description": '공동체와 우정, 서로를 격려하고 세워 주는 관계',
        "curated_references": [
            "요한복음 15:13",
            "잠언 17:17",
            "잠언 27:17",
            "요한복음 17:21",
            "히브리서 10:24-25"
        ],
    },
    {
        "tokens": ['사명', '헌신', '섬김', '순종'],
        "description": '사명과 순종, 헌신과 사랑으로 섬기는 삶',
        "curated_references": [
            "요한복음 14:15",
            "로마서 12:1",
            "신명기 10:12",
            "마태복음 16:24",
            "갈라디아서 2:20"
        ],
    },
    {
        "tokens": ['건강', '질병', '치유', '회복'],
        "description": '치유와 회복, 강건함, 약한 자를 세우시는 하나님',
        "curated_references": [
            "야고보서 5:15",
            "출애굽기 15:26",
            "이사야 53:5",
            "마가복음 5:34",
            "시편 41:3"
        ],
    },
    {
        "tokens": ['재정', '돈', '필요', '궁핍', '가난'],
        "description": '필요를 채우시는 하나님, 공급과 만족, 나눔과 신뢰',
        "curated_references": [
            "빌립보서 4:19",
            "마태복음 6:33",
            "히브리서 13:5",
            "잠언 30:8",
            "마태복음 6:26",
        ],
    },
    {
        "tokens": ['갈등', '분노', '싸움'],
        "description": '화해와 용서, 평화, 사랑으로 문제를 해결함',
        "curated_references": [
            "야고보서 1:19-20",
            "잠언 15:1",
            "에베소서 4:26",
            "마태복음 18:15",
            "잠언 16:32"
        ],
    },
    {
        "tokens": ['평안', '쉼', '안식', '샬롬'],
        "description": '평안과 안식, 폭풍 가운데도 지키시는 하나님',
        "curated_references": [
            "요한복음 14:27",
            "마태복음 11:28",
            "시편 4:8",
            "빌립보서 4:7",
            "요한복음 16:33"
        ],
    },
]

REFERENCE_SPLIT_PATTERN = re.compile(r'^(.*?)(\d+:\d.*)$')


def _collect_all_curated_references():
    seen = set()
    refs = []
    for rule in THEME_CONTEXT_RULES:
        for ref in rule.get("curated_references", []):
            if not ref:
                continue
            cleaned = normalize_korean(ref.strip())
            if cleaned not in seen:
                seen.add(cleaned)
                refs.append(cleaned)
    return refs


ALL_CURATED_REFERENCES = _collect_all_curated_references()
REFERENCE_INDEX = {}
REFERENCE_INDEX_LOADED = False


def canonical_book_name(book: str) -> str:
    book = normalize_korean(book or '').strip()
    if not book:
        return ''
    return BOOK_NAME_MAP.get(book, book)


def split_reference(reference: str):
    reference = normalize_korean(reference or '').strip()
    reference = reference.split('(')[0].strip()
    if not reference:
        return '', ''
    match = REFERENCE_SPLIT_PATTERN.match(reference)
    if match:
        book_raw = match.group(1).strip()
        remainder = match.group(2).strip()
    else:
        book_raw = reference
        remainder = ''
    book = canonical_book_name(book_raw)
    if remainder:
        remainder = remainder.strip()
        # 범위가 붙어 있으면 시작 절만 사용
        for sep in ['-', '–', '—', '~']:
            if sep in remainder:
                remainder = remainder.split(sep)[0].strip()
                break
    remainder = remainder.strip()
    return book, remainder


def normalize_reference(reference: str) -> str:
    """구절 표시 방식이 조금씩 달라도 비교가 가능하도록 정규화."""
    book, remainder = split_reference(reference)
    if book and remainder:
        base = f"{book} {remainder}"
    elif book:
        base = book
    else:
        base = remainder
    return base.replace(" ", "")


def build_reference_label(metadata: dict, document: str) -> str:
    """메타데이터와 본문에서 책 이름 + 장:절을 조합해 사람이 읽을 레퍼런스를 만든다."""
    reference_field = metadata.get("reference") or ""
    source_field = metadata.get("source") or ""
    ref_book, ref_numbers = split_reference(reference_field)
    source_book = canonical_book_name(source_field)
    book = ref_book or source_book
    chapter_verse = extract_chapter_verse(document or "") if document else None

    if not chapter_verse and ref_numbers:
        chapter_verse = ref_numbers

    if book and chapter_verse:
        return f"{book} {chapter_verse}"
    if book:
        return book
    if chapter_verse:
        return chapter_verse
    return "알 수 없는 구절"


def build_reference_index():
    """테마 대표 구절을 빠르게 가져올 수 있도록 메모리에 적재."""
    global REFERENCE_INDEX_LOADED
    if REFERENCE_INDEX_LOADED or not bible_collection or not ALL_CURATED_REFERENCES:
        REFERENCE_INDEX_LOADED = True
        return

    target_refs = {
        normalize_reference(ref): ref
        for ref in ALL_CURATED_REFERENCES
        if ref
    }
    target_refs.pop('', None)

    if not target_refs:
        REFERENCE_INDEX_LOADED = True
        return

    print("🔄 테마 대표 구절 인덱스 로딩 중...")
    try:
        data = bible_collection.get(include=["documents", "metadatas"])
    except Exception as e:
        print(f"⚠️ 대표 구절 인덱스 로딩 실패: {e}")
        return

    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    found = 0

    for doc, meta in zip(docs, metas):
        reference = build_reference_label(meta, doc)
        normalized = normalize_reference(reference)
        if normalized in target_refs and normalized not in REFERENCE_INDEX:
            REFERENCE_INDEX[normalized] = {
                "text": doc,
                "metadata": meta,
            }
            found += 1
            if found == len(target_refs):
                break

    REFERENCE_INDEX_LOADED = True
    print(f"✅ 대표 구절 인덱스 준비 완료: {len(REFERENCE_INDEX)}개 매핑")


def ensure_reference_index():
    if not REFERENCE_INDEX_LOADED and bible_collection:
        build_reference_index()


mailboxes = {}
postcards = {}


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def fetch_mailbox_supabase(mailbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/mailboxes"
    params = {"id": f"eq.{mailbox_id}", "limit": 1}
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Supabase mailbox fetch 실패 status={resp.status_code}, body={resp.text}")
            return None
        data = resp.json()
        return data[0] if data else None
    except Exception as exc:
        print(f"⚠️ Supabase mailbox fetch 예외: {exc}")
        return None


def fetch_postcards_supabase(mailbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
    params = {"mailbox_id": f"eq.{mailbox_id}", "order": "created_at.asc"}
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Supabase postcards fetch 실패 status={resp.status_code}, body={resp.text}")
            return []
        return resp.json() or []
    except Exception as exc:
        print(f"⚠️ Supabase postcards fetch 예외: {exc}")
        return []


def store_mailbox_supabase(mailbox: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 mailboxes 저장을 건너뜁니다.")
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/mailboxes"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    payload = {
        "id": mailbox["id"],
        "name": mailbox.get("name"),
        "nickname": mailbox.get("nickname"),
        "prayer_topic": mailbox.get("prayer_topic", ""),
        "url": mailbox.get("url"),
        "created_at": mailbox.get("created_at"),
        "is_opened": mailbox.get("is_opened", False),
        "full_url": mailbox.get("full_url"),
    }
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        if resp.status_code not in (200, 201):
            print(f"⚠️ Supabase mailboxes 저장 실패 status={resp.status_code}, body={resp.text}")
            return None
        return resp.json()
    except Exception as exc:
        print(f"⚠️ Supabase mailboxes 저장 예외: {exc}")
        return None


def store_postcard_supabase(mailbox_id: str, postcard: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 postcards 저장을 건너뜁니다.")
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    payload = {
        "id": postcard["id"],
        "mailbox_id": mailbox_id,
        "verse_reference": postcard.get("verse_reference"),
        "verse_text": postcard.get("verse_text"),
        "message": postcard.get("message", ""),
        "created_at": postcard.get("created_at"),
    }
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        if resp.status_code in (200, 201):
            return resp.json()
        print(f"⚠️ Supabase postcards 저장 실패 status={resp.status_code}, body={resp.text}")
    except Exception as exc:
        print(f"⚠️ Supabase postcards 저장 예외: {exc}")
    return None


def store_generated_url(original_url: str, base_url: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 generated_urls 저장을 건너뜁니다.")
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/generated_urls"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"

    last_error = None
    for _ in range(3):
        short_code = uuid.uuid4().hex[:8]
        short_url = f"{base_url.rstrip('/')}/{short_code}"
        payload = {"short_url": short_url, "original_url": original_url}

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        except Exception as exc:
            last_error = f"request failure: {exc}"
            break

        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                if isinstance(data, list) and data:
                    return data[0].get("short_url", short_url)
                if isinstance(data, dict) and data.get("short_url"):
                    return data.get("short_url")
            except ValueError:
                return short_url
            return short_url

        if resp.status_code == 409:
            last_error = "duplicate short_url, retrying"
            continue

        last_error = f"status={resp.status_code}, body={resp.text}"
        break

    if last_error:
        print(f"⚠️ Supabase generated_urls 저장 실패: {last_error}")
    return None


def build_contextual_query(keyword: str):
    """키워드를 상황 설명 문장으로 확장하고, 테마별 대표 구절 목록도 함께 반환."""
    keyword = (keyword or '').strip()
    lowered = keyword.lower()
    matched_contexts = []
    curated_refs = []

    for rule in THEME_CONTEXT_RULES:
        tokens = rule["tokens"]
        if any(token in keyword for token in tokens) or any(token in lowered for token in tokens):
            matched_contexts.append(rule["description"])
            curated_refs.extend(rule.get("curated_references", []))

    if not matched_contexts:
        matched_contexts.append(DEFAULT_CONTEXT_DESCRIPTION)

    # 중복 제거하면서 순서 유지
    seen_ctx = set()
    unique_contexts = []
    for ctx in matched_contexts:
        if ctx not in seen_ctx:
            unique_contexts.append(ctx)
            seen_ctx.add(ctx)

    seen_refs = set()
    unique_refs = []
    for ref in curated_refs:
        ref = ref.strip()
        if ref and ref not in seen_refs:
            unique_refs.append(ref)
            seen_refs.add(ref)

    contextual_summary = ' / '.join(unique_contexts)
    expanded = (
        f"query: {keyword}. "
        f"상황과 감정: {contextual_summary}. "
        "주제와 맞닿은 성경의 약속, 위로, 격려, 도전, 하나님의 성품과 계획을 찾는다."
    )
    return expanded, unique_refs


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/create-mailbox', methods=['POST'])
def create_mailbox():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    prayer_topic = data.get('prayer_topic', '')

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    mailbox_id = str(uuid.uuid4())[:8]
    base_url = request.url_root.rstrip('/')
    mailbox_path = f'/mailbox/{mailbox_id}'
    original_url = f"{base_url}{mailbox_path}"
    mailboxes[mailbox_id] = {
        'id': mailbox_id,
        'name': name,
        'nickname': name,
        'prayer_topic': prayer_topic,
        'url': mailbox_path,
        'full_url': original_url,
        'created_at': datetime.now().isoformat(),
        'is_opened': False
    }
    postcards[mailbox_id] = []

    short_url = store_generated_url(original_url=original_url, base_url=base_url)
    store_mailbox_supabase(mailboxes[mailbox_id])
    response_payload = {
        'mailbox_id': mailbox_id,
        'url': mailbox_path,
        'original_url': original_url
    }
    if short_url:
        response_payload['short_url'] = short_url
    return jsonify(response_payload)


@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """semantic 우선 + popularity + 테마 대표 구절 전부 상단 주입"""
    if not bible_collection:
        return jsonify({'error': 'ChromaDB 컬렉션이 로드되지 않았습니다'}), 500
    
    try:
        data = request.get_json(silent=True) or {}
        keyword = (data.get('keyword') or data.get('query') or '').strip()
        if not keyword:
            return jsonify({'error': '검색어가 필요합니다'}), 400
        print(f"\n🔍 검색 키워드: '{keyword}'")

        ensure_reference_index()
        
        # 1) 쿼리를 주제+상황으로 확장
        query_text, curated_refs = build_contextual_query(keyword)
        
        # ⭐ 2) TEHMA 대표 구절 전부 먼저 확보 (중복 제거)
        curated_reference_set = set()
        curated_keys_order = []
        theme_injected = []  # 주입될 대표 구절들
        
        for ref in curated_refs:
            key = normalize_reference(ref)
            if key and key not in curated_reference_set:
                curated_reference_set.add(key)
                curated_keys_order.append(key)
        
        print(f"   🎯 매칭된 테마 규칙: {len(curated_keys_order)}개 대표 구절")
        
        # 대표 구절들을 먼저 모두 확보 (캐시 또는 DB에서)
        for key in curated_keys_order:
            cached = REFERENCE_INDEX.get(key)
            if cached:
                meta = cached["metadata"] or {}
                doc = cached["text"]
                popularity = meta.get("popularity", 85)
                reference = build_reference_label(meta, doc)
                
                theme_injected.append({
                    "text": doc,
                    "reference": reference,
                    "semantic_score": None,
                    "popularity": popularity,
                    "final_score": 1.8,  # 항상 최상단 고정 점수
                    "is_curated": True,
                    "injected": True,
                    "priority": "theme_top"  # 최상위 우선순위
                })
            else:
                print(f"     ⚠️ 대표 구절 미발견: {key}")
        
        print(f"   ✅ 테마 대표 구절 {len(theme_injected)}개 확보 완료")
        
        # 3) 쿼리 임베딩 및 벡터 검색 (대표 구절 제외하고 일반 검색)
        query_embedding = embedding_model.encode(query_text).tolist()
        print(f"   임베딩 생성 완료: {len(query_embedding)}차원")
        
        # 상위 40개 정도 일반 검색 (대표 구절만큼 덜 가져옴)
        raw_results = bible_collection.query(
            query_embeddings=[query_embedding],
            n_results=40,
            include=["documents", "metadatas", "distances"]
        )
        print(f"✅ 1차 벡터 검색 완료: {len(raw_results['documents'][0])}개 결과")
        
        # 4) 일반 검색 결과 rerank (테마 대표 구절 제외)
        docs = raw_results["documents"][0]
        metas = raw_results["metadatas"][0]
        dists = raw_results["distances"][0]
        
        reranked_general = []
        used_refs_general = set()
        
        for doc, meta, dist in zip(docs, metas, dists):
            reference = build_reference_label(meta, doc)
            normalized_ref = normalize_reference(reference)
            
            # 이미 테마 대표 구절이면 스킵
            if normalized_ref in curated_reference_set:
                continue
                
            semantic_score = 1 - dist
            popularity = meta.get("popularity", 30)
            pop_norm = popularity / 100.0
            final_score = semantic_score * 0.8 + pop_norm * 0.2
            
            reranked_general.append({
                "text": doc,
                "reference": reference,
                "semantic_score": round(semantic_score, 4),
                "popularity": popularity,
                "final_score": round(final_score, 4),
                "is_curated": False,
                "priority": "general"
            })
            used_refs_general.add(normalized_ref)
        
        # 5) 최종 결과 조합: [테마 대표 구절 전부] + [일반 상위 결과]
        reranked_general.sort(key=lambda x: x["final_score"], reverse=True)
        final_results = theme_injected + reranked_general[:5 - len(theme_injected)]
        
        # 부족하면 일반 결과 더 채우기
        if len(final_results) < 5:
            remaining = [r for r in reranked_general if normalize_reference(r["reference"]) not in used_refs_general]
            final_results.extend(remaining[:5 - len(final_results)])
        
        # 최대 5개로 제한
        top_k = final_results[:5]
        
        print("📌 최종 선택된 구절 (테마 우선 + final_score):")
        for i, r in enumerate(top_k, 1):
            priority = r.get("priority", "general")
            print(f"  {i}. [{r['reference']}] {priority} | score={r['final_score']}")
            print(f"     {r['text'][:80]}...")
        
        return jsonify({"verses": top_k})
    
    except Exception as e:
        print(f"❌ 검색 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"검색 실패: {str(e)}"}), 500



def format_results(results):
    """ChromaDB 결과를 포맷팅하는 헬퍼 함수"""
    formatted = []
    if results['documents'] and results['documents'][0]:
        for i, doc in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
            distance = results['distances'][0][i] if results.get('distances') else 0
            
            reference = build_reference_label(metadata, doc)
            similarity_score = round((1 - distance) * 100, 1)
            popularity = metadata.get('popularity', 30)
            
            formatted.append({
                'text': doc,
                'reference': reference,
                'similarity': similarity_score,
                'popularity': popularity
            })
            
            print(f"  [{reference}] 유사도: {similarity_score}% | 인기도: {popularity}")
    
    return formatted


@app.route('/api/send-postcard', methods=['POST'])
def send_postcard():
    data = request.json
    mailbox_id = data.get('mailbox_id')
    
    if mailbox_id not in mailboxes:
        loaded = fetch_mailbox_supabase(mailbox_id)
        if not loaded:
            return jsonify({'error': 'Mailbox not found'}), 404
        mailboxes[mailbox_id] = loaded
        postcards[mailbox_id] = fetch_postcards_supabase(mailbox_id)
    
    postcard = {
        'id': str(uuid.uuid4()),
        'verse_reference': data.get('verse_reference'),
        'verse_text': data.get('verse_text'),
        'message': data.get('message', ''),
        'created_at': datetime.now().isoformat()
    }
    
    postcards[mailbox_id].append(postcard)
    store_postcard_supabase(mailbox_id, postcard)
    
    return jsonify({'success': True, 'postcard_id': postcard['id']})


@app.route('/mailbox/<mailbox_id>')
def mailbox(mailbox_id):
    if mailbox_id not in mailboxes:
        loaded = fetch_mailbox_supabase(mailbox_id)
        if not loaded:
            return "우체통을 찾을 수 없습니다", 404
        mailboxes[mailbox_id] = loaded
        postcards[mailbox_id] = fetch_postcards_supabase(mailbox_id)
    
    mailbox_data = mailboxes[mailbox_id]
    postcard_list = postcards.get(mailbox_id, [])
    
    if datetime.now() >= datetime(2026, 1, 1) or mailbox_data.get('is_opened'):
        mailbox_data['is_opened'] = True
        return render_template('mailbox.html', 
                             mailbox=mailbox_data, 
                             postcards=postcard_list)
    else:
        return render_template('mailbox_locked.html', mailbox=mailbox_data)


@app.route('/send/<mailbox_id>')
def send_page(mailbox_id):
    if mailbox_id not in mailboxes:
        loaded = fetch_mailbox_supabase(mailbox_id)
        if not loaded:
            return "우체통을 찾을 수 없습니다", 404
        mailboxes[mailbox_id] = loaded
        postcards.setdefault(mailbox_id, fetch_postcards_supabase(mailbox_id))

    return render_template('send_postcard.html', mailbox_id=mailbox_id)


def open_all_mailboxes():
    for mailbox_id in mailboxes:
        mailboxes[mailbox_id]['is_opened'] = True


scheduler = BackgroundScheduler()
scheduler.add_job(
    func=open_all_mailboxes,
    trigger='cron',
    year=2026,
    month=1,
    day=1,
    hour=0,
    minute=0
)
scheduler.start()


if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작")
    print("✅ 시맨틱 검색 활성화 (1024차원 벡터)")
    print("✅ 인기도 필터링 활성화 (3-tier 검색)")
    print("📍 브라우저에서 접속: http://127.0.0.1:5001")
    print("="*50 + "\n")
    app.run(host='127.0.0.1', port=5001, debug=True, threaded=True)
