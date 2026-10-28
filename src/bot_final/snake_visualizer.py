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


def digits_on(board):
    return {int(c) for row in board for c in row if is_digit(c)}


def target_digit(board):
    """El número que toca: el que no tiene a su anterior en el tablero."""
    present = digits_on(board)
    firsts = [d for d in sorted(present) if (d + 7) % 9 + 1 not in present]
    return firsts[0] if firsts else min(present, default=None)


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


BOMB_RADIUS = {BIG_BOMB: 2, SMALL_BOMB: 1}


def _square(r, c, radius):
    span = range(-radius, radius + 1)
    return {(r + dr, c + dc) for dr in span for dc in span}


def bomb_zone(board):
    zone = set()
    for r, row in enumerate(board):
        for c, cell in enumerate(row):
            if cell in BOMB_RADIUS:
                zone |= _square(r, c, BOMB_RADIUS[cell])
    return zone


def short_points(value):
    if value < 1000:
        return str(value)
    text = f"{value / 1000:.1f}".replace(".0", "")
    return text.replace(".", ",") + "k"


def other_side(side):
    return "B" if str(side).upper() in {"A", "1"} else "A"


# ------------------------------------------------------------- análisis
def _side_letter(side):
    return "A" if str(side).upper() in {"A", "1"} else "B"


def _history_frame(game):
    """(cuadro a mostrar, cuántos cuadros hacia atrás, total de cuadros)."""
    history = game.get("history") or []
    back = min(VIEW["back"], max(0, len(history) - 1))
    frame = dict(game)
    if history:
        frame.update(history[-1 - back])
    return frame, back, len(history)


def game_view(game):
    """Junta todo lo que hace falta para dibujar un cuadro (vivo o pasado)."""
    frame, back, frames = _history_frame(game)
    board = frame.get("board") or frame.get("grid") or []
    me = _side_letter(game.get("my_side", "A"))
    frame.update(
        board=board, me=me,
        my_head=find_head(board, me, frame.get("my_inv", 0)),
        enemy_head=find_head(board, other_side(me), frame.get("enemy_inv", 0)),
        target=target_digit(board), back=back, frames=frames,
    )
    return frame


def _apple_row(view, d):
    cells = cells_of(view["board"], str(d))
    return (d, len(cells), d * 100 * view.get("my_mult", 1),
            d * 100 * view.get("enemy_mult", 1),
            min_dist(view["my_head"], cells), min_dist(view["enemy_head"], cells))


def apple_rows(view):
    """Una fila por número: (número, copias, vale para mí, vale para él, dist mía, dist suya)."""
    start = view["target"] or 1
    digits = sorted(digits_on(view["board"]), key=lambda d: (d - start) % 9)
    return [_apple_row(view, d) for d in digits]


def _is_near(dist):
    return dist is not None and dist <= CAMP_DIST


def _is_far(dist):
    return dist is not None and dist > CAMP_DIST


def enemy_camping(view):
    """Número futuro al lado del cual espera el rival (o None)."""
    rows = apple_rows(view)
    if not rows or not _is_far(rows[0][5]):
        return None
    return next((row[0] for row in rows[1:] if _is_near(row[5])), None)


# ------------------------------------------------------------- dibujo
def _cell_style(cell, view):
    my_body, en_body = view["me"].lower(), other_side(view["me"]).lower()
    if view.get("my_inv"):
        my_body = view["me"]
    if view.get("enemy_inv"):
        en_body = other_side(view["me"])
    styles = {my_body: MY_BODY, en_body: EN_BODY, "#": WALL}
    return styles.get(cell)


def _rect_center(rect):
    return rect[0] + rect[2] // 2, rect[1] + rect[3] // 2


def _draw_digit_number(pygame, screen, fonts, cell, rect, filled):
    color = DIGIT_COLORS[int(cell) - 1]
    center = _rect_center(rect)
    pygame.draw.circle(screen, color, center, max(3, rect[2] // 2 - 1), 0 if filled else 2)
    _blit_center(screen, fonts[1].render(cell, True, BG if filled else color), center)


def _label_size(label, rect):
    return label.get_size() if hasattr(label, "get_size") else (rect[2], rect[3])


def _draw_digit_points(pygame, screen, fonts, cell, rect, view, filled):
    d = int(cell)
    key = "my_mult" if MODES[VIEW["mode"]] == "mis puntos" else "enemy_mult"
    label = fonts[2].render(short_points(d * 100 * view.get(key, 1)), True, BG)
    w, h = _label_size(label, rect)
    center = _rect_center(rect)
    box = (center[0] - w // 2 - 2, center[1] - h // 2 - 1, w + 4, h + 2)
    pygame.draw.rect(screen, DIGIT_COLORS[d - 1], box, border_radius=3)
    if filled:
        pygame.draw.rect(screen, TEXT, box, 2, border_radius=3)
    _blit_center(screen, label, center)


def _draw_digit(pygame, screen, fonts, cell, rect, view):
    filled = int(cell) == view["target"]
    if MODES[VIEW["mode"]] == "numero":
        _draw_digit_number(pygame, screen, fonts, cell, rect, filled)
    else:
        _draw_digit_points(pygame, screen, fonts, cell, rect, view, filled)


def _blit_center(screen, surface, center):
    if hasattr(surface, "get_size"):
        w, h = surface.get_size()
        screen.blit(surface, (center[0] - w // 2, center[1] - h // 2))
    else:
        screen.blit(surface, center)


def _draw_bomb(pygame, screen, cell, rect):
    half = max(2, rect[2] // 2 - 1)
    pygame.draw.circle(screen, BOMB, _rect_center(rect), half if cell == BIG_BOMB else half * 2 // 3)


def _symbol_labels(view):
    def tail_color(letter):
        return MY_HEAD if view["me"] == letter else EN_HEAD
    return {"X": ("X", X_COLOR), STAR_CH: ("*", STAR), "*": ("*", SHOT_FOOD),
            TAIL_A: ("a", tail_color("A")), TAIL_B: ("b", tail_color("B"))}


def _draw_label(pygame, screen, fonts, cell, rect, view):
    label = _symbol_labels(view).get(cell)
    if label:
        text, color = label
        _blit_center(screen, fonts[1].render(text, True, color), _rect_center(rect))


def _draw_symbol(pygame, screen, fonts, cell, rect, view):
    if is_digit(cell):
        _draw_digit(pygame, screen, fonts, cell, rect, view)
    elif cell in BOMB_RADIUS:
        _draw_bomb(pygame, screen, cell, rect)
    else:
        _draw_label(pygame, screen, fonts, cell, rect, view)


def _draw_head(pygame, screen, fonts, rect, color, direction):
    pygame.draw.rect(screen, color, rect)
    if not direction:
        return
    arrows = {"up": "^", "down": "v", "left": "<", "right": ">"}
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    _blit_center(screen, fonts[1].render(arrows.get(str(direction).lower(), ""), True, BG), center)


def _cell_background(pos, value, zone, view):
    base = BOMB_ZONE if pos in zone and value == " " else CELL_BG
    return _cell_style(value, view) or base


def _paint_cell(pygame, screen, rect, color, cell):
    pygame.draw.rect(screen, color, rect)
    if cell >= 12:
        pygame.draw.rect(screen, GRID_LINE, rect, 1)


def _paint_cells(pygame, screen, view, cell, origin):
    """Primera pasada: fondo de cada casilla. Devuelve el rectángulo de cada una."""
    zone = bomb_zone(view["board"]) if VIEW["zones"] else set()
    rects = {}
    for r, row in enumerate(view["board"]):
        for c, value in enumerate(row):
            rect = rects[r, c] = (origin[0] + c * cell, origin[1] + r * cell, cell, cell)
            _paint_cell(pygame, screen, rect, _cell_background((r, c), value, zone, view), cell)
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


def _dash_if_none(value):
    return "-" if value is None else value


def _apple_table_line(row, target):
    d, copies, mine, his, d_me, d_him = row
    mark = ">" if d == target else " "
    return f"{mark}{d} x{copies} {mine:>7} {his:>7}  {_dash_if_none(d_me):>5}  {_dash_if_none(d_him):>5}"


def _draw_apple_table(pygame, screen, fonts, view, area):
    x, y = area[0], area[1]
    screen.blit(fonts[1].render("Nro  vale yo  vale el  dist yo  dist el", True, MUTED), (x, y))
    for i, row in enumerate(apple_rows(view)):
        text = _apple_table_line(row, view["target"])
        screen.blit(fonts[1].render(text, True, DIGIT_COLORS[row[0] - 1]), (x, y + 20 + i * 18))
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
