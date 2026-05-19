from __future__ import annotations

from typing import Iterable, Optional

from .constants import (
    DEFAULT_DROP_EVENTS,
    SUPPORTED_THEMES,
    copy_default_drop_events,
    copy_default_market_settings,
    copy_default_market_state,
)
from .models import LevelSettings


def sanitize_positive_float(value, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def normalize_stack_rarity_upgrades(raw_rules) -> list[dict]:
    if not isinstance(raw_rules, list):
        return []

    normalized: list[dict] = []
    for rule in raw_rules:
        if not isinstance(rule, dict):
            continue
        target_rarity_id = str(rule.get("target_rarity_id") or "").strip()
        if not target_rarity_id:
            continue
        min_qty = int(max(1, sanitize_positive_float(rule.get("min_qty", 1), 1)))
        normalized.append(
            {
                "min_qty": min_qty,
                "target_rarity_id": target_rarity_id,
            }
        )

    normalized.sort(key=lambda row: row["min_qty"])
    return normalized


def ensure_rarity_defaults(rarity: dict) -> None:
    if "weight" not in rarity:
        min_roll = sanitize_positive_float(rarity.get("min_roll", 0.0), 0.0)
        max_roll = sanitize_positive_float(rarity.get("max_roll", 0.0), min_roll)
        rarity["weight"] = max(0.0, max_roll - min_roll)

    rarity["weight"] = sanitize_positive_float(rarity.get("weight", 0.0), 0.0)
    rarity.pop("min_roll", None)
    rarity.pop("max_roll", None)

    rarity.setdefault("drop_bg_color", "#0f172a")
    rarity.setdefault("drop_text_color", "#e4ecfb")
    rarity.setdefault("drop_border_color", rarity.get("color", "#3b82f6"))
    rarity["drop_box_width"] = int(
        max(120, sanitize_positive_float(rarity.get("drop_box_width", 260), 260))
    )
    rarity["drop_box_height"] = int(
        max(36, sanitize_positive_float(rarity.get("drop_box_height", 60), 60))
    )
    rarity["drop_font_size"] = int(
        max(10, sanitize_positive_float(rarity.get("drop_font_size", 18), 18))
    )
    rarity["stack_max_size"] = int(
        max(1, sanitize_positive_float(rarity.get("stack_max_size", 10), 10))
    )
    rarity["stack_display_max"] = int(
        max(1, sanitize_positive_float(rarity.get("stack_display_max", 99), 99))
    )
    rarity["stack_rarity_upgrades"] = normalize_stack_rarity_upgrades(
        rarity.get("stack_rarity_upgrades", [])
    )


def normalize_appearance(raw_appearance) -> dict:
    appearance = raw_appearance if isinstance(raw_appearance, dict) else {}
    theme = appearance.get("theme", "dark")
    return {"theme": theme if theme in SUPPORTED_THEMES else "dark"}


def normalize_filters(raw_filters) -> dict:
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    return {
        "rarity_hidden": dict(filters.get("rarity_hidden") or {}),
        "item_hidden": dict(filters.get("item_hidden") or {}),
    }


def normalize_levels(raw_levels) -> dict:
    levels = raw_levels if isinstance(raw_levels, dict) else {}
    normalized = LevelSettings().to_dict()
    if "base_xp" in levels:
        try:
            normalized["base_xp"] = max(1, int(levels["base_xp"]))
        except (TypeError, ValueError):
            pass
    if "xp_growth" in levels:
        try:
            normalized["xp_growth"] = max(1.01, float(levels["xp_growth"]))
        except (TypeError, ValueError):
            pass
    return normalized


def normalize_drop_visuals(raw_visuals) -> dict:
    visuals = raw_visuals if isinstance(raw_visuals, dict) else {}
    return {
        "spawn_cooldown_ms": int(
            max(0, sanitize_positive_float(visuals.get("spawn_cooldown_ms", 70), 70))
        ),
        "appearance_effect_enabled": bool(
            visuals.get("appearance_effect_enabled", True)
        ),
        "background_image_path": str(visuals.get("background_image_path", "") or ""),
        "background_brightness": min(
            2.0,
            max(
                0.2,
                float(
                    sanitize_positive_float(
                        visuals.get("background_brightness", 1.0),
                        1.0,
                    )
                    or 1.0
                ),
            ),
        ),
    }


DEFAULT_DROP_EVENT_NAMES = {
    str(event.get("id")): str(event.get("name"))
    for event in DEFAULT_DROP_EVENTS
    if event.get("id") and event.get("name")
}


def _is_corrupted_drop_event_name(name: str) -> bool:
    stripped = name.strip()
    if not stripped:
        return True
    letters = [char for char in stripped if char.isalpha()]
    question_marks = stripped.count("?")
    return question_marks > 0 and not letters


def normalize_drop_events(raw_events) -> list[dict]:
    if not isinstance(raw_events, list):
        return copy_default_drop_events()

    normalized: list[dict] = []
    for index, event in enumerate(raw_events):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or f"event-{index + 1}")
        event_name = str(event.get("name") or "")
        if _is_corrupted_drop_event_name(event_name):
            event_name = DEFAULT_DROP_EVENT_NAMES.get(
                event_id,
                f"Событие {index + 1}",
            )
        normalized_event = {
            "id": event_id,
            "name": event_name,
            "weight": sanitize_positive_float(event.get("weight", 0), 0),
            "multiplier": int(
                max(1, sanitize_positive_float(event.get("multiplier", 1), 1))
            ),
        }

        if "encounter_type" in event or "type" in event:
            normalized_event["encounter_type"] = str(
                event.get("encounter_type") or event.get("type") or "normal"
            )
        if "rolls" in event or "extra_rolls" in event:
            rolls = event.get("rolls", event.get("extra_rolls", 1))
            normalized_event["rolls"] = int(max(1, sanitize_positive_float(rolls, 1)))
        if "currency_bias" in event:
            normalized_event["currency_bias"] = sanitize_positive_float(
                event.get("currency_bias", 1.0),
                1.0,
            )
        if "currency_only" in event:
            normalized_event["currency_only"] = bool(event.get("currency_only"))
        if "unique_chance" in event:
            normalized_event["unique_chance"] = min(
                1.0,
                sanitize_positive_float(event.get("unique_chance", 0.0), 0.0),
            )
        if "unique_tags" in event and isinstance(event.get("unique_tags"), list):
            normalized_event["unique_tags"] = [
                str(tag).strip()
                for tag in event.get("unique_tags", [])
                if str(tag).strip()
            ]
        if "duplicate_best" in event:
            normalized_event["duplicate_best"] = bool(event.get("duplicate_best"))
        if "rarity_luck_rolls" in event:
            normalized_event["rarity_luck_rolls"] = int(
                max(
                    1,
                    sanitize_positive_float(event.get("rarity_luck_rolls", 1), 1),
                )
            )

        normalized.append(normalized_event)

    return normalized or copy_default_drop_events()


def normalize_market_settings(raw_market) -> dict:
    raw = raw_market if isinstance(raw_market, dict) else {}
    normalized = copy_default_market_settings()
    normalized["enabled"] = bool(raw.get("enabled", normalized["enabled"]))
    normalized["tick_seconds"] = int(
        max(
            5,
            sanitize_positive_float(
                raw.get("tick_seconds", normalized["tick_seconds"]),
                30,
            ),
        )
    )
    normalized["reference_currency_id"] = str(
        raw.get("reference_currency_id", normalized["reference_currency_id"]) or ""
    )
    normalized["max_ticks_per_refresh"] = int(
        max(
            1,
            sanitize_positive_float(
                raw.get("max_ticks_per_refresh", normalized["max_ticks_per_refresh"]),
                240,
            ),
        )
    )
    return normalized


def normalize_focus_chain_settings(raw_chain) -> dict:
    chain = raw_chain if isinstance(raw_chain, dict) else {}
    long_session_minutes = int(
        min(
            180,
            max(
                1,
                sanitize_positive_float(chain.get("long_session_minutes", 45), 45),
            ),
        )
    )
    deep_session_minutes = int(
        min(
            180,
            max(
                long_session_minutes,
                sanitize_positive_float(chain.get("deep_session_minutes", 90), 90),
            ),
        )
    )
    return {
        "break_window_minutes": int(
            min(
                720,
                max(
                    15,
                    sanitize_positive_float(
                        chain.get("break_window_minutes", 150),
                        150,
                    ),
                ),
            )
        ),
        "bonus_roll_every": int(
            min(
                12,
                max(
                    1,
                    sanitize_positive_float(chain.get("bonus_roll_every", 2), 2),
                ),
            )
        ),
        "max_bonus_rolls": int(
            min(
                20,
                max(
                    0,
                    sanitize_positive_float(chain.get("max_bonus_rolls", 5), 5),
                ),
            )
        ),
        "luck_roll_every": int(
            min(
                12,
                max(
                    1,
                    sanitize_positive_float(chain.get("luck_roll_every", 3), 3),
                ),
            )
        ),
        "max_luck_rolls": int(
            min(
                10,
                max(
                    1,
                    sanitize_positive_float(chain.get("max_luck_rolls", 5), 5),
                ),
            )
        ),
        "daily_chain_bonus_roll_cap": int(
            min(
                50,
                max(
                    0,
                    sanitize_positive_float(
                        chain.get("daily_chain_bonus_roll_cap", 8),
                        8,
                    ),
                ),
            )
        ),
        "short_session_minutes": int(
            min(
                60,
                max(
                    0,
                    sanitize_positive_float(
                        chain.get("short_session_minutes", 15),
                        15,
                    ),
                ),
            )
        ),
        "short_session_daily_limit": int(
            min(
                30,
                max(
                    0,
                    sanitize_positive_float(
                        chain.get("short_session_daily_limit", 3),
                        3,
                    ),
                ),
            )
        ),
        "short_session_decay": min(
            1.0,
            max(
                0.0,
                sanitize_positive_float(chain.get("short_session_decay", 0.5), 0.5),
            ),
        ),
        "long_session_minutes": long_session_minutes,
        "long_session_bonus_rolls": int(
            min(
                10,
                max(
                    0,
                    sanitize_positive_float(
                        chain.get("long_session_bonus_rolls", 1),
                        1,
                    ),
                ),
            )
        ),
        "deep_session_minutes": deep_session_minutes,
        "deep_session_bonus_rolls": int(
            min(
                20,
                max(
                    0,
                    sanitize_positive_float(
                        chain.get("deep_session_bonus_rolls", 2),
                        2,
                    ),
                ),
            )
        ),
    }


def normalize_market_state(raw_market) -> dict:
    raw = raw_market if isinstance(raw_market, dict) else {}
    normalized = copy_default_market_state()
    normalized["last_tick"] = int(sanitize_positive_float(raw.get("last_tick", 0), 0))
    try:
        normalized["sentiment"] = max(-1.0, min(1.0, float(raw.get("sentiment", 0.0))))
    except (TypeError, ValueError):
        normalized["sentiment"] = 0.0
    for key in ("prices", "recent_drops", "recent_purchases"):
        if isinstance(raw.get(key), dict):
            normalized[key] = dict(raw[key])
    return normalized


def normalize_rarity_boosts(
    raw_boosts,
    *,
    valid_rarity_ids: Optional[Iterable[str]] = None,
    strict_percent: bool = False,
) -> list[dict]:
    if not isinstance(raw_boosts, list):
        return []

    allowed = set(valid_rarity_ids) if valid_rarity_ids is not None else None
    normalized: list[dict] = []
    for row in raw_boosts:
        if not isinstance(row, dict):
            continue
        rarity_id = str(row.get("rarity_id") or "").strip()
        if not rarity_id:
            continue
        if allowed is not None and rarity_id not in allowed:
            continue
        try:
            percent = float(row.get("percent", 0))
        except (TypeError, ValueError):
            if strict_percent:
                raise
            percent = 0.0
        normalized.append({"rarity_id": rarity_id, "percent": percent})
    return normalized


def normalize_auto_stop_conditions(
    raw_conditions,
    *,
    valid_item_ids: Optional[Iterable[str]] = None,
) -> list[dict]:
    if not isinstance(raw_conditions, list):
        return []

    allowed = set(valid_item_ids) if valid_item_ids is not None else None
    normalized: list[dict] = []
    for row in raw_conditions:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        if allowed is not None and item_id not in allowed:
            continue
        normalized.append(
            {
                "item_id": item_id,
                "target_qty": int(
                    max(1, sanitize_positive_float(row.get("target_qty", 1), 1))
                ),
            }
        )
    return normalized


def normalize_stats(raw_stats) -> dict:
    stats = raw_stats if isinstance(raw_stats, dict) else {}
    return {
        "total_opened": int(stats.get("total_opened", 0)),
        "total_spent": float(stats.get("total_spent", 0)),
        "total_focus_minutes": int(
            max(0, sanitize_positive_float(stats.get("total_focus_minutes", 0), 0))
        ),
        "completed_focus_sessions": int(
            max(0, sanitize_positive_float(stats.get("completed_focus_sessions", 0), 0))
        ),
        "total_rewards": int(
            max(0, sanitize_positive_float(stats.get("total_rewards", 0), 0))
        ),
        "by_rarity": dict(stats.get("by_rarity") or {}),
    }


def normalize_focus(raw_focus) -> dict:
    focus = raw_focus if isinstance(raw_focus, dict) else {}
    active = focus.get("active_session")
    active_session = None
    if isinstance(active, dict):
        active_id = str(active.get("id") or "").strip()
        if active_id:
            active_session = {
                "id": active_id,
                "task_title": str(active.get("task_title") or "Focus session"),
                "duration_minutes": int(
                    max(1, sanitize_positive_float(active.get("duration_minutes", 25), 25))
                ),
                "difficulty_level": int(
                    min(
                        5,
                        max(
                            1,
                            sanitize_positive_float(
                                active.get("difficulty_level", 2),
                                2,
                            ),
                        ),
                    )
                ),
                "started_at": int(
                    max(0, sanitize_positive_float(active.get("started_at", 0), 0))
                ),
                "ends_at": int(
                    max(0, sanitize_positive_float(active.get("ends_at", 0), 0))
                ),
                "status": str(active.get("status") or "active"),
            }

    completed_sessions = []
    raw_completed = focus.get("completed_sessions", [])
    if isinstance(raw_completed, list):
        for session in raw_completed:
            if not isinstance(session, dict):
                continue
            session_id = str(session.get("id") or "").strip()
            if not session_id:
                continue
            completed_sessions.append(
                {
                    "id": session_id,
                    "task_title": str(session.get("task_title") or "Focus session"),
                    "duration_minutes": int(
                        max(
                            1,
                            sanitize_positive_float(
                                session.get("duration_minutes", 1),
                                1,
                            ),
                        )
                    ),
                    "difficulty_level": int(
                        min(
                            5,
                            max(
                                1,
                                sanitize_positive_float(
                                    session.get("difficulty_level", 2),
                                    2,
                                ),
                            ),
                        )
                    ),
                    "started_at": int(
                        max(0, sanitize_positive_float(session.get("started_at", 0), 0))
                    ),
                    "completed_at": int(
                        max(
                            0,
                            sanitize_positive_float(session.get("completed_at", 0), 0),
                        )
                    ),
                    "reward_rolls": int(
                        max(0, sanitize_positive_float(session.get("reward_rolls", 0), 0))
                    ),
                    "chain_count": int(
                        max(0, sanitize_positive_float(session.get("chain_count", 0), 0))
                    ),
                    "chain_bonus_rolls": int(
                        max(
                            0,
                            sanitize_positive_float(
                                session.get("chain_bonus_rolls", 0),
                                0,
                            ),
                        )
                    ),
                    "chain_luck_rolls": int(
                        max(
                            1,
                            sanitize_positive_float(
                                session.get("chain_luck_rolls", 1),
                                1,
                            ),
                        )
                    ),
                    "difficulty_bonus_rolls": int(
                        max(
                            0,
                            sanitize_positive_float(
                                session.get("difficulty_bonus_rolls", 0),
                                0,
                            ),
                        )
                    ),
                    "difficulty_luck_rolls": int(
                        max(
                            0,
                            sanitize_positive_float(
                                session.get("difficulty_luck_rolls", 0),
                                0,
                            ),
                        )
                    ),
                }
            )

    daily_focus = {}
    raw_daily = focus.get("daily_focus", {})
    if isinstance(raw_daily, dict):
        for date_key, row in raw_daily.items():
            if not isinstance(row, dict):
                continue
            key = str(date_key or "").strip()
            if not key:
                continue
            daily_focus[key] = {
                "minutes": int(
                    max(0, sanitize_positive_float(row.get("minutes", 0), 0))
                ),
                "sessions": int(
                    max(0, sanitize_positive_float(row.get("sessions", 0), 0))
                ),
                "short_sessions": int(
                    max(0, sanitize_positive_float(row.get("short_sessions", 0), 0))
                ),
                "chain_bonus_rolls": int(
                    max(0, sanitize_positive_float(row.get("chain_bonus_rolls", 0), 0))
                ),
            }

    quest_claims = {}
    raw_claims = focus.get("quest_claims", {})
    if isinstance(raw_claims, dict):
        for date_key, claims in raw_claims.items():
            key = str(date_key or "").strip()
            if not key or not isinstance(claims, list):
                continue
            quest_claims[key] = [
                str(claim).strip() for claim in claims if str(claim).strip()
            ]

    return {
        "active_session": active_session,
        "completed_sessions": completed_sessions[:200],
        "daily_focus": daily_focus,
        "focus_streak": int(
            max(0, sanitize_positive_float(focus.get("focus_streak", 0), 0))
        ),
        "best_focus_streak": int(
            max(0, sanitize_positive_float(focus.get("best_focus_streak", 0), 0))
        ),
        "last_completed_at": int(
            max(0, sanitize_positive_float(focus.get("last_completed_at", 0), 0))
        ),
        "chain_started_at": int(
            max(0, sanitize_positive_float(focus.get("chain_started_at", 0), 0))
        ),
        "today_minutes": int(
            max(0, sanitize_positive_float(focus.get("today_minutes", 0), 0))
        ),
        "today_sessions": int(
            max(0, sanitize_positive_float(focus.get("today_sessions", 0), 0))
        ),
        "quest_claims": quest_claims,
    }


def normalize_collection(raw_collection) -> dict:
    collection = raw_collection if isinstance(raw_collection, dict) else {}
    raw_items = collection.get("items", {})
    items = raw_items if isinstance(raw_items, dict) else {}
    normalized_items = {}

    for item_id, row in items.items():
        if not isinstance(row, dict):
            continue
        item_key = str(item_id or "").strip()
        if not item_key:
            continue
        found_count = int(max(0, sanitize_positive_float(row.get("found_count", 0), 0)))
        if found_count <= 0:
            continue
        first_found_at = int(
            max(0, sanitize_positive_float(row.get("first_found_at", 0), 0))
        )
        last_found_at = int(
            max(first_found_at, sanitize_positive_float(row.get("last_found_at", 0), 0))
        )
        best_stack = int(max(1, sanitize_positive_float(row.get("best_stack", 1), 1)))
        normalized_items[item_key] = {
            "found_count": found_count,
            "first_found_at": first_found_at,
            "last_found_at": last_found_at,
            "best_stack": best_stack,
            "seeded": bool(row.get("seeded", False)),
        }

    return {
        "seeded_from_inventory": bool(collection.get("seeded_from_inventory", False)),
        "items": normalized_items,
    }


def normalize_item(item: dict) -> None:
    item["is_currency"] = bool(item.get("is_currency", False))
    if "tags" in item and isinstance(item["tags"], list):
        item["tags"] = [str(tag).strip() for tag in item["tags"] if str(tag).strip()]
    else:
        item["tags"] = []
    item["is_unique"] = bool(item.get("is_unique", False))
    for key in (
        "market_value_chaos",
        "market_demand",
        "market_supply",
        "market_liquidity",
        "market_volatility",
    ):
        if key in item:
            item[key] = sanitize_positive_float(item.get(key), 0.0)
