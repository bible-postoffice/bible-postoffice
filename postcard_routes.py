from datetime import datetime
import uuid
from flask import Blueprint, jsonify, render_template, request


def create_postcard_blueprint(
    postboxes,
    postcards,
    fetch_postbox_supabase,
    fetch_postcards_supabase,
    store_postbox_supabase,
    store_postcard_supabase,
):
    bp = Blueprint("postcard_routes", __name__)

    def ensure_postbox_loaded(postbox_id):
        if postbox_id not in postboxes:
            loaded = fetch_postbox_supabase(postbox_id)
            if not loaded:
                return None
            postboxes[postbox_id] = loaded
            postcards[postbox_id] = fetch_postcards_supabase(postbox_id)
        return postboxes[postbox_id]

    def ensure_postbox_exists(postbox_id):
        if ensure_postbox_loaded(postbox_id):
            return postboxes[postbox_id]

        # Supabase에도 없으면 최소 정보로 생성 후 진행
        base_url = request.url_root.rstrip("/")
        postbox_path = f"/postboxes/{postbox_id}"
        fallback = {
            "id": postbox_id,
            "name": "우체통",
            "nickname": "우체통",
            "prayer_topic": "",
            "url": postbox_path,
            "full_url": f"{base_url}{postbox_path}",
            "created_at": datetime.now().isoformat(),
            "is_opened": False,
        }
        postboxes[postbox_id] = fallback
        postcards.setdefault(postbox_id, [])
        store_postbox_supabase(fallback)
        return fallback

    @bp.route("/api/send-postcard", methods=["POST"])
    def send_postcard():
        data = request.json
        postbox_id = data.get("postbox_id")

        if postbox_id not in postboxes:
            loaded = fetch_postbox_supabase(postbox_id)
            if not loaded:
                base_url = request.url_root.rstrip("/")
                postbox_path = f"/postboxes/{postbox_id}"
                fallback = {
                    "id": postbox_id,
                    "name": "우체통",
                    "nickname": "우체통",
                    "prayer_topic": "",
                    "url": postbox_path,
                    "created_at": datetime.now().isoformat(),
                    "is_opened": False,
                }
                postboxes[postbox_id] = fallback
                postcards[postbox_id] = []
                store_postbox_supabase(fallback)
            else:
                postboxes[postbox_id] = loaded
                postcards[postbox_id] = fetch_postcards_supabase(postbox_id)

        postcard = {
            "id": str(uuid.uuid4()),
            "template_id": data.get("template_id") or 1,
            "template_type": data.get("template_type") if data.get("template_type") is not None else 0,
            "template_name": data.get("template_name") or "",
            "is_anonymous": bool(data.get("is_anonymous")),
            "verse_reference": data.get("verse_reference"),
            "verse_text": data.get("verse_text"),
            "message": data.get("message", ""),
            "font_family": data.get("font_family") or "",
            "font_style": data.get("font_style") or "",
            "created_at": datetime.now().isoformat(),
        }

        postcards[postbox_id].append(postcard)
        store_postcard_supabase(postbox_id, postcard)

        return jsonify({"success": True, "postcard_id": postcard["id"]})

    @bp.route("/send/<postbox_id>")
    def send_page(postbox_id):
        if not ensure_postbox_loaded(postbox_id):
            return "우체통을 찾을 수 없습니다", 404

        return render_template("choose_template.html", postbox_id=postbox_id)

    @bp.route("/send/<postbox_id>/write")
    def send_page_write(postbox_id):
        ensure_postbox_exists(postbox_id)

        template_id = request.args.get("template_id")
        template_type = request.args.get("template_type")
        template_name = request.args.get("template_name")

        return render_template(
            "send_postcard.html",
            postbox_id=postbox_id,
            template_id=template_id,
            template_type=template_type,
            template_name=template_name,
        )

    @bp.route("/send/<postbox_id>/preview")
    def send_page_preview(postbox_id):
        ensure_postbox_exists(postbox_id)
        return render_template("preview_postcard.html", postbox_id=postbox_id)

    return bp
