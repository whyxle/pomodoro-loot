from __future__ import annotations

from typing import Callable, Optional, Protocol, Sequence

from .constants import DEFAULT_DROP_EVENTS, SHOP_MARKUP
from .models import LevelSettings
from .normalizers import ensure_rarity_defaults, sanitize_positive_float


class RandomLike(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


def build_rarity_map(rarities: Sequence[dict]) -> dict[str, dict]:
    return {rarity["id"]: rarity for rarity in rarities}


def build_item_map(items: Sequence[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def get_display_rarity_for_stack(
    base_rarity: dict,
    qty: int,
    rarity_map: dict[str, dict],
) -> dict:
    display_rarity = base_rarity
    upgrades = base_rarity.get("stack_rarity_upgrades", [])
    for rule in sorted(upgrades, key=lambda row: row.get("min_qty", 0)):
        min_qty = int(max(1, sanitize_positive_float(rule.get("min_qty", 1), 1)))
        if qty < min_qty:
            continue
        target = rarity_map.get(rule.get("target_rarity_id"))
        if target:
            display_rarity = target
    return display_rarity


def build_boosts_by_rarity(rarity_boosts: Sequence[dict]) -> dict[str, float]:
    boosts_by_rarity: dict[str, float] = {}
    for row in rarity_boosts:
        rarity_id = str(row.get("rarity_id") or "").strip()
        if not rarity_id:
            continue
        try:
            percent = float(row.get("percent", 0))
        except (TypeError, ValueError):
            continue
        boosts_by_rarity[rarity_id] = boosts_by_rarity.get(rarity_id, 0.0) + percent
    return boosts_by_rarity


def pick_from_cumulative(
    pool: Optional[list[tuple[dict, float]]],
    total_weight: float,
    rng: RandomLike,
) -> Optional[dict]:
    if not pool or total_weight <= 0:
        return None
    point = rng.uniform(0, total_weight)
    for item, cumulative_weight in pool:
        if point <= cumulative_weight:
            return item
    return pool[-1][0]


def roll_rarity(
    rarities: Sequence[dict],
    rarity_boosts: Sequence[dict],
    rng: RandomLike,
) -> Optional[dict]:
    boosts_by_rarity = build_boosts_by_rarity(rarity_boosts)
    weighted: list[tuple[dict, float]] = []
    total = 0.0
    for rarity in rarities:
        ensure_rarity_defaults(rarity)
        base_weight = sanitize_positive_float(rarity.get("weight", 0), 0)
        boost_percent = boosts_by_rarity.get(rarity["id"], 0.0)
        boosted_weight = base_weight * max(0.0, 1 + (boost_percent / 100.0))
        if boosted_weight <= 0:
            continue
        total += boosted_weight
        weighted.append((rarity, total))

    if total <= 0:
        weighted = []
        total = 0.0
        for rarity in rarities:
            ensure_rarity_defaults(rarity)
            base_weight = sanitize_positive_float(rarity.get("weight", 0), 0)
            if base_weight <= 0:
                continue
            total += base_weight
            weighted.append((rarity, total))

    return pick_from_cumulative(weighted, total, rng)


def build_item_pools(
    items: Sequence[dict],
    item_filter: Optional[Callable[[dict], bool]] = None,
) -> tuple[dict[str, list[tuple[dict, float]]], dict[str, float]]:
    pools: dict[str, list[tuple[dict, float]]] = {}
    totals: dict[str, float] = {}
    for item in items:
        if item_filter is not None and not item_filter(item):
            continue
        if item.get("weight", 0) <= 0:
            continue
        rarity_id = item["rarity_id"]
        current_total = totals.get(rarity_id, 0.0) + float(item["weight"])
        totals[rarity_id] = current_total
        pools.setdefault(rarity_id, []).append((item, current_total))
    return pools, totals


def item_effective_weight(item: dict, rarity_map: dict[str, dict]) -> float:
    rarity = rarity_map.get(item.get("rarity_id"))
    rarity_weight = sanitize_positive_float((rarity or {}).get("weight", 0), 0)
    item_weight = sanitize_positive_float(item.get("weight", 0), 0)
    return rarity_weight * item_weight


def compute_shop_unit_price(
    target_item: dict,
    currency_item: dict,
    rarity_map: dict[str, dict],
) -> int:
    target_weight = item_effective_weight(target_item, rarity_map)
    currency_weight = item_effective_weight(currency_item, rarity_map)
    if target_weight <= 0 or currency_weight <= 0:
        return 1
    base_cost = currency_weight / target_weight
    with_markup = base_cost * (1 + SHOP_MARKUP)
    return max(1, int(round(with_markup)))


def compute_shop_offer(
    target_item: dict,
    currency_item: dict,
    rarity_map: dict[str, dict],
) -> dict:
    target_weight = item_effective_weight(target_item, rarity_map)
    currency_weight = item_effective_weight(currency_item, rarity_map)
    if target_weight <= 0 or currency_weight <= 0:
        return {"min_quantity": 1, "bundle_price": 1}

    base_cost = (currency_weight / target_weight) * (1 + SHOP_MARKUP)
    if base_cost >= 1:
        return {"min_quantity": 1, "bundle_price": max(1, int(round(base_cost)))}

    min_quantity = max(1, int(1 / base_cost))
    return {"min_quantity": min_quantity, "bundle_price": 1}


def build_drop_events_pool(
    events: Sequence[dict],
) -> tuple[list[tuple[dict, float]], float]:
    cumulative = 0.0
    pool: list[tuple[dict, float]] = []
    for event in events:
        weight = sanitize_positive_float(event.get("weight", 0), 0)
        if weight <= 0:
            continue
        cumulative += weight
        pool.append((event, cumulative))
    return pool, cumulative


def pick_drop_event(
    pool: list[tuple[dict, float]],
    total_weight: float,
    rng: RandomLike,
) -> Optional[dict]:
    picked = pick_from_cumulative(pool, total_weight, rng)
    return picked or DEFAULT_DROP_EVENTS[0]


def is_hidden_drop(
    filters: dict,
    rarity_map: dict[str, dict],
    rarity_id: str,
    item_id: str,
    qty: int = 1,
) -> bool:
    base_rarity = rarity_map.get(rarity_id)
    if base_rarity and qty > 1:
        display_rarity = get_display_rarity_for_stack(base_rarity, qty, rarity_map)
        check_rarity_id = display_rarity["id"]
    else:
        check_rarity_id = rarity_id

    if filters.get("rarity_hidden", {}).get(check_rarity_id):
        return True
    if filters.get("item_hidden", {}).get(item_id):
        return True
    return False


def calculate_level_progress(stats: dict, settings: dict) -> dict:
    xp_source = stats.get("total_focus_minutes", 0) or stats.get("total_opened", 0)
    xp = int(xp_source)
    levels_cfg = settings.get("levels", LevelSettings().to_dict())
    base = max(1, int(levels_cfg.get("base_xp", 8)))
    growth = max(1.01, float(levels_cfg.get("xp_growth", 1.35)))

    level = 1
    xp_left = xp
    need = base
    while xp_left >= need:
        xp_left -= need
        level += 1
        need = int(round(base * (growth ** (level - 1))))

    progress = xp_left / need if need > 0 else 0
    return {
        "xp": xp,
        "level": level,
        "xp_in_level": xp_left,
        "xp_for_next": need,
        "progress": round(progress, 4),
    }


def calculate_rarity_probabilities(rarities: Sequence[dict]) -> dict[str, float]:
    total_weight = sum(max(0.0, float(rarity.get("weight", 0))) for rarity in rarities)
    if total_weight <= 0:
        return {}

    probabilities: dict[str, float] = {}
    for rarity in rarities:
        probabilities[rarity["id"]] = round(
            (max(0.0, float(rarity.get("weight", 0))) / total_weight) * 100,
            3,
        )
    return probabilities
