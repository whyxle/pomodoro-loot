from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

from simcase.application.simulator import CaseSimulator
from simcase.domain.constants import DATA_FILE, PROJECT_ROOT
from simcase.domain.normalizers import normalize_drop_events
from simcase.presentation.api import API
from simcase.service import CaseSimulator as LegacyCaseSimulator
from simcase.ui import HTML, INDEX_HTML_PATH, UI_DIR


def rarity_template(rarity_id: str, name: str, weight: float) -> dict:
    return {
        "id": rarity_id,
        "name": name,
        "weight": weight,
        "color": "#888888",
        "drop_sound": "",
        "drop_bg_color": "#0f172a",
        "drop_text_color": "#e4ecfb",
        "drop_border_color": "#3b82f6",
        "drop_box_width": 260,
        "drop_box_height": 60,
        "drop_font_size": 18,
        "stack_max_size": 10,
        "stack_display_max": 99,
        "stack_rarity_upgrades": [],
    }


def item_template(item_id: str, rarity_id: str, weight: float, *, is_currency: bool = False) -> dict:
    return {
        "id": item_id,
        "name": item_id,
        "rarity_id": rarity_id,
        "weight": weight,
        "image_path": "",
        "description": "",
        "is_currency": is_currency,
    }


class FlatRng:
    def uniform(self, a: float, b: float) -> float:
        return (a + b) / 2

    def gauss(self, _mean: float, _deviation: float) -> float:
        return 0.0


class MutableClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class SimulatorRegressionTests(unittest.TestCase):
    def create_simulator(self) -> CaseSimulator:
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base_path = Path(temp_dir.name) / "case_simulator_data.json"
        return CaseSimulator(str(base_path))

    def test_legacy_imports_keep_working_and_defaults_bootstrap(self):
        self.assertIs(LegacyCaseSimulator, CaseSimulator)

        simulator = self.create_simulator()
        state = simulator.state()

        self.assertEqual(4, len(state["rarities"]))
        self.assertEqual(0, len(state["items"]))
        self.assertEqual("dark", state["settings"]["appearance"]["theme"])
        self.assertEqual(1, state["level"]["level"])
        self.assertIsNone(state["focus"]["active_session"])
        self.assertEqual(0, state["focus"]["today_minutes"])
        self.assertAlmostEqual(100.0, sum(state["rarity_probabilities"].values()), places=3)
        self.assertEqual(PROJECT_ROOT, Path(DATA_FILE).parent)

    def test_pywebview_api_has_no_public_recursive_state(self):
        simulator = self.create_simulator()
        api = API(simulator=simulator)

        self.assertFalse(hasattr(api, "store"))
        self.assertFalse(hasattr(api, "dialogs"))
        self.assertEqual([], [name for name in vars(api) if not name.startswith("_")])

    def test_webview_ui_files_are_split_and_loadable(self):
        self.assertTrue(INDEX_HTML_PATH.exists())
        self.assertTrue((UI_DIR / "styles.css").exists())
        self.assertTrue((UI_DIR / "app.js").exists())
        self.assertIn('href="styles.css"', HTML)
        self.assertIn('src="app.js"', HTML)
        self.assertNotIn("<style>", HTML)
        self.assertNotIn("<script>\n", HTML)

    def test_update_settings_normalizes_payload_without_changing_contract(self):
        simulator = self.create_simulator()
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("tracked", rarity_id, 1)]
        item_id = simulator.data["items"][0]["id"]

        result = simulator.update_settings(
            {
                "appearance": {"theme": "unsupported"},
                "drop_visuals": {
                    "spawn_cooldown_ms": -50,
                    "appearance_effect_enabled": 0,
                    "background_image_path": None,
                    "background_brightness": 99,
                },
                "drop_events": [{"name": "x2", "weight": "5", "multiplier": 0}],
                "rarity_boosts": [
                    {"rarity_id": rarity_id, "percent": "25.5"},
                    {"rarity_id": "missing", "percent": 10},
                ],
                "auto_stop_conditions": [
                    {"item_id": item_id, "target_qty": 0},
                    {"item_id": "missing", "target_qty": 50},
                ],
            }
        )

        self.assertTrue(result["ok"])
        settings = result["state"]["settings"]
        self.assertEqual("dark", settings["appearance"]["theme"])
        self.assertEqual(0, settings["drop_visuals"]["spawn_cooldown_ms"])
        self.assertFalse(settings["drop_visuals"]["appearance_effect_enabled"])
        self.assertEqual("", settings["drop_visuals"]["background_image_path"])
        self.assertEqual(2.0, settings["drop_visuals"]["background_brightness"])
        self.assertEqual(
            [{"id": "event-1", "name": "x2", "weight": 5.0, "multiplier": 1}],
            settings["drop_events"],
        )
        self.assertEqual(
            [{"rarity_id": rarity_id, "percent": 25.5}],
            settings["rarity_boosts"],
        )
        self.assertEqual(
            [{"item_id": item_id, "target_qty": 1}],
            settings["auto_stop_conditions"],
        )

    def test_normalize_drop_events_repairs_corrupted_standard_names(self):
        events = normalize_drop_events(
            [
                {"id": "normal", "name": "??????? ????", "weight": 1},
                {"id": "chest", "name": "??????", "weight": 1},
                {"id": "boss", "name": "????", "weight": 1},
                {"id": "legion", "name": "??????", "weight": 1},
                {"id": "abyss", "name": "??????", "weight": 1},
                {"id": "mirror_altar", "name": "?????????? ??????", "weight": 1},
            ]
        )

        self.assertEqual(
            [
                "Обычная награда",
                "Бонусная находка",
                "Большой итог",
                "Поток идей",
                "Редкий прорыв",
                "Двойной итог",
            ],
            [event["name"] for event in events],
        )

    def test_normalize_drop_events_keeps_custom_valid_names(self):
        events = normalize_drop_events(
            [
                {"id": "custom", "name": "Моя охота", "weight": 7},
                {"id": "normal", "name": "Особый старт", "weight": 3},
            ]
        )

        self.assertEqual(["Моя охота", "Особый старт"], [event["name"] for event in events])

    def test_focus_session_requires_elapsed_time_and_rewards_completion(self):
        clock = MutableClock(1000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        started = simulator.start_focus_session(
            {"duration_minutes": 1, "task_title": "Read docs"}
        )
        session_id = started["session"]["id"]
        early = simulator.complete_focus_session(session_id)
        self.assertFalse(early["ok"])
        self.assertEqual(0, simulator.data["stats"]["completed_focus_sessions"])
        self.assertEqual({}, simulator.data["inventory"])

        clock.now += 60
        completed = simulator.complete_focus_session(session_id)

        self.assertTrue(completed["ok"])
        state = completed["state"]
        self.assertIsNone(state["focus"]["active_session"])
        self.assertEqual(1, state["stats"]["completed_focus_sessions"])
        self.assertEqual(1, state["stats"]["total_focus_minutes"])
        self.assertEqual(1, state["level"]["xp"])
        self.assertEqual(2, state["inventory"]["focus_item"])

    def test_cancel_focus_session_breaks_streak_without_reward(self):
        clock = MutableClock(2000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        started = simulator.start_focus_session({"duration_minutes": 1})
        cancelled = simulator.cancel_focus_session(started["session"]["id"])

        self.assertTrue(cancelled["ok"])
        self.assertIsNone(cancelled["state"]["focus"]["active_session"])
        self.assertEqual(0, cancelled["state"]["focus"]["focus_streak"])
        self.assertEqual(0, cancelled["state"]["stats"]["completed_focus_sessions"])
        self.assertEqual({}, cancelled["state"]["inventory"])

    def test_daily_focus_quests_are_claimed_once_per_day(self):
        clock = MutableClock(3000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        first = simulator.start_focus_session({"duration_minutes": 60})
        clock.now += 60 * 60
        first_reward = simulator.complete_focus_session(first["session"]["id"])
        claimed_ids = {
            quest["id"] for quest in first_reward["focus_reward"]["claimed_quests"]
        }
        self.assertEqual({"first_session", "focus_60"}, claimed_ids)
        self.assertEqual(3, first_reward["focus_reward"]["reward_rolls"])

        second = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        self.assertEqual([], second_reward["focus_reward"]["claimed_quests"])
        self.assertEqual(1, second_reward["focus_reward"]["reward_rolls"])
        self.assertEqual(61, second_reward["state"]["focus"]["today_minutes"])

    def test_preset_export_excludes_progress_and_import_replaces_catalog(self):
        simulator = self.create_simulator()
        old_rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("old_item", old_rarity_id, 1)]
        simulator.data["inventory"] = {"old_item": 2}
        simulator.data["stats"]["total_focus_minutes"] = 90

        new_rarity = rarity_template("new-rarity", "New", 100)
        new_item = item_template("new-item", "new-rarity", 1)
        imported = simulator.import_preset(
            {
                "name": "Test preset",
                "rarities": [new_rarity],
                "items": [new_item],
                "settings": {
                    "drop_events": [
                        {
                            "id": "normal",
                            "name": "Normal",
                            "weight": 1,
                            "multiplier": 1,
                        }
                    ]
                },
            }
        )

        self.assertTrue(imported["ok"])
        self.assertEqual(["new-item"], [item["id"] for item in imported["state"]["items"]])
        self.assertEqual({}, imported["state"]["inventory"])
        self.assertEqual(90, imported["state"]["stats"]["total_focus_minutes"])

        exported = simulator.export_preset()["preset"]
        self.assertNotIn("inventory", exported)
        self.assertNotIn("collection", exported)
        self.assertNotIn("stats", exported)
        self.assertNotIn("focus", exported)

    def test_open_case_respects_stack_rarity_filters_after_grouping(self):
        simulator = self.create_simulator()

        simulator.data["rarities"] = [
            {
                **rarity_template("base", "База", 100),
                "stack_rarity_upgrades": [{"min_qty": 2, "target_rarity_id": "up"}],
            },
            rarity_template("up", "Повышенная", 0),
        ]
        simulator.data["items"] = [item_template("item-1", "base", 1)]
        simulator.data["inventory"] = {}
        simulator.data["stats"] = {"total_opened": 0, "total_spent": 0, "by_rarity": {}}
        simulator.data["settings"]["drop_events"] = [
            {"id": "double", "name": "x2", "weight": 1, "multiplier": 2}
        ]
        simulator.data["settings"]["rarity_boosts"] = []
        simulator.data["settings"]["filters"] = {
            "rarity_hidden": {"up": True},
            "item_hidden": {},
        }

        result = simulator.open_case(1)

        self.assertTrue(result["ok"])
        self.assertEqual([], result["grouped_visible_results"])
        self.assertEqual(2, result["hidden_results_count"])
        self.assertEqual(2, result["state"]["inventory"]["item-1"])

    def test_purchase_item_keeps_shop_rules(self):
        simulator = self.create_simulator()

        simulator.data["rarities"] = [rarity_template("r-1", "Общая", 100)]
        simulator.data["items"] = [
            item_template("currency", "r-1", 1, is_currency=True),
            item_template("target", "r-1", 100),
        ]
        simulator.data["inventory"] = {"currency": 10}

        invalid = simulator.purchase_item("target", "currency", 1)
        self.assertFalse(invalid["ok"])
        self.assertIn("Минимальная покупка", invalid["message"])

        success = simulator.purchase_item("target", "currency", 86)
        self.assertTrue(success["ok"])
        self.assertEqual(86, success["state"]["inventory"]["target"])
        self.assertEqual(9, success["state"]["inventory"]["currency"])
        self.assertEqual(86, success["price"]["min_quantity"])
        self.assertEqual(1, success["price"]["total"])

    def test_legion_encounter_rolls_many_currency_drops(self):
        simulator = self.create_simulator()

        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        simulator.data["items"] = [
            item_template("chaos", "r-1", 1, is_currency=True),
            item_template("sword", "r-1", 1, is_currency=False),
        ]
        simulator.data["inventory"] = {}
        simulator.data["stats"] = {"total_opened": 0, "total_spent": 0, "by_rarity": {}}
        simulator.data["settings"]["drop_events"] = [
            {
                "id": "legion",
                "name": "Legion",
                "weight": 1,
                "multiplier": 2,
                "rolls": 3,
                "currency_only": True,
            }
        ]
        simulator.data["settings"]["rarity_boosts"] = []

        result = simulator.open_case(1)

        self.assertTrue(result["ok"])
        self.assertEqual(6, result["state"]["inventory"]["chaos"])
        self.assertEqual(1, result["state"]["stats"]["total_opened"])
        self.assertEqual(3, len(result["results"]))

    def test_mirror_altar_duplicates_best_drop(self):
        simulator = self.create_simulator()

        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        simulator.data["items"] = [item_template("mirror", "r-1", 1, is_currency=True)]
        simulator.data["inventory"] = {}
        simulator.data["stats"] = {"total_opened": 0, "total_spent": 0, "by_rarity": {}}
        simulator.data["settings"]["drop_events"] = [
            {
                "id": "mirror_altar",
                "name": "Mirror Altar",
                "weight": 1,
                "multiplier": 1,
                "rolls": 1,
                "duplicate_best": True,
            }
        ]
        simulator.data["settings"]["rarity_boosts"] = []

        result = simulator.open_case(1)

        self.assertTrue(result["ok"])
        self.assertEqual(2, result["state"]["inventory"]["mirror"])
        self.assertEqual(2, len(result["results"]))
        self.assertTrue(result["results"][1]["drop_event"]["mirrored_duplicate"])

    def test_market_prices_drive_currency_shop_offers(self):
        clock = MutableClock()
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )

        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        chaos = item_template("chaos", "r-1", 1, is_currency=True)
        chaos.update({"name": "Chaos Orb", "market_value_chaos": 1.0})
        divine = item_template("divine", "r-1", 1, is_currency=True)
        divine.update({"name": "Divine Orb", "market_value_chaos": 180.0})
        simulator.data["items"] = [chaos, divine]
        simulator.data["inventory"] = {"chaos": 1000}
        simulator.data["market"] = {
            "last_tick": 0,
            "sentiment": 0.0,
            "prices": {},
            "recent_drops": {},
            "recent_purchases": {},
        }
        simulator.data["settings"]["market"] = {
            "enabled": True,
            "tick_seconds": 5,
            "reference_currency_id": "chaos",
            "max_ticks_per_refresh": 4,
        }

        state = simulator.state()
        self.assertEqual(1.0, state["market"]["prices"]["chaos"]["price_chaos"])
        self.assertEqual(180.0, state["market"]["prices"]["divine"]["price_chaos"])

        offer = simulator._compute_shop_offer(divine, chaos)
        self.assertGreater(offer["bundle_price"], 180)

        clock.now += 10
        state = simulator.state()
        self.assertGreaterEqual(state["market"]["prices"]["divine"]["volume"], 1)

    def test_collection_seeds_from_existing_inventory_once(self):
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        base_path = Path(temp_dir.name) / "case_simulator_data.json"
        rarity = rarity_template("r-1", "Currency", 100)
        found = item_template("found", "r-1", 1)
        missing = item_template("missing", "r-1", 1)

        (Path(temp_dir.name) / "case_rarities.json").write_text(
            json.dumps([rarity]),
            encoding="utf-8",
        )
        (Path(temp_dir.name) / "case_items.json").write_text(
            json.dumps([found, missing]),
            encoding="utf-8",
        )
        (Path(temp_dir.name) / "case_inventory.json").write_text(
            json.dumps({"found": 3}),
            encoding="utf-8",
        )

        simulator = CaseSimulator(
            str(base_path),
            time_provider=MutableClock(1234.0),
        )
        state = simulator.state()

        self.assertTrue(state["collection"]["seeded_from_inventory"])
        self.assertEqual(3, state["collection"]["items"]["found"]["found_count"])
        self.assertTrue(state["collection"]["items"]["found"]["seeded"])
        self.assertNotIn("missing", state["collection"]["items"])
        self.assertEqual(1, state["collection_summary"]["found_items"])
        self.assertEqual(2, state["collection_summary"]["total_items"])

    def test_open_case_records_collection_counts_and_preserves_first_drop(self):
        clock = MutableClock(1000.0)
        simulator = self.create_simulator()
        simulator._time_provider = clock
        simulator._rng = FlatRng()
        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        simulator.data["items"] = [item_template("chaos", "r-1", 1, is_currency=True)]
        simulator.data["inventory"] = {}
        simulator.data["stats"] = {"total_opened": 0, "total_spent": 0, "by_rarity": {}}
        simulator.data["collection"] = {"seeded_from_inventory": True, "items": {}}
        simulator.data["settings"]["drop_events"] = [
            {"id": "normal", "name": "Normal", "weight": 1, "multiplier": 1}
        ]
        simulator.data["settings"]["rarity_boosts"] = []

        first = simulator.open_case(1)
        clock.now = 1500.0
        second = simulator.open_case(1)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        row = second["state"]["collection"]["items"]["chaos"]
        self.assertEqual(2, row["found_count"])
        self.assertEqual(1000, row["first_found_at"])
        self.assertEqual(1500, row["last_found_at"])
        self.assertEqual(1, row["best_stack"])
        self.assertFalse(row["seeded"])

    def test_purchase_item_does_not_unlock_collection_item(self):
        simulator = self.create_simulator()
        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        simulator.data["items"] = [
            item_template("currency", "r-1", 1, is_currency=True),
            item_template("target", "r-1", 1),
        ]
        simulator.data["inventory"] = {"currency": 10}
        simulator.data["collection"] = {"seeded_from_inventory": True, "items": {}}

        result = simulator.purchase_item("target", "currency", 1)

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["state"]["inventory"]["target"])
        self.assertNotIn("target", result["state"]["collection"]["items"])

    def test_delete_item_removes_collection_entry(self):
        simulator = self.create_simulator()
        simulator.data["rarities"] = [rarity_template("r-1", "Currency", 100)]
        simulator.data["items"] = [item_template("target", "r-1", 1)]
        simulator.data["inventory"] = {"target": 1}
        simulator.data["collection"] = {
            "seeded_from_inventory": True,
            "items": {
                "target": {
                    "found_count": 1,
                    "first_found_at": 1000,
                    "last_found_at": 1000,
                    "best_stack": 1,
                    "seeded": False,
                }
            },
        }

        result = simulator.delete_item("target")

        self.assertTrue(result["ok"])
        self.assertNotIn("target", result["state"]["collection"]["items"])

    def test_clear_collection_keeps_inventory_intact(self):
        simulator = self.create_simulator()
        simulator.data["collection"] = {
            "seeded_from_inventory": True,
            "items": {
                "item-1": {
                    "found_count": 4,
                    "first_found_at": 1000,
                    "last_found_at": 1000,
                    "best_stack": 4,
                    "seeded": True,
                }
            },
        }
        simulator.data["inventory"] = {"item-1": 4}

        result = simulator.clear_collection()

        self.assertTrue(result["ok"])
        self.assertEqual({"item-1": 4}, result["state"]["inventory"])
        self.assertEqual({}, result["state"]["collection"]["items"])
        self.assertTrue(result["state"]["collection"]["seeded_from_inventory"])


if __name__ == "__main__":
    unittest.main()
