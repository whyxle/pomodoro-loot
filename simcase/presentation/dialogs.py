from __future__ import annotations


class WebviewFileDialogs:
    image_file_types = ("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif)",)
    sound_file_types = ("Audio files (*.wav;*.mp3;*.ogg;*.flac)",)
    window_not_found_message = "Окно не найдено"

    def pick_image_file(self) -> dict:
        return self._pick_file(self.image_file_types)

    def pick_sound_file(self) -> dict:
        return self._pick_file(self.sound_file_types)

    def _pick_file(self, file_types: tuple[str, ...]) -> dict:
        try:
            import webview

            windows = webview.windows
            if not windows:
                return {"ok": False, "message": self.window_not_found_message}
            paths = windows[0].create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=file_types,
            )
            if not paths:
                return {"ok": True, "path": ""}
            return {"ok": True, "path": paths[0]}
        except Exception as err:
            return {"ok": False, "message": str(err), "path": ""}
