import sys
import time
import json
import asyncio
import threading
from collections import deque
import pygame
import websockets

# =====================================================================
# 1. CONFIGURACIÓN GENERAL Y CONSTANTES GLOBALES
# =====================================================================
WINDOW_WIDTH = 1360
WINDOW_HEIGHT = 820
HEADER_HEIGHT = 45
CELL_SIZE = 30
HUD_HEIGHT = 90
FPS = 30

DEADLINE_TIMEOUT = 0.080  
INF = 10**9
ABORT_FLAG = -INF - 1

DIRECTIONS = {
    "UP": (-1, 0), "DOWN": (1, 0),
    "LEFT": (0, -1), "RIGHT": (0, 1),
}

TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

visual_state = {
    "status": "Conectando al servidor...",
    "games": {},
    "focused_id": None,
    "view_mode": "GRID"
}
visual_lock = threading.Lock()

bot_histories = {}
TT = {}
SEARCH_ABORTED = False

# =====================================================================
# 2. SINCRONIZACIÓN VISUAL (DASHBOARD)
# =====================================================================
def update_visual_game_state(game_id, grid, side, my_name, enemy_name, my_score, enemy_score, remaining_moves):
    with visual_lock:
        if game_id not in visual_state["games"]:
            visual_state["games"][game_id] = {}
            if visual_state["focused_id"] is None:
                visual_state["focused_id"] = game_id

        visual_state["games"][game_id].update({
            "game_id": game_id, "grid": grid, "my_side": str(side),
            "my_name": my_name, "enemy_name": enemy_name,
            "my_score": my_score, "enemy_score": enemy_score,
            "remaining_moves": remaining_moves,
            "game_over": False, "winner": None,
            "last_updated": time.time()
        })

def update_visual_game_over(game_id, s1, s2):
    with visual_lock:
        if game_id and game_id in visual_state["games"]:
            g = visual_state["games"][game_id]
            g["game_over"] = True
            is_a = g["my_side"] in {"A", "1"}
            g["my_score"] = s1 if is_a else s2
            g["enemy_score"] = s2 if is_a else s1
            
            if g["my_score"] > g["enemy_score"]:
                g["winner"] = f"🟢 {g['my_name']} (Ganó)"
            elif g["enemy_score"] > g["my_score"]:
                g["winner"] = f"🔵 {g['enemy_name']} (Ganó)"
            else:
                g["winner"] = "⚪ Empate"

def set_global_status(text):
    with visual_lock:
        visual_state["status"] = text

# =====================================================================
# 3. PARSEO Y GENERADOR ESTRICTO DE LEGALIDAD
# =====================================================================
def parse_board(board_raw):
    if isinstance(board_raw, str):
        lines = board_raw.replace("\r", "").split("\n")
        if lines and lines[-1] == "": lines = lines[:-1]
        return [list(line.replace("|", "#")) for line in lines]
    return [list(row) for row in board_raw]

def _find_cell_with_targets(grid, targets):
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in targets: return (r, c)
    return None

def find_head(grid, side):
    return _find_cell_with_targets(grid, {"A", "1"} if str(side) in {"A", "1"} else {"B", "2"})

def find_enemy_head(grid, side):
    return _find_cell_with_targets(grid, {"B", "2"} if str(side) in {"A", "1"} else {"A", "1"})

def find_food(grid):
    return [(r, c) for r, row in enumerate(grid) for c, val in enumerate(row) if val == "*"]

def is_pos_inside(grid, pos):
    if not grid or not pos: return False
    return 0 <= pos[0] < len(grid) and 0 <= pos[1] < len(grid[0])

def get_strict_legal_moves(grid, head, body):
    """Fuente de verdad absoluta: nunca devuelve casillas fuera de 0..14 ni cuerpos."""
    if not head or not grid:
        return {}
    r, c = head
    tail = body[-1] if body and len(body) > 0 else None
    legal = {}
    
    for name, (dr, dc) in DIRECTIONS.items():
        nr, nc = r + dr, c + dc
        if 0 <= nr < len(grid) and 0 <= nc < len(grid[0]):
            cell = grid[nr][nc]
            if cell in {" ", "*"} or ((nr, nc) == tail and cell != "*"):
                legal[name] = (nr, nc)
    return legal

# =====================================================================
# 4. TRACKER EXACTO DE CUERPOS Y VELOCIDAD DE SCORE
# =====================================================================
def update_and_get_state(game_id, grid, side, my_score, en_score):
    head_my = find_head(grid, side)
    head_en = find_enemy_head(grid, side)
    
    is_p1 = str(side) in {"A", "1"}
    my_target = {"A", "1", "a"} if is_p1 else {"B", "2", "b"}
    en_target = {"B", "2", "b"} if is_p1 else {"A", "1", "a"}
    
    my_cells = sum(row.count(ch) for row in grid for ch in my_target)
    en_cells = sum(row.count(ch) for row in grid for ch in en_target)
    
    if game_id not in bot_histories:
        bot_histories[game_id] = {
            "my_path": deque(), "en_path": deque(),
            "scores": deque(maxlen=20) 
        }
        
    history = bot_histories[game_id]
    history["scores"].append((my_score, en_score))
        
    if not history["my_path"] and head_my: history["my_path"].append(head_my)
    if not history["en_path"] and head_en: history["en_path"].append(head_en)
        
    if head_my and history["my_path"][-1] != head_my:
        history["my_path"].append(head_my)
    if head_en and history["en_path"][-1] != head_en:
        history["en_path"].append(head_en)
        
    while len(history["my_path"]) > my_cells: history["my_path"].popleft()
    while len(history["en_path"]) > en_cells: history["en_path"].popleft()
    
    my_rate, en_rate = 0, 0
    if len(history["scores"]) > 1:
        past_my, past_en = history["scores"][0]
        my_rate = (my_score - past_my) / len(history["scores"])
        en_rate = (en_score - past_en) / len(history["scores"])
    
    return deque(reversed(history["my_path"])), deque(reversed(history["en_path"])), my_rate, en_rate

# =====================================================================
# 5. TOPOLOGÍA, CORREDORES Y DISTANCIAS BFS
# =====================================================================
def bfs_distances(grid, start_pos, tail_pos=None):
    if not start_pos or not is_pos_inside(grid, start_pos): return {}
    queue = deque([start_pos])
    distances = {start_pos: 0}
    while queue:
        curr = queue.popleft()
        d = distances[curr]
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if is_pos_inside(grid, npos):
                if (grid[npos[0]][npos[1]] in {" ", "*"} or npos == tail_pos) and npos not in distances:
                    distances[npos] = d + 1
                    queue.append(npos)
    return distances

def analyze_topology(grid, start_pos, my_len, tail_pos=None):
    dists = bfs_distances(grid, start_pos, tail_pos)
    space = len(dists)
    
    effective_exits = 0
    for dr, dc in DIRECTIONS.values():
        npos = (start_pos[0] + dr, start_pos[1] + dc)
        if is_pos_inside(grid, npos) and (grid[npos[0]][npos[1]] in {" ", "*"} or npos == tail_pos):
            effective_exits += 1

    tail_reachable = (tail_pos in dists) if tail_pos else False
    is_pocket_trap = (space <= my_len) and not tail_reachable
    return space, effective_exits, tail_reachable, is_pocket_trap, dists

def analyze_chokepoints(grid, my_head, en_head, my_body, en_body):
    if not en_head or not my_head: return False, None
    en_tail = en_body[-1] if en_body else None
    my_tail = my_body[-1] if my_body else None
    
    en_space, en_exits, _, _, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    my_dists = bfs_distances(grid, my_head, my_tail)
    
    if en_exits <= 2 and en_space < 60:
        for pos, dist_en in en_dists.items():
            open_connections = sum(1 for dr, dc in DIRECTIONS.values() 
                                   if is_pos_inside(grid, (pos[0]+dr, pos[1]+dc)) 
                                   and grid[pos[0]+dr][pos[1]+dc] in {" ", "*"} 
                                   and (pos[0]+dr, pos[1]+dc) not in en_dists)
            if open_connections >= 2:
                dist_my = my_dists.get(pos, INF)
                if dist_my <= dist_en and dist_my != INF:
                    return True, pos
    return False, None

# =====================================================================
# 6. SIMULADOR DE ESTADOS (O(1) Con Soporte para Lados A y B)
# =====================================================================
def get_snake_chars(side, is_mine):
    is_a = str(side) in {"A", "1"}
    if is_mine:
        return ("A", "a") if is_a else ("B", "b")
    else:
        return ("B", "b") if is_a else ("A", "a")

def make_move(grid, body, next_pos, is_mine, current_score, food_list, side):
    head_char, body_char = get_snake_chars(side, is_mine)
    eaten_food = (grid[next_pos[0]][next_pos[1]] == "*")
    
    tail_pos, prev_tail_char = None, None
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
        if next_pos in food_list: food_list.remove(next_pos)
            
    return tail_pos, prev_tail_char, prev_target_char, eaten_food, current_score

def unmake_move(grid, body, tail_pos, prev_tail_char, prev_target_char, eaten_food, is_mine, next_pos, food_list, side):
    head_char, _ = get_snake_chars(side, is_mine)
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
# 7. EVALUADOR TÁCTICO V6.1
# =====================================================================
def evaluate_state_v6(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_rate, en_rate):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None
    if not my_head: return -INF + 100
    if not en_head: return INF - 100
        
    my_tail = my_body[-1] if my_body else None
    en_tail = en_body[-1] if en_body else None
    
    my_space, my_exits, my_tail_reach, my_pocket_trap, my_dists = analyze_topology(grid, my_head, len(my_body), my_tail)
    en_space, en_exits, en_tail_reach, en_pocket_trap, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    
    if my_pocket_trap: return -800000 + my_space
    if en_pocket_trap: return 800000 - en_space
        
    score_diff = my_score - en_score
    projected_diff = score_diff + (my_rate - en_rate) * (remaining / 2.0)
    
    mode = "CONTEST"
    if remaining < 40 and score_diff > 0: mode = "SURVIVE"
    elif projected_diff < -150 or (score_diff < 0 and en_rate > my_rate + 2): mode = "CATCH_UP"
    elif projected_diff > 250: mode = "DOMINATE"

    base_score = score_diff * 10000
    
    food_score = 0
    min_my_food = INF
    
    for f in food_list:
        md = my_dists.get(f, INF)
        ed = en_dists.get(f, INF)
        if md < min_my_food: min_my_food = md
        
        if md < ed: food_score += 300 - md * 10  
        elif ed < md: food_score -= 200 - ed * 10 
        elif md != INF: food_score += 100 - md * 10
            
    if min_my_food != INF:
        food_score += (30 - min_my_food) * 15  

    option_delta = (my_exits - en_exits) * 25  
    my_territory = sum(1 for r in range(len(grid)) for c in range(len(grid[0])) 
                       if grid[r][c] not in {"#", "A", "B", "a", "b"} and my_dists.get((r,c), INF) < en_dists.get((r,c), INF))
                       
    can_cut, door_pos = analyze_chokepoints(grid, my_head, en_head, my_body, en_body)
    tactical_score = 0
    if can_cut and door_pos:
        dist_to_door = my_dists.get(door_pos, INF)
        if dist_to_door == 0: tactical_score += 500000
        elif dist_to_door != INF: tactical_score += 100000 - dist_to_door * 5000

    if mode == "CATCH_UP":
        return base_score + food_score * 8 + my_territory * 10 + tactical_score + option_delta
    elif mode == "DOMINATE":
        return base_score + my_space * 20 + my_territory * 30 + tactical_score + option_delta
    elif mode == "SURVIVE":
        return base_score + my_space * 50 + option_delta * 2
    else:
        return base_score + food_score * 5 + my_territory * 15 + tactical_score + option_delta + my_space * 5

# =====================================================================
# 8. BÚSQUEDA ALPHA-BETA Y FALLBACK
# =====================================================================
def get_ordered_moves_v6(grid, head, body, other_body, food_list, en_head):
    legal_moves = get_strict_legal_moves(grid, head, body)
    if not legal_moves: return []
    
    moves = [(name, pos) for name, pos in legal_moves.items()]
    can_cut, door_pos = analyze_chokepoints(grid, head, en_head, body, other_body)
    cur_dists = bfs_distances(grid, head, body[-1] if body else None)
    min_cur_food = min((cur_dists.get(f, INF) for f in food_list), default=INF)
    
    def priority(item):
        _, npos = item
        s = 0
        if can_cut and npos == door_pos: s += 10000
        if npos in food_list: s += 5000
        else:
            nd = min((abs(npos[0]-f[0]) + abs(npos[1]-f[1]) for f in food_list), default=INF)
            if nd < min_cur_food: s += 500
        return s
        
    moves.sort(key=priority, reverse=True)
    return moves

def alpha_beta(grid, depth, alpha, beta, is_my_turn, my_body, en_body, deadline, my_score, en_score, remaining, food_list, my_rate, en_rate, side):
    global SEARCH_ABORTED
    if time.monotonic() >= deadline:
        SEARCH_ABORTED = True
        return ABORT_FLAG
        
    state_hash = hash((tuple(my_body), tuple(en_body), is_my_turn, tuple(sorted(food_list)), remaining))
    if state_hash in TT and TT[state_hash]['depth'] >= depth:
        entry = TT[state_hash]
        if entry['flag'] == TT_EXACT: return entry['score']
        if entry['flag'] == TT_LOWER and entry['score'] >= beta: return entry['score']
        if entry['flag'] == TT_UPPER and entry['score'] <= alpha: return entry['score']
        
    if depth == 0 or len(my_body) == 0 or len(en_body) == 0:
        return evaluate_state_v6(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_rate, en_rate)
        
    orig_alpha = alpha
    
    if is_my_turn:
        best = -INF
        moves = get_ordered_moves_v6(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
        if not moves: return evaluate_state_v6(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_rate, en_rate)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list, side)
            val = alpha_beta(grid, depth-1, alpha, beta, False, my_body, en_body, deadline, n_score, en_score, remaining-1, food_list, my_rate, en_rate, side)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list, side)
            
            if SEARCH_ABORTED or val == ABORT_FLAG: return ABORT_FLAG
            best = max(best, val)
            alpha = max(alpha, best)
            if beta <= alpha: break
                
        flag = TT_EXACT if (best > orig_alpha and best < beta) else (TT_LOWER if best >= beta else TT_UPPER)
        TT[state_hash] = {'score': best, 'depth': depth, 'flag': flag}
        return best
    else:
        best = INF
        moves = get_ordered_moves_v6(grid, en_body[0], en_body, my_body, food_list, my_body[0] if my_body else None)
        if not moves: return evaluate_state_v6(grid, my_body, en_body, my_score, en_score, remaining, food_list, my_rate, en_rate)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, en_body, npos, False, en_score, food_list, side)
            val = alpha_beta(grid, depth-1, alpha, beta, True, my_body, en_body, deadline, my_score, n_score, remaining-1, food_list, my_rate, en_rate, side)
            unmake_move(grid, en_body, tail, pt, ptr, eaten, False, npos, food_list, side)
            
            if SEARCH_ABORTED or val == ABORT_FLAG: return ABORT_FLAG
            best = min(best, val)
            beta = min(beta, best)
            if beta <= alpha: break
                
        flag = TT_EXACT if (best > orig_alpha and best < beta) else (TT_UPPER if best <= orig_alpha else TT_LOWER)
        TT[state_hash] = {'score': best, 'depth': depth, 'flag': flag}
        return best

def emergency_safety_fallback(grid, my_body, food_list):
    if not my_body:
        return None
    legal_moves = get_strict_legal_moves(grid, my_body[0], my_body)
    if not legal_moves:
        return None
        
    best_dir = list(legal_moves.keys())[0]
    max_score = -INF
    
    for name, npos in legal_moves.items():
        space, exits, reach, trap, dists = analyze_topology(grid, npos, len(my_body), my_body[-1])
        m_food = min((dists.get(f, INF) for f in food_list), default=INF)
        score = space*10 + exits*50 + (1000 if reach else 0) - (10000 if trap else 0) + (200 - m_food*2 if m_food!=INF else 0)
        
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
    
    is_p1 = str(side) in {"A", "1"}
    my_score = game_data.get("score_1", 0) if is_p1 else game_data.get("score_2", 0)
    en_score = game_data.get("score_2", 0) if is_p1 else game_data.get("score_1", 0)
    remaining = game_data.get("remaining_moves", 300)
    
    my_body, en_body, my_rate, en_rate = update_and_get_state(game_id, grid, side, my_score, en_score)
    if not my_body:
        h = find_head(grid, side)
        if h: my_body = deque([h])
        else: return "DOWN"
    
    # 1. BARRERA DE LEGALIDAD ESTRICTA
    strict_legal = get_strict_legal_moves(grid, my_body[0], my_body)
    if not strict_legal:
        # Si no hay salidas legales libres, buscamos cualquier casilla dentro de límites
        for name, (dr, dc) in DIRECTIONS.items():
            if 0 <= my_body[0][0] + dr < len(grid) and 0 <= my_body[0][1] + dc < len(grid[0]):
                return name
        return "DOWN"
        
    if len(strict_legal) == 1:
        return list(strict_legal.keys())[0]
        
    food_list = find_food(grid)
    raw_candidates = get_ordered_moves_v6(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
    
    # 2. FILTRADO INNEGOCIABLE: Solo permitimos candidatos válidos
    candidates = [item for item in raw_candidates if item[0] in strict_legal]
    
    if not candidates:
        best_move = emergency_safety_fallback(grid, my_body, food_list)
        if not best_move or best_move not in strict_legal:
            best_move = list(strict_legal.keys())[0]
        return best_move

    best_move = candidates[0][0]
    depth = 1
    
    current_dir = None
    if len(my_body) > 1:
        dr, dc = my_body[0][0] - my_body[1][0], my_body[0][1] - my_body[1][1]
        for name, (ddr, ddc) in DIRECTIONS.items():
            if dr == ddr and dc == ddc: current_dir = name
    
    while time.monotonic() < deadline and depth <= 16:
        SEARCH_ABORTED = False
        layer_best_move = best_move
        layer_best_score = -INF
        
        for move_name, npos in candidates:
            if time.monotonic() >= deadline:
                SEARCH_ABORTED = True
                break
                
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list, side)
            score = alpha_beta(grid, depth-1, -INF, INF, False, my_body, en_body, deadline, n_score, en_score, remaining-1, food_list, my_rate, en_rate, side)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list, side)
            
            if SEARCH_ABORTED or score == ABORT_FLAG:
                SEARCH_ABORTED = True
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
            
    # 3. VALIDADOR FINAL DE SEGURIDAD
    if best_move not in strict_legal:
        best_move = list(strict_legal.keys())[0]
                        
    return best_move

# =====================================================================
# 9. CLIENTE WEBSOCKET 
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
    if str(side) in {"A", "1"}: return p1, p2, s1, s2
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
        "data": {"game_id": game_id, "turn_token": payload.get("turn_token"), "direction": move_dir}
    }
    await websocket.send(json.dumps(response))

def _handle_game_over(payload):
    game_id = payload.get("game_id")
    s1, s2 = payload.get("score_1", 0), payload.get("score_2", 0)
    update_visual_game_over(game_id, s1, s2)

def _handle_ws_error(payload):
    set_global_status(f"Error: {payload.get('Error', 'Desconocido')}")

def _process_sync_ws_event(event_type, payload):
    if event_type == "list_users": _handle_list_users(payload)
    elif event_type == "game_over": _handle_game_over(payload)
    elif event_type == "error": _handle_ws_error(payload)

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
# 10. VISUALIZADOR MULTI-PARTIDA (DASHBOARD PYGAME)
# =====================================================================
import math

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
    border_color = (60, 60, 70) if not game_data["game_over"] else ((255, 215, 0) if "Ganador" in str(game_data.get("winner")) else (150, 50, 50))
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
    if not grid or not grid[0]: return
        
    grid_top, available_w, available_h = y + 60, w - 16, h - 68
    rows, cols = len(grid), len(grid[0])
    cell_size = max(4, min(available_w // cols, available_h // rows))
    
    offset_x = x + (w - cols * cell_size) // 2
    offset_y = grid_top + (available_h - rows * cell_size) // 2
    
    c_map = {'A': (50,255,100), '1': (50,255,100), 'a': (0,160,50), 'B': (60,180,255), '2': (60,180,255), 'b': (0,80,180), '*': (255,90,50), '#': (70,70,75)}
    if game_data["my_side"] in {"B", "2"}:
        c_map = {'A': (60,180,255), '1': (60,180,255), 'a': (0,80,180), 'B': (50,255,100), '2': (50,255,100), 'b': (0,160,50), '*': (255,90,50), '#': (70,70,75)}
        
    for r in range(rows):
        for c in range(cols):
            color = c_map.get(grid[r][c], (32, 32, 35))
            c_rect = (offset_x + c * cell_size, offset_y + r * cell_size, cell_size, cell_size)
            pygame.draw.rect(screen, color, c_rect)
            if cell_size >= 12: pygame.draw.rect(screen, (45, 45, 50), c_rect, 1)

def run_visualizer():
    pygame.init()
    pygame.font.init()
    font_global = pygame.font.SysFont("consolas", 16, bold=True)
    font_panel_bold = pygame.font.SysFont("consolas", 13, bold=True)
    font_panel_small = pygame.font.SysFont("consolas", 11)
    
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("🐍 Multi-Match Visualizer - V6.1 Blindado")
    clock = pygame.time.Clock()
    running = True
    
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
                
        screen.fill((12, 12, 14))
        
        with visual_lock:
            global_status = visual_state["status"]
            games_snapshot = list(visual_state["games"].values())
            
        pygame.draw.rect(screen, (15, 15, 18), (0, 0, WINDOW_WIDTH, HEADER_HEIGHT))
        pygame.draw.line(screen, (60, 60, 70), (0, HEADER_HEIGHT), (WINDOW_WIDTH, HEADER_HEIGHT), 2)
        screen.blit(font_global.render("🐍 Bot V6.1 (Guardia de Legalidad Blindado)", True, (255, 255, 255)), (16, 14))
        screen.blit(font_global.render(f"Estado: {global_status} | Partidas activas: {len(games_snapshot)}", True, (160, 220, 255)), (WINDOW_WIDTH - 600, 14))
        
        num_games = len(games_snapshot)
        if num_games == 0:
            screen.blit(font_global.render("Esperando partidas activas...", True, (150, 150, 160)), (WINDOW_WIDTH // 2 - 150, WINDOW_HEIGHT // 2))
        else:
            g_rows, g_cols = _calculate_grid_layout(num_games)
            margin, board_area_top = 12, HEADER_HEIGHT + 12
            panel_w = (WINDOW_WIDTH - margin * (g_cols + 1)) // g_cols
            panel_h = (WINDOW_HEIGHT - board_area_top - margin * g_rows) // g_rows
            
            for idx, g_data in enumerate(games_snapshot[:g_rows * g_cols]):
                r_idx, c_idx = idx // g_cols, idx % g_cols
                px, py = margin + c_idx * (panel_w + margin), board_area_top + r_idx * (panel_h + margin)
                _draw_single_board_panel(screen, g_data, (px, py, panel_w, panel_h), (font_panel_bold, font_panel_small))
                
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    sys.exit()

# =====================================================================
# 11. SUITE DE AUTO-TEST Y ENTRY POINT
# =====================================================================
def _run_self_tests():
    # Test 1: Borde Superior (Fila 0) - Lado A
    b1 = parse_board("|   A           |\n|   a           |\n|   a           |\n" + "|\n".join(["|               |"]*12) + "|\n")
    m1 = choose_direction({"board": b1, "side": "A", "game_id": "t1", "remaining_moves": 290})
    assert m1 != "UP", f"Error crítico: eligió '{m1}' en fila 0 (Lado A)"
    
    # Test 2: Borde Superior (Fila 0) - Lado B (Caso exacto del log de Turno 28)
    b2 = parse_board("|           B   |\n|           b   |\n|           b   |\n" + "|\n".join(["|               |"]*12) + "|\n")
    m2 = choose_direction({"board": b2, "side": "B", "game_id": "t2", "remaining_moves": 273})
    assert m2 != "UP", f"Error crítico: eligió '{m2}' en fila 0 (Lado B)"

def main():
    _run_self_tests()
    if len(sys.argv) < 2:
        print("Uso: python botV5.5.py <TU_TOKEN_JWT>")
        sys.exit(1)
    ws_thread = threading.Thread(target=start_ws_thread, args=(sys.argv[1],), daemon=True)
    ws_thread.start()
    run_visualizer()

if __name__ == "__main__":
    main()