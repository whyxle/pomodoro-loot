from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_RUNTIME_DIR = Path(os.environ.get("LOCALAPPDATA", str(PROJECT_ROOT))) / "SimDrop"
WEBVIEW_STORAGE_DIR = APP_RUNTIME_DIR / "pywebview"
DATA_FILE = str(PROJECT_ROOT / "case_simulator_data.json")
SUPPORTED_THEMES = frozenset({"dark", "light"})
MAX_RAW_RESULTS = 500
HISTORY_LIMIT = 500
SHOP_MARKUP = 0.15

DEFAULT_DROP_EVENTS = [
    {
        "id": "normal",
        "name": "Обычная награда",
        "encounter_type": "normal",
        "weight": 8200.0,
        "multiplier": 1,
        "rolls": 1,
    },
    {
        "id": "chest",
        "name": "Бонусная находка",
        "encounter_type": "chest",
        "weight": 1300.0,
        "multiplier": 3,
        "rolls": 1,
        "currency_bias": 1.1,
    },
    {
        "id": "boss",
        "name": "Большой итог",
        "encounter_type": "boss",
        "weight": 380.0,
        "multiplier": 5,
        "rolls": 1,
        "rarity_luck_rolls": 2,
        "currency_bias": 1.25,
    },
    {
        "id": "legion",
        "name": "Поток идей",
        "encounter_type": "legion",
        "weight": 95.0,
        "multiplier": 2,
        "rolls": 7,
        "currency_only": True,
        "currency_bias": 3.0,
        "rarity_luck_rolls": 2,
    },
    {
        "id": "abyss",
        "name": "Редкий прорыв",
        "encounter_type": "abyss",
        "weight": 22.0,
        "multiplier": 2,
        "rolls": 2,
        "unique_chance": 0.22,
        "unique_tags": ["unique"],
    },
    {
        "id": "mirror_altar",
        "name": "Двойной итог",
        "encounter_type": "mirror_altar",
        "weight": 1.2,
        "multiplier": 1,
        "rolls": 2,
        "duplicate_best": True,
        "rarity_luck_rolls": 3,
        "currency_bias": 1.5,
    },
]


def copy_default_drop_events() -> list[dict]:
    return deepcopy(DEFAULT_DROP_EVENTS)


DEFAULT_MARKET_SETTINGS = {
    "enabled": True,
    "tick_seconds": 30,
    "reference_currency_id": "chaos_orb",
    "max_ticks_per_refresh": 240,
}


DEFAULT_MARKET_STATE = {
    "last_tick": 0,
    "sentiment": 0.0,
    "prices": {},
    "recent_drops": {},
    "recent_purchases": {},
}


def copy_default_market_settings() -> dict:
    return deepcopy(DEFAULT_MARKET_SETTINGS)


def copy_default_market_state() -> dict:
    return deepcopy(DEFAULT_MARKET_STATE)
