# SNAKE 3.9.2 (Incremento 3, reglas v9, versión 2)
# Cambios contra 3.9.1 (probados en un simulador con las reglas hasta la v9):
#   1. Carrera por el número que toca: la evaluación resta los puntos que el rival
#      se va a llevar si llega primero. Así el bot no se come un número cuando eso le
#      deja al rival el siguiente (que vale más), que es lo que hacían Alejo y Santino.
#   2. La X vale más: antes un paso de multiplicador valía como mucho 1.200 puntos;
#      ahora hasta 6.000 al principio de la partida (baja a medida que se acaba).
#   Nada de la v10 (estrella, 28/10) es nuevo: queda lo que ya traía la 3.9.1.
# Base: 2.6.1 (antes "V8.1" / v6actualizado) + adaptación a las reglas v7, v8, v9 y v10:
#   v7: Ⓐ/Ⓑ (comida de cola) dejan de ser pared: se pueden pisar.
#   v8: las casillas al alcance de una bomba (💣 a 2 o menos, 🧨 a 1 o menos,
#       diagonales incluidas) se tratan como muro: pisarlas te deja en 0.
#   v9: las * de los disparos no hacen que el bot se olvide de los dígitos.
#   v10: con invencibilidad la cabeza viene en minúscula; se normaliza. ⭐ se puede pisar.
#
# Historia anterior (2.6.1 = V8.0 + reglas v4 (X multiplicador), v5 (# muro) y v6 (copias de dígitos))
# Based on V7.5 methodology fixes. V3 rules added without removing tactical safety layers.
#
# Cambios V8.1 (todos son no-op en tableros v1-v3, sin X / # / copias):
#   v4: la celda X ya no se trata como obstáculo; se puede comer (+50) y el
#       multiplicador (multiplier_1/2) se lee del turno y se simula en la búsqueda.
#   v5: el muro # sigue siendo "no transitable", pero si no queda ningún otro
#       movimiento se prefiere chocar el # (-500, seguimos vivos) antes que morir.
#   v6: el objetivo ahora son TODAS las copias del dígito correcto (antes solo una,
#       y las demás copias se trataban como dígito equivocado). Al comer una copia
#       el simulador borra las otras, y la carrera por comida usa la copia más cercana.
#   Evaluación: el "bolsillo" (encierro) ya no borra el puntaje (con multiplicadores
#       encerrarse llegaba a parecer mejor que un estado normal), y las X cercanas
#       que ganamos en carrera suman valor aunque estén fuera del horizonte de búsqueda.
import sys
import time
from collections import deque

# =====================================================================
# 1. CONFIGURACIÓN GENERAL Y CONSTANTES
# =====================================================================
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
GLOBAL_HUD_HEIGHT = 50
FPS = 30

DEADLINE_TIMEOUT = 0.080  # límite externo nominal del servidor
DEADLINE_MARGIN_SECONDS = 0.020  # B980 calibrado: menor margen con p99 externo <=80 ms en V7.5 R3
INF = 10**9
TERMINAL_WIN_SCORE = 900_000_000  # muerte decide la partida; domina cualquier heurística

# Future Escape v1: capa aislada de seguridad futura.
USE_FUTURE_ESCAPE_DEFAULT = True
FE_HORIZON = 2              # rival responde + nuestra siguiente jugada
FE_TIME_BUDGET = 0.008# máximo ~8 ms dentro del mismo deadline total de 80 ms
FE_NODE_BUDGET = 450# límite duro de estados FE por decisión
FE_FATAL_RISK = 450000
FE_POCKET_RISK = 180000
FE_TIGHT_RISK = 90000
FE_SINGLE_EXIT_RISK = 20000

# Food Race v1: refuerza la carrera por comida sin agregar BFS nuevos.
# Reutiliza las distancias topológicas ya calculadas por el evaluador.
FOOD_RACE_MAX_DISTANCE = 12
FOOD_RACE_BASE = 1400
FOOD_RACE_DISTANCE_WEIGHT = 150
FOOD_RACE_MARGIN_WEIGHT = 320
FOOD_RACE_NEAR_BONUS = 900
FOOD_RACE_SOLO_REACHABLE_BONUS = 700
FOOD_RACE_SECONDARY_WEIGHT = 0.35
FOOD_RACE_CAP = 7500

# Anti-Cycle v1: rompe loops cortos persistentes sin añadir BFS.
# Solo actúa en la raíz y únicamente después de varios turnos sin crecimiento.
USE_ANTI_CYCLE_DEFAULT = True

# =====================================================================
# V6: GAME STRATEGY CONTROLLER + APPLE FREEZE / BANKING V1
# =====================================================================
# Legacy: movimiento +1 y manzana +100 (=+99 neto). V3: el target correcto
# vale digit*100; compute_strategy_state recibe el reward actual para ajustar urgencia.
STRATEGY_ACTIVE_REMAINING = 120
STRATEGY_LOCK_REMAINING = 70
STRATEGY_DESPERATE_NET_APPLES = 3

# Apple Freeze: solo aparece en LOCK tardío y nunca en la ventana final de cobro.
# La manzana debe ser claramente nuestra y debe existir una alternativa raíz segura.
USE_APPLE_FREEZE_DEFAULT = True
APPLE_FREEZE_MAX_REMAINING = 70
APPLE_BANK_CASHOUT_REMAINING = 8
APPLE_FREEZE_MIN_ENEMY_DISTANCE = 5
APPLE_FREEZE_BASE_PENALTY = 320000
APPLE_FREEZE_EXTRA_BANKED = 30000
APPLE_FREEZE_CAP = 440000

# Endgame Bank: defer a target food that is effectively "ours" when eating it
# now would respawn a new target for the rival. This extends the old LOCK-only
# freeze to tied / one-food-behind late games.
ENDGAME_BANK_MAX_REMAINING = 60
ENDGAME_BANK_CASHOUT_REMAINING = 8
ENDGAME_BANK_MAX_MY_DISTANCE = 2
ENDGAME_BANK_MIN_ENEMY_MARGIN = 6
ENDGAME_BANK_MAX_REQUIRED_NET = 2
ENDGAME_BANK_BASE_PENALTY = 420000
ENDGAME_BANK_CAP_PER_REWARD_SCALE = 500000

# Cuando vamos perdiendo, comer también genera un nuevo spawn real que el
# simulador determinista no puede representar. Un bonus pequeño compensa esa
# oportunidad de recambio sin competir con seguridad/muerte.
TRAILING_EAT_BONUS = 12000
DESPERATE_EAT_BONUS = 28000

# Adaptive Territory v1: deliberately bounded so it cannot overpower food/score.
TERRITORY_EARLY_REMAINING = 210
TERRITORY_LATE_REMAINING = 80
TERRITORY_BASE_EARLY = 0
TERRITORY_BASE_MID = 5
TERRITORY_BASE_LATE = 9
TERRITORY_WIN_BONUS = 4
TERRITORY_LOSE_REDUCTION = 5
TERRITORY_FOOD_SUPPRESS = 0.25
TERRITORY_CAP = 3500
TERRITORY_MIN_COMBINED_LENGTH = 14
# V6 baseline: Adaptive Territory queda desactivado hasta demostrar mejora empírica.
USE_ADAPTIVE_TERRITORY_V6 = False

# Root Safety Gate v1: si una serpiente larga tiene una alternativa FE=0,
# los candidatos con riesgo geométrico explícito pagan bastante más.
# No prohíbe riesgo cuando TODAS las opciones son riesgosas.
FE_SAFETY_GATE_MIN_LENGTH = 10
FE_SAFETY_GATE_SCALE_LONG = 4
FE_SAFETY_GATE_SCALE_VERY_LONG = 5

# Forced Trap Probe v1: detecta muertes forzadas por pasillo/seguimiento rival
# sin ampliar el minimax FE completo. Solo continúa mientras NUESTRA respuesta
# sea única; si recuperamos 2+ opciones, deja de considerarlo una trampa forzada.
FORCED_TRAP_MAX_ROUNDS = 4
FORCED_TRAP_FATAL_PENALTY = FE_FATAL_RISK

# V6.1 Tactical Trap Solver: búsqueda táctica selectiva, no heurística global.
# Se activa solo en posiciones cerradas/tardías y usa presupuesto duro propio.
TACTICAL_SOLVER_MAX_PLIES = 14
TACTICAL_SOLVER_TIME_BUDGET = 0.007
TACTICAL_OFFENSE_MAX_PLIES = 10
TACTICAL_OFFENSE_TIME_BUDGET = 0.0025
TACTICAL_SOLVER_NODE_BUDGET = 3500
# Umbrales REALES del disparador táctico. En V6.1 original estos nombres existían
# pero el código usaba 50/4 escritos a mano, por lo que eran parámetros muertos.
# Dejamos 50/4 como defaults para preservar exactamente el comportamiento original.
TACTICAL_ACTIVE_REMAINING = 50
TACTICAL_HEAD_DISTANCE = 4
TACTICAL_FORCED_LOSS_PENALTY = 850_000_000
TACTICAL_FORCED_WIN_BONUS = 850_000_000

# Safe Food Opportunity: desempate táctico hacia comida claramente ganable.
# Nunca compensa una muerte forzada ni una señal FE fatal.
SAFE_FOOD_MAX_STEPS = 3
SAFE_FOOD_IMMEDIATE_BONUS = 75000
SAFE_FOOD_PATH_BONUS = 45000
SAFE_FOOD_STEP_BONUS = 10_000

AC_HISTORY_SIZE = 32
AC_MAX_PERIOD = 8
AC_MIN_REPEATS = 2
AC_MIN_NO_GROWTH_TURNS = 8
AC_BASE_PENALTY = 9000
AC_REPEAT_PENALTY = 3500
AC_SHORT_PERIOD_BONUS = 1200
AC_PENALTY_CAP = 30000

# V8.1 / regla v4: pickups X y multiplicador de puntos de comida.
X_PICKUP_POINTS = 50          # +50 plano, no se multiplica
X_TURNS_PER_FOOD = 18         # estimación: turnos propios por cada comida comida
X_AVG_FOOD_POINTS = 500       # dígito promedio (5) * 100
X_FUTURE_DISCOUNT = 0.8       # 3.9.2: antes 0.35; la X vale mucho más (los rivales ganan por multiplicador)
X_VIRTUAL_CAP = 6000          # 3.9.2: antes 1200
X_MIN_REMAINING = 12          # al final el multiplicador ya no rinde
X_POTENTIAL_RADIUS = 8        # más lejos que esto, la X no suma en la evaluación
X_POTENTIAL_DECAY = 0.9       # a d pasos la X vale 0.9^d de su valor (calibrado en arena)
X_ORDERING_PRIORITY = 8000

# 3.9.2: carrera por el número que toca, en puntos esperados.
# Antes la evaluación casi no veía quién se iba a comer el próximo número; por eso
# el bot se comía el que tocaba aunque el rival estuviera parado al lado del siguiente
# (que vale más) y se lo regalaba.
RACE_ENABLED = True
RACE_P_BASE = 0.45        # probabilidad base de ganar una carrera pareja
RACE_P_PER_STEP = 0.10    # cada paso de ventaja suma esto
RACE_P_MAX = 0.85
RACE_WEIGHT = 1.0
RACE_CLAIM_WEIGHT = 0.0   # lo que vale 'ir ganando' una carrera sin haber comido
RACE_MIN_REMAINING = 6
# 3.9.2: si el rival gana la carrera del número que toca, me paro cerca de una copia
# del número que viene que quede lejos de donde él va a comer (lo que hacen Alejo y Santino).
CAMP_ENABLED = False      # probado: por ahora no mejora; queda apagado
CAMP_WEIGHT = 0.8
CAMP_P_BASE = 0.5
CAMP_P_PER_STEP = 0.1
DIGIT_CELLS = {}  # posiciones de cada dígito al inicio del turno (se recalcula en la raíz)

# Flags para la Transposition Table (Alpha-Beta exacto)
TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

DIRECTIONS = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}

FOOD_DIGITS = frozenset("123456789")
X_PICKUP = "X"   # regla v4 (16 Sep 2026)
WALL_CHAR = "#"  # regla v5 (23 Sep 2026)


def is_a_side(side):
    """Protocol compatibility: side may be A/B (current) or legacy 1/2."""
    return str(side).upper() in {"A", "1"}


def is_food_symbol(cell):
    return cell == "*" or cell in FOOD_DIGITS


def is_open_cell(cell):
    """Cells that can be entered without colliding. Wrong digits are legal but costly.

    v4: X es una celda comible (+50 y multiplicador), no un obstáculo.
    v5: # NO es abierta (cuesta -500 y no avanzamos).
    """
    return cell == " " or cell == X_PICKUP or is_food_symbol(cell)

# Historiales exactos por partida / estado de búsqueda.
bot_histories = {}
TT = {}
SEARCH_ABORTED = False
SEARCH_NODES = 0
SEARCH_NODE_BUDGET = None
SEARCH_MODE = "time"
LAST_FE_STATS = {}
LAST_AC_STATS = {}
LAST_STRATEGY_STATS = {}

# v4: multiplicador por jugador, clave = is_player_a (True -> jugador A / _1).
# Se carga del turno y la simulación lo sube/baja al comer/descomer una X.
MULTIPLIERS = {True: 1, False: 1}


def _safe_multiplier(value):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def load_multipliers(game_data):
    MULTIPLIERS[True] = _safe_multiplier(game_data.get("multiplier_1", 1))
    MULTIPLIERS[False] = _safe_multiplier(game_data.get("multiplier_2", 1))


def _multiplier_for(is_player_a):
    return MULTIPLIERS.get(bool(is_player_a), 1)


def multiplier_future_value(remaining):
    """Puntos virtuales estimados de +1 paso de multiplicador con `remaining` jugadas."""
    if remaining <= X_MIN_REMAINING:
        return 0
    my_turns = remaining // 2
    value = my_turns / X_TURNS_PER_FOOD * X_AVG_FOOD_POINTS * X_FUTURE_DISCOUNT
    return int(min(X_VIRTUAL_CAP, value))

# =====================================================================
# PARSEO / MOTOR ESTRATÉGICO
# =====================================================================
def _strip_board_frame(line):
    if len(line) >= 2 and line.startswith("|") and line.endswith("|"):
        return line[1:-1]
    return line


def _board_lines(board_str):
    lines = board_str.replace("\r", "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_board_str(board_str):
    board_str = board_str.replace("\ufe0f", "")  # v8/v10: emojis sin selector de variante
    return [list(_strip_board_frame(line)) for line in _board_lines(board_str)]

def parse_board(board_raw):
    if isinstance(board_raw, str):
        return _parse_board_str(board_raw)
    return [list(row) for row in board_raw]

def _dimensions_from_board_size(game_data):
    size = str(game_data.get("board_size", "")).lower().replace(" ", "")
    if "x" not in size:
        return None, None
    left, right = size.split("x", 1)
    if not left.isdigit() or not right.isdigit():
        return None, None
    return int(left), int(right)


def _coalesce_dimension(value, fallback):
    return fallback if value is None else value


def _int_dimensions(rows, cols):
    try:
        return int(rows), int(cols)
    except (TypeError, ValueError):
        return None, None


def _declared_board_dimensions(game_data):
    rows = game_data.get("rows")
    cols = game_data.get("cols")
    fallback_rows, fallback_cols = _dimensions_from_board_size(game_data)
    rows = _coalesce_dimension(rows, fallback_rows)
    cols = _coalesce_dimension(cols, fallback_cols)
    return _int_dimensions(rows, cols)

def parse_turn_board(game_data):
    """Parse board and consume/validate v2 rows, cols and board_size metadata."""
    grid = parse_board(game_data.get("board", ""))
    rows, cols = _declared_board_dimensions(game_data)
    if rows is not None and cols is not None and grid:
        actual = (len(grid), len(grid[0]))
        if actual != (rows, cols):
            # Do not crash a live match on malformed metadata; board remains source of truth.
            LAST_STRATEGY_STATS["dimension_warning"] = {
                "declared": [rows, cols], "actual": list(actual)
            }
    return grid

# =====================================================================
# REGLAS v7-v10: se traducen al vocabulario que ya entiende el motor
# =====================================================================
BOMB_RADIUS = {"\U0001F4A3": 2, "\U0001F9E8": 1}  # 💣 zona 5x5, 🧨 zona 3x3
TAIL_FOOD = frozenset("\u24B6\u24B7")             # Ⓐ Ⓑ
STAR = "\u2B50"                                    # ⭐
SNAKE_CELLS = frozenset("AaBb")
KNOWN_CELLS = frozenset(" #*X") | FOOD_DIGITS | SNAKE_CELLS


def _normalize_invincible(grid, game_data):
    """v10: una serpiente invencible se dibuja con cabeza minúscula y cuerpo mayúscula."""
    for letter, key in (("A", "invincible_1"), ("B", "invincible_2")):
        if not game_data.get(key):
            continue
        low = letter.lower()
        swap = {letter: low, low: letter}
        for row in grid:
            for c, cell in enumerate(row):
                if cell in swap:
                    row[c] = swap[cell]


def _bomb_zone_cells(grid):
    rows, cols = len(grid), len(grid[0]) if grid else 0
    zone = set()
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            radius = BOMB_RADIUS.get(cell)
            if radius is None:
                continue
            for rr in range(max(0, r - radius), min(rows, r + radius + 1)):
                for cc in range(max(0, c - radius), min(cols, c + radius + 1)):
                    zone.add((rr, cc))
    return zone


def adapt_new_rules(grid, game_data):
    """Reescribe en el lugar las celdas de reglas v7-v10 para el motor v6."""
    _normalize_invincible(grid, game_data)
    digits_present = numbered_food_mode(grid)
    for r, c in _bomb_zone_cells(grid):
        if grid[r][c] not in SNAKE_CELLS:
            grid[r][c] = WALL_CHAR
    for row in grid:
        for c, cell in enumerate(row):
            if cell in TAIL_FOOD or cell == STAR:
                row[c] = " "
            elif cell == "*" and digits_present:
                row[c] = " "
            elif cell not in KNOWN_CELLS:
                row[c] = WALL_CHAR  # símbolo desconocido: mejor no pisarlo
    return grid

def _find_cell_with_targets(grid, targets):
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in targets:
                return (r, c)
    return None

def find_head(grid, side):
    # V3 uses digits as food, so numeric board cells can NEVER be snake heads.
    return _find_cell_with_targets(grid, {"A"} if is_a_side(side) else {"B"})

def find_enemy_head(grid, side):
    return _find_cell_with_targets(grid, {"B"} if is_a_side(side) else {"A"})

def _cyclic_predecessor_digit(digit):
    value = int(digit)
    return str(9 if value == 1 else value - 1)

def _numbered_food_positions(grid):
    """v6: {dígito: [todas sus copias en orden de lectura]}."""
    cells = {}
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in FOOD_DIGITS:
                cells.setdefault(val, []).append((r, c))
    return cells

def _numbered_food_cells(grid):
    """Compatibilidad: una posición por dígito (la primera copia)."""
    return {digit: positions[0] for digit, positions in _numbered_food_positions(grid).items()}

def _forward_food_run_length(start, present):
    current = int(start)
    length = 0
    while str(current) in present and length < 9:
        length += 1
        current = 1 if current == 9 else current + 1
    return length


def _fallback_food_digit(present):
    ordered = sorted(present, key=int)
    key = lambda digit: (_forward_food_run_length(digit, present), -int(digit))
    return max(ordered, key=key)


def _target_digit(present):
    candidates = [
        digit for digit in present
        if _cyclic_predecessor_digit(digit) not in present
    ]
    return candidates[0] if len(candidates) == 1 else _fallback_food_digit(present)


def correct_numbered_food_positions(grid):
    """Return (digit, [todas las copias]) del dígito correcto, o (None, [])."""
    cells = _numbered_food_positions(grid)
    if not cells:
        return None, []
    digit = _target_digit(set(cells))
    return digit, list(cells[digit])


def correct_numbered_food(grid):
    """Return (digit, position) for the next legal v3 digit, or (None, None)."""
    digit, positions = correct_numbered_food_positions(grid)
    if digit is None:
        return None, None
    return digit, positions[0]

def _legacy_food_cells(grid):
    return [
        (r, c)
        for r, row in enumerate(grid)
        for c, value in enumerate(row)
        if value == "*"
    ]


def find_food(grid):
    """Strategic food targets: all legacy apples, or ALL copies of the correct digit (v6)."""
    stars = _legacy_food_cells(grid)
    if stars:
        return stars
    _, positions = correct_numbered_food_positions(grid)
    return positions

def current_food_reward(grid, food_list=None):
    targets = food_list if food_list is not None else find_food(grid)
    if not targets:
        return 100
    r, c = targets[0]
    cell = grid[r][c]
    return int(cell) * 100 if cell in FOOD_DIGITS else 100

def numbered_food_mode(grid):
    return any(val in FOOD_DIGITS for row in grid for val in row)

def wrong_numbered_food_at(grid, pos, food_list):
    if not is_pos_inside(grid, pos):
        return False
    cell = grid[pos[0]][pos[1]]
    return cell in FOOD_DIGITS and pos not in set(food_list)

def is_pos_inside(grid, pos):
    if not grid or not pos:
        return False
    return 0 <= pos[0] < len(grid) and 0 <= pos[1] < len(grid[0])


def target_copies_mode(grid, food_list):
    """v6: True si food_list son varias copias del MISMO dígito objetivo.

    En ese caso la carrera se decide por la copia más cercana de cada jugador:
    si el rival come cualquier copia, desaparecen todas.
    """
    if not food_list or len(food_list) < 2:
        return False
    pos = food_list[0]
    return is_pos_inside(grid, pos) and grid[pos[0]][pos[1]] in FOOD_DIGITS


def _min_food_distance(distances, food_list):
    return min((distances.get(food, INF) for food in food_list), default=INF)


def _effective_enemy_food_distances(distances, food_list, collapse):
    """Con copias, la distancia del rival a CADA copia es su distancia a la más cercana."""
    if not collapse:
        return distances
    effective = dict(distances)
    best = _min_food_distance(distances, food_list)
    for food in food_list:
        effective[food] = best
    return effective

# =====================================================================
# 4. RASTREO ROBUSTO DE CUERPOS (StateTracker)
# =====================================================================

def _is_unvisited_body_cell(grid, pos, body_char, visited):
    if not is_pos_inside(grid, pos):
        return False
    return pos not in visited and grid[pos[0]][pos[1]] == body_char


def _body_candidate_degree(grid, pos, body_char, visited):
    degree = 0
    for dr, dc in DIRECTIONS.values():
        q = (pos[0] + dr, pos[1] + dc)
        if _is_unvisited_body_cell(grid, q, body_char, visited):
            degree += 1
    return degree


def _trace_candidates(grid, curr, body_char, visited):
    out = []
    for dr, dc in DIRECTIONS.values():
        npos = (curr[0] + dr, curr[1] + dc)
        if _is_unvisited_body_cell(grid, npos, body_char, visited):
            out.append((_body_candidate_degree(grid, npos, body_char, visited), npos))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out]


def _trace_dfs(grid, curr, body_char, expected_len, path, visited, node_state, node_budget):
    node_state[0] += 1
    if node_state[0] > node_budget:
        return False
    if len(path) == expected_len:
        return True
    for npos in _trace_candidates(grid, curr, body_char, visited):
        visited.add(npos)
        path.append(npos)
        if _trace_dfs(grid, npos, body_char, expected_len, path, visited, node_state, node_budget):
            return True
        path.pop()
        visited.remove(npos)
    return False


def _first_unseen_body_neighbor(grid, curr, body_char, seen):
    for dr, dc in DIRECTIONS.values():
        q = (curr[0] + dr, curr[1] + dc)
        if _is_unvisited_body_cell(grid, q, body_char, seen):
            return q
    return None


def _trace_greedy_fallback(grid, head, body_char):
    greedy = [head]
    curr = head
    seen = {head}
    while True:
        nxt = _first_unseen_body_neighbor(grid, curr, body_char, seen)
        if nxt is None:
            break
        greedy.append(nxt)
        seen.add(nxt)
        curr = nxt
    return deque(reversed(greedy))


def _trace_full_snake(grid, head, body_char):
    """Reconstruye head->tail cubriendo todas las celdas si es posible."""
    expected_len = 1 + sum(row.count(body_char) for row in grid)
    if expected_len <= 1:
        return deque([head])
    path = [head]
    visited = {head}
    if _trace_dfs(grid, head, body_char, expected_len, path, visited, [0], 50000):
        return deque(reversed(path))
    return _trace_greedy_fallback(grid, head, body_char)


def _history_for_game(game_id):
    if game_id not in bot_histories:
        bot_histories[game_id] = {"my_path": deque(), "en_path": deque()}
    return bot_histories[game_id]


def _append_head_if_new(path, head):
    if not head:
        return
    if not path or path[-1] != head:
        path.append(head)


def _resync_path_if_short(path, cell_count, grid, head, body_char):
    if not head:
        return path
    if len(path) < cell_count:
        return _trace_full_snake(grid, head, body_char)
    return path


def _trim_history_path(path, cell_count):
    while len(path) > cell_count:
        path.popleft()



def _side_body_symbols(is_p1):
    if is_p1:
        return {"A", "a"}, {"B", "b"}, "a", "b"
    return {"B", "b"}, {"A", "a"}, "b", "a"


def _count_target_cells(grid, targets):
    total = 0
    for row in grid:
        for char in targets:
            total += row.count(char)
    return total


def get_bodies(game_id, grid, side):
    head_my = find_head(grid, side)
    head_en = find_enemy_head(grid, side)
    my_target, en_target, my_body_char, en_body_char = _side_body_symbols(is_a_side(side))
    my_cells = _count_target_cells(grid, my_target)
    en_cells = _count_target_cells(grid, en_target)
    history = _history_for_game(game_id)
    _append_head_if_new(history["my_path"], head_my)
    _append_head_if_new(history["en_path"], head_en)
    history["my_path"] = _resync_path_if_short(history["my_path"], my_cells, grid, head_my, my_body_char)
    history["en_path"] = _resync_path_if_short(history["en_path"], en_cells, grid, head_en, en_body_char)
    _trim_history_path(history["my_path"], my_cells)
    _trim_history_path(history["en_path"], en_cells)
    return deque(reversed(history["my_path"])), deque(reversed(history["en_path"]))

# =====================================================================
# 5. TOPOLOGÍA, CORREDORES Y DISTANCIAS BFS REALES
# =====================================================================
def _bfs_can_enter(grid, pos, tail_pos, distances):
    if not is_pos_inside(grid, pos):
        return False
    if pos in distances:
        return False
    return is_open_cell(grid[pos[0]][pos[1]]) or pos == tail_pos


def _bfs_neighbors(grid, curr):
    for dr, dc in DIRECTIONS.values():
        yield curr[0] + dr, curr[1] + dc


def _valid_bfs_start(grid, start_pos):
    return bool(start_pos) and is_pos_inside(grid, start_pos)


def _fast_bfs_distances(grid, start_pos, tail_pos=None):
    """BFS equivalente usando índices enteros y buffers planos.

    Conserva el mismo contrato de salida (dict {(r,c): distancia}) que el v4,
    pero evita la mayor parte de las tuplas, búsquedas en dict y llamadas de
    helpers dentro del recorrido caliente.
    (V8.1: X cuenta como celda abierta, igual que is_open_cell.)
    """
    if not _valid_bfs_start(grid, start_pos):
        return {}

    rows = len(grid)
    cols = len(grid[0])
    sr, sc = start_pos
    total = rows * cols

    dist = [-1] * total
    queue = [0] * total
    visited = [0] * total

    start_idx = sr * cols + sc
    tail_idx = (
        tail_pos[0] * cols + tail_pos[1]
        if tail_pos is not None and is_pos_inside(grid, tail_pos)
        else -1
    )

    dist[start_idx] = 0
    queue[0] = start_idx
    visited[0] = start_idx
    q_head = 0
    q_tail = 1
    visited_count = 1

    while q_head < q_tail:
        idx = queue[q_head]
        q_head += 1
        r = idx // cols
        c = idx - r * cols
        next_dist = dist[idx] + 1

        if r > 0:
            nidx = idx - cols
            if dist[nidx] < 0:
                cell = grid[r - 1][c]
                if cell == " " or cell == "*" or cell == "X" or cell in FOOD_DIGITS or nidx == tail_idx:
                    dist[nidx] = next_dist
                    queue[q_tail] = nidx
                    visited[visited_count] = nidx
                    q_tail += 1
                    visited_count += 1

        if r + 1 < rows:
            nidx = idx + cols
            if dist[nidx] < 0:
                cell = grid[r + 1][c]
                if cell == " " or cell == "*" or cell == "X" or cell in FOOD_DIGITS or nidx == tail_idx:
                    dist[nidx] = next_dist
                    queue[q_tail] = nidx
                    visited[visited_count] = nidx
                    q_tail += 1
                    visited_count += 1

        if c > 0:
            nidx = idx - 1
            if dist[nidx] < 0:
                cell = grid[r][c - 1]
                if cell == " " or cell == "*" or cell == "X" or cell in FOOD_DIGITS or nidx == tail_idx:
                    dist[nidx] = next_dist
                    queue[q_tail] = nidx
                    visited[visited_count] = nidx
                    q_tail += 1
                    visited_count += 1

        if c + 1 < cols:
            nidx = idx + 1
            if dist[nidx] < 0:
                cell = grid[r][c + 1]
                if cell == " " or cell == "*" or cell == "X" or cell in FOOD_DIGITS or nidx == tail_idx:
                    dist[nidx] = next_dist
                    queue[q_tail] = nidx
                    visited[visited_count] = nidx
                    q_tail += 1
                    visited_count += 1

    return {
        (idx // cols, idx % cols): dist[idx]
        for idx in visited[:visited_count]
    }


def bfs_distances(grid, start_pos, tail_pos=None):
    return _fast_bfs_distances(grid, start_pos, tail_pos)

def _legal_destination(grid, npos, tail_my):
    if not is_pos_inside(grid, npos):
        return False
    value = grid[npos[0]][npos[1]]
    if is_open_cell(value):
        return True
    return npos == tail_my and not is_food_symbol(value)


def get_legal_moves_raw(grid, head, body, other_body):
    if not head:
        return []
    tail_my = body[-1] if body else None
    moves = []
    for name, (dr, dc) in DIRECTIONS.items():
        npos = (head[0] + dr, head[1] + dc)
        if _legal_destination(grid, npos, tail_my):
            moves.append((name, npos))
    return moves

def _effective_exit_count(grid, start_pos, tail_pos):
    count = 0
    for npos in _bfs_neighbors(grid, start_pos):
        if not is_pos_inside(grid, npos):
            continue
        if is_open_cell(grid[npos[0]][npos[1]]) or npos == tail_pos:
            count += 1
    return count


def _tail_reachable(distances, tail_pos):
    return bool(tail_pos and tail_pos in distances)


def analyze_topology(grid, start_pos, my_len, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos):
        return 0, 0, False, False, {}
    distances = bfs_distances(grid, start_pos, tail_pos)
    space = len(distances)
    exits = _effective_exit_count(grid, start_pos, tail_pos)
    tail_reachable = _tail_reachable(distances, tail_pos)
    pocket = space <= my_len + 1 and not tail_reachable
    return space, exits, tail_reachable, pocket, distances


def _open_outside_region(grid, npos, region):
    if not is_pos_inside(grid, npos):
        return False
    return is_open_cell(grid[npos[0]][npos[1]]) and npos not in region


def _count_open_connections(grid, pos, region):
    count = 0
    for dr, dc in DIRECTIONS.values():
        npos = (pos[0] + dr, pos[1] + dc)
        if _open_outside_region(grid, npos, region):
            count += 1
    return count


def _reaches_chokepoint_first(dist_my, dist_en):
    return dist_my != INF and dist_my <= dist_en


def _find_reachable_chokepoint(grid, enemy_distances, my_distances):
    for pos, dist_en in enemy_distances.items():
        if _count_open_connections(grid, pos, enemy_distances) < 2:
            continue
        if _reaches_chokepoint_first(my_distances.get(pos, INF), dist_en):
            return pos
    return None


def _enemy_region_is_compressed(grid, exits, space):
    return exits <= 2 and space < (len(grid) * len(grid[0]) // 2)



def _tail_or_none(body):
    if body:
        return body[-1]
    return None


def _chokepoint_result(pos):
    if pos is None:
        return False, None, False
    return True, pos, True


def analyze_corridor_chokepoints(grid, my_head, en_head, my_body, en_body):
    """Identifica cuellos de botella y puertas usando BFS real."""
    if not en_head or not my_head:
        return False, None, False
    en_tail = _tail_or_none(en_body)
    my_tail = _tail_or_none(my_body)
    en_space, en_exits, _, _, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    if not _enemy_region_is_compressed(grid, en_exits, en_space):
        return False, None, False
    pos = _find_reachable_chokepoint(grid, en_dists, bfs_distances(grid, my_head, my_tail))
    return _chokepoint_result(pos)

class TopologyInfo:
    __slots__ = ('space', 'exits', 'tail_reachable', 'pocket_trap', 'distances')

    def __init__(self, space, exits, tail_reachable, pocket_trap, distances):
        self.space = space
        self.exits = exits
        self.tail_reachable = tail_reachable
        self.pocket_trap = pocket_trap
        self.distances = distances



def _flood_cell_allowed(grid, npos, tail_pos, distances):
    if not is_pos_inside(grid, npos):
        return False
    if npos in distances:
        return False
    return is_open_cell(grid[npos[0]][npos[1]]) or npos == tail_pos


def _flood_distances(grid, start_pos, tail_pos):
    # Misma semántica que el flood del v4; comparte el núcleo BFS optimizado.
    return _fast_bfs_distances(grid, start_pos, tail_pos)


def _is_open_exit(grid, npos, tail_pos):
    if not is_pos_inside(grid, npos):
        return False
    return is_open_cell(grid[npos[0]][npos[1]]) or npos == tail_pos


def _count_open_exits(grid, start_pos, tail_pos):
    exits = 0
    for dr, dc in DIRECTIONS.values():
        npos = (start_pos[0] + dr, start_pos[1] + dc)
        if _is_open_exit(grid, npos, tail_pos):
            exits += 1
    return exits


def analyze_topology_consolidated(grid, start_pos, my_len, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos):
        return TopologyInfo(0, 0, False, False, {})
    distances = _flood_distances(grid, start_pos, tail_pos)
    space = len(distances)
    exits = _count_open_exits(grid, start_pos, tail_pos)
    tail_reachable = tail_pos in distances if tail_pos else False
    pocket_trap = space <= my_len + 1 and not tail_reachable
    return TopologyInfo(space, exits, tail_reachable, pocket_trap, distances)



def analyze_corridor_chokepoints_opt(grid, my_head, en_head, en_topo, my_topo):
    if not en_head or not my_head:
        return False, None, False
    if not _enemy_region_is_compressed(grid, en_topo.exits, en_topo.space):
        return False, None, False
    pos = _find_reachable_chokepoint(grid, en_topo.distances, my_topo.distances)
    return (True, pos, True) if pos is not None else (False, None, False)

# =====================================================================
# 6. SIMULADOR EXACTO DE ESTADOS (O(1))
# =====================================================================
def _move_food_flags(target_char, next_pos, food_list):
    legacy = target_char == "*"
    digit = target_char in FOOD_DIGITS
    correct = digit and next_pos in food_list
    wrong = digit and not correct
    return legacy, correct, wrong


def _remove_tail_for_move(grid, body, grows):
    if grows or not body:
        return None, None
    tail_pos = body.pop()
    prev_tail_char = grid[tail_pos[0]][tail_pos[1]]
    grid[tail_pos[0]][tail_pos[1]] = " "
    return tail_pos, prev_tail_char


def _demote_old_head(grid, body, body_char):
    if body:
        old_head = body[0]
        grid[old_head[0]][old_head[1]] = body_char


def _score_move_result(current_score, target_char, legacy, correct, wrong, multiplier=1):
    if legacy:
        return current_score + 100 * multiplier
    if correct:
        return current_score + int(target_char) * 100 * multiplier
    if wrong:
        return current_score - 500
    if target_char == X_PICKUP:
        return current_score + X_PICKUP_POINTS
    return current_score + 1


def _refresh_food_after_move(grid, food_list, legacy, correct):
    if legacy or correct:
        food_list[:] = find_food(grid)


def _consume_target_copies(grid, target_positions, eaten_pos, digit_char):
    """v6: comer el dígito objetivo elimina todas sus demás copias."""
    for pos in target_positions:
        if pos != eaten_pos and grid[pos[0]][pos[1]] == digit_char:
            grid[pos[0]][pos[1]] = " "


def _restore_target_copies(grid, food_undo, eaten_pos, digit_char, eaten_food):
    if not eaten_food or digit_char not in FOOD_DIGITS:
        return
    if not isinstance(food_undo, (tuple, list)):
        return
    for pos in food_undo:
        if pos != eaten_pos and grid[pos[0]][pos[1]] == " ":
            grid[pos[0]][pos[1]] = digit_char


def _bump_multiplier(target_char, is_player_a, step):
    if target_char == X_PICKUP:
        key = bool(is_player_a)
        MULTIPLIERS[key] = MULTIPLIERS.get(key, 1) + step


def make_move(grid, body, next_pos, is_player_a, current_score, food_list):
    """Apply one simulated move for legacy *, v3/v6 numbered food and v4 X."""
    head_char = "A" if is_player_a else "B"
    body_char = "a" if is_player_a else "b"
    prev_target_char = grid[next_pos[0]][next_pos[1]]
    legacy, correct, wrong = _move_food_flags(
        prev_target_char, next_pos, food_list
    )
    grows = legacy or correct
    food_undo = tuple(food_list)
    multiplier = _multiplier_for(is_player_a)
    tail_pos, prev_tail_char = _remove_tail_for_move(grid, body, grows)
    _demote_old_head(grid, body, body_char)
    grid[next_pos[0]][next_pos[1]] = head_char
    body.appendleft(next_pos)
    current_score = _score_move_result(
        current_score, prev_target_char, legacy, correct, wrong, multiplier
    )
    if correct:
        _consume_target_copies(grid, food_undo, next_pos, prev_target_char)
    _bump_multiplier(prev_target_char, is_player_a, 1)
    _refresh_food_after_move(grid, food_list, legacy, correct)
    return (
        tail_pos, prev_tail_char, prev_target_char,
        grows, current_score, food_undo
    )

def _restore_old_head(grid, body, prev_target_char):
    old_head = body.popleft()
    grid[old_head[0]][old_head[1]] = prev_target_char


def _restore_new_head(grid, body, head_char):
    if body:
        new_head = body[0]
        grid[new_head[0]][new_head[1]] = head_char


def _restore_tail(grid, body, tail_pos, prev_tail_char, eaten_food):
    if eaten_food or not tail_pos:
        return
    body.append(tail_pos)
    grid[tail_pos[0]][tail_pos[1]] = prev_tail_char


def _restore_food_snapshot(food_list, food_undo):
    if isinstance(food_undo, (tuple, list)):
        food_list[:] = list(food_undo)


def unmake_move(grid, body, tail_pos, prev_tail_char, prev_target_char,
                eaten_food, is_player_a, next_pos, food_list, food_undo):
    head_char = "A" if is_player_a else "B"
    _restore_old_head(grid, body, prev_target_char)
    _restore_new_head(grid, body, head_char)
    _restore_tail(grid, body, tail_pos, prev_tail_char, eaten_food)
    _restore_target_copies(grid, food_undo, next_pos, prev_target_char, eaten_food)
    _bump_multiplier(prev_target_char, is_player_a, -1)
    _restore_food_snapshot(food_list, food_undo)

# =====================================================================
# 6B. FUTURE ESCAPE V1 (aislado del Alpha-Beta principal)
# =====================================================================

def _fe_exit_risk(topo, terminal_if_no_moves):
    risk = 0
    if topo.exits == 0:
        risk = FE_FATAL_RISK if terminal_if_no_moves else FE_POCKET_RISK
    if topo.exits == 1:
        risk = max(risk, FE_SINGLE_EXIT_RISK)
    return risk


def _fe_tail_space_risk(topo, margin):
    if topo.tail_reachable:
        return 0
    if margin <= 1:
        return FE_TIGHT_RISK + 50000
    if margin <= 3:
        return FE_TIGHT_RISK
    if margin <= 6:
        return 35000
    return 0


def _future_escape_state_risk(grid, my_body, en_body, food_list, terminal_if_no_moves=True):
    """Riesgo geométrico actual para NUESTRA serpiente."""
    if not my_body:
        return FE_FATAL_RISK
    my_head = my_body[0]
    legal = get_legal_moves_raw(grid, my_head, my_body, en_body)
    if terminal_if_no_moves and not legal:
        return FE_FATAL_RISK
    topo = analyze_topology_consolidated(grid, my_head, len(my_body), my_body[-1])
    margin = topo.space - len(my_body)
    risk = _fe_exit_risk(topo, terminal_if_no_moves)
    if topo.pocket_trap:
        risk = max(risk, FE_POCKET_RISK + max(0, 2 - margin) * 10000)
    return max(risk, _fe_tail_space_risk(topo, margin))



def _fe_budget_reached(deadline, stats):
    return time.monotonic() >= deadline or stats['nodes'] >= FE_NODE_BUDGET


def _fe_cache_key(my_body, en_body, food_list, depth, is_my_turn, my_is_a):
    return (tuple(my_body), tuple(en_body), tuple(sorted(food_list)), depth, is_my_turn, my_is_a)


def _fe_early_internal_result(is_my_turn, current_risk, deadline, stats):
    if is_my_turn and current_risk >= FE_FATAL_RISK:
        return current_risk
    if _fe_budget_reached(deadline, stats):
        stats['aborted'] = True
        return current_risk
    return None


def _fe_child_after_move(grid, moving_body, other_body, food_list, moving_is_a,
                         npos, my_body, en_body, my_is_a, depth, next_is_my_turn,
                         deadline, stats, memo):
    undo = make_move(grid, moving_body, npos, moving_is_a, 0, food_list)
    try:
        return future_escape_risk(
            grid, my_body, en_body, food_list, my_is_a,
            depth - 1, next_is_my_turn, deadline, stats, memo
        )
    finally:
        unmake_move(
            grid, moving_body, undo[0], undo[1], undo[2], undo[3],
            moving_is_a, npos, food_list, undo[5]
        )


def _fe_my_turn_risk(grid, my_body, en_body, food_list, my_is_a, depth,
                     deadline, stats, memo, current_risk):
    moves = get_legal_moves_raw(grid, my_body[0], my_body, en_body)
    if not moves:
        return FE_FATAL_RISK
    best_risk = FE_FATAL_RISK
    for _, npos in moves:
        if _fe_budget_reached(deadline, stats):
            stats['aborted'] = True
            break
        child = _fe_child_after_move(
            grid, my_body, en_body, food_list, my_is_a, npos,
            my_body, en_body, my_is_a, depth, False, deadline, stats, memo
        )
        best_risk = min(best_risk, max(current_risk, child))
        if best_risk == 0:
            break
    return _fe_aborted_best_risk(best_risk, current_risk, stats)


def _fe_aborted_best_risk(best_risk, current_risk, stats):
    if best_risk == FE_FATAL_RISK and stats['aborted']:
        return current_risk
    return best_risk



def _fe_enemy_moves(grid, my_body, en_body):
    if not en_body:
        return []
    return get_legal_moves_raw(grid, en_body[0], en_body, my_body)


def _fe_explored_result(explored, worst_risk, current_risk):
    if explored:
        return worst_risk
    return current_risk


def _fe_enemy_turn_risk(grid, my_body, en_body, food_list, my_is_a, depth,
                        deadline, stats, memo, current_risk):
    moves = _fe_enemy_moves(grid, my_body, en_body)
    if not moves:
        return 0
    worst_risk = 0
    explored = False
    for _, npos in moves:
        if _fe_budget_reached(deadline, stats):
            stats['aborted'] = True
            break
        explored = True
        child = _fe_child_after_move(
            grid, en_body, my_body, food_list, not my_is_a, npos,
            my_body, en_body, my_is_a, depth, True, deadline, stats, memo
        )
        worst_risk = max(worst_risk, child)
        if worst_risk >= FE_FATAL_RISK:
            break
    return _fe_explored_result(explored, worst_risk, current_risk)


def future_escape_risk(grid, my_body, en_body, food_list, my_is_a,
                       depth, is_my_turn, deadline, stats, memo):
    """Minimax pequeño de riesgo: nosotros minimizamos riesgo, rival lo maximiza."""
    stats['nodes'] += 1
    if depth <= 0:
        return _future_escape_state_risk(grid, my_body, en_body, food_list, True)
    current_risk = _future_escape_state_risk(grid, my_body, en_body, food_list, is_my_turn)
    early = _fe_early_internal_result(is_my_turn, current_risk, deadline, stats)
    if early is not None:
        return early
    key = _fe_cache_key(my_body, en_body, food_list, depth, is_my_turn, my_is_a)
    cached = memo.get(key)
    if cached is not None:
        return max(current_risk, cached)
    if is_my_turn:
        result = _fe_my_turn_risk(
            grid, my_body, en_body, food_list, my_is_a, depth,
            deadline, stats, memo, current_risk
        )
    else:
        result = _fe_enemy_turn_risk(
            grid, my_body, en_body, food_list, my_is_a, depth,
            deadline, stats, memo, current_risk
        )
    memo[key] = result
    return result



def _state_snapshot(grid, my_body, en_body, food_list):
    return tuple(tuple(row) for row in grid), tuple(my_body), tuple(en_body), tuple(food_list)


def _state_matches_snapshot(snapshot, grid, my_body, en_body, food_list):
    return snapshot == _state_snapshot(grid, my_body, en_body, food_list)


def _compute_fe_root_candidate(grid, my_body, en_body, food_list, my_is_a,
                               npos, horizon, deadline, stats, memo):
    undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
    try:
        return future_escape_risk(
            grid, my_body, en_body, food_list, my_is_a,
            horizon, False, deadline, stats, memo
        )
    finally:
        unmake_move(
            grid, my_body, undo[0], undo[1], undo[2], undo[3],
            my_is_a, npos, food_list, undo[5]
        )


def _collect_fe_penalties(grid, my_body, en_body, food_list, my_is_a,
                          candidates, horizon, deadline, stats, memo):
    penalties = {}
    for move_name, npos in candidates:
        if _fe_budget_reached(deadline, stats):
            stats['aborted'] = True
            penalties.setdefault(move_name, 0)
            continue
        penalties[move_name] = _compute_fe_root_candidate(
            grid, my_body, en_body, food_list, my_is_a,
            npos, horizon, deadline, stats, memo
        )
    return penalties


def _finalize_fe_penalties(candidates, penalties, aborted):
    if aborted:
        return {move_name: 0 for move_name, _ in candidates}
    for move_name, _ in candidates:
        penalties.setdefault(move_name, 0)
    return penalties


def compute_future_escape_penalties(grid, my_body, en_body, food_list,
                                    my_is_a, candidates, overall_deadline,
                                    horizon=FE_HORIZON, deterministic=False):
    """Calcula una penalización FE por candidato raíz, una sola vez por turno."""
    global LAST_FE_STATS
    start = time.monotonic()
    fe_deadline = float('inf') if deterministic else min(overall_deadline, start + FE_TIME_BUDGET)
    stats = {'nodes': 0, 'aborted': False}
    original = _state_snapshot(grid, my_body, en_body, food_list)
    penalties = _collect_fe_penalties(
        grid, my_body, en_body, food_list, my_is_a, candidates,
        horizon, fe_deadline, stats, {}
    )
    penalties = _finalize_fe_penalties(candidates, penalties, stats['aborted'])
    reversible = _state_matches_snapshot(original, grid, my_body, en_body, food_list)
    if not reversible:
        raise AssertionError("Future Escape rompió la reversibilidad del estado")
    LAST_FE_STATS = {
        'enabled': True, 'nodes': stats['nodes'], 'aborted': stats['aborted'],
        'elapsed_ms': (time.monotonic() - start) * 1000.0,
        'penalties': dict(penalties), 'horizon': horizon,
        'reversible': reversible, 'applied': not stats['aborted'],
    }
    return penalties

# =====================================================================
# 7. FOOD RACE V1 + EVALUADOR TÁCTICO
# =====================================================================

def _food_race_value(distance, other_distance, reward_scale):
    dist = min(distance, FOOD_RACE_MAX_DISTANCE)
    margin = FOOD_RACE_MAX_DISTANCE if other_distance == INF else min(other_distance - distance, 6)
    value = (
        FOOD_RACE_BASE
        + max(0, FOOD_RACE_MAX_DISTANCE - dist) * FOOD_RACE_DISTANCE_WEIGHT
        + margin * FOOD_RACE_MARGIN_WEIGHT
    )
    if distance <= 2:
        value += FOOD_RACE_NEAR_BONUS
    if other_distance == INF:
        value += FOOD_RACE_SOLO_REACHABLE_BONUS
    return value * reward_scale


def _food_race_side(my_distance, enemy_distance, reward_scale):
    if my_distance == INF and enemy_distance == INF:
        return None, 0
    if my_distance < enemy_distance:
        return 'claim', _food_race_value(my_distance, enemy_distance, reward_scale)
    if enemy_distance < my_distance:
        return 'threat', _food_race_value(enemy_distance, my_distance, reward_scale)
    return None, 0


def _weighted_top_two(values):
    if not values:
        return 0
    total = values[0]
    if len(values) > 1:
        total += int(values[1] * FOOD_RACE_SECONDARY_WEIGHT)
    return total


def compute_food_race_bonus(my_topo, en_topo, food_list, reward_scale=1, collapse=False):
    """Valor focal de carrera por comida sin BFS adicionales.

    collapse=True (v6, copias del mismo dígito): una sola carrera entre la copia
    más cercana para nosotros y la más cercana para el rival.
    """
    if not food_list:
        return 0
    reward_scale = max(1, min(9, int(reward_scale)))
    scaled_cap = FOOD_RACE_CAP * reward_scale
    if collapse:
        side, value = _food_race_side(
            _min_food_distance(my_topo.distances, food_list),
            _min_food_distance(en_topo.distances, food_list),
            reward_scale
        )
        signed = value if side == 'claim' else (-value if side == 'threat' else 0)
        return max(-scaled_cap, min(scaled_cap, signed))
    claims, threats = [], []
    for food in food_list:
        side, value = _food_race_side(
            my_topo.distances.get(food, INF), en_topo.distances.get(food, INF), reward_scale
        )
        if side == 'claim':
            claims.append(value)
        elif side == 'threat':
            threats.append(value)
    claims.sort(reverse=True)
    threats.sort(reverse=True)
    positive = _weighted_top_two(claims)
    negative = _weighted_top_two(threats)
    return max(-scaled_cap, min(scaled_cap, positive - negative))

def _turns_left(remaining, my_to_move):
    if my_to_move:
        return (remaining + 1) // 2, remaining // 2
    return remaining // 2, (remaining + 1) // 2


def _apple_margin_requirements(base_margin, food_swing):
    if base_margin > 0:
        safe = max(0, (base_margin - 1) // food_swing)
        return 0, safe
    required = max(1, (1 - base_margin + food_swing - 1) // food_swing)
    return required, 0


def _leading_strategy_mode(remaining, safe):
    locked = remaining <= STRATEGY_LOCK_REMAINING and safe >= 2
    return "LOCK" if locked else "LEADING"


def _losing_strategy_mode(remaining, required):
    late_two = remaining <= STRATEGY_LOCK_REMAINING and required >= 2
    desperate = required >= STRATEGY_DESPERATE_NET_APPLES or late_two
    return "DESPERATE" if desperate else "TRAILING"


def _strategy_mode(remaining, base_margin, required, safe):
    if remaining > STRATEGY_ACTIVE_REMAINING:
        return "NORMAL"
    if base_margin > 0:
        return _leading_strategy_mode(remaining, safe)
    return _losing_strategy_mode(remaining, required)


def compute_strategy_state(my_score, en_score, remaining,
                           my_to_move=True, food_reward=100):
    remaining = max(0, int(remaining))
    my_turns_left, en_turns_left = _turns_left(remaining, my_to_move)
    base_margin = my_score - en_score + my_turns_left - en_turns_left
    food_swing = max(1, int(food_reward) - 1)
    required, safe = _apple_margin_requirements(base_margin, food_swing)
    return {
        "mode": _strategy_mode(remaining, base_margin, required, safe),
        "base_margin": base_margin,
        "required_net_apples": required,
        "safe_concedable_apples": safe,
        "my_turns_left": my_turns_left,
        "enemy_turns_left": en_turns_left,
        "my_to_move": bool(my_to_move),
        "remaining": remaining,
        "food_reward": int(food_reward),
        "food_swing": food_swing,
    }


def _strategy_adjust_anti_cycle_penalties(penalties, strategy):
    """El ciclo no significa lo mismo según el objetivo de la partida.

    LOCK: repetir una ruta segura puede ser una defensa válida.
    DESPERATE: bailar sin progresar es especialmente malo.
    """
    mode = strategy.get("mode", "NORMAL")
    out = {}
    for move, value in penalties.items():
        if mode == "LOCK":
            out[move] = int(value * 0.20)
        elif mode == "LEADING":
            out[move] = int(value * 0.70)
        elif mode == "DESPERATE":
            out[move] = min(int(AC_PENALTY_CAP * 1.5), int(value * 1.35))
        else:
            out[move] = value
    return out



def _apple_freeze_inactive(strategy, remaining, food_count):
    return (
        strategy.get("mode") != "LOCK"
        or remaining > APPLE_FREEZE_MAX_REMAINING
        or remaining <= APPLE_BANK_CASHOUT_REMAINING
        or food_count < 2
    )


def _is_safe_non_food_candidate(name, npos, food_set, fe_penalties, forced_trap_penalties):
    return (
        npos not in food_set
        and fe_penalties.get(name, 0) == 0
        and forced_trap_penalties.get(name, 0) == 0
    )


def _safe_non_food_names(candidates, food_set, fe_penalties, forced_trap_penalties):
    return [
        name for name, npos in candidates
        if _is_safe_non_food_candidate(name, npos, food_set, fe_penalties, forced_trap_penalties)
    ]


def _is_bankable_food(md, ed):
    return md <= 2 and (ed == INF or ed >= md + 3)


def _is_enemy_urgent_food(md, ed):
    return ed <= 2 and ed < md


def _classify_freeze_food(food_list, my_topo, en_topo):
    bankable = []
    enemy_urgent = 0
    for food in food_list:
        md = my_topo.distances.get(food, INF)
        ed = en_topo.distances.get(food, INF)
        if _is_bankable_food(md, ed):
            bankable.append(food)
        if _is_enemy_urgent_food(md, ed):
            enemy_urgent += 1
    return bankable, enemy_urgent


def _bank_time_window_open(remaining):
    if remaining > ENDGAME_BANK_MAX_REMAINING:
        return False
    return remaining > ENDGAME_BANK_CASHOUT_REMAINING


def _deferred_catchup_bank_allowed(strategy, remaining):
    if not _bank_time_window_open(remaining):
        return False
    base_margin = strategy.get("base_margin", 0)
    food_swing = max(1, strategy.get("food_swing", 99))
    if base_margin >= 0:
        return True
    required = strategy.get("required_net_apples", 99)
    if base_margin < -food_swing:
        return False
    return required <= ENDGAME_BANK_MAX_REQUIRED_NET


def _historical_freeze_may_run(strategy, remaining, food_count):
    return not _apple_freeze_inactive(strategy, remaining, food_count)


def _bank_layer_may_run(strategy, remaining, food_count):
    if _deferred_catchup_bank_allowed(strategy, remaining):
        return True
    return _historical_freeze_may_run(strategy, remaining, food_count)


def _strongly_bankable_food(food_list, my_topo, en_topo):
    bankable = []
    for food in food_list:
        md = my_topo.distances.get(food, INF)
        ed = en_topo.distances.get(food, INF)
        close_to_us = md <= ENDGAME_BANK_MAX_MY_DISTANCE
        safely_far_from_enemy = ed == INF or ed >= md + ENDGAME_BANK_MIN_ENEMY_MARGIN
        if close_to_us and safely_far_from_enemy:
            bankable.append(food)
    return bankable


def _bank_penalty_for_reward(grid, food_list):
    reward_scale = max(1, min(9, current_food_reward(grid, food_list) // 100))
    cap = ENDGAME_BANK_CAP_PER_REWARD_SCALE * reward_scale
    return min(cap, ENDGAME_BANK_BASE_PENALTY * reward_scale)


def _apply_deferred_catchup_bank(penalties, candidates, bankable, grid, food_list):
    if not bankable:
        return False
    banked = set(bankable)
    penalty = _bank_penalty_for_reward(grid, food_list)
    active = False
    for name, npos in candidates:
        if npos in banked:
            penalties[name] = max(penalties.get(name, 0), penalty)
            active = True
    return active


def _freeze_strength_ok(bankable_count, safe_concede, enemy_urgent):
    strong_bank = bankable_count >= 2 and safe_concede >= 2
    strong_lead = safe_concede >= 3
    if not (strong_bank or strong_lead):
        return False
    return safe_concede >= enemy_urgent + 1


def _freeze_candidate_eligible(npos, food_set, bankable, en_topo):
    if npos not in food_set:
        return False
    if npos not in bankable:
        return False
    return en_topo.distances.get(npos, INF) >= APPLE_FREEZE_MIN_ENEMY_DISTANCE


def _freeze_penalty_value(bankable_count, safe_concede):
    penalty = APPLE_FREEZE_BASE_PENALTY
    if bankable_count >= 2:
        penalty += APPLE_FREEZE_EXTRA_BANKED
    if safe_concede >= 3:
        penalty += APPLE_FREEZE_EXTRA_BANKED
    return min(APPLE_FREEZE_CAP, penalty)


def _apply_freeze_penalties(penalties, candidates, food_set, bankable, en_topo, safe_concede):
    for name, npos in candidates:
        if _freeze_candidate_eligible(npos, food_set, bankable, en_topo):
            penalties[name] = _freeze_penalty_value(len(bankable), safe_concede)



def _zero_move_map(candidates):
    result = {}
    for name, _ in candidates:
        result[name] = 0
    return result


def _topology_for_body_or_empty(grid, body):
    if not body:
        return TopologyInfo(0, 0, False, False, {})
    return analyze_topology_consolidated(grid, body[0], len(body), body[-1])


def _new_freeze_stats(penalties):
    return {
        "enabled": True, "active": False, "bankable_food": 0,
        "enemy_urgent_food": 0, "deferred_catchup": False,
        "strategic_bank": False, "penalties": penalties.copy(),
    }


def _enemy_topology_for_targets(grid, en_body, food_list, collapse):
    """v6: con copias, el rival 'llega' a todas las copias cuando llega a la más cercana."""
    topo = _topology_for_body_or_empty(grid, en_body)
    if not collapse:
        return topo
    return TopologyInfo(
        topo.space, topo.exits, topo.tail_reachable, topo.pocket_trap,
        _effective_enemy_food_distances(topo.distances, food_list, True)
    )


def _freeze_context_or_none(grid, my_body, en_body, food_list, candidates,
                            strategy, fe_penalties, forced_trap_penalties, penalties):
    if not food_list or not my_body:
        return None
    remaining = strategy.get("remaining", 999)
    collapse = target_copies_mode(grid, food_list)
    # Varias copias del mismo dígito siguen siendo UNA sola comida estratégica.
    food_count = 1 if collapse else len(food_list)
    if not _bank_layer_may_run(strategy, remaining, food_count):
        return None
    food_set = set(food_list)
    safe_non_food = _safe_non_food_names(
        candidates, food_set, fe_penalties, forced_trap_penalties
    )
    if not safe_non_food:
        return None
    return {
        "remaining": remaining, "food_set": food_set,
        "safe_non_food": safe_non_food,
        "my_topo": _topology_for_body_or_empty(grid, my_body),
        "en_topo": _enemy_topology_for_targets(grid, en_body, food_list, collapse),
        "penalties": penalties,
        "food_count": food_count,
    }


def _try_deferred_catchup_bank(grid, food_list, candidates, strategy, ctx, stats):
    if not _deferred_catchup_bank_allowed(strategy, ctx["remaining"]):
        return False
    deferred = _strongly_bankable_food(food_list, ctx["my_topo"], ctx["en_topo"])
    active = _apply_deferred_catchup_bank(
        ctx["penalties"], candidates, deferred, grid, food_list
    )
    if not active:
        return False
    stats["active"] = True
    stats["strategic_bank"] = True
    stats["deferred_catchup"] = strategy.get("base_margin", 0) <= 0
    stats["bankable_food"] = len(deferred)
    stats["safe_non_food"] = list(ctx["safe_non_food"])
    stats["penalties"] = dict(ctx["penalties"])
    return True


def _apply_historical_lock_freeze(food_list, candidates, strategy, ctx, stats):
    if _apple_freeze_inactive(strategy, ctx["remaining"], ctx["food_count"]):
        return
    bankable, enemy_urgent = _classify_freeze_food(
        food_list, ctx["my_topo"], ctx["en_topo"]
    )
    stats["bankable_food"] = len(bankable)
    stats["enemy_urgent_food"] = enemy_urgent
    safe_concede = strategy.get("safe_concedable_apples", 0)
    if not _freeze_strength_ok(len(bankable), safe_concede, enemy_urgent):
        return
    _apply_freeze_penalties(
        ctx["penalties"], candidates, ctx["food_set"], bankable,
        ctx["en_topo"], safe_concede
    )
    stats["active"] = any(ctx["penalties"].values())
    stats["penalties"] = dict(ctx["penalties"])
    stats["safe_non_food"] = list(ctx["safe_non_food"])


def compute_apple_freeze_penalties(grid, my_body, en_body, food_list, candidates,
                                   strategy, fe_penalties, forced_trap_penalties):
    """Root banking for historical LOCK and late controlled catch-up food."""
    penalties = _zero_move_map(candidates)
    stats = _new_freeze_stats(penalties)
    ctx = _freeze_context_or_none(
        grid, my_body, en_body, food_list, candidates, strategy,
        fe_penalties, forced_trap_penalties, penalties
    )
    if ctx is None:
        return penalties, stats
    if _try_deferred_catchup_bank(grid, food_list, candidates, strategy, ctx, stats):
        return penalties, stats
    _apply_historical_lock_freeze(food_list, candidates, strategy, ctx, stats)
    return penalties, stats


def compute_strategy_root_adjustments(candidates, food_list, strategy):
    """Pequeña corrección de recambio cuando necesitamos remontar.

    La arena respawnea una manzana al comer; el Alpha-Beta determinista no.
    En TRAILING/DESPERATE damos un valor pequeño al acto de generar otra
    oportunidad. Nunca es comparable a una señal FE fatal.
    """
    food_set = set(food_list)
    mode = strategy.get("mode", "NORMAL")
    eat_bonus = DESPERATE_EAT_BONUS if mode == "DESPERATE" else (TRAILING_EAT_BONUS if mode == "TRAILING" else 0)
    return {name: (eat_bonus if npos in food_set else 0) for name, npos in candidates}


def _territory_base_weight(remaining):
    if remaining > TERRITORY_EARLY_REMAINING:
        return TERRITORY_BASE_EARLY
    if remaining > TERRITORY_LATE_REMAINING:
        return TERRITORY_BASE_MID
    return TERRITORY_BASE_LATE


def _territory_score_weight(weight, score_diff):
    if score_diff >= 100:
        return weight + TERRITORY_WIN_BONUS
    if score_diff <= -100:
        return max(0, weight - TERRITORY_LOSE_REDUCTION)
    return weight


def _territory_food_weight(weight, food_race_bonus, min_my_food_dist):
    actionable = (
        min_my_food_dist != INF
        and min_my_food_dist <= 5
        and abs(food_race_bonus) >= 1800
    )
    if actionable:
        return int(round(weight * TERRITORY_FOOD_SUPPRESS))
    return weight


def _territory_mode_weight(weight, strategy_mode):
    scales = {"DESPERATE": 0.0, "TRAILING": 0.35, "LOCK": 0.50}
    scale = scales.get(strategy_mode)
    if scale is None:
        return weight
    return int(round(weight * scale))


def compute_adaptive_territory_bonus(territory_delta, score_diff, remaining,
                                     food_race_bonus, min_my_food_dist,
                                     strategy_mode=None):
    weight = _territory_base_weight(remaining)
    weight = _territory_score_weight(weight, score_diff)
    weight = _territory_food_weight(weight, food_race_bonus, min_my_food_dist)
    weight = _territory_mode_weight(weight, strategy_mode)
    delta = max(-50, min(50, territory_delta))
    return max(-TERRITORY_CAP, min(TERRITORY_CAP, delta * weight))


def _evaluation_heads(my_body, en_body):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None
    return my_head, en_head


def _evaluation_tails(my_body, en_body):
    my_tail = my_body[-1] if my_body else None
    en_tail = en_body[-1] if en_body else None
    return my_tail, en_tail


def _missing_head_value(my_head, en_head):
    if not my_head:
        return -INF
    if not en_head:
        return INF
    return None


def _evaluation_topologies(grid, my_body, en_body, my_head, en_head):
    my_tail, en_tail = _evaluation_tails(my_body, en_body)
    my_topo = analyze_topology_consolidated(
        grid, my_head, len(my_body), my_tail
    )
    en_topo = analyze_topology_consolidated(
        grid, en_head, len(en_body), en_tail
    )
    return my_topo, en_topo


def _pocket_terminal_value(my_topo, en_topo):
    if my_topo.pocket_trap:
        return -500000 + my_topo.space * 100
    if en_topo.pocket_trap:
        return 500000 - en_topo.space * 100
    return None


POCKET_EVAL_SCALE = 400  # 500000 * 400 = 200M: debajo de TERMINAL_WIN_SCORE (900M)


def _pocket_scaled_value(pocket):
    """Conserva el orden original (-500000 + espacio*100) pero a escala de ±200M."""
    return pocket * POCKET_EVAL_SCALE


def _choke_bonus(grid, my_head, en_head, my_topo, en_topo):
    can_cut, door_pos, _ = analyze_corridor_chokepoints_opt(
        grid, my_head, en_head, en_topo, my_topo
    )
    if not can_cut or not door_pos:
        return 0
    distance = my_topo.distances.get(door_pos, INF)
    if distance == 0:
        return 350000
    if distance != INF:
        return 150000 - distance * 3000
    return 0


def _food_distance_contribution(my_distance, enemy_distance):
    if my_distance < enemy_distance:
        return 400 - my_distance * 12
    if enemy_distance < my_distance:
        return -(250 - enemy_distance * 8)
    if my_distance != INF:
        return 100 - my_distance * 8
    return 0


def _food_tempo(my_topo, en_topo, food_list, collapse=False):
    if collapse:
        # v6: una sola carrera por el dígito objetivo (copia más cercana de cada uno).
        my_distance = _min_food_distance(my_topo.distances, food_list)
        enemy_distance = _min_food_distance(en_topo.distances, food_list)
        score = _food_distance_contribution(my_distance, enemy_distance)
        if my_distance != INF:
            score += 200 - my_distance * 10
        return score, my_distance
    score = 0
    min_my_distance = INF
    for food in food_list:
        my_distance = my_topo.distances.get(food, INF)
        enemy_distance = en_topo.distances.get(food, INF)
        min_my_distance = min(min_my_distance, my_distance)
        score += _food_distance_contribution(my_distance, enemy_distance)
    if min_my_distance != INF:
        score += 200 - min_my_distance * 10
    return score, min_my_distance


def _x_pickup_positions(grid):
    return [
        (r, c)
        for r, row in enumerate(grid) if X_PICKUP in row
        for c, value in enumerate(row) if value == X_PICKUP
    ]


def _x_potential(distance, x_value, score_weight):
    """Valor parcial de una X que ganamos la carrera, decreciente con la distancia.

    Evita el efecto horizonte: sin esto, una X a 5 pasos 'no existe' para la búsqueda
    y el bot pagaba -500 (dígito equivocado) para llegar a ella en 3 pasos.
    Siempre < x_value completo, así que comerla sigue siendo mejor que rondarla.
    """
    if distance > X_POTENTIAL_RADIUS:
        return 0
    return int(x_value * score_weight * (X_POTENTIAL_DECAY ** distance))


def _x_pickup_tempo(grid, my_topo, en_topo, x_value, score_weight=500):
    """v4: valor de las X que alcanzamos primero menos las que alcanza primero el rival."""
    if x_value <= 0:
        return 0
    mine = 0
    theirs = 0
    for pos in _x_pickup_positions(grid):
        my_distance = my_topo.distances.get(pos, INF)
        enemy_distance = en_topo.distances.get(pos, INF)
        if my_distance < enemy_distance:
            mine = max(mine, _x_potential(my_distance, x_value, score_weight))
        elif enemy_distance < my_distance:
            theirs = max(theirs, _x_potential(enemy_distance, x_value, score_weight))
    return mine - theirs


def _body_is_player_a(grid, body):
    head = body[0]
    return grid[head[0]][head[1]] == "A"


def _territory_cell_owner(grid, pos, my_topo, en_topo):
    r, c = pos
    if grid[r][c] in {"#", "A", "B", "a", "b"}:
        return 0
    my_distance = my_topo.distances.get(pos, INF)
    enemy_distance = en_topo.distances.get(pos, INF)
    if my_distance < enemy_distance:
        return 1
    if enemy_distance < my_distance:
        return -1
    return 0


def _territory_delta(grid, my_topo, en_topo):
    delta = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            delta += _territory_cell_owner(grid, (r, c), my_topo, en_topo)
    return delta


def _territory_eval_bonus(grid, my_body, en_body, my_topo, en_topo,
                          score_diff, remaining, food_race_bonus,
                          min_my_food_dist, strategy):
    enabled = USE_ADAPTIVE_TERRITORY_V6
    long_enough = len(my_body) + len(en_body) >= TERRITORY_MIN_COMBINED_LENGTH
    if not enabled or not long_enough:
        return 0
    return compute_adaptive_territory_bonus(
        _territory_delta(grid, my_topo, en_topo),
        score_diff, remaining, food_race_bonus, min_my_food_dist,
        strategy.get("mode")
    )


def _final_evaluation_value(remaining, score_diff, base_score, food_tempo_score,
                            food_race_bonus, territory_bonus, mobility_score,
                            choke_bonus):
    if remaining < 30:
        if score_diff > 0:
            return base_score + territory_bonus + choke_bonus + mobility_score * 0 + 0
        return base_score + food_tempo_score * 4 + food_race_bonus * 2 + territory_bonus + choke_bonus
    if score_diff < -150:
        return base_score + food_tempo_score * 3 + int(food_race_bonus * 1.5) + territory_bonus + mobility_score + choke_bonus
    return base_score + food_tempo_score * 2 + food_race_bonus + territory_bonus + mobility_score + choke_bonus


def _late_leading_value(base_score, my_topo, territory_bonus, choke_bonus):
    return (
        base_score + my_topo.space * 50 + my_topo.exits * 250
        + territory_bonus + choke_bonus
    )


def _combine_evaluation(remaining, score_diff, base_score, food_tempo_score,
                        food_race_bonus, territory_bonus, mobility_score,
                        choke_bonus, my_topo):
    if remaining < 30 and score_diff > 0:
        return _late_leading_value(
            base_score, my_topo, territory_bonus, choke_bonus
        )
    return _final_evaluation_value(
        remaining, score_diff, base_score, food_tempo_score,
        food_race_bonus, territory_bonus, mobility_score, choke_bonus
    )


def _race_winner_probability(my_distance, enemy_distance, my_to_move):
    """(yo_gano, probabilidad) de la carrera por el número que toca."""
    i_win = my_distance < enemy_distance or (my_distance == enemy_distance and my_to_move)
    margin = abs(enemy_distance - my_distance)
    prob = min(RACE_P_MAX, RACE_P_BASE + RACE_P_PER_STEP * margin)
    return i_win, prob


def _race_expected_points(grid, my_topo, en_topo, food_list, my_mult, en_mult,
                          remaining, my_to_move):
    """Puntos esperados del número que toca: + si lo gano yo, - si lo gana el rival."""
    if not RACE_ENABLED or not food_list or remaining < RACE_MIN_REMAINING:
        return 0
    my_distance = _min_food_distance(my_topo.distances, food_list)
    enemy_distance = _min_food_distance(en_topo.distances, food_list)
    if my_distance == INF and enemy_distance == INF:
        return 0
    reward = current_food_reward(grid, food_list)
    i_win, prob = _race_winner_probability(
        min(my_distance, 99), min(enemy_distance, 99), my_to_move
    )
    if i_win and 2 * my_distance <= remaining:
        return int(RACE_WEIGHT * RACE_CLAIM_WEIGHT * prob * reward * my_mult)
    if not i_win and 2 * enemy_distance <= remaining:
        threat = -int(RACE_WEIGHT * prob * reward * en_mult)
        camp = _camp_expected_points(
            grid, my_topo, en_topo, food_list, reward, my_mult, enemy_distance, remaining
        )
        # esperar nunca puede valer más que ganar la carrera (si no, el bot se la regala)
        return min(0, threat + camp)
    return 0


def _next_digit_cells(grid, digit):
    return [
        pos for pos in DIGIT_CELLS.get(digit, ())
        if grid[pos[0]][pos[1]] == digit
    ]


def _camp_expected_points(grid, my_topo, en_topo, food_list, reward, my_mult,
                          enemy_distance, remaining):
    """Valor de esperar cerca del número que viene mientras el rival come el actual."""
    if not CAMP_ENABLED or reward <= 0:
        return 0
    enemy_spot = min(food_list, key=lambda pos: en_topo.distances.get(pos, INF))
    next_digit = str(reward // 100 % 9 + 1)
    best = None
    for pos in _next_digit_cells(grid, next_digit):
        my_distance = my_topo.distances.get(pos, INF)
        if my_distance == INF:
            continue
        enemy_after = abs(pos[0] - enemy_spot[0]) + abs(pos[1] - enemy_spot[1])
        my_after = max(1, my_distance - enemy_distance)
        advantage = enemy_after - my_after
        if advantage > 0 and (best is None or advantage > best):
            best = advantage
    if best is None or 2 * (enemy_distance + 1) > remaining:
        return 0
    prob = min(RACE_P_MAX, CAMP_P_BASE + CAMP_P_PER_STEP * best)
    return int(CAMP_WEIGHT * prob * (int(next_digit) * 100) * my_mult)


def evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining,
                      food_list, my_to_move=True):
    my_head, en_head = _evaluation_heads(my_body, en_body)
    missing = _missing_head_value(my_head, en_head)
    if missing is not None:
        return missing
    my_topo, en_topo = _evaluation_topologies(
        grid, my_body, en_body, my_head, en_head
    )
    score_diff = my_score - en_score
    my_is_a = _body_is_player_a(grid, my_body)
    my_mult = _multiplier_for(my_is_a)
    en_mult = _multiplier_for(not my_is_a)
    score_weight = 500 if remaining > 100 else 2500
    # v4: cada paso de multiplicador de ventaja vale puntos futuros estimados.
    x_value = multiplier_future_value(remaining)
    race = _race_expected_points(
        grid, my_topo, en_topo, food_list, my_mult, en_mult, remaining, my_to_move
    )
    base_score = (score_diff + (my_mult - en_mult) * x_value + race) * score_weight

    pocket = _pocket_terminal_value(my_topo, en_topo)
    if pocket is not None:
        # V8.1: antes devolvía ±500000 SIN el puntaje. Con multiplicadores (v4) el
        # puntaje llega a millones y encerrarse parecía mejor que un estado normal.
        # Ahora el bolsillo domina (±200M) pero conserva el puntaje como desempate.
        return _pocket_scaled_value(pocket) + base_score

    choke_bonus = _choke_bonus(grid, my_head, en_head, my_topo, en_topo)
    food_reward = current_food_reward(grid, food_list) * my_mult
    strategy = compute_strategy_state(
        my_score, en_score, remaining,
        my_to_move=my_to_move, food_reward=food_reward
    )
    collapse = target_copies_mode(grid, food_list)
    food_tempo_score, min_my_food_dist = _food_tempo(
        my_topo, en_topo, food_list, collapse
    )
    food_scale = max(1, min(9, food_reward // 100))
    food_tempo_score *= food_scale
    food_race_bonus = compute_food_race_bonus(
        my_topo, en_topo, food_list, reward_scale=food_scale, collapse=collapse
    )
    territory_bonus = _territory_eval_bonus(
        grid, my_body, en_body, my_topo, en_topo, score_diff,
        remaining, food_race_bonus, min_my_food_dist, strategy
    )
    mobility_score = my_topo.exits * 120 + min(my_topo.space, 40) * 8
    value = _combine_evaluation(
        remaining, score_diff, base_score, food_tempo_score,
        food_race_bonus, territory_bonus, mobility_score, choke_bonus,
        my_topo
    )
    return value + _x_pickup_tempo(grid, my_topo, en_topo, x_value, score_weight)

# =====================================================================
# 8. BÚSQUEDA ALPHA-BETA CON TRANSPOSITION TABLE EXACTA
# =====================================================================
def _ordering_topologies(grid, head, body, en_head, other_body):
    my_topo = analyze_topology_consolidated(
        grid, head, len(body), body[-1] if body else None
    )
    en_topo = analyze_topology_consolidated(
        grid, en_head, len(other_body), other_body[-1] if other_body else None
    )
    return my_topo, en_topo


def _food_manhattan_distance(npos, food_list):
    return min(
        (abs(npos[0] - food[0]) + abs(npos[1] - food[1]) for food in food_list),
        default=INF
    )


def _cut_priority(can_cut, door_pos, npos):
    return 100000 if can_cut and door_pos and npos == door_pos else None


def _food_priority(grid, npos, food_list):
    if npos not in food_list:
        return None
    reward = current_food_reward(grid, food_list)
    return 20000 * max(1, min(9, reward // 100))


def _move_priority_score(grid, npos, food_list, min_cur_food, can_cut, door_pos):
    cut = _cut_priority(can_cut, door_pos, npos)
    if cut is not None:
        return cut
    food = _food_priority(grid, npos, food_list)
    if food is not None:
        return food
    if wrong_numbered_food_at(grid, npos, food_list):
        return -250000
    if grid[npos[0]][npos[1]] == X_PICKUP:
        return X_ORDERING_PRIORITY
    closer = _food_manhattan_distance(npos, food_list) < min_cur_food
    return 5000 if closer else 0


def get_ordered_moves_v5(grid, head, body, other_body, food_list, en_head):
    moves = get_legal_moves_raw(grid, head, body, other_body)
    if not moves:
        return []
    my_topo, en_topo = _ordering_topologies(
        grid, head, body, en_head, other_body
    )
    can_cut, door_pos, _ = analyze_corridor_chokepoints_opt(
        grid, head, en_head, en_topo, my_topo
    )
    min_cur_food = min(
        (my_topo.distances.get(food, INF) for food in food_list),
        default=INF
    )
    key = lambda item: _move_priority_score(
        grid, item[1], food_list, min_cur_food, can_cut, door_pos
    )
    moves.sort(key=key, reverse=True)
    return moves

_NO_SEARCH_RESULT = object()


def _search_abort_result(deadline):
    global SEARCH_ABORTED, SEARCH_NODES
    SEARCH_NODES += 1
    if SEARCH_NODE_BUDGET is not None and SEARCH_NODES > SEARCH_NODE_BUDGET:
        SEARCH_ABORTED = True
        return 0
    if SEARCH_MODE == "time" and time.monotonic() >= deadline:
        SEARCH_ABORTED = True
        return 0
    return _NO_SEARCH_RESULT


def _score_terminal_by_points(my_score, en_score):
    if my_score > en_score:
        return TERMINAL_WIN_SCORE
    if my_score < en_score:
        return -TERMINAL_WIN_SCORE
    return 0


def _exact_terminal_result(my_body, en_body, my_score, en_score, remaining):
    if remaining <= 0:
        return _score_terminal_by_points(my_score, en_score)
    if not my_body:
        return -TERMINAL_WIN_SCORE - max(0, remaining)
    if not en_body:
        return TERMINAL_WIN_SCORE + max(0, remaining)
    return _NO_SEARCH_RESULT


def _search_state_hash(my_body, en_body, is_my_turn, food_list,
                       remaining, my_is_a, my_score, en_score):
    base = (
        tuple(my_body), tuple(en_body), is_my_turn,
        tuple(sorted(food_list)), remaining, my_is_a, my_score, en_score,
    )
    mults = (MULTIPLIERS[True], MULTIPLIERS[False])
    # Sin multiplicadores la clave queda igual que en V8.0 (la usa la auditoría histórica).
    return hash(base if mults == (1, 1) else base + mults)


def _tt_cutoff_score(entry, alpha, beta):
    score = entry["score"]
    flag = entry["flag"]
    if flag == TT_EXACT:
        return score
    cutoffs = {
        TT_LOWER: score >= beta,
        TT_UPPER: score <= alpha,
    }
    return score if cutoffs.get(flag, False) else _NO_SEARCH_RESULT


def _tt_probe(state_hash, depth, alpha, beta):
    entry = TT.get(state_hash)
    if entry is None:
        return _NO_SEARCH_RESULT
    if entry["depth"] < depth:
        return _NO_SEARCH_RESULT
    return _tt_cutoff_score(entry, alpha, beta)


def _no_moves_terminal_score(is_my_turn, remaining):
    if is_my_turn:
        return -TERMINAL_WIN_SCORE - max(0, remaining)
    return TERMINAL_WIN_SCORE + max(0, remaining)


def _leaf_result(grid, is_my_turn, my_body, en_body, my_score, en_score,
                 remaining, food_list):
    active = my_body if is_my_turn else en_body
    other = en_body if is_my_turn else my_body
    moves = get_legal_moves_raw(grid, active[0], active, other)
    if not moves:
        return _no_moves_terminal_score(is_my_turn, remaining)
    return evaluate_state_v5(
        grid, my_body, en_body, my_score, en_score,
        remaining, food_list, my_to_move=is_my_turn
    )


def _ordered_moves_for_turn(grid, is_my_turn, my_body, en_body, food_list):
    if is_my_turn:
        return get_ordered_moves_v5(
            grid, my_body[0], my_body, en_body, food_list,
            _enemy_head_from_body(en_body)
        )
    return get_ordered_moves_v5(
        grid, en_body[0], en_body, my_body, food_list,
        _enemy_head_from_body(my_body)
    )


def _recursive_move_context(grid, is_my_turn, my_body, en_body, npos,
                            my_is_a, my_score, en_score, food_list):
    if is_my_turn:
        undo = make_move(grid, my_body, npos, my_is_a, my_score, food_list)
        return my_body, my_is_a, undo, undo[4], en_score
    undo = make_move(grid, en_body, npos, not my_is_a, en_score, food_list)
    return en_body, not my_is_a, undo, my_score, undo[4]


def _undo_recursive_move(grid, active_body, actor_is_a, npos, food_list, undo):
    tail, prev_tail, prev_target, eaten, _, food_undo = undo
    unmake_move(
        grid, active_body, tail, prev_tail, prev_target, eaten,
        actor_is_a, npos, food_list, food_undo
    )


def _initial_search_best(is_my_turn):
    return -INF if is_my_turn else INF


def _update_search_bounds(is_my_turn, best, value, alpha, beta):
    if is_my_turn:
        best = max(best, value)
        return best, max(alpha, best), beta
    best = min(best, value)
    return best, alpha, min(beta, best)


def _tt_flag_for_result(best, orig_alpha, orig_beta):
    if best <= orig_alpha:
        return TT_UPPER
    if best >= orig_beta:
        return TT_LOWER
    return TT_EXACT


def _store_tt_result(state_hash, depth, best, orig_alpha, orig_beta):
    TT[state_hash] = {
        "score": best,
        "depth": depth,
        "flag": _tt_flag_for_result(best, orig_alpha, orig_beta),
    }


def _alpha_beta_expand(grid, depth, alpha, beta, is_my_turn, my_body, en_body,
                       deadline, my_score, en_score, remaining, food_list,
                       my_is_a, state_hash):
    moves = _ordered_moves_for_turn(grid, is_my_turn, my_body, en_body, food_list)
    if not moves:
        return _no_moves_terminal_score(is_my_turn, remaining)

    orig_alpha, orig_beta = alpha, beta
    best = _initial_search_best(is_my_turn)
    for _, npos in moves:
        active_body, actor_is_a, undo, next_my_score, next_en_score = _recursive_move_context(
            grid, is_my_turn, my_body, en_body, npos,
            my_is_a, my_score, en_score, food_list
        )
        value = alpha_beta(
            grid, depth - 1, alpha, beta, not is_my_turn,
            my_body, en_body, deadline, next_my_score, next_en_score,
            remaining - 1, food_list, my_is_a
        )
        _undo_recursive_move(grid, active_body, actor_is_a, npos, food_list, undo)
        if SEARCH_ABORTED:
            return 0
        best, alpha, beta = _update_search_bounds(
            is_my_turn, best, value, alpha, beta
        )
        if beta <= alpha:
            break

    _store_tt_result(state_hash, depth, best, orig_alpha, orig_beta)
    return best


def alpha_beta(grid, depth, alpha, beta, is_my_turn, my_body, en_body,
               deadline, my_score, en_score, remaining, food_list, my_is_a):
    aborted = _search_abort_result(deadline)
    if aborted is not _NO_SEARCH_RESULT:
        return aborted
    terminal = _exact_terminal_result(
        my_body, en_body, my_score, en_score, remaining
    )
    if terminal is not _NO_SEARCH_RESULT:
        return terminal
    state_hash = _search_state_hash(
        my_body, en_body, is_my_turn, food_list,
        remaining, my_is_a, my_score, en_score
    )
    cached = _tt_probe(state_hash, depth, alpha, beta)
    if cached is not _NO_SEARCH_RESULT:
        return cached
    if depth == 0:
        return _leaf_result(
            grid, is_my_turn, my_body, en_body, my_score, en_score,
            remaining, food_list
        )
    return _alpha_beta_expand(
        grid, depth, alpha, beta, is_my_turn, my_body, en_body,
        deadline, my_score, en_score, remaining, food_list, my_is_a,
        state_hash
    )

def _body_char_for_side(side):
    return "a" if is_a_side(side) else "b"


def _back_position(head, delta):
    dr, dc = delta
    return head[0] - dr, head[1] - dc


def _direction_matches_body(grid, head, delta, body_char):
    pos = _back_position(head, delta)
    return is_pos_inside(grid, pos) and grid[pos[0]][pos[1]] == body_char


def _get_current_direction(grid, head, side):
    if not head:
        return None
    body_char = _body_char_for_side(side)
    for name, delta in DIRECTIONS.items():
        if _direction_matches_body(grid, head, delta, body_char):
            return name
    return None

def _fallback_position(head, delta):
    return head[0] + delta[0], head[1] + delta[1]


def _fallback_food_bonus(distances, food_list):
    min_food = min((distances.get(food, INF) for food in food_list), default=INF)
    return 0 if min_food == INF else 200 - min_food * 5


def _fallback_candidate_score(grid, npos, my_body, food_list):
    space, exits, reach, trap, distances = analyze_topology(
        grid, npos, len(my_body), my_body[-1]
    )
    wrong_penalty = (
        200000 if wrong_numbered_food_at(grid, npos, food_list) else 0
    )
    return (
        space * 15 + exits * 60 + (1500 if reach else 0)
        - (10000 if trap else 0)
        + _fallback_food_bonus(distances, food_list)
        - wrong_penalty
    )


def _fallback_candidate_legal(grid, npos, my_body):
    if not is_pos_inside(grid, npos):
        return False
    return is_open_cell(grid[npos[0]][npos[1]]) or npos == my_body[-1]


def _wall_bump_direction(grid, head):
    """v5: chocar un # cuesta -500 pero NO mata; mejor que un choque letal."""
    for name, delta in DIRECTIONS.items():
        npos = _fallback_position(head, delta)
        if is_pos_inside(grid, npos) and grid[npos[0]][npos[1]] == WALL_CHAR:
            return name
    return None


def emergency_safety_fallback(grid, my_body, en_body, food_list):
    if not my_body:
        return "UP"
    best_dir, max_score = "UP", -INF
    for name, delta in DIRECTIONS.items():
        npos = _fallback_position(my_body[0], delta)
        if not _fallback_candidate_legal(grid, npos, my_body):
            continue
        score = _fallback_candidate_score(grid, npos, my_body, food_list)
        if score > max_score:
            best_dir, max_score = name, score
    if max_score == -INF:
        wall_dir = _wall_bump_direction(grid, my_body[0])
        if wall_dir is not None:
            return wall_dir
    return best_dir

def _anti_cycle_recent(history):
    recent = history.get("ac_recent_heads")
    if recent is None:
        recent = deque(maxlen=AC_HISTORY_SIZE)
        history["ac_recent_heads"] = recent
    return recent


def _anti_cycle_growth_update(history, body_len):
    last_len = history.get("ac_last_body_len")
    if last_len is None or body_len > last_len:
        history["ac_no_growth_turns"] = 0
    else:
        history["ac_no_growth_turns"] = history.get("ac_no_growth_turns", 0) + 1
    history["ac_last_body_len"] = body_len


def _update_anti_cycle_history(game_id, head, body_len):
    history = bot_histories.setdefault(
        game_id, {"my_path": deque(), "en_path": deque()}
    )
    recent = _anti_cycle_recent(history)
    is_new_turn = not recent or recent[-1] != head
    if is_new_turn:
        _anti_cycle_growth_update(history, body_len)
        recent.append(head)
    return list(recent), history.get("ac_no_growth_turns", 0)


def _cycle_repeat_count(seq, period, pattern):
    repeats = 1
    cursor = len(seq) - 2 * period
    while cursor >= 0 and seq[cursor:cursor + period] == pattern:
        repeats += 1
        cursor -= period
    return repeats


def _cycle_period_penalty(seq, period, no_growth_turns):
    if len(seq) < period * AC_MIN_REPEATS:
        return 0, 0
    pattern = seq[-period:]
    repeats = _cycle_repeat_count(seq, period, pattern)
    if repeats < AC_MIN_REPEATS:
        return 0, repeats
    if no_growth_turns + 1 < period * AC_MIN_REPEATS:
        return 0, repeats
    penalty = (
        AC_BASE_PENALTY
        + (repeats - AC_MIN_REPEATS) * AC_REPEAT_PENALTY
        + max(0, AC_MAX_PERIOD - period) * AC_SHORT_PERIOD_BONUS
    )
    return min(penalty, AC_PENALTY_CAP), repeats


def _better_cycle_result(best, penalty, period, repeats):
    best_penalty, best_period, best_repeats = best
    if penalty > best_penalty:
        return penalty, period, repeats
    return best_penalty, best_period, best_repeats


def _anti_cycle_penalty_for_candidate(recent_heads, candidate_pos, no_growth_turns):
    if candidate_pos is None or no_growth_turns < AC_MIN_NO_GROWTH_TURNS:
        return 0, None, 0
    seq = list(recent_heads) + [candidate_pos]
    best = (0, None, 0)
    for period in range(2, AC_MAX_PERIOD + 1):
        penalty, repeats = _cycle_period_penalty(seq, period, no_growth_turns)
        best = _better_cycle_result(best, penalty, period, repeats)
    return best


def compute_anti_cycle_penalties(game_id, head, body_len, candidates, enabled=True):
    global LAST_AC_STATS
    recent, no_growth = _update_anti_cycle_history(game_id, head, body_len)

    if not enabled:
        LAST_AC_STATS = {
            'enabled': False, 'no_growth_turns': no_growth,
            'penalties': {}, 'periods': {}, 'repeats': {}
        }
        return {}

    penalties = {}
    periods = {}
    repeats_map = {}
    for move_name, npos in candidates:
        penalty, period, repeats = _anti_cycle_penalty_for_candidate(
            recent, npos, no_growth
        )
        penalties[move_name] = penalty
        if period is not None:
            periods[move_name] = period
            repeats_map[move_name] = repeats

    LAST_AC_STATS = {
        'enabled': True,
        'no_growth_turns': no_growth,
        'history_len': len(recent),
        'penalties': dict(penalties),
        'periods': periods,
        'repeats': repeats_map,
    }
    return penalties


def _fe_gate_scale(body_len, remaining, score_diff):
    scale = (
        FE_SAFETY_GATE_SCALE_VERY_LONG
        if body_len >= 14 else FE_SAFETY_GATE_SCALE_LONG
    )
    if remaining <= 100:
        scale += 1
    if score_diff <= -300:
        scale = max(3, scale - 1)
    return scale


def _scaled_fe_risk(risk, scale):
    if risk <= 0:
        return 0
    if risk >= FE_FATAL_RISK:
        return risk
    return min(FE_FATAL_RISK, risk * scale)


def strengthen_root_fe_penalties(penalties, body_len, remaining, score_diff):
    if not penalties or body_len < FE_SAFETY_GATE_MIN_LENGTH:
        return dict(penalties)
    if min(penalties.values(), default=0) != 0:
        return dict(penalties)
    scale = _fe_gate_scale(body_len, remaining, score_diff)
    return {
        move: _scaled_fe_risk(risk, scale)
        for move, risk in penalties.items()
    }



def _hard_deadline_reached(hard_deadline):
    return hard_deadline is not None and time.monotonic() >= hard_deadline


def _corridor_forced_after_enemy_move(grid, my_body, en_body, food_list, my_is_a,
                                      en_pos, rounds_left, stats, hard_deadline):
    enemy_undo = make_move(grid, en_body, en_pos, not my_is_a, 0, food_list)
    try:
        my_moves = get_legal_moves_raw(grid, my_body[0], my_body, en_body)
        if not my_moves:
            return True
        if len(my_moves) > 1:
            return False
        my_pos = my_moves[0][1]
        my_undo = make_move(grid, my_body, my_pos, my_is_a, 0, food_list)
        try:
            return _enemy_can_force_corridor_death(
                grid, my_body, en_body, food_list, my_is_a,
                rounds_left - 1, stats, hard_deadline
            )
        finally:
            unmake_move(
                grid, my_body, my_undo[0], my_undo[1], my_undo[2], my_undo[3],
                my_is_a, my_pos, food_list, my_undo[5]
            )
    finally:
        unmake_move(
            grid, en_body, enemy_undo[0], enemy_undo[1], enemy_undo[2], enemy_undo[3],
            not my_is_a, en_pos, food_list, enemy_undo[5]
        )



def _corridor_probe_invalid(rounds_left, en_body):
    return rounds_left <= 0 or not en_body


def _enemy_corridor_moves_force(grid, my_body, en_body, food_list, my_is_a,
                                enemy_moves, rounds_left, stats, hard_deadline):
    for _, en_pos in enemy_moves:
        stats['nodes'] += 1
        if _corridor_forced_after_enemy_move(
            grid, my_body, en_body, food_list, my_is_a,
            en_pos, rounds_left, stats, hard_deadline
        ):
            return True
    return False


def _enemy_can_force_corridor_death(grid, my_body, en_body, food_list, my_is_a,
                                    rounds_left, stats, hard_deadline=None):
    """True si el rival puede encadenar una muerte mientras nosotros solo tengamos 0/1 respuesta."""
    if _hard_deadline_reached(hard_deadline):
        stats['aborted'] = True
        return False
    if _corridor_probe_invalid(rounds_left, en_body):
        return False
    enemy_moves = get_legal_moves_raw(grid, en_body[0], en_body, my_body)
    if not enemy_moves:
        return False
    return _enemy_corridor_moves_force(
        grid, my_body, en_body, food_list, my_is_a,
        enemy_moves, rounds_left, stats, hard_deadline
    )



def _forced_trap_candidate_penalty(grid, my_body, en_body, food_list, my_is_a,
                                   npos, max_rounds, stats, hard_deadline):
    undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
    try:
        forced = _enemy_can_force_corridor_death(
            grid, my_body, en_body, food_list, my_is_a,
            max_rounds, stats, hard_deadline
        )
        return FORCED_TRAP_FATAL_PENALTY if forced else 0
    finally:
        unmake_move(
            grid, my_body, undo[0], undo[1], undo[2], undo[3],
            my_is_a, npos, food_list, undo[5]
        )


def _collect_forced_trap_penalties(grid, my_body, en_body, food_list, my_is_a,
                                   candidates, max_rounds, stats, hard_deadline):
    penalties = {}
    for move_name, npos in candidates:
        if _hard_deadline_reached(hard_deadline):
            stats['aborted'] = True
            penalties.setdefault(move_name, 0)
            continue
        penalties[move_name] = _forced_trap_candidate_penalty(
            grid, my_body, en_body, food_list, my_is_a,
            npos, max_rounds, stats, hard_deadline
        )
    return penalties


def compute_forced_trap_penalties(grid, my_body, en_body, food_list, my_is_a, candidates,
                                  max_rounds=FORCED_TRAP_MAX_ROUNDS, hard_deadline=None):
    """Penalización raíz binaria: fatal solo si el rival puede mantenernos sin elección hasta morir."""
    original = _state_snapshot(grid, my_body, en_body, food_list)
    stats = {'nodes': 0, 'aborted': False}
    penalties = _collect_forced_trap_penalties(
        grid, my_body, en_body, food_list, my_is_a,
        candidates, max_rounds, stats, hard_deadline
    )
    if not _state_matches_snapshot(original, grid, my_body, en_body, food_list):
        raise AssertionError("Forced Trap Probe rompió la reversibilidad del estado")
    return penalties, stats




def _edge_distance(grid, pos):
    """Distancia a un borde real del tablero ya sin las barras `|` del frame."""
    if not pos or not grid or not grid[0]:
        return INF
    r, c = pos
    max_r = len(grid) - 1
    max_c = len(grid[0]) - 1
    return min(r, max_r - r, c, max_c - c)



def _tactical_critical_mobility(my_moves, en_moves):
    return len(my_moves) <= 1 or len(en_moves) <= 1


def _tactical_late_large(remaining, combined_len):
    return remaining <= TACTICAL_ACTIVE_REMAINING and combined_len >= 24


def _tactical_any_compressed(my_moves, en_moves):
    return len(my_moves) <= 2 or len(en_moves) <= 2


def _tactical_close_contact(head_dist, combined_len, my_moves, en_moves):
    if head_dist > TACTICAL_HEAD_DISTANCE:
        return False
    if combined_len < 14:
        return False
    return _tactical_any_compressed(my_moves, en_moves)


def _tactical_edge_pressure(edge, head_dist, combined_len, my_moves, en_moves):
    if edge > 1:
        return False
    if head_dist > max(6, TACTICAL_HEAD_DISTANCE):
        return False
    if combined_len < 16:
        return False
    return _tactical_any_compressed(my_moves, en_moves)


def _tactical_solver_should_run(grid, my_body, en_body, remaining):
    if not my_body or not en_body:
        return False
    my_moves = get_legal_moves_raw(grid, my_body[0], my_body, en_body)
    en_moves = get_legal_moves_raw(grid, en_body[0], en_body, my_body)
    head_dist = abs(my_body[0][0] - en_body[0][0]) + abs(my_body[0][1] - en_body[0][1])
    edge = min(_edge_distance(grid, my_body[0]), _edge_distance(grid, en_body[0]))
    combined_len = len(my_body) + len(en_body)
    checks = (
        _tactical_critical_mobility(my_moves, en_moves),
        _tactical_late_large(remaining, combined_len),
        _tactical_close_contact(head_dist, combined_len, my_moves, en_moves),
        _tactical_edge_pressure(edge, head_dist, combined_len, my_moves, en_moves),
    )
    return any(checks)



def _tactical_budget_exhausted(deadline, stats):
    return stats['nodes'] >= TACTICAL_SOLVER_NODE_BUDGET or time.monotonic() >= deadline


def _tactical_order_moves(grid, moving_body, my_body, en_body, food_list,
                          moving_is_a, target_is_my, forcing_turn, moves):
    ordered = []
    for name, pos in moves:
        undo = make_move(grid, moving_body, pos, moving_is_a, 0, food_list)
        try:
            victim = my_body if target_is_my else en_body
            attacker = en_body if target_is_my else my_body
            vm = get_legal_moves_raw(grid, victim[0], victim, attacker) if victim else []
            ordered.append((len(vm), name, pos))
        finally:
            unmake_move(
                grid, moving_body, undo[0], undo[1], undo[2], undo[3],
                moving_is_a, pos, food_list, undo[5]
            )
    ordered.sort(key=lambda x: x[0], reverse=not forcing_turn)
    return ordered


def _tactical_child_after_move(grid, moving_body, pos, moving_is_a, my_body, en_body,
                               food_list, my_is_a, turn_is_my, target_is_my,
                               plies_left, deadline, stats, memo):
    undo = make_move(grid, moving_body, pos, moving_is_a, 0, food_list)
    try:
        return _force_target_death(
            grid, my_body, en_body, food_list, my_is_a,
            not turn_is_my, target_is_my, plies_left - 1,
            deadline, stats, memo
        )
    finally:
        unmake_move(
            grid, moving_body, undo[0], undo[1], undo[2], undo[3],
            moving_is_a, pos, food_list, undo[5]
        )


def _tactical_child_resolution(forcing_turn, child):
    if child is None:
        return False, None, True
    if forcing_turn:
        return child is True, True, False
    return child is False, False, False


def _search_tactical_ordered(grid, moving_body, my_body, en_body, food_list,
                             moving_is_a, my_is_a, turn_is_my, target_is_my,
                             plies_left, deadline, stats, memo, ordered, forcing_turn):
    saw_unknown = False
    for _, _, pos in ordered:
        if _tactical_budget_exhausted(deadline, stats):
            stats['aborted'] = True
            saw_unknown = True
            break
        stats['nodes'] += 1
        child = _tactical_child_after_move(
            grid, moving_body, pos, moving_is_a, my_body, en_body,
            food_list, my_is_a, turn_is_my, target_is_my,
            plies_left, deadline, stats, memo
        )
        resolved, value, unknown = _tactical_child_resolution(forcing_turn, child)
        saw_unknown = saw_unknown or unknown
        if resolved:
            return value, saw_unknown
    return None, saw_unknown


def _tactical_unresolved_result(forcing_turn, saw_unknown):
    if saw_unknown:
        return None
    return False if forcing_turn else True



def _tactical_turn_bodies(my_body, en_body, turn_is_my):
    if turn_is_my:
        return my_body, en_body
    return en_body, my_body


def _tactical_moves_for_body(grid, moving_body, other_body):
    if not moving_body:
        return []
    return get_legal_moves_raw(grid, moving_body[0], moving_body, other_body)


def _tactical_moving_is_a(my_is_a, turn_is_my):
    if turn_is_my:
        return my_is_a
    return not my_is_a


def _tactical_store_result(memo, key, result):
    if result is not None:
        memo[key] = result
    return result



def _tactical_finalize_search(memo, key, resolved, forcing_turn, saw_unknown):
    if resolved is not None:
        return _tactical_store_result(memo, key, resolved)
    result = _tactical_unresolved_result(forcing_turn, saw_unknown)
    return _tactical_store_result(memo, key, result)


def _force_target_death(grid, my_body, en_body, food_list, my_is_a,
                        turn_is_my, target_is_my, plies_left,
                        deadline, stats, memo):
    """Minimax booleano con cuantificadores exactos."""
    if _tactical_budget_exhausted(deadline, stats):
        stats['aborted'] = True
        return None
    moving_body, other_body = _tactical_turn_bodies(my_body, en_body, turn_is_my)
    moves = _tactical_moves_for_body(grid, moving_body, other_body)
    if not moves:
        return turn_is_my == target_is_my
    if plies_left <= 0:
        return False
    key = (tuple(my_body), tuple(en_body), tuple(sorted(food_list)), turn_is_my, target_is_my, plies_left)
    if key in memo:
        return memo[key]
    forcing_turn = turn_is_my != target_is_my
    moving_is_a = _tactical_moving_is_a(my_is_a, turn_is_my)
    ordered = _tactical_order_moves(
        grid, moving_body, my_body, en_body, food_list,
        moving_is_a, target_is_my, forcing_turn, moves
    )
    resolved, saw_unknown = _search_tactical_ordered(
        grid, moving_body, my_body, en_body, food_list, moving_is_a,
        my_is_a, turn_is_my, target_is_my, plies_left, deadline,
        stats, memo, ordered, forcing_turn
    )
    return _tactical_finalize_search(memo, key, resolved, forcing_turn, saw_unknown)



def _new_tactical_stats():
    return {
        'enabled': False, 'nodes': 0, 'aborted': False,
        'forced_losses': [], 'forced_wins': [], 'elapsed_ms': 0.0,
        'defense_nodes': 0, 'offense_nodes': 0,
    }


def _run_tactical_defense(grid, my_body, en_body, food_list, my_is_a,
                          candidates, local_deadline, stats, loss_penalties):
    memo = {}
    for move_name, npos in candidates:
        if _tactical_budget_exhausted(local_deadline, stats):
            stats['aborted'] = True
            break
        undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
        before_nodes = stats['nodes']
        try:
            enemy_forces_us = _force_target_death(
                grid, my_body, en_body, food_list, my_is_a,
                False, True, TACTICAL_SOLVER_MAX_PLIES,
                local_deadline, stats, memo
            )
            if enemy_forces_us is True:
                loss_penalties[move_name] = TACTICAL_FORCED_LOSS_PENALTY
                stats['forced_losses'].append(move_name)
        finally:
            stats['defense_nodes'] += stats['nodes'] - before_nodes
            unmake_move(
                grid, my_body, undo[0], undo[1], undo[2], undo[3],
                my_is_a, npos, food_list, undo[5]
            )


def _tactical_offense_promising(my_body, en_body, enemy_moves):
    if not en_body:
        return False
    head_dist = abs(my_body[0][0] - en_body[0][0]) + abs(my_body[0][1] - en_body[0][1])
    return len(enemy_moves) <= 2 or head_dist <= 4


def _run_tactical_offense_candidate(grid, my_body, en_body, food_list, my_is_a,
                                    move_name, npos, offense_deadline, stats,
                                    memo, win_bonuses):
    undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
    before_nodes = stats['nodes']
    try:
        enemy_moves = get_legal_moves_raw(grid, en_body[0], en_body, my_body) if en_body else []
        if not _tactical_offense_promising(my_body, en_body, enemy_moves):
            return
        we_force_enemy = _force_target_death(
            grid, my_body, en_body, food_list, my_is_a,
            False, False, TACTICAL_OFFENSE_MAX_PLIES,
            offense_deadline, stats, memo
        )
        if we_force_enemy is True:
            win_bonuses[move_name] = TACTICAL_FORCED_WIN_BONUS
            stats['forced_wins'].append(move_name)
    finally:
        stats['offense_nodes'] += stats['nodes'] - before_nodes
        unmake_move(
            grid, my_body, undo[0], undo[1], undo[2], undo[3],
            my_is_a, npos, food_list, undo[5]
        )


def _run_tactical_offense(grid, my_body, en_body, food_list, my_is_a,
                          candidates, offense_deadline, stats,
                          loss_penalties, win_bonuses):
    memo = {}
    for move_name, npos in candidates:
        if loss_penalties.get(move_name, 0) > 0:
            continue
        if _tactical_budget_exhausted(offense_deadline, stats):
            break
        _run_tactical_offense_candidate(
            grid, my_body, en_body, food_list, my_is_a,
            move_name, npos, offense_deadline, stats, memo, win_bonuses
        )



def _tactical_local_deadline(deterministic, global_deadline, start):
    if deterministic:
        return float('inf')
    return min(global_deadline, start + TACTICAL_SOLVER_TIME_BUDGET)


def _tactical_offense_deadline(deterministic, local_deadline):
    if deterministic:
        return local_deadline
    return min(local_deadline, time.monotonic() + TACTICAL_OFFENSE_TIME_BUDGET)


def compute_tactical_trap_scores(grid, my_body, en_body, food_list, my_is_a,
                                 candidates, remaining, global_deadline, deterministic=False):
    """Prueba raíz selectiva para pérdidas/ganancias forzadas por encierro."""
    zero = _zero_move_map(candidates)
    stats = _new_tactical_stats()
    if not _tactical_solver_should_run(grid, my_body, en_body, remaining):
        return zero, zero.copy(), stats
    start = time.monotonic()
    local_deadline = _tactical_local_deadline(deterministic, global_deadline, start)
    stats['enabled'] = True
    loss_penalties, win_bonuses = zero.copy(), zero.copy()
    original = _state_snapshot(grid, my_body, en_body, food_list)
    _run_tactical_defense(
        grid, my_body, en_body, food_list, my_is_a,
        candidates, local_deadline, stats, loss_penalties
    )
    offense_deadline = _tactical_offense_deadline(deterministic, local_deadline)
    if time.monotonic() < offense_deadline:
        _run_tactical_offense(
            grid, my_body, en_body, food_list, my_is_a,
            candidates, offense_deadline, stats, loss_penalties, win_bonuses
        )
    stats['elapsed_ms'] = (time.monotonic() - start) * 1000.0
    if not _state_matches_snapshot(original, grid, my_body, en_body, food_list):
        raise AssertionError('Tactical Trap Solver rompió la reversibilidad')
    return loss_penalties, win_bonuses, stats



def _unit_step(delta):
    if delta > 0:
        return 1
    if delta < 0:
        return -1
    return 0


def _straight_delta(start, food):
    sr, sc = start
    fr, fc = food
    if sr == fr:
        return 0, _unit_step(fc - sc)
    if sc == fc:
        return _unit_step(fr - sr), 0
    return None



def _straight_food_value(grid, pos, dist):
    if is_food_symbol(grid[pos[0]][pos[1]]):
        return dist
    return INF


def _straight_cell_blocked(grid, pos):
    if not is_pos_inside(grid, pos):
        return True
    # v4: pasar por una X en el camino es gratis (incluso suma), no bloquea.
    return grid[pos[0]][pos[1]] not in (' ', X_PICKUP)


def _walk_straight_food(grid, start, food, dr, dc, dist):
    r, c = start
    for _ in range(dist):
        r += dr
        c += dc
        pos = (r, c)
        if pos == food:
            return _straight_food_value(grid, pos, dist)
        if _straight_cell_blocked(grid, pos):
            return INF
    return INF


def _clear_straight_food_distance(grid, start, food):
    """Distancia si food está en línea recta y el corredor está libre."""
    delta = _straight_delta(start, food)
    if delta is None:
        return INF
    dist = abs(food[0] - start[0]) + abs(food[1] - start[1])
    if dist <= 0:
        return 0
    return _walk_straight_food(grid, start, food, delta[0], delta[1], dist)



def _safe_food_root_blocked(name, fe_penalties, tactical_losses, tactical_wins):
    return (
        tactical_losses.get(name, 0) > 0
        or fe_penalties.get(name, 0) > 0
        or tactical_wins.get(name, 0) > 0
    )


def _safe_food_race_is_finite(distance, enemy_distance):
    if distance == INF:
        return False
    return enemy_distance != INF


def _same_real_edge_lane(grid, my_head, food):
    if _edge_distance(grid, my_head) != 0:
        return False
    return _edge_distance(grid, food) == 0


def _short_shadowable_race(distance, enemy_distance):
    if distance > 3:
        return False
    return enemy_distance <= distance + 3


def _safe_food_edge_shadow_risk(grid, my_head, food, distance, enemy_distance):
    """True for the real Candela-style edge lane that Safe Food must not boost."""
    if not _safe_food_race_is_finite(distance, enemy_distance):
        return False
    if not _same_real_edge_lane(grid, my_head, food):
        return False
    return _short_shadowable_race(distance, enemy_distance)


def _safe_food_tuple(grid, my_head, food, enemy_distances):
    distance = _clear_straight_food_distance(grid, my_head, food)
    if distance == INF or distance > SAFE_FOOD_MAX_STEPS - 1:
        return None
    enemy_distance = enemy_distances.get(food, INF)
    if distance >= enemy_distance:
        return None
    if _safe_food_edge_shadow_risk(grid, my_head, food, distance, enemy_distance):
        return None
    return distance, enemy_distance, food



def _enemy_food_distances(grid, en_body):
    if not en_body:
        return {}
    return bfs_distances(grid, en_body[0], en_body[-1])


def _food_candidate_is_better(candidate, best):
    if best is None:
        return True
    return candidate < best


def _best_safe_food_after_root(grid, my_head, en_body, food_list):
    enemy_distances = _effective_enemy_food_distances(
        _enemy_food_distances(grid, en_body), food_list,
        target_copies_mode(grid, food_list)
    )
    best = None
    for food in food_list:
        candidate = _safe_food_tuple(grid, my_head, food, enemy_distances)
        if candidate is None:
            continue
        if _food_candidate_is_better(candidate, best):
            best = candidate
    return best


def _safe_food_path_adjustment(grid, my_body, en_body, food_list, my_is_a, npos):
    undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
    try:
        best = _best_safe_food_after_root(grid, my_body[0], en_body, food_list)
        if best is None:
            return 0, None
        distance, enemy_distance, food = best
        bonus = SAFE_FOOD_PATH_BONUS + max(0, SAFE_FOOD_MAX_STEPS - distance) * SAFE_FOOD_STEP_BONUS
        detail = {
            'food': food, 'distance_after_root': distance,
            'enemy_distance': enemy_distance, 'immediate': False,
        }
        return bonus, detail
    finally:
        unmake_move(
            grid, my_body, undo[0], undo[1], undo[2], undo[3],
            my_is_a, npos, food_list, undo[5]
        )


def _safe_food_candidate_adjustment(grid, my_body, en_body, food_list, my_is_a,
                                    name, npos, lock_freeze_window,
                                    fe_penalties, tactical_losses, tactical_wins):
    if _safe_food_root_blocked(name, fe_penalties, tactical_losses, tactical_wins):
        return 0, None
    if npos in food_list:
        if lock_freeze_window:
            return 0, None
        return SAFE_FOOD_IMMEDIATE_BONUS, {
            'food': npos, 'distance_after_root': 0, 'immediate': True,
        }
    return _safe_food_path_adjustment(grid, my_body, en_body, food_list, my_is_a, npos)



def _missing_safe_food_inputs(food_list, my_body):
    return not food_list or not my_body


def _safe_food_lock_window(strategy):
    return (
        strategy.get('mode') == 'LOCK'
        and strategy.get('remaining', 300) > APPLE_BANK_CASHOUT_REMAINING
    )


def _apply_safe_food_candidates(grid, my_body, en_body, food_list, my_is_a,
                                candidates, lock_freeze_window, fe_penalties,
                                tactical_losses, tactical_wins, out, details):
    for name, npos in candidates:
        bonus, detail = _safe_food_candidate_adjustment(
            grid, my_body, en_body, food_list, my_is_a,
            name, npos, lock_freeze_window,
            fe_penalties, tactical_losses, tactical_wins
        )
        out[name] = bonus
        if detail is not None:
            details[name] = detail


def compute_safe_food_opportunity_adjustments(grid, my_body, en_body, food_list,
                                               my_is_a, candidates, strategy,
                                               fe_penalties, tactical_losses,
                                               tactical_wins):
    """Bonus raíz solo hacia comida cercana, recta, ganable y no fatal."""
    out = _zero_move_map(candidates)
    details = {}
    if _missing_safe_food_inputs(food_list, my_body):
        return out, details
    _apply_safe_food_candidates(
        grid, my_body, en_body, food_list, my_is_a, candidates,
        _safe_food_lock_window(strategy), fe_penalties,
        tactical_losses, tactical_wins, out, details
    )
    return out, details

def _decision_deadline(search_mode):
    start_time = time.monotonic()
    deadline = start_time + max(0.001, DEADLINE_TIMEOUT - DEADLINE_MARGIN_SECONDS)
    if search_mode in {"nodes", "fixed_depth"}:
        return float("inf"), True
    return deadline, False


def _reset_search_state(search_mode, node_budget):
    global TT, SEARCH_ABORTED, SEARCH_NODES, SEARCH_NODE_BUDGET, SEARCH_MODE
    SEARCH_MODE = search_mode
    SEARCH_NODE_BUDGET = int(node_budget) if search_mode == "nodes" else None
    SEARCH_NODES = 0
    TT.clear()
    SEARCH_ABORTED = False


def _scores_for_side(game_data, my_is_a):
    if my_is_a:
        return game_data.get("score_1", 0), game_data.get("score_2", 0)
    return game_data.get("score_2", 0), game_data.get("score_1", 0)


def _enemy_head_from_body(en_body):
    return en_body[0] if en_body else None


def _build_turn_context(game_data, use_ac):
    global LAST_STRATEGY_STATS
    load_multipliers(game_data)
    grid = adapt_new_rules(parse_turn_board(game_data), game_data)
    side = game_data.get("side", "A")
    game_id = game_data.get("game_id", "default")
    my_body, en_body = get_bodies(game_id, grid, side)
    if not my_body:
        return None

    my_is_a = is_a_side(side)
    my_score, en_score = _scores_for_side(game_data, my_is_a)
    remaining = game_data.get("remaining_moves", 300)
    food_list = find_food(grid)
    DIGIT_CELLS.clear()
    DIGIT_CELLS.update(_numbered_food_positions(grid))
    food_reward = current_food_reward(grid, food_list) * _multiplier_for(my_is_a)
    strategy = compute_strategy_state(
        my_score, en_score, remaining, my_to_move=True, food_reward=food_reward
    )
    LAST_STRATEGY_STATS = dict(strategy)
    current_dir = _get_current_direction(grid, my_body[0], side)
    candidates = get_ordered_moves_v5(
        grid, my_body[0], my_body, en_body, food_list, _enemy_head_from_body(en_body)
    )
    ac_penalties = compute_anti_cycle_penalties(
        game_id, my_body[0], len(my_body), candidates, enabled=use_ac
    )
    ac_penalties = _strategy_adjust_anti_cycle_penalties(ac_penalties, strategy)
    return {
        "grid": grid, "side": side, "game_id": game_id,
        "my_body": my_body, "en_body": en_body, "my_is_a": my_is_a,
        "my_score": my_score, "en_score": en_score, "remaining": remaining,
        "food_list": food_list, "strategy": strategy, "current_dir": current_dir,
        "candidates": candidates, "ac_penalties": ac_penalties,
    }


def _early_root_decision(ctx, use_fe):
    global LAST_FE_STATS
    candidates = ctx["candidates"]
    if not candidates:
        LAST_FE_STATS = {"enabled": use_fe, "nodes": 0, "elapsed_ms": 0.0, "penalties": {}}
        return emergency_safety_fallback(
            ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"]
        )
    if len(candidates) == 1:
        move = candidates[0][0]
        LAST_FE_STATS = {"enabled": use_fe, "nodes": 0, "elapsed_ms": 0.0, "penalties": {move: 0}}
        return move
    return None


def _future_escape_layer(ctx, use_fe, deadline, deterministic):
    global LAST_FE_STATS
    if not use_fe:
        LAST_FE_STATS = {"enabled": False, "nodes": 0, "elapsed_ms": 0.0, "penalties": {}}
        return {}
    penalties = compute_future_escape_penalties(
        ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"],
        ctx["my_is_a"], ctx["candidates"], deadline, deterministic=deterministic
    )
    return strengthen_root_fe_penalties(
        penalties, len(ctx["my_body"]), ctx["remaining"], ctx["my_score"] - ctx["en_score"]
    )


def _zero_move_map(candidates):
    return {name: 0 for name, _ in candidates}


def _forced_trap_layer(ctx, use_fe, deadline, deterministic):
    if not use_fe:
        return _zero_move_map(ctx["candidates"]), {"nodes": 0}
    hard_deadline = None if deterministic else deadline
    return compute_forced_trap_penalties(
        ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"],
        ctx["my_is_a"], ctx["candidates"], hard_deadline=hard_deadline
    )


def _time_expired(search_mode, deadline):
    return search_mode == "time" and time.monotonic() >= deadline


def _node_budget_expired(search_mode):
    return (
        search_mode == "nodes"
        and SEARCH_NODE_BUDGET is not None
        and SEARCH_NODES >= SEARCH_NODE_BUDGET
    )


def _search_budget_expired(search_mode, deadline):
    return _time_expired(search_mode, deadline) or _node_budget_expired(search_mode)


def _safe_food_layer(ctx, fe_penalties, tactical_loss, tactical_win, search_mode, deadline):
    if _time_expired(search_mode, deadline):
        return _zero_move_map(ctx["candidates"]), {}
    return compute_safe_food_opportunity_adjustments(
        ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"],
        ctx["my_is_a"], ctx["candidates"], ctx["strategy"],
        fe_penalties, tactical_loss, tactical_win
    )


def _freeze_disabled_stats(penalties, grid):
    reason = "disabled_or_deadline"
    return {
        "enabled": False, "active": False, "penalties": dict(penalties),
        "reason": reason,
    }


def _apple_freeze_layer(ctx, use_apple_freeze, fe_penalties, forced_penalties, search_mode, deadline):
    # food_list is already target-only in v3, so banking is safe to evaluate there too.
    effective = use_apple_freeze
    can_run = not _time_expired(search_mode, deadline)
    if effective and can_run:
        penalties, stats = compute_apple_freeze_penalties(
            ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"],
            ctx["candidates"], ctx["strategy"], fe_penalties, forced_penalties
        )
        return effective, penalties, stats
    penalties = _zero_move_map(ctx["candidates"])
    return effective, penalties, _freeze_disabled_stats(penalties, ctx["grid"])


def _strategy_adjustments_layer(ctx, search_mode, deadline):
    if _time_expired(search_mode, deadline):
        return _zero_move_map(ctx["candidates"])
    return compute_strategy_root_adjustments(
        ctx["candidates"], ctx["food_list"], ctx["strategy"]
    )


def _record_root_stats(ctx, freeze_stats, strategy_adjustments, forced_stats,
                       tactical_stats, safe_adjustments, safe_details):
    global LAST_STRATEGY_STATS
    LAST_STRATEGY_STATS = dict(ctx["strategy"])
    LAST_STRATEGY_STATS.update({
        "apple_freeze": freeze_stats,
        "root_adjustments": dict(strategy_adjustments),
        "anti_cycle_penalties": dict(ctx["ac_penalties"]),
        "forced_trap_nodes": forced_stats.get("nodes", 0),
        "tactical": tactical_stats,
        "safe_food_adjustments": dict(safe_adjustments),
        "safe_food_details": safe_details,
        "multipliers": {
            "mine": _multiplier_for(ctx["my_is_a"]),
            "enemy": _multiplier_for(not ctx["my_is_a"]),
        },
    })


def _build_root_layers(ctx, use_fe, use_apple_freeze, search_mode, deadline, deterministic):
    fe_penalties = _future_escape_layer(ctx, use_fe, deadline, deterministic)
    forced_penalties, forced_stats = _forced_trap_layer(
        ctx, use_fe, deadline, deterministic
    )
    tactical_loss, tactical_win, tactical_stats = compute_tactical_trap_scores(
        ctx["grid"], ctx["my_body"], ctx["en_body"], ctx["food_list"],
        ctx["my_is_a"], ctx["candidates"], ctx["remaining"], deadline,
        deterministic=deterministic
    )
    safe_adjustments, safe_details = _safe_food_layer(
        ctx, fe_penalties, tactical_loss, tactical_win, search_mode, deadline
    )
    effective_freeze, freeze_penalties, freeze_stats = _apple_freeze_layer(
        ctx, use_apple_freeze, fe_penalties, forced_penalties, search_mode, deadline
    )
    strategy_adjustments = _strategy_adjustments_layer(ctx, search_mode, deadline)
    _record_root_stats(
        ctx, freeze_stats, strategy_adjustments, forced_stats,
        tactical_stats, safe_adjustments, safe_details
    )
    return {
        "fe": fe_penalties, "forced": forced_penalties,
        "tactical_loss": tactical_loss, "tactical_win": tactical_win,
        "safe": safe_adjustments, "freeze": freeze_penalties,
        "strategy": strategy_adjustments, "effective_freeze": effective_freeze,
    }


def _adjust_root_score(score, move_name, layers, use_fe, use_ac, ac_penalties):
    if use_fe:
        score -= layers["fe"].get(move_name, 0)
        score -= layers["forced"].get(move_name, 0)
    score -= layers["tactical_loss"].get(move_name, 0)
    score += layers["tactical_win"].get(move_name, 0)
    score += layers["safe"].get(move_name, 0)
    if use_ac:
        score -= ac_penalties.get(move_name, 0)
    score += layers["strategy"].get(move_name, 0)
    if layers["effective_freeze"]:
        score -= layers["freeze"].get(move_name, 0)
    return score


def _evaluate_root_move(ctx, move_name, npos, depth, deadline, layers, use_fe, use_ac):
    tail, prev_tail, prev_target, eaten, next_score, food_undo = make_move(
        ctx["grid"], ctx["my_body"], npos, ctx["my_is_a"],
        ctx["my_score"], ctx["food_list"]
    )
    score = alpha_beta(
        ctx["grid"], depth - 1, -INF, INF, False,
        ctx["my_body"], ctx["en_body"], deadline,
        next_score, ctx["en_score"], ctx["remaining"] - 1,
        ctx["food_list"], ctx["my_is_a"]
    )
    score = _adjust_root_score(
        score, move_name, layers, use_fe, use_ac, ctx["ac_penalties"]
    )
    unmake_move(
        ctx["grid"], ctx["my_body"], tail, prev_tail, prev_target, eaten,
        ctx["my_is_a"], npos, ctx["food_list"], food_undo
    )
    return score


def _prefer_root_move(score, best_score, move_name, current_dir):
    return score > best_score or (score == best_score and move_name == current_dir)


def _search_depth_layer(ctx, depth, best_move, deadline, layers, use_fe, use_ac, search_mode):
    global SEARCH_ABORTED
    SEARCH_ABORTED = False
    layer_best_move = best_move
    layer_best_score = -INF
    for move_name, npos in ctx["candidates"]:
        if _search_budget_expired(search_mode, deadline):
            SEARCH_ABORTED = True
            break
        score = _evaluate_root_move(
            ctx, move_name, npos, depth, deadline, layers, use_fe, use_ac
        )
        if SEARCH_ABORTED:
            break
        if _prefer_root_move(score, layer_best_score, move_name, ctx["current_dir"]):
            layer_best_score = score
            layer_best_move = move_name
    return layer_best_move


def _iterative_root_search(ctx, deadline, layers, use_fe, use_ac, search_mode, fixed_depth):
    best_move = ctx["candidates"][0][0]
    depth = 1
    max_depth = fixed_depth if search_mode == "fixed_depth" else 12
    while depth <= max_depth:
        if _search_budget_expired(search_mode, deadline):
            break
        layer_best_move = _search_depth_layer(
            ctx, depth, best_move, deadline, layers, use_fe, use_ac, search_mode
        )
        if SEARCH_ABORTED:
            break
        best_move = layer_best_move
        ctx["candidates"].sort(key=lambda item: item[0] == best_move, reverse=True)
        depth += 1
    return best_move


def _candidate_position(candidates, move_name):
    return next((pos for name, pos in candidates if name == move_name), None)


def _position_is_trap(grid, pos, body):
    return analyze_topology(grid, pos, len(body), body[-1])[3]


def _nontrap_alternative(ctx, best_move, search_mode, deadline):
    for alt_name, alt_pos in ctx["candidates"]:
        if _time_expired(search_mode, deadline):
            return None
        if alt_name == best_move:
            continue
        if not _position_is_trap(ctx["grid"], alt_pos, ctx["my_body"]):
            return alt_name
    return None


def _final_root_safety(ctx, best_move, search_mode, deadline):
    chosen_pos = _candidate_position(ctx["candidates"], best_move)
    if chosen_pos is None or _time_expired(search_mode, deadline):
        return best_move
    if not _position_is_trap(ctx["grid"], chosen_pos, ctx["my_body"]):
        return best_move
    alternative = _nontrap_alternative(ctx, best_move, search_mode, deadline)
    return alternative if alternative is not None else best_move


def choose_direction(game_data, use_fe=USE_FUTURE_ESCAPE_DEFAULT, use_ac=USE_ANTI_CYCLE_DEFAULT,
                     use_apple_freeze=USE_APPLE_FREEZE_DEFAULT, search_mode="time",
                     node_budget=12000, fixed_depth=6):
    deadline, deterministic = _decision_deadline(search_mode)
    _reset_search_state(search_mode, node_budget)
    ctx = _build_turn_context(game_data, use_ac)
    if ctx is None:
        return "UP"
    early = _early_root_decision(ctx, use_fe)
    if early is not None:
        return early
    layers = _build_root_layers(
        ctx, use_fe, use_apple_freeze, search_mode, deadline, deterministic
    )
    best_move = _iterative_root_search(
        ctx, deadline, layers, use_fe, use_ac, search_mode, fixed_depth
    )
    return _final_root_safety(ctx, best_move, search_mode, deadline)

# =====================================================================
# ENTRYPOINT MINIMO: la conexion vive en snake_runtime.py
# =====================================================================
def main():
    from snake_runtime import run_client
    run_client(choose_direction, parse_turn_board, is_a_side, FOOD_DIGITS)


if __name__ == "__main__":
    main()