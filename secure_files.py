
"""
Blueprint for secure file serving.

Usage:
    from secure_files import files_bp
    app.register_blueprint(files_bp, url_prefix="/files")

Auth:
    Replace `current_user_has_access(folder, filename)` with your logic,
    e.g. check login session, roles, ownership, etc.
"""

import os
from flask import Blueprint, abort, send_file, request
from storage import build_file_path, sanitize_filename

files_bp = Blueprint("files", __name__)

def current_user_has_access(folder: str, filename: str) -> bool:
    # TODO: implement your authorization logic (role/ownership)
    # For now, require a dummy header/token just as placeholder
    # Replace with real session check (e.g. flask-login current_user).
    token = request.headers.get("X-Debug-Token")
    return bool(token)  # <-- change to real check!

@files_bp.route("/<folder>/<path:filename>", methods=["GET"])
def serve_secure_file(folder: str, filename: str):
    fname = sanitize_filename(filename)
    if not current_user_has_access(folder, fname):
        abort(403)
    full_path = build_file_path(folder, fname)
    if not os.path.isfile(full_path):
        abort(404)
    # as_attachment=False -> inline display where possible
    return send_file(full_path, as_attachment=False)
