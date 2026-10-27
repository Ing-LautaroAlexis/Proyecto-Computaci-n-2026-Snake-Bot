"""Visor en vivo (pygame), separado del motor de decisión.

Muestra cada manzana con su número (o cuántos puntos vale), las X, las bombas
con su zona, el muro, la cola soltada, la estrella, los multiplicadores y
avisa cuando el rival está esperando al lado de un número que viene.

Teclas:
    M        cambia lo que se ve en cada manzana: número / mis puntos / sus puntos
    Z        muestra u oculta la zona de las bombas
    <- ->    volver atrás / adelante en la partida (pausa la vista)
    ESPACIO  volver al vivo
Si guardás cambios en este archivo mientras el visor está abierto, se recarga
solo (si el cambio tiene un error, sigue la versión anterior y lo avisa arriba).
"""
from __future__ import annotations

import importlib
import os
import sys

# ------------------------------------------------------------- ajustes
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
GLOBAL_HUD_HEIGHT = 50
FPS = 30
SIDE_PANEL_MIN = 900  # ancho mínimo del panel para mostrar la tabla de manzanas
CAMP_DIST = 3         # a cuántas casillas cuenta como "esperando"

BG = (12, 12, 14)
CELL_BG = (26, 27, 30)
GRID_LINE = (40, 41, 46)
TEXT = (225, 228, 232)
MUTED = (140, 145, 155)
MY_HEAD, MY_BODY = (50, 230, 110), (20, 130, 60)
EN_HEAD, EN_BODY = (70, 170, 255), (25, 80, 170)
WALL = (95, 95, 105)
X_COLOR = (255, 205, 40)
BOMB_ZONE = (70, 30, 30)
BOMB = (230, 70, 50)
STAR = (255, 230, 90)
SHOT_FOOD = (255, 120, 80)
DIGIT_COLORS = (
    (90, 200, 120), (60, 190, 175), (70, 160, 230), (110, 130, 240), (160, 110, 235),
    (225, 100, 200), (240, 100, 80), (245, 150, 40), (250, 210, 40),
)

BIG_BOMB, SMALL_BOMB = "\U0001f4a3", "\U0001f9e8"
TAIL_A, TAIL_B, STAR_CH = "Ⓐ", "Ⓑ", "⭐"
MODES = ("numero", "mis puntos", "sus puntos")
VIEW = {"mode": 0, "zones": True, "back": 0, "error": ""}


# ------------------------------------------------------------- reglas
def is_digit(cell):
    return len(cell) == 1 and "1" <= cell <= "9"


def target_digit(board):
    """El número que toca: el que no tiene a su anterior en el tablero."""
    present = {int(c) for row in board for c in row if is_digit(c)}
    for d in sorted(present):
        if (d + 7) % 9 + 1 not in present:
            return d
    return min(present) if present else None


def find_head(board, side, invincible):
    letter = side.lower() if invincible else side.upper()
    for r, row in enumerate(board):
        if letter in row:
            return r, row.index(letter)
    return None


def cells_of(board, ch):
    return [(r, c) for r, row in enumerate(board) for c, v in enumerate(row) if v == ch]


def min_dist(head, cells):
    if not head or not cells:
        return None
    return min(abs(head[0] - r) + abs(head[1] - c) for r, c in cells)


def bomb_zone(board):
    zone = set()
    for r, row in enumerate(board):
        for c, cell in enumerate(row):
            radius = {BIG_BOMB: 2, SMALL_BOMB: 1}.get(cell, 0)
            zone.update((r + dr, c + dc) for dr in range(-radius, radius + 1)
                        for dc in range(-radius, radius + 1) if radius)
    return zone


def short_points(value):
    if value < 1000:
        return str(value)
    text = f"{value / 1000:.1f}".replace(".0", "")
    return text.replace(".", ",") + "k"


def other_side(side):
    return "B" if str(side).upper() in {"A", "1"} else "A"


# ------------------------------------------------------------- análisis
def game_view(game):
    """Junta todo lo que hace falta para dibujar un cuadro (vivo o pasado)."""
    history = game.get("history") or []
    back = min(VIEW["back"], max(0, len(history) - 1))
    frame = dict(game)
    if history:
        frame.update(history[-1 - back])
    board = frame.get("board") or frame.get("grid") or []
    me = "A" if str(game.get("my_side", "A")).upper() in {"A", "1"} else "B"
    frame.update(
        board=board, me=me,
        my_head=find_head(board, me, frame.get("my_inv", 0)),
        enemy_head=find_head(board, other_side(me), frame.get("enemy_inv", 0)),
        target=target_digit(board), back=back, frames=len(history),
    )
    return frame


def apple_rows(view):
    """Una fila por número: (número, copias, vale para mí, vale para él, dist mía, dist suya)."""
    board, target = view["board"], view["target"]
    digits = sorted({int(c) for row in board for c in row if is_digit(c)},
                    key=lambda d: (d - (target or 1)) % 9)
    rows = []
    for d in digits:
        cells = cells_of(board, str(d))
        rows.append((d, len(cells), d * 100 * view.get("my_mult", 1),
                     d * 100 * view.get("enemy_mult", 1),
                     min_dist(view["my_head"], cells), min_dist(view["enemy_head"], cells)))
    return rows


def enemy_camping(view):
    """Número futuro al lado del cual espera el rival (o None)."""
    rows = apple_rows(view)
    if not rows or rows[0][5] is None or rows[0][5] <= CAMP_DIST:
        return None
    for digit, _, _, _, _, dist in rows[1:]:
        if dist is not None and dist <= CAMP_DIST:
            return digit
    return None


# ------------------------------------------------------------- dibujo
def _cell_style(cell, view):
    my_body, en_body = view["me"].lower(), other_side(view["me"]).lower()
    if view.get("my_inv"):
        my_body = view["me"]
    if view.get("enemy_inv"):
        en_body = other_side(view["me"])
    styles = {my_body: MY_BODY, en_body: EN_BODY, "#": WALL}
    return styles.get(cell)


def _draw_digit(pygame, screen, fonts, cell, rect, view):
    d = int(cell)
    color = DIGIT_COLORS[d - 1]
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    filled = d == view["target"]
    mode = MODES[VIEW["mode"]]
    if mode == "numero":
        pygame.draw.circle(screen, color, center, max(3, rect[2] // 2 - 1), 0 if filled else 2)
        _blit_center(screen, fonts[1].render(cell, True, BG if filled else color), center)
        return
    mult = view.get("my_mult", 1) if mode == "mis puntos" else view.get("enemy_mult", 1)
    label = fonts[2].render(short_points(d * 100 * mult), True, BG)
    w, h = label.get_size() if hasattr(label, "get_size") else (rect[2], rect[3])
    box = (center[0] - w // 2 - 2, center[1] - h // 2 - 1, w + 4, h + 2)
    pygame.draw.rect(screen, color, box, border_radius=3)
    if filled:
        pygame.draw.rect(screen, TEXT, box, 2, border_radius=3)
    _blit_center(screen, label, center)


def _blit_center(screen, surface, center):
    if hasattr(surface, "get_size"):
        w, h = surface.get_size()
        screen.blit(surface, (center[0] - w // 2, center[1] - h // 2))
    else:
        screen.blit(surface, center)


def _draw_symbol(pygame, screen, fonts, cell, rect, view):
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    half = max(2, rect[2] // 2 - 1)
    if is_digit(cell):
        _draw_digit(pygame, screen, fonts, cell, rect, view)
    elif cell in (BIG_BOMB, SMALL_BOMB):
        pygame.draw.circle(screen, BOMB, center, half if cell == BIG_BOMB else half * 2 // 3)
    else:
        labels = {"X": ("X", X_COLOR), STAR_CH: ("*", STAR), "*": ("*", SHOT_FOOD),
                  TAIL_A: ("a", MY_HEAD if view["me"] == "A" else EN_HEAD),
                  TAIL_B: ("b", MY_HEAD if view["me"] == "B" else EN_HEAD)}
        if cell in labels:
            text, color = labels[cell]
            _blit_center(screen, fonts[1].render(text, True, color), center)


def _draw_head(pygame, screen, fonts, rect, color, direction):
    pygame.draw.rect(screen, color, rect)
    if not direction:
        return
    arrows = {"up": "^", "down": "v", "left": "<", "right": ">"}
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    _blit_center(screen, fonts[1].render(arrows.get(str(direction).lower(), ""), True, BG), center)


def _paint_cells(pygame, screen, view, cell, origin):
    """Primera pasada: fondo de cada casilla. Devuelve el rectángulo de cada una."""
    zone = bomb_zone(view["board"]) if VIEW["zones"] else set()
    rects = {}
    for r, row in enumerate(view["board"]):
        for c, value in enumerate(row):
            rect = rects[r, c] = (origin[0] + c * cell, origin[1] + r * cell, cell, cell)
            base = BOMB_ZONE if (r, c) in zone and value == " " else CELL_BG
            pygame.draw.rect(screen, _cell_style(value, view) or base, rect)
            if cell >= 12:
                pygame.draw.rect(screen, GRID_LINE, rect, 1)
    return rects


def _paint_symbols(pygame, screen, fonts, view, rects):
    """Segunda pasada: cabezas y símbolos (el texto puede pasarse de su casilla)."""
    for pos, rect in rects.items():
        if pos == view["my_head"]:
            _draw_head(pygame, screen, fonts, rect, MY_HEAD, view.get("direction"))
        elif pos == view["enemy_head"]:
            _draw_head(pygame, screen, fonts, rect, EN_HEAD, None)
        else:
            _draw_symbol(pygame, screen, fonts, view["board"][pos[0]][pos[1]], rect, view)


def _draw_board(pygame, screen, fonts, view, area):
    if not view["board"] or not view["board"][0]:
        return
    cell, ox, oy = _board_geometry(view["board"], area)
    rects = _paint_cells(pygame, screen, view, cell, (ox, oy))
    _paint_symbols(pygame, screen, fonts, view, rects)


def _board_geometry(grid, rect):
    x, y, w, h = rect
    rows, cols = len(grid), len(grid[0])
    cell = max(4, min((w - 16) // cols, (h - 8) // rows))
    return cell, x + (w - cols * cell) // 2, y + (h - rows * cell) // 2


def _player_line(name, score, mult, inv):
    extra = f"  INVENCIBLE {inv}" if inv else ""
    return f"{name}: {score:,} pts  x{mult}{extra}".replace(",", ".")


def _border_color(game):
    if not game["game_over"]:
        return (60, 60, 70)
    won = game.get("winner") and game["my_name"] in game["winner"]
    return (255, 215, 0) if won else (160, 50, 50)


def _draw_panel_header(pygame, screen, view, rect, fonts):
    x, y, w, _ = rect
    pygame.draw.rect(screen, (22, 22, 24), rect, border_radius=8)
    pygame.draw.rect(screen, _border_color(view), rect, 2, border_radius=8)
    lines = (
        (_player_line(view["my_name"], view.get("my_score", 0), view.get("my_mult", 1), view.get("my_inv", 0)), MY_HEAD),
        (_player_line(view["enemy_name"], view.get("enemy_score", 0), view.get("enemy_mult", 1), view.get("enemy_inv", 0)), EN_HEAD),
    )
    for i, (text, color) in enumerate(lines):
        screen.blit(fonts[0].render(text, True, color), (x + 8, y + 6 + i * 18))
    move = 400 - view.get("remaining_moves", 400)
    state = "VIVO" if not view.get("back") else f"PASADO (-{view['back']})"
    screen.blit(fonts[1].render(f"movida {move}/400  {state}", True, TEXT), (x + w - 260, y + 6))
    if view.get("game_over") and view.get("winner"):
        screen.blit(fonts[1].render(f"Gana: {view['winner']}", True, (255, 215, 0)), (x + w - 260, y + 24))


def _draw_apple_table(pygame, screen, fonts, view, area):
    x, y = area[0], area[1]
    screen.blit(fonts[1].render("Nro  vale yo  vale el  dist yo  dist el", True, MUTED), (x, y))
    for i, (d, copies, mine, his, d_me, d_him) in enumerate(apple_rows(view)):
        mark = ">" if d == view["target"] else " "
        text = f"{mark}{d} x{copies} {mine:>7} {his:>7}  {d_me if d_me is not None else '-':>5}  {d_him if d_him is not None else '-':>5}"
        screen.blit(fonts[1].render(text, True, DIGIT_COLORS[d - 1]), (x, y + 20 + i * 18))
    camp = enemy_camping(view)
    if camp:
        warn = f"OJO: el rival espera al lado del {camp}"
        screen.blit(fonts[1].render(warn, True, BOMB), (x, y + 30 + 18 * 6))


def _draw_panel(pygame, screen, game, rect, fonts, food_digits=None):
    view = game_view(game)
    _draw_panel_header(pygame, screen, view, rect, fonts)
    x, y, w, h = rect
    table_w = 330 if w >= SIDE_PANEL_MIN else 0
    _draw_board(pygame, screen, fonts, view, (x, y + 48, w - table_w, h - 52))
    if table_w and view["board"]:
        _draw_apple_table(pygame, screen, fonts, view, (x + w - table_w + 8, y + 60))


def _snapshot(state, lock):
    with lock:
        return state["status"], list(state["games"].values())


def _draw_hud(pygame, screen, font, status, count):
    pygame.draw.rect(screen, (15, 15, 18), (0, 0, WINDOW_WIDTH, GLOBAL_HUD_HEIGHT))
    pygame.draw.line(screen, (60, 60, 70), (0, GLOBAL_HUD_HEIGHT), (WINDOW_WIDTH, GLOBAL_HUD_HEIGHT), 2)
    screen.blit(font.render("Snake - visor en vivo", True, TEXT), (16, 6))
    keys = f"[M] manzanas: {MODES[VIEW['mode']]}  [Z] bombas  [<- ->] atras/adelante  [ESPACIO] vivo"
    screen.blit(font.render(keys, True, MUTED), (16, 27))
    msg = VIEW["error"] or f"{status} | partidas: {count}"
    color = BOMB if VIEW["error"] else (160, 220, 255)
    screen.blit(font.render(msg, True, color), (WINDOW_WIDTH - 520, 6))


def _grid_layout(count):
    from bisect import bisect_left
    layouts = ((1, 1), (1, 2), (2, 2), (2, 3), (2, 4), (3, 4))
    return layouts[bisect_left((1, 2, 4, 6, 8), count)]


def _panel_rect(index, rows, cols):
    margin = 12
    top = GLOBAL_HUD_HEIGHT + margin
    width = (WINDOW_WIDTH - margin * (cols + 1)) // cols
    height = (WINDOW_HEIGHT - top - margin * rows) // rows
    r_idx, c_idx = divmod(index, cols)
    return margin + c_idx * (width + margin), top + r_idx * (height + margin), width, height


def _draw_games(pygame, screen, games, fonts, food_digits=None):
    if not games:
        text = fonts[0].render("Esperando partidas del servidor...", True, MUTED)
        screen.blit(text, (WINDOW_WIDTH // 2 - 200, WINDOW_HEIGHT // 2))
        return
    rows, cols = _grid_layout(len(games))
    for index, game in enumerate(games[: rows * cols]):
        _draw_panel(pygame, screen, game, _panel_rect(index, rows, cols), fonts[1:])


# ------------------------------------------------------------- teclado
def handle_key(name):
    """Aplica una tecla (nombre de pygame.key.name). Devuelve True si la usó."""
    actions = {
        "m": lambda: VIEW.update(mode=(VIEW["mode"] + 1) % len(MODES)),
        "z": lambda: VIEW.update(zones=not VIEW["zones"]),
        "left": lambda: VIEW.update(back=VIEW["back"] + 1),
        "right": lambda: VIEW.update(back=max(0, VIEW["back"] - 1)),
        "space": lambda: VIEW.update(back=0),
    }
    action = actions.get(name)
    if action:
        action()
    return action is not None


def _process_events(pygame):
    """Procesa teclas. Devuelve True si hay que cerrar."""
    quit_now = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            quit_now = True
        elif event.type == getattr(pygame, "KEYDOWN", None):
            handle_key(pygame.key.name(event.key))
    return quit_now


def _should_quit(pygame):
    return any(event.type == pygame.QUIT for event in pygame.event.get())


# ------------------------------------------------------------- recarga en vivo
def _reload_if_changed(module, last_mtime):
    """Si se guardó este archivo, lo vuelve a cargar. Devuelve (módulo, mtime)."""
    try:
        mtime = os.path.getmtime(module.__file__)
    except OSError:
        return module, last_mtime
    if mtime == last_mtime:
        return module, last_mtime
    try:
        saved = dict(VIEW)
        module = importlib.reload(module)
        module.VIEW.update(saved, error="")
    except Exception as exc:  # el visor nunca se cae por un error al editar
        VIEW["error"] = f"Error en el visor: {exc}"[:70]
    return module, mtime


def _build_ui(pygame):
    pygame.init()
    pygame.font.init()
    fonts = (
        pygame.font.SysFont("consolas", 16, bold=True),
        pygame.font.SysFont("consolas", 14, bold=True),
        pygame.font.SysFont("consolas", 13, bold=True),
        pygame.font.SysFont("consolas", 10, bold=True),
    )
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Code Challenge - visor en vivo")
    return screen, fonts, pygame.time.Clock()


def draw_frame(pygame, screen, fonts, visual_state, visual_lock):
    screen.fill(BG)
    status, games = _snapshot(visual_state, visual_lock)
    _draw_hud(pygame, screen, fonts[0], status, len(games))
    _draw_games(pygame, screen, games, fonts)
    pygame.display.flip()


def run_visualizer(visual_state, visual_lock, food_digits=None):
    import pygame
    screen, fonts, clock = _build_ui(pygame)
    module = sys.modules[__name__]
    mtime = os.path.getmtime(module.__file__)
    while not module._process_events(pygame):
        module, mtime = _reload_if_changed(module, mtime)
        module.draw_frame(pygame, screen, fonts, visual_state, visual_lock)
        clock.tick(FPS)
    pygame.quit()
