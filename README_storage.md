
# Storage pack (drop-in)

KAM SKOPÍROVAŤ:
- `storage.py`, `init_storage.py`, `secure_files.py` do koreňa tvojej app (rovnako ako app.py).
- Otvor `app.py` a urob zmeny podľa `sample_app_patch.txt` (3 riadky importov/registrácia).

ENV:
- `APP_DATA_DIR` (default `./data`) – program si priečinok vytvorí sám.

MIGRÁCIA:
- Spusti jednorazovo: `python migrate_storage.py` (ak máš staré súbory v `static/uploads`).

Hotovo. Žiadne externé knižnice, len štandardná knižnica Python + Flask/Werkzeug už máš.
