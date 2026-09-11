#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snake Arena interactiva
-----------------------
- Busca bots recursivamente desde la carpeta del proyecto.
- Permite ChatGPT vs Gemini, dos versiones del mismo autor o self-play.
- Tableros variables 12..20 (rectangulares incluidos) o tamaño fijo.
- Reglas actuales con '*' y modo v3 opcional con comida numerada 1..9.
- Empareja lados A/B por seed para comparar de forma más justa.
- No requiere escribir rutas largas.

Uso normal:
    python arena.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
import traceback
import types
import uuid
from collections import deque
from dataclasses import dataclass, asdict, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_MOVES = 300
LEGACY_FOOD_COUNT = 3
V3_FOOD_COUNT = 5
MIN_BOARD = 12
MAX_BOARD = 20
NOMINAL_BOT_LIMIT_MS = 80.0

DIRECTIONS = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}

IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "tests", "test",
}
IGNORED_FILES = {
    "arena.py", "snake_runtime.py", "snake_visualizer.py", "run.py",
    "setup.py", "conftest.py",
}


# ============================================================================
# Descubrimiento y carga de bots
# ============================================================================

def _looks_like_bot(path: Path) -> bool:
    if path.name.lower() in IGNORED_FILES:
        return False
    if any(part.lower() in IGNORED_DIRS for part in path.parts):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "def choose_direction" in text


def discover_bots(root: Path) -> List[Path]:
    bots = [p for p in root.rglob("*.py") if _looks_like_bot(p)]
    return sorted(bots, key=lambda p: str(p.relative_to(root)).lower())


def display_name(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def load_bot_module(file_path: Path) -> Tuple[types.ModuleType, str]:
    """Carga una copia aislada del bot. Permite cargar el mismo archivo dos veces."""
    file_path = file_path.resolve()
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    module_name = f"snake_arena_{file_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"No se pudo crear loader para {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    # Algunos bots tienen helpers locales al lado del .py.
    parent = str(file_path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        if inserted:
            try:
                sys.path.remove(parent)
            except ValueError:
                pass

    if not callable(getattr(module, "choose_direction", None)):
        sys.modules.pop(module_name, None)
        raise AttributeError(f"{file_path.name} no define choose_direction(game_data)")
    return module, module_name


def unload_bot_module(module_name: str) -> None:
    sys.modules.pop(module_name, None)


# ============================================================================
# Motor de juego
# ============================================================================

def _advance_digit(digit: str, steps: int = 1) -> str:
    value = int(digit)
    return str(((value - 1 + steps) % 9) + 1)


def _cyclic_predecessor(digit: str) -> str:
    return _advance_digit(digit, -1)


def correct_digit_from_present(present: Iterable[str]) -> Optional[str]:
    present_set = set(present)
    if not present_set:
        return None
    candidates = [d for d in present_set if _cyclic_predecessor(d) not in present_set]
    if len(candidates) == 1:
        return candidates[0]

    # Fallback defensivo para tableros malformados: elegir el inicio de la
    # secuencia consecutiva más larga.
    best = None
    best_len = -1
    for digit in sorted(present_set, key=int):
        length = 0
        cur = digit
        while cur in present_set and length < 9:
            length += 1
            cur = _advance_digit(cur)
        if length > best_len:
            best_len = length
            best = digit
    return best


@dataclass
class TurnTiming:
    samples_ms: List[float] = field(default_factory=list)
    overruns_80ms: int = 0
    exceptions: int = 0

    def add(self, ms: float) -> None:
        self.samples_ms.append(ms)
        if ms > NOMINAL_BOT_LIMIT_MS:
            self.overruns_80ms += 1

    def summary(self) -> Dict[str, float]:
        if not self.samples_ms:
            return {"calls": 0, "avg_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "over80": 0}
        values = sorted(self.samples_ms)
        def pct(p: float) -> float:
            idx = min(len(values) - 1, max(0, math.ceil(p * len(values)) - 1))
            return values[idx]
        return {
            "calls": len(values),
            "avg_ms": sum(values) / len(values),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "max_ms": max(values),
            "over80": self.overruns_80ms,
        }


@dataclass
class GameResult:
    seed: int
    rows: int
    cols: int
    rules: str
    bot_a_label: str
    bot_b_label: str
    winner_side: Optional[str]
    winner_label: Optional[str]
    draw: bool
    score_a: int
    score_b: int
    correct_food_a: int
    correct_food_b: int
    wrong_food_a: int
    wrong_food_b: int
    death_side: Optional[str]
    death_reason: Optional[str]
    total_turns: int
    technical_loss_side: Optional[str] = None
    timing_a: Dict[str, float] = field(default_factory=dict)
    timing_b: Dict[str, float] = field(default_factory=dict)


class SnakeArenaEngine:
    def __init__(
        self,
        bot_a_label: str,
        bot_b_label: str,
        rows: int,
        cols: int,
        seed: int,
        rules: str = "legacy",
        max_moves: int = MAX_MOVES,
    ):
        if rows < MIN_BOARD or cols < MIN_BOARD:
            raise ValueError("El tablero debe ser al menos 12x12 para estas posiciones iniciales")
        self.rows = rows
        self.cols = cols
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.rules = rules
        self.max_moves = max_moves
        self.bot_a_label = bot_a_label
        self.bot_b_label = bot_b_label
        self.game_id = f"arena-{uuid.uuid4()}"

        self.remaining_moves = max_moves
        self.current_turn = "A"
        self.score_a = 0
        self.score_b = 0
        self.correct_food_a = 0
        self.correct_food_b = 0
        self.wrong_food_a = 0
        self.wrong_food_b = 0
        self.game_over = False
        self.winner_side: Optional[str] = None
        self.death_side: Optional[str] = None
        self.death_reason: Optional[str] = None
        self.technical_loss_side: Optional[str] = None
        self.turn_count = 0

        self.body_a = deque([(1, 3), (1, 2), (1, 1)])
        self.body_b = deque([
            (rows - 2, cols - 4),
            (rows - 2, cols - 3),
            (rows - 2, cols - 2),
        ])

        self.legacy_food: set[Tuple[int, int]] = set()
        self.numbered_food: Dict[str, Tuple[int, int]] = {}
        if rules == "v3":
            for digit in "12345":
                self._spawn_numbered_digit(digit)
        else:
            self._fill_legacy_food()

    # ---- food ---------------------------------------------------------------
    def _snake_occupied(self) -> set[Tuple[int, int]]:
        return set(self.body_a) | set(self.body_b)

    def _food_positions(self) -> set[Tuple[int, int]]:
        if self.rules == "v3":
            return set(self.numbered_food.values())
        return set(self.legacy_food)

    def _empty_cells(self) -> List[Tuple[int, int]]:
        occupied = self._snake_occupied() | self._food_positions()
        return [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if (r, c) not in occupied
        ]

    def _spawn_one_position(self) -> Optional[Tuple[int, int]]:
        empty = self._empty_cells()
        return self.rng.choice(empty) if empty else None

    def _fill_legacy_food(self) -> None:
        while len(self.legacy_food) < LEGACY_FOOD_COUNT:
            pos = self._spawn_one_position()
            if pos is None:
                break
            self.legacy_food.add(pos)

    def _spawn_numbered_digit(self, digit: str) -> None:
        pos = self._spawn_one_position()
        if pos is not None:
            self.numbered_food[digit] = pos

    def correct_digit(self) -> Optional[str]:
        return correct_digit_from_present(self.numbered_food.keys())

    # ---- board/payload ------------------------------------------------------
    def board_string(self) -> str:
        grid = [[" " for _ in range(self.cols)] for _ in range(self.rows)]
        if self.rules == "v3":
            for digit, (r, c) in self.numbered_food.items():
                grid[r][c] = digit
        else:
            for r, c in self.legacy_food:
                grid[r][c] = "*"

        for r, c in list(self.body_a)[1:]:
            grid[r][c] = "a"
        if self.body_a:
            r, c = self.body_a[0]
            grid[r][c] = "A"

        for r, c in list(self.body_b)[1:]:
            grid[r][c] = "b"
        if self.body_b:
            r, c = self.body_b[0]
            grid[r][c] = "B"

        return "\n".join("|" + "".join(row) + "|" for row in grid) + "\n"

    def payload(self, side: str) -> Dict[str, object]:
        return {
            "game_id": self.game_id,
            "turn_token": str(uuid.uuid4()),
            "board": self.board_string(),
            "remaining_moves": self.remaining_moves,
            "rows": self.rows,
            "cols": self.cols,
            "board_size": f"{self.rows}x{self.cols}",
            "side": side,
            "player_1": self.bot_a_label,
            "score_1": self.score_a,
            "player_2": self.bot_b_label,
            "score_2": self.score_b,
        }

    # ---- movement -----------------------------------------------------------
    def _inside(self, pos: Tuple[int, int]) -> bool:
        return 0 <= pos[0] < self.rows and 0 <= pos[1] < self.cols

    def _food_at(self, pos: Tuple[int, int]) -> Optional[str]:
        if self.rules == "legacy":
            return "*" if pos in self.legacy_food else None
        for digit, food_pos in self.numbered_food.items():
            if food_pos == pos:
                return digit
        return None

    def _growth_and_score(self, food_symbol: Optional[str]) -> Tuple[bool, Optional[int], bool]:
        """(grows, score_delta_if_food, is_wrong_numbered)."""
        if food_symbol is None:
            return False, None, False
        if self.rules == "legacy":
            return True, 100, False
        correct = self.correct_digit()
        if food_symbol == correct:
            return True, int(food_symbol) * 100, False
        return False, -500, True

    def _apply_food_effect(self, side: str, symbol: str, score_delta: int, wrong: bool) -> None:
        if side == "A":
            self.score_a += score_delta
            if wrong:
                self.wrong_food_a += 1
            else:
                self.correct_food_a += 1
        else:
            self.score_b += score_delta
            if wrong:
                self.wrong_food_b += 1
            else:
                self.correct_food_b += 1

        if self.rules == "legacy":
            pos_to_remove = next((p for p in self.legacy_food if p == self._last_next_head), None)
            if pos_to_remove is not None:
                self.legacy_food.remove(pos_to_remove)
            self._fill_legacy_food()
            return

        # v3
        self.numbered_food.pop(symbol, None)
        if wrong:
            # Mismo dígito reaparece en otro lugar.
            self._spawn_numbered_digit(symbol)
        else:
            # Siempre quedan cinco consecutivos: tras comer d aparece d+5 (mod 9).
            new_digit = _advance_digit(symbol, 5)
            self._spawn_numbered_digit(new_digit)

    def forfeit(self, side: str, reason: str) -> None:
        if self.game_over:
            return
        self.game_over = True
        self.technical_loss_side = side
        self.death_side = side
        self.death_reason = reason
        other = "B" if side == "A" else "A"
        self.winner_side = other
        if side == "A":
            self.score_a -= 500
            self.score_b += 1000
        else:
            self.score_b -= 500
            self.score_a += 1000

    def step(self, direction: str) -> None:
        if self.game_over:
            return
        side = self.current_turn
        active = self.body_a if side == "A" else self.body_b
        other = self.body_b if side == "A" else self.body_a

        move = str(direction).upper()
        if move not in DIRECTIONS:
            self.forfeit(side, f"Dirección inválida: {direction!r}")
            return

        dr, dc = DIRECTIONS[move]
        head = active[0]
        next_head = (head[0] + dr, head[1] + dc)
        self._last_next_head = next_head
        food_symbol = self._food_at(next_head)
        grows, food_score, wrong = self._growth_and_score(food_symbol)

        # La cola propia se libera si este movimiento NO hace crecer.
        own_obstacles = set(active) if grows else set(list(active)[:-1])
        other_obstacles = set(other)

        collision_reason = None
        if not self._inside(next_head):
            collision_reason = "pared"
        elif next_head in own_obstacles:
            collision_reason = "cuerpo propio"
        elif next_head in other_obstacles:
            collision_reason = "cuerpo rival"

        self.turn_count += 1
        if collision_reason is not None:
            self.game_over = True
            self.death_side = side
            self.death_reason = collision_reason
            self.winner_side = "B" if side == "A" else "A"
            if side == "A":
                self.score_a -= 500
                self.score_b += 1000
            else:
                self.score_b -= 500
                self.score_a += 1000
            return

        active.appendleft(next_head)
        if grows:
            pass
        else:
            active.pop()

        if food_symbol is not None and food_score is not None:
            self._apply_food_effect(side, food_symbol, food_score, wrong)
        else:
            if side == "A":
                self.score_a += 1
            else:
                self.score_b += 1

        self.remaining_moves -= 1
        if self.remaining_moves <= 0:
            self.game_over = True
            if self.score_a > self.score_b:
                self.winner_side = "A"
            elif self.score_b > self.score_a:
                self.winner_side = "B"
            else:
                self.winner_side = None
            return

        self.current_turn = "B" if side == "A" else "A"

    def result(self, timing_a: TurnTiming, timing_b: TurnTiming) -> GameResult:
        draw = self.game_over and self.winner_side is None
        winner_label = None
        if self.winner_side == "A":
            winner_label = self.bot_a_label
        elif self.winner_side == "B":
            winner_label = self.bot_b_label
        return GameResult(
            seed=self.seed,
            rows=self.rows,
            cols=self.cols,
            rules=self.rules,
            bot_a_label=self.bot_a_label,
            bot_b_label=self.bot_b_label,
            winner_side=self.winner_side,
            winner_label=winner_label,
            draw=draw,
            score_a=self.score_a,
            score_b=self.score_b,
            correct_food_a=self.correct_food_a,
            correct_food_b=self.correct_food_b,
            wrong_food_a=self.wrong_food_a,
            wrong_food_b=self.wrong_food_b,
            death_side=self.death_side,
            death_reason=self.death_reason,
            total_turns=self.turn_count,
            technical_loss_side=self.technical_loss_side,
            timing_a=timing_a.summary(),
            timing_b=timing_b.summary(),
        )


# ============================================================================
# Ejecución de partidas
# ============================================================================

def timed_choose(module: types.ModuleType, payload: Dict[str, object], timing: TurnTiming) -> str:
    start = time.perf_counter()
    try:
        move = module.choose_direction(payload)
    except Exception:
        timing.exceptions += 1
        raise
    finally:
        timing.add((time.perf_counter() - start) * 1000.0)
    return str(move).upper()


def run_game(
    path_a: Path,
    path_b: Path,
    label_a: str,
    label_b: str,
    rows: int,
    cols: int,
    seed: int,
    rules: str,
    max_moves: int = MAX_MOVES,
    visual: bool = False,
    visual_log_callback: Optional[Callable[[GameResult], None]] = None,
) -> GameResult:
    # En modo visual, la propia sesión administra la recarga de los módulos.
    # Esto permite reiniciar una partida con R sin conservar globals/historiales
    # del intento anterior.
    if visual:
        return _run_visual_game(
            path_a, path_b, label_a, label_b,
            rows, cols, seed, rules, max_moves=max_moves,
            on_save_log=visual_log_callback,
        )

    mod_a = mod_b = None
    name_a = name_b = None
    timing_a, timing_b = TurnTiming(), TurnTiming()
    engine = SnakeArenaEngine(label_a, label_b, rows, cols, seed, rules, max_moves=max_moves)
    try:
        mod_a, name_a = load_bot_module(path_a)
        mod_b, name_b = load_bot_module(path_b)

        while not engine.game_over:
            side = engine.current_turn
            module = mod_a if side == "A" else mod_b
            timing = timing_a if side == "A" else timing_b
            try:
                move = timed_choose(module, engine.payload(side), timing)
            except Exception as exc:
                short = f"Excepción {type(exc).__name__}: {exc}"
                engine.forfeit(side, short)
                print(f"\n[ERROR BOT {side}] {short}")
                traceback.print_exc(limit=2)
                break
            engine.step(move)
        return engine.result(timing_a, timing_b)
    finally:
        if name_a:
            unload_bot_module(name_a)
        if name_b:
            unload_bot_module(name_b)


VISUAL_HUD_HEIGHT = 145
VISUAL_MIN_CELL = 12
VISUAL_MAX_CELL = 36
VISUAL_PREFERRED_WIDTH = 760
# Margen para bordes/título de ventana y barra de tareas de Windows.
VISUAL_DESKTOP_MARGIN_X = 40
VISUAL_DESKTOP_MARGIN_Y = 110


def _fit_visual_geometry(rows: int, cols: int, desktop_w: int, desktop_h: int):
    """Calcula un tablero que entre completo en el escritorio visible."""
    desktop_w = max(480, int(desktop_w or 1280))
    desktop_h = max(480, int(desktop_h or 800))

    usable_w = max(320, desktop_w - VISUAL_DESKTOP_MARGIN_X)
    usable_h = max(320, desktop_h - VISUAL_DESKTOP_MARGIN_Y)

    max_by_width = max(1, usable_w // max(1, cols))
    board_height_budget = max(1, usable_h - VISUAL_HUD_HEIGHT)
    max_by_height = max(1, board_height_budget // max(1, rows))

    cell = min(VISUAL_MAX_CELL, max_by_width, max_by_height)
    cell = max(VISUAL_MIN_CELL, cell)

    # En escritorios muy pequeños prioriza que TODO el tablero sea visible.
    if rows * cell + VISUAL_HUD_HEIGHT > usable_h:
        cell = max(6, board_height_budget // max(1, rows))
    if cols * cell > usable_w:
        cell = max(6, usable_w // max(1, cols))

    board_w = cols * cell
    board_h = rows * cell
    preferred_w = min(VISUAL_PREFERRED_WIDTH, usable_w)
    width = min(usable_w, max(board_w, preferred_w))
    height = min(usable_h, board_h + VISUAL_HUD_HEIGHT)
    return cell, VISUAL_HUD_HEIGHT, width, height


def _run_visual_game(
    path_a: Path,
    path_b: Path,
    label_a: str,
    label_b: str,
    rows: int,
    cols: int,
    seed: int,
    rules: str,
    max_moves: int = MAX_MOVES,
    on_save_log: Optional[Callable[[GameResult], None]] = None,
) -> GameResult:
    """Sesión visual persistente con reinicio rápido.

    Controles:
      R / ENTER -> reiniciar misma seed y mismos lados (módulos recargados)
      N         -> nueva seed (+1), mismo tamaño
      TAB       -> intercambiar A/B y reiniciar
      ESPACIO   -> pausa
      ARRIBA/ABAJO -> velocidad
      CLICK "Guardar log" -> guardar solo esta partida visual
      ESC       -> volver al menú

    La ventana NO se cierra sola al terminar: queda mostrando el resultado y
    los controles. Así no hay que relanzar arena.py para repetir una partida.
    """
    try:
        import pygame
    except ImportError:
        print("No está instalado pygame. Corriendo sin ventana.")
        return run_game(
            path_a, path_b, label_a, label_b,
            rows, cols, seed, rules, max_moves=max_moves, visual=False,
        )

    pygame.init()
    pygame.display.set_caption("Snake Arena local")
    font = pygame.font.SysFont("consolas", 15, bold=True)
    small = pygame.font.SysFont("consolas", 12)
    clock = pygame.time.Clock()

    fps = 20
    paused = False
    running = True
    current_seed = int(seed)
    current_path_a, current_path_b = Path(path_a), Path(path_b)
    current_label_a, current_label_b = label_a, label_b

    engine = None
    mod_a = mod_b = None
    name_a = name_b = None
    timing_a = timing_b = None
    last_completed_result: Optional[GameResult] = None
    save_log_requested = False
    save_log_done = False

    # Se recalculan al crear/reiniciar la partida.
    screen = None
    cell = 24
    hud = 145
    width = height = 0
    digit_font = None

    def unload_current_modules() -> None:
        nonlocal mod_a, mod_b, name_a, name_b
        if name_a:
            unload_bot_module(name_a)
        if name_b:
            unload_bot_module(name_b)
        mod_a = mod_b = None
        name_a = name_b = None

    def start_match() -> None:
        nonlocal engine, mod_a, mod_b, name_a, name_b
        nonlocal timing_a, timing_b, screen, cell, hud, width, height, digit_font, paused
        nonlocal save_log_requested, save_log_done
        unload_current_modules()
        timing_a, timing_b = TurnTiming(), TurnTiming()
        engine = SnakeArenaEngine(
            current_label_a, current_label_b,
            rows, cols, current_seed, rules, max_moves=max_moves,
        )
        mod_a, name_a = load_bot_module(current_path_a)
        try:
            mod_b, name_b = load_bot_module(current_path_b)
        except Exception:
            if name_a:
                unload_bot_module(name_a)
            mod_a = None
            name_a = None
            raise

        display_info = pygame.display.Info()
        cell, hud, width, height = _fit_visual_geometry(
            engine.rows, engine.cols,
            display_info.current_w, display_info.current_h,
        )
        screen = pygame.display.set_mode((width, height))
        digit_font = pygame.font.SysFont("consolas", max(14, cell // 2), bold=True)
        paused = False
        # Cada partida visual empieza sin guardar. El usuario debe pulsar el
        # botón expresamente para conservar SU log. Reiniciar/nueva seed/TAB
        # vuelve a dejarlo desactivado.
        save_log_requested = False
        save_log_done = False

    def log_button_rect() -> pygame.Rect:
        assert engine is not None
        y = engine.rows * cell
        return pygame.Rect(width - 174, y + 78, 164, 30)

    def save_visual_log_if_ready() -> None:
        nonlocal save_log_done, last_completed_result
        if (
            on_save_log is None
            or not save_log_requested
            or save_log_done
            or engine is None
            or timing_a is None
            or timing_b is None
            or not engine.game_over
        ):
            return
        result = engine.result(timing_a, timing_b)
        last_completed_result = result
        on_save_log(result)
        save_log_done = True

    def draw() -> None:
        assert engine is not None and screen is not None and digit_font is not None
        screen.fill((18, 18, 20))
        board = engine.board_string().splitlines()
        clean = [line[1:-1] for line in board if line.startswith("|") and line.endswith("|")]
        for r, row in enumerate(clean):
            for c, value in enumerate(row):
                rect = pygame.Rect(c * cell, r * cell, cell, cell)
                pygame.draw.rect(screen, (30, 30, 33), rect)
                pygame.draw.rect(screen, (45, 45, 48), rect, 1)
                if value == "A":
                    pygame.draw.rect(screen, (60, 240, 100), rect.inflate(-2, -2), border_radius=5)
                elif value == "a":
                    pygame.draw.rect(screen, (0, 145, 50), rect.inflate(-4, -4), border_radius=4)
                elif value == "B":
                    pygame.draw.rect(screen, (70, 175, 255), rect.inflate(-2, -2), border_radius=5)
                elif value == "b":
                    pygame.draw.rect(screen, (0, 90, 190), rect.inflate(-4, -4), border_radius=4)
                elif value == "*":
                    pygame.draw.circle(screen, (240, 70, 60), rect.center, max(4, cell // 3))
                elif value in "123456789":
                    pygame.draw.circle(screen, (245, 170, 50), rect.center, max(5, cell // 3))
                    txt = digit_font.render(value, True, (20, 20, 20))
                    screen.blit(txt, txt.get_rect(center=rect.center))

        y = engine.rows * cell
        pygame.draw.rect(screen, (14, 14, 16), (0, y, width, hud))
        screen.blit(font.render(f"A  {engine.bot_a_label}: {engine.score_a}", True, (60, 240, 100)), (10, y + 8))
        screen.blit(font.render(f"B  {engine.bot_b_label}: {engine.score_b}", True, (70, 175, 255)), (10, y + 31))
        mode = "v3 números" if engine.rules == "v3" else "actual (*)"
        info = (
            f"seed {engine.seed} | {engine.rows}x{engine.cols} | {mode} | "
            f"restantes {engine.remaining_moves} | turno {engine.current_turn}"
        )
        screen.blit(small.render(info, True, (220, 220, 220)), (10, y + 58))

        if engine.game_over:
            winner = "EMPATE" if engine.winner_side is None else f"GANA {engine.winner_side}"
            screen.blit(font.render(winner, True, (255, 215, 0)), (10, y + 82))
            controls1 = "R/ENTER reiniciar | N nueva seed | TAB cambiar A/B"
            controls2 = "ESC volver al menú"
        else:
            state = "PAUSA" if paused else "JUGANDO"
            controls1 = f"{state} | R reiniciar | ESPACIO pausa | ↑/↓ velocidad ({fps} FPS)"
            controls2 = "N nueva seed | TAB cambiar A/B | ESC volver al menú"
        screen.blit(small.render(controls1, True, (175, 210, 175)), (10, y + 108))
        screen.blit(small.render(controls2, True, (170, 170, 175)), (10, y + 126))

        # Botón exclusivo del visualizador. Por defecto no se guarda nada.
        if on_save_log is not None:
            button = log_button_rect()
            if save_log_done:
                fill = (32, 95, 48)
                border = (90, 220, 120)
                caption = "LOG GUARDADO"
            elif save_log_requested:
                fill = (92, 74, 28)
                border = (235, 190, 70)
                caption = "GUARDAR AL FINAL"
            else:
                fill = (46, 46, 52)
                border = (150, 150, 160)
                caption = "GUARDAR LOG"
            pygame.draw.rect(screen, fill, button, border_radius=6)
            pygame.draw.rect(screen, border, button, 2, border_radius=6)
            txt = small.render(caption, True, (240, 240, 240))
            screen.blit(txt, txt.get_rect(center=button.center))

        pygame.display.flip()

    try:
        start_match()
        while running:
            restart_requested = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if on_save_log is not None and log_button_rect().collidepoint(event.pos):
                        if not save_log_done:
                            save_log_requested = True
                            # Si la partida ya terminó, el click guarda inmediatamente.
                            # Si sigue en curso, queda armada y se guarda al finalizar.
                            save_visual_log_if_ready()
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        paused = not paused
                    elif event.key == pygame.K_UP:
                        fps = min(120, fps + 5)
                    elif event.key == pygame.K_DOWN:
                        fps = max(1, fps - 5)
                    elif event.key in (pygame.K_r, pygame.K_RETURN, pygame.K_KP_ENTER):
                        restart_requested = True
                    elif event.key == pygame.K_n:
                        current_seed += 1
                        restart_requested = True
                    elif event.key == pygame.K_TAB:
                        current_path_a, current_path_b = current_path_b, current_path_a
                        current_label_a, current_label_b = current_label_b, current_label_a
                        restart_requested = True

            if restart_requested and running:
                start_match()
                continue

            assert engine is not None and timing_a is not None and timing_b is not None
            if not paused and not engine.game_over:
                side = engine.current_turn
                module = mod_a if side == "A" else mod_b
                timing = timing_a if side == "A" else timing_b
                try:
                    move = timed_choose(module, engine.payload(side), timing)
                except Exception as exc:
                    engine.forfeit(side, f"Excepción {type(exc).__name__}: {exc}")
                else:
                    engine.step(move)

                if engine.game_over:
                    last_completed_result = engine.result(timing_a, timing_b)
                    save_visual_log_if_ready()

            draw()
            clock.tick(fps)
    finally:
        # Guardamos el estado final antes de descargar módulos.
        if engine is not None and timing_a is not None and timing_b is not None:
            current_result = engine.result(timing_a, timing_b)
        else:
            current_result = last_completed_result
        unload_current_modules()
        pygame.quit()

    # Si salimos en medio de una partida después de haber completado otra,
    # el resumen corresponde a la última partida terminada, no a la parcial.
    if last_completed_result is not None and (current_result is None or not current_result.draw and current_result.winner_side is None and not engine.game_over):
        return last_completed_result
    if current_result is not None:
        return current_result
    raise RuntimeError("La sesión visual terminó sin poder producir un resultado")


# ============================================================================
# Tournament / stats
# ============================================================================

def _pair_dimensions(seed: int, fixed: Optional[Tuple[int, int]]) -> Tuple[int, int]:
    if fixed is not None:
        return fixed
    rng = random.Random(seed ^ 0x5A17C0DE)
    return rng.randint(MIN_BOARD, MAX_BOARD), rng.randint(MIN_BOARD, MAX_BOARD)


def run_tournament(
    bot1: Path,
    bot2: Path,
    label1: str,
    label2: str,
    games: int,
    rules: str,
    fixed_size: Optional[Tuple[int, int]],
    base_seed: int,
) -> List[GameResult]:
    results: List[GameResult] = []
    games = max(1, int(games))
    pair_count = (games + 1) // 2
    game_no = 0

    print("\nJugando... (mismos seeds por pareja, lados A/B intercambiados)\n")
    for pair_idx in range(pair_count):
        seed = base_seed + pair_idx
        rows, cols = _pair_dimensions(seed, fixed_size)
        assignments = [
            (bot1, bot2, label1, label2),
            (bot2, bot1, label2, label1),
        ]
        for path_a, path_b, label_a, label_b in assignments:
            if game_no >= games:
                break
            game_no += 1
            start = time.perf_counter()
            result = run_game(path_a, path_b, label_a, label_b, rows, cols, seed, rules)
            elapsed = time.perf_counter() - start
            results.append(result)
            if result.draw:
                outcome = "EMPATE"
            else:
                outcome = f"gana {result.winner_label}"
            death = f" | muerte {result.death_side}" if result.death_side else ""
            print(
                f"[{game_no:>2}/{games}] seed {seed} {rows}x{cols} | "
                f"A:{result.score_a} B:{result.score_b} | {outcome}{death} | {elapsed:.1f}s"
            )
    return results


def _result_for_label(result: GameResult, label: str) -> Tuple[int, int, int, int, Dict[str, float], bool]:
    """score, correct, wrong, death(0/1), timing, is_A"""
    if result.bot_a_label == label:
        return result.score_a, result.correct_food_a, result.wrong_food_a, int(result.death_side == "A"), result.timing_a, True
    return result.score_b, result.correct_food_b, result.wrong_food_b, int(result.death_side == "B"), result.timing_b, False


def summarize(results: Sequence[GameResult], label1: str, label2: str) -> Dict[str, object]:
    same_bot = label1 == label2
    summary: Dict[str, object] = {
        "games": len(results),
        "draws": sum(r.draw for r in results),
        "side_A_wins": sum(r.winner_side == "A" for r in results),
        "side_B_wins": sum(r.winner_side == "B" for r in results),
    }

    if same_bot:
        summary["self_play"] = True
        summary["deaths_A"] = sum(r.death_side == "A" for r in results)
        summary["deaths_B"] = sum(r.death_side == "B" for r in results)
        return summary

    stats = {}
    for label in (label1, label2):
        wins = sum((not r.draw) and r.winner_label == label for r in results)
        points = wins + 0.5 * sum(r.draw for r in results)
        scores = []
        correct = wrong = deaths = 0
        timing_samples = []
        games_as_a = wins_as_a = games_as_b = wins_as_b = 0
        for r in results:
            score, c, w, d, timing, is_a = _result_for_label(r, label)
            scores.append(score)
            correct += c
            wrong += w
            deaths += d
            if timing.get("calls", 0):
                timing_samples.append(timing)
            if is_a:
                games_as_a += 1
                wins_as_a += int(r.winner_label == label)
            else:
                games_as_b += 1
                wins_as_b += int(r.winner_label == label)
        total_calls = sum(int(t["calls"]) for t in timing_samples)
        weighted_avg = (
            sum(float(t["avg_ms"]) * int(t["calls"]) for t in timing_samples) / total_calls
            if total_calls else 0.0
        )
        stats[label] = {
            "wins": wins,
            "point_rate": points / len(results) if results else 0.0,
            "avg_final_score": statistics.mean(scores) if scores else 0.0,
            "correct_food": correct,
            "wrong_food": wrong,
            "deaths": deaths,
            "games_as_A": games_as_a,
            "wins_as_A": wins_as_a,
            "games_as_B": games_as_b,
            "wins_as_B": wins_as_b,
            "avg_think_ms": weighted_avg,
            "over80_calls": sum(int(t.get("over80", 0)) for t in timing_samples),
            "think_calls": total_calls,
            "max_think_ms": max((float(t.get("max_ms", 0.0)) for t in timing_samples), default=0.0),
        }
    summary["bots"] = stats
    return summary


def print_summary(results: Sequence[GameResult], label1: str, label2: str) -> Dict[str, object]:
    summary = summarize(results, label1, label2)
    print("\n" + "=" * 72)
    print("RESULTADO FINAL")
    print("=" * 72)
    print(f"Partidas: {summary['games']} | Empates: {summary['draws']}")
    print(f"Victorias lado A: {summary['side_A_wins']} | lado B: {summary['side_B_wins']}")

    if summary.get("self_play"):
        print(f"Self-play de la misma versión: {label1}")
        print(f"Muertes A: {summary['deaths_A']} | Muertes B: {summary['deaths_B']}")
        print("En self-play mirá sobre todo A/B, muertes y estabilidad; no hay dos identidades distintas.")
        return summary

    bots = summary["bots"]
    for label in (label1, label2):
        s = bots[label]
        print(f"\n{label}")
        print(f"  Victorias: {s['wins']} | point rate: {s['point_rate']:.3f}")
        print(f"  Comidas correctas: {s['correct_food']} | incorrectas: {s['wrong_food']} | muertes: {s['deaths']}")
        print(f"  A: {s['wins_as_A']}/{s['games_as_A']} | B: {s['wins_as_B']}/{s['games_as_B']}")
        print(
            f"  Think: avg {s['avg_think_ms']:.1f} ms | max {s['max_think_ms']:.1f} ms | "
            f">80ms {s['over80_calls']}/{s['think_calls']}"
        )
    return summary


def save_summary(root: Path, results: Sequence[GameResult], summary: Dict[str, object], config: Dict[str, object]) -> Path:
    out_dir = root / "arena_results"
    out_dir.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"arena_{timestamp}.json"
    payload = {
        "config": config,
        "summary": summary,
        "games": [asdict(r) for r in results],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ============================================================================
# Menú interactivo
# ============================================================================

def ask_int(prompt: str, default: int, minimum: int = 1, maximum: Optional[int] = None) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Ingresá un número.")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            bound = f" entre {minimum} y {maximum}" if maximum is not None else f" >= {minimum}"
            print(f"Debe ser{bound}.")
            continue
        return value


def choose_bot(bots: Sequence[Path], root: Path, prompt: str) -> Path:
    while True:
        raw = input(prompt).strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Elegí el número de la lista.")
            continue
        if 1 <= idx <= len(bots):
            return bots[idx - 1]
        print("Número fuera de rango.")


def ask_rules() -> str:
    print("\nReglas:")
    print("  1. Actuales / legacy: 3 comidas '*' (default)")
    print("  2. v3: 5 comidas numeradas 1..9 en orden cíclico")
    raw = input("Elegí [1]: ").strip()
    return "v3" if raw == "2" else "legacy"


def ask_board_size() -> Optional[Tuple[int, int]]:
    print("\nTablero:")
    print("  1. Variable 12..20 por seed (default)")
    print("  2. Fijo")
    raw = input("Elegí [1]: ").strip()
    if raw != "2":
        return None
    rows = ask_int("Filas", 15, MIN_BOARD, MAX_BOARD)
    cols = ask_int("Columnas", 15, MIN_BOARD, MAX_BOARD)
    return rows, cols


def _run_interactive_session(root: Path, bots: Sequence[Path]) -> Dict[str, object]:
    print("\n" + "=" * 72)
    print("SNAKE ARENA INTERACTIVA")
    print("=" * 72)
    print(f"Proyecto: {root}")
    print("\nBots encontrados:")
    for i, path in enumerate(bots, 1):
        print(f"  {i:>2}. {display_name(path, root)}")

    bot1 = choose_bot(bots, root, "\nElegí BOT 1: ")
    bot2 = choose_bot(bots, root, "Elegí BOT 2: ")
    label1 = display_name(bot1, root)
    label2 = display_name(bot2, root)

    print("\nModo:")
    print("  1. Torneo rápido, varias partidas (default)")
    print("  2. Una partida visual con Pygame")
    mode = input("Elegí [1]: ").strip()

    rules = ask_rules()
    fixed_size = ask_board_size()
    base_seed = ask_int("Seed inicial", 950001, 0)

    visual_saved_paths: List[Path] = []

    if mode == "2":
        rows, cols = _pair_dimensions(base_seed, fixed_size)
        print(f"\nVisual: {label1} como A vs {label2} como B | {rows}x{cols}")

        def save_selected_visual_log(result: GameResult) -> None:
            # Solo se llama cuando el usuario pulsa el botón dentro del visor.
            # Se guarda una partida por archivo y no se altera el flujo de torneos.
            visual_config = {
                "bot1": result.bot_a_label,
                "bot2": result.bot_b_label,
                "rules": result.rules,
                "fixed_size": [result.rows, result.cols],
                "base_seed": result.seed,
                "visual": True,
                "saved_by_visual_button": True,
            }
            visual_summary = summarize([result], result.bot_a_label, result.bot_b_label)
            out_dir = root / "arena_results"
            out_dir.mkdir(exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            millis = int((time.time() % 1) * 1000)
            out = out_dir / f"arena_visual_{timestamp}_{millis:03d}_seed{result.seed}.json"
            payload = {
                "config": visual_config,
                "summary": visual_summary,
                "games": [asdict(result)],
            }
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            visual_saved_paths.append(out)
            print(f"\n[VISUAL] Log guardado en: {out.relative_to(root)}")

        result = run_game(
            bot1, bot2, label1, label2, rows, cols, base_seed, rules,
            visual=True, visual_log_callback=save_selected_visual_log,
        )
        results = [result]
    else:
        games = ask_int("Cantidad de partidas", 10, 1, 1000)
        if games % 2:
            print("Aviso: con cantidad impar un bot tendrá una partida extra como A. Para comparar, conviene usar un número par.")
        results = run_tournament(bot1, bot2, label1, label2, games, rules, fixed_size, base_seed)

    summary = print_summary(results, label1, label2)
    config = {
        "bot1": label1,
        "bot2": label2,
        "rules": rules,
        "fixed_size": list(fixed_size) if fixed_size else None,
        "base_seed": base_seed,
        "visual": mode == "2",
    }
    if mode == "2":
        if visual_saved_paths:
            print(f"\nLogs visuales guardados por botón: {len(visual_saved_paths)}")
        else:
            print("\nVisual finalizado sin guardar log (no se pulsó 'Guardar log').")
    else:
        out = save_summary(root, results, summary, config)
        print(f"\nResumen guardado en: {out.relative_to(root)}")
    return config


def main() -> None:
    root = Path(__file__).resolve().parent
    while True:
        bots = discover_bots(root)
        if not bots:
            print("No encontré ningún .py con def choose_direction(...) debajo de esta carpeta.")
            print(f"Carpeta buscada: {root}")
            raise SystemExit(1)

        _run_interactive_session(root, bots)

        print("\n¿Qué querés hacer ahora?")
        print("  1. Volver al menú y elegir otra partida (default)")
        print("  2. Salir")
        choice = input("Elegí [1]: ").strip()
        if choice == "2":
            print("Arena cerrada.")
            return


if __name__ == "__main__":
    main()
