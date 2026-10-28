"""Estrategia nueva de la 3.9.2: no regalar el número que viene, esperar y valor de la X."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "bot_final"
BOT = ROOT / "bot_3.10.1.py"
for dependency in ("pygame", "websockets"):
    sys.modules.setdefault(dependency, types.ModuleType(dependency))


def load_bot():
    name = "bot392_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, BOT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def board(rows):
    return "".join("|" + row + "|\n" for row in rows)


# El 3 está pegado a mi cabeza. El rival está más cerca que yo del 4 (el que viene).
RIVAL_NEAR_NEXT = [
    "            ",
    " aaA3       ",
    "            ",
    "            ",
    "            ",
    "     5      ",
    "           4",
    "            ",
    "            ",
    "           6",
    "       B    ",
    "7      bb   ",
]


class Topo:
    def __init__(self, distances):
        self.distances = distances


class TestStrategy392(unittest.TestCase):
    def setUp(self):
        self.bot = load_bot()

    def ask(self, mult_me, mult_rival, race=True):
        self.bot.RACE_ENABLED = race
        self.bot.CAMP_ENABLED = race
        payload = {
            "board": board(RIVAL_NEAR_NEXT), "rows": 12, "cols": 12, "board_size": "12x12",
            "remaining_moves": 300, "side": "A", "score_1": 1000, "score_2": 1000,
            "multiplier_1": mult_me, "multiplier_2": mult_rival,
            "game_id": uuid.uuid4().hex,
        }
        return self.bot.choose_direction(payload, search_mode="nodes", node_budget=4000)

    def test_does_not_gift_next_digit_to_stronger_rival(self):
        # Comer el 3 (x2) le deja el 4 al rival (x6): la 3.1 lo comía, la 3.9.2 no.
        self.assertEqual(self.ask(2, 6, race=False), "RIGHT")
        self.assertNotEqual(self.ask(2, 6, race=True), "RIGHT")

    def test_still_eats_when_trade_is_fair(self):
        self.assertEqual(self.ask(3, 3, race=True), "RIGHT")
        self.assertEqual(self.ask(6, 2, race=True), "RIGHT")

    def test_race_probability(self):
        self.assertEqual(self.bot._race_winner_probability(2, 5, True), (True, 0.75))
        self.assertEqual(self.bot._race_winner_probability(3, 3, False), (False, 0.45))
        self.assertTrue(self.bot._race_winner_probability(3, 3, True)[0])
        self.assertEqual(self.bot._race_winner_probability(1, 20, True)[1], self.bot.RACE_P_MAX)

    def test_race_points_signs(self):
        grid = [list(" 5  "), list("    ")]
        food = [(0, 1)]
        me, rival = Topo({(0, 1): 1}), Topo({(0, 1): 3})
        self.bot.RACE_CLAIM_WEIGHT = 0.5
        won = self.bot._race_expected_points(grid, me, rival, food, 2, 2, 300, True)
        self.assertGreater(won, 0)
        lost = self.bot._race_expected_points(grid, rival, me, food, 2, 2, 300, True)
        self.assertLess(lost, 0)
        self.assertEqual(self.bot._race_expected_points(grid, me, rival, [], 2, 2, 300, True), 0)
        self.assertEqual(self.bot._race_expected_points(grid, me, rival, food, 2, 2, 3, True), 0)
        far = Topo({})
        self.assertEqual(self.bot._race_expected_points(grid, far, far, food, 2, 2, 300, True), 0)
        self.assertEqual(self.bot._race_expected_points(grid, Topo({(0, 1): 200}), Topo({(0, 1): 300}), food, 2, 2, 300, True), 0)

    def test_camping_reduces_loss_but_never_beats_winning(self):
        self.bot.CAMP_ENABLED = True
        grid = [list("5    6"), list("      ")]
        food = [(0, 0)]
        self.bot.DIGIT_CELLS.clear()
        self.bot.DIGIT_CELLS.update({"5": [(0, 0)], "6": [(0, 5)]})
        rival = Topo({(0, 0): 1})
        far_from_six = Topo({(0, 0): 4, (0, 5): 9})
        next_to_six = Topo({(0, 0): 4, (0, 5): 1})
        lost = self.bot._race_expected_points(grid, far_from_six, rival, food, 2, 2, 300, True)
        camped = self.bot._race_expected_points(grid, next_to_six, rival, food, 2, 2, 300, True)
        self.assertLess(lost, camped)
        self.assertLessEqual(camped, 0)
        self.bot.CAMP_ENABLED = False
        self.assertEqual(self.bot._camp_expected_points(grid, next_to_six, rival, food, 500, 2, 1, 300), 0)
        self.bot.CAMP_ENABLED = True
        self.assertEqual(self.bot._camp_expected_points(grid, next_to_six, rival, food, 500, 2, 1, 2), 0)
        self.assertEqual(self.bot._camp_expected_points(grid, Topo({}), rival, food, 500, 2, 1, 300), 0)

    def test_x_is_worth_more_than_a_small_digit_early(self):
        self.assertGreater(self.bot.multiplier_future_value(380), 3 * 100 * 4)
        self.assertEqual(self.bot.multiplier_future_value(10), 0)


if __name__ == "__main__":
    unittest.main()
