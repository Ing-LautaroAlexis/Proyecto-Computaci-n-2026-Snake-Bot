"""Arreglo de la 3.9.4 (torneo del 27/10): no meterse en un pasillo sin salida para comer."""
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

BIG, SMALL = "\U0001f4a3", "\U0001f9e8"


def load_bot():
    name = "bot394_" + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, BOT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def board(rows):
    return "".join("|" + row + "|\n" for row in rows)


# Partida 12, jugada 186: el 7 está pegado al borde y Rosarito viene por la fila de abajo.
# Ir a la izquierda a comerlo terminaba encerrado en la esquina (quedó en 0 y chocó 4 veces más).
EDGE_TRAP = [
    "  7 A       7     " + BIG + "  1",
    "   Baaa               ",
    "   b  a 8     ###     ",
    " 2 b  a  9            ",
    "   b  aa      " + SMALL + "       ",
    " " + SMALL + " b                  ",
    "                  " + BIG + "   ",
    "                      ",
    "                      ",
    "       1              ",
    "2                 " + SMALL + "   ",
    "        " + SMALL + "             ",
    "                      ",
    "                9     ",
    "               8      ",
    "                      ",
    " 9        8           ",
    "                      ",
    "                      ",
    " X          " + SMALL + "  1  X   ",
    "7  8                  ",
    "                      ",
    "2                2    ",
    "              8       ",
]


class TestStrategy394(unittest.TestCase):
    def setUp(self):
        self.bot = load_bot()

    def ask_edge_trap(self):
        payload = {
            "board": board(EDGE_TRAP), "rows": 24, "cols": 22, "board_size": "24x22",
            "remaining_moves": 214, "side": "A", "score_1": 3031, "score_2": 5787,
            "multiplier_1": 8, "multiplier_2": 5, "game_id": uuid.uuid4().hex,
        }
        return self.bot.choose_direction(payload, search_mode="fixed_depth", fixed_depth=3)

    def test_does_not_walk_into_edge_trap(self):
        self.assertEqual(self.ask_edge_trap(), "RIGHT")

    def test_old_penalty_was_too_small(self):
        # Con el castigo de antes y poca profundidad (como en la partida real) iba a comer el 7.
        self.bot.FORCED_TRAP_ROOT_SCALE = 1
        self.assertEqual(self.ask_edge_trap(), "LEFT")


if __name__ == "__main__":
    unittest.main()
