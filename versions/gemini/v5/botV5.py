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
    path = [head]
    curr = head
    visited = {head}
    while True:
        found = False
        for dr, dc in DIRECTIONS.values():
            nr, nc = curr[0] + dr, curr[1] + dc
            if (nr, nc) not in visited and is_pos_inside(grid, (nr, nc)) and grid[nr][nc] == body_char:
                path.append((nr, nc))
                visited.add((nr, nc))
                curr = (nr, nc)
                found = True
                break
        if not found:
            break
    path.reverse()
    return deque(path)

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

# =====================================================================
# 6. SIMULADOR EXACTO DE ESTADOS (O(1))
# =====================================================================
def make_move(grid, body, next_pos, is_mine, current_score, food_list):
    head_char = "A" if is_mine else "B"
    body_char = "a" if is_mine else "b"
    eaten_food = (grid[next_pos[0]][next_pos[1]] == "*")
    
    tail_pos = None
    prev_tail_char = None
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
        current_score += 100
        if next_pos in food_list:
            food_list.remove(next_pos)
            
    return tail_pos, prev_tail_char, prev_target_char, eaten_food, current_score

def unmake_move(grid, body, tail_pos, prev_tail_char, prev_target_char, eaten_food, is_mine, next_pos, food_list):
    head_char = "A" if is_mine else "B"
    
    old_head = body.popleft()
    grid[old_head[0]][old_head[1]] = prev_target_char
    
    if len(body) > 0:
        new_head = body[0]
        grid[new_head[0]][new_head[1]] = head_char
        
    if not eaten_food and tail_pos:
        body.append(tail_pos)
        grid[tail_pos[0]][tail_pos[1]] = prev_tail_char
        
    if eaten_food:
        food_list.append(next_pos)

# =====================================================================
# 7. EVALUADOR TÁCTICO V5 (Food Tempo & Anti-Parálisis)
# =====================================================================
def evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None
    
    if not my_head:
        return -INF
    if not en_head:
        return INF
        
    my_tail = my_body[-1] if my_body else None
    en_tail = en_body[-1] if en_body else None
    
    # 1. Topología de Supervivencia
    my_space, my_exits, my_tail_reach, my_pocket_trap, my_dists = analyze_topology(grid, my_head, len(my_body), my_tail)
    en_space, en_exits, en_tail_reach, en_pocket_trap, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    
    if my_pocket_trap:
        return -500000 + (my_space * 100)
    if en_pocket_trap:
        return 500000 - (en_space * 100)
        
    # 2. Asfixia en Corredores (Kill Corridor)
    can_cut, door_pos, is_lethal = analyze_corridor_chokepoints(grid, my_head, en_head, my_body, en_body)
    choke_bonus = 0
    if can_cut and door_pos:
        dist_to_door = my_dists.get(door_pos, INF)
        if dist_to_door == 0:
            choke_bonus = 350000
        elif dist_to_door != INF:
            choke_bonus = 150000 - (dist_to_door * 3000)
            
    # 3. Diferencial de Puntuación Balanceado (Sin Parálisis)
    score_diff = my_score - en_score
    # Se escala proporcional al tiempo restante para no congelar decisiones en early game
    score_weight = 500 if remaining > 100 else 2500
    base_score = score_diff * score_weight
    
    # 4. Food Tempo & Resource Denial
    food_tempo_score = 0
    min_my_food_dist = INF
    
    for f in food_list:
        md = my_dists.get(f, INF)
        ed = en_dists.get(f, INF)
        
        if md < min_my_food_dist:
            min_my_food_dist = md
            
        if md < ed:
            # Controlamos la manzana: +150 por cercanía y negación
            food_tempo_score += (400 - md * 12)
        elif ed < md:
            # Ventaja enemiga: penalización por comida concedida
            food_tempo_score -= (250 - ed * 8)
        else:
            if md != INF:
                food_tempo_score += (100 - md * 8)
                
    # Gradiente de proximidad continuo hacia la comida más cercana
    if min_my_food_dist != INF:
        food_tempo_score += (200 - min_my_food_dist * 10)
        
    # 5. Territorio Voronoi
    my_territory = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] not in {"#", "A", "B", "a", "b"}:
                md = my_dists.get((r, c), INF)
                ed = en_dists.get((r, c), INF)
                if md < ed:
                    my_territory += 1
                    
    # 6. Movilidad y Modos Estratégicos
    mobility_score = (my_exits * 120) + min(my_space, 40) * 8
    
    # Detección de Modo Catch-Up (Remontada agresiva)
    is_losing = score_diff < -150
    
    if remaining < 30:
        if score_diff > 0:
            return base_score + (my_space * 50) + (my_exits * 250) + choke_bonus
        return base_score + (food_tempo_score * 4) + (my_territory * 15) + choke_bonus
    elif is_losing:
        # Prioridad absoluta a reconquistar manzanas y territorio
        return base_score + (food_tempo_score * 3) + (my_territory * 25) + mobility_score + choke_bonus
    else:
        return base_score + (food_tempo_score * 2) + (my_territory * 18) + mobility_score + choke_bonus

# =====================================================================
# 8. BÚSQUEDA ALPHA-BETA CON TRANSPOSITION TABLE EXACTA
# =====================================================================
def get_ordered_moves_v5(grid, head, body, other_body, food_list, en_head):
    moves = get_legal_moves_raw(grid, head, body, other_body)
    if not moves:
        return []
        
    can_cut, door_pos, _ = analyze_corridor_chokepoints(grid, head, en_head, body, other_body)
    
    # Calcular distancias actuales para el gradiente
    cur_dists = bfs_distances(grid, head, body[-1] if body else None)
    min_cur_food = min((cur_dists.get(f, INF) for f in food_list), default=INF)
    
    def move_priority(item):
        _, npos = item
        score = 0
        if can_cut and door_pos and npos == door_pos:
            score += 100000
        if npos in food_list:
            score += 20000
        else:
            # Bono por gradiente (acercarse a la comida)
            next_d = min((abs(npos[0] - f[0]) + abs(npos[1] - f[1]) for f in food_list), default=INF)
            if next_d < min_cur_food:
                score += 5000
        return score
        
    moves.sort(key=move_priority, reverse=True)
    return moves

def alpha_beta(grid, depth, alpha, beta, is_my_turn, my_body, en_body, deadline, my_score, en_score, remaining, food_list):
    global SEARCH_ABORTED
    if time.monotonic() >= deadline:
        SEARCH_ABORTED = True
        return 0
        
    state_hash = hash((
        tuple(my_body), tuple(en_body), is_my_turn,
        tuple(sorted(food_list)), remaining
    ))
    
    if state_hash in TT and TT[state_hash]['depth'] >= depth:
        entry = TT[state_hash]
        if entry['flag'] == TT_EXACT:
            return entry['score']
        elif entry['flag'] == TT_LOWER and entry['score'] >= beta:
            return entry['score']
        elif entry['flag'] == TT_UPPER and entry['score'] <= alpha:
            return entry['score']
        
    if depth == 0 or len(my_body) == 0 or len(en_body) == 0:
        return evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list)
        
    orig_alpha = alpha
    
    if is_my_turn:
        best = -INF
        moves = get_ordered_moves_v5(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
        if not moves:
            return evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list)
            val = alpha_beta(grid, depth - 1, alpha, beta, False, my_body, en_body, deadline, n_score, en_score, remaining - 1, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
            if SEARCH_ABORTED:
                return 0
            best = max(best, val)
            alpha = max(alpha, best)
            if beta <= alpha:
                break
                
        if not SEARCH_ABORTED:
            flag = TT_EXACT if (best > orig_alpha and best < beta) else (TT_LOWER if best >= beta else TT_UPPER)
            TT[state_hash] = {'score': best, 'depth': depth, 'flag': flag}
        return best
    else:
        best = INF
        moves = get_ordered_moves_v5(grid, en_body[0], en_body, my_body, food_list, my_body[0] if my_body else None)
        if not moves:
            return evaluate_state_v5(grid, my_body, en_body, my_score, en_score, remaining, food_list)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, en_body, npos, False, en_score, food_list)
            val = alpha_beta(grid, depth - 1, alpha, beta, True, my_body, en_body, deadline, my_score, n_score, remaining - 1, food_list)
            unmake_move(grid, en_body, tail, pt, ptr, eaten, False, npos, food_list)
            
            if SEARCH_ABORTED:
                return 0
            best = min(best, val)
            beta = min(beta, best)
            if beta <= alpha:
                break
                
        if not SEARCH_ABORTED:
            flag = TT_EXACT if (best > orig_alpha and best < beta) else (TT_UPPER if best <= orig_alpha else TT_LOWER)
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

def choose_direction(game_data):
    global TT, SEARCH_ABORTED
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
        
    is_p1 = str(side) in {"A", "1"}
    my_score = game_data.get("score_1", 0) if is_p1 else game_data.get("score_2", 0)
    en_score = game_data.get("score_2", 0) if is_p1 else game_data.get("score_1", 0)
    remaining = game_data.get("remaining_moves", 300)
    food_list = find_food(grid)
    
    current_dir = _get_current_direction(grid, my_body[0], side)
    candidates = get_ordered_moves_v5(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
    
    if not candidates:
        return emergency_safety_fallback(grid, my_body, en_body, food_list)
    if len(candidates) == 1:
        return candidates[0][0]
        
    best_move = candidates[0][0]
    depth = 1
    
    while time.monotonic() < deadline and depth <= 12:
        SEARCH_ABORTED = False
        layer_best_move = best_move
        layer_best_score = -INF
        
        for move_name, npos in candidates:
            if time.monotonic() >= deadline:
                SEARCH_ABORTED = True
                break
                
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list)
            score = alpha_beta(grid, depth - 1, -INF, INF, False, my_body, en_body, deadline, n_score, en_score, remaining - 1, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
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
            
    # Validación final contra trampas geométricas
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
def _validate_and_get_token():
    if len(sys.argv) < 2:
        print("Uso: python bot_v5.py <TU_TOKEN_JWT>")
        sys.exit(1)
    return sys.argv[1]

def main():
    bot_token = _validate_and_get_token()
    ws_thread = threading.Thread(target=start_ws_thread, args=(bot_token,), daemon=True)
    ws_thread.start()
    run_visualizer()

if __name__ == "__main__":
    main()