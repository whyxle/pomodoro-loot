from __future__ import annotations

from pathlib import Path

UI_DIR = Path(__file__).resolve().with_name("web")
INDEX_HTML_PATH = UI_DIR / "index.html"
INDEX_HTML_URL = INDEX_HTML_PATH.as_uri()

# Backward-compatible access for old imports; the application window loads
# the file URL so linked CSS and JS are resolved by the webview.
HTML = INDEX_HTML_PATH.read_text(encoding="utf-8")
