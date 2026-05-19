from pathlib import Path
import json
import time
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
        ui_text = INDEX_HTML_PATH.read_text(encoding="utf-8") + (
            UI_DIR / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Бриллиантовая", ui_text)
        self.assertNotIn("Босс", ui_text)

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
                "focus_chain": {
                    "break_window_minutes": 5,
                    "bonus_roll_every": 0,
                    "max_bonus_rolls": 50,
                    "luck_roll_every": 0,
                    "max_luck_rolls": 99,
                    "daily_chain_bonus_roll_cap": 99,
                    "short_session_minutes": 99,
                    "short_session_daily_limit": 99,
                    "short_session_decay": 2,
                    "long_session_minutes": 999,
                    "long_session_bonus_rolls": 99,
                    "deep_session_minutes": 1,
                    "deep_session_bonus_rolls": 99,
                },
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
        self.assertEqual(
            {
                "break_window_minutes": 15,
                "bonus_roll_every": 1,
                "max_bonus_rolls": 20,
                "luck_roll_every": 1,
                "max_luck_rolls": 10,
                "daily_chain_bonus_roll_cap": 50,
                "short_session_minutes": 60,
                "short_session_daily_limit": 30,
                "short_session_decay": 1.0,
                "long_session_minutes": 180,
                "long_session_bonus_rolls": 10,
                "deep_session_minutes": 180,
                "deep_session_bonus_rolls": 20,
            },
            settings["focus_chain"],
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

    def test_start_focus_session_saves_and_clamps_difficulty(self):
        simulator = self.create_simulator()

        high = simulator.start_focus_session(
            {"duration_minutes": 25, "difficulty_level": 99}
        )

        self.assertTrue(high["ok"])
        self.assertEqual(5, high["session"]["difficulty_level"])
        self.assertEqual(5, high["state"]["focus"]["active_session"]["difficulty_level"])

        simulator.cancel_focus_session(high["session"]["id"])
        low = simulator.start_focus_session(
            {"duration_minutes": 25, "difficulty_level": -4}
        )

        self.assertTrue(low["ok"])
        self.assertEqual(1, low["session"]["difficulty_level"])
        self.assertEqual(1, low["state"]["focus"]["active_session"]["difficulty_level"])

    def test_diamond_difficulty_completion_adds_bonus_rolls_and_luck(self):
        clock = MutableClock(1500.0)
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
            {"duration_minutes": 1, "difficulty_level": 5}
        )
        clock.now += 60
        completed = simulator.complete_focus_session(started["session"]["id"])
        reward = completed["focus_reward"]

        self.assertTrue(completed["ok"])
        self.assertEqual(5, reward["difficulty_level"])
        self.assertEqual(4, reward["difficulty_bonus_rolls"])
        self.assertEqual(2, reward["difficulty_luck_rolls"])
        self.assertEqual(6, reward["reward_rolls"])
        self.assertEqual(3, reward["reward_luck_rolls"])
        self.assertEqual(5, reward["session"]["difficulty_level"])
        self.assertEqual(
            4,
            completed["state"]["focus"]["completed_sessions"][0][
                "difficulty_bonus_rolls"
            ],
        )

    def test_legacy_focus_sessions_default_to_standard_difficulty(self):
        simulator = self.create_simulator()
        simulator.data["focus"]["active_session"] = {
            "id": "legacy-active",
            "task_title": "Legacy task",
            "duration_minutes": 25,
            "started_at": 100,
            "ends_at": 1600,
            "status": "active",
        }
        simulator.data["focus"]["completed_sessions"] = [
            {
                "id": "legacy-complete",
                "task_title": "Legacy done",
                "duration_minutes": 25,
                "started_at": 10,
                "completed_at": 1510,
                "reward_rolls": 1,
            }
        ]

        state = simulator.state()

        self.assertEqual(2, state["focus"]["active_session"]["difficulty_level"])
        self.assertEqual(2, state["focus"]["completed_sessions"][0]["difficulty_level"])

    def test_focus_state_reports_next_local_midnight_reset(self):
        now = time.mktime((2026, 5, 19, 10, 30, 0, -1, -1, -1))
        expected_reset = int(time.mktime((2026, 5, 20, 0, 0, 0, -1, -1, -1)))
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            time_provider=MutableClock(now),
        )

        state = simulator.state()

        self.assertEqual(expected_reset, state["focus"]["daily_reset_at"])
        self.assertEqual(
            expected_reset - int(now),
            state["focus"]["daily_reset_seconds_left"],
        )

    def test_focus_activity_calendar_uses_adaptive_all_time_peak_intensity(self):
        now = time.mktime((2026, 5, 19, 12, 0, 0, -1, -1, -1))
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            time_provider=MutableClock(now),
        )
        simulator.data["focus"]["daily_focus"] = {
            "2026-05-15": {"minutes": 0, "sessions": 0},
            "2026-05-16": {"minutes": 1, "sessions": 1},
            "2026-05-17": {"minutes": 8, "sessions": 2},
            "2026-05-18": {"minutes": 16, "sessions": 3},
            "2026-05-19": {"minutes": 30, "sessions": 4},
        }

        state = simulator.state()
        calendar = state["focus"]["activity_calendar"]
        by_date = {day["date"]: day for day in calendar}

        self.assertEqual(53 * 7, len(calendar))
        self.assertEqual(30, state["focus"]["activity_peak_minutes"])
        self.assertEqual(0, by_date["2026-05-15"]["intensity"])
        self.assertEqual(1, by_date["2026-05-16"]["intensity"])
        self.assertEqual(2, by_date["2026-05-17"]["intensity"])
        self.assertEqual(3, by_date["2026-05-18"]["intensity"])
        self.assertEqual(4, by_date["2026-05-19"]["intensity"])
        self.assertEqual(4, by_date["2026-05-19"]["sessions"])

    def test_focus_activity_calendar_has_no_intensity_without_activity(self):
        now = time.mktime((2026, 5, 19, 12, 0, 0, -1, -1, -1))
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            time_provider=MutableClock(now),
        )

        state = simulator.state()

        self.assertEqual(0, state["focus"]["activity_peak_minutes"])
        self.assertTrue(
            all(day["intensity"] == 0 for day in state["focus"]["activity_calendar"])
        )

    def test_focus_activity_calendar_uses_peak_outside_visible_range(self):
        now = time.mktime((2026, 5, 19, 12, 0, 0, -1, -1, -1))
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            time_provider=MutableClock(now),
        )
        simulator.data["focus"]["daily_focus"] = {
            "2025-01-01": {"minutes": 200, "sessions": 5},
            "2026-05-19": {"minutes": 100, "sessions": 2},
        }

        state = simulator.state()
        by_date = {day["date"]: day for day in state["focus"]["activity_calendar"]}

        self.assertEqual(200, state["focus"]["activity_peak_minutes"])
        self.assertNotIn("2025-01-01", by_date)
        self.assertEqual(2, by_date["2026-05-19"]["intensity"])

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
        self.assertEqual(4, first_reward["focus_reward"]["reward_rolls"])

        second = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        self.assertEqual([], second_reward["focus_reward"]["claimed_quests"])
        self.assertEqual(2, second_reward["focus_reward"]["reward_rolls"])
        self.assertEqual(61, second_reward["state"]["focus"]["today_minutes"])

    def test_focus_chain_continues_within_configured_break_window(self):
        clock = MutableClock(4000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]
        simulator.update_settings(
            {
                "focus_chain": {
                    "break_window_minutes": 150,
                    "bonus_roll_every": 2,
                    "max_bonus_rolls": 5,
                    "luck_roll_every": 3,
                    "max_luck_rolls": 5,
                }
            }
        )

        first = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        first_reward = simulator.complete_focus_session(first["session"]["id"])

        clock.now += 149 * 60
        second = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        clock.now += 1
        third = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        third_reward = simulator.complete_focus_session(third["session"]["id"])

        self.assertEqual(1, first_reward["focus_reward"]["chain"]["count"])
        self.assertEqual(2, second_reward["focus_reward"]["chain"]["count"])
        self.assertEqual(3, third_reward["focus_reward"]["chain"]["count"])
        self.assertTrue(second_reward["focus_reward"]["chain"]["continued"])
        self.assertEqual(1, second_reward["focus_reward"]["chain"]["bonus_rolls"])
        self.assertEqual(2, second_reward["focus_reward"]["reward_rolls"])
        self.assertEqual(2, third_reward["focus_reward"]["chain"]["luck_rolls"])
        self.assertEqual(3, third_reward["state"]["focus"]["focus_streak"])
        self.assertEqual(3, third_reward["state"]["focus"]["best_focus_streak"])

    def test_focus_chain_resets_after_configured_break_window(self):
        clock = MutableClock(8000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]
        simulator.update_settings(
            {
                "focus_chain": {
                    "break_window_minutes": 30,
                    "bonus_roll_every": 2,
                    "max_bonus_rolls": 5,
                    "luck_roll_every": 3,
                    "max_luck_rolls": 5,
                }
            }
        )

        first = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        simulator.complete_focus_session(first["session"]["id"])

        clock.now += 31 * 60
        expired_state = simulator.state()
        self.assertEqual(0, expired_state["focus"]["focus_streak"])

        second = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        self.assertEqual(1, second_reward["focus_reward"]["chain"]["count"])
        self.assertFalse(second_reward["focus_reward"]["chain"]["continued"])
        self.assertEqual(0, second_reward["focus_reward"]["chain"]["bonus_rolls"])
        self.assertEqual(1, second_reward["focus_reward"]["reward_rolls"])

    def test_fast_cancel_preserves_existing_focus_chain_without_reward(self):
        clock = MutableClock(12000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        first = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        simulator.complete_focus_session(first["session"]["id"])

        cancelled = simulator.start_focus_session({"duration_minutes": 1})
        cancelled_result = simulator.cancel_focus_session(cancelled["session"]["id"])

        clock.now += 60
        next_session = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        next_reward = simulator.complete_focus_session(next_session["session"]["id"])

        self.assertEqual(1, cancelled_result["state"]["focus"]["focus_streak"])
        self.assertEqual(1, cancelled_result["state"]["stats"]["completed_focus_sessions"])
        self.assertEqual(2, cancelled_result["state"]["inventory"]["focus_item"])
        self.assertEqual(2, next_reward["focus_reward"]["chain"]["count"])
        self.assertTrue(next_reward["focus_reward"]["chain"]["continued"])
        self.assertEqual(2, next_reward["focus_reward"]["reward_rolls"])

    def test_slow_cancel_breaks_existing_focus_chain(self):
        clock = MutableClock(16000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        first = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        simulator.complete_focus_session(first["session"]["id"])

        cancelled = simulator.start_focus_session({"duration_minutes": 5})
        clock.now += 120
        cancelled_result = simulator.cancel_focus_session(cancelled["session"]["id"])

        clock.now += 60
        next_session = simulator.start_focus_session({"duration_minutes": 1})
        clock.now += 60
        next_reward = simulator.complete_focus_session(next_session["session"]["id"])

        self.assertEqual(0, cancelled_result["state"]["focus"]["focus_streak"])
        self.assertEqual(1, next_reward["focus_reward"]["chain"]["count"])
        self.assertFalse(next_reward["focus_reward"]["chain"]["continued"])
        self.assertEqual(1, next_reward["focus_reward"]["reward_rolls"])

    def test_short_session_diminishing_returns_reduce_chain_bonus(self):
        clock = MutableClock(20000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]
        simulator.update_settings(
            {
                "focus_chain": {
                    "break_window_minutes": 150,
                    "bonus_roll_every": 2,
                    "max_bonus_rolls": 5,
                    "luck_roll_every": 3,
                    "max_luck_rolls": 5,
                    "daily_chain_bonus_roll_cap": 8,
                    "short_session_minutes": 15,
                    "short_session_daily_limit": 1,
                    "short_session_decay": 0.5,
                    "long_session_minutes": 45,
                    "long_session_bonus_rolls": 1,
                    "deep_session_minutes": 90,
                    "deep_session_bonus_rolls": 2,
                }
            }
        )

        first = simulator.start_focus_session({"duration_minutes": 5})
        clock.now += 5 * 60
        simulator.complete_focus_session(first["session"]["id"])

        second = simulator.start_focus_session({"duration_minutes": 5})
        clock.now += 5 * 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        self.assertEqual(2, second_reward["focus_reward"]["chain"]["count"])
        self.assertEqual(1, second_reward["focus_reward"]["chain"]["raw_bonus_rolls"])
        self.assertEqual(0, second_reward["focus_reward"]["chain"]["bonus_rolls"])
        self.assertEqual(0.5, second_reward["focus_reward"]["anti_farm"]["short_session_multiplier"])
        self.assertEqual(1, second_reward["focus_reward"]["reward_rolls"])

    def test_daily_chain_bonus_cap_limits_streak_farming(self):
        clock = MutableClock(24000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]
        simulator.update_settings(
            {
                "focus_chain": {
                    "break_window_minutes": 150,
                    "bonus_roll_every": 2,
                    "max_bonus_rolls": 5,
                    "luck_roll_every": 3,
                    "max_luck_rolls": 5,
                    "daily_chain_bonus_roll_cap": 1,
                    "short_session_minutes": 15,
                    "short_session_daily_limit": 3,
                    "short_session_decay": 0.5,
                    "long_session_minutes": 45,
                    "long_session_bonus_rolls": 1,
                    "deep_session_minutes": 90,
                    "deep_session_bonus_rolls": 2,
                }
            }
        )

        first = simulator.start_focus_session({"duration_minutes": 15})
        clock.now += 15 * 60
        simulator.complete_focus_session(first["session"]["id"])

        second = simulator.start_focus_session({"duration_minutes": 15})
        clock.now += 15 * 60
        second_reward = simulator.complete_focus_session(second["session"]["id"])

        third = simulator.start_focus_session({"duration_minutes": 15})
        clock.now += 15 * 60
        third_reward = simulator.complete_focus_session(third["session"]["id"])

        self.assertEqual(1, second_reward["focus_reward"]["chain"]["bonus_rolls"])
        self.assertEqual(2, second_reward["focus_reward"]["reward_rolls"])
        self.assertEqual(0, third_reward["focus_reward"]["chain"]["bonus_rolls"])
        self.assertTrue(third_reward["focus_reward"]["anti_farm"]["daily_cap_hit"])
        self.assertEqual(1, third_reward["focus_reward"]["anti_farm"]["daily_chain_bonus_used"])
        self.assertEqual(1, third_reward["focus_reward"]["reward_rolls"])

    def test_long_focus_block_gets_length_bonus(self):
        clock = MutableClock(28000.0)
        temp_dir = TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        simulator = CaseSimulator(
            str(Path(temp_dir.name) / "case_simulator_data.json"),
            rng=FlatRng(),
            time_provider=clock,
        )
        rarity_id = simulator.data["rarities"][0]["id"]
        simulator.data["items"] = [item_template("focus_item", rarity_id, 1)]

        session = simulator.start_focus_session({"duration_minutes": 45})
        clock.now += 45 * 60
        reward = simulator.complete_focus_session(session["session"]["id"])

        self.assertEqual(1, reward["focus_reward"]["anti_farm"]["length_bonus_rolls"])
        self.assertEqual(3, reward["focus_reward"]["reward_rolls"])

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
