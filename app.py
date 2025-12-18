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


app = Flask(__name__)

import os
app.secret_key = os.urandom(24)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


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


REFERENCE_INPUT_PATTERN = re.compile(
    r'^\s*([0-9]{0,1}\s*[가-힣A-Za-z]{1,30})\s*([0-9]{1,3})\s*(?:[:장]\s*([0-9]{1,3}))\s*(?:[-–—~]\s*([0-9]{1,3}))?\s*(?:절)?\s*$'
)

BOOK_ABBREVIATIONS = {
    # 한글 약어
    "마": "마태복음", "막": "마가복음", "눅": "누가복음", "요": "요한복음",
    "롬": "로마서", "고전": "고린도전서", "고후": "고린도후서", "갈": "갈라디아서",
    "엡": "에베소서", "빌": "빌립보서", "골": "골로새서", "살전": "데살로니가전서",
    "살후": "데살로니가후서", "딤전": "디모데전서", "딤후": "디모데후서",
    "약": "야고보서", "벧전": "베드로전서", "벧후": "베드로후서",
    # 영문 약어(소문자)
    "mt": "마태복음", "matt": "마태복음", "mk": "마가복음", "lk": "누가복음",
    "jn": "요한복음", "rom": "로마서", "1th": "데살로니가전서", "2th": "데살로니가후서",
    "eph": "에베소서", "phil": "빌립보서", "jas": "야고보서",
}

KOREAN_TO_ENGLISH_BOOK = {v: k for k, v in BOOK_NAME_MAP.items()}
FULL_BOOK_TO_ABBREVIATIONS = {}
for abbr, full in BOOK_ABBREVIATIONS.items():
    if re.fullmatch(r"[가-힣0-9]+", abbr):
        FULL_BOOK_TO_ABBREVIATIONS.setdefault(full, []).append(abbr)


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
VERSE_LOOKUP_INDEX = {}
VERSE_LOOKUP_INDEX_LOADED = False


def canonical_book_name(book: str) -> str:
    book_key = normalize_korean(book or '').replace(" ", "")
    if not book_key:
        return ''
    if book_key.lower() in BOOK_ABBREVIATIONS:
        return BOOK_ABBREVIATIONS[book_key.lower()]
    if book_key in BOOK_ABBREVIATIONS:
        return BOOK_ABBREVIATIONS[book_key]
    return BOOK_NAME_MAP.get(book_key, book_key)


def parse_reference_input(text: str):
    m = REFERENCE_INPUT_PATTERN.match(normalize_korean(text or ""))
    if not m:
        return None
    book_raw, chapter, verse, verse_end = m.groups()
    book = canonical_book_name(book_raw)
    if not book:
        return None
    return {
        "book": book,
        "chapter": int(chapter),
        "verse": int(verse),
        "verse_end": int(verse_end) if verse_end else None,
    }


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


def build_verse_lookup_index():
    """(책+장:절) → 문서 전체 인덱스"""
    global VERSE_LOOKUP_INDEX_LOADED
    if VERSE_LOOKUP_INDEX_LOADED or not bible_collection:
        VERSE_LOOKUP_INDEX_LOADED = True
        return
    for doc, meta in iter_collection_documents(include=["documents", "metadatas"]):
        ref = build_reference_label(meta, doc)
        key = normalize_reference(ref)
        if key and key not in VERSE_LOOKUP_INDEX:
            VERSE_LOOKUP_INDEX[key] = {"text": doc, "metadata": meta}
    VERSE_LOOKUP_INDEX_LOADED = True


def ensure_verse_lookup_index():
    if not VERSE_LOOKUP_INDEX_LOADED and bible_collection:
        build_verse_lookup_index()


VERSE_LOOKUP_INDEX = {}
VERSE_LOOKUP_INDEX_LOADED = False


def iter_collection_documents(where=None, include=None, batch_size=2000):
    include = include or ["documents", "metadatas"]
    offset = 0
    while True:
        try:
            data = bible_collection.get(
                where=where,
                include=include,
                limit=batch_size,
                offset=offset,
            )
        except TypeError:
            data = bible_collection.get(where=where, include=include)
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs:
            return
        for d, m in zip(docs, metas):
            yield d, (m or {})
        offset += len(docs)


def build_verse_lookup_index():
    global VERSE_LOOKUP_INDEX_LOADED
    if VERSE_LOOKUP_INDEX_LOADED or not bible_collection:
        VERSE_LOOKUP_INDEX_LOADED = True
        return

    for doc, meta in iter_collection_documents(include=["documents", "metadatas"]):
        ref = build_reference_label(meta, doc)
        key = normalize_reference(ref)
        if key and key not in VERSE_LOOKUP_INDEX:
            VERSE_LOOKUP_INDEX[key] = {"text": doc, "metadata": meta}

    VERSE_LOOKUP_INDEX_LOADED = True


def ensure_verse_lookup_index():
    if not VERSE_LOOKUP_INDEX_LOADED and bible_collection:
        build_verse_lookup_index()


def extract_exact_verse_text(book, chapter, verse, document):
    doc_norm = normalize_korean(document or "")
    abbrs = FULL_BOOK_TO_ABBREVIATIONS.get(book, [])
    for abbr in abbrs:
        start = re.search(
            rf'{re.escape(abbr)}\s*{chapter}\s*:\s*{verse}\s*',
            doc_norm,
        )
        if not start:
            continue
        nxt = re.search(
            r'\n?\s*[가-힣]{1,5}\s*\d+\s*:\s*\d+\s*',
            doc_norm[start.end():],
        )
        end_idx = start.end() + (nxt.start() if nxt else len(doc_norm))
        body = doc_norm[start.end():end_idx].strip()
        return f"{abbr}{chapter}:{verse} {body}".strip()
    return None


def get_exact_verse_entry(ref_input: str):
    parsed = parse_reference_input(ref_input)
    if not parsed:
        return None

    book = parsed["book"]
    chapter = parsed["chapter"]
    verse = parsed["verse"]
    target_label = f"{book} {chapter}:{verse}"
    target_key = normalize_reference(target_label)

    ensure_verse_lookup_index()
    if target_key in VERSE_LOOKUP_INDEX:
        return VERSE_LOOKUP_INDEX[target_key]

    def doc_has_target(doc: str):
        doc_compact = re.sub(r"\s+", "", normalize_korean(doc or ""))
        markers = [
            f"{abbr}{chapter}:{verse}"
            for abbr in FULL_BOOK_TO_ABBREVIATIONS.get(book, [])
        ]
        markers += [re.sub(r"\s+", "", f"{book} {chapter}:{verse}")]
        return any(m in doc_compact for m in markers if m)

    for src in [book, KOREAN_TO_ENGLISH_BOOK.get(book)]:
        if not src:
            continue
        for doc, meta in iter_collection_documents(
            where={"source": src},
            include=["documents", "metadatas"],
        ):
            if normalize_reference(build_reference_label(meta, doc)) == target_key:
                return {"text": doc, "metadata": meta}
            if doc_has_target(doc):
                text = extract_exact_verse_text(book, chapter, verse, doc) or doc
                meta = dict(meta or {})
                meta["_reference_override"] = target_label
                return {"text": text, "metadata": meta}

    try:
        emb = embedding_model.encode(f"{target_label} 성경 구절").tolist()
        res = bible_collection.query(
            query_embeddings=[emb],
            n_results=200,
            include=["documents", "metadatas", "distances"],
        )
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for doc, meta in zip(docs, metas):
            if normalize_reference(build_reference_label(meta, doc)) == target_key:
                return {"text": doc, "metadata": meta}
            if doc_has_target(doc):
                text = extract_exact_verse_text(book, chapter, verse, doc) or doc
                meta = dict(meta or {})
                meta["_reference_override"] = target_label
                return {"text": text, "metadata": meta}
    except Exception:
        pass

    return None


def get_or_create_curated_entry(normalized_key: str, reference_label: str):
    if not normalized_key:
        return None
    cached = REFERENCE_INDEX.get(normalized_key)
    if cached:
        return cached
    hit = get_exact_verse_entry(reference_label)
    if hit:
        REFERENCE_INDEX[normalized_key] = hit
        return hit
    return None


postboxes = {}
postcards = {}

def fetch_postbox_supabase(postbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postboxes"
    params = {"id": f"eq.{postbox_id}", "limit": 1}
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Supabase postbox fetch 실패 status={resp.status_code}, body={resp.text}")
            return None
        data = resp.json()
        return data[0] if data else None
    except Exception as exc:
        print(f"⚠️ Supabase postbox fetch 예외: {exc}")
        return None


def fetch_postcards_supabase(postbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
    params = {"postbox_id": f"eq.{postbox_id}", "order": "created_at.asc"}
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Supabase postcards fetch 실패 status={resp.status_code}, body={resp.text}")
            return []
        return resp.json() or []
    except Exception as exc:
        print(f"⚠️ Supabase postcards fetch 예외: {exc}")
        return []


def store_postbox_supabase(postbox: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 postboxes 저장을 건너뜁니다.")
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postboxes"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    payload = {
        "id": postbox["id"],
        "name": postbox.get("name"),
        "nickname": postbox.get("nickname"),
        "prayer_topic": postbox.get("prayer_topic", ""),
        "url": postbox.get("url"),
        "created_at": postbox.get("created_at"),
        "is_opened": postbox.get("is_opened", False),
        "full_url": postbox.get("full_url"),
    }
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        if resp.status_code not in (200, 201):
            print(f"⚠️ Supabase postboxes 저장 실패 status={resp.status_code}, body={resp.text}")
            return None
        return resp.json()
    except Exception as exc:
        print(f"⚠️ Supabase postboxes 저장 예외: {exc}")
        return None


def store_postcard_supabase(postbox_id: str, postcard: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 postcards 저장을 건너뜁니다.")
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    payload = {
        "id": postcard["id"],
        "postbox_id": postbox_id,
        "template_id": postcard.get("template_id"),
        "template_type": postcard.get("template_type"),
        "template_name": postcard.get("template_name"),
        "is_anonymous": postcard.get("is_anonymous", False),
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


KOREAN_STOPWORDS = {
    "자기",
    "우리",
    "너희",
    "그",
    "이",
    "저",
    "것",
    "수",
    "때",
    "말",
    "일",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "에",
    "의",
    "과",
    "와",
    "로",
    "으로",
}


def greedy_terms(q: str):
    terms = []
    for tok in re.findall(
        r"[가-힣]{2,}|[a-z]{2,}",
        normalize_korean(q or "").lower(),
    ):
        if tok in KOREAN_STOPWORDS:
            continue
        terms.append(tok)
    seen = set()
    out = []
    for t in terms:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out[:6]


def greedy_match_count(terms, doc: str):
    docc = re.sub(r"\s+", "", normalize_korean(doc or "").lower())
    return sum(1 for t in terms if t and re.sub(r"\s+", "", t) in docc)



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





@app.route('/send/<postbox_id>')
def send_page(postbox_id):
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            return "우체통을 찾을 수 없습니다", 404
        postboxes[postbox_id] = loaded
        postcards.setdefault(postbox_id, fetch_postcards_supabase(postbox_id))

    return render_template('choose_template.html', postbox_id=postbox_id)


@app.route('/send/<postbox_id>/write')
def send_page_write(postbox_id):
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            return "우체통을 찾을 수 없습니다", 404
        postboxes[postbox_id] = loaded
        postcards.setdefault(postbox_id, fetch_postcards_supabase(postbox_id))

    template_id = request.args.get('template_id')
    template_type = request.args.get('template_type')
    template_name = request.args.get('template_name')

    return render_template(
        'send_postcard.html',
        postbox_id=postbox_id,
        template_id=template_id,
        template_type=template_type,
        template_name=template_name,
    )


def open_all_postboxes():
    for postbox_id in postboxes:
        postboxes[postbox_id]['is_opened'] = True


scheduler = BackgroundScheduler()
scheduler.add_job(
    func=open_all_postboxes,
    trigger='cron',
    year=2026,
    month=1,
    day=1,
    hour=0,
    minute=0
)
scheduler.start()


# ----------------------------------------------------------------
# 1. 메인 및 인증 관련 라우트 (추가/수정된 부분)
# ----------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

import requests
from flask import Flask, render_template, request, redirect, url_for, flash, session

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # 1. 폼 데이터 가져오기
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        if not SUPABASE_URL or not SUPABASE_KEY:
            flash("서버 설정 오류가 발생했습니다.")
            return redirect(url_for('signup'))

        # 2. Supabase 저장용 엔드포인트 및 페이로드 설정
        endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/bible_users"
        payload = {
            "name": name,
            "email": email,
            "password": password  # 실제 서비스 시 해싱(hashing) 권장
        }

        try:
            # 3. REST API를 통해 데이터 POST
            resp = requests.post(
                endpoint, 
                headers=supabase_headers(), 
                json=payload, 
                timeout=8
            )

            # 성공 시 (201 Created)
            if resp.status_code in (200, 201):
                flash(f"{name}님, 환영합니다! 로그인을 진행해주세요.")
                return redirect(url_for('login'))
            
            # 실패 시 (예: 이메일 중복 등)
            else:
                error_msg = resp.json().get('message', '알 수 없는 오류')
                if "unique_violation" in resp.text:
                    flash("이미 사용 중인 이메일입니다.")
                else:
                    flash(f"가입 실패: {error_msg}")
                return redirect(url_for('signup'))

        except Exception as e:
            print(f"⚠️ 회원가입 API 예외 발생: {e}")
            flash("서버 통신 중 오류가 발생했습니다.")
            return redirect(url_for('signup'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # [수정] 조회 시에도 테이블 이름을 users로 설정
        endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/bible_users?email=eq.{email}&password=eq.{password}&select=*"
        
        try:
            resp = requests.get(endpoint, headers=supabase_headers())
            users = resp.json()

            if resp.status_code == 200 and len(users) > 0:
                user = users[0]
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                
                flash(f"{user['name']}님, 환영합니다!")
                return redirect(url_for('setup_postbox')) # 로그인 성공 시 우체통 설정으로
            else:
                flash("이메일 또는 비밀번호가 일치하지 않습니다.")
                return redirect(url_for('login'))
        except Exception as e:
            flash("로그인 처리 중 오류가 발생했습니다.")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ----------------------------------------------------------------
# 2. 우체통 및 구절 API 라우트 (기존 로직 유지)
# ----------------------------------------------------------------

@app.route('/api/create-postbox', methods=['POST'])
def create_postbox():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    privacy = data.get('privacy')
    color = data.get('color')
    prayer_topic = data.get('prayer_topic', '')
    
    # [중요] 클라이언트에서 보낸 user_id (Supabase Auth ID)
    # 로그인을 했으므로 프론트에서 함께 보내주거나 세션에서 확인해야 합니다.
    user_id = data.get('user_id') 

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    # 1. 자르지 않은 전체 UUID 생성
    full_uuid = str(uuid.uuid4()) 
    
    base_url = request.url_root.rstrip('/')
    postbox_path = f'/postbox/{full_uuid}'
    original_url = f"{base_url}{postbox_path}"

    # 2. 데이터 구조 (Supabase 컬럼명에 맞춰 조정)
    postbox_data = {
        'id': full_uuid,           # 이제 UUID 전체가 들어감
        'name': name,
        'owner_id': user_id,        # 누가 만들었는지 저장
        'prayer_topic': prayer_topic,
        'created_at': datetime.now().isoformat(),
        'color': color,
        'is_opened': False,
        'end_date': datetime(2026, 1, 1, 0, 0, 0).isoformat(),
        'privacy': privacy
    }

    # 3. Supabase 저장
    # store_postbox_supabase 함수 내부에서 'mailboxes' 테이블에 insert 하도록 구성
    try:
        store_postbox_supabase(postbox_data)
        
        # 선택사항: 메모리(postboxes)에도 저장 시
        postboxes[full_uuid] = postbox_data
        postcards[full_uuid] = []

        response_payload = {
            'postbox_id': full_uuid,
            'url': postbox_path,
            'original_url': original_url
        }
        
        return jsonify(response_payload)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """레퍼런스 직접 매칭 → 문구 검색(greedy+semantic) 추천."""
    if not bible_collection:
        return jsonify({'error': 'ChromaDB 컬렉션이 로드되지 않았습니다'}), 500
    
    try:
        data = request.get_json(silent=True) or {}
        query = (data.get('query') or data.get('keyword') or '').strip()
        if not query:
            return jsonify({'error': '검색어가 필요합니다'}), 400
        print(f"\n🔍 검색 쿼리: '{query}'")
        ensure_reference_index()
        ensure_verse_lookup_index()

        # 1) 레퍼런스 직접 매칭 먼저 시도
        exact_hit = get_exact_verse_entry(query)
        if exact_hit:
            meta = exact_hit["metadata"] or {}
            ref_override = meta.get("_reference_override")
            if ref_override:
                reference = ref_override
            else:
                reference = build_reference_label(meta, exact_hit["text"])
            print(f"   🎯 레퍼런스 직접 매칭 성공: {reference}")

            return jsonify({
                "verses": [
                    {
                        "reference": reference,
                        "text": exact_hit["text"],
                        "metadata": meta,
                        "score": 1.0,
                    }
                ]
            })
        else:
            print("   ⚠️ 레퍼런스 직접 매칭 없음 → 시맨틱/greedy 검색으로 진행")

        # 2) 테마 토큰 매칭 → curated 구절 우선 주입
        query_text, curated_refs = build_contextual_query(query)
        curated_set = set()
        curated_items = []
        for ref in curated_refs:
            key = normalize_reference(ref)
            if not key or key in curated_set:
                continue
            curated_set.add(key)
            hit = get_or_create_curated_entry(key, ref)
            if hit:
                meta = hit.get("metadata") or {}
                doc = hit.get("text", "")
                reference = build_reference_label(meta, doc)
                pop = meta.get("popularity", 85)
                curated_items.append({
                    "reference": reference,
                    "text": doc,
                    "metadata": meta,
                    "score": 1.8,
                    "priority": "theme_top",
                    "popularity": pop,
                })
            else:
                print(f"     ⚠️ 대표 구절 미발견: {ref}")
        if curated_items:
            print(f"   🎯 테마 대표 구절 {len(curated_items)}개 주입")

        # 3) 문구 검색: greedy + semantic 혼합
        expanded_terms = greedy_terms(query)
        print(f"   🔎 greedy 핵심어: {expanded_terms if expanded_terms else '없음'}")
        query_embedding = embedding_model.encode(query_text).tolist()
        raw_results = bible_collection.query(
            query_embeddings=[query_embedding],
            n_results=200,
            include=["documents", "metadatas", "distances"],
        )

        docs = (raw_results.get("documents") or [[]])[0]
        metas = (raw_results.get("metadatas") or [[]])[0]
        dists = (raw_results.get("distances") or [[]])[0]

        scored = []
        for doc, meta, dist in zip(docs, metas, dists):
            if not doc:
                continue
            meta = meta or {}
            reference = meta.get("reference") or build_reference_label(meta, doc)
            if normalize_reference(reference) in curated_set:
                continue
            pop = meta.get("popularity", 0)
            semantic = 1 - dist if dist is not None else 0
            greedy_hits = greedy_match_count(expanded_terms, doc)
            greedy_bonus = min(0.18, greedy_hits * 0.06)
            phrase_bonus = 0.0  # 별도 phrase 스코어가 있다면 여기서 더해줌
            final_score = semantic * 0.6 + (pop / 100.0) * 0.4 + phrase_bonus + greedy_bonus

            scored.append((final_score, reference, doc, meta))

        scored.sort(key=lambda x: x[0], reverse=True)
        remaining_slots = max(0, 5 - len(curated_items))
        top = curated_items + scored[:remaining_slots]

        verses = []
        for entry in top:
            if isinstance(entry, tuple):
                score, reference, doc, meta = entry
            else:
                score = entry.get("score", entry.get("final_score", 1.0))
                reference = entry.get("reference")
                doc = entry.get("text")
                meta = entry.get("metadata", {})

            print(f"  📌 [{reference}] score={round(score,4)}")
            snippet = re.sub(r"\s+", " ", (doc or ""))[:120]
            print(f"     {snippet}...")
            verses.append(
                {
                    "reference": reference,
                    "text": doc,
                    "metadata": meta,
                    "score": score,
                }
            )

        return jsonify({"verses": verses})
    
    except Exception as e:
        print(f"❌ 검색 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"검색 실패: {str(e)}"}), 500


@app.route('/api/send-postcard', methods=['POST'])
def send_postcard():
    data = request.json
    postbox_id = data.get('postbox_id')

    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            return jsonify({'error': 'postbox not found'}), 404
        postboxes[postbox_id] = loaded
        postcards[postbox_id] = fetch_postcards_supabase(postbox_id)
    
    postcard = {
        'id': str(uuid.uuid4()),
        'template_id': data.get('template_id') or 'postcard-sunset',
        'template_type': data.get('template_type') or '엽서',
        'is_anonymous': bool(data.get('is_anonymous')),
        'verse_reference': data.get('verse_reference'),
        'verse_text': data.get('verse_text'),
        'message': data.get('message', ''),
        'created_at': datetime.now().isoformat()
    }
    
    postcards[postbox_id].append(postcard)
    store_postcard_supabase(postbox_id, postcard)
    
    return jsonify({'success': True, 'postcard_id': postcard['id']})

@app.route('/postbox/<postbox_id>')
def postbox(postbox_id):
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            return "우체통을 찾을 수 없습니다", 404
        postboxes[postbox_id] = loaded
        postcards[postbox_id] = fetch_postcards_supabase(postbox_id)
    
    postbox_data = postboxes[postbox_id]
    postcard_list = postcards.get(postbox_id, [])
    
    if datetime.now() >= datetime(2026, 1, 1) or postbox_data.get('is_opened'):
        postbox_data['is_opened'] = True
        return render_template('postbox.html', 
                             postbox=postbox_data, 
                             postcards=postcard_list)
    else:
        return render_template('postbox_locked.html', postbox=postbox_data)

from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("로그인이 필요한 서비스입니다.")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 회원 로그인 구현 전까지 테스트
@app.route('/setup-postbox')
@login_required
def setup_postbox():
    # .env 파일에서 직접 읽어서 템플릿으로 전달
    s_url = os.environ.get("SUPABASE_URL")
    s_key = os.environ.get("SUPABASE_KEY")
    # 임시로 유저 이름을 '나'로 설정 (로그인 연동 전)
    return render_template('setup_postbox.html',
                           supabase_url=s_url,
                           supabase_key=s_key,
                           user_name=session.get('user_name'))

from flask import Flask, render_template, request
from datetime import datetime

@app.route('/postbox/<name>')
def view_postbox(name):
    # 테스트용 파라미터들
    color = request.args.get('color', 'red')
    privacy = request.args.get('privacy', 'public')
    role = request.args.get('role', 'guest')  # 'owner' 또는 'guest'
    
    # 시간 체크 (2026년 1월 1일로 설정하여 테스트해보세요)
    target_date = datetime(2026, 1, 1, 0, 0, 0)
    is_expired = datetime.now() >= target_date # 현재 시간이 타겟 시간을 지났는가?
    
    is_owner = (role == 'owner')
    
    return render_template('view_postbox.html', 
                           postbox_name=name, 
                           color=color, 
                           privacy=privacy,
                           is_owner=is_owner,
                           is_expired=is_expired)


if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작")
 
    print("✅ 인기도 필터링 활성화 (3-tier 검색)")
    ensure_reference_index()
    ensure_verse_lookup_index()
    print("📍 브라우저에서 접속: http://127.0.0.1:5001")
    print("="*50 + "\n")
    app.run(host='127.0.0.1', port=5001, debug=True, threaded=True)