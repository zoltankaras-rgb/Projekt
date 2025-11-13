
"""
One-time migration: move files from static/uploads/** to APP_DATA_DIR subfolders.
Run once locally or on server.
"""
import os
import shutil
from storage import get_base_dir, sanitize_filename, safe_join

STATIC_UPLOADS = "static/uploads"

# Map from old subpaths to new folders (adjust if needed)
FOLDER_MAP = {
    "orders": "orders",
    "invoices": "invoices",
    "b2c": "b2c_meta",
    "exports": "exports",
    "imports": "imports",
    "": "uploads",  # default bucket
}

def migrate():
    if not os.path.isdir(STATIC_UPLOADS):
        print("No static/uploads found. Nothing to migrate.")
        return
    moved = 0
    for root, _, files in os.walk(STATIC_UPLOADS):
        rel = os.path.relpath(root, STATIC_UPLOADS)
        bucket = FOLDER_MAP.get(rel.split(os.sep)[0] if rel != "." else "", "uploads")
        for fn in files:
            src = os.path.join(root, fn)
            dst = safe_join(bucket, sanitize_filename(fn))
            shutil.move(src, dst)
            moved += 1
            print(f"MOVED: {src} -> {dst}")
    print(f"Done. Moved {moved} files.")
    # Keep an empty placeholder if you want to keep the folder
    os.makedirs(STATIC_UPLOADS, exist_ok=True)
    open(os.path.join(STATIC_UPLOADS, ".gitkeep"), "a").close()

if __name__ == "__main__":
    migrate()
