"""Deterministic behavior-preservation check against the frozen pre-refactor V7.6 snapshot."""
from __future__ import annotations

import random
import sys
import types
import uuid
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
CURRENT = ROOT / "botv8.0_v5.py"
REFERENCE = TESTS_DIR / "REFERENCE_DO_NOT_DEPLOY.snapshot"
SCENARIOS = 100
NODE_BUDGET = 24

for dependency in ("pygame", "websockets"):
    sys.modules.setdefault(dependency, types.ModuleType(dependency))


def load_source_module(path, tag):
    name = tag + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
    return module


def _snake_pattern(rows, cols, variant):
    patterns = (
        ([(1, 3), (1, 2), (1, 1)], [(rows - 2, cols - 4), (rows - 2, cols - 3), (rows - 2, cols - 2)]),
        ([(3, 1), (2, 1), (1, 1)], [(rows - 4, cols - 2), (rows - 3, cols - 2), (rows - 2, cols - 2)]),
        ([(2, 3), (2, 2), (1, 2)], [(rows - 3, cols - 4), (rows - 3, cols - 3), (rows - 2, cols - 3)]),
    )
    return patterns[variant % len(patterns)]


def _place_snake(grid, cells, head_char, body_char):
    grid[cells[0][0]][cells[0][1]] = head_char
    for row, col in cells[1:]:
        grid[row][col] = body_char


def _empty_cells(grid):
    return [(r, c) for r, row in enumerate(grid) for c, value in enumerate(row) if value == " "]


def _cyclic_digits(start):
    return [str(((start - 1 + offset) % 9) + 1) for offset in range(5)]


def _place_food(grid, rng, scenario_index):
    free = _empty_cells(grid)
    rng.shuffle(free)
    if scenario_index % 10 == 0:
        symbols = ["*", "*", "*"]
    else:
        symbols = _cyclic_digits((scenario_index % 9) + 1)
    for symbol, (row, col) in zip(symbols, free):
        grid[row][col] = symbol


def board(rows, cols, seed, scenario_index):
    rng = random.Random(seed)
    grid = [[" "] * cols for _ in range(rows)]
    snake_a, snake_b = _snake_pattern(rows, cols, scenario_index)
    _place_snake(grid, snake_a, "A", "a")
    _place_snake(grid, snake_b, "B", "b")
    _place_food(grid, rng, scenario_index)
    return "\n".join("|" + "".join(row) + "|" for row in grid) + "\n"


def _payload(index, rng):
    rows = rng.randint(12, 20)
    cols = rng.randint(12, 20)
    seed = 100_000 + index
    return {
        "game_id": f"eq_{index}",
        "board": board(rows, cols, seed, index),
        "rows": rows,
        "cols": cols,
        "board_size": f"{rows}x{cols}",
        "remaining_moves": 1 + ((299 - index * 17) % 300),
        "side": "A" if index % 2 == 0 else "B",
        "score_1": rng.randint(-500, 9000),
        "score_2": rng.randint(-500, 9000),
    }


def _compare_one(old, new, payload, index):
    old_move = old.choose_direction(payload, search_mode="nodes", node_budget=NODE_BUDGET)
    new_move = new.choose_direction(payload, search_mode="nodes", node_budget=NODE_BUDGET)
    if old_move != new_move:
        raise AssertionError(f"scenario={index}: old={old_move} new={new_move}")
    return old_move


def run_equivalence():
    old = load_source_module(REFERENCE, "old_")
    new = load_source_module(CURRENT, "new_")
    rng = random.Random(760_2026)
    counts = {"UP": 0, "DOWN": 0, "LEFT": 0, "RIGHT": 0}
    for index in range(SCENARIOS):
        move = _compare_one(old, new, _payload(index, rng), index)
        counts[move] = counts.get(move, 0) + 1
    return counts


if __name__ == "__main__":
    result = run_equivalence()
    print(f"EQUIVALENCE_PASS {SCENARIOS}/{SCENARIOS} node_budget={NODE_BUDGET} moves={result}")
