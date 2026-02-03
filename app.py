# app.py
from flask import Flask, render_template, request, jsonify, url_for, session, redirect, flash
import json
import re
import requests
import uuid
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
import os


from postcard_routes import create_postcard_blueprint

import config
from config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_KEY, THEME_CONTEXT_RULES, DEFAULT_CONTEXT_DESCRIPTION
from services.database import supabase, embedding_model, bible_collection, supabase_vec
from routes.postbox import postbox_bp



from popular_verses import (
    get_popularity_score,
    extract_chapter_verse,
    normalize_korean,
    BOOK_NAME_MAP,
)  # ⭐ 추가


app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# 세션 보안 설정
app.config.update(
    SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

app.register_blueprint(postbox_bp)


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




postboxes = {}
postcards = {}

# 템플릿 유형 (엽서 0 고정)
TEMPLATE_TYPE_POSTCARD = 0


def supabase_headers():
    """Supabase REST API 요청에 필요한 헤더 반환"""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }


def fetch_postbox_supabase(postbox_id: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postboxes"
    
    # UUID 형식(36자)이 아니면 url 컬럼으로 조회 (슬러그 지원)
    if len(postbox_id) != 36:
        params = {"url": f"eq.{postbox_id}", "limit": 1}
    else:
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
    """우편 ID로 엽서 1건을 가져온다 (Supabase → 메모리 캐시)."""
    # 1) Supabase 우선 조회 (DB 수정 사항 즉시 반영)
    if SUPABASE_URL and SUPABASE_KEY:
        endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postcards"
        params = {"id": f"eq.{postcard_id}", "limit": 1}
        try:
            resp = requests.get(endpoint, headers=supabase_headers(), params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json() or []
                if data:
                    card = data[0]
                    # 캐시에도 반영해 일관성 유지
                    for plist in postcards.values():
                        for idx, cached in enumerate(plist):
                            if cached.get("id") == postcard_id:
                                plist[idx] = card
                                return card
                    return card
            else:
                print(f"⚠️ Supabase postcard fetch 실패 status={resp.status_code}, body={resp.text}")
        except Exception as exc:
            print(f"⚠️ Supabase postcard fetch 예외: {exc}")

    # 2) 메모리 캐시 fallback
    for plist in postcards.values():
        for card in plist:
            if card.get("id") == postcard_id:
                return card
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
    tpl_type = TEMPLATE_TYPE_POSTCARD
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
    sender_name = postcard.get("sender_name")
    if sender_name:
        payload["sender_name"] = sender_name
    if postcard.get("font_family"):
        payload["font_family"] = postcard.get("font_family")
    if postcard.get("font_style"):
        payload["font_style"] = postcard.get("font_style")
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=8)
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 400:
            fallback_payload = dict(payload)
            if "font_family" in resp.text or "font_style" in resp.text:
                fallback_payload.pop("font_family", None)
                fallback_payload.pop("font_style", None)
            if "sender_name" in resp.text:
                fallback_payload.pop("sender_name", None)
            if fallback_payload != payload:
                resp_retry = requests.post(endpoint, headers=headers, json=fallback_payload, timeout=8)
                if resp_retry.status_code in (200, 201):
                    print("ℹ️ Supabase가 일부 컬럼을 지원하지 않아 기본 필드로 저장했습니다.")
                    return resp_retry.json()
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


def fetch_user_id_by_email(email: str):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        res = supabase.table('bible_users').select("id").eq("email", email).execute()
        if res.data:
            return res.data[0]['id']
    except Exception:
        pass
    return None


# 카드 작성/미리보기/전송 관련 라우트는 별도 블루프린트로 분리
postcard_bp = create_postcard_blueprint(
    postboxes=postboxes,
    postcards=postcards,
    fetch_postbox_supabase=fetch_postbox_supabase,
    fetch_postcards_supabase=fetch_postcards_supabase,
    store_postbox_supabase=store_postbox_supabase,
    store_postcard_supabase=store_postcard_supabase,
    fetch_user_id_by_email=fetch_user_id_by_email,
)
app.register_blueprint(postcard_bp)



def fetch_template_meta(template_id: int):
    # TODO: Implement actual Supabase fetch if needed
    return None

@app.route('/view-postcard/<postcard_id>')
def view_postcard(postcard_id):
    card = fetch_postcard_by_id(postcard_id)
    if not card:
        return "엽서를 찾을 수 없습니다.", 404
    sender = card.get("sender_name") or "익명"
    verse_ref = card.get("verse_reference") or "말씀"
    verse_text = card.get("verse_text") or ""
    message = card.get("message") or ""
    font_family = card.get("font_family") or ""
    tpl_id_raw = card.get("template_id") or 1
    tpl_img = None
    tpl_type_raw = card.get("template_type")
    tpl_type = None
    try:
        tpl_type = int(tpl_type_raw) if tpl_type_raw is not None else None
    except Exception:
        tpl_type = None

    TEMPLATE_IMAGE_MAP = {
        0: {  # 엽서
            1: "images/postcards/postcard1.jpg",
            2: "images/postcards/postcard2.jpg",
            3: "images/postcards/postcard3.jpg",
            4: "images/postcards/postcard4.jpg",
            5: "images/postcards/postcard5.jpg",
            6: "images/postcards/postcard6.jpg",
        }
    }

    try:
        tpl_meta = fetch_template_meta(int(tpl_id_raw))
        if tpl_meta:
            tpl_img = tpl_meta.get("image_path")
            tpl_type = tpl_meta.get("template_type", tpl_type)
    except Exception:
        tpl_meta = None

    try:
        tpl_id_int = int(tpl_id_raw)
    except Exception:
        tpl_id_int = None

    # 템플릿 타입이 없거나 잘못되었으면 ID로 유추 (5 이상은 편지지로 취급)
    tpl_type = TEMPLATE_TYPE_POSTCARD

    template_image = tpl_img
    if not template_image:
        template_image = TEMPLATE_IMAGE_MAP.get(tpl_type, {}).get(tpl_id_int) or "images/postcards/postcard1.jpg"

    # 파일 시스템은 대소문자 구분이 있을 수 있으니 소문자로 정규화
    template_image = template_image.lstrip("/").lower()
    template_image_url = template_image
    if not (template_image_url.startswith("http://") or template_image_url.startswith("https://")):
        template_image_url = url_for('static', filename=template_image)

    # 1. 엽서가 속한 우체통 정보를 가져와서 앞뒤 엽서 ID를 찾음
    prev_id = None
    next_id = None
    total_count = 1
    current_index = 0
    postbox_url = None

    postbox_id = card.get("postbox_id")
    if postbox_id:
        all_cards = fetch_postcards_supabase(postbox_id)
        if all_cards:
            total_count = len(all_cards)
            # ID 기준 혹은 생성일 순으로 정렬되어 있다고 가정 (fetch_postcards_supabase에서 정렬함)
            card_ids = [c["id"] for c in all_cards]
            if postcard_id in card_ids:
                current_index = card_ids.index(postcard_id)
                if current_index > 0:
                    prev_id = card_ids[current_index - 1]
                if current_index < total_count - 1:
                    next_id = card_ids[current_index + 1]
        
        # 우체통 URL(slug) 조회
        pb = fetch_postbox_supabase(postbox_id)
        if pb:
            postbox_url = pb.get("url")

    # 2. URL 생성
    prev_url = url_for('view_postcard', postcard_id=prev_id) if prev_id else None
    next_url = url_for('view_postcard', postcard_id=next_id) if next_id else None
    list_url = url_for('postbox.view_postbox', url_path=postbox_url) if postbox_url else None

    return render_template(
        'postcard_view.html',
        postcard_id=postcard_id,
        sender=sender,
        verse_reference=verse_ref,
        verse_text=verse_text,
        message=message,
        font_family=font_family,
        template_id=tpl_id_raw,
        template_type=tpl_type,
        template_image=template_image,
        template_image_url=template_image_url,
        kakao_js_key=os.environ.get("KAKAO_JS_KEY", ""),
        # 내비게이션 데이터
        prev_url=prev_url,
        next_url=next_url,
        list_url=list_url,
        total_count=total_count,
        current_index=current_index
    )


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


def _parse_supabase_metadata(raw_meta):
    if not raw_meta:
        return {}
    if isinstance(raw_meta, dict):
        return raw_meta
    if isinstance(raw_meta, str):
        try:
            parsed = json.loads(raw_meta)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _extract_supabase_row(row: dict):
    if not isinstance(row, dict):
        return None
    meta = _parse_supabase_metadata(row.get("metadata"))
    doc = row.get("text") or row.get("content") or row.get("document") or row.get("verse_text")
    reference = row.get("reference") or row.get("verse_reference") or row.get("ref")
    distance = row.get("distance")
    similarity = row.get("similarity")
    if distance is None and similarity is not None:
        distance = 1 - similarity
    popularity = row.get("popularity")
    if popularity is None:
        popularity = meta.get("popularity", 0) if isinstance(meta, dict) else 0
    return {
        "doc": doc,
        "reference": reference,
        "meta": meta,
        "distance": distance,
        "popularity": popularity,
    }


def _supabase_vector_query(query_embedding, match_count=200):
    if not supabase_vec:
        return None, "SUPABASE_VEC_URL 또는 SUPABASE_VEC_KEY가 설정되지 않았습니다."
    rpc_candidates = [
        os.environ.get("SUPABASE_VEC_RPC"),
        "match_bible_verses",
        "match_bible",
        "match_verses",
        "match_documents",
    ]
    last_error = None
    for rpc_name in rpc_candidates:
        if not rpc_name:
            continue
        try:
            result = supabase_vec.rpc(
                rpc_name,
                {
                    "query_embedding": query_embedding,
                    "match_count": match_count,
                },
            ).execute()
            if result.data is not None:
                return result.data, None
        except Exception as exc:
            last_error = exc
    return None, last_error or "Supabase RPC 호출에 실패했습니다."


def recommend_verses_supabase(query: str, page: int):
    try:
        print(f"\n🔍 검색 쿼리(Supabase): '{query}'")
        query_text, _ = build_contextual_query(query)
        expanded_terms = greedy_terms(query)
        normalized_query = re.sub(r"\s+", "", normalize_korean(query or "").lower())

        query_embedding = embedding_model.encode(query_text).tolist()
        raw_rows, error = _supabase_vector_query(query_embedding, match_count=200)
        if raw_rows is None:
            return jsonify({"error": f"Supabase 검색 실패: {error}"}), 500

        scored = []
        for row in raw_rows:
            parsed = _extract_supabase_row(row)
            if not parsed:
                continue
            doc = parsed["doc"]
            if not doc:
                continue
            meta = parsed["meta"]
            reference = parsed["reference"] or build_reference_label(meta, doc)
            pop = parsed["popularity"] or 0
            dist = parsed["distance"]
            semantic = 1 - dist if dist is not None else 0
            greedy_hits = greedy_match_count(expanded_terms, doc)
            greedy_bonus = min(0.18, greedy_hits * 0.06)
            coverage = greedy_hits / max(1, len(expanded_terms)) if expanded_terms else 0
            phrase_bonus = coverage * 0.1
            if coverage >= 0.99:
                phrase_bonus += 0.08
            if normalized_query and normalized_query in re.sub(r"\s+", "", normalize_korean(doc or "").lower()):
                phrase_bonus += 0.06
            phrase_bonus = min(0.24, phrase_bonus)
            final_score = semantic * 0.6 + (pop / 100.0) * 0.4 + phrase_bonus + greedy_bonus
            scored.append((final_score, reference, doc, meta))

        scored.sort(key=lambda x: x[0], reverse=True)
        page_size = 3
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_slice = scored[start_idx:end_idx]
        total_pages = (len(scored) + page_size - 1) // page_size if scored else 0

        verses = []
        for score, reference, doc, meta in page_slice:
            verses.append(
                {
                    "reference": reference,
                    "text": doc,
                    "metadata": meta,
                    "score": score,
                }
            )

        has_more = end_idx < len(scored)
        return jsonify({
            "verses": verses,
            "has_more": has_more,
            "total_pages": total_pages,
            "page": page,
        })
    except Exception as e:
        print(f"❌ Supabase 검색 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"검색 실패: {str(e)}"}), 500



@app.route('/api/legacy/create-postbox', methods=['POST'])
def create_postbox():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    prayer_topic = data.get('prayer_topic', '')

    if not name:
        return jsonify({'error': 'Name is required'}), 400

    postbox_id = str(uuid.uuid4())[:8]
    base_url = request.url_root.rstrip('/')
    postbox_path = f'/postbox/{postbox_id}'
    original_url = f"{base_url}{postbox_path}"
    postboxes[postbox_id] = {
        'id': postbox_id,
        'name': name,
        'prayer_topic': prayer_topic,
        'url': postbox_path,
        'full_url': original_url,
        'created_at': datetime.now().isoformat(),
        'is_opened': False
    }
    postcards[postbox_id] = []

    short_url = store_generated_url(original_url=original_url, base_url=base_url)
    store_postbox_supabase(postboxes[postbox_id])
    response_payload = {
        'postbox_id': postbox_id,
        'url': postbox_path,
        'original_url': original_url
    }
    if short_url:
        response_payload['short_url'] = short_url
    return jsonify(response_payload)


# 호환성: 기존 /api/create-mailbox 엔드포인트를 /api/create-postbox로 포워딩
@app.route('/api/create-mailbox', methods=['POST'])
def create_mailbox_legacy():
    return create_postbox()


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

def open_all_postboxes():
    for postbox_id in postboxes:
        postboxes[postbox_id]['is_opened'] = True


# 추가 1: Supabase 인증 후 돌아올 콜백 경로
@app.route('/auth/callback')
def auth_callback():
    # 이 페이지는 단순히 index로 리다이렉트만 해주면 됩니다.
    # 그러면 index.html(hero.html)에 있는 JS가 토큰을 감지해 처리합니다.
    return redirect(url_for('index'))




@app.route('/api/debug/postbox/<id_or_slug>')
def debug_postbox(id_or_slug):
    if len(id_or_slug) != 36:
        params = {"url": f"eq.{id_or_slug}", "limit": 1}
    else:
        params = {"id": f"eq.{id_or_slug}", "limit": 1}
    endpoint = f"{SUPABASE_URL.rstrip('/')}/rest/v1/postboxes"
    try:
        resp = requests.get(endpoint, headers=supabase_headers(), params=params)
        return jsonify({
            "status": resp.status_code,
            "data": resp.json(),
            "params": params,
            "endpoint": endpoint
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/')
def index():
    # 0. 인증 프로세스 중에는 서버측 자동 리다이렉트 방지
    if request.args.get('auth') == '1':
        return render_template('index.html', 
                             supabase_url=os.getenv('SUPABASE_URL'),
                             supabase_key=os.getenv('SUPABASE_KEY'),
                             is_logged_in='user_email' in session)

    # 1. 로그인 세션 확인
    if 'user_email' in session:
        email = session['user_email']
        print(session)
        try:
            # 2. DB에서 사용자 정보 확인
            user_res = supabase.table('bible_users').select("id, flag").eq("email", email).execute()
            
            # 결과 데이터가 존재하는지 안전하게 체크
            if user_res and hasattr(user_res, 'data') and len(user_res.data) > 0:
                user_data = user_res.data[0]
                user_id = user_data['id']
                # flag가 True(우체통 있음)인지 확인
                has_postbox = user_data.get('flag', False)

                if has_postbox:
                    # 3. 우체통 URL 조회
                    pb_res = supabase.table('postboxes').select("url").eq("owner_id", user_id).execute()
                    if pb_res and pb_res.data:
                        # 블루프린트를 사용 중이라면 url_for 사용을 권장하지만, 
                        # 일단 기존 방식대로 리다이렉트 주소 구성
                        return redirect(f"/postbox/{pb_res.data[0]['url']}")
            
                    # 4. 우체통이 없거나 flag가 False면 생성 페이지로 이동
                    # 블루프린트 내부의 경로라면 'postbox.create_postbox_page' 형식이 될 수 있음
                    return redirect(url_for('postbox.create_postbox_action'))
            
        except Exception as e:
            print(f"❌ Index Route Error: {e}")
            # 에러 발생 시 세션을 유지한 채 메인 렌더링 (또는 로그아웃 처리)

    # 5. 비로그인 상태이거나 예외 상황 시 메인 페이지 렌더링
    return render_template(
        'index.html',   
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_ANON_KEY,
        is_logged_in=False
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')



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


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_manifest():
    return "", 204

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 Flask 서버 시작")
    
    # 환경 감지
    is_local = os.environ.get('RENDER') is None  # Render는 자동으로 RENDER 환경변수 설정
    host = '127.0.0.1' if is_local else '0.0.0.0'
    port = int(os.environ.get('PORT', 5001))
    debug = is_local
    
    print(f"📍 브라우저에서 접속: http://{host}:{port}")
    print(f"🔧 환경: {'로컬 개발' if is_local else 'Render 배포'}")
    print("="*50 + "\n")

    app.run(host=host, port=port, debug=debug)

