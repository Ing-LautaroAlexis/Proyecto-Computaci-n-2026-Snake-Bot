"""Estrategia nueva de la 3.9.3: el bot ve y pelea las X aunque estén lejos (partida 9)."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "bot_final"
BOT = ROOT / "bot_3.9.3.py"
for dependency in ("pygame", "websockets"):
    sys.modules.setdefault(dependency, types.ModuleType(dependency))


def load_bot():
    name = "bot393_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, BOT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def board(rows):
    return "".join("|" + row + "|\n" for row in rows)


class Topo:
    def __init__(self, distances):
        self.distances = distances


# Partida 9: la X estaba a más de 8 casillas y el bot no la iba a buscar.
# Acá está a 18 pasos (arriba a la izquierda); con la vista de 8 de la 3.9.2 iba a la derecha.
FAR_X = [" " * 20 for _ in range(20)]
FAR_X[1] = " X" + " " * 18
FAR_X[10] = " " * 8 + "aaA" + " " * 9
FAR_X[19] = " bbB" + " " * 16


class TestStrategy393(unittest.TestCase):
    def setUp(self):
        self.bot = load_bot()

    def test_far_x_still_counts(self):
        # 3.9.2 dejaba de ver la X a más de 8 pasos; ahora la ve hasta 40.
        self.assertGreater(self.bot._x_potential(20, 3000, 500), 0)
        self.assertEqual(self.bot._x_potential(41, 3000, 500), 0)
        self.assertGreater(self.bot._x_potential(5, 3000, 500), self.bot._x_potential(20, 3000, 500))

    def test_contested_x_is_still_worth_fighting(self):
        grid = [list("X     ")]
        me_close, rival = Topo({(0, 0): 5}), Topo({(0, 0): 4})
        only_rival = -self.bot._x_potential(4, 3000, 500)
        fought = self.bot._x_pickup_tempo(grid, me_close, rival, 3000, 500)
        self.assertGreater(fought, only_rival)
        self.assertLess(fought, 0)
        far_behind = Topo({(0, 0): 9})
        self.assertEqual(self.bot._x_pickup_tempo(grid, far_behind, rival, 3000, 500), only_rival)
        self.assertEqual(self.bot._x_pickup_tempo(grid, me_close, rival, 0, 500), 0)
        self.assertEqual(self.bot._x_race_values(4, 4, 3000, 500), (0, 0))

    def test_goes_for_a_far_x(self):
        payload = {
            "board": board(FAR_X), "rows": 20, "cols": 20, "board_size": "20x20",
            "remaining_moves": 360, "side": "A", "score_1": 0, "score_2": 0,
            "multiplier_1": 1, "multiplier_2": 1, "game_id": uuid.uuid4().hex,
        }
        self.assertEqual(self.bot.choose_direction(payload, search_mode="nodes", node_budget=3000), "UP")
        self.bot.X_POTENTIAL_RADIUS = 8
        payload["game_id"] = uuid.uuid4().hex
        self.assertNotEqual(self.bot.choose_direction(payload, search_mode="nodes", node_budget=3000), "UP")


if __name__ == "__main__":
    unittest.main()
