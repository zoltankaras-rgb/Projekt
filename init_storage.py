
"""
Call `init_storage()` at app startup to create required folders automatically.
"""

from storage import ensure_structure

REQUIRED_FOLDERS = [
    "orders",
    "invoices",
    "uploads",
    "b2c_meta",
    "exports",
    "imports",
    "logs",
]

def init_storage():
    ensure_structure(REQUIRED_FOLDERS)
