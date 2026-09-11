import sys
import time
import json
import asyncio
import threading
from collections import deque
import pygame
import websockets

# =====================================================================
# 1. CONFIGURACIÓN GENERAL Y CONSTANTES
# =====================================================================
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
GLOBAL_HUD_HEIGHT = 50
FPS = 30

DEADLINE_TIMEOUT = 0.080  # 80ms para cálculo seguro tolerando latencia de red
INF = 10**9
TERMINAL_WIN_SCORE = 900_000_000  # muerte decide la partida; domina cualquier heurística

# Future Escape v1: capa aislada de seguridad futura.
USE_FUTURE_ESCAPE_DEFAULT = True
FE_HORIZON = 2              # rival responde + nuestra siguiente jugada
FE_TIME_BUDGET = 0.008      # máximo ~8 ms dentro del mismo deadline total de 80 ms
FE_NODE_BUDGET = 450        # límite duro de estados FE por decisión
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
# Un movimiento normal vale +1 y comer vale +100: cada manzana aporta +99
# respecto del turno normal. El controlador calcula cuántas manzanas NETAS
# necesitamos/concedemos si ambos sobreviven hasta el límite.
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
AC_HISTORY_SIZE = 32
AC_MAX_PERIOD = 8
AC_MIN_REPEATS = 2
AC_MIN_NO_GROWTH_TURNS = 8
AC_BASE_PENALTY = 9000
AC_REPEAT_PENALTY = 3500
AC_SHORT_PERIOD_BONUS = 1200
AC_PENALTY_CAP = 30000

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

# Estado visual multi-partida
visual_state = {
    "status": "Conectando al servidor...",
    "games": {}
}
visual_lock = threading.Lock()

# Historiales exactos por partida
bot_histories = {}
TT = {}
SEARCH_ABORTED = False
LAST_FE_STATS = {}
LAST_AC_STATS = {}
LAST_STRATEGY_STATS = {}

# =====================================================================
# 2. SINCRONIZACIÓN VISUAL
# =====================================================================
def update_visual_game_state(game_id, grid, side, my_name, enemy_name, my_score, enemy_score, remaining_moves):
    with visual_lock:
        visual_state["games"][game_id] = {
            "grid": grid,
            "my_side": str(side),
            "my_name": my_name,
            "enemy_name": enemy_name,
            "my_score": my_score,
            "enemy_score": enemy_score,
            "remaining_moves": remaining_moves,
            "game_over": False,
            "winner": None,
            "last_updated": time.time()
        }

def update_visual_game_over(game_id, s1, s2):
    with visual_lock:
        if game_id and game_id in visual_state["games"]:
            g = visual_state["games"][game_id]
            g["game_over"] = True
            is_a = g["my_side"] in {"A", "1"}
            g["my_score"] = s1 if is_a else s2
            g["enemy_score"] = s2 if is_a else s1
            
            if g["my_score"] > g["enemy_score"]:
                g["winner"] = f"{g['my_name']} (Ganador)"
            elif g["enemy_score"] > g["my_score"]:
                g["winner"] = f"{g['enemy_name']} (Ganador)"
            else:
                g["winner"] = "Empate"

def set_global_status(text):
    with visual_lock:
        visual_state["status"] = text

# =====================================================================
# 3. PARSEO Y UTILIDADES BASE
# =====================================================================
def _parse_board_str(board_str):
    lines = board_str.replace("\r", "").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return [list(line.replace("|", "#")) for line in lines]

def parse_board(board_raw):
    if isinstance(board_raw, str):
        return _parse_board_str(board_raw)
    return [list(row) for row in board_raw]

def _find_cell_with_targets(grid, targets):
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in targets:
                return (r, c)
    return None

def find_head(grid, side):
    return _find_cell_with_targets(grid, {"A", "1"} if str(side) in {"A", "1"} else {"B", "2"})

def find_enemy_head(grid, side):
    return _find_cell_with_targets(grid, {"B", "2"} if str(side) in {"A", "1"} else {"A", "1"})

def find_food(grid):
    return [(r, c) for r, row in enumerate(grid) for c, val in enumerate(row) if val == "*"]

def is_pos_inside(grid, pos):
    if not grid or not pos:
        return False
    return 0 <= pos[0] < len(grid) and 0 <= pos[1] < len(grid[0])

# =====================================================================
# 4. RASTREO ROBUSTO DE CUERPOS (StateTracker)
# =====================================================================
def _trace_full_snake(grid, head, body_char):
    """Reconstruye head->tail cubriendo todas las celdas si es posible.

    En estados auto-adyacentes la geometría puede admitir más de un orden válido;
    sin historial no existe forma de saber cuál fue el orden real. Este resync
    busca una ruta completa determinista y solo cae al greedy histórico si no
    encuentra una ruta completa dentro del presupuesto de exploración.
    """
    expected_len = 1 + sum(row.count(body_char) for row in grid)
    if expected_len <= 1:
        return deque([head])

    path = [head]
    visited = {head}
    nodes = 0
    NODE_BUDGET = 50000

    def candidates(curr):
        out = []
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if npos in visited or not is_pos_inside(grid, npos):
                continue
            if grid[npos[0]][npos[1]] != body_char:
                continue
            # Warnsdorff: probar primero la celda con menos continuaciones.
            degree = 0
            for dr2, dc2 in DIRECTIONS.values():
                q = (npos[0] + dr2, npos[1] + dc2)
                if q not in visited and is_pos_inside(grid, q) and grid[q[0]][q[1]] == body_char:
                    degree += 1
            out.append((degree, npos))
        out.sort(key=lambda x: x[0])
        return [p for _, p in out]

    def dfs(curr):
        nonlocal nodes
        nodes += 1
        if nodes > NODE_BUDGET:
            return False
        if len(path) == expected_len:
            return True
        for npos in candidates(curr):
            visited.add(npos)
            path.append(npos)
            if dfs(npos):
                return True
            path.pop()
            visited.remove(npos)
        return False

    if dfs(head):
        return deque(reversed(path))  # formato histórico interno: tail -> head

    # Fallback compatible con V5; no se presenta como reconstrucción exacta.
    greedy = [head]
    curr = head
    seen = {head}
    while True:
        nxt = None
        for dr, dc in DIRECTIONS.values():
            q = (curr[0] + dr, curr[1] + dc)
            if q not in seen and is_pos_inside(grid, q) and grid[q[0]][q[1]] == body_char:
                nxt = q
                break
        if nxt is None:
            break
        greedy.append(nxt)
        seen.add(nxt)
        curr = nxt
    return deque(reversed(greedy))

def get_bodies(game_id, grid, side):
    head_my = find_head(grid, side)
    head_en = find_enemy_head(grid, side)
    
    is_p1 = str(side) in {"A", "1"}
    my_target = {"A", "1", "a"} if is_p1 else {"B", "2", "b"}
    en_target = {"B", "2", "b"} if is_p1 else {"A", "1", "a"}
    
    my_cells = sum(row.count(ch) for row in grid for ch in my_target)
    en_cells = sum(row.count(ch) for row in grid for ch in en_target)
    
    if game_id not in bot_histories:
        bot_histories[game_id] = {
            "my_path": deque(),
            "en_path": deque()
        }
        
    history = bot_histories[game_id]
        
    if head_my and (not history["my_path"] or history["my_path"][-1] != head_my):
        history["my_path"].append(head_my)
    if head_en and (not history["en_path"] or history["en_path"][-1] != head_en):
        history["en_path"].append(head_en)
        
    if len(history["my_path"]) < my_cells and head_my:
        history["my_path"] = _trace_full_snake(grid, head_my, "a" if is_p1 else "b")
    if len(history["en_path"]) < en_cells and head_en:
        history["en_path"] = _trace_full_snake(grid, head_en, "b" if is_p1 else "a")
        
    while len(history["my_path"]) > my_cells:
        history["my_path"].popleft()
    while len(history["en_path"]) > en_cells:
        history["en_path"].popleft()
    
    return deque(reversed(history["my_path"])), deque(reversed(history["en_path"]))

# =====================================================================
# 5. TOPOLOGÍA, CORREDORES Y DISTANCIAS BFS REALES
# =====================================================================
def bfs_distances(grid, start_pos, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos):
        return {}
    queue = deque([start_pos])
    distances = {start_pos: 0}
    
    while queue:
        curr = queue.popleft()
        d = distances[curr]
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if not is_pos_inside(grid, npos):
                continue
            cell = grid[npos[0]][npos[1]]
            if (cell in {" ", "*"} or npos == tail_pos) and npos not in distances:
                distances[npos] = d + 1
                queue.append(npos)
    return distances

def get_legal_moves_raw(grid, head, body, other_body):
    moves = []
    if not head:
        return moves
        
    tail_my = body[-1] if len(body) > 0 else None
    
    for name, (dr, dc) in DIRECTIONS.items():
        npos = (head[0] + dr, head[1] + dc)
        if not is_pos_inside(grid, npos):
            continue
            
        val = grid[npos[0]][npos[1]]
        if val in {" ", "*"}:
            moves.append((name, npos))
        elif npos == tail_my and val != "*":
            moves.append((name, npos))
    return moves

def analyze_topology(grid, start_pos, my_len, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos):
        return 0, 0, False, False, {}

    distances = bfs_distances(grid, start_pos, tail_pos)
    space = len(distances)
    
    effective_exits = 0
    for dr, dc in DIRECTIONS.values():
        npos = (start_pos[0] + dr, start_pos[1] + dc)
        if is_pos_inside(grid, npos):
            cell = grid[npos[0]][npos[1]]
            if cell in {" ", "*"} or npos == tail_pos:
                effective_exits += 1

    tail_reachable = (tail_pos in distances) if tail_pos else False
    is_pocket_trap = (space <= my_len + 1) and not tail_reachable
    
    return space, effective_exits, tail_reachable, is_pocket_trap, distances

def analyze_corridor_chokepoints(grid, my_head, en_head, my_body, en_body):
    """Identifica cuellos de botella y puertas usando BFS real."""
    if not en_head or not my_head:
        return False, None, False
        
    en_tail = en_body[-1] if en_body else None
    my_tail = my_body[-1] if my_body else None
    
    en_space, en_exits, en_tail_reach, en_trap, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    my_dists = bfs_distances(grid, my_head, my_tail)
    
    if en_exits <= 2 and en_space < (len(grid) * len(grid[0]) // 2):
        for pos, dist_en in en_dists.items():
            open_connections = 0
            for dr, dc in DIRECTIONS.values():
                npos = (pos[0] + dr, pos[1] + dc)
                if is_pos_inside(grid, npos) and grid[npos[0]][npos[1]] in {" ", "*"} and npos not in en_dists:
                    open_connections += 1
                    
            if open_connections >= 2:
                dist_my = my_dists.get(pos, INF)
                if dist_my <= dist_en and dist_my != INF:
                    return True, pos, True
                    
    return False, None, False

class TopologyInfo:
    __slots__ = ('space', 'exits', 'tail_reachable', 'pocket_trap', 'distances')

    def __init__(self, space, exits, tail_reachable, pocket_trap, distances):
        self.space = space
        self.exits = exits
        self.tail_reachable = tail_reachable
        self.pocket_trap = pocket_trap
        self.distances = distances


def analyze_topology_consolidated(grid, start_pos, my_len, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos):
        return TopologyInfo(0, 0, False, False, {})

    distances = {start_pos: 0}
    queue = deque([start_pos])
    while queue:
        curr = queue.popleft()
        d = distances[curr]
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if not is_pos_inside(grid, npos):
                continue
            if (grid[npos[0]][npos[1]] in {" ", "*"} or npos == tail_pos) and npos not in distances:
                distances[npos] = d + 1
                queue.append(npos)

    space = len(distances)
    exits = 0
    for dr, dc in DIRECTIONS.values():
        npos = (start_pos[0] + dr, start_pos[1] + dc)
        if is_pos_inside(grid, npos):
            if grid[npos[0]][npos[1]] in {" ", "*"} or npos == tail_pos:
                exits += 1

    tail_reachable = (tail_pos in distances) if tail_pos else False
    pocket_trap = (space <= my_len + 1) and not tail_reachable
    return TopologyInfo(space, exits, tail_reachable, pocket_trap, distances)


def analyze_corridor_chokepoints_opt(grid, my_head, en_head, en_topo, my_topo):
    if not en_head or not my_head:
        return False, None, False

    if en_topo.exits <= 2 and en_topo.space < (len(grid) * len(grid[0]) // 2):
        for pos, dist_en in en_topo.distances.items():
            open_connections = 0
            for dr, dc in DIRECTIONS.values():
                npos = (pos[0] + dr, pos[1] + dc)
                if (
                    is_pos_inside(grid, npos)
                    and grid[npos[0]][npos[1]] in {" ", "*"}
                    and npos not in en_topo.distances
                ):
                    open_connections += 1
            if open_connections >= 2:
                dist_my = my_topo.distances.get(pos, INF)
                if dist_my <= dist_en and dist_my != INF:
                    return True, pos, True
    return False, None, False

# =====================================================================
# 6. SIMULADOR EXACTO DE ESTADOS (O(1))
# =====================================================================
def make_move(grid, body, next_pos, is_player_a, current_score, food_list):
    head_char = "A" if is_player_a else "B"
    body_char = "a" if is_player_a else "b"
    eaten_food = (grid[next_pos[0]][next_pos[1]] == "*")

    tail_pos = None
    prev_tail_char = None
    food_idx = -1

    if not eaten_food and len(body) > 0:
        tail_pos = body.pop()
        prev_tail_char = grid[tail_pos[0]][tail_pos[1]]
        grid[tail_pos[0]][tail_pos[1]] = " "

    prev_target_char = grid[next_pos[0]][next_pos[1]]

    if len(body) > 0:
        old_head = body[0]
        grid[old_head[0]][old_head[1]] = body_char

    grid[next_pos[0]][next_pos[1]] = head_char
    body.appendleft(next_pos)

    if eaten_food:
        # La arena otorga +100 al comer (sin +1 adicional en ese mismo turno).
        current_score += 100
        if next_pos in food_list:
            food_idx = food_list.index(next_pos)
            food_list.pop(food_idx)
    else:
        # Movimiento sobrevivido normal: +1, igual que la arena/servidor local.
        current_score += 1

    return tail_pos, prev_tail_char, prev_target_char, eaten_food, current_score, food_idx

def unmake_move(grid, body, tail_pos, prev_tail_char, prev_target_char,
                eaten_food, is_player_a, next_pos, food_list, food_idx):
    head_char = "A" if is_player_a else "B"

    old_head = body.popleft()
    grid[old_head[0]][old_head[1]] = prev_target_char

    if len(body) > 0:
        new_head = body[0]
        grid[new_head[0]][new_head[1]] = head_char

    if not eaten_food and tail_pos:
        body.append(tail_pos)
        grid[tail_pos[0]][tail_pos[1]] = prev_tail_char

    # Restaurar en el índice original mantiene reversibilidad y determinismo.
    if eaten_food and food_idx != -1:
        food_list.insert(food_idx, next_pos)

# =====================================================================
# 6B. FUTURE ESCAPE V1 (aislado del Alpha-Beta principal)
# =====================================================================
def _future_escape_state_risk(grid, my_body, en_body, food_list, terminal_if_no_moves=True):
    """Riesgo geométrico actual para NUESTRA serpiente.

    `terminal_if_no_moves` solo debe ser True cuando realmente corresponde
    evaluar nuestra capacidad de mover (nuestro turno o una hoja FE). En turno
    rival, una celda puede liberarse antes de que nos toque mover.
    """
    if not my_body:
        return FE_FATAL_RISK

    my_head = my_body[0]
    my_tail = my_body[-1] if my_body else None
    legal = get_legal_moves_raw(grid, my_head, my_body, en_body)
    if terminal_if_no_moves and not legal:
        return FE_FATAL_RISK

    topo = analyze_topology_consolidated(grid, my_head, len(my_body), my_tail)

    risk = 0
    if topo.exits == 0:
        # Sin salida es terminal solo si toca/termina de evaluarse nuestro movimiento.
        risk = FE_FATAL_RISK if terminal_if_no_moves else FE_POCKET_RISK
    margin = topo.space - len(my_body)

    if topo.pocket_trap:
        risk = max(risk, FE_POCKET_RISK + max(0, 2 - margin) * 10000)

    # Una sola salida no es una muerte: solo una señal de fragilidad.
    if topo.exits == 1:
        risk = max(risk, FE_SINGLE_EXIT_RISK)

    # Poco espacio sin acceso a la cola es el patrón que más interesa a FE.
    if not topo.tail_reachable:
        if margin <= 1:
            risk = max(risk, FE_TIGHT_RISK + 50000)
        elif margin <= 3:
            risk = max(risk, FE_TIGHT_RISK)
        elif margin <= 6:
            risk = max(risk, 35000)

    return risk


def future_escape_risk(grid, my_body, en_body, food_list, my_is_a,
                       depth, is_my_turn, deadline, stats, memo):
    """Minimax pequeño de riesgo: nosotros minimizamos riesgo, rival lo maximiza.

    El objetivo es detectar autoencierro/movilidad futura mala, no reemplazar
    el evaluador estratégico principal. Si se agota el presupuesto, devuelve
    solo el riesgo observable del estado actual (fallback conservador).
    """
    stats['nodes'] += 1

    # En una hoja queremos saber si, desde ese estado, tendremos movilidad real.
    if depth <= 0:
        return _future_escape_state_risk(
            grid, my_body, en_body, food_list, terminal_if_no_moves=True
        )

    # En nodos internos no declaramos muerte solo porque AHORA no podamos mover:
    # si es turno rival, su movimiento puede liberar una celda antes de nuestro turno.
    current_risk = _future_escape_state_risk(
        grid, my_body, en_body, food_list, terminal_if_no_moves=is_my_turn
    )
    if is_my_turn and current_risk >= FE_FATAL_RISK:
        return current_risk
    if time.monotonic() >= deadline or stats['nodes'] >= FE_NODE_BUDGET:
        stats['aborted'] = True
        return current_risk

    key = (
        tuple(my_body), tuple(en_body), tuple(sorted(food_list)),
        depth, is_my_turn, my_is_a
    )
    cached = memo.get(key)
    if cached is not None:
        return max(current_risk, cached)

    if is_my_turn:
        moves = get_legal_moves_raw(
            grid, my_body[0], my_body, en_body
        )
        if not moves:
            return FE_FATAL_RISK

        best_risk = FE_FATAL_RISK
        for _, npos in moves:
            if time.monotonic() >= deadline or stats['nodes'] >= FE_NODE_BUDGET:
                stats['aborted'] = True
                break
            undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
            child = future_escape_risk(
                grid, my_body, en_body, food_list, my_is_a,
                depth - 1, False, deadline, stats, memo
            )
            unmake_move(
                grid, my_body, undo[0], undo[1], undo[2], undo[3],
                my_is_a, npos, food_list, undo[5]
            )
            best_risk = min(best_risk, max(current_risk, child))
            if best_risk == 0:
                break

        if best_risk == FE_FATAL_RISK and stats['aborted']:
            best_risk = current_risk
        result = best_risk
    else:
        # Si el rival no puede moverse, no penalizamos nuestra raíz por FE:
        # el Alpha-Beta principal es quien valora la ventaja táctica de la muerte rival.
        moves = get_legal_moves_raw(
            grid, en_body[0], en_body, my_body
        ) if en_body else []
        if not moves:
            return 0

        # El riesgo previo al movimiento rival no se arrastra automáticamente:
        # su movimiento puede liberar una celda. Evaluamos el peor estado DESPUÉS
        # de que el rival haya respondido.
        worst_risk = 0
        explored = False
        for _, npos in moves:
            if time.monotonic() >= deadline or stats['nodes'] >= FE_NODE_BUDGET:
                stats['aborted'] = True
                break
            explored = True
            undo = make_move(grid, en_body, npos, not my_is_a, 0, food_list)
            child = future_escape_risk(
                grid, my_body, en_body, food_list, my_is_a,
                depth - 1, True, deadline, stats, memo
            )
            unmake_move(
                grid, en_body, undo[0], undo[1], undo[2], undo[3],
                not my_is_a, npos, food_list, undo[5]
            )
            worst_risk = max(worst_risk, child)
            if worst_risk >= FE_FATAL_RISK:
                break

        result = worst_risk if explored else current_risk

    memo[key] = result
    return result


def compute_future_escape_penalties(grid, my_body, en_body, food_list,
                                    my_is_a, candidates, overall_deadline,
                                    horizon=FE_HORIZON):
    """Calcula una penalización FE por candidato raíz, una sola vez por turno."""
    global LAST_FE_STATS
    start = time.monotonic()
    fe_deadline = min(overall_deadline, start + FE_TIME_BUDGET)
    stats = {'nodes': 0, 'aborted': False}
    memo = {}
    penalties = {}

    # Snapshot para detectar cualquier rotura de reversibilidad dentro de FE.
    original_grid = tuple(tuple(row) for row in grid)
    original_my = tuple(my_body)
    original_en = tuple(en_body)
    original_food = tuple(food_list)

    for move_name, npos in candidates:
        if time.monotonic() >= fe_deadline or stats['nodes'] >= FE_NODE_BUDGET:
            stats['aborted'] = True
            penalties.setdefault(move_name, 0)
            continue

        undo = make_move(grid, my_body, npos, my_is_a, 0, food_list)
        penalties[move_name] = future_escape_risk(
            grid, my_body, en_body, food_list, my_is_a,
            horizon, False, fe_deadline, stats, memo
        )
        unmake_move(
            grid, my_body, undo[0], undo[1], undo[2], undo[3],
            my_is_a, npos, food_list, undo[5]
        )

    # Si FE agotó presupuesto, descartamos TODA la capa para este turno.
    # Así el orden de candidatos nunca puede sesgar la decisión por una evaluación parcial.
    if stats['aborted']:
        penalties = {move_name: 0 for move_name, _ in candidates}
    else:
        for move_name, _ in candidates:
            penalties.setdefault(move_name, 0)

    reversible = (
        tuple(tuple(row) for row in grid) == original_grid
        and tuple(my_body) == original_my
        and tuple(en_body) == original_en
        and tuple(food_list) == original_food
    )
    if not reversible:
        raise AssertionError("Future Escape rompió la reversibilidad del estado")

    LAST_FE_STATS = {
        'enabled': True,
        'nodes': stats['nodes'],
        'aborted': stats['aborted'],
        'elapsed_ms': (time.monotonic() - start) * 1000.0,
        'penalties': dict(penalties),
        'horizon': horizon,
        'reversible': reversible,
        'applied': not stats['aborted'],
    }
    return penalties

# =====================================================================
# 7. FOOD RACE V1 + EVALUADOR TÁCTICO
# =====================================================================
def compute_food_race_bonus(my_topo, en_topo, food_list):
    """Valor focal de carrera por comida sin BFS adicionales.

    No intenta sumar tres objetivos con el mismo peso. Prioriza la mejor
    manzana que podemos reclamar y la amenaza más urgente del rival.
    Un valor positivo favorece nuestra carrera; negativo indica comida
    que probablemente estamos regalando.
    """
    if not food_list:
        return 0

    claims = []
    threats = []

    for food in food_list:
        md = my_topo.distances.get(food, INF)
        ed = en_topo.distances.get(food, INF)

        if md == INF and ed == INF:
            continue

        if md < ed:
            dist = min(md, FOOD_RACE_MAX_DISTANCE)
            margin = FOOD_RACE_MAX_DISTANCE if ed == INF else min(ed - md, 6)
            value = (
                FOOD_RACE_BASE
                + max(0, FOOD_RACE_MAX_DISTANCE - dist) * FOOD_RACE_DISTANCE_WEIGHT
                + margin * FOOD_RACE_MARGIN_WEIGHT
            )
            if md <= 2:
                value += FOOD_RACE_NEAR_BONUS
            if ed == INF:
                value += FOOD_RACE_SOLO_REACHABLE_BONUS
            claims.append(value)

        elif ed < md:
            dist = min(ed, FOOD_RACE_MAX_DISTANCE)
            margin = FOOD_RACE_MAX_DISTANCE if md == INF else min(md - ed, 6)
            value = (
                FOOD_RACE_BASE
                + max(0, FOOD_RACE_MAX_DISTANCE - dist) * FOOD_RACE_DISTANCE_WEIGHT
                + margin * FOOD_RACE_MARGIN_WEIGHT
            )
            if ed <= 2:
                value += FOOD_RACE_NEAR_BONUS
            if md == INF:
                value += FOOD_RACE_SOLO_REACHABLE_BONUS
            threats.append(value)

    claims.sort(reverse=True)
    threats.sort(reverse=True)

    # Foco: el objetivo principal pesa entero; el secundario solo parcialmente.
    positive = claims[0] if claims else 0
    if len(claims) > 1:
        positive += int(claims[1] * FOOD_RACE_SECONDARY_WEIGHT)

    negative = threats[0] if threats else 0
    if len(threats) > 1:
        negative += int(threats[1] * FOOD_RACE_SECONDARY_WEIGHT)

    return max(-FOOD_RACE_CAP, min(FOOD_RACE_CAP, positive - negative))

def compute_strategy_state(my_score, en_score, remaining, my_to_move=True):
    """Estado estratégico exacto respecto del límite de movimientos.

    `remaining` incluye el turno actual. Si nadie vuelve a comer, el jugador
    actual obtendrá ceil(remaining/2) puntos normales y el rival floor(...).
    Cada manzana futura sustituye un +1 por +100, es decir, cambia el margen
    relativo en 99 puntos.
    """
    remaining = max(0, int(remaining))
    if my_to_move:
        my_turns_left = (remaining + 1) // 2
        en_turns_left = remaining // 2
    else:
        my_turns_left = remaining // 2
        en_turns_left = (remaining + 1) // 2
    base_margin = (my_score - en_score) + (my_turns_left - en_turns_left)

    if base_margin > 0:
        required_net_apples = 0
        safe_concedable_apples = max(0, (base_margin - 1) // 99)
    else:
        required_net_apples = max(1, (1 - base_margin + 98) // 99)
        safe_concedable_apples = 0

    if remaining > STRATEGY_ACTIVE_REMAINING:
        mode = "NORMAL"
    elif base_margin > 0:
        if remaining <= STRATEGY_LOCK_REMAINING and safe_concedable_apples >= 2:
            mode = "LOCK"
        else:
            mode = "LEADING"
    else:
        # Con poco tiempo, necesitar dos manzanas netas ya es una situación
        # suficientemente urgente para subir varianza/agresividad alimentaria.
        if (required_net_apples >= STRATEGY_DESPERATE_NET_APPLES
                or (remaining <= STRATEGY_LOCK_REMAINING and required_net_apples >= 2)):
            mode = "DESPERATE"
        else:
            mode = "TRAILING"

    return {
        "mode": mode,
        "base_margin": base_margin,
        "required_net_apples": required_net_apples,
        "safe_concedable_apples": safe_concedable_apples,
        "my_turns_left": my_turns_left,
        "enemy_turns_left": en_turns_left,
        "my_to_move": bool(my_to_move),
        "remaining": remaining,
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


def compute_apple_freeze_penalties(grid, my_body, en_body, food_list, candidates,
                                   strategy, fe_penalties, forced_trap_penalties):
    """Penaliza COBRAR ahora una manzana que conviene mantener congelada.

    Se activa solo cuando la ventaja ya tolera manzanas rivales, falta poco,
    la manzana está claramente reservada para nosotros y existe una jugada
    no-comida con FE=0 y sin trampa forzada. No se activa en los últimos
    movimientos: ahí queremos cobrar la reserva sin dar tiempo al respawn.
    """
    penalties = {name: 0 for name, _ in candidates}
    stats = {
        "enabled": True, "active": False, "bankable_food": 0,
        "enemy_urgent_food": 0, "penalties": penalties.copy(),
    }

    remaining = strategy.get("remaining", 999)
    if (strategy.get("mode") != "LOCK"
            or remaining > APPLE_FREEZE_MAX_REMAINING
            or remaining <= APPLE_BANK_CASHOUT_REMAINING
            or len(food_list) < 2):
        return penalties, stats

    food_set = set(food_list)
    safe_non_food = [
        name for name, npos in candidates
        if npos not in food_set
        and fe_penalties.get(name, 0) == 0
        and forced_trap_penalties.get(name, 0) == 0
    ]
    if not safe_non_food:
        return penalties, stats

    my_topo = analyze_topology_consolidated(
        grid, my_body[0], len(my_body), my_body[-1] if my_body else None
    )
    en_topo = analyze_topology_consolidated(
        grid, en_body[0], len(en_body), en_body[-1] if en_body else None
    ) if en_body else TopologyInfo(0, 0, False, False, {})

    bankable = []
    enemy_urgent = 0
    for f in food_list:
        md = my_topo.distances.get(f, INF)
        ed = en_topo.distances.get(f, INF)
        if md <= 2 and (ed == INF or ed >= md + 3):
            bankable.append(f)
        if ed <= 2 and ed < md:
            enemy_urgent += 1

    stats["bankable_food"] = len(bankable)
    stats["enemy_urgent_food"] = enemy_urgent

    # Evidencia de replay: con una sola reserva y apenas 2 manzanas de colchón,
    # congelar demasiado pronto puede convertir una victoria en empate.
    # V6 exige una ventaja muy sólida (>=3) O el patrón fuerte de dos reservas
    # privadas con >=2 de colchón, que corresponde al caso de "congelar slots".
    safe_concede = strategy.get("safe_concedable_apples", 0)
    strong_bank = (len(bankable) >= 2 and safe_concede >= 2)
    strong_lead = (safe_concede >= 3)
    if not (strong_bank or strong_lead):
        return penalties, stats
    if safe_concede < enemy_urgent + 1:
        return penalties, stats

    for name, npos in candidates:
        if npos not in food_set:
            continue
        ed = en_topo.distances.get(npos, INF)
        if npos not in bankable or ed < APPLE_FREEZE_MIN_ENEMY_DISTANCE:
            continue

        penalty = APPLE_FREEZE_BASE_PENALTY
        if len(bankable) >= 2:
            penalty += APPLE_FREEZE_EXTRA_BANKED
        if strategy.get("safe_concedable_apples", 0) >= 3:
            penalty += APPLE_FREEZE_EXTRA_BANKED
        penalties[name] = min(APPLE_FREEZE_CAP, penalty)

    stats["active"] = any(penalties.values())
    stats["penalties"] = dict(penalties)
    stats["safe_non_food"] = list(safe_non_food)
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


def compute_adaptive_territory_bonus(territory_delta, score_diff, remaining,
                                     food_race_bonus, min_my_food_dist, strategy_mode=None):
    """Contextual territory bonus without extra BFS.

    Design goals:
    - Early game: almost no territory pressure; food/tempo should dominate.
    - Mid/late: territory matters progressively more.
    - Ahead: protect/control more space. Behind: territory yields to recovery.
    - Clear/near food race: suppress territory so the bot does not dance centrally.
    - Hard cap keeps this heuristic subordinate to actual score and strong food races.
    """
    if remaining > TERRITORY_EARLY_REMAINING:
        weight = TERRITORY_BASE_EARLY
    elif remaining > TERRITORY_LATE_REMAINING:
        weight = TERRITORY_BASE_MID
    else:
        weight = TERRITORY_BASE_LATE

    # Score-aware risk posture. A full apple is ~100 points, so use broad bands.
    if score_diff >= 100:
        weight += TERRITORY_WIN_BONUS
    elif score_diff <= -100:
        weight = max(0, weight - TERRITORY_LOSE_REDUCTION)

    # If there is an actionable food race, territory becomes a tie-breaker only.
    actionable_food = (
        min_my_food_dist != INF and min_my_food_dist <= 5
        and abs(food_race_bonus) >= 1800
    )
    if actionable_food:
        weight = int(round(weight * TERRITORY_FOOD_SUPPRESS))

    # V6: el territorio es instrumental, no un objetivo. Si necesitamos
    # remontar, cede casi por completo a comida; en LOCK solo queda como
    # desempate/defensa y nunca se infla por ir ganando.
    if strategy_mode == "DESPERATE":
        weight = 0
    elif strategy_mode == "TRAILING":
        weight = int(round(weight * 0.35))
    elif strategy_mode == "LOCK":
        weight = int(round(weight * 0.50))

    # Clamp the geometric differential too; one huge open region must not dominate.
    delta = max(-50, min(50, territory_delta))
    bonus = delta * weight
    return max(-TERRITORY_CAP, min(TERRITORY_CAP, bonus))


def evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_to_move=True):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None

    if not my_head:
        return -INF
    if not en_head:
        return INF

    my_tail = my_body[-1] if my_body else None
    en_tail = en_body[-1] if en_body else None

    # Una topología por serpiente; el chokepoint reutiliza estas distancias.
    my_topo = analyze_topology_consolidated(grid, my_head, len(my_body), my_tail)
    en_topo = analyze_topology_consolidated(grid, en_head, len(en_body), en_tail)

    if my_topo.pocket_trap:
        return -500000 + (my_topo.space * 100)
    if en_topo.pocket_trap:
        return 500000 - (en_topo.space * 100)

    can_cut, door_pos, _ = analyze_corridor_chokepoints_opt(
        grid, my_head, en_head, en_topo, my_topo
    )
    choke_bonus = 0
    if can_cut and door_pos:
        dist_to_door = my_topo.distances.get(door_pos, INF)
        if dist_to_door == 0:
            choke_bonus = 350000
        elif dist_to_door != INF:
            choke_bonus = 150000 - (dist_to_door * 3000)

    score_diff = my_score - en_score
    strategy = compute_strategy_state(my_score, en_score, remaining, my_to_move=my_to_move)
    score_weight = 500 if remaining > 100 else 2500
    base_score = score_diff * score_weight

    food_tempo_score = 0
    min_my_food_dist = INF
    for f in food_list:
        md = my_topo.distances.get(f, INF)
        ed = en_topo.distances.get(f, INF)
        if md < min_my_food_dist:
            min_my_food_dist = md
        if md < ed:
            food_tempo_score += (400 - md * 12)
        elif ed < md:
            food_tempo_score -= (250 - ed * 8)
        elif md != INF:
            food_tempo_score += (100 - md * 8)

    if min_my_food_dist != INF:
        food_tempo_score += (200 - min_my_food_dist * 10)

    # Food Race v1: componente focal y simétrico. No ejecuta BFS nuevos.
    food_race_bonus = compute_food_race_bonus(my_topo, en_topo, food_list)

    territory_bonus = 0
    if USE_ADAPTIVE_TERRITORY_V6 and len(my_body) + len(en_body) >= TERRITORY_MIN_COMBINED_LENGTH:
        my_territory = 0
        en_territory = 0
        for r in range(len(grid)):
            for c in range(len(grid[0])):
                if grid[r][c] not in {"#", "A", "B", "a", "b"}:
                    md = my_topo.distances.get((r, c), INF)
                    ed = en_topo.distances.get((r, c), INF)
                    if md < ed:
                        my_territory += 1
                    elif ed < md:
                        en_territory += 1
        territory_delta = my_territory - en_territory
        territory_bonus = compute_adaptive_territory_bonus(
            territory_delta, score_diff, remaining, food_race_bonus, min_my_food_dist,
            strategy.get("mode")
        )

    mobility_score = (my_topo.exits * 120) + min(my_topo.space, 40) * 8
    is_losing = score_diff < -150

    if remaining < 30:
        if score_diff > 0:
            return base_score + (my_topo.space * 50) + (my_topo.exits * 250) + territory_bonus + choke_bonus
        return base_score + (food_tempo_score * 4) + (food_race_bonus * 2) + territory_bonus + choke_bonus
    elif is_losing:
        return base_score + (food_tempo_score * 3) + int(food_race_bonus * 1.5) + territory_bonus + mobility_score + choke_bonus
    return base_score + (food_tempo_score * 2) + food_race_bonus + territory_bonus + mobility_score + choke_bonus

# =====================================================================
# 8. BÚSQUEDA ALPHA-BETA CON TRANSPOSITION TABLE EXACTA
# =====================================================================
def get_ordered_moves_v5(grid, head, body, other_body, food_list, en_head):
    moves = get_legal_moves_raw(grid, head, body, other_body)
    if not moves:
        return []

    # V5 hacía 3 BFS aquí: 2 dentro del análisis de chokepoint + 1 propio.
    # Consolidamos a 2 topologías sin cambiar el criterio de ordenamiento.
    my_topo = analyze_topology_consolidated(
        grid, head, len(body), body[-1] if body else None
    )
    en_topo = analyze_topology_consolidated(
        grid, en_head, len(other_body), other_body[-1] if other_body else None
    )
    can_cut, door_pos, _ = analyze_corridor_chokepoints_opt(
        grid, head, en_head, en_topo, my_topo
    )

    min_cur_food = min((my_topo.distances.get(f, INF) for f in food_list), default=INF)

    def move_priority(item):
        _, npos = item
        score = 0
        if can_cut and door_pos and npos == door_pos:
            score += 100000
        if npos in food_list:
            score += 20000
        else:
            next_d = min(
                (abs(npos[0] - f[0]) + abs(npos[1] - f[1]) for f in food_list),
                default=INF
            )
            if next_d < min_cur_food:
                score += 5000
        return score

    moves.sort(key=move_priority, reverse=True)
    return moves

def alpha_beta(grid, depth, alpha, beta, is_my_turn, my_body, en_body,
               deadline, my_score, en_score, remaining, food_list, my_is_a):
    global SEARCH_ABORTED
    if time.monotonic() >= deadline:
        SEARCH_ABORTED = True
        return 0

    # El orden de food_list no forma parte del estado semántico.
    state_hash = hash((
        tuple(my_body), tuple(en_body), is_my_turn,
        tuple(sorted(food_list)), remaining, my_is_a, my_score, en_score
    ))

    if state_hash in TT and TT[state_hash]['depth'] >= depth:
        entry = TT[state_hash]
        if entry['flag'] == TT_EXACT:
            return entry['score']
        elif entry['flag'] == TT_LOWER and entry['score'] >= beta:
            return entry['score']
        elif entry['flag'] == TT_UPPER and entry['score'] <= alpha:
            return entry['score']

    # Terminal real: si al jugador que debe mover no le queda ningún movimiento,
    # la partida termina por muerte. Esto debe dominar cualquier heurística,
    # incluso si el horizonte de búsqueda llegó justo a depth == 0.
    if len(my_body) == 0:
        return -TERMINAL_WIN_SCORE - max(0, remaining)
    if len(en_body) == 0:
        return TERMINAL_WIN_SCORE + max(0, remaining)

    if depth == 0:
        # En la frontera del horizonte hay que detectar muerte antes de evaluar.
        # Son solo 4 vecinos y evita que una posición ya perdida reciba un score
        # heurístico aparentemente aceptable.
        side_to_move_body = my_body if is_my_turn else en_body
        other_body = en_body if is_my_turn else my_body
        terminal_moves = get_legal_moves_raw(
            grid, side_to_move_body[0], side_to_move_body, other_body
        )
        if not terminal_moves:
            if is_my_turn:
                return -TERMINAL_WIN_SCORE - max(0, remaining)
            return TERMINAL_WIN_SCORE + max(0, remaining)
        return evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_to_move=is_my_turn)

    orig_alpha = alpha
    orig_beta = beta

    if is_my_turn:
        best = -INF
        moves = get_ordered_moves_v5(
            grid, my_body[0], my_body, en_body, food_list,
            en_body[0] if en_body else None
        )
        if not moves:
            return -TERMINAL_WIN_SCORE - max(0, remaining)

        for _, npos in moves:
            tail, pt, ptr, eaten, n_score, f_idx = make_move(
                grid, my_body, npos, my_is_a, my_score, food_list
            )
            val = alpha_beta(
                grid, depth - 1, alpha, beta, False,
                my_body, en_body, deadline,
                n_score, en_score, remaining - 1, food_list,
                my_is_a
            )
            unmake_move(
                grid, my_body, tail, pt, ptr, eaten,
                my_is_a, npos, food_list, f_idx
            )

            if SEARCH_ABORTED:
                return 0
            best = max(best, val)
            alpha = max(alpha, best)
            if beta <= alpha:
                break

        if not SEARCH_ABORTED:
            if best <= orig_alpha:
                flag = TT_UPPER
            elif best >= orig_beta:
                flag = TT_LOWER
            else:
                flag = TT_EXACT
            TT[state_hash] = {'score': best, 'depth': depth, 'flag': flag}
        return best

    best = INF
    moves = get_ordered_moves_v5(
        grid, en_body[0], en_body, my_body, food_list,
        my_body[0] if my_body else None
    )
    if not moves:
        return TERMINAL_WIN_SCORE + max(0, remaining)

    for _, npos in moves:
        tail, pt, ptr, eaten, n_score, f_idx = make_move(
            grid, en_body, npos, not my_is_a, en_score, food_list
        )
        val = alpha_beta(
            grid, depth - 1, alpha, beta, True,
            my_body, en_body, deadline,
            my_score, n_score, remaining - 1, food_list,
            my_is_a
        )
        unmake_move(
            grid, en_body, tail, pt, ptr, eaten,
            not my_is_a, npos, food_list, f_idx
        )

        if SEARCH_ABORTED:
            return 0
        best = min(best, val)
        beta = min(beta, best)
        if beta <= alpha:
            break

    if not SEARCH_ABORTED:
        if best <= orig_alpha:
            flag = TT_UPPER
        elif best >= orig_beta:
            flag = TT_LOWER
        else:
            flag = TT_EXACT
        TT[state_hash] = {'score': best, 'depth': depth, 'flag': flag}
    return best

def _get_current_direction(grid, head, side):
    if not head:
        return None
    body_chars = {"a"} if str(side) in {"A", "1"} else {"b"}
    for d_name, (dr, dc) in DIRECTIONS.items():
        back_r, back_c = head[0] - dr, head[1] - dc
        if is_pos_inside(grid, (back_r, back_c)) and grid[back_r][back_c] in body_chars:
            return d_name
    return None

def emergency_safety_fallback(grid, my_body, en_body, food_list):
    """Safety Kernel de emergencia con gradiente de escape y comida."""
    if not my_body:
        return "UP"
    head = my_body[0]
    best_dir = "UP"
    max_score = -INF
    
    for name, (dr, dc) in DIRECTIONS.items():
        npos = (head[0] + dr, head[1] + dc)
        if not is_pos_inside(grid, npos):
            continue
            
        cell = grid[npos[0]][npos[1]]
        if cell in {" ", "*"} or (npos == my_body[-1]):
            space, exits, reach, trap, dists = analyze_topology(grid, npos, len(my_body), my_body[-1])
            min_food = min((dists.get(f, INF) for f in food_list), default=INF)
            food_bonus = (200 - min_food * 5) if min_food != INF else 0
            
            score = space * 15 + exits * 60 + (1500 if reach else 0) - (10000 if trap else 0) + food_bonus
            if score > max_score:
                max_score = score
                best_dir = name
                
    return best_dir

def _update_anti_cycle_history(game_id, head, body_len):
    """Actualiza historial de posiciones REALES una vez por turno propio.

    El crecimiento de longitud se usa como señal robusta de que hubo comida;
    cuando ocurre, el contador sin progreso se reinicia.
    """
    history = bot_histories.setdefault(game_id, {"my_path": deque(), "en_path": deque()})
    recent = history.get("ac_recent_heads")
    if recent is None:
        recent = deque(maxlen=AC_HISTORY_SIZE)
        history["ac_recent_heads"] = recent

    # Evita contar dos veces un evento duplicado del mismo turno.
    is_new_turn = (not recent or recent[-1] != head)
    if is_new_turn:
        last_len = history.get("ac_last_body_len")
        if last_len is None or body_len > last_len:
            history["ac_no_growth_turns"] = 0
        else:
            history["ac_no_growth_turns"] = history.get("ac_no_growth_turns", 0) + 1
        history["ac_last_body_len"] = body_len
        recent.append(head)

    return list(recent), history.get("ac_no_growth_turns", 0)


def _anti_cycle_penalty_for_candidate(recent_heads, candidate_pos, no_growth_turns):
    """Penaliza solo si candidate_pos prolongaría un ciclo corto repetido.

    Ejemplo: A-B-C-D-A-B-C -> elegir D completa por segunda vez el ciclo
    de periodo 4. No penaliza simples revisitas ni trayectorias no periódicas.
    """
    if candidate_pos is None or no_growth_turns < AC_MIN_NO_GROWTH_TURNS:
        return 0, None, 0

    seq = list(recent_heads) + [candidate_pos]
    best_penalty = 0
    best_period = None
    best_repeats = 0

    for period in range(2, AC_MAX_PERIOD + 1):
        if len(seq) < period * AC_MIN_REPEATS:
            continue

        pattern = seq[-period:]
        repeats = 1
        cursor = len(seq) - 2 * period
        while cursor >= 0 and seq[cursor:cursor + period] == pattern:
            repeats += 1
            cursor -= period

        if repeats < AC_MIN_REPEATS:
            continue

        # Exige suficiente tiempo sin crecimiento para no castigar un giro
        # normal inmediatamente después de comer.
        if no_growth_turns + 1 < period * AC_MIN_REPEATS:
            continue

        penalty = (
            AC_BASE_PENALTY
            + (repeats - AC_MIN_REPEATS) * AC_REPEAT_PENALTY
            + max(0, AC_MAX_PERIOD - period) * AC_SHORT_PERIOD_BONUS
        )
        penalty = min(penalty, AC_PENALTY_CAP)
        if penalty > best_penalty:
            best_penalty = penalty
            best_period = period
            best_repeats = repeats

    return best_penalty, best_period, best_repeats


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


def strengthen_root_fe_penalties(penalties, body_len, remaining, score_diff):
    """Refuerza FE solo cuando existe al menos una alternativa raíz con riesgo 0.

    Evita que una ventaja heurística de comida/territorio compense demasiado fácil
    una señal geométrica de encierro en serpientes largas. Si todas las jugadas
    tienen riesgo, no altera nada: Alpha-Beta sigue eligiendo el mal menor.
    """
    if not penalties or body_len < FE_SAFETY_GATE_MIN_LENGTH:
        return dict(penalties)
    if min(penalties.values(), default=0) != 0:
        return dict(penalties)

    scale = FE_SAFETY_GATE_SCALE_VERY_LONG if body_len >= 14 else FE_SAFETY_GATE_SCALE_LONG
    if remaining <= 100:
        scale += 1
    # Si vamos muy atrás, seguimos protegiendo la vida pero reducimos un poco
    # la aversión a riesgo para permitir remontadas.
    if score_diff <= -300:
        scale = max(3, scale - 1)

    out = {}
    for move, risk in penalties.items():
        if risk <= 0:
            out[move] = 0
        elif risk >= FE_FATAL_RISK:
            out[move] = risk
        else:
            out[move] = min(FE_FATAL_RISK, risk * scale)
    return out


def _enemy_can_force_corridor_death(grid, my_body, en_body, food_list, my_is_a, rounds_left, stats):
    """True si el rival puede encadenar una muerte mientras nosotros solo tengamos 0/1 respuesta.

    No intenta resolver estrategia general. Es una extensión táctica barata para pasillos,
    bordes y "shadowing" donde el rival va cerrando la única salida turno a turno.
    """
    if rounds_left <= 0 or not en_body:
        return False

    enemy_moves = get_legal_moves_raw(grid, en_body[0], en_body, my_body)
    if not enemy_moves:
        return False

    for _, en_pos in enemy_moves:
        stats['nodes'] += 1
        eu = make_move(grid, en_body, en_pos, not my_is_a, 0, food_list)
        try:
            my_moves = get_legal_moves_raw(grid, my_body[0], my_body, en_body)
            if not my_moves:
                return True

            # Si recuperamos elección real, ya no es un pasillo FORZADO.
            if len(my_moves) > 1:
                continue

            _, my_pos = my_moves[0]
            mu = make_move(grid, my_body, my_pos, my_is_a, 0, food_list)
            try:
                if _enemy_can_force_corridor_death(
                    grid, my_body, en_body, food_list, my_is_a, rounds_left - 1, stats
                ):
                    return True
            finally:
                unmake_move(
                    grid, my_body, mu[0], mu[1], mu[2], mu[3],
                    my_is_a, my_pos, food_list, mu[5]
                )
        finally:
            unmake_move(
                grid, en_body, eu[0], eu[1], eu[2], eu[3],
                not my_is_a, en_pos, food_list, eu[5]
            )

    return False


def compute_forced_trap_penalties(grid, my_body, en_body, food_list, my_is_a, candidates,
                                  max_rounds=FORCED_TRAP_MAX_ROUNDS):
    """Penalización raíz binaria: fatal solo si el rival puede mantenernos sin elección hasta morir."""
    original_grid = tuple(tuple(row) for row in grid)
    original_my = tuple(my_body)
    original_en = tuple(en_body)
    original_food = tuple(food_list)

    penalties = {}
    stats = {'nodes': 0}
    for move_name, npos in candidates:
        u = make_move(grid, my_body, npos, my_is_a, 0, food_list)
        try:
            forced = _enemy_can_force_corridor_death(
                grid, my_body, en_body, food_list, my_is_a, max_rounds, stats
            )
            penalties[move_name] = FORCED_TRAP_FATAL_PENALTY if forced else 0
        finally:
            unmake_move(
                grid, my_body, u[0], u[1], u[2], u[3],
                my_is_a, npos, food_list, u[5]
            )

    reversible = (
        tuple(tuple(row) for row in grid) == original_grid
        and tuple(my_body) == original_my
        and tuple(en_body) == original_en
        and tuple(food_list) == original_food
    )
    if not reversible:
        raise AssertionError("Forced Trap Probe rompió la reversibilidad del estado")

    return penalties, stats


def choose_direction(game_data, use_fe=USE_FUTURE_ESCAPE_DEFAULT, use_ac=USE_ANTI_CYCLE_DEFAULT,
                     use_apple_freeze=USE_APPLE_FREEZE_DEFAULT):
    global TT, SEARCH_ABORTED, LAST_FE_STATS, LAST_AC_STATS, LAST_STRATEGY_STATS
    TT.clear()
    SEARCH_ABORTED = False

    start_time = time.monotonic()
    deadline = start_time + DEADLINE_TIMEOUT

    grid = parse_board(game_data.get("board", ""))
    side = game_data.get("side", "A")
    game_id = game_data.get("game_id", "default")

    my_body, en_body = get_bodies(game_id, grid, side)
    if not my_body:
        return "UP"

    my_is_a = str(side) in {"A", "1"}
    my_score = game_data.get("score_1", 0) if my_is_a else game_data.get("score_2", 0)
    en_score = game_data.get("score_2", 0) if my_is_a else game_data.get("score_1", 0)
    remaining = game_data.get("remaining_moves", 300)
    food_list = find_food(grid)

    strategy = compute_strategy_state(my_score, en_score, remaining, my_to_move=True)
    # Evita estadísticas stale incluso si hay 0/1 movimientos legales y salimos temprano.
    LAST_STRATEGY_STATS = dict(strategy)

    current_dir = _get_current_direction(grid, my_body[0], side)
    candidates = get_ordered_moves_v5(
        grid, my_body[0], my_body, en_body, food_list,
        en_body[0] if en_body else None
    )

    ac_penalties = compute_anti_cycle_penalties(
        game_id, my_body[0], len(my_body), candidates, enabled=use_ac
    )
    ac_penalties = _strategy_adjust_anti_cycle_penalties(ac_penalties, strategy)

    if not candidates:
        LAST_FE_STATS = {'enabled': use_fe, 'nodes': 0, 'elapsed_ms': 0.0, 'penalties': {}}
        return emergency_safety_fallback(grid, my_body, en_body, food_list)
    if len(candidates) == 1:
        LAST_FE_STATS = {'enabled': use_fe, 'nodes': 0, 'elapsed_ms': 0.0, 'penalties': {candidates[0][0]: 0}}
        return candidates[0][0]

    fe_penalties = {}
    if use_fe:
        fe_penalties = compute_future_escape_penalties(
            grid, my_body, en_body, food_list, my_is_a, candidates, deadline
        )
        fe_penalties = strengthen_root_fe_penalties(
            fe_penalties, len(my_body), remaining, my_score - en_score
        )
    else:
        LAST_FE_STATS = {'enabled': False, 'nodes': 0, 'elapsed_ms': 0.0, 'penalties': {}}

    forced_trap_penalties, forced_trap_stats = compute_forced_trap_penalties(
        grid, my_body, en_body, food_list, my_is_a, candidates
    ) if use_fe else ({move_name: 0 for move_name, _ in candidates}, {'nodes': 0})

    if use_apple_freeze:
        apple_freeze_penalties, freeze_stats = compute_apple_freeze_penalties(
            grid, my_body, en_body, food_list, candidates, strategy,
            fe_penalties, forced_trap_penalties
        )
    else:
        apple_freeze_penalties = {move_name: 0 for move_name, _ in candidates}
        freeze_stats = {"enabled": False, "active": False, "penalties": dict(apple_freeze_penalties)}

    strategy_adjustments = compute_strategy_root_adjustments(candidates, food_list, strategy)
    LAST_STRATEGY_STATS = dict(strategy)
    LAST_STRATEGY_STATS.update({
        "apple_freeze": freeze_stats,
        "root_adjustments": dict(strategy_adjustments),
        "anti_cycle_penalties": dict(ac_penalties),
        "forced_trap_nodes": forced_trap_stats.get('nodes', 0),
    })

    best_move = candidates[0][0]
    depth = 1

    # Conservamos el límite estratégico de V5: esta fase no cambia estrategia.
    while time.monotonic() < deadline and depth <= 12:
        SEARCH_ABORTED = False
        layer_best_move = best_move
        layer_best_score = -INF

        for move_name, npos in candidates:
            if time.monotonic() >= deadline:
                SEARCH_ABORTED = True
                break

            tail, pt, ptr, eaten, n_score, f_idx = make_move(
                grid, my_body, npos, my_is_a, my_score, food_list
            )
            score = alpha_beta(
                grid, depth - 1, -INF, INF, False,
                my_body, en_body, deadline,
                n_score, en_score, remaining - 1, food_list,
                my_is_a
            )
            if use_fe:
                score -= fe_penalties.get(move_name, 0)
                score -= forced_trap_penalties.get(move_name, 0)
            if use_ac:
                score -= ac_penalties.get(move_name, 0)
            score += strategy_adjustments.get(move_name, 0)
            if use_apple_freeze:
                score -= apple_freeze_penalties.get(move_name, 0)
            unmake_move(
                grid, my_body, tail, pt, ptr, eaten,
                my_is_a, npos, food_list, f_idx
            )

            if SEARCH_ABORTED:
                break

            if score > layer_best_score or (score == layer_best_score and move_name == current_dir):
                layer_best_score = score
                layer_best_move = move_name

        if not SEARCH_ABORTED:
            best_move = layer_best_move
            candidates.sort(key=lambda x: x[0] == best_move, reverse=True)
            depth += 1
        else:
            break

    # Conservamos el safety check geométrico final de V5.
    _, chosen_npos = next(((m, p) for m, p in candidates if m == best_move), (None, None))
    if chosen_npos:
        _, _, _, is_trap, _ = analyze_topology(grid, chosen_npos, len(my_body), my_body[-1])
        if is_trap:
            for alt_name, alt_pos in candidates:
                if alt_name != best_move:
                    _, _, _, alt_trap, _ = analyze_topology(grid, alt_pos, len(my_body), my_body[-1])
                    if not alt_trap:
                        best_move = alt_name
                        break

    return best_move

# =====================================================================
# 9. CLIENTE WEBSOCKET (Multi-Partida)
# =====================================================================
def _handle_list_users(payload):
    users = payload.get("users", [])
    set_global_status(f"Online ({len(users)} bots conectados)")

async def _handle_challenge(payload, websocket):
    challenge_id = payload.get("challenge_id")
    opponent = payload.get("opponent", "Desconocido")
    set_global_status(f"Aceptando reto de {opponent}...")
    accept_action = {
        "action": "accept_challenge",
        "data": {"challenge_id": challenge_id}
    }
    await websocket.send(json.dumps(accept_action))

def _extract_turn_scores(payload, side):
    p1 = payload.get("player_1", "Jugador 1")
    p2 = payload.get("player_2", "Jugador 2")
    s1, s2 = payload.get("score_1", 0), payload.get("score_2", 0)
    if str(side) in {"A", "1"}:
        return p1, p2, s1, s2
    return p2, p1, s2, s1

async def _handle_your_turn(payload, websocket):
    game_id = payload.get("game_id", "default")
    side = payload.get("side", "A")
    my_name, enemy_name, my_score, enemy_score = _extract_turn_scores(payload, side)
    grid = parse_board(payload.get("board", ""))
    
    update_visual_game_state(
        game_id, grid, side, my_name, enemy_name,
        my_score, enemy_score, payload.get("remaining_moves", 300)
    )
    
    move_dir = choose_direction(payload)
    
    response = {
        "action": "move",
        "data": {
            "game_id": game_id,
            "turn_token": payload.get("turn_token"),
            "direction": move_dir
        }
    }
    await websocket.send(json.dumps(response))

def _handle_game_over(payload):
    game_id = payload.get("game_id")
    s1, s2 = payload.get("score_1", 0), payload.get("score_2", 0)
    update_visual_game_over(game_id, s1, s2)

def _handle_ws_error(payload):
    err_msg = payload.get("Error", "Error desconocido")
    set_global_status(f"Error: {err_msg}")

def _process_sync_ws_event(event_type, payload):
    if event_type == "list_users":
        _handle_list_users(payload)
    elif event_type == "game_over":
        _handle_game_over(payload)
    elif event_type == "error":
        _handle_ws_error(payload)

async def _process_ws_event(event_type, payload, websocket):
    if event_type == "your_turn":
        await _handle_your_turn(payload, websocket)
        return
    if event_type == "challenge":
        await _handle_challenge(payload, websocket)
        return
    _process_sync_ws_event(event_type, payload)

async def _listen_ws_stream(websocket):
    set_global_status("Conectado. Esperando eventos...")
    async for message in websocket:
        event_data = json.loads(message)
        await _process_ws_event(event_data.get("event"), event_data.get("data", {}), websocket)

async def _connect_and_stream(uri):
    set_global_status("Conectando al servidor...")
    async with websockets.connect(uri) as websocket:
        await _listen_ws_stream(websocket)

async def websocket_client_loop(token):
    uri = f"wss://server.codechallenge.net.ar/ws?token={token}"
    while True:
        try:
            await _connect_and_stream(uri)
        except Exception as e:
            set_global_status(f"Desconectado ({e}). Reintentando...")
            await asyncio.sleep(3)

def start_ws_thread(token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_client_loop(token))

# =====================================================================
# 10. MOTOR VISUAL MULTI-PARTIDA
# =====================================================================
def _build_side_color_map(my_side):
    is_a = my_side in {'A', '1'}
    p1_head = (50, 255, 100) if is_a else (60, 180, 255)
    p1_body = (0, 160, 50) if is_a else (0, 80, 180)
    p2_head = (60, 180, 255) if is_a else (50, 255, 100)
    p2_body = (0, 80, 180) if is_a else (0, 160, 50)
    return {
        '*': (255, 90, 50), '#': (70, 70, 75),
        'A': p1_head, '1': p1_head, 'a': p1_body,
        'B': p2_head, '2': p2_head, 'b': p2_body
    }

def _calculate_grid_layout(num_games):
    if num_games <= 1: return 1, 1
    if num_games == 2: return 1, 2
    if num_games <= 4: return 2, 2
    if num_games <= 6: return 2, 3
    if num_games <= 8: return 2, 4
    return 3, 4

def _draw_single_board_panel(screen, game_data, rect, fonts):
    font_bold, font_small = fonts
    x, y, w, h = rect
    
    pygame.draw.rect(screen, (22, 22, 24), rect, border_radius=8)
    border_color = (60, 60, 70) if not game_data["game_over"] else (
        (255, 215, 0) if game_data.get("winner") and game_data["my_name"] in game_data["winner"] else (160, 50, 50)
    )
    pygame.draw.rect(screen, border_color, rect, 2, border_radius=8)
    
    txt_p1 = f"🟢 {game_data['my_name']}: {game_data['my_score']} pts"
    txt_p2 = f"🔵 {game_data['enemy_name']}: {game_data['enemy_score']} pts"
    txt_turn = f"⏱️ {300 - game_data['remaining_moves']}/300"
    
    screen.blit(font_bold.render(txt_p1, True, (50, 255, 100)), (x + 8, y + 6))
    screen.blit(font_bold.render(txt_p2, True, (60, 180, 255)), (x + 8, y + 24))
    screen.blit(font_small.render(txt_turn, True, (200, 200, 200)), (x + w - 75, y + 6))
    
    if game_data["game_over"] and game_data["winner"]:
        screen.blit(font_small.render(f"🏆 {game_data['winner']}", True, (255, 215, 0)), (x + 8, y + 42))
    
    grid = game_data["grid"]
    if not grid or not grid[0]:
        return
        
    grid_top = y + 60
    available_w = w - 16
    available_h = h - 68
    
    rows, cols = len(grid), len(grid[0])
    cell_size = max(4, min(available_w // cols, available_h // rows))
    
    board_px_w = cols * cell_size
    board_px_h = rows * cell_size
    offset_x = x + (w - board_px_w) // 2
    offset_y = grid_top + (available_h - board_px_h) // 2
    
    c_map = _build_side_color_map(game_data["my_side"])
    
    for r in range(rows):
        for c in range(cols):
            val = grid[r][c]
            color = c_map.get(val, (32, 32, 35))
            c_rect = (offset_x + c * cell_size, offset_y + r * cell_size, cell_size, cell_size)
            pygame.draw.rect(screen, color, c_rect)
            if cell_size >= 12:
                pygame.draw.rect(screen, (45, 45, 50), c_rect, 1)

def run_visualizer():
    pygame.init()
    pygame.font.init()
    
    font_global = pygame.font.SysFont("consolas", 16, bold=True)
    font_panel_bold = pygame.font.SysFont("consolas", 13, bold=True)
    font_panel_small = pygame.font.SysFont("consolas", 11)
    
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("🐍 Code Challenge - Multi-Match Visualizer")
    clock = pygame.time.Clock()
    running = True
    
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                
        screen.fill((12, 12, 14))
        
        with visual_lock:
            global_status = visual_state["status"]
            games_snapshot = list(visual_state["games"].values())
            
        pygame.draw.rect(screen, (15, 15, 18), (0, 0, WINDOW_WIDTH, GLOBAL_HUD_HEIGHT))
        pygame.draw.line(screen, (60, 60, 70), (0, GLOBAL_HUD_HEIGHT), (WINDOW_WIDTH, GLOBAL_HUD_HEIGHT), 2)
        screen.blit(font_global.render("🐍 Multi-Match Visualizer", True, (255, 255, 255)), (16, 14))
        screen.blit(font_global.render(f"Estado: {global_status} | Partidas activas: {len(games_snapshot)}", True, (160, 220, 255)), (WINDOW_WIDTH - 600, 14))
        
        num_games = len(games_snapshot)
        if num_games == 0:
            screen.blit(font_global.render("Esperando partidas activas del servidor...", True, (150, 150, 160)), (WINDOW_WIDTH // 2 - 200, WINDOW_HEIGHT // 2))
        else:
            g_rows, g_cols = _calculate_grid_layout(num_games)
            margin = 12
            board_area_top = GLOBAL_HUD_HEIGHT + margin
            
            panel_w = (WINDOW_WIDTH - margin * (g_cols + 1)) // g_cols
            panel_h = (WINDOW_HEIGHT - board_area_top - margin * g_rows) // g_rows
            
            for idx, g_data in enumerate(games_snapshot[:g_rows * g_cols]):
                r_idx = idx // g_cols
                c_idx = idx % g_cols
                px = margin + c_idx * (panel_w + margin)
                py = board_area_top + r_idx * (panel_h + margin)
                
                _draw_single_board_panel(screen, g_data, (px, py, panel_w, panel_h), (font_panel_bold, font_panel_small))
                
        pygame.display.flip()
        clock.tick(FPS)
        
    pygame.quit()
    sys.exit()

# =====================================================================
# 11. ENTRADA PRINCIPAL
# =====================================================================
# =====================================================================
# 11. TESTS OFFLINE DE CORRECCIÓN (sin red)
# =====================================================================
def run_tests():
    print("=== BOT V6 CORRECTNESS AUDIT: TESTS ===")

    # 1) Topología consolidada debe ser semánticamente idéntica a V5.
    grid = [
        list("#######"),
        list("#A a  #"),
        list("#  a* #"),
        list("#  B  #"),
        list("#  b  #"),
        list("#     #"),
        list("#######"),
    ]
    my_body = deque([(1, 1), (1, 3), (2, 3)])
    # La forma anterior solo se usa para comparar BFS/topología, no como snake válida.
    old = analyze_topology(grid, (1, 1), len(my_body), (2, 3))
    new = analyze_topology_consolidated(grid, (1, 1), len(my_body), (2, 3))
    assert (old[0], old[1], old[2], old[3], old[4]) == (
        new.space, new.exits, new.tail_reachable, new.pocket_trap, new.distances
    ), "Topología consolidada cambió la semántica."
    print("[OK] Topología consolidada equivalente")

    # 2) Cola adyacente: el test correcto debe usar una cola realmente vecina.
    grid_tail = [
        list("#####"),
        list("#Aa #"),
        list("#aa #"),
        list("#####"),
    ]
    body_tail = deque([(1, 1), (1, 2), (2, 2), (2, 1)])
    moves = get_legal_moves_raw(grid_tail, body_tail[0], body_tail, deque())
    assert any(pos == (2, 1) for _, pos in moves), "La cola adyacente debería poder liberarse en un movimiento sin comida."
    print("[OK] Test de cola adyacente válido")

    # 3) Reversibilidad exacta A/B, con y sin comida, incluyendo orden de food_list.
    def check_reversible(is_a, eat):
        head = "A" if is_a else "B"
        body_ch = "a" if is_a else "b"
        grid_r = [
            list("######"),
            list(f"# {body_ch}  #"),
            list(f"# {head} *#"),
            list("#    #"),
            list("######"),
        ]
        body_r = deque([(2, 2), (1, 2)])
        food_r = [(2, 4), (3, 1), (3, 3)]
        target = (2, 4) if eat else (2, 3)
        if eat:
            # Asegurar que el target sea comida en grid y lista.
            pass
        else:
            grid_r[2][3] = " "
        import copy
        snap_grid = copy.deepcopy(grid_r)
        snap_body = deque(body_r)
        snap_food = list(food_r)
        undo = make_move(grid_r, body_r, target, is_a, 0, food_r)
        unmake_move(grid_r, body_r, undo[0], undo[1], undo[2], undo[3], is_a, target, food_r, undo[5])
        assert grid_r == snap_grid and body_r == snap_body and food_r == snap_food

    # Ajuste de dos escenarios donde la comida debe coincidir con el target.
    for is_a in (True, False):
        # no-eat
        head = "A" if is_a else "B"; body_ch = "a" if is_a else "b"
        g = [list("######"), list(f"# {body_ch}  #"), list(f"# {head}  #"), list("#    #"), list("######")]
        b = deque([(2,2),(1,2)]); f = [(3,1),(3,3)]
        import copy
        sg,sb,sf = copy.deepcopy(g),deque(b),list(f)
        u = make_move(g,b,(2,3),is_a,0,f)
        unmake_move(g,b,u[0],u[1],u[2],u[3],is_a,(2,3),f,u[5])
        assert g == sg and b == sb and f == sf
        # eat + food order
        g = [list("######"), list(f"# {body_ch}  #"), list(f"# {head} *#"), list("#    #"), list("######")]
        b = deque([(2,2),(1,2)]); f = [(3,1),(2,4),(3,3)]
        sg,sb,sf = copy.deepcopy(g),deque(b),list(f)
        u = make_move(g,b,(2,4),is_a,0,f)
        unmake_move(g,b,u[0],u[1],u[2],u[3],is_a,(2,4),f,u[5])
        assert g == sg and b == sb and f == sf
    print("[OK] Make/Unmake reversible para A y B + orden de comida")

    # 4) Tracker U: debe cubrir todas las celdas y devolver head->tail.
    bot_histories.pop("tracker_u", None)
    grid_u = [list("Aaa"), list("  a"), list("aaa")]
    body_u = get_bodies("tracker_u", grid_u, "A")[0]
    assert list(body_u) == [(0,0),(0,1),(0,2),(1,2),(2,2),(2,1),(2,0)]
    print("[OK] Tracker resync U-shape")

    # 5) TT: un nodo MIN completamente explorado con ventana amplia debe ser EXACT.
    tt_grid = [
        list("#######"),
        list("#     #"),
        list("# Aa  #"),
        list("#     #"),
        list("#  bB #"),
        list("# *   #"),
        list("#######"),
    ]
    tt_my = deque([(2,2),(2,3)])
    tt_en = deque([(4,4),(4,3)])
    tt_food = [(5,2)]
    TT.clear()
    global SEARCH_ABORTED
    SEARCH_ABORTED = False
    _ = alpha_beta(
        tt_grid, 1, -INF, INF, False, tt_my, tt_en,
        time.monotonic() + 1.0, 0, 0, 100, tt_food, True
    )
    tt_key = hash((tuple(tt_my), tuple(tt_en), False, tuple(sorted(tt_food)), 100, True, 0, 0))
    assert TT[tt_key]['flag'] == TT_EXACT, "Nodo MIN completo debe guardarse como TT_EXACT."
    print("[OK] Flags TT correctos en nodo MIN completo")

    # 6) Future Escape: estado sin salida debe ser fatal; abierto debe ser seguro.
    fe_blocked = [
        list("#####"),
        list("#aaa#"),
        list("#aAa#"),
        list("#aaa#"),
        list("#####"),
    ]
    fe_blocked_body = deque([(2,2),(1,2),(1,1),(2,1),(3,1),(3,2),(3,3),(2,3),(1,3)])
    assert _future_escape_state_risk(fe_blocked, fe_blocked_body, deque(), []) == FE_FATAL_RISK

    fe_open = [
        list("#######"),
        list("#     #"),
        list("# Aa  #"),
        list("#     #"),
        list("#  bB #"),
        list("#     #"),
        list("#######"),
    ]
    fe_open_my = deque([(2,2),(2,3)])
    fe_open_en = deque([(4,4),(4,3)])
    assert _future_escape_state_risk(fe_open, fe_open_my, fe_open_en, []) == 0
    print("[OK] Future Escape distingue fatal vs abierto")

    # 7) Causalidad FE: en una serpiente válida, UP entra en una zona de alto
    # riesgo futuro mientras DOWN conserva una ruta abierta. No fijamos qué debe
    # elegir Alpha-Beta: solo demostramos que FE separa los candidatos.
    causal_grid = [list(x) for x in [
        "###########",
        "#Baaaaaa  #",
        "#baa aaaa #",
        "#  a    a #",
        "#  aa   a #",
        "#   a   a #",
        "#   aaAaa #",
        "#  aaa    #",
        "#  a      #",
        "#  aa     #",
        "###########",
    ]]
    causal_my = deque([
        (6,6),(6,7),(6,8),(5,8),(4,8),(3,8),(2,8),(2,7),(1,7),(1,6),
        (2,6),(2,5),(1,5),(1,4),(1,3),(1,2),(2,2),(2,3),(3,3),(4,3),
        (4,4),(5,4),(6,4),(6,5),(7,5),(7,4),(7,3),(8,3),(9,3),(9,4)
    ])
    causal_en = deque([(1,1),(2,1)])
    causal_candidates = get_legal_moves_raw(
        causal_grid, causal_my[0], causal_my, causal_en
    )
    causal_penalties = compute_future_escape_penalties(
        causal_grid, causal_my, causal_en, [], True, causal_candidates,
        time.monotonic() + 1.0
    )
    assert causal_penalties.get("UP", 0) > causal_penalties.get("DOWN", 0), causal_penalties
    assert LAST_FE_STATS.get("reversible") is True

    # Mismo patrón jugando como B: FE debe ser simétrico respecto del lado.
    causal_grid_b = [list(x) for x in [
        "###########",
        "#A bbbbbb  #",
        "#abb bbbb #",
        "#  b    b #",
        "#  bb   b #",
        "#   b   b #",
        "#   bbBbb #",
        "#  bbb    #",
        "#  b      #",
        "#  bb     #",
        "###########",
    ]]
    causal_candidates_b = get_legal_moves_raw(
        causal_grid_b, causal_my[0], causal_my, causal_en
    )
    causal_penalties_b = compute_future_escape_penalties(
        causal_grid_b, causal_my, causal_en, [], False, causal_candidates_b,
        time.monotonic() + 1.0
    )
    assert causal_penalties_b == causal_penalties, (causal_penalties, causal_penalties_b)
    print(f"[OK] FE causal A/B: UP={causal_penalties.get('UP')} > DOWN={causal_penalties.get('DOWN')}")

    # 8) Food Race: debe premiar una carrera ganable y penalizar la simétrica.
    fr_my = TopologyInfo(20, 3, True, False, {(2,2):0, (2,3):1, (2,4):2, (2,5):3})
    fr_en = TopologyInfo(20, 3, True, False, {(4,4):0, (3,4):1, (2,4):2, (2,5):4})
    fr_food = [(2,5)]
    fr_pos = compute_food_race_bonus(fr_my, fr_en, fr_food)
    fr_neg = compute_food_race_bonus(fr_en, fr_my, fr_food)
    assert fr_pos > 0 and fr_neg < 0 and fr_pos == -fr_neg, (fr_pos, fr_neg)

    # Cercanía importa incluso con el mismo margen de ventaja.
    near_my = TopologyInfo(20, 3, True, False, {(1,1):0, (1,2):1})
    near_en = TopologyInfo(20, 3, True, False, {(3,3):0, (2,3):1, (1,3):2, (1,2):3})
    far_my = TopologyInfo(20, 3, True, False, {(1,1):0, (1,2):6})
    far_en = TopologyInfo(20, 3, True, False, {(3,3):0, (1,2):8})
    assert compute_food_race_bonus(near_my, near_en, [(1,2)]) > compute_food_race_bonus(far_my, far_en, [(1,2)])
    assert compute_food_race_bonus(fr_my, fr_en, []) == 0
    print(f"[OK] Food Race focal: favorable={fr_pos}, desfavorable={fr_neg}")

    # 9) Anti-Cycle: un cuadrado repetido debe ser detectado, una salida no.
    ac_hist = [(8,8), (8,9), (9,9), (9,8), (8,8), (8,9), (9,9)]
    ac_continue, ac_period, ac_repeats = _anti_cycle_penalty_for_candidate(
        ac_hist, (9,8), 12
    )
    ac_break, _, _ = _anti_cycle_penalty_for_candidate(
        ac_hist, (7,9), 12
    )
    assert ac_continue > 0 and ac_period == 4 and ac_repeats >= 2, (ac_continue, ac_period, ac_repeats)
    assert ac_break == 0, ac_break
    # Tras crecimiento reciente no debe intervenir.
    ac_after_growth, _, _ = _anti_cycle_penalty_for_candidate(ac_hist, (9,8), 0)
    assert ac_after_growth == 0
    print(f"[OK] Anti-Cycle causal: continuar={ac_continue}, romper={ac_break}, periodo={ac_period}")

    # 10) Adaptive Territory: early casi apagado; gana peso en mid/late,
    # aumenta al ir ganando y se suprime ante una carrera clara por comida.
    at_early = compute_adaptive_territory_bonus(30, 0, 260, 0, INF)
    at_mid = compute_adaptive_territory_bonus(30, 0, 150, 0, INF)
    at_win = compute_adaptive_territory_bonus(30, 120, 150, 0, INF)
    at_lose = compute_adaptive_territory_bonus(30, -120, 150, 0, INF)
    at_food = compute_adaptive_territory_bonus(30, 120, 150, 3500, 3)
    assert at_early == 0, at_early
    assert at_mid > at_early, (at_mid, at_early)
    assert at_win > at_mid, (at_win, at_mid)
    assert at_lose < at_mid, (at_lose, at_mid)
    assert 0 <= at_food < at_win, (at_food, at_win)
    assert abs(compute_adaptive_territory_bonus(999, 120, 50, 0, INF)) <= TERRITORY_CAP
    assert USE_ADAPTIVE_TERRITORY_V6 is False

    # Root Safety Gate: solo refuerza riesgo si hay alternativa FE=0 y cuerpo largo.
    sg = strengthen_root_fe_penalties({'SAFE': 0, 'RISK': FE_SINGLE_EXIT_RISK}, 14, 90, 0)
    assert sg['SAFE'] == 0 and sg['RISK'] > FE_SINGLE_EXIT_RISK
    sg_all = strengthen_root_fe_penalties({'A': FE_SINGLE_EXIT_RISK, 'B': FE_TIGHT_RISK}, 14, 90, 0)
    assert sg_all == {'A': FE_SINGLE_EXIT_RISK, 'B': FE_TIGHT_RISK}
    sg_short = strengthen_root_fe_penalties({'SAFE': 0, 'RISK': FE_SINGLE_EXIT_RISK}, 6, 90, 0)
    assert sg_short['RISK'] == FE_SINGLE_EXIT_RISK
    print('[OK] Root Safety Gate + Territory conservador')
    print(f"[OK] Adaptive Territory: early={at_early}, mid={at_mid}, win={at_win}, lose={at_lose}, food={at_food}")

    # Score simulation exacta respecto de arena local: +1 normal, +100 al comer.
    score_grid = [list("#####"), list("#A *#"), list("#a  #"), list("#aB #"), list("#####")]
    score_body = deque([(1,1),(2,1),(3,1)])
    score_food = [(1,3)]
    snap_grid = [row[:] for row in score_grid]; snap_body = deque(score_body); snap_food = list(score_food)
    tail, pt, ptr, eaten, ns, fi = make_move(score_grid, score_body, (1,2), True, 10, score_food)
    assert not eaten and ns == 11
    unmake_move(score_grid, score_body, tail, pt, ptr, eaten, True, (1,2), score_food, fi)
    assert score_grid == snap_grid and score_body == snap_body and score_food == snap_food
    tail, pt, ptr, eaten, ns, fi = make_move(score_grid, score_body, (1,3), True, 10, score_food)
    assert eaten and ns == 110
    unmake_move(score_grid, score_body, tail, pt, ptr, eaten, True, (1,3), score_food, fi)
    assert score_grid == snap_grid and score_body == snap_body and score_food == snap_food
    print('[OK] Score simulado: +1 normal / +100 comida')

    # Terminal real en el horizonte: sin jugadas = muerte, no evaluación heurística.
    term_grid = [list("#####"), list("#Aa##"), list("##a##"), list("###B#"), list("#####")]
    term_my = deque([(1,1),(1,2),(2,2)])
    term_en = deque([(3,3)])
    term_score = alpha_beta(term_grid, 0, -INF, INF, True, term_my, term_en,
                            time.monotonic()+1.0, 5000, 0, 50, [], True)
    assert term_score < -800_000_000, term_score
    print('[OK] Terminal sin movimientos domina heurística')

    # V6 Strategy Controller: matemática de manzanas netas y modos.
    st_lock = compute_strategy_state(500, 300, 40)
    st_lead = compute_strategy_state(350, 300, 40)
    st_trail = compute_strategy_state(250, 300, 40)
    st_des = compute_strategy_state(100, 300, 40)
    st_normal = compute_strategy_state(500, 0, 200)
    assert st_lock['mode'] == 'LOCK' and st_lock['safe_concedable_apples'] == 2, st_lock
    assert st_lead['mode'] == 'LEADING', st_lead
    assert st_trail['mode'] == 'TRAILING' and st_trail['required_net_apples'] == 1, st_trail
    assert st_des['mode'] == 'DESPERATE' and st_des['required_net_apples'] == 3, st_des
    assert st_normal['mode'] == 'NORMAL', st_normal
    st_enemy_turn = compute_strategy_state(0, 0, 1, my_to_move=False)
    assert st_enemy_turn['base_margin'] == -1 and st_enemy_turn['required_net_apples'] == 1, st_enemy_turn
    assert _strategy_adjust_anti_cycle_penalties({'X': 10000}, st_lock)['X'] < 10000
    assert _strategy_adjust_anti_cycle_penalties({'X': 10000}, st_des)['X'] > 10000
    print('[OK] V6 Strategy Controller: NORMAL/LEADING/LOCK/TRAILING/DESPERATE')

    # Apple Freeze: con +200, una amenaza rival y dos manzanas reservadas,
    # comer la reserva se penaliza si existe salida segura; al final se cobra.
    fg = [[" " for _ in range(9)] for _ in range(7)]
    for r in range(7): fg[r][0] = fg[r][8] = '|'
    fmy = deque([(3,3),(3,2),(3,1)])
    fen = deque([(5,6),(5,7)])
    for i,(r,c) in enumerate(fmy): fg[r][c] = 'A' if i == 0 else 'a'
    for i,(r,c) in enumerate(fen): fg[r][c] = 'B' if i == 0 else 'b'
    ffoods = [(3,4),(2,3),(5,5)]
    for r,c in ffoods: fg[r][c] = '*'
    fcands = get_legal_moves_raw(fg, fmy[0], fmy, fen)
    fstate = compute_strategy_state(500, 300, 40); fstate['remaining'] = 40
    ffe = {name:0 for name,_ in fcands}; ftrap = {name:0 for name,_ in fcands}
    fpen, fstats = compute_apple_freeze_penalties(fg, fmy, fen, ffoods, fcands, fstate, ffe, ftrap)
    assert max(fpen.values(), default=0) > 250000 and fstats['active'], (fpen, fstats)
    cash = dict(fstate); cash['remaining'] = 6
    cpen, _ = compute_apple_freeze_penalties(fg, fmy, fen, ffoods, fcands, cash, ffe, ftrap)
    assert all(v == 0 for v in cpen.values()), cpen
    print('[OK] Apple Freeze/Banking: congela reserva y libera cashout final')

    # TT V6: el score forma parte del estado semántico.
    key_a = hash((tuple(tt_my), tuple(tt_en), False, tuple(sorted(tt_food)), 100, True, 0, 0))
    key_b = hash((tuple(tt_my), tuple(tt_en), False, tuple(sorted(tt_food)), 100, True, 100, 0))
    assert key_a != key_b
    print('[OK] TT V6 distingue mismo tablero con scores diferentes')

    # Forced Trap Probe: patrón realista de "shadowing" contra el borde.
    trap_grid = [list("                "),
                 list("                "),
                 list("             A  "),
                 list("             a B"),
                 list("             a b"),
                 list("            aa b"),
                 list("              bb"),
                 list("              b "),
                 list("              b ")]
    # Completar a 15x17 como parse_board (incluye paredes | en columnas 0 y 16).
    while len(trap_grid) < 15:
        trap_grid.append(list("                "))
    # Este test sintético se arma directamente con coordenadas internas equivalentes.
    tmy = deque([(3, 15), (4, 15), (5, 15), (6, 15), (7, 15), (8, 15), (9, 15)])
    ten = deque([(2, 13), (3, 13), (4, 13), (5, 13), (5, 12)])
    # Rehacer una grilla vacía 15x17 con paredes laterales para evitar ambigüedad del dibujo.
    tg = [[" " for _ in range(17)] for _ in range(15)]
    for r in range(15):
        tg[r][0] = tg[r][16] = "|"
    for i,(r,c) in enumerate(tmy): tg[r][c] = "B" if i == 0 else "b"
    for i,(r,c) in enumerate(ten): tg[r][c] = "A" if i == 0 else "a"
    tcands = get_legal_moves_raw(tg, tmy[0], tmy, ten)
    tp, ts = compute_forced_trap_penalties(tg, tmy, ten, [], False, tcands, max_rounds=4)
    assert tp.get("UP", 0) == FORCED_TRAP_FATAL_PENALTY, tp
    assert tp.get("LEFT", 0) == 0, tp
    print("[OK] Forced Trap Probe detecta shadowing fatal en borde")

    print("=== TODOS LOS TESTS APROBADOS ===")


def run_benchmark(iterations=2000):
    """Microbenchmark reproducible de topología V5 vs consolidada.

    No mide winrate ni Alpha-Beta completo; solo el hot-path de topología.
    """
    grid = [list("###############")]
    for _ in range(13):
        grid.append(list("#             #"))
    grid.append(list("###############"))
    grid[2][2] = "A"; grid[2][3] = "a"; grid[2][4] = "a"
    grid[12][12] = "B"; grid[12][11] = "b"; grid[12][10] = "b"
    grid[7][7] = "*"; grid[4][10] = "*"; grid[10][4] = "*"
    my_head, en_head = (2,2), (12,12)
    my_tail, en_tail = (2,4), (12,10)

    t0 = time.perf_counter()
    for _ in range(iterations):
        analyze_topology(grid, my_head, 3, my_tail)
        analyze_topology(grid, en_head, 3, en_tail)
    old_t = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(iterations):
        analyze_topology_consolidated(grid, my_head, 3, my_tail)
        analyze_topology_consolidated(grid, en_head, 3, en_tail)
    new_t = time.perf_counter() - t0

    print(f"iterations={iterations}")
    print(f"V5 topology: {old_t*1000:.3f} ms")
    print(f"OPT topology: {new_t*1000:.3f} ms")
    print(f"ratio old/new: {old_t/new_t:.3f}x" if new_t else "ratio: inf")

def _validate_and_get_token():
    if len(sys.argv) < 2:
        print("Uso: python botv5.2.2.py <TU_TOKEN_JWT>")
        sys.exit(1)
    return sys.argv[1]

def main():
    bot_token = _validate_and_get_token()
    ws_thread = threading.Thread(target=start_ws_thread, args=(bot_token,), daemon=True)
    ws_thread.start()
    run_visualizer()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    elif len(sys.argv) > 1 and sys.argv[1] == "--benchmark":
        run_benchmark()
    else:
        main()
