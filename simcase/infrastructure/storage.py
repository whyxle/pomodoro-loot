from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union


@dataclass
class SplitJsonStorage:
    base_path: Union[str, Path] = "case_simulator_data.json"
    base_dir: Path = field(init=False)
    rarities_path: Path = field(init=False)
    items_path: Path = field(init=False)
    inventory_path: Path = field(init=False)
    collection_path: Path = field(init=False)
    focus_path: Path = field(init=False)
    stats_path: Path = field(init=False)
    settings_path: Path = field(init=False)
    market_path: Path = field(init=False)

    def __post_init__(self) -> None:
        base_dir = Path(self.base_path).expanduser().resolve().parent
        self.base_dir = base_dir
        self.rarities_path = base_dir / "case_rarities.json"
        self.items_path = base_dir / "case_items.json"
        self.inventory_path = base_dir / "case_inventory.json"
        self.collection_path = base_dir / "case_collection.json"
        self.focus_path = base_dir / "case_focus.json"
        self.stats_path = base_dir / "case_stats.json"
        self.settings_path = base_dir / "case_settings.json"
        self.market_path = base_dir / "case_market.json"

    def _read_json(self, path: Path) -> Any:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write_json(self, path: Path, payload: Any) -> None:
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

    def load(self, defaults: dict) -> dict:
        data = deepcopy(defaults)
        split_sources = (
            ("rarities", self.rarities_path),
            ("items", self.items_path),
            ("inventory", self.inventory_path),
            ("collection", self.collection_path),
            ("focus", self.focus_path),
            ("stats", self.stats_path),
            ("settings", self.settings_path),
            ("market", self.market_path),
        )
        for key, path in split_sources:
            if not path.exists():
                continue
            try:
                loaded = self._read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data.get(key), dict) and isinstance(loaded, dict):
                data[key] = loaded
            elif isinstance(data.get(key), list) and isinstance(loaded, list):
                data[key] = loaded
        return data

    def save(self, data: dict) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.rarities_path, data.get("rarities", []))
        self._write_json(self.items_path, data.get("items", []))
        self._write_json(self.inventory_path, data.get("inventory", {}))
        self._write_json(self.collection_path, data.get("collection", {}))
        self._write_json(self.focus_path, data.get("focus", {}))
        self._write_json(self.stats_path, data.get("stats", {}))
        self._write_json(self.settings_path, data.get("settings", {}))
        self._write_json(self.market_path, data.get("market", {}))
