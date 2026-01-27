# 추천 알고리즘 관련 로직
# 성경 레퍼먼스 파싱 로직
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

# 핵심 추천 알고리즘
@app.route('/api/recommend-verses', methods=['POST'])
def recommend_verses():
    """레퍼런스 직접 매칭 → 문구 검색(greedy+semantic) 추천."""
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or data.get('keyword') or '').strip()
    page = 0
    try:
        page = max(0, int(data.get('page', 0)))
    except Exception:
        page = 0
    if not query:
        return jsonify({'error': '검색어가 필요합니다'}), 400
    if not bible_collection:
        return recommend_verses_supabase(query, page)

    try:
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
        page_size = 3
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

# 3. 인덱스 생성 및 쿼리
REFERENCE_INDEX = {}

def ensure_reference_index():
    if not REFERENCE_INDEX_LOADED and bible_collection:
        build_reference_index()

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
