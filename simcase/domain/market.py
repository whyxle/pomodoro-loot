from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from .calculations import compute_shop_offer, item_effective_weight
from .constants import SHOP_MARKUP


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _positive_float(value: Any, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _normal(rng: Any) -> float:
    if hasattr(rng, "gauss"):
        return float(rng.gauss(0.0, 1.0))
    u1 = max(1e-12, float(rng.uniform(0.0, 1.0)))
    u2 = float(rng.uniform(0.0, 1.0))
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def _find_reference_item(items: Sequence[dict], reference_item_id: str) -> Optional[dict]:
    if reference_item_id:
        for item in items:
            if item.get("id") == reference_item_id:
                return item
    for item in items:
        if item.get("id") == "chaos_orb":
            return item
    for item in items:
        if str(item.get("name", "")).lower() == "chaos orb":
            return item
    for item in items:
        if item.get("is_currency"):
            return item
    return items[0] if items else None


def item_has_market_price(item: dict) -> bool:
    return _positive_float(item.get("market_value_chaos"), 0.0) > 0


def intrinsic_value_chaos(
    item: dict,
    reference_item: Optional[dict],
    rarity_map: dict[str, dict],
) -> float:
    explicit = _positive_float(item.get("market_value_chaos"), 0.0)
    if explicit > 0:
        return explicit

    item_weight = item_effective_weight(item, rarity_map)
    reference_weight = (
        item_effective_weight(reference_item, rarity_map) if reference_item else 0.0
    )
    if item_weight <= 0 or reference_weight <= 0:
        return 1.0
    return _clamp(reference_weight / item_weight, 0.001, 250000.0)


def _item_market_row(
    item: dict,
    reference_item: Optional[dict],
    rarity_map: dict[str, dict],
) -> dict:
    base_value = intrinsic_value_chaos(item, reference_item, rarity_map)
    liquidity = _positive_float(item.get("market_liquidity"), 0.0)
    if liquidity <= 0:
        liquidity = _clamp(18.0 / math.sqrt(max(base_value, 0.01)), 0.25, 18.0)
    volatility = _positive_float(item.get("market_volatility"), 0.0)
    if volatility <= 0:
        volatility = _clamp(0.012 + 0.08 / math.sqrt(liquidity + 0.2), 0.012, 0.26)
    spread = _clamp(0.012 + volatility / max(1.4, liquidity * 4.5), 0.01, 0.24)
    return {
        "price_chaos": round(base_value, 6),
        "fair_value_chaos": round(base_value, 6),
        "demand": max(0.1, _positive_float(item.get("market_demand"), 1.0)),
        "supply": max(0.1, _positive_float(item.get("market_supply"), 1.0)),
        "liquidity": round(liquidity, 4),
        "volatility": round(volatility, 4),
        "spread": round(spread, 4),
        "volume": 0,
        "last_change": 0.0,
    }


def initialize_market_prices(
    market: dict,
    settings: dict,
    items: Sequence[dict],
    rarity_map: dict[str, dict],
) -> None:
    prices = market.setdefault("prices", {})
    reference_item = _find_reference_item(items, settings.get("reference_currency_id", ""))
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        row = prices.get(item_id)
        if not isinstance(row, dict):
            row = _item_market_row(item, reference_item, rarity_map)
            prices[item_id] = row
        else:
            fresh = _item_market_row(item, reference_item, rarity_map)
            for key, value in fresh.items():
                row.setdefault(key, value)

    valid_ids = {item.get("id") for item in items}
    for item_id in list(prices.keys()):
        if item_id not in valid_ids:
            prices.pop(item_id, None)

    if reference_item and reference_item.get("id") in prices:
        prices[reference_item["id"]]["price_chaos"] = 1.0
        prices[reference_item["id"]]["fair_value_chaos"] = 1.0
        prices[reference_item["id"]]["last_change"] = 0.0


def record_market_supply(market: dict, item_id: str, quantity: int) -> None:
    if quantity <= 0:
        return
    drops = market.setdefault("recent_drops", {})
    drops[item_id] = float(drops.get(item_id, 0.0)) + float(quantity)


def record_market_demand(market: dict, item_id: str, quantity: int) -> None:
    if quantity <= 0:
        return
    purchases = market.setdefault("recent_purchases", {})
    purchases[item_id] = float(purchases.get(item_id, 0.0)) + float(quantity)


def _decayed_pressure(bucket: dict, item_id: str, liquidity: float) -> float:
    quantity = _positive_float(bucket.get(item_id), 0.0)
    if quantity <= 0:
        return 0.0
    return quantity / (35.0 + liquidity * 42.0)


def _decay_recent_flow(bucket: dict) -> None:
    for item_id in list(bucket.keys()):
        next_value = _positive_float(bucket.get(item_id), 0.0) * 0.72
        if next_value < 0.05:
            bucket.pop(item_id, None)
        else:
            bucket[item_id] = round(next_value, 4)


def _advance_market_once(
    market: dict,
    settings: dict,
    items: Sequence[dict],
    rarity_map: dict[str, dict],
    rng: Any,
) -> None:
    prices = market.setdefault("prices", {})
    reference_item = _find_reference_item(items, settings.get("reference_currency_id", ""))
    reference_id = reference_item.get("id") if reference_item else ""
    recent_drops = market.setdefault("recent_drops", {})
    recent_purchases = market.setdefault("recent_purchases", {})

    sentiment = float(market.get("sentiment", 0.0))
    sentiment = _clamp(sentiment * 0.92 + _normal(rng) * 0.035, -0.65, 0.65)
    market["sentiment"] = round(sentiment, 5)

    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        row = prices.setdefault(item_id, _item_market_row(item, reference_item, rarity_map))
        baseline = intrinsic_value_chaos(item, reference_item, rarity_map)
        liquidity = max(0.2, _positive_float(row.get("liquidity"), 1.0))
        volatility = max(0.001, _positive_float(row.get("volatility"), 0.04))

        if item_id == reference_id:
            row["price_chaos"] = 1.0
            row["fair_value_chaos"] = 1.0
            row["last_change"] = 0.0
            row["volume"] = int(max(40, liquidity * 120))
            continue

        drop_pressure = _decayed_pressure(recent_drops, item_id, liquidity)
        purchase_pressure = _decayed_pressure(recent_purchases, item_id, liquidity)
        baseline_demand = max(0.1, _positive_float(item.get("market_demand"), 1.0))
        baseline_supply = max(0.1, _positive_float(item.get("market_supply"), 1.0))
        demand_target = _clamp(
            baseline_demand * (1.0 + sentiment * 0.32 + purchase_pressure),
            0.35,
            3.8,
        )
        supply_target = _clamp(
            baseline_supply * (1.0 - sentiment * 0.18 + drop_pressure),
            0.35,
            3.8,
        )

        demand = _positive_float(row.get("demand"), baseline_demand)
        supply = _positive_float(row.get("supply"), baseline_supply)
        noise_scale = 1.0 / math.sqrt(liquidity + 0.35)
        demand = _clamp(
            demand + (demand_target - demand) * 0.22 + _normal(rng) * 0.035 * noise_scale,
            0.25,
            4.2,
        )
        supply = _clamp(
            supply + (supply_target - supply) * 0.22 + _normal(rng) * 0.04 * noise_scale,
            0.25,
            4.2,
        )

        fair_value = baseline * ((demand / supply) ** 0.82)
        previous = max(0.0001, _positive_float(row.get("price_chaos"), baseline))
        mean_reversion = _clamp(0.08 + liquidity * 0.012, 0.08, 0.28)
        flow = _clamp((demand - supply) * 0.018, -0.09, 0.09)
        random_walk = _normal(rng) * volatility * noise_scale
        jump = 0.0
        jump_probability = _clamp(0.002 + volatility * 0.045 / math.sqrt(liquidity), 0.002, 0.04)
        if rng.uniform(0.0, 1.0) < jump_probability:
            jump = _normal(rng) * volatility * _clamp(1.1 / math.sqrt(liquidity), 0.35, 1.4)

        next_log = (
            math.log(previous)
            + mean_reversion * (math.log(max(0.0001, fair_value)) - math.log(previous))
            + flow
            + random_walk
            + jump
        )
        low = max(0.0001, baseline * 0.22)
        high = max(low * 1.01, baseline * 4.8)
        next_price = _clamp(math.exp(next_log), low, high)
        change = (next_price / previous) - 1.0
        volume = max(
            1,
            int(
                liquidity
                * 32
                * (demand + supply)
                * (0.75 + rng.uniform(0.0, 0.8))
                * (1.0 + min(4.0, abs(change) * 10.0))
            ),
        )
        spread = _clamp(0.012 + volatility / max(1.4, liquidity * 4.5), 0.01, 0.24)

        row.update(
            {
                "price_chaos": round(next_price, 6),
                "fair_value_chaos": round(fair_value, 6),
                "demand": round(demand, 4),
                "supply": round(supply, 4),
                "spread": round(spread, 4),
                "volume": volume,
                "last_change": round(change, 5),
            }
        )

    _decay_recent_flow(recent_drops)
    _decay_recent_flow(recent_purchases)


def refresh_market(
    market: dict,
    settings: dict,
    items: Sequence[dict],
    rarity_map: dict[str, dict],
    rng: Any,
    now: float,
) -> bool:
    initialize_market_prices(market, settings, items, rarity_map)
    if not settings.get("enabled", True):
        return False

    tick_seconds = max(5, int(settings.get("tick_seconds", 30)))
    last_tick = int(_positive_float(market.get("last_tick"), 0.0))
    if last_tick <= 0:
        market["last_tick"] = int(now)
        return True

    elapsed = int(now) - last_tick
    if elapsed < tick_seconds:
        return False

    max_ticks = max(1, int(settings.get("max_ticks_per_refresh", 240)))
    ticks = min(max_ticks, elapsed // tick_seconds)
    for _ in range(ticks):
        _advance_market_once(market, settings, items, rarity_map, rng)
    market["last_tick"] = int(now)
    return True


def market_price_chaos(
    item: dict,
    market: dict,
    reference_item: Optional[dict],
    rarity_map: dict[str, dict],
) -> float:
    row = market.get("prices", {}).get(item.get("id"), {})
    price = _positive_float(row.get("price_chaos"), 0.0)
    if price > 0:
        return price
    return intrinsic_value_chaos(item, reference_item, rarity_map)


def compute_market_shop_offer(
    target_item: dict,
    currency_item: dict,
    market: dict,
    settings: dict,
    items: Sequence[dict],
    rarity_map: dict[str, dict],
) -> dict:
    if not item_has_market_price(target_item) or not item_has_market_price(currency_item):
        return compute_shop_offer(target_item, currency_item, rarity_map)

    reference_item = _find_reference_item(items, settings.get("reference_currency_id", ""))
    target_price = market_price_chaos(target_item, market, reference_item, rarity_map)
    currency_price = market_price_chaos(currency_item, market, reference_item, rarity_map)
    if target_price <= 0 or currency_price <= 0:
        return compute_shop_offer(target_item, currency_item, rarity_map)

    prices = market.get("prices", {})
    target_spread = _positive_float(prices.get(target_item.get("id"), {}).get("spread"), 0.03)
    currency_spread = _positive_float(
        prices.get(currency_item.get("id"), {}).get("spread"),
        0.03,
    )
    effective_markup = SHOP_MARKUP + ((target_spread + currency_spread) / 2.0)
    base_cost = (target_price / currency_price) * (1.0 + effective_markup)

    if base_cost >= 1:
        return {
            "min_quantity": 1,
            "bundle_price": max(1, int(round(base_cost))),
            "market_price": round(target_price, 6),
            "currency_market_price": round(currency_price, 6),
            "spread": round(effective_markup, 4),
        }

    min_quantity = max(1, int(1 / base_cost))
    return {
        "min_quantity": min_quantity,
        "bundle_price": 1,
        "market_price": round(target_price, 6),
        "currency_market_price": round(currency_price, 6),
        "spread": round(effective_markup, 4),
    }
