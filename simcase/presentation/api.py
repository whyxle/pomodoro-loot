from __future__ import annotations

from typing import Optional

from ..application.simulator import CaseSimulator
from .dialogs import WebviewFileDialogs


class API:
    def __init__(
        self,
        simulator: Optional[CaseSimulator] = None,
        dialogs: Optional[WebviewFileDialogs] = None,
    ):
        # pywebview recursively traverses public attributes of js_api objects.
        # Internal collaborators must stay private, otherwise API generation
        # walks into complex objects like Path and breaks method exposure.
        self._store = simulator or CaseSimulator()
        self._dialogs = dialogs or WebviewFileDialogs()

    def get_state(self):
        return {"ok": True, "state": self._store.state()}

    def open_case(self, times=1):
        return self._store.open_case(times)

    def start_focus_session(self, payload):
        return self._store.start_focus_session(payload or {})

    def cancel_focus_session(self, session_id):
        return self._store.cancel_focus_session(session_id)

    def complete_focus_session(self, session_id):
        return self._store.complete_focus_session(session_id)

    def export_preset(self):
        return self._store.export_preset()

    def import_preset(self, payload):
        return self._store.import_preset(payload)

    def add_rarity(self, rarity):
        return self._store.add_rarity(rarity)

    def update_rarity(self, rarity_id, payload):
        return self._store.update_rarity(rarity_id, payload)

    def update_rarities_bulk(self, rows):
        return self._store.update_rarities_bulk(rows)

    def normalize_rarity_ranges(self):
        return self._store.normalize_rarity_ranges()

    def delete_rarity(self, rarity_id):
        return self._store.delete_rarity(rarity_id)

    def add_item(self, payload):
        return self._store.add_item(payload)

    def update_item(self, item_id, payload):
        return self._store.update_item(item_id, payload)

    def delete_item(self, item_id):
        return self._store.delete_item(item_id)

    def update_items_bulk(self, rows):
        return self._store.update_items_bulk(rows)

    def adjust_inventory(self, item_id, delta):
        return self._store.adjust_inventory(item_id, int(delta))

    def clear_inventory(self):
        return self._store.clear_inventory()

    def purchase_item(self, item_id, currency_item_id, quantity=1):
        return self._store.purchase_item(item_id, currency_item_id, int(quantity))

    def set_filter_rarity(self, rarity_id, value):
        return self._store.set_filter_rarity(rarity_id, bool(value))

    def set_filter_item(self, item_id, value):
        return self._store.set_filter_item(item_id, bool(value))

    def update_settings(self, payload):
        return self._store.update_settings(payload)

    def clear_history(self):
        return self._store.clear_history()

    def clear_collection(self):
        return self._store.clear_collection()

    def reset_stats(self):
        return self._store.reset_stats()

    def play_rarity_sound(self, rarity_id):
        return self._store.play_rarity_sound(rarity_id)

    def pick_image_file(self):
        return self._dialogs.pick_image_file()

    def pick_sound_file(self):
        return self._dialogs.pick_sound_file()
