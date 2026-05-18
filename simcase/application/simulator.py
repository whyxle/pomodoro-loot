from __future__ import annotations

import json
import random
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from typing import Any, Callable, Dict, Optional, Tuple

from ..domain.calculations import (
    build_drop_events_pool,
    build_item_map,
    build_item_pools,
    build_rarity_map,
    calculate_level_progress,
    calculate_rarity_probabilities,
    compute_shop_offer,
    compute_shop_unit_price,
    get_display_rarity_for_stack,
    is_hidden_drop,
    item_effective_weight,
    pick_drop_event,
    pick_from_cumulative,
    roll_rarity,
)
from ..domain.constants import DATA_FILE, HISTORY_LIMIT, MAX_RAW_RESULTS
from ..domain.defaults import build_empty_state, default_items, default_rarities
from ..domain.market import (
    compute_market_shop_offer,
    initialize_market_prices,
    item_has_market_price,
    market_price_chaos,
    record_market_demand,
    record_market_supply,
    refresh_market,
)
from ..domain.models import Item, LevelSettings, Rarity
from ..domain.normalizers import (
    ensure_rarity_defaults,
    normalize_appearance,
    normalize_auto_stop_conditions,
    normalize_collection,
    normalize_drop_events,
    normalize_drop_visuals,
    normalize_filters,
    normalize_focus,
    normalize_focus_chain_settings,
    normalize_item,
    normalize_levels,
    normalize_market_settings,
    normalize_market_state,
    normalize_rarity_boosts,
    normalize_stack_rarity_upgrades,
    normalize_stats,
    sanitize_positive_float,
)
from ..infrastructure.storage import SplitJsonStorage


DAILY_FOCUS_QUESTS = (
    {
        "id": "first_session",
        "label": "Первая сессия",
        "metric": "sessions",
        "target": 1,
        "bonus_rolls": 1,
    },
    {
        "id": "focus_60",
        "label": "60 минут фокуса",
        "metric": "minutes",
        "target": 60,
        "bonus_rolls": 1,
    },
    {
        "id": "focus_120",
        "label": "120 минут фокуса",
        "metric": "minutes",
        "target": 120,
        "bonus_rolls": 2,
    },
)

CANCEL_CHAIN_GRACE_SECONDS = 120


class CaseSimulator:
    """Stateful application service that orchestrates the simulator."""

    def __init__(
        self,
        path: str = DATA_FILE,
        storage: Optional[SplitJsonStorage] = None,
        rng: Optional[Any] = None,
        time_provider: Optional[Callable[[], float]] = None,
        id_factory: Optional[Callable[[], str]] = None,
    ):
        self.path = path
        self.storage = storage or SplitJsonStorage(path)
        self._rng = rng or random
        self._time_provider = time_provider or time.time
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self.data = build_empty_state()
        self._load_or_create_defaults()

    @staticmethod
    def _clone(value):
        return deepcopy(value)

    def _load_or_create_defaults(self) -> None:
        self.data = self.storage.load(build_empty_state())

        settings = self.data.setdefault("settings", {})
        settings["appearance"] = normalize_appearance(settings.get("appearance"))
        settings["filters"] = normalize_filters(settings.get("filters"))
        settings["levels"] = normalize_levels(settings.get("levels"))
        settings["drop_visuals"] = normalize_drop_visuals(settings.get("drop_visuals"))
        settings["drop_events"] = normalize_drop_events(settings.get("drop_events"))
        settings["market"] = normalize_market_settings(settings.get("market"))
        settings["rarity_boosts"] = normalize_rarity_boosts(
            settings.get("rarity_boosts")
        )
        settings["auto_stop_conditions"] = normalize_auto_stop_conditions(
            settings.get("auto_stop_conditions"),
            valid_item_ids=self._item_map().keys(),
        )
        settings["focus_chain"] = normalize_focus_chain_settings(
            settings.get("focus_chain")
        )

        self.data["stats"] = normalize_stats(self.data.get("stats"))
        self.data["market"] = normalize_market_state(self.data.get("market"))
        self.data["collection"] = normalize_collection(self.data.get("collection"))
        self.data["focus"] = normalize_focus(self.data.get("focus"))
        self.data.setdefault("history", [])

        if not self.data.get("rarities"):
            self.data["rarities"] = default_rarities()

        if not self.data.get("items"):
            self.data["items"] = default_items(self.data["rarities"])

        for rarity in self.data["rarities"]:
            self._ensure_rarity_defaults(rarity)
            rarity.setdefault("drop_sound", "")
            rarity.pop("drop_effect", None)

        for item in self.data["items"]:
            normalize_item(item)

        self._seed_collection_from_inventory()

        initialize_market_prices(
            self.data["market"],
            settings["market"],
            self.data["items"],
            self._rarity_map(),
        )

        self.save()

    def save(self) -> None:
        self.storage.save(self.data)

    def _append_history(self, action: str, payload: dict) -> None:
        self.data.setdefault("history", [])
        self.data["history"].insert(
            0,
            {
                "id": self._id_factory(),
                "timestamp": int(self._time_provider()),
                "action": action,
                "payload": payload,
            },
        )
        self.data["history"] = self.data["history"][:HISTORY_LIMIT]

    def _today_key(self, timestamp: Optional[float] = None) -> str:
        current = self._time_provider() if timestamp is None else timestamp
        return time.strftime("%Y-%m-%d", time.localtime(current))

    def _focus_state(self) -> dict:
        focus = normalize_focus(self.data.get("focus"))
        self.data["focus"] = focus
        return focus

    def _today_focus_row(self, date_key: Optional[str] = None) -> dict:
        focus = self.data.setdefault("focus", {})
        key = date_key or self._today_key()
        return focus.setdefault("daily_focus", {}).setdefault(
            key,
            {"minutes": 0, "sessions": 0},
        )

    def _daily_quest_status(self, date_key: Optional[str] = None) -> list[dict]:
        focus = self.data.setdefault("focus", {})
        key = date_key or self._today_key()
        row = self._today_focus_row(key)
        claimed = set(focus.setdefault("quest_claims", {}).get(key, []))
        statuses = []
        for quest in DAILY_FOCUS_QUESTS:
            value = int(row.get(quest["metric"], 0))
            statuses.append(
                {
                    **quest,
                    "value": value,
                    "completed": value >= int(quest["target"]),
                    "claimed": quest["id"] in claimed,
                }
            )
        return statuses

    def _focus_chain_settings(self) -> dict:
        settings = self.data.setdefault("settings", {})
        settings["focus_chain"] = normalize_focus_chain_settings(
            settings.get("focus_chain")
        )
        return settings["focus_chain"]

    def _latest_completed_at(self, focus: dict) -> int:
        stored_completed_at = int(
            max(0, self._sanitize_positive_float(focus.get("last_completed_at", 0), 0))
        )
        if stored_completed_at > 0:
            return stored_completed_at
        if int(focus.get("focus_streak", 0)) <= 0:
            return 0

        latest = 0
        for session in focus.get("completed_sessions", []):
            if not isinstance(session, dict):
                continue
            completed_at = int(
                max(
                    0,
                    self._sanitize_positive_float(session.get("completed_at", 0), 0),
                )
            )
            latest = max(latest, completed_at)
        return latest

    def _chain_deadline_at(
        self,
        focus: dict,
        chain_settings: Optional[dict] = None,
    ) -> int:
        settings = chain_settings or self._focus_chain_settings()
        last_completed_at = self._latest_completed_at(focus)
        if last_completed_at <= 0:
            return 0
        return last_completed_at + int(settings["break_window_minutes"]) * 60

    def _chain_bonus_rolls(
        self,
        chain_count: int,
        chain_settings: Optional[dict] = None,
    ) -> int:
        settings = chain_settings or self._focus_chain_settings()
        chain_count = max(0, int(chain_count))
        if chain_count <= 1:
            return 0
        every = max(1, int(settings["bonus_roll_every"]))
        return min(int(settings["max_bonus_rolls"]), chain_count // every)

    def _chain_luck_rolls(
        self,
        chain_count: int,
        chain_settings: Optional[dict] = None,
    ) -> int:
        settings = chain_settings or self._focus_chain_settings()
        chain_count = max(0, int(chain_count))
        if chain_count <= 1:
            return 1
        every = max(1, int(settings["luck_roll_every"]))
        return min(
            int(settings["max_luck_rolls"]),
            1 + (chain_count // every),
        )

    def _length_bonus_rolls(
        self,
        duration_minutes: int,
        chain_settings: Optional[dict] = None,
    ) -> int:
        settings = chain_settings or self._focus_chain_settings()
        duration_minutes = max(0, int(duration_minutes))
        if duration_minutes >= int(settings["deep_session_minutes"]):
            return int(settings["deep_session_bonus_rolls"])
        if duration_minutes >= int(settings["long_session_minutes"]):
            return int(settings["long_session_bonus_rolls"])
        return 0

    def _short_session_multiplier(
        self,
        duration_minutes: int,
        short_sessions_before: int,
        chain_settings: Optional[dict] = None,
    ) -> tuple[bool, float]:
        settings = chain_settings or self._focus_chain_settings()
        short_limit_minutes = int(settings["short_session_minutes"])
        is_short = short_limit_minutes > 0 and duration_minutes < short_limit_minutes
        if not is_short:
            return False, 1.0

        daily_limit = int(settings["short_session_daily_limit"])
        if short_sessions_before < daily_limit:
            return True, 1.0

        over_limit = short_sessions_before - daily_limit + 1
        decay = float(settings["short_session_decay"])
        return True, max(0.0, min(1.0, decay**over_limit))

    def _apply_focus_chain_limits(
        self,
        raw_bonus_rolls: int,
        raw_luck_rolls: int,
        duration_minutes: int,
        today_row: dict,
        chain_settings: Optional[dict] = None,
    ) -> dict:
        settings = chain_settings or self._focus_chain_settings()
        short_sessions_before = int(today_row.get("short_sessions", 0))
        is_short, short_multiplier = self._short_session_multiplier(
            duration_minutes,
            short_sessions_before,
            settings,
        )
        scaled_bonus_rolls = int(max(0, raw_bonus_rolls) * short_multiplier)
        scaled_luck_rolls = 1 + int(max(0, raw_luck_rolls - 1) * short_multiplier)

        daily_cap = int(settings["daily_chain_bonus_roll_cap"])
        daily_used_before = int(today_row.get("chain_bonus_rolls", 0))
        daily_left = max(0, daily_cap - daily_used_before) if daily_cap > 0 else 0
        capped_bonus_rolls = min(scaled_bonus_rolls, daily_left)
        length_bonus_rolls = self._length_bonus_rolls(duration_minutes, settings)

        return {
            "chain_bonus_rolls": capped_bonus_rolls,
            "chain_luck_rolls": max(1, scaled_luck_rolls),
            "length_bonus_rolls": length_bonus_rolls,
            "short_session": is_short,
            "short_sessions_before": short_sessions_before,
            "short_session_multiplier": round(short_multiplier, 3),
            "raw_chain_bonus_rolls": max(0, int(raw_bonus_rolls)),
            "scaled_chain_bonus_rolls": scaled_bonus_rolls,
            "raw_chain_luck_rolls": max(1, int(raw_luck_rolls)),
            "scaled_chain_luck_rolls": max(1, scaled_luck_rolls),
            "daily_chain_bonus_cap": daily_cap,
            "daily_chain_bonus_used_before": daily_used_before,
            "daily_chain_bonus_left_before": daily_left,
            "daily_cap_hit": scaled_bonus_rolls > capped_bonus_rolls,
        }

    def _session_continues_chain(
        self,
        focus: dict,
        started_at: int,
        chain_settings: Optional[dict] = None,
    ) -> tuple[bool, int, int]:
        settings = chain_settings or self._focus_chain_settings()
        last_completed_at = self._latest_completed_at(focus)
        if last_completed_at <= 0:
            return False, 0, 0
        deadline_at = last_completed_at + int(settings["break_window_minutes"]) * 60
        gap_seconds = max(0, started_at - last_completed_at)
        return started_at <= deadline_at, gap_seconds, deadline_at

    def _sync_focus_chain_expiration(
        self,
        focus: dict,
        now: Optional[int] = None,
    ) -> None:
        now = int(self._time_provider()) if now is None else int(now)
        active = focus.get("active_session")
        chain_settings = self._focus_chain_settings()
        deadline_at = self._chain_deadline_at(focus, chain_settings)
        if deadline_at <= 0:
            return
        if active:
            started_at = int(
                max(0, self._sanitize_positive_float(active.get("started_at", 0), 0))
            )
            if started_at and started_at <= deadline_at:
                return
        if now > deadline_at:
            focus["focus_streak"] = 0
            focus["chain_started_at"] = 0

    def _focus_chain_summary(self, focus: dict, now: Optional[int] = None) -> dict:
        now = int(self._time_provider()) if now is None else int(now)
        settings = self._focus_chain_settings()
        current_count = int(focus.get("focus_streak", 0))
        last_completed_at = self._latest_completed_at(focus)
        deadline_at = self._chain_deadline_at(focus, settings)
        active = focus.get("active_session")
        today_row = self._today_focus_row(self._today_key(now))
        daily_bonus_used = int(today_row.get("chain_bonus_rolls", 0))
        daily_bonus_cap = int(settings["daily_chain_bonus_roll_cap"])

        if active:
            started_at = int(
                max(0, self._sanitize_positive_float(active.get("started_at", now), now))
            )
            continues, gap_seconds, _deadline_at = self._session_continues_chain(
                focus,
                started_at,
                settings,
            )
            next_count = current_count + 1 if continues else 1
        else:
            continues = bool(last_completed_at and now <= deadline_at)
            gap_seconds = max(0, now - last_completed_at) if last_completed_at else 0
            next_count = current_count + 1 if continues else 1

        return {
            "current": current_count,
            "best": int(focus.get("best_focus_streak", 0)),
            "break_window_minutes": int(settings["break_window_minutes"]),
            "daily_bonus_roll_cap": daily_bonus_cap,
            "daily_bonus_rolls_used": daily_bonus_used,
            "daily_bonus_rolls_left": max(0, daily_bonus_cap - daily_bonus_used),
            "last_completed_at": last_completed_at,
            "chain_started_at": int(focus.get("chain_started_at", 0)),
            "deadline_at": deadline_at,
            "seconds_left": max(0, deadline_at - now) if deadline_at else 0,
            "gap_minutes": round(gap_seconds / 60, 1),
            "next_count": next_count,
            "continues": continues,
            "next_bonus_rolls": self._chain_bonus_rolls(next_count, settings),
            "next_luck_rolls": self._chain_luck_rolls(next_count, settings),
        }

    def _refresh_focus_summary(self) -> None:
        focus = self._focus_state()
        now = int(self._time_provider())
        self._sync_focus_chain_expiration(focus, now)
        today = self._today_key()
        row = self._today_focus_row(today)
        focus["today_minutes"] = int(row.get("minutes", 0))
        focus["today_sessions"] = int(row.get("sessions", 0))
        focus["daily_quests"] = self._daily_quest_status(today)
        focus["chain"] = self._focus_chain_summary(focus, now)

    def _rarity_map(self) -> Dict[str, dict]:
        return build_rarity_map(self.data["rarities"])

    def _item_map(self) -> Dict[str, dict]:
        return build_item_map(self.data["items"])

    @staticmethod
    def _sanitize_positive_float(value, default: float = 0.0) -> float:
        return sanitize_positive_float(value, default)

    def _ensure_rarity_defaults(self, rarity: dict) -> None:
        ensure_rarity_defaults(rarity)

    def _normalize_stack_rarity_upgrades(self, raw_rules) -> list[dict]:
        return normalize_stack_rarity_upgrades(raw_rules)

    def _get_display_rarity_for_stack(self, base_rarity: dict, qty: int) -> dict:
        return get_display_rarity_for_stack(base_rarity, qty, self._rarity_map())

    def _roll_rarity(self) -> Optional[dict]:
        settings = self.data.get("settings", {})
        return roll_rarity(
            self.data["rarities"],
            settings.get("rarity_boosts", []),
            self._rng,
        )

    def _pick_item_by_rarity(self, rarity_id: str) -> Optional[dict]:
        candidates = [
            item
            for item in self.data["items"]
            if item["rarity_id"] == rarity_id and item["weight"] > 0
        ]
        if not candidates:
            return None

        pool = []
        total_weight = 0.0
        for item in candidates:
            total_weight += item["weight"]
            pool.append((item, total_weight))
        return pick_from_cumulative(pool, total_weight, self._rng)

    def _item_effective_weight(self, item: dict) -> float:
        return item_effective_weight(item, self._rarity_map())

    def _compute_shop_unit_price(self, target_item: dict, currency_item: dict) -> int:
        return compute_shop_unit_price(target_item, currency_item, self._rarity_map())

    def _compute_shop_offer(self, target_item: dict, currency_item: dict) -> dict:
        if item_has_market_price(target_item) and item_has_market_price(currency_item):
            self._refresh_market()
            return compute_market_shop_offer(
                target_item,
                currency_item,
                self.data.setdefault("market", {}),
                self.data["settings"].setdefault("market", {}),
                self.data["items"],
                self._rarity_map(),
            )
        return compute_shop_offer(target_item, currency_item, self._rarity_map())

    @staticmethod
    def _pick_item_from_pool(
        pool: Optional[list[tuple[dict, float]]],
        total_weight: float,
        rng: Optional[Any] = None,
    ) -> Optional[dict]:
        return pick_from_cumulative(pool, total_weight, rng or random)

    def _build_drop_events_pool(self) -> Tuple[list[tuple[dict, float]], float]:
        return build_drop_events_pool(self.data["settings"].get("drop_events", []))

    def _pick_drop_event(
        self,
        pool: list[tuple[dict, float]],
        total_weight: float,
    ) -> Optional[dict]:
        return pick_drop_event(pool, total_weight, self._rng)

    def _refresh_market(self) -> bool:
        settings = self.data.setdefault("settings", {})
        market_settings = normalize_market_settings(settings.get("market"))
        settings["market"] = market_settings
        market = normalize_market_state(self.data.get("market"))
        self.data["market"] = market
        return refresh_market(
            market,
            market_settings,
            self.data.get("items", []),
            self._rarity_map(),
            self._rng,
            self._time_provider(),
        )

    def _record_market_supply(self, item_id: str, quantity: int) -> None:
        record_market_supply(self.data.setdefault("market", {}), item_id, quantity)

    def _record_market_demand(self, item_id: str, quantity: int) -> None:
        record_market_demand(self.data.setdefault("market", {}), item_id, quantity)

    def _collection_items(self) -> dict:
        collection = normalize_collection(self.data.get("collection"))
        self.data["collection"] = collection
        valid_item_ids = set(self._item_map().keys())
        for item_id in list(collection["items"].keys()):
            if item_id not in valid_item_ids:
                collection["items"].pop(item_id, None)
        return collection["items"]

    def _seed_collection_from_inventory(self) -> None:
        collection = normalize_collection(self.data.get("collection"))
        self.data["collection"] = collection
        if collection.get("seeded_from_inventory"):
            return

        now = int(self._time_provider())
        items = collection.setdefault("items", {})
        valid_item_ids = set(self._item_map().keys())
        for item_id, quantity in self.data.get("inventory", {}).items():
            if item_id not in valid_item_ids:
                continue
            qty = int(max(0, self._sanitize_positive_float(quantity, 0)))
            if qty <= 0 or item_id in items:
                continue
            items[item_id] = {
                "found_count": qty,
                "first_found_at": now,
                "last_found_at": now,
                "best_stack": qty,
                "seeded": True,
            }

        collection["seeded_from_inventory"] = True

    def _record_collection_drop(self, item_id: str, quantity: int, timestamp: int) -> None:
        if item_id not in self._item_map():
            return
        qty = int(max(1, quantity))
        items = self._collection_items()
        row = items.get(item_id)
        if not row:
            items[item_id] = {
                "found_count": qty,
                "first_found_at": timestamp,
                "last_found_at": timestamp,
                "best_stack": qty,
                "seeded": False,
            }
            return

        row["found_count"] = int(row.get("found_count", 0)) + qty
        if not row.get("first_found_at"):
            row["first_found_at"] = timestamp
        row["last_found_at"] = timestamp
        row["best_stack"] = max(int(row.get("best_stack", 1)), qty)
        row["seeded"] = bool(row.get("seeded", False))

    def collection_summary(self) -> dict:
        items = self.data.get("items", [])
        total_items = len(items)
        collection_items = self._collection_items()
        found_item_ids = {
            item_id
            for item_id, row in collection_items.items()
            if int(row.get("found_count", 0)) > 0
        }
        found_items = len(found_item_ids)
        total_found_copies = sum(
            int(row.get("found_count", 0)) for row in collection_items.values()
        )
        rarity_map = self._rarity_map()
        item_map = self._item_map()
        rarest_item = None
        rarest_sort = None

        for item_id in found_item_ids:
            item = item_map.get(item_id)
            if not item:
                continue
            rarity = rarity_map.get(item.get("rarity_id"), {})
            rarity_weight = self._sanitize_positive_float(rarity.get("weight", 0), 0)
            item_weight = self._sanitize_positive_float(item.get("weight", 0), 0)
            sort_key = (
                rarity_weight if rarity_weight > 0 else float("inf"),
                item_weight if item_weight > 0 else float("inf"),
                str(item.get("name", "")),
            )
            if rarest_sort is None or sort_key < rarest_sort:
                rarest_sort = sort_key
                rarest_item = {
                    "item": self._clone(item),
                    "rarity": self._clone(rarity) if rarity else None,
                    "collection": self._clone(collection_items[item_id]),
                }

        completion = (found_items / total_items * 100) if total_items else 0.0
        return {
            "total_items": total_items,
            "found_items": found_items,
            "missing_items": max(0, total_items - found_items),
            "completion_percent": round(completion, 2),
            "total_found_copies": total_found_copies,
            "rarest_item": rarest_item,
        }

    def _rarity_rank(self, rarity: dict) -> float:
        weight = self._sanitize_positive_float(rarity.get("weight", 0), 0)
        return weight if weight > 0 else float("inf")

    def _roll_rarity_for_event(
        self,
        event: Optional[dict],
        minimum_luck_rolls: int = 1,
    ) -> Optional[dict]:
        rolls = int(max(1, minimum_luck_rolls))
        if event:
            rolls = max(rolls, int(max(1, event.get("rarity_luck_rolls", 1))))
        best = None
        for _ in range(rolls):
            candidate = self._roll_rarity()
            if candidate and (
                best is None or self._rarity_rank(candidate) < self._rarity_rank(best)
            ):
                best = candidate
        return best

    @staticmethod
    def _item_tags(item: dict) -> set[str]:
        tags = item.get("tags", [])
        if not isinstance(tags, list):
            return set()
        return {str(tag).strip() for tag in tags if str(tag).strip()}

    def _pick_special_item(self, item_filter) -> Optional[dict]:
        pool = []
        total_weight = 0.0
        rarity_map = self._rarity_map()
        for item in self.data.get("items", []):
            if not item_filter(item):
                continue
            weight = self._sanitize_positive_float(item.get("weight", 0), 0)
            rarity = rarity_map.get(item.get("rarity_id"))
            if rarity:
                weight *= max(1.0, self._sanitize_positive_float(rarity.get("weight", 1), 1))
            if weight <= 0:
                continue
            total_weight += weight
            pool.append((item, total_weight))
        return self._pick_item_from_pool(pool, total_weight, self._rng)

    def _pick_abyss_unique(self, event: dict) -> Optional[dict]:
        tags = {
            str(tag).strip()
            for tag in event.get("unique_tags", [])
            if str(tag).strip()
        } or {"abyss"}

        def matches(item: dict) -> bool:
            item_tags = self._item_tags(item)
            return bool(item.get("is_unique") or "unique" in item_tags) and bool(
                tags.intersection(item_tags)
            )

        return self._pick_special_item(matches)

    def _drop_market_score(self, drop: dict) -> float:
        item = drop.get("item") or {}
        rarity_map = self._rarity_map()
        if item_has_market_price(item):
            settings = self.data["settings"].get("market", {})
            reference_id = settings.get("reference_currency_id", "chaos_orb")
            reference_item = self._item_map().get(reference_id)
            return market_price_chaos(
                item,
                self.data.setdefault("market", {}),
                reference_item,
                rarity_map,
            )
        effective = self._item_effective_weight(item)
        return 1.0 / max(0.000001, effective)

    def _is_hidden_drop(self, rarity_id: str, item_id: str, qty: int = 1) -> bool:
        filters = self.data["settings"].get("filters", {})
        return is_hidden_drop(filters, self._rarity_map(), rarity_id, item_id, qty)

    def _validate_rarity_weights(self) -> Tuple[bool, str]:
        if not self.data["rarities"]:
            return False, "Добавьте хотя бы одну редкость"

        total_weight = 0.0
        for rarity in self.data["rarities"]:
            self._ensure_rarity_defaults(rarity)
            if rarity["weight"] < 0:
                return (
                    False,
                    f"У редкости {rarity['name']} вес не может быть отрицательным",
                )
            total_weight += rarity["weight"]

        if total_weight <= 0:
            return False, "Сумма весов редкостей должна быть больше 0"
        return True, "ok"

    def normalize_rarity_ranges(self) -> dict:
        rarities = self.data["rarities"]
        if not rarities:
            return {"ok": False, "message": "Нет редкостей для нормализации"}

        equal_weight = round(100 / len(rarities), 3)
        for rarity in rarities:
            rarity["weight"] = equal_weight

        self._append_history(
            "normalize_rarity_ranges",
            {"count": len(rarities), "mode": "equal_weights"},
        )
        self.save()
        return {"ok": True, "state": self.state()}

    def level_progress(self) -> dict:
        return calculate_level_progress(
            self.data.setdefault("stats", {}),
            self.data.setdefault("settings", {}),
        )

    def open_case(
        self,
        times: int = 1,
        *,
        record_case_stats: bool = True,
        history_action: Optional[str] = "open_case",
        reward_luck_rolls: int = 1,
    ) -> dict:
        times = max(1, int(times))
        settings = self.data["settings"]
        stats = self.data.setdefault("stats", {})
        stats.setdefault("total_opened", 0)
        stats.setdefault("total_spent", 0)
        stats.setdefault("by_rarity", {})

        include_raw_results = times <= MAX_RAW_RESULTS
        result = []
        visible_result = []
        history_sample = []
        hidden_results_count = 0
        grouped_visible = []
        grouped_visible_open: Dict[Tuple[str, str], dict] = {}
        opened_count = 0
        collection_timestamp = int(self._time_provider())

        weights_by_rarity, totals_by_rarity = build_item_pools(self.data["items"])
        currency_weights_by_rarity, currency_totals_by_rarity = build_item_pools(
            self.data["items"],
            lambda item: bool(item.get("is_currency")),
        )
        drop_events_pool, drop_events_total = self._build_drop_events_pool()

        for _ in range(times):
            drop_event = self._pick_drop_event(drop_events_pool, drop_events_total)
            drop_multiplier = int(drop_event.get("multiplier", 1)) if drop_event else 1
            drop_multiplier = max(1, drop_multiplier)
            rolls = int(max(1, (drop_event or {}).get("rolls", 1)))
            currency_bias = self._sanitize_positive_float(
                (drop_event or {}).get("currency_bias", 1.0),
                1.0,
            )
            currency_only = bool((drop_event or {}).get("currency_only", False))
            encounter_drops = []

            for _roll_index in range(rolls):
                rarity = self._roll_rarity_for_event(drop_event, reward_luck_rolls)
                if not rarity:
                    continue

                use_currency_pool = currency_only
                if not use_currency_pool and currency_bias > 1:
                    chance = min(0.85, (currency_bias - 1.0) / currency_bias)
                    use_currency_pool = self._rng.uniform(0, 1) < chance

                item = None
                if use_currency_pool:
                    item = self._pick_item_from_pool(
                        currency_weights_by_rarity.get(rarity["id"]),
                        currency_totals_by_rarity.get(rarity["id"], 0.0),
                        self._rng,
                    )
                if not item:
                    item = self._pick_item_from_pool(
                        weights_by_rarity.get(rarity["id"]),
                        totals_by_rarity.get(rarity["id"], 0.0),
                        self._rng,
                    )
                if not item and currency_only:
                    item = self._pick_special_item(
                        lambda candidate: bool(candidate.get("is_currency"))
                    )
                    if item:
                        rarity = self._rarity_map().get(item.get("rarity_id"), rarity)
                if not item:
                    continue

                encounter_drops.append(
                    {
                        "rarity": rarity,
                        "item": item,
                        "qty": drop_multiplier,
                        "drop_event": drop_event,
                    }
                )

            unique_chance = self._sanitize_positive_float(
                (drop_event or {}).get("unique_chance", 0.0),
                0.0,
            )
            if unique_chance > 0 and self._rng.uniform(0, 1) < unique_chance:
                unique_item = self._pick_abyss_unique(drop_event or {})
                if unique_item:
                    unique_rarity = self._rarity_map().get(unique_item["rarity_id"])
                    if unique_rarity:
                        encounter_drops.append(
                            {
                                "rarity": unique_rarity,
                                "item": unique_item,
                                "qty": 1,
                                "drop_event": drop_event,
                            }
                        )

            if (drop_event or {}).get("duplicate_best") and encounter_drops:
                best_drop = max(encounter_drops, key=self._drop_market_score)
                encounter_drops.append(
                    {
                        "rarity": best_drop["rarity"],
                        "item": best_drop["item"],
                        "qty": best_drop["qty"],
                        "drop_event": {
                            **(drop_event or {}),
                            "mirrored_duplicate": True,
                        },
                    }
                )

            if not encounter_drops:
                continue

            opened_count += 1
            if record_case_stats:
                stats["total_opened"] += 1
                stats["total_spent"] += settings["open_price"]
            else:
                stats["total_rewards"] = int(stats.get("total_rewards", 0)) + 1

            for drop in encounter_drops:
                rarity = drop["rarity"]
                item = drop["item"]
                qty = max(1, int(drop.get("qty", 1)))

                self.data["inventory"][item["id"]] = (
                    self.data["inventory"].get(item["id"], 0) + qty
                )
                self._record_collection_drop(item["id"], qty, collection_timestamp)
                stats["by_rarity"][rarity["id"]] = (
                    stats["by_rarity"].get(rarity["id"], 0) + qty
                )
                self._record_market_supply(item["id"], qty)

                drop["hidden_by_filter"] = self._is_hidden_drop(
                    rarity["id"], item["id"], qty
                )
                if len(history_sample) < 100:
                    history_sample.append(drop)
                if include_raw_results:
                    result.append(drop)
                    if not drop["hidden_by_filter"]:
                        visible_result.append(drop)

                group_key = (item["id"], rarity["id"])
                stack_max_size = max(1, int(rarity.get("stack_max_size", 1)))
                qty_left = qty
                while qty_left > 0:
                    group = grouped_visible_open.get(group_key)
                    if not group or group["qty"] >= stack_max_size:
                        group = {
                            "item": item,
                            "rarity": rarity,
                            "source_rarity_id": rarity["id"],
                            "qty": 0,
                            "drop_event": drop.get("drop_event"),
                        }
                        grouped_visible.append(group)
                        grouped_visible_open[group_key] = group

                    free_space = stack_max_size - group["qty"]
                    add_qty = min(free_space, qty_left)
                    group["qty"] += add_qty
                    group["rarity"] = self._get_display_rarity_for_stack(
                        rarity, group["qty"]
                    )
                    qty_left -= add_qty

        filtered_grouped_visible = []
        for group in grouped_visible:
            source_rarity_id = group.get("source_rarity_id") or group["item"].get(
                "rarity_id"
            )
            item_id = group["item"]["id"]
            group_qty = group.get("qty", 1)
            if not self._is_hidden_drop(source_rarity_id, item_id, group_qty):
                filtered_grouped_visible.append(group)
            else:
                hidden_results_count += group_qty

        if history_action:
            self._append_history(
                history_action,
                {
                    "times": times,
                    "results": history_sample,
                    "count_results": opened_count,
                },
            )
        self.save()
        return {
            "ok": True,
            "results": result,
            "visible_results": visible_result,
            "grouped_visible_results": filtered_grouped_visible,
            "hidden_results_count": hidden_results_count,
            "drop_events_used": [
                event
                for event in self.data["settings"].get("drop_events", [])
                if event.get("weight", 0) > 0
            ],
            "state": self.state(),
        }

    def start_focus_session(self, payload: dict) -> dict:
        focus = self._focus_state()
        if focus.get("active_session"):
            return {
                "ok": False,
                "message": "Уже есть активная фокус-сессия",
            }

        payload = payload if isinstance(payload, dict) else {}
        try:
            duration_minutes = int(payload.get("duration_minutes", 25))
        except (TypeError, ValueError):
            duration_minutes = 25
        duration_minutes = max(1, min(180, duration_minutes))
        task_title = str(payload.get("task_title") or "").strip()
        if not task_title:
            task_title = "Фокус-сессия"
        task_title = task_title[:120]

        started_at = int(self._time_provider())
        self._sync_focus_chain_expiration(focus, started_at)
        session = {
            "id": self._id_factory(),
            "task_title": task_title,
            "duration_minutes": duration_minutes,
            "started_at": started_at,
            "ends_at": started_at + duration_minutes * 60,
            "status": "active",
        }
        focus["active_session"] = session
        self._append_history("start_focus_session", session)
        self.save()
        return {"ok": True, "session": self._clone(session), "state": self.state()}

    def cancel_focus_session(self, session_id: str) -> dict:
        focus = self._focus_state()
        active = focus.get("active_session")
        if not active or active.get("id") != session_id:
            return {"ok": False, "message": "Активная сессия не найдена"}

        now = int(self._time_provider())
        started_at = int(
            max(0, self._sanitize_positive_float(active.get("started_at", now), now))
        )
        elapsed_seconds = max(0, now - started_at)
        chain_preserved = elapsed_seconds < CANCEL_CHAIN_GRACE_SECONDS

        focus["active_session"] = None
        if not chain_preserved:
            focus["focus_streak"] = 0
            focus["chain_started_at"] = 0
            focus["last_completed_at"] = 0
        self._append_history(
            "cancel_focus_session",
            {
                "id": active.get("id"),
                "task_title": active.get("task_title", ""),
                "duration_minutes": active.get("duration_minutes", 0),
                "cancelled_at": now,
                "elapsed_seconds": elapsed_seconds,
                "chain_preserved": chain_preserved,
            },
        )
        self.save()
        return {"ok": True, "state": self.state()}

    def _claim_completed_daily_quests(self, date_key: str) -> tuple[list[dict], int]:
        focus = self._focus_state()
        claims_by_date = focus.setdefault("quest_claims", {})
        claimed = set(claims_by_date.get(date_key, []))
        newly_claimed = []
        bonus_rolls = 0
        for status in self._daily_quest_status(date_key):
            if not status["completed"] or status["id"] in claimed:
                continue
            claimed.add(status["id"])
            newly_claimed.append({**status, "claimed": True})
            bonus_rolls += int(status.get("bonus_rolls", 0))
        claims_by_date[date_key] = sorted(claimed)
        return newly_claimed, bonus_rolls

    def complete_focus_session(self, session_id: str) -> dict:
        focus = self._focus_state()
        active = focus.get("active_session")
        if not active or active.get("id") != session_id:
            return {"ok": False, "message": "Активная сессия не найдена"}

        now = int(self._time_provider())
        ends_at = int(active.get("ends_at", 0))
        if now < ends_at:
            seconds_left = ends_at - now
            return {
                "ok": False,
                "message": f"Сессия еще идет: осталось {seconds_left} сек.",
                "seconds_left": seconds_left,
            }

        duration_minutes = int(max(1, active.get("duration_minutes", 1)))
        started_at = int(active.get("started_at", 0))
        chain_settings = self._focus_chain_settings()
        continued_chain, chain_gap_seconds, chain_deadline_at = (
            self._session_continues_chain(focus, started_at, chain_settings)
        )
        previous_chain = int(focus.get("focus_streak", 0)) if continued_chain else 0
        chain_count = previous_chain + 1
        chain_started_at = int(focus.get("chain_started_at", 0)) if continued_chain else 0
        if chain_started_at <= 0:
            chain_started_at = started_at or now
        raw_chain_bonus_rolls = self._chain_bonus_rolls(chain_count, chain_settings)
        raw_chain_luck_rolls = self._chain_luck_rolls(chain_count, chain_settings)

        today = self._today_key(now)
        today_row = self._today_focus_row(today)
        reward_limits = self._apply_focus_chain_limits(
            raw_chain_bonus_rolls,
            raw_chain_luck_rolls,
            duration_minutes,
            today_row,
            chain_settings,
        )
        chain_bonus_rolls = reward_limits["chain_bonus_rolls"]
        chain_luck_rolls = reward_limits["chain_luck_rolls"]
        length_bonus_rolls = reward_limits["length_bonus_rolls"]

        focus["active_session"] = None
        focus["focus_streak"] = chain_count
        focus["best_focus_streak"] = max(
            int(focus.get("best_focus_streak", 0)),
            int(focus.get("focus_streak", 0)),
        )
        focus["last_completed_at"] = now
        focus["chain_started_at"] = chain_started_at

        today_row["minutes"] = int(today_row.get("minutes", 0)) + duration_minutes
        today_row["sessions"] = int(today_row.get("sessions", 0)) + 1
        if reward_limits["short_session"]:
            today_row["short_sessions"] = int(today_row.get("short_sessions", 0)) + 1
        else:
            today_row.setdefault("short_sessions", int(today_row.get("short_sessions", 0)))
        today_row["chain_bonus_rolls"] = (
            int(today_row.get("chain_bonus_rolls", 0)) + chain_bonus_rolls
        )

        stats = self.data.setdefault("stats", {})
        stats["total_focus_minutes"] = int(stats.get("total_focus_minutes", 0)) + duration_minutes
        stats["completed_focus_sessions"] = int(
            stats.get("completed_focus_sessions", 0)
        ) + 1

        claimed_quests, quest_bonus_rolls = self._claim_completed_daily_quests(today)
        completed_count = int(stats.get("completed_focus_sessions", 0))
        long_break_suggested = completed_count % 4 == 0
        reward_luck_rolls = chain_luck_rolls
        reward_rolls = (
            1
            + quest_bonus_rolls
            + (1 if long_break_suggested else 0)
            + chain_bonus_rolls
            + length_bonus_rolls
        )

        session_record = {
            "id": active.get("id"),
            "task_title": active.get("task_title", "Фокус-сессия"),
            "duration_minutes": duration_minutes,
            "started_at": started_at,
            "completed_at": now,
            "reward_rolls": reward_rolls,
            "chain_count": chain_count,
            "chain_bonus_rolls": chain_bonus_rolls,
            "chain_bonus_rolls_raw": raw_chain_bonus_rolls,
            "chain_luck_rolls": chain_luck_rolls,
            "chain_luck_rolls_raw": raw_chain_luck_rolls,
            "length_bonus_rolls": length_bonus_rolls,
            "short_session": reward_limits["short_session"],
        }
        focus.setdefault("completed_sessions", []).insert(0, session_record)
        focus["completed_sessions"] = focus["completed_sessions"][:200]
        self._refresh_focus_summary()

        reward = self.open_case(
            reward_rolls,
            record_case_stats=False,
            history_action=None,
            reward_luck_rolls=reward_luck_rolls,
        )
        metadata = {
            "session": session_record,
            "reward_rolls": reward_rolls,
            "reward_luck_rolls": reward_luck_rolls,
            "claimed_quests": claimed_quests,
            "long_break_suggested": long_break_suggested,
            "chain": {
                "count": chain_count,
                "continued": continued_chain,
                "gap_minutes": round(chain_gap_seconds / 60, 1),
                "break_window_minutes": int(chain_settings["break_window_minutes"]),
                "chain_started_at": chain_started_at,
                "previous_deadline_at": chain_deadline_at,
                "next_deadline_at": now
                + int(chain_settings["break_window_minutes"]) * 60,
                "bonus_rolls": chain_bonus_rolls,
                "raw_bonus_rolls": raw_chain_bonus_rolls,
                "luck_rolls": chain_luck_rolls,
                "raw_luck_rolls": raw_chain_luck_rolls,
            },
            "anti_farm": {
                "short_session": reward_limits["short_session"],
                "short_sessions_today": int(today_row.get("short_sessions", 0)),
                "short_session_limit": int(chain_settings["short_session_daily_limit"]),
                "short_session_minutes": int(chain_settings["short_session_minutes"]),
                "short_session_multiplier": reward_limits["short_session_multiplier"],
                "daily_chain_bonus_cap": reward_limits["daily_chain_bonus_cap"],
                "daily_chain_bonus_used": int(today_row.get("chain_bonus_rolls", 0)),
                "daily_chain_bonus_left": max(
                    0,
                    int(chain_settings["daily_chain_bonus_roll_cap"])
                    - int(today_row.get("chain_bonus_rolls", 0)),
                ),
                "daily_cap_hit": reward_limits["daily_cap_hit"],
                "length_bonus_rolls": length_bonus_rolls,
                "scaled_chain_bonus_rolls": reward_limits["scaled_chain_bonus_rolls"],
                "scaled_chain_luck_rolls": reward_limits["scaled_chain_luck_rolls"],
            },
        }
        self._append_history("complete_focus_session", metadata)
        self.save()
        reward.update(
            {
                "focus_reward": metadata,
                "state": self.state(),
            }
        )
        return reward

    def export_preset(self) -> dict:
        settings = self.data.setdefault("settings", {})
        preset = {
            "schema_version": 1,
            "name": "Custom Loot Preset",
            "rarities": self._clone(self.data.get("rarities", [])),
            "items": self._clone(self.data.get("items", [])),
            "settings": {
                "drop_events": self._clone(settings.get("drop_events", [])),
                "drop_visuals": self._clone(settings.get("drop_visuals", {})),
            },
        }
        return {"ok": True, "preset": preset}

    def import_preset(self, payload: Any) -> dict:
        raw = payload
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {"ok": False, "message": "Не удалось прочитать JSON пресета"}
        if isinstance(raw, dict) and isinstance(raw.get("preset"), dict):
            raw = raw["preset"]
        if not isinstance(raw, dict):
            return {"ok": False, "message": "Некорректный формат пресета"}

        rarities = self._clone(raw.get("rarities", []))
        items = self._clone(raw.get("items", []))
        if not isinstance(rarities, list) or not rarities:
            return {"ok": False, "message": "В пресете должна быть хотя бы одна редкость"}
        if not isinstance(items, list):
            return {"ok": False, "message": "Список предметов в пресете поврежден"}

        snapshot = self._clone(
            {
                "rarities": self.data.get("rarities", []),
                "items": self.data.get("items", []),
                "inventory": self.data.get("inventory", {}),
                "collection": self.data.get("collection", {}),
                "settings": self.data.get("settings", {}),
                "market": self.data.get("market", {}),
            }
        )
        try:
            for rarity in rarities:
                if not isinstance(rarity, dict) or not str(rarity.get("id", "")).strip():
                    raise ValueError("bad_rarity")
                self._ensure_rarity_defaults(rarity)
                rarity.setdefault("name", rarity["id"])
                rarity.setdefault("color", "#888888")
                rarity.setdefault("drop_sound", "")

            rarity_ids = {rarity["id"] for rarity in rarities}
            for item in items:
                if not isinstance(item, dict) or not str(item.get("id", "")).strip():
                    raise ValueError("bad_item")
                if item.get("rarity_id") not in rarity_ids:
                    raise ValueError("bad_item_rarity")
                normalize_item(item)
                item["name"] = str(item.get("name") or item["id"])
                item["weight"] = self._sanitize_positive_float(item.get("weight", 1), 1)

            self.data["rarities"] = rarities
            self.data["items"] = items
            settings = self.data.setdefault("settings", {})
            raw_settings = raw.get("settings", {})
            if not isinstance(raw_settings, dict):
                raw_settings = {}
            if "drop_events" in raw_settings:
                settings["drop_events"] = normalize_drop_events(
                    raw_settings.get("drop_events")
                )
            if "drop_visuals" in raw_settings:
                settings["drop_visuals"] = normalize_drop_visuals(
                    raw_settings.get("drop_visuals")
                )

            valid_ids = {item["id"] for item in items}
            self.data["inventory"] = {
                item_id: qty
                for item_id, qty in self.data.get("inventory", {}).items()
                if item_id in valid_ids
            }
            self.data["collection"] = normalize_collection(self.data.get("collection"))
            for item_id in list(self.data["collection"].get("items", {}).keys()):
                if item_id not in valid_ids:
                    self.data["collection"]["items"].pop(item_id, None)
            self.data["settings"]["filters"] = normalize_filters(
                self.data["settings"].get("filters")
            )
            self.data["settings"]["filters"]["item_hidden"] = {
                item_id: hidden
                for item_id, hidden in self.data["settings"]["filters"]
                .get("item_hidden", {})
                .items()
                if item_id in valid_ids
            }
            self.data["settings"]["filters"]["rarity_hidden"] = {
                rarity_id: hidden
                for rarity_id, hidden in self.data["settings"]["filters"]
                .get("rarity_hidden", {})
                .items()
                if rarity_id in rarity_ids
            }
            self.data["market"] = normalize_market_state(self.data.get("market"))
            initialize_market_prices(
                self.data["market"],
                self.data["settings"].get("market", {}),
                self.data["items"],
                self._rarity_map(),
            )
        except (KeyError, TypeError, ValueError):
            self.data.update(snapshot)
            return {"ok": False, "message": "Пресет содержит несовместимые данные"}

        valid, msg = self._validate_rarity_weights()
        if not valid:
            self.data.update(snapshot)
            return {"ok": False, "message": msg}

        self._append_history(
            "import_preset",
            {
                "rarities": len(rarities),
                "items": len(items),
                "name": raw.get("name", ""),
            },
        )
        self.save()
        return {"ok": True, "state": self.state()}

    def add_rarity(self, payload: dict) -> dict:
        rarity = asdict(
            Rarity(
                id=self._id_factory(),
                name=payload["name"],
                weight=self._sanitize_positive_float(payload.get("weight", 1), 1),
                color=payload.get("color", "#888888"),
                drop_sound=payload.get("drop_sound", ""),
                drop_bg_color=payload.get("drop_bg_color", "#0f172a"),
                drop_text_color=payload.get("drop_text_color", "#e4ecfb"),
                drop_border_color=payload.get(
                    "drop_border_color",
                    payload.get("color", "#3b82f6"),
                ),
                drop_box_width=int(payload.get("drop_box_width", 260)),
                drop_box_height=int(payload.get("drop_box_height", 60)),
                drop_font_size=int(payload.get("drop_font_size", 18)),
                stack_max_size=int(payload.get("stack_max_size", 10)),
                stack_display_max=int(payload.get("stack_display_max", 99)),
                stack_rarity_upgrades=self._normalize_stack_rarity_upgrades(
                    payload.get("stack_rarity_upgrades", [])
                ),
            )
        )
        self._ensure_rarity_defaults(rarity)
        self.data["rarities"].append(rarity)
        valid, msg = self._validate_rarity_weights()
        if not valid:
            self.data["rarities"].pop()
            return {"ok": False, "message": msg}

        self._append_history("add_rarity", rarity)
        self.save()
        return {"ok": True, "state": self.state()}

    def update_rarity(self, rarity_id: str, payload: dict) -> dict:
        for rarity in self.data["rarities"]:
            if rarity["id"] != rarity_id:
                continue

            rarity["name"] = payload.get("name", rarity["name"])
            rarity["weight"] = self._sanitize_positive_float(
                payload.get("weight", rarity.get("weight", 0)),
                rarity.get("weight", 0),
            )
            rarity["color"] = payload.get("color", rarity["color"])
            rarity["drop_sound"] = payload.get(
                "drop_sound",
                rarity.get("drop_sound", ""),
            )
            rarity["drop_bg_color"] = payload.get(
                "drop_bg_color",
                rarity.get("drop_bg_color", "#0f172a"),
            )
            rarity["drop_text_color"] = payload.get(
                "drop_text_color",
                rarity.get("drop_text_color", "#e4ecfb"),
            )
            rarity["drop_border_color"] = payload.get(
                "drop_border_color",
                rarity.get("drop_border_color", rarity["color"]),
            )
            rarity["drop_box_width"] = int(
                payload.get("drop_box_width", rarity.get("drop_box_width", 260))
            )
            rarity["drop_box_height"] = int(
                payload.get("drop_box_height", rarity.get("drop_box_height", 60))
            )
            rarity["drop_font_size"] = int(
                payload.get("drop_font_size", rarity.get("drop_font_size", 18))
            )
            rarity["stack_max_size"] = int(
                payload.get("stack_max_size", rarity.get("stack_max_size", 10))
            )
            rarity["stack_display_max"] = int(
                payload.get(
                    "stack_display_max",
                    rarity.get("stack_display_max", 99),
                )
            )
            if "stack_rarity_upgrades" in payload:
                rarity["stack_rarity_upgrades"] = self._normalize_stack_rarity_upgrades(
                    payload.get("stack_rarity_upgrades", [])
                )
            self._ensure_rarity_defaults(rarity)

            valid, msg = self._validate_rarity_weights()
            if not valid:
                return {"ok": False, "message": msg}

            self._append_history("update_rarity", rarity)
            self.save()
            return {"ok": True, "state": self.state()}

        return {"ok": False, "message": "Редкость не найдена"}

    def update_rarities_bulk(self, rows: list[dict]) -> dict:
        rarity_map = self._rarity_map()
        snapshot = self._clone(self.data["rarities"])
        try:
            for row in rows:
                rarity = rarity_map.get(row["id"])
                if not rarity:
                    continue
                rarity["name"] = row.get("name", rarity["name"])
                rarity["weight"] = self._sanitize_positive_float(
                    row.get("weight", rarity.get("weight", 0)),
                    rarity.get("weight", 0),
                )
                rarity["color"] = row.get("color", rarity["color"])
                rarity["drop_sound"] = row.get(
                    "drop_sound",
                    rarity.get("drop_sound", ""),
                )
                rarity["drop_bg_color"] = row.get(
                    "drop_bg_color",
                    rarity.get("drop_bg_color", "#0f172a"),
                )
                rarity["drop_text_color"] = row.get(
                    "drop_text_color",
                    rarity.get("drop_text_color", "#e4ecfb"),
                )
                rarity["drop_border_color"] = row.get(
                    "drop_border_color",
                    rarity.get("drop_border_color", rarity["color"]),
                )
                rarity["drop_box_width"] = int(
                    row.get("drop_box_width", rarity.get("drop_box_width", 260))
                )
                rarity["drop_box_height"] = int(
                    row.get("drop_box_height", rarity.get("drop_box_height", 60))
                )
                rarity["drop_font_size"] = int(
                    row.get("drop_font_size", rarity.get("drop_font_size", 18))
                )
                rarity["stack_max_size"] = int(
                    row.get("stack_max_size", rarity.get("stack_max_size", 10))
                )
                rarity["stack_display_max"] = int(
                    row.get(
                        "stack_display_max",
                        rarity.get("stack_display_max", 99),
                    )
                )
                if "stack_rarity_upgrades" in row:
                    rarity["stack_rarity_upgrades"] = (
                        self._normalize_stack_rarity_upgrades(
                            row.get("stack_rarity_upgrades", [])
                        )
                    )
                self._ensure_rarity_defaults(rarity)

            valid, msg = self._validate_rarity_weights()
            if not valid:
                self.data["rarities"] = snapshot
                return {"ok": False, "message": msg}
        except (KeyError, TypeError, ValueError):
            self.data["rarities"] = snapshot
            return {"ok": False, "message": "Ошибка в данных массового обновления редкостей"}

        self._append_history("update_rarities_bulk", {"count": len(rows)})
        self.save()
        return {"ok": True, "state": self.state()}

    def delete_rarity(self, rarity_id: str) -> dict:
        if any(item["rarity_id"] == rarity_id for item in self.data["items"]):
            return {
                "ok": False,
                "message": "Нельзя удалить редкость, пока есть связанные предметы",
            }

        before = len(self.data["rarities"])
        self.data["rarities"] = [
            rarity for rarity in self.data["rarities"] if rarity["id"] != rarity_id
        ]
        if len(self.data["rarities"]) == before:
            return {"ok": False, "message": "Редкость не найдена"}

        self.data["settings"].get("filters", {}).get("rarity_hidden", {}).pop(
            rarity_id,
            None,
        )
        self._append_history("delete_rarity", {"rarity_id": rarity_id})
        self.save()
        return {"ok": True, "state": self.state()}

    def add_item(self, payload: dict) -> dict:
        if payload["rarity_id"] not in self._rarity_map():
            return {"ok": False, "message": "Указанная редкость не существует"}

        weight = float(payload.get("weight", 1))
        if weight < 0:
            return {"ok": False, "message": "Вес предмета не может быть отрицательным"}

        item = asdict(
            Item(
                id=self._id_factory(),
                name=payload["name"],
                rarity_id=payload["rarity_id"],
                weight=weight,
                image_path=payload.get("image_path", ""),
                description=payload.get("description", ""),
                is_currency=bool(payload.get("is_currency", False)),
            )
        )
        self.data["items"].append(item)
        self._append_history("add_item", item)
        self.save()
        return {"ok": True, "state": self.state()}

    def update_item(self, item_id: str, payload: dict) -> dict:
        rarity_map = self._rarity_map()
        for item in self.data["items"]:
            if item["id"] != item_id:
                continue

            if "rarity_id" in payload and payload["rarity_id"] not in rarity_map:
                return {"ok": False, "message": "Указанная редкость не существует"}

            weight = float(payload.get("weight", item["weight"]))
            if weight < 0:
                return {"ok": False, "message": "Вес предмета не может быть отрицательным"}

            item["name"] = payload.get("name", item["name"])
            item["rarity_id"] = payload.get("rarity_id", item["rarity_id"])
            item["weight"] = weight
            item["image_path"] = payload.get("image_path", item["image_path"])
            item["description"] = payload.get("description", item["description"])
            item["is_currency"] = bool(
                payload.get("is_currency", item.get("is_currency", False))
            )
            self._append_history("update_item", item)
            self.save()
            return {"ok": True, "state": self.state()}

        return {"ok": False, "message": "Предмет не найден"}

    def update_items_bulk(self, rows: list[dict]) -> dict:
        item_map = self._item_map()
        rarity_map = self._rarity_map()
        snapshot = self._clone(self.data["items"])
        try:
            for row in rows:
                item = item_map.get(row["id"])
                if not item:
                    continue
                rarity_id = row.get("rarity_id", item["rarity_id"])
                if rarity_id not in rarity_map:
                    raise ValueError("bad_rarity")

                weight = float(row.get("weight", item["weight"]))
                if weight < 0:
                    raise ValueError("bad_weight")

                item["name"] = row.get("name", item["name"])
                item["rarity_id"] = rarity_id
                item["weight"] = weight
                item["image_path"] = row.get("image_path", item.get("image_path", ""))
                item["description"] = row.get(
                    "description",
                    item.get("description", ""),
                )
                item["is_currency"] = bool(
                    row.get("is_currency", item.get("is_currency", False))
                )
        except (KeyError, TypeError, ValueError):
            self.data["items"] = snapshot
            return {"ok": False, "message": "Ошибка в данных массового обновления предметов"}

        self._append_history("update_items_bulk", {"count": len(rows)})
        self.save()
        return {"ok": True, "state": self.state()}

    def delete_item(self, item_id: str) -> dict:
        before = len(self.data["items"])
        self.data["items"] = [item for item in self.data["items"] if item["id"] != item_id]
        if len(self.data["items"]) == before:
            return {"ok": False, "message": "Предмет не найден"}

        self.data["inventory"].pop(item_id, None)
        self.data["settings"].get("filters", {}).get("item_hidden", {}).pop(
            item_id,
            None,
        )
        self.data.setdefault("market", {}).setdefault("prices", {}).pop(item_id, None)
        self.data.setdefault("market", {}).setdefault("recent_drops", {}).pop(item_id, None)
        self.data.setdefault("market", {}).setdefault("recent_purchases", {}).pop(
            item_id,
            None,
        )
        self.data.setdefault("collection", {}).setdefault("items", {}).pop(
            item_id,
            None,
        )
        self._append_history("delete_item", {"item_id": item_id})
        self.save()
        return {"ok": True, "state": self.state()}

    def adjust_inventory(self, item_id: str, delta: int) -> dict:
        if item_id not in self._item_map():
            return {"ok": False, "message": "Предмет не найден"}

        delta = int(delta)
        if delta >= 0:
            return {
                "ok": False,
                "message": "Разрешено только списание предметов из инвентаря",
            }

        current_value = self.data["inventory"].get(item_id, 0)
        new_value = current_value + delta
        if new_value < 0:
            return {"ok": False, "message": "Недостаточно предметов в инвентаре"}

        if new_value == 0:
            self.data["inventory"].pop(item_id, None)
        else:
            self.data["inventory"][item_id] = new_value

        self._append_history("consume_item", {"item_id": item_id, "delta": delta})
        self.save()
        return {"ok": True, "state": self.state()}

    def clear_inventory(self) -> dict:
        self.data["inventory"] = {}
        self._append_history("clear_inventory", {})
        self.save()
        return {"ok": True, "state": self.state()}

    def purchase_item(self, item_id: str, currency_item_id: str, quantity: int = 1) -> dict:
        quantity = int(quantity)
        if quantity < 1:
            return {"ok": False, "message": "Количество покупки должно быть не меньше 1"}

        item_map = self._item_map()
        target_item = item_map.get(item_id)
        currency_item = item_map.get(currency_item_id)
        if not target_item:
            return {"ok": False, "message": "Покупаемый предмет не найден"}
        if not currency_item:
            return {"ok": False, "message": "Валюта не найдена"}
        if not currency_item.get("is_currency", False):
            return {"ok": False, "message": "Выбранный предмет не является валютой"}

        offer = self._compute_shop_offer(target_item, currency_item)
        min_quantity = offer["min_quantity"]
        bundle_price = offer["bundle_price"]
        if quantity % min_quantity != 0:
            return {
                "ok": False,
                "message": f"Минимальная покупка для этого предмета: {min_quantity} шт.",
            }

        bundles_count = quantity // min_quantity
        total_price = bundle_price * bundles_count
        current_currency = int(self.data["inventory"].get(currency_item_id, 0))
        if current_currency < total_price:
            return {
                "ok": False,
                "message": f"Недостаточно валюты: нужно {total_price}, доступно {current_currency}",
            }

        next_currency = current_currency - total_price
        if next_currency == 0:
            self.data["inventory"].pop(currency_item_id, None)
        else:
            self.data["inventory"][currency_item_id] = next_currency

        self.data["inventory"][item_id] = int(self.data["inventory"].get(item_id, 0)) + quantity
        self._record_market_demand(item_id, quantity)
        self._record_market_supply(currency_item_id, total_price)
        self._append_history(
            "purchase_item",
            {
                "item_id": item_id,
                "currency_item_id": currency_item_id,
                "quantity": quantity,
                "unit_price": bundle_price,
                "total_price": total_price,
                "min_quantity": min_quantity,
            },
        )
        self.save()
        return {
            "ok": True,
            "message": f"Покупка успешна: {quantity} шт. за {total_price}",
            "price": {
                "unit": bundle_price,
                "total": total_price,
                "min_quantity": min_quantity,
            },
            "state": self.state(),
        }

    def set_filter_rarity(self, rarity_id: str, value: bool) -> dict:
        rarity_hidden = (
            self.data["settings"].setdefault("filters", {}).setdefault("rarity_hidden", {})
        )
        if value:
            rarity_hidden[rarity_id] = True
        else:
            rarity_hidden.pop(rarity_id, None)

        self._append_history("set_filter_rarity", {"rarity_id": rarity_id, "value": value})
        self.save()
        return {"ok": True, "state": self.state()}

    def set_filter_item(self, item_id: str, value: bool) -> dict:
        item_hidden = (
            self.data["settings"].setdefault("filters", {}).setdefault("item_hidden", {})
        )
        if value:
            item_hidden[item_id] = True
        else:
            item_hidden.pop(item_id, None)

        self._append_history("set_filter_item", {"item_id": item_id, "value": value})
        self.save()
        return {"ok": True, "state": self.state()}

    def update_settings(self, payload: dict) -> dict:
        settings = self.data["settings"]
        snapshot = self._clone(settings)
        try:
            for key in ("roll_min", "roll_max", "open_price"):
                if key in payload:
                    settings[key] = float(payload[key])

            levels = payload.get("levels", {})
            if levels:
                settings.setdefault("levels", LevelSettings().to_dict())
                if "base_xp" in levels:
                    settings["levels"]["base_xp"] = max(1, int(levels["base_xp"]))
                if "xp_growth" in levels:
                    settings["levels"]["xp_growth"] = max(
                        1.01,
                        float(levels["xp_growth"]),
                    )

            appearance = payload.get("appearance", {})
            if appearance:
                settings["appearance"] = normalize_appearance(
                    {
                        "theme": appearance.get(
                            "theme",
                            settings.get("appearance", {}).get("theme", "dark"),
                        )
                    }
                )

            drop_visuals = payload.get("drop_visuals", {})
            if drop_visuals:
                settings.setdefault("drop_visuals", {})
                if "spawn_cooldown_ms" in drop_visuals:
                    settings["drop_visuals"]["spawn_cooldown_ms"] = int(
                        max(
                            0,
                            self._sanitize_positive_float(
                                drop_visuals["spawn_cooldown_ms"],
                                70,
                            ),
                        )
                    )
                if "appearance_effect_enabled" in drop_visuals:
                    settings["drop_visuals"]["appearance_effect_enabled"] = bool(
                        drop_visuals["appearance_effect_enabled"]
                    )
                if "background_image_path" in drop_visuals:
                    settings["drop_visuals"]["background_image_path"] = str(
                        drop_visuals.get("background_image_path", "") or ""
                    )
                if "background_brightness" in drop_visuals:
                    brightness = self._sanitize_positive_float(
                        drop_visuals.get("background_brightness", 1.0),
                        1.0,
                    )
                    settings["drop_visuals"]["background_brightness"] = min(
                        2.0,
                        max(0.2, float(brightness or 1.0)),
                    )

            if "drop_events" in payload:
                raw_events = payload.get("drop_events")
                if not isinstance(raw_events, list):
                    raise TypeError("drop_events must be list")
                settings["drop_events"] = normalize_drop_events(raw_events)

            if "market" in payload:
                raw_market = payload.get("market")
                if not isinstance(raw_market, dict):
                    raise TypeError("market must be dict")
                settings["market"] = normalize_market_settings(raw_market)

            if "rarity_boosts" in payload:
                raw_boosts = payload.get("rarity_boosts")
                if not isinstance(raw_boosts, list):
                    raise TypeError("rarity_boosts must be list")
                settings["rarity_boosts"] = normalize_rarity_boosts(
                    raw_boosts,
                    valid_rarity_ids=self._rarity_map().keys(),
                    strict_percent=True,
                )

            if "auto_stop_conditions" in payload:
                raw_auto_stop = payload.get("auto_stop_conditions")
                if not isinstance(raw_auto_stop, list):
                    raise TypeError("auto_stop_conditions must be list")
                settings["auto_stop_conditions"] = normalize_auto_stop_conditions(
                    raw_auto_stop,
                    valid_item_ids=self._item_map().keys(),
                )

            if "focus_chain" in payload:
                raw_focus_chain = payload.get("focus_chain")
                if not isinstance(raw_focus_chain, dict):
                    raise TypeError("focus_chain must be dict")
                settings["focus_chain"] = normalize_focus_chain_settings(
                    raw_focus_chain
                )
        except (TypeError, ValueError):
            self.data["settings"] = snapshot
            return {"ok": False, "message": "Ошибка в значениях настроек"}

        valid, msg = self._validate_rarity_weights()
        if not valid:
            self.data["settings"] = snapshot
            return {"ok": False, "message": msg}

        self._append_history("update_settings", settings)
        self.save()
        return {"ok": True, "state": self.state()}

    def clear_history(self) -> dict:
        self.data["history"] = []
        self.save()
        return {"ok": True, "state": self.state()}

    def clear_collection(self) -> dict:
        self.data["collection"] = {
            "seeded_from_inventory": True,
            "items": {},
        }
        self._append_history("clear_collection", {})
        self.save()
        return {"ok": True, "state": self.state()}

    def reset_stats(self) -> dict:
        self.data["stats"] = {
            "total_opened": 0,
            "total_spent": 0,
            "total_focus_minutes": 0,
            "completed_focus_sessions": 0,
            "total_rewards": 0,
            "by_rarity": {},
        }
        self._append_history("reset_stats", {})
        self.save()
        return {"ok": True, "state": self.state()}

    def state(self) -> dict:
        market_changed = self._refresh_market()
        if market_changed:
            self.save()
        self._refresh_focus_summary()
        collection_summary = self.collection_summary()
        snapshot = self._clone(self.data)
        snapshot["rarity_probabilities"] = calculate_rarity_probabilities(
            snapshot.get("rarities", [])
        )
        snapshot["level"] = self.level_progress()
        snapshot["collection_summary"] = collection_summary
        return snapshot

    def play_rarity_sound(self, rarity_id: str) -> dict:
        rarity = self._rarity_map().get(rarity_id)
        if not rarity:
            return {"ok": False, "message": "Редкость не найдена", "played": False}

        path = rarity.get("drop_sound", "")
        if not path:
            return {"ok": True, "message": "No sound configured", "played": False}

        try:
            import winsound

            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return {"ok": True, "played": True}
        except Exception as err:
            return {"ok": False, "played": False, "message": str(err), "sound": path}
