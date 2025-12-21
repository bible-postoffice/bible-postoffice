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
from flask import Flask, render_template, request, jsonify, session, redirect # redirect 추가
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'e48ca7312db5b8f76c0c095e845c9eaf')
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


#
# 하영
#
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

# 템플릿 유형 매핑 (Supabase templates.template_type: 0=엽서, 1=편지지)
TEMPLATE_TYPE_MAP = {
    "엽서": 0,
    "편지지": 1,
}


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def fetch_postbox_supabase(postbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postboxes"
    params = {"id": f"eq.{postbox_id}", "limit": 1}
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Supabase post fetch 실패 status={resp.status_code}, body={resp.text}")
            return None
        data = resp.json()
        return data[0] if data else None
    except Exception as exc:
        print(f"⚠️ Supabase post fetch 예외: {exc}")
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




def fetch_postcard_by_id(postcard_id: str):
    """우편 ID로 엽서 1건을 가져온다 (메모리 캐시 → Supabase)."""
    # 1) 메모리 캐시 우선
    for plist in postcards.values():
        for card in plist:
            if card.get("id") == postcard_id:
                return card

    # 2) Supabase 조회
    if SUPABASE_URL and SUPABASE_KEY:
        endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
        params = {"id": f"eq.{postcard_id}", "limit": 1}
        try:
            resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json() or []
                return data[0] if data else None
            else:
                print(f"⚠️ Supabase postcard fetch 실패 status={resp.status_code}, body={resp.text}")
        except Exception as exc:
            print(f"⚠️ Supabase postcard fetch 예외: {exc}")
    return None


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
        "prayer_topic": postbox.get("prayer_topic", ""),
        "url": postbox.get("url"),
        "created_at": postbox.get("created_at"),
        "is_opened": postbox.get("is_opened", False),
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


def ensure_postbox_supabase(postbox_id: str):
    """Supabase postboxes에 해당 postbox가 없으면 저장을 시도."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    if fetch_postbox_supabase(postbox_id):
        return
    pb = postboxes.get(postbox_id)
    if pb:
        store_postbox_supabase(pb)


def store_postcard_supabase(postbox_id: str, postcard: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ Supabase 설정이 없어 postcards 저장을 건너뜁니다.")
        return None
    # 외래키 충돌 방지를 위해 postbox 레코드 확보
    ensure_postbox_supabase(postbox_id)
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
    headers = supabase_headers()
    headers["Prefer"] = "return=representation"
    # template_id를 integer로 변환 시도 (문자열에 숫자가 섞여 있으면 숫자만 추출)
    tpl_id_raw = postcard.get("template_id")
    tpl_id = None
    try:
        if isinstance(tpl_id_raw, str):
            digits = ''.join(ch for ch in tpl_id_raw if ch.isdigit())
            tpl_id = int(digits) if digits else None
        elif tpl_id_raw is not None:
            tpl_id = int(tpl_id_raw)
    except Exception:
        tpl_id = None
    tpl_type_raw = postcard.get("template_type")
    tpl_type = TEMPLATE_TYPE_MAP.get(tpl_type_raw, tpl_type_raw if isinstance(tpl_type_raw, int) else None)
    payload = {
        "id": postcard["id"],
        "postbox_id": postbox_id,
        "template_id": tpl_id,
        "template_type": tpl_type,
        "is_anonymous": postcard.get("is_anonymous", False),
        "verse_reference": postcard.get("verse_reference"),
        "verse_text": postcard.get("verse_text"),
        "message": postcard.get("message", ""),
        "created_at": postcard.get("created_at"),
    }
    if postcard.get("font_family"):
        payload["font_family"] = postcard.get("font_family")
    if postcard.get("font_style"):
        payload["font_style"] = postcard.get("font_style")
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 400 and ("font_family" in resp.text or "font_style" in resp.text):
            fallback_payload = dict(payload)
            fallback_payload.pop("font_family", None)
            fallback_payload.pop("font_style", None)
            resp_font_retry = requests.post(endpoint, headers=headers, json=fallback_payload, timeout=8)
            if resp_font_retry.status_code in (200, 201):
                print("ℹ️ Supabase가 글씨체 컬럼을 지원하지 않아 기본 필드로 저장했습니다.")
                return resp_font_retry.json()
        # 외래키 부족 등으로 실패하면 한번 더 postbox upsert 시도 후 재시도
        if resp.status_code == 409:
            ensure_postbox_supabase(postbox_id)
            resp_retry = requests.post(endpoint, headers=headers, json=payload, timeout=8)
            if resp_retry.status_code in (200, 201):
                return resp_retry.json()
            print(f"⚠️ Supabase postcards 재시도 실패 status={resp_retry.status_code}, body={resp_retry.text}")
        else:
            print(f"⚠️ Supabase postcards 저장 실패 status={resp.status_code}, body={resp.text}")
    except Exception as exc:
        print(f"⚠️ Supabase postcards 저장 예외: {exc}")
        return None


@app.route('/view-postcard/<postcard_id>')
def view_postcard(postcard_id):
    card = fetch_postcard_by_id(postcard_id)
    if not card:
        return "엽서를 찾을 수 없습니다.", 404
    sender = "익명"
    verse_ref = card.get("verse_reference") or "말씀"
    verse_text = card.get("verse_text") or ""
    message = card.get("message") or ""
    font_family = card.get("font_family") or ""
    tpl_id_raw = card.get("template_id") or 1
    tpl_img = None
    tpl_type = card.get("template_type") or 0
    try:
        tpl_meta = fetch_template_meta(int(tpl_id_raw))
        if tpl_meta:
            tpl_img = tpl_meta.get("image_path")
            tpl_type = tpl_meta.get("template_type", tpl_type)
    except Exception:
        tpl_meta = None
    # 파일 시스템은 대소문자 구분이 있을 수 있으니 소문자로 정규화
    template_image = (tpl_img or "images/postcards/POSTCARD1.png").lower()
    template_type = tpl_type
    return render_template(
        'postcard_view.html',
        postcard_id=postcard_id,
        sender=sender,
        verse_reference=verse_ref,
        verse_text=verse_text,
        message=message,
        font_family=font_family,
        template_id=tpl_id_raw,
        template_type=template_type,
        template_image=template_image,
    )

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


@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """레퍼런스 직접 매칭 → 문구 검색(greedy+semantic) 추천."""
    if not bible_collection:
        return jsonify({'error': 'ChromaDB 컬렉션이 로드되지 않았습니다'}), 500
    
    try:
        data = request.get_json(silent=True) or {}
        query = (data.get('query') or data.get('keyword') or '').strip()
        page = 0
        try:
            page = max(0, int(data.get('page', 0)))
        except Exception:
            page = 0
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
                "success": True, 
                "url": unique_path
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
        normalized_query = re.sub(r"\s+", "", normalize_korean(query or "").lower())
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
            coverage = greedy_hits / max(1, len(expanded_terms)) if expanded_terms else 0
            phrase_bonus = coverage * 0.1  # 핵심어 커버리지 보너스
            if coverage >= 0.99:  # 모든 핵심어를 포함하면 추가 가산
                phrase_bonus += 0.08
            if normalized_query and normalized_query in re.sub(r"\s+", "", normalize_korean(doc or "").lower()):
                phrase_bonus += 0.06  # 전체 문구가 연속해 들어있으면 추가 보너스
            phrase_bonus = min(0.24, phrase_bonus)
            final_score = semantic * 0.6 + (pop / 100.0) * 0.4 + phrase_bonus + greedy_bonus

            scored.append((final_score, reference, doc, meta))

        scored.sort(key=lambda x: x[0], reverse=True)
        all_candidates_full = curated_items + scored
        page_size = 5
        start_idx = page * page_size
        end_idx = start_idx + page_size
        # 요청한 페이지까지 필요한 만큼만 슬라이스
        needed = end_idx
        all_candidates = all_candidates_full[:needed]
        page_slice = all_candidates[start_idx:end_idx]
        total_pages = (len(all_candidates_full) + page_size - 1) // page_size if all_candidates_full else 0

        verses = []
        for entry in page_slice:
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

        has_more = end_idx < len(all_candidates_full)
        return jsonify({
            "verses": verses,
            "has_more": has_more,
            "total_pages": total_pages,
            "page": page,
        })
    
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
    postbox_id = data.get('postbox_id')
    
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            # Supabase에도 없으면 최소 정보로 생성 후 진행
            base_url = request.url_root.rstrip('/')
            postbox_path = f"/postboxes/{postbox_id}"
            fallback = {
                'id': postbox_id,
                'name': '우체통',
                'nickname': '우체통',
                'prayer_topic': '',
                'url': postbox_path,
                'created_at': datetime.now().isoformat(),
                'is_opened': False
            }
            postboxes[postbox_id] = fallback
            postcards[postbox_id] = []
            store_postbox_supabase(fallback)
        else:
            postboxes[postbox_id] = loaded
            postcards[postbox_id] = fetch_postcards_supabase(postbox_id)
    
    postcard = {
        'id': str(uuid.uuid4()),
        'template_id': data.get('template_id') or 1,
        'template_type': data.get('template_type') if data.get('template_type') is not None else 0,
        'template_name': data.get('template_name') or '',
        'is_anonymous': bool(data.get('is_anonymous')),
        'verse_reference': data.get('verse_reference'),
        'verse_text': data.get('verse_text'),
        'message': data.get('message', ''),
        'font_family': data.get('font_family') or '',
        'font_style': data.get('font_style') or '',
        'created_at': datetime.now().isoformat()
    }
    
    postcards[postbox_id].append(postcard)
    store_postcard_supabase(postbox_id, postcard)
    
    return jsonify({'success': True, 'postcard_id': postcard['id']})


@app.route('/send/<postbox_id>/write')
def send_page_write(postbox_id):
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            # Supabase에도 없으면 최소 정보로 생성하여 진행
            base_url = request.url_root.rstrip('/')
            postbox_path = f"/postboxes/{postbox_id}"
            fallback = {
                'id': postbox_id,
                'name': '우체통',
                'nickname': '우체통',
                'prayer_topic': '',
                'url': postbox_path,
                'full_url': f"{base_url}{postbox_path}",
                'created_at': datetime.now().isoformat(),
                'is_opened': False
            }
            postboxes[postbox_id] = fallback
            postcards.setdefault(postbox_id, [])
            store_postbox_supabase(fallback)
        else:
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


@app.route('/send/<postbox_id>/preview')
def send_page_preview(postbox_id):
    if postbox_id not in postboxes:
        loaded = fetch_postbox_supabase(postbox_id)
        if not loaded:
            base_url = request.url_root.rstrip('/')
            postbox_path = f"/postboxes/{postbox_id}"
            fallback = {
                'id': postbox_id,
                'name': '우체통',
                'nickname': '우체통',
                'prayer_topic': '',
                'url': postbox_path,
                'full_url': f"{base_url}{postbox_path}",
                'created_at': datetime.now().isoformat(),
                'is_opened': False
            }
            postboxes[postbox_id] = fallback
            postcards.setdefault(postbox_id, [])
            store_postbox_supabase(fallback)
        else:
            postboxes[postbox_id] = loaded
            postcards.setdefault(postbox_id, fetch_postcards_supabase(postbox_id))

    return render_template('preview_postcard.html', postbox_id=postbox_id)


def open_all_postboxes():
    for postbox_id in postboxes:
        postboxes[postbox_id]['is_opened'] = True


# -----------------------
#
# 세림
#

@app.route('/auth/check-and-save', methods=['POST'])
def check_and_save():

    data = request.get_json()
    token = data.get('token')
    email = data.get('email')

    try:
        # 1. 토큰 검증 (Supabase Auth 연동)
        user_info = supabase.auth.get_user(token)
        if not user_info:
            return jsonify({"success": False, "message": "유효하지 않은 토큰"}), 401

        # Supabase 유저 메타데이터에서 display_name 추출
        user_metadata = user_info.user.user_metadata
        nickname = user_metadata.get('display_name') or user_metadata.get('full_name') or email.split('@')[0]
        
        # 2. bible_users 테이블에 Upsert (없으면 생성, 있으면 업데이트)
        # email 컬럼이 Primary Key로 설정되어 있어야 합니다.
        user_data = {
            "email": email,
            "nickname" : nickname,
            "last_login_at": datetime.now().isoformat() # 파이썬에서 시간 생성
        }
        
        # upsert는 기본적으로 on_conflict를 Primary Key로 잡습니다.
        response = supabase.table('bible_users').upsert(user_data).execute()

        if not response.data:
            return jsonify({"success": False, "message": "유저 정보를 찾을 수 없습니다."}), 404
        
        user = response.data[0]
        user_id = user.get('id')
        user_flag = user.get('flag', False) # flag 값 확인 (True/False)
        
        # 세션에 이메일 저장 (로그인 유지용)
        session['user_email'] = email
        session['user_nickname'] = nickname


        # 2. 로직 분기
        if user_flag:
            # [Case: flag=true] 우체통 정보 조회
            postbox_res = supabase.table('postboxes').select('url').eq('owner_id', user_id).execute()
            
            if postbox_res.data:
                # 우체통 URL이 존재하면 해당 주소로 안내
                postbox_url = postbox_res.data[0].get('url')
                print(f"Redirecting to: /postbox/{postbox_url}")
                return jsonify({
                    "success": True,
                    "redirect_url": f"/postbox/{postbox_url}", # 실제 우체통 주소
                    "status": "existing_user",
                    "nickname": nickname
                })
            else:
                        # 데이터 정합성 방어: flag는 true인데 postbox가 없는 경우
                        return jsonify({"success": True, "redirect_url": "/create-postbox", "status": "new_user"})
            
        else:
                    # [Case: flag=false] 계정은 있으나 우체통은 없음 -> 생성 페이지로
                    return jsonify({
                        "success": True, 
                        "redirect_url": "/create-postbox", 
                        "status": "new_user",
                        "nickname": nickname
                    })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


import uuid

@app.route('/create-postbox-action', methods=['POST'])
def create_postbox_action():
    if 'user_email' not in session:
        return jsonify({"success": False, "message": "로그인이 필요합니다."}), 401

    data = request.get_json()
    
    try:
        # 고유 URL 생성 (예: nickname-4자리숫자)
        unique_path = f"{str(uuid.uuid4())[:8]}" 
        
        postbox_data = {
            "owner_id": data.get('owner_id'),
            "name": data.get('name'),
            "prayer_topic": data.get('prayer_topic'),
            "color": data.get('color'),
            "privacy": data.get('privacy'), # True/False
            "url": unique_path,
            "is_opened": False,
            "created_at" : datetime.now().isoformat()
        }

        # DB에 저장 (이때 SQL에서 만든 트리거가 bible_users의 flag를 true로 바꿈)
        result = supabase.table('postboxes').insert(postbox_data).execute()

        if result.data:
            return jsonify({
                "success": True, 
                "url": unique_path
            })
        else:
            return jsonify({"success": False, "message": "DB 저장 실패"}), 500
    except Exception as e:
        print(f"Create Error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/create-postbox')
def create_postbox_page():
    if 'user_email' not in session:
        return redirect('/')
    
    user_nickname = session.get('user_nickname', '사용자')

    return render_template('create_postbox.html',
                           user_name=user_nickname,
                           supabase_url=os.environ.get('SUPABASE_URL'), 
                           supabase_key=os.environ.get('SUPABASE_KEY')
                           )

# 우체통 확인
@app.route('/postbox/<url_path>')
def view_postbox(url_path):
    try:
        # 1. DB의 'postboxes' 테이블에서 url 컬럼이 url_path와 일치하는 데이터 조회
        result = supabase.table('postboxes').select("*").eq("url", url_path).execute()

        # 2. 데이터가 없는 경우 (잘못된 주소)
        if not result.data:
            print(f"No postbox found in DB for URL: {url_path}")
            return "우체통을 찾을 수 없습니다.", 404

        postbox = result.data[0] # 첫 번째 검색 결과 가져오기

       # 2. 현재 접속자가 주인인지 확인 (세션 기반)
        # 세션의 이메일과 DB의 owner_id(또는 연동된 이메일)를 비교
        # 여기서는 단순화를 위해 세션 이메일이 있고, 해당 유저의 id와 pb['owner_id']가 같은지 확인이 필요합니다.
        # 일단은 로그인 기능을 고려해 아래와 같이 구성합니다.
        user_email = session.get('user_email')
        end_date = session.get('end_date') or '2026-01-01'
        is_owner = False
        
        # 주인을 확인하기 위해 현재 로그인된 유저의 UUID를 가져와야 함
        if user_email:
            user_res = supabase.table('bible_users').select("id").eq("email", user_email).execute()
            if user_res.data and user_res.data[0]['id'] == postbox['owner_id']:
                is_owner = True

        # 3. 개봉일 설정 (예: 2026년 1월 1일)
        from datetime import datetime
        try:
            target_dt = datetime.strptime(end_date, '%Y-%m-%d')
        except:
            # 날짜 형식이 잘못되었을 경우를 대비한 방어 코드
            target_dt = datetime(2026, 1, 1)

        is_expired = datetime.now() >= target_dt

        # 4. 템플릿 렌더링 (HTML에서 사용하는 변수명과 일치시킴)
        return render_template('view_postbox.html', 
                               postbox_name=postbox['name'],
                               color=postbox['color'],
                               # DB가 0이면 'public', 1이면 'private'으로 변환해서 전달
                               privacy='public' if postbox['privacy'] == 0 else 'private',
                               end_date=end_date,
                               is_owner=is_owner,
                               is_expired=is_expired)

    except Exception as e:
        print(f"Error: {e}")
        return "오류가 발생했습니다.", 500

# 편지 작성
@app.route('/send_postcard/<url_path>')
def send_postcard(url_path):
    # 1. 로그인 체크
    if 'user_email' not in session:
        return redirect('/login')

    # 2. 우체통 정보 가져오기 (작성 화면 꾸미기용)
    result = supabase.table('postboxes').select("name, color").eq("url", url_path).execute()
    if not result.data:
        return "존재하지 않는 우체통입니다.", 404

    pb = result.data[0]
    return render_template('send_postcard.html', 
                           url_path=url_path, 
                           postbox_name=pb['name'], 
                           color=pb['color'])


@app.route('/')
def index():
    if 'user_email' in session:
            # 로그인 세션이 있다면 DB에서 flag를 다시 확인
            email = session['user_email']
            user_res = supabase.table('bible_users').select("id, flag").eq("email", email).execute()
            
            if user_res.data and user_res.data[0]['flag'] is True:
                # 우체통이 이미 있다면 내 우체통으로 리다이렉트
                pb_res = supabase.table('postboxes').select("url").eq("owner_id", user_res.data[0]['id']).execute()
                if pb_res.data:
                    return redirect(f"/postbox/{pb_res.data[0]['url']}")
            
            # flag가 false면 생성 페이지로
            return redirect('/create-postbox')
    return render_template('index.html',
                            url=os.environ.get('SUPABASE_URL'), 
                            key=os.environ.get('SUPABASE_KEY'))



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


if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작")
    print("✅ 인기도 필터링 활성화 (3-tier 검색)")
    ensure_reference_index()
    ensure_verse_lookup_index()
    # 환경 감지
    is_local = os.environ.get('RENDER') is None  # Render는 자동으로 RENDER 환경변수 설정
    host = '127.0.0.1' if is_local else '0.0.0.0'
    port = int(os.environ.get('PORT', 5001))
    debug = is_local
    
    print(f"📍 브라우저에서 접속: http://{host}:{port}")
    print(f"🔧 환경: {'로컬 개발' if is_local else 'Render 배포'}")
    print("="*50 + "\n")
