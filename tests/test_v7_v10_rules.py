"""Reglas de octubre (v7 a v10) sobre el bot 3.9.2."""
import importlib.util
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "bot_final"
BOT = ROOT / "bot_3.9.3.py"
for name in ("pygame", "websockets"):
    sys.modules.setdefault(name, types.ModuleType(name))
spec = importlib.util.spec_from_file_location("bot391_v7v10", BOT)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

SIZE = 20
BOMB = "\U0001F4A3"
PETARDO = "\U0001F9E8"


def make_turn(cells, size=SIZE, **extra):
    grid = [[" "] * size for _ in range(size)]
    for (r, c), value in cells.items():
        grid[r][c] = value
    board = "\n".join("|" + "".join(row) + "|" for row in grid)
    data = {"board": board, "rows": size, "cols": size, "board_size": f"{size}x{size}",
            "side": "A", "remaining_moves": 380, "game_id": f"t{time.time_ns()}",
            "score_1": 0, "score_2": 0, "multiplier_1": 1, "multiplier_2": 1}
    data.update(extra)
    return data


def adapted(data):
    return bot.adapt_new_rules(bot.parse_turn_board(data), data)


def test_bomb_zone_becomes_wall():
    grid = adapted(make_turn({(10, 10): BOMB, (3, 3): PETARDO, (15, 2): "A", (15, 1): "a", (2, 15): "B"}))
    assert grid[8][8] == "#" and grid[12][12] == "#"   # 💣: 2 casillas, diagonal incluida
    assert grid[7][10] == " "
    assert grid[2][2] == "#" and grid[4][4] == "#"     # 🧨: 1 casilla
    assert grid[1][3] == " "


def test_bot_does_not_walk_into_bomb_zone():
    cells = {(10, 5): "A", (10, 4): "a", (10, 3): "a", (2, 15): "B", (2, 16): "b",
             (2, 17): "b", (10, 12): "1", (9, 8): BOMB}
    data = make_turn(cells)
    move = bot.choose_direction(data)
    dr, dc = bot.DIRECTIONS[move] if hasattr(bot, "DIRECTIONS") else {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}[move]
    head = (10 + dr, 5 + dc)
    assert max(abs(head[0] - 9), abs(head[1] - 8)) > 2


def test_shot_food_does_not_hide_digits():
    data = make_turn({(10, 5): "A", (10, 4): "a", (2, 15): "B", (5, 5): "*", (15, 15): "3"})
    grid = adapted(data)
    assert grid[5][5] == " "
    assert bot.find_food(grid) == [(15, 15)]


def test_shot_food_kept_without_digits():
    grid = adapted(make_turn({(10, 5): "A", (2, 15): "B", (5, 5): "*"}))
    assert grid[5][5] == "*"


def test_tail_food_star_and_unknown_symbols():
    grid = adapted(make_turn({(10, 5): "A", (2, 15): "B", (1, 1): "Ⓐ", (1, 2): "Ⓑ",
                              (1, 3): "⭐", (1, 4): "?"}))
    assert grid[1][1:5] == [" ", " ", " ", "#"]


def test_variation_selector_is_ignored():
    data = make_turn({(10, 5): "A", (2, 15): "B"})
    data["board"] = data["board"].replace("|" + " " * SIZE + "|", "|⭐️" + " " * (SIZE - 1) + "|", 1)
    grid = bot.parse_turn_board(data)
    assert len(grid[0]) == SIZE and grid[0][0] == "⭐"


def test_invincible_head_is_found():
    data = make_turn({(10, 5): "a", (10, 4): "A", (10, 3): "A", (2, 15): "B"}, invincible_1=True)
    grid = adapted(data)
    assert bot.find_head(grid, "A") == (10, 5)
    assert bot.choose_direction(data) in {"UP", "DOWN", "LEFT", "RIGHT"}


def test_large_board_is_fast():
    cells = {(15, 15): "A", (15, 14): "a", (15, 13): "a", (5, 5): "B", (5, 6): "b",
             (20, 20): "1", (8, 22): BOMB, (25, 3): PETARDO, (12, 12): "X"}
    data = make_turn(cells, size=30)
    start = time.monotonic()
    bot.choose_direction(data)
    assert time.monotonic() - start < 0.2
