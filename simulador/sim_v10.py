"""Simulador de Snake con las reglas v1-v10 (v10 = estrella e invencibilidad, 28/10).

Arma los mismos datos que manda el servidor en `your_turn` para que cualquier bot
con `choose_direction(game_data)` pueda jugar.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

BIG, SMALL = "\U0001f4a3", "\U0001f9e8"
BOMB_RADIUS = {BIG: 2, SMALL: 1}
TAIL_FOR = {"A": "Ⓐ", "B": "Ⓑ"}  # comida que solo come A / B
DIRS = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}
TOTAL_MOVES = 400
SHOT_COST = 5000
STAR = "⭐"
INVINCIBLE_TURNS = 50
STAR_FIRST_ROUND = 20
STAR_COOLDOWN_ROUNDS = 20
FINAL_STARS = 10
FINAL_PHASE = 100  # últimas movidas: sin bombas y 10 estrellas


def cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def other_letter(letter):
    return "B" if letter == "A" else "A"


@dataclass
class Snake:
    letter: str
    body: list  # cabeza primero
    score: int = 0
    mult: int = 1
    crashes: int = 0
    xs: int = 0
    digits: int = 0
    digit_points: int = 0
    explosions: int = 0
    wrong: int = 0
    shots: int = 0
    tail_food: int = 0
    lost: bool = False
    inv: int = 0
    stars: int = 0
    rams: int = 0

    def letters(self):
        """(letra de la cabeza, letra del cuerpo): invencible = al revés."""
        low = self.letter.lower()
        return (low, self.letter) if self.inv else (self.letter, low)


@dataclass
class Game:
    rows: int
    cols: int
    rng: random.Random
    remaining: int = TOTAL_MOVES
    food: dict = field(default_factory=dict)      # pos -> char (dígitos, X, Ⓐ, Ⓑ, *, ⭐)
    bombs: dict = field(default_factory=dict)     # pos -> char
    wall: list = field(default_factory=list)
    bombs_active: bool = True
    star_ready_round: int = STAR_FIRST_ROUND
    final_stars: bool = False
    snakes: dict = field(default_factory=dict)

    # ------------------------------------------------------------ armado
    @classmethod
    def new(cls, seed, rows=None, cols=None):
        rng = random.Random(seed)
        rows = rows or rng.randint(20, 30)
        cols = cols or rng.randint(20, 30)
        g = cls(rows=rows, cols=cols, rng=rng)
        g.snakes = {
            "A": Snake("A", [(1, 3), (1, 2), (1, 1)]),
            "B": Snake("B", [(rows - 2, cols - 3), (rows - 2, cols - 2), (rows - 2, cols - 1)]),
        }
        g._setup_items()
        return g

    def _setup_items(self):
        for ch in [BIG] * 2 + [SMALL] * 5:
            self._spawn_bomb(ch)
        for d in range(1, 6):
            self._spawn_digit(d)
        for _ in range(2):
            self._spawn_item("X")
        self._spawn_wall()

    def occupied(self):
        occ = set()
        for s in self.snakes.values():
            occ.update(s.body)
        return occ

    def bomb_zone(self):
        zone = set()
        for pos, ch in self.bombs.items():
            r = BOMB_RADIUS[ch]
            span = range(-r, r + 1)
            zone.update((pos[0] + dr, pos[1] + dc) for dr in span for dc in span)
        return zone

    def _free_cells(self, avoid_zone=True):
        blocked = self.occupied() | set(self.food) | set(self.bombs) | set(self.wall)
        if avoid_zone:
            blocked |= self.bomb_zone()
        return [(r, c) for r in range(self.rows) for c in range(self.cols)
                if (r, c) not in blocked]

    def _spawn_item(self, ch):
        cells = self._free_cells()
        if cells:
            self.food[self.rng.choice(cells)] = ch

    def _spawn_digit(self, d):
        for _ in range(self.rng.randint(3, 5)):
            self._spawn_item(str(d))

    def _bomb_cell_ok(self, p, r, heads, items):
        far_heads = all(cheb(p, h) > r + 1 for h in heads)
        return far_heads and all(cheb(p, i) > r for i in items)

    def _bomb_items(self):
        return [p for p, c in self.food.items() if c.isdigit() or c == "X"]

    def _bomb_cells(self, r):
        heads = [s.body[0] for s in self.snakes.values()]
        items = self._bomb_items()
        return [p for p in self._free_cells(avoid_zone=False)
                if self._bomb_cell_ok(p, r, heads, items)]

    def _spawn_bomb(self, ch):
        if not self.bombs_active:
            return
        cells = self._bomb_cells(BOMB_RADIUS[ch])
        if cells:
            self.bombs[self.rng.choice(cells)] = ch

    def _wall_candidate(self, length):
        vertical = self.rng.random() < 0.5
        r = self.rng.randrange(self.rows - (length if vertical else 0))
        c = self.rng.randrange(self.cols - (0 if vertical else length))
        return [(r + i, c) if vertical else (r, c + i) for i in range(length)]

    def _spawn_wall(self):
        length = self.rng.choice([3, 5, 7, 9, 11])
        for _ in range(200):
            cells = self._wall_candidate(length)
            blocked = self.occupied() | set(self.food) | set(self.bombs)
            if not any(p in blocked for p in cells):
                self.wall = cells
                return
        self.wall = []

    def _round_end(self):
        """Después de que mueven los dos: el muro se achica; si desaparece, sale otro."""
        self.wall = self.wall[1:-1]
        if not self.wall:
            self._spawn_wall()

    # ------------------------------------------------------------ vista
    def _digits_present(self):
        return {int(c) for c in self.food.values() if c.isdigit()}

    def target(self):
        present = self._digits_present()
        firsts = [d for d in sorted(present) if (d + 7) % 9 + 1 not in present]
        return firsts[0] if firsts else None

    def _paint(self, grid, cells):
        for p, ch in cells:
            grid[p[0]][p[1]] = ch

    def board_rows(self):
        grid = [[" "] * self.cols for _ in range(self.rows)]
        self._paint(grid, [(p, "#") for p in self.wall])
        self._paint(grid, self.bombs.items())
        self._paint(grid, self.food.items())
        for s in self.snakes.values():
            self._paint(grid, self._snake_cells(s))
        return grid

    @staticmethod
    def _snake_cells(s):
        head, body = s.letters()
        return [(p, head if i == 0 else body) for i, p in enumerate(s.body)]

    def board_str(self):
        return "".join("|" + "".join(row) + "|\n" for row in self.board_rows())

    def payload(self, side, game_id, names=("p1", "p2")):
        a, b = self.snakes["A"], self.snakes["B"]
        return {
            "board": self.board_str(), "rows": self.rows, "cols": self.cols,
            "board_size": f"{self.rows}x{self.cols}", "remaining_moves": self.remaining,
            "side": side, "player_1": names[0], "player_2": names[1],
            "score_1": a.score, "score_2": b.score,
            "multiplier_1": a.mult, "multiplier_2": b.mult,
            "invincible_1": a.inv, "invincible_2": b.inv,
            "game_id": game_id, "turn_token": "t",
        }

    # ------------------------------------------------------------ reglas
    @staticmethod
    def _crash_penalty(s):
        """El primer choque deja en 0 (si tenías puntos); los demás, -500."""
        s.score = 0 if s.crashes == 0 and s.score > 0 else s.score - 500
        s.crashes += 1

    @staticmethod
    def _bomb_penalty(s):
        s.score = 0 if s.score > 0 else s.score - 500
        s.explosions += 1

    def _penalize(self, s, kind):
        """Choque o explosión. v10: invencible no pierde puntos por nada."""
        if s.inv:
            return
        (self._crash_penalty if kind == "crash" else self._bomb_penalty)(s)
        if s.score < -2500:
            s.lost = True

    def _drop_as_food(self, cells, ch):
        zone = self.bomb_zone()
        for p in cells:
            if p not in zone:
                self.food[p] = ch

    def _crash(self, s):
        if s.inv:
            return  # v10: se queda quieta, sin perder cola
        dropped = s.body[3:]
        s.body = s.body[:3]
        self._drop_as_food(dropped, TAIL_FOR[other_letter(s.letter)])
        self._penalize(s, "crash")

    def _eat_target(self, s, ch):
        d = int(ch)
        s.score += d * 100 * s.mult
        s.digits += 1
        s.digit_points += d * 100 * s.mult
        for p in [p for p, c in self.food.items() if c == ch]:
            del self.food[p]
        self._spawn_digit((d + 4) % 9 + 1)
        return True

    def _eat_wrong(self, s, ch):
        s.wrong += 1
        self._spawn_item(ch)
        if s.inv:
            return True  # v10: invencible, fuera de orden no cuesta y crece
        s.score -= 500
        return False

    def _eat_digit(self, s, ch):
        if int(ch) == self.target():
            return self._eat_target(s, ch)
        return self._eat_wrong(s, ch)

    def _eat_x(self, s, ch):
        s.score += 50
        s.mult += 1
        s.xs += 1
        self._spawn_item("X")
        return False

    def _eat_star(self, s, ch):
        s.score += 100 * s.mult
        s.inv = INVINCIBLE_TURNS
        s.stars += 1
        if self.final_stars:
            self._spawn_item(STAR)
        return True

    def _eat_bonus(self, s, ch):
        s.score += 100 * s.mult
        s.tail_food += 1
        return True

    def _eater(self, s, ch):
        if ch.isdigit():
            return self._eat_digit
        if ch == TAIL_FOR[s.letter]:
            return self._eat_bonus
        return {"X": self._eat_x, STAR: self._eat_star, "*": self._eat_bonus}.get(ch)

    def _eat(self, s, pos):
        """Aplica lo que hay en `pos`. Devuelve True si la serpiente crece."""
        ch = self.food.pop(pos, None)
        eater = None if ch is None else self._eater(s, ch)
        if eater is None:
            s.score += 1  # vacío o cola soltada que no es mía: se borra
            return False
        return eater(s, ch)

    def _bombs_hit(self, head):
        return [p for p, ch in self.bombs.items() if cheb(p, head) <= BOMB_RADIUS[ch]]

    def _check_bombs(self, s):
        hit = self._bombs_hit(s.body[0])
        if not hit:
            return
        kinds = [self.bombs.pop(p) for p in hit]
        self._penalize(s, "bomb")
        for ch in kinds:
            self._spawn_bomb(ch)

    def _inside(self, pos):
        return 0 <= pos[0] < self.rows and 0 <= pos[1] < self.cols

    def _shot_hit(self, start, delta, enemy):
        """Primera casilla del rival en la línea del disparo (o None)."""
        r, c = start
        while True:
            r, c = r + delta[0], c + delta[1]
            if not self._inside((r, c)) or (r, c) in self.wall:
                return None
            if (r, c) in enemy.body:
                return r, c

    def _shoot(self, s, direction):
        if s.score < SHOT_COST:
            s.score -= 500
            return
        s.score -= SHOT_COST
        s.shots += 1
        enemy = self.snakes[other_letter(s.letter)]
        hit = self._shot_hit(s.body[0], DIRS[direction], enemy)
        if hit and not enemy.inv:
            self._cut(enemy, hit)

    def _cut(self, enemy, cell):
        """Corta al rival desde `cell` hasta la cola; esas casillas pasan a ser *."""
        idx = max(enemy.body.index(cell), 1)
        cut = enemy.body[idx:]
        enemy.body = enemy.body[:idx]
        self._drop_as_food(cut, "*")

    def _round(self):
        return (TOTAL_MOVES - self.remaining) // 2

    def _star_count(self):
        return list(self.food.values()).count(STAR)

    def _star_cells(self):
        """Casillas libres lo más equidistantes posible de las dos cabezas."""
        ha, hb = (s.body[0] for s in self.snakes.values())
        cells = self._free_cells()
        gaps = {p: abs(manhattan(p, ha) - manhattan(p, hb)) for p in cells}
        best = min(gaps.values(), default=None)
        return [p for p in cells if gaps[p] == best]

    def _start_final_stars(self):
        self.final_stars = True
        for _ in range(FINAL_STARS - self._star_count()):
            self._spawn_item(STAR)

    def _spawn_regular_star(self):
        if any(s.inv for s in self.snakes.values()):
            self.star_ready_round = self._round() + STAR_COOLDOWN_ROUNDS + 1
            return
        cells = self._star_cells() if self._round() >= self.star_ready_round else []
        if cells:
            self.food[self.rng.choice(cells)] = STAR

    def _update_stars(self):
        """v10: una estrella por vez desde la ronda 20; 10 juntas en las últimas 100."""
        if self.remaining <= FINAL_PHASE and not self.final_stars:
            self._start_final_stars()
        elif not self.final_stars and not self._star_count():
            self._spawn_regular_star()

    def _end_bombs(self):
        if self.remaining <= FINAL_PHASE and self.bombs_active:
            self.bombs_active = False
            self.bombs.clear()

    def _act(self, s, other, action):
        if isinstance(action, tuple):
            self._shoot(s, action[1].upper())
        else:
            self._move(s, other, str(action).upper())

    def play(self, letter, action):
        """Aplica la jugada de `letter`. action = 'UP' o ('shoot', 'UP')."""
        s = self.snakes[letter]
        self._act(s, self.snakes[other_letter(letter)], action)
        self.remaining -= 1
        s.inv = max(0, s.inv - 1)
        if letter == "B":
            self._round_end()
        self._update_stars()
        self._end_bombs()

    def _grows_into(self, s, ch):
        """True si comer `ch` hace crecer (la cola no se mueve este turno)."""
        if ch is None:
            return False
        if ch.isdigit():
            return bool(s.inv) or int(ch) == self.target()
        return ch in ("*", STAR, TAIL_FOR[s.letter])

    def _blocked(self, s, other, new, grows):
        own_block = s.body if grows else s.body[:-1]
        if not self._inside(new) or new in self.wall:
            return True
        return new in own_block or new in other.body

    def _step(self, s, new):
        grows = self._eat(s, new)
        s.body.insert(0, new)
        if not grows:
            s.body.pop()
        self._check_bombs(s)

    def _move(self, s, other, direction):
        if direction not in DIRS:
            s.score -= 500
            return
        dr, dc = DIRS[direction]
        new = (s.body[0][0] + dr, s.body[0][1] + dc)
        if s.inv and new in other.body:
            self._cut(other, new)   # v10: invencible corta al rival que choca
            s.rams += 1
            return
        if self._blocked(s, other, new, self._grows_into(s, self.food.get(new))):
            self._crash(s)
            return
        self._step(s, new)

    def over(self):
        return self.remaining <= 0 or any(s.lost for s in self.snakes.values())

    def winner(self):
        a, b = self.snakes["A"], self.snakes["B"]
        if a.lost != b.lost:
            return "B" if a.lost else "A"
        if a.score == b.score:
            return None
        return "A" if a.score > b.score else "B"
