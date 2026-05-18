from __future__ import annotations

from dataclasses import asdict

from .constants import (
    copy_default_drop_events,
    copy_default_market_settings,
    copy_default_market_state,
)
from .models import LevelSettings, Rarity


def build_empty_state() -> dict:
    return {
        "rarities": [],
        "items": [],
        "inventory": {},
        "collection": default_collection(),
        "focus": default_focus(),
        "history": [],
        "stats": default_stats(),
        "settings": default_settings(),
        "market": copy_default_market_state(),
    }


def default_settings() -> dict:
    return {
        "roll_min": 0,
        "roll_max": 100,
        "open_price": 1,
        "appearance": {"theme": "dark"},
        "filters": {
            "rarity_hidden": {},
            "item_hidden": {},
        },
        "levels": LevelSettings().to_dict(),
        "drop_visuals": {
            "spawn_cooldown_ms": 70,
            "appearance_effect_enabled": True,
            "background_image_path": "",
            "background_brightness": 1.0,
        },
        "drop_events": copy_default_drop_events(),
        "market": copy_default_market_settings(),
        "rarity_boosts": [],
        "auto_stop_conditions": [],
        "focus_chain": {
            "break_window_minutes": 150,
            "bonus_roll_every": 2,
            "max_bonus_rolls": 5,
            "luck_roll_every": 3,
            "max_luck_rolls": 5,
            "daily_chain_bonus_roll_cap": 8,
            "short_session_minutes": 15,
            "short_session_daily_limit": 3,
            "short_session_decay": 0.5,
            "long_session_minutes": 45,
            "long_session_bonus_rolls": 1,
            "deep_session_minutes": 90,
            "deep_session_bonus_rolls": 2,
        },
    }


def default_stats() -> dict:
    return {
        "total_opened": 0,
        "total_spent": 0,
        "total_focus_minutes": 0,
        "completed_focus_sessions": 0,
        "total_rewards": 0,
        "by_rarity": {},
    }


def default_collection() -> dict:
    return {
        "seeded_from_inventory": False,
        "items": {},
    }


def default_focus() -> dict:
    return {
        "active_session": None,
        "completed_sessions": [],
        "daily_focus": {},
        "focus_streak": 0,
        "best_focus_streak": 0,
        "last_completed_at": 0,
        "chain_started_at": 0,
        "today_minutes": 0,
        "today_sessions": 0,
        "quest_claims": {},
    }


def default_rarities() -> list[dict]:
    return [
        asdict(
            Rarity.create(
                name="Обычная",
                weight=60,
                color="#c8b994",
                drop_bg_color="#16130f",
                drop_text_color="#d8c79a",
                drop_border_color="#6f6045",
                drop_box_width=230,
                drop_box_height=44,
                drop_font_size=17,
            )
        ),
        asdict(
            Rarity.create(
                name="Редкая",
                weight=25,
                color="#d6a64b",
                drop_bg_color="#1d160b",
                drop_text_color="#f1d38a",
                drop_border_color="#9f762a",
                drop_box_width=250,
                drop_box_height=48,
                drop_font_size=18,
            )
        ),
        asdict(
            Rarity.create(
                name="Эпическая",
                weight=12,
                color="#af6025",
                drop_bg_color="#211006",
                drop_text_color="#ffd0a0",
                drop_border_color="#9f5521",
                drop_box_width=280,
                drop_box_height=52,
                drop_font_size=21,
            )
        ),
        asdict(
            Rarity.create(
                name="Легендарная",
                weight=3,
                color="#fff3a6",
                drop_bg_color="#251700",
                drop_text_color="#fff7ce",
                drop_border_color="#d8b64f",
                drop_box_width=320,
                drop_box_height=60,
                drop_font_size=24,
            )
        ),
    ]


def default_items(rarities: list[dict]) -> list[dict]:
    return []
