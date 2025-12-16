# app.py
from flask import Flask, render_template, request, jsonify
import chromadb
import uuid
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sentence_transformers import SentenceTransformer
import os
import re
from dotenv import load_dotenv
from popular_verses import (
    get_popularity_score,
    extract_chapter_verse,
    normalize_korean,
    BOOK_NAME_MAP,
)  # ⭐ 추가

load_dotenv()

CHROMA_PATH = os.environ.get("CHROMA_PATH")
if not CHROMA_PATH:
    if os.path.exists("./vectordb_e5small"):
        CHROMA_PATH = "./vectordb_e5small"
    else:
        CHROMA_PATH = "./vectordb2"

EMBEDDING_MODEL_NAME = os.environ.get(
    "EMBEDDING_MODEL", "intfloat/multilingual-e5-small"
)

app = Flask(__name__)

# 임베딩 모델 로드
print("🔄 임베딩 모델 로딩 중...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
embedding_dim = embedding_model.get_sentence_embedding_dimension()
print(f"✅ 임베딩 모델 로드 완료: {EMBEDDING_MODEL_NAME} ({embedding_dim}차원)")

# ChromaDB 초기화
try:
    print(f"📁 ChromaDB 경로: {CHROMA_PATH}")
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
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
            "시편 103:3",
            "마가복음 5:34"
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
# 예: "롬15:13", "Rom 15:13", "1Th 5:18", "약5:15" 등
DOC_REFERENCE_PATTERN = re.compile(r'([0-9]{0,1}\s*[가-힣A-Za-z]{1,20})\s*(\d+:\d+)')
DOC_REFERENCE_PATTERN_JANG = re.compile(r'([0-9]{0,1}\s*[가-힣A-Za-z]{1,20})\s*(\d+)\s*장\s*(\d+)\s*절')

# 입력으로 들어오는 "마 10:5", "마10장5절", "Matthew 10:5" 같은 레퍼런스 파서
REFERENCE_INPUT_PATTERN_RANGE = re.compile(
    r'^\s*([0-9]{0,1}\s*[가-힣A-Za-z]{1,30})\s*([0-9]{1,3})\s*(?:[:장]\s*([0-9]{1,3}))\s*(?:[-–—~]\s*([0-9]{1,3}))?\s*(?:절)?\s*$'
)

BOOK_ABBREVIATIONS = {
    "창": "창세기",
    "출": "출애굽기",
    "레": "레위기",
    "민": "민수기",
    "신": "신명기",
    "수": "여호수아",
    "삿": "사사기",
    "룻": "룻기",
    "삼상": "사무엘상",
    "삼하": "사무엘하",
    "왕상": "열왕기상",
    "왕하": "열왕기하",
    "대상": "역대상",
    "대하": "역대하",
    "스": "에스라",
    "느": "느헤미야",
    "에": "에스더",
    "욥": "욥기",
    "시": "시편",
    "잠": "잠언",
    "전": "전도서",
    "아": "아가",
    "사": "이사야",
    "렘": "예레미야",
    "애": "예레미야애가",
    "겔": "에스겔",
    "단": "다니엘",
    "호": "호세아",
    "욜": "요엘",
    "암": "아모스",
    "옵": "오바댜",
    "욘": "요나",
    "미": "미가",
    "나": "나훔",
    "합": "하박국",
    "습": "스바냐",
    "학": "학개",
    "슥": "스가랴",
    "말": "말라기",
    "마": "마태복음",
    "막": "마가복음",
    "눅": "누가복음",
    "요": "요한복음",
    "행": "사도행전",
    "롬": "로마서",
    "고전": "고린도전서",
    "고후": "고린도후서",
    "갈": "갈라디아서",
    "엡": "에베소서",
    "빌": "빌립보서",
    "골": "골로새서",
    "살전": "데살로니가전서",
    "살후": "데살로니가후서",
    "딤전": "디모데전서",
    "딤후": "디모데후서",
    "딛": "디도서",
    "몬": "빌레몬서",
    "히": "히브리서",
    "약": "야고보서",
    "벧전": "베드로전서",
    "벧후": "베드로후서",
    "요일": "요한일서",
    "요이": "요한이서",
    "요삼": "요한삼서",
    "유": "유다서",
    "계": "요한계시록",
    # English abbreviations (lowercase keys)
    "mt": "마태복음",
    "mat": "마태복음",
    "matt": "마태복음",
    "mk": "마가복음",
    "mrk": "마가복음",
    "lk": "누가복음",
    "luk": "누가복음",
    "jn": "요한복음",
    "jhn": "요한복음",
    "ps": "시편",
    "psa": "시편",
    "prov": "잠언",
    "prv": "잠언",
    "rom": "로마서",
    "1th": "데살로니가전서",
    "1thess": "데살로니가전서",
    "2th": "데살로니가후서",
    "2thess": "데살로니가후서",
    "eph": "에베소서",
    "phil": "빌립보서",
    "jas": "야고보서",
}

KOREAN_TO_ENGLISH_BOOK = {v: k for k, v in BOOK_NAME_MAP.items()}
FULL_BOOK_TO_ABBREVIATIONS = {}
for _abbr, _full in BOOK_ABBREVIATIONS.items():
    # 문서 프리픽스는 대개 한글 약어(예: 마10:5) 형태
    if re.fullmatch(r"[가-힣0-9]+", _abbr):
        FULL_BOOK_TO_ABBREVIATIONS.setdefault(_full, []).append(_abbr)


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


def iter_collection_documents(where=None, include=None, batch_size=2000):
    """
    Chroma collection.get() 결과가 기본적으로 limit이 걸려 있는 환경을 대비해,
    offset/limit 기반으로 문서를 순회한다.
    """
    if not bible_collection:
        return
    include = include or ["documents", "metadatas"]

    total = None
    try:
        total = bible_collection.count()
    except Exception:
        total = None

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
            # offset/limit 미지원 버전이면 단건 호출로 폴백
            data = bible_collection.get(where=where, include=include)
            docs = data.get("documents") or []
            metas = data.get("metadatas") or []
            for doc, meta in zip(docs, metas):
                yield doc, (meta or {})
            return

        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs:
            return

        for doc, meta in zip(docs, metas):
            yield doc, (meta or {})

        offset += len(docs)
        if total is not None and offset >= total:
            return


def canonical_book_name(book: str) -> str:
    book = normalize_korean(book or '').strip()
    if not book:
        return ''
    book_key = normalize_korean(book).replace(" ", "")
    book_key_lower = book_key.lower()
    if book_key_lower in BOOK_ABBREVIATIONS:
        return BOOK_ABBREVIATIONS[book_key_lower]
    if book_key in BOOK_ABBREVIATIONS:
        return BOOK_ABBREVIATIONS[book_key]
    if book in BOOK_ABBREVIATIONS:
        return BOOK_ABBREVIATIONS[book]
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


def parse_reference_input(text: str):
    """
    사용자가 입력한 레퍼런스(예: '마 10:5', '마10장5절', 'Matthew 10:5')를 파싱한다.
    반환: {"book": str, "chapter": int, "verse": int, "verse_end": Optional[int]} 또는 None
    """
    normalized = normalize_korean(text or "").strip()
    if not normalized:
        return None
    match = REFERENCE_INPUT_PATTERN_RANGE.match(normalized)
    if not match:
        return None
    book_raw, chapter_str, verse_str, verse_end_str = match.groups()
    book = canonical_book_name(book_raw)
    if not book:
        return None
    chapter = int(chapter_str)
    verse = int(verse_str)
    verse_end = int(verse_end_str) if verse_end_str else None
    return {"book": book, "chapter": chapter, "verse": verse, "verse_end": verse_end}


def _candidate_source_values(book: str):
    book = canonical_book_name(book)
    candidates = []
    if book:
        candidates.append(book)
        english = KOREAN_TO_ENGLISH_BOOK.get(book)
        if english:
            candidates.append(english)
    # 중복 제거하면서 순서 유지
    seen = set()
    unique = []
    for item in candidates:
        if item and item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def get_exact_verse_entry(reference_input: str):
    """입력 레퍼런스가 주어졌을 때, 해당 구절(또는 해당 구절이 포함된 문서)을 정확히 찾아 반환."""
    if not bible_collection:
        return None
    parsed = parse_reference_input(reference_input)
    if not parsed:
        return None

    book = parsed["book"]
    chapter = parsed["chapter"]
    verse = parsed["verse"]
    verse_end = parsed.get("verse_end")
    target_label = f"{book} {chapter}:{verse}"
    target_key = normalize_reference(target_label)
    target_range_key = (
        normalize_reference(f"{book} {chapter}:{verse}-{verse_end}") if verse_end else None
    )

    ensure_verse_lookup_index()
    if target_key in VERSE_LOOKUP_INDEX:
        return VERSE_LOOKUP_INDEX[target_key]
    if target_range_key and target_range_key in VERSE_LOOKUP_INDEX:
        return VERSE_LOOKUP_INDEX[target_range_key]

    def _doc_contains_target(doc: str) -> bool:
        doc_norm = normalize_korean(doc or "")
        doc_compact = re.sub(r"\s+", "", doc_norm)
        # '10:5'만으로는 책을 구분할 수 없어 오탐이 생기므로, 책까지 포함된 마커만 사용한다.
        markers = []
        abbrs = FULL_BOOK_TO_ABBREVIATIONS.get(book, [])
        for abbr in abbrs:
            markers.append(f"{abbr}{chapter}:{verse}")
            markers.append(f"{abbr}{chapter}장{verse}절")
        markers.append(re.sub(r"\s+", "", f"{book} {chapter}:{verse}"))
        return any(m and m in doc_compact for m in markers)

    def _match_in_docs(docs, metas):
        for doc, meta in zip(docs or [], metas or []):
            label = build_reference_label(meta or {}, doc or "")
            if normalize_reference(label) == target_key:
                return {"text": doc, "metadata": meta or {}}
        return None

    # 1) source(book) 필터로 우선 탐색
    for source_value in _candidate_source_values(book):
        try:
            for doc, meta in iter_collection_documents(
                where={"source": source_value},
                include=["documents", "metadatas"],
                batch_size=2000,
            ):
                label = build_reference_label(meta or {}, doc or "")
                if normalize_reference(label) == target_key:
                    return {"text": doc, "metadata": meta or {}}
                if _doc_contains_target(doc):
                    extracted = extract_exact_verse_text(book, chapter, verse, doc) or doc
                    meta = dict(meta or {})
                    meta["_reference_override"] = target_label
                    return {"text": extracted, "metadata": meta}
        except Exception:
            continue

    # 2) 임베딩 기반 검색 후 (정확 레이블 매칭 → 본문 마커 매칭) 순으로 폴백
    try:
        embedding = embedding_model.encode(f"{target_label} 성경 구절").tolist()
        results = bible_collection.query(
            query_embeddings=[embedding],
            n_results=200,
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0] or []
        hit = _match_in_docs(docs, metas)
        if hit:
            return hit
        # 레이블이 정확히 없더라도, chunk 내부에 '마10:5' 같은 마커가 있으면 그 문서를 반환
        best = None
        best_dist = None
        for doc, meta, dist in zip(docs, metas, dists):
            if _doc_contains_target(doc):
                if best is None or (isinstance(dist, (int, float)) and dist < best_dist):
                    extracted = extract_exact_verse_text(book, chapter, verse, doc) or doc
                    meta = dict(meta or {})
                    meta["_reference_override"] = target_label
                    best = {"text": extracted, "metadata": meta}
                    best_dist = dist
        if best:
            return best
    except Exception as exc:
        print(f"⚠️ 레퍼런스 직접 검색 실패 ({reference_input}): {exc}")

    return None


def contains_phrase(query: str, document: str) -> bool:
    query = normalize_korean(query or "").strip()
    document = normalize_korean(document or "")
    if not query or len(query) < 2:
        return False
    query_compact = re.sub(r"\s+", "", query)
    doc_compact = re.sub(r"\s+", "", document)
    return query_compact in doc_compact


KOREAN_STOPWORDS = {
    "자기", "내", "나", "너", "우리", "너희", "그", "그의", "그녀", "그들의",
    "이", "저", "것", "수", "때", "말", "일", "등",
    "을", "를", "이", "가", "은", "는", "에", "의", "과", "와", "로", "으로",
}


def greedy_terms(query: str):
    """
    구절/문구 검색을 위해 질의에서 핵심 단어를 추출한다(간단 휴리스틱).
    예: '자기 십자가를' -> ['십자가']
    """
    normalized = normalize_korean(query or "").strip().lower()
    if not normalized:
        return []
    terms = []
    for token in re.findall(r"[가-힣]{2,}|[a-z]{2,}", normalized):
        token = token.strip()
        if token in KOREAN_STOPWORDS:
            continue
        if len(token) < 2:
            continue
        terms.append(token)
    seen = set()
    unique = []
    for t in terms:
        if t not in seen:
            unique.append(t)
            seen.add(t)
    return unique[:6]


def greedy_match_count(terms, document: str) -> int:
    if not terms or not document:
        return 0
    doc_norm = normalize_korean(document).lower()
    doc_compact = re.sub(r"\s+", "", doc_norm)
    count = 0
    for term in terms:
        term_compact = re.sub(r"\s+", "", term)
        if term_compact and term_compact in doc_compact:
            count += 1
    return count


def extract_exact_verse_text(book: str, chapter: int, verse: int, document: str) -> str | None:
    """
    chunk 문서에 여러 절이 포함된 경우(예: 마10:4 ... \\n마10:5 ...),
    요청한 특정 절만 본문으로 잘라낸다.
    """
    if not document:
        return None
    doc_norm = normalize_korean(document)
    abbrs = FULL_BOOK_TO_ABBREVIATIONS.get(book, [])
    if not abbrs:
        return None

    best = None
    best_pos = None
    for abbr in abbrs:
        # 시작 마커: '마10:5' 또는 '마 10:5'
        start_pattern = re.compile(
            rf'({re.escape(abbr)})\s*{chapter}\s*:\s*{verse}\s*',
            re.MULTILINE,
        )
        start_match = start_pattern.search(doc_norm)
        if not start_match:
            continue

        start_idx = start_match.end()
        # 다음 절 마커(대개 같은 책 약어로 시작하지만, 안전하게 한글약어+장:절 패턴으로 종료)
        next_marker = re.compile(r'\n?\s*[가-힣]{1,5}\s*\d+\s*:\s*\d+\s*', re.MULTILINE)
        next_match = next_marker.search(doc_norm, start_idx)
        end_idx = next_match.start() if next_match else len(doc_norm)
        body = doc_norm[start_idx:end_idx].strip()
        candidate = f"{abbr}{chapter}:{verse} {body}".strip()

        if best is None or (start_match.start() < best_pos):
            best = candidate
            best_pos = start_match.start()

    return best


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

    if (not book or not chapter_verse) and document:
        normalized_doc = normalize_korean(document or "")
        doc_match = DOC_REFERENCE_PATTERN.search(normalized_doc[:80])
        if doc_match:
            doc_book_raw, doc_chapter = doc_match.groups()
            doc_book = canonical_book_name(doc_book_raw)
            if not book:
                book = doc_book
            if not chapter_verse:
                chapter_verse = doc_chapter
        elif (match := DOC_REFERENCE_PATTERN_JANG.search(normalized_doc[:80])):
            doc_book_raw, chapter, verse = match.groups()
            doc_book = canonical_book_name(doc_book_raw)
            if not book:
                book = doc_book
            if not chapter_verse:
                chapter_verse = f"{chapter}:{verse}"
        if not chapter_verse:
            detected = extract_chapter_verse(document or "")
            if detected:
                chapter_verse = detected

    if book and chapter_verse:
        return f"{book} {chapter_verse}"
    if book:
        return book
    if chapter_verse:
        return chapter_verse
    return "알 수 없는 구절"


def build_reference_index():
    """테마 대표 구절을 빠르게 가져올 수 있도록 메모리에 적재."""
    global REFERENCE_INDEX_LOADED, VERSE_LOOKUP_INDEX_LOADED
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
    found = 0

    try:
        iterator = iter_collection_documents(include=["documents", "metadatas"])
        for doc, meta in iterator:
            reference = build_reference_label(meta, doc)
            normalized = normalize_reference(reference)
            if normalized and normalized not in VERSE_LOOKUP_INDEX:
                VERSE_LOOKUP_INDEX[normalized] = {
                    "text": doc,
                    "metadata": meta,
                }
            if normalized in target_refs and normalized not in REFERENCE_INDEX:
                REFERENCE_INDEX[normalized] = {
                    "text": doc,
                    "metadata": meta,
                }
                found += 1
    except Exception as e:
        print(f"⚠️ 대표 구절 인덱스 로딩 실패: {e}")
        return

    missing_keys = [key for key in target_refs if key not in REFERENCE_INDEX]
    if missing_keys:
        print(f"   🔎 인덱스 미포함 대표 구절 {len(missing_keys)}개 추가 탐색")
        for key in missing_keys:
            original_ref = target_refs[key]
            entry = lookup_reference_with_query(original_ref)
            if not entry:
                entry = lookup_reference_by_book(original_ref)
            if entry:
                REFERENCE_INDEX[key] = entry
            else:
                print(f"     ⚠️ 초기 로딩에서 대표 구절 미발견: {original_ref}")

    REFERENCE_INDEX_LOADED = True
    VERSE_LOOKUP_INDEX_LOADED = True
    print(f"✅ 대표 구절 인덱스 준비 완료: {len(REFERENCE_INDEX)}개 매핑")


def ensure_reference_index():
    if not REFERENCE_INDEX_LOADED and bible_collection:
        build_reference_index()


def build_verse_lookup_index():
    """레퍼런스(책+장:절) → 문서/메타데이터 전체 인덱스(직접 구절 검색용)."""
    global VERSE_LOOKUP_INDEX_LOADED
    if VERSE_LOOKUP_INDEX_LOADED or not bible_collection:
        VERSE_LOOKUP_INDEX_LOADED = True
        return
    print("🔄 레퍼런스 전체 인덱스 로딩 중...")
    try:
        for doc, meta in iter_collection_documents(include=["documents", "metadatas"]):
            reference = build_reference_label(meta or {}, doc or "")
            key = normalize_reference(reference)
            if key and key not in VERSE_LOOKUP_INDEX:
                VERSE_LOOKUP_INDEX[key] = {"text": doc, "metadata": meta or {}}
    except Exception as e:
        print(f"⚠️ 레퍼런스 전체 인덱스 로딩 실패: {e}")
        return
    VERSE_LOOKUP_INDEX_LOADED = True
    print(f"✅ 레퍼런스 전체 인덱스 준비 완료: {len(VERSE_LOOKUP_INDEX)}개")


def ensure_verse_lookup_index():
    if not VERSE_LOOKUP_INDEX_LOADED and bible_collection:
        build_verse_lookup_index()


def lookup_reference_with_query(reference_label: str):
    """Missing curated 구절을 직접 검색해서 찾아온다."""
    if not bible_collection or not reference_label:
        return None
    target_book, _ = split_reference(reference_label)
    try:
        query_text = f"{reference_label} 성경 구절의 본문"
        embedding = embedding_model.encode(query_text).tolist()
        results = bible_collection.query(
            query_embeddings=[embedding],
            n_results=5,
            include=["documents", "metadatas"],
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        for doc, meta in zip(docs, metas):
            label = build_reference_label(meta, doc)
            if normalize_reference(label) == normalize_reference(reference_label):
                return {"text": doc, "metadata": meta}
        if target_book:
            for doc, meta in zip(docs, metas):
                candidate_label = build_reference_label(meta, doc)
                candidate_book, _ = split_reference(candidate_label)
                if candidate_book == target_book:
                    return {"text": doc, "metadata": meta}
    except Exception as exc:
        print(f"⚠️ 대표 구절 직접 조회 실패 ({reference_label}): {exc}")
    return None


def lookup_reference_by_book(reference_label: str):
    """같은 책에 속한 metadata를 훑어 해당 장/절을 찾는다."""
    if not bible_collection or not reference_label:
        return None
    book, _ = split_reference(reference_label)
    if not book:
        return None

    try:
        for doc, meta in iter_collection_documents(
            where={"source": book},
            include=["documents", "metadatas"],
            batch_size=2000,
        ):
            label = build_reference_label(meta, doc)
            if normalize_reference(label) == normalize_reference(reference_label):
                return {"text": doc, "metadata": meta}
    except Exception as exc:
        print(f"⚠️ 대표 구절 책 기반 조회 실패 ({reference_label}): {exc}")
        return None
    return None


def get_or_create_curated_entry(normalized_key: str, reference_label: str):
    if not normalized_key:
        return None
    cached = REFERENCE_INDEX.get(normalized_key)
    if cached:
        return cached
    exact = get_exact_verse_entry(reference_label)
    if exact:
        REFERENCE_INDEX[normalized_key] = exact
        return exact
    fetched = lookup_reference_with_query(reference_label)
    if fetched:
        REFERENCE_INDEX[normalized_key] = fetched
        return fetched
    book_hit = lookup_reference_by_book(reference_label)
    if book_hit:
        REFERENCE_INDEX[normalized_key] = book_hit
        return book_hit
    return None


ensure_reference_index()
ensure_verse_lookup_index()

mailboxes = {}
postcards = {}


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
    key_terms = greedy_terms(keyword)
    term_hint = f" 핵심어: {', '.join(key_terms)}." if key_terms else ""
    expanded = (
        f"query: {keyword}. "
        f"상황과 감정: {contextual_summary}.{term_hint} "
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
    mailboxes[mailbox_id] = {
        'id': mailbox_id,
        'name': name,
        'nickname': name,
        'prayer_topic': prayer_topic,
        'url': f'/mailbox/{mailbox_id}',
        'created_at': datetime.now().isoformat(),
        'is_opened': False
    }
    postcards[mailbox_id] = []
    
    return jsonify({
        'mailbox_id': mailbox_id,
        'url': f'/mailbox/{mailbox_id}'
    })

@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """semantic 우선 + popularity + 테마 대표 구절 전부 상단 주입"""
    if not bible_collection:
        return jsonify({'error': 'ChromaDB 컬렉션이 로드되지 않았습니다'}), 500
    
    try:
        data = request.json or {}
        query = (data.get('query') or data.get('keyword') or '사랑').strip()
        print(f"\n🔍 검색 입력: '{query}'")

        ensure_reference_index()

        # 0) 레퍼런스 직접 입력(예: "마 10:5")이면 해당 구절을 최우선 반환
        parsed_reference = parse_reference_input(query)
        exact_hit = get_exact_verse_entry(query)

        curated_reference_set = set()
        theme_injected = []
        phrase_query = query

        if exact_hit:
            meta = exact_hit.get("metadata") or {}
            doc = exact_hit.get("text", "")
            popularity = meta.get("popularity")
            if not isinstance(popularity, (int, float)):
                popularity = get_popularity_score(meta.get("source", ""), doc)
                meta["popularity"] = popularity
            if parsed_reference:
                reference = f"{parsed_reference['book']} {parsed_reference['chapter']}:{parsed_reference['verse']}"
            else:
                reference = meta.get("_reference_override") or build_reference_label(meta, doc)

            curated_reference_set.add(normalize_reference(reference))
            theme_injected.append({
                "text": doc,
                "reference": reference,
                "semantic_score": None,
                "popularity": popularity,
                "final_score": 2.0,
                "is_curated": False,
                "injected": True,
                "priority": "exact_reference",
            })
            query_text = f"query: {doc}. 이 구절과 유사한 위로/격려/도전 구절을 찾는다."
            phrase_query = None
            print(f"   🎯 레퍼런스 직접 매칭: {reference}")
        else:
            if parsed_reference:
                normalized_label = f"{parsed_reference['book']} {parsed_reference['chapter']}:{parsed_reference['verse']}"
                print(f"   ⚠️ 레퍼런스 형식 감지되었지만 미발견: {normalized_label}")
            # 1) 쿼리를 주제+상황으로 확장
            query_text, curated_refs = build_contextual_query(query)

            # ⭐ 2) THEME 대표 구절 전부 먼저 확보 (중복 제거)
            curated_keys_order = []
            for ref in curated_refs:
                key = normalize_reference(ref)
                if key and key not in curated_reference_set:
                    curated_reference_set.add(key)
                    curated_keys_order.append((key, ref))

            print(f"   🎯 매칭된 테마 규칙: {len(curated_keys_order)}개 대표 구절")

            # 대표 구절들을 먼저 모두 확보 (캐시 또는 DB에서)
            for key, original_label in curated_keys_order:
                cached = get_or_create_curated_entry(key, original_label)
                if not cached:
                    print(f"     ⚠️ 대표 구절 미발견: {original_label}")
                    continue

                meta = cached.get("metadata") or {}
                doc = cached.get("text", "")
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
                    "priority": "theme_top"
                })

            print(f"   ✅ 테마 대표 구절 {len(theme_injected)}개 확보 완료")

        # 3) 쿼리 임베딩 및 벡터 검색 (대표 구절 제외하고 일반 검색)
        query_embedding = embedding_model.encode(query_text).tolist()
        print(f"   임베딩 생성 완료: {len(query_embedding)}차원")
        
        # 구절/문구 검색은 recall이 중요하므로 조금 더 많이 가져온 뒤 rerank
        expanded_terms = greedy_terms(query) if not exact_hit else []
        n_results = 200 if (not exact_hit and (len(query) >= 6 or " " in query or expanded_terms)) else 40

        raw_results = bible_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        print(f"✅ 1차 벡터 검색 완료: {len(raw_results['documents'][0])}개 결과")
        
        # 4) 일반 검색 결과 rerank (테마 대표 구절 제외)
        docs = raw_results["documents"][0]
        metas = raw_results["metadatas"][0]
        dists = raw_results["distances"][0]
        
        reranked_general = []
        
        for doc, meta, dist in zip(docs, metas, dists):
            reference = build_reference_label(meta, doc)
            normalized_ref = normalize_reference(reference)
            
            # 이미 테마 대표 구절이면 스킵
            if normalized_ref in curated_reference_set:
                continue
                
            semantic_score = 1 - dist
            popularity = meta.get("popularity")
            if not isinstance(popularity, (int, float)):
                popularity = get_popularity_score(meta.get("source", ""), doc)
                meta["popularity"] = popularity
            pop_norm = popularity / 100.0
            phrase_bonus = 0.15 if phrase_query and contains_phrase(phrase_query, doc) else 0.0
            greedy_hits = greedy_match_count(expanded_terms, doc) if expanded_terms else 0
            greedy_bonus = min(0.18, greedy_hits * 0.06)
            final_score = semantic_score * 0.6 + pop_norm * 0.4 + phrase_bonus + greedy_bonus
            
            reranked_general.append({
                "text": doc,
                "reference": reference,
                "semantic_score": round(semantic_score, 4),
                "popularity": popularity,
                "final_score": round(final_score, 4),
                "is_curated": False,
                "priority": "general"
            })
        
        # 5) 최종 결과 조합: [테마 대표 구절 전부] + [일반 상위 결과]
        reranked_general.sort(key=lambda x: x["final_score"], reverse=True)
        remaining_slots = max(0, 5 - len(theme_injected))
        final_results = theme_injected + reranked_general[:remaining_slots]
        if len(final_results) < 5:
            extra_needed = 5 - len(final_results)
            final_results.extend(reranked_general[remaining_slots:remaining_slots + extra_needed])
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
        return jsonify({'error': 'Mailbox not found'}), 404
    
    postcard = {
        'id': str(uuid.uuid4()),
        'verse_reference': data.get('verse_reference'),
        'verse_text': data.get('verse_text'),
        'message': data.get('message', ''),
        'created_at': datetime.now().isoformat()
    }
    
    postcards[mailbox_id].append(postcard)
    
    return jsonify({'success': True, 'postcard_id': postcard['id']})


@app.route('/mailbox/<mailbox_id>')
def mailbox(mailbox_id):
    if mailbox_id not in mailboxes:
        return "우체통을 찾을 수 없습니다", 404
    
    mailbox_data = mailboxes[mailbox_id]
    
    if datetime.now() >= datetime(2026, 1, 1) or mailbox_data['is_opened']:
        mailbox_data['is_opened'] = True
        return render_template('mailbox.html', 
                             mailbox=mailbox_data, 
                             postcards=postcards.get(mailbox_id, []))
    else:
        return render_template('mailbox_locked.html', mailbox=mailbox_data)


@app.route('/send/<mailbox_id>')
def send_page(mailbox_id):
    if mailbox_id not in mailboxes:
        return "우체통을 찾을 수 없습니다", 404
    
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
