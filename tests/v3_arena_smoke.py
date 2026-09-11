"""Small deterministic v3 arena smoke test for rectangular boards and numbered food."""
from __future__ import annotations

import random
import sys
import types
import uuid
from collections import deque
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
BOT = ROOT / "botv8.0_v5.py"
DIRS = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}

for dependency in ("pygame", "websockets"):
    sys.modules.setdefault(dependency, types.ModuleType(dependency))


def load_bot():
    name = "smoke_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(BOT)
    sys.modules[name] = module
    exec(compile(BOT.read_text(encoding="utf-8"), str(BOT), "exec"), module.__dict__)
    module.FE_NODE_BUDGET = 80
    module.TACTICAL_SOLVER_NODE_BUDGET = 150
    module.FORCED_TRAP_MAX_ROUNDS = 2
    return module


def predecessor(digit):
    return 9 if digit == 1 else digit - 1


def correct_digit(food):
    present = set(food)
    candidates = [digit for digit in present if predecessor(digit) not in present]
    if len(candidates) != 1:
        raise AssertionError(f"invalid v3 food window: {sorted(present)}")
    return candidates[0]


class Arena:
    def __init__(self, seed, rows, cols):
        self.rng = random.Random(seed)
        self.rows = rows
        self.cols = cols
        self.remaining = 300
        self.turn = "A"
        self.score_a = 0
        self.score_b = 0
        self.a = deque([(1, 3), (1, 2), (1, 1)])
        self.b = deque([(rows - 2, cols - 4), (rows - 2, cols - 3), (rows - 2, cols - 2)])
        self.food = {}
        self.next_spawn = 6
        for digit in range(1, 6):
            self.spawn(digit)

    def occupied(self):
        return set(self.a) | set(self.b) | set(self.food.values())

    def spawn(self, digit):
        occupied = self.occupied()
        free = [(r, c) for r in range(self.rows) for c in range(self.cols) if (r, c) not in occupied]
        self.food[digit] = self.rng.choice(free)

    def board(self):
        grid = [[" "] * self.cols for _ in range(self.rows)]
        self._draw_food(grid)
        self._draw_snake(grid, self.a, "A", "a")
        self._draw_snake(grid, self.b, "B", "b")
        return "\n".join("|" + "".join(row) + "|" for row in grid) + "\n"

    def _draw_food(self, grid):
        for digit, (row, col) in self.food.items():
            grid[row][col] = str(digit)

    @staticmethod
    def _draw_snake(grid, body, head_char, body_char):
        for row, col in list(body)[1:]:
            grid[row][col] = body_char
        row, col = body[0]
        grid[row][col] = head_char

    def _moving_context(self, side, bot_a, bot_b):
        if side == "A":
            return bot_a, self.a, self.b
        return bot_b, self.b, self.a

    def _payload(self, game_id, side):
        return {
            "game_id": game_id,
            "board": self.board(),
            "rows": self.rows,
            "cols": self.cols,
            "board_size": f"{self.rows}x{self.cols}",
            "remaining_moves": self.remaining,
            "side": side,
            "score_1": self.score_a,
            "score_2": self.score_b,
        }

    @staticmethod
    def _next_position(body, move):
        dr, dc = DIRS[move]
        return body[0][0] + dr, body[0][1] + dc

    def _digit_at(self, position):
        for digit, food_pos in self.food.items():
            if food_pos == position:
                return digit
        return None

    def _inside(self, position):
        row, col = position
        return 0 <= row < self.rows and 0 <= col < self.cols

    def _collides(self, position, body, other, grows):
        own_occupied = set(body) if grows else set(list(body)[:-1])
        return (not self._inside(position)) or position in own_occupied or position in set(other)

    def _next_digit_value(self):
        value = self.next_spawn
        self.next_spawn = 1 if value == 9 else value + 1
        return value

    def _eat_correct(self, body, digit):
        del self.food[digit]
        self.spawn(self._next_digit_value())
        return digit * 100

    def _eat_wrong(self, body, digit):
        body.pop()
        del self.food[digit]
        self.spawn(digit)
        return -500

    @staticmethod
    def _normal_move(body):
        body.pop()
        return 1

    def _apply_cell(self, body, digit, is_correct):
        if digit is None:
            return self._normal_move(body)
        if is_correct:
            return self._eat_correct(body, digit)
        return self._eat_wrong(body, digit)

    def _add_score(self, side, delta):
        if side == "A":
            self.score_a += delta
            return
        self.score_b += delta

    def step(self, bot_a, bot_b, game_id):
        side = self.turn
        module, body, other = self._moving_context(side, bot_a, bot_b)
        move = module.choose_direction(self._payload(game_id, side), search_mode="nodes", node_budget=40)
        if move not in DIRS:
            raise AssertionError(f"invalid move: {move}")
        position = self._next_position(body, move)
        digit = self._digit_at(position)
        is_correct = digit is not None and digit == correct_digit(self.food)
        if self._collides(position, body, other, is_correct):
            return side
        body.appendleft(position)
        self._add_score(side, self._apply_cell(body, digit, is_correct))
        self.remaining -= 1
        self.turn = "B" if side == "A" else "A"
        return None

    def result(self, turns, death):
        return {"turns": turns, "death": death, "score": (self.score_a, self.score_b)}

    def run(self, bot_a, bot_b, max_turns=24):
        game_id = "smoke"
        for turn_index in range(max_turns):
            death = self.step(bot_a, bot_b, game_id)
            if death is not None:
                return self.result(turn_index + 1, death)
        return self.result(max_turns, None)


def run_smoke_case(seed, size):
    bot_a = load_bot()
    bot_b = load_bot()
    return Arena(seed, *size).run(bot_a, bot_b)


def main():
    sizes = [(12, 20), (20, 12), (12, 12), (20, 20), (17, 14)]
    for index, size in enumerate(sizes, 1):
        print(size, run_smoke_case(8800 + index, size))


if __name__ == "__main__":
    main()
