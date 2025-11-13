
"""
Drop-in storage helper for Flask apps (no extra deps).

- Uses APP_DATA_DIR (default: ./data)
- Auto-creates base dir and subfolders on demand
- Safe path join & filename sanitization
- Simple helpers for uploads and JSON files
"""

import os
import re
import json
from datetime import datetime
from typing import Iterable, Optional

# -------- Core config --------

def get_base_dir() -> str:
    base = os.getenv("APP_DATA_DIR", "./data").strip()
    if not base:
        base = "./data"
    os.makedirs(base, exist_ok=True)
    return base

# Allowed characters for filenames; we strip/replace the rest
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")

def sanitize_filename(name: str) -> str:
    if not name:
        name = "unnamed"
    # Replace path separators just in case
    name = name.replace("\\", "_").replace("/", "_")
    name = _SANITIZE_RE.sub("_", name)
    # Prevent hidden files like ".env"
    if name.startswith("."):
        name = name.lstrip(".")
        if not name:
            name = "file"
    return name

def safe_join(*parts: str) -> str:
    # Joined under base dir only; prevents traversal
    base = os.path.abspath(get_base_dir())
    path = os.path.abspath(os.path.join(base, *[sanitize_filename(p) for p in parts]))
    if not path.startswith(base + os.sep) and path != base:
        raise ValueError("Illegal path traversal")
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    return path

# -------- Folders & structure --------

def ensure_structure(subdirs: Iterable[str]) -> None:
    base = get_base_dir()
    for s in subdirs:
        d = safe_join(s)
        os.makedirs(d, exist_ok=True)

# -------- High-level helpers --------

def save_bytes(data: bytes, *path_parts: str) -> str:
    path = safe_join(*path_parts)
    with open(path, "wb") as f:
        f.write(data)
    return path

def save_text(text: str, *path_parts: str, encoding="utf-8") -> str:
    path = safe_join(*path_parts)
    with open(path, "w", encoding=encoding) as f:
        f.write(text)
    return path

def save_upload(file_storage, folder: str, filename: Optional[str] = None) -> str:
    """
    file_storage: Werkzeug FileStorage (request.files['...'])
    folder: logical subfolder (e.g., "orders", "invoices", "uploads")
    filename: optional target filename; fallback to uploaded filename
    """
    if file_storage is None:
        raise ValueError("No file provided")
    raw_name = filename or getattr(file_storage, "filename", None) or "upload"
    name = sanitize_filename(raw_name)
    # prefix with timestamp to avoid collisions
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    final = f"{stamp}_{name}"
    path = safe_join(folder, final)
    file_storage.save(path)  # Werkzeug handles stream saving
    return path

def write_json(obj, *path_parts: str, indent=2) -> str:
    path = safe_join(*path_parts)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    return path

def read_json(*path_parts: str):
    path = safe_join(*path_parts)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def list_files(folder: str):
    root = safe_join(folder)
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            out.append(name)
    return out

# -------- Secure file serving helpers --------

def build_file_path(folder: str, filename: str) -> str:
    # Compose path safely for serving
    return safe_join(folder, filename)

