from __future__ import annotations

from pathlib import Path
from typing import Optional

from .api import API
from ..domain.constants import WEBVIEW_STORAGE_DIR
from ..ui import INDEX_HTML_URL

WINDOW_TITLE = "Симулятор кейсов"
WINDOW_WIDTH = 1460
WINDOW_HEIGHT = 920


def create_main_window(api: Optional[API] = None):
    import webview

    return webview.create_window(
        WINDOW_TITLE,
        url=INDEX_HTML_URL,
        js_api=api or API(),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
    )


def main() -> None:
    import webview

    Path(WEBVIEW_STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    create_main_window()
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=str(WEBVIEW_STORAGE_DIR),
    )
