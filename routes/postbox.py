from flask import Blueprint, jsonify

message_bp = Blueprint("postbox", __name__)

@message_bp.route("/", methods=["POST"])
def create_message():
    return jsonify({"result": "ok"})
