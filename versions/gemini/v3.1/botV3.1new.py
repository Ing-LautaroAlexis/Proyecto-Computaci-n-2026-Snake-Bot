import sys
import time
import json
import asyncio
import threading
import multiprocessing as mp
from collections import deque
import pygame
import websockets

# =====================================================================
# 1. CONFIGURACIÓN GENERAL
# =====================================================================
CELL_SIZE = 30
HUD_HEIGHT = 90
FPS = 30
DEADLINE_TIMEOUT = 0.080  # 80ms de cálculo para margen de ping
INF = 10**9

DIRECTIONS = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}

# Control de subprocesos de ventanas en el proceso principal
active_game_queues = {}
bot_histories = {}
TT = {}
SEARCH_ABORTED = False

# =====================================================================
# 2. PROCESO VISUAL INDEPENDIENTE (1 Ventana por Partida)
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

def run_single_game_window(game_id, data_queue):
    """Función que corre en un subproceso aislado con su propia ventana Pygame."""
    pygame.init()
    pygame.font.init()
    
    font_main = pygame.font.SysFont("consolas", 16, bold=True)
    font_small = pygame.font.SysFont("consolas", 13)
    
    screen = None
    clock = pygame.time.Clock()
    running = True
    
    state = {
        "grid": [],
        "my_side": "A",
        "my_name": "Mi Bot",
        "enemy_name": "Rival",
        "my_score": 0,
        "enemy_score": 0,
        "remaining_moves": 300,
        "game_over": False,
        "winner": None
    }
    
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                
        # Consumir todas las actualizaciones enviadas por el WebSocket
        while not data_queue.empty():
            try:
                update = data_queue.get_nowait()
                state.update(update)
            except:
                break
                
        grid = state.get("grid", [])
        if grid and grid[0]:
            rows, cols = len(grid), len(grid[0])
            w = cols * CELL_SIZE
            h = rows * CELL_SIZE + HUD_HEIGHT
            
            if screen is None:
                screen = pygame.display.set_mode((w, h))
                pygame.display.set_caption(f"🐍 vs {state['enemy_name']} [{game_id[:6]}]")
                
            screen.fill((18, 18, 22))
            
            # Dibujar cuadrícula del tablero
            c_map = _build_side_color_map(state["my_side"])
            for r in range(rows):
                for c in range(cols):
                    val = grid[r][c]
                    color = c_map.get(val, (28, 28, 32))
                    rect = (c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE, CELL_SIZE)
                    pygame.draw.rect(screen, color, rect)
                    pygame.draw.rect(screen, (38, 38, 42), rect, 1)
                    
            # Dibujar HUD inferior
            hud_y = rows * CELL_SIZE
            pygame.draw.rect(screen, (12, 12, 14), (0, hud_y, w, HUD_HEIGHT))
            pygame.draw.line(screen, (50, 50, 60), (0, hud_y), (w, hud_y), 2)
            
            txt_p1 = f"🟢 {state['my_name']}: {state['my_score']} pts"
            txt_p2 = f"🔵 {state['enemy_name']}: {state['enemy_score']} pts"
            txt_turn = f"⏱️ Turnos: {300 - state['remaining_moves']}/300"
            
            screen.blit(font_main.render(txt_p1, True, (50, 255, 100)), (10, hud_y + 8))
            screen.blit(font_main.render(txt_p2, True, (60, 180, 255)), (10, hud_y + 30))
            screen.blit(font_small.render(txt_turn, True, (200, 200, 200)), (w - 180, hud_y + 8))
            
            if state["game_over"] and state.get("winner"):
                screen.blit(font_main.render(f"🏆 {state['winner']}", True, (255, 215, 0)), (10, hud_y + 56))
                
            pygame.display.flip()
            
        clock.tick(FPS)
        
    pygame.quit()

# =====================================================================
# 3. MOTOR TOPOLÓGICO Y CEREBRO (V4)
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

    queue = deque([start_pos])
    distances = {start_pos: 0}
    effective_exits = 0
    tail_reachable = False
    
    while queue:
        curr = queue.popleft()
        dist = distances[curr]
        
        walkable_neighbors = 0
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if not is_pos_inside(grid, npos):
                continue
                
            cell = grid[npos[0]][npos[1]]
            is_walkable = (cell in {" ", "*"}) or (npos == tail_pos)
            
            if is_walkable:
                walkable_neighbors += 1
                if npos not in distances:
                    distances[npos] = dist + 1
                    queue.append(npos)
                    if npos == tail_pos:
                        tail_reachable = True
                        
        if curr == start_pos:
            effective_exits = walkable_neighbors

    space = len(distances)
    is_pocket_trap = (space <= my_len + 1) and not tail_reachable
    return space, effective_exits, tail_reachable, is_pocket_trap, distances

def analyze_corridor_chokepoints(grid, my_head, en_head, my_body, en_body):
    if not en_head or not my_head:
        return False, None, False
        
    en_tail = en_body[-1] if en_body else None
    en_space, en_exits, en_tail_reach, en_trap, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    
    if en_exits <= 2 and en_space < (len(grid) * len(grid[0]) // 2):
        for pos, dist_en in en_dists.items():
            open_connections = 0
            for dr, dc in DIRECTIONS.values():
                npos = (pos[0] + dr, pos[1] + dc)
                if is_pos_inside(grid, npos) and grid[npos[0]][npos[1]] in {" ", "*"} and npos not in en_dists:
                    open_connections += 1
                    
            if open_connections >= 2:
                dist_my = abs(my_head[0] - pos[0]) + abs(my_head[1] - pos[1])
                if dist_my <= dist_en:
                    return True, pos, True
                    
    return False, None, False

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

def evaluate_state_v4(grid, my_body, en_body, my_score, en_score, remaining, food_list):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None
    
    if not my_head: return -INF
    if not en_head: return INF
        
    my_tail = my_body[-1] if my_body else None
    en_tail = en_body[-1] if en_body else None
    
    my_space, my_exits, my_tail_reach, my_pocket_trap, my_dists = analyze_topology(grid, my_head, len(my_body), my_tail)
    en_space, en_exits, en_tail_reach, en_pocket_trap, en_dists = analyze_topology(grid, en_head, len(en_body), en_tail)
    
    if my_pocket_trap: return -600000 + (my_space * 100)
    if en_pocket_trap: return 600000 - (en_space * 100)
        
    can_cut, door_pos, is_lethal = analyze_corridor_chokepoints(grid, my_head, en_head, my_body, en_body)
    choke_bonus = 0
    if can_cut and door_pos:
        dist_to_door = abs(my_head[0] - door_pos[0]) + abs(my_head[1] - door_pos[1])
        choke_bonus = 400000 if dist_to_door == 0 else (200000 - dist_to_door * 5000)
            
    score_diff = my_score - en_score
    base_score = score_diff * 10000
    
    food_pull = 0
    for f in food_list:
        md = my_dists.get(f, INF)
        ed = en_dists.get(f, INF)
        if md < ed: food_pull += (350 - md * 6)
        elif ed < md: food_pull -= (200 - ed * 5)
        else:
            if md != INF: food_pull += (80 - md * 5)
                
    my_territory = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] not in {"#", "A", "B", "a", "b"}:
                md = my_dists.get((r, c), INF)
                ed = en_dists.get((r, c), INF)
                if md < ed: my_territory += 1
                    
    mobility_score = (my_exits * 150) + min(my_space, 50) * 10
    if my_tail_reach and len(my_body) > 5:
        mobility_score += 150
        
    if remaining < 30:
        if score_diff > 0:
            return base_score + (my_space * 60) + (my_exits * 300) + choke_bonus
        return base_score + (food_pull * 4) + (my_territory * 15) + choke_bonus
    elif remaining < 120:
        return base_score + (food_pull * 2) + (my_territory * 20) + mobility_score + choke_bonus
    return base_score + food_pull + (my_territory * 15) + mobility_score + choke_bonus

def get_ordered_moves_v4(grid, head, body, other_body, food_list, en_head):
    moves = get_legal_moves_raw(grid, head, body, other_body)
    if not moves:
        return []
    can_cut, door_pos, _ = analyze_corridor_chokepoints(grid, head, en_head, body, other_body)
    
    def move_priority(item):
        _, npos = item
        score = 0
        if can_cut and door_pos and npos == door_pos: score += 100000
        if npos in food_list: score += 5000
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
        tuple(sorted(food_list)), remaining // 4
    ))
    
    if state_hash in TT and TT[state_hash]['depth'] >= depth:
        return TT[state_hash]['score']
        
    if depth == 0 or len(my_body) == 0 or len(en_body) == 0:
        return evaluate_state_v4(grid, my_body, en_body, my_score, en_score, remaining, food_list)
        
    if is_my_turn:
        best = -INF
        moves = get_ordered_moves_v4(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
        if not moves:
            return evaluate_state_v4(grid, my_body, en_body, my_score, en_score, remaining, food_list)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list)
            val = alpha_beta(grid, depth - 1, alpha, beta, False, my_body, en_body, deadline, n_score, en_score, remaining, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
            if SEARCH_ABORTED: return 0
            best = max(best, val)
            alpha = max(alpha, best)
            if beta <= alpha: break
                
        TT[state_hash] = {'score': best, 'depth': depth}
        return best
    else:
        best = INF
        moves = get_ordered_moves_v4(grid, en_body[0], en_body, my_body, food_list, my_body[0] if my_body else None)
        if not moves:
            return evaluate_state_v4(grid, my_body, en_body, my_score, en_score, remaining, food_list)
            
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, en_body, npos, False, en_score, food_list)
            val = alpha_beta(grid, depth - 1, alpha, beta, True, my_body, en_body, deadline, my_score, n_score, remaining - 1, food_list)
            unmake_move(grid, en_body, tail, pt, ptr, eaten, False, npos, food_list)
            
            if SEARCH_ABORTED: return 0
            best = min(best, val)
            beta = min(beta, best)
            if beta <= alpha: break
                
        TT[state_hash] = {'score': best, 'depth': depth}
        return best

def _get_current_direction(grid, head, side):
    if not head: return None
    body_chars = {"a"} if str(side) in {"A", "1"} else {"b"}
    for d_name, (dr, dc) in DIRECTIONS.items():
        back_r, back_c = head[0] - dr, head[1] - dc
        if is_pos_inside(grid, (back_r, back_c)) and grid[back_r][back_c] in body_chars:
            return d_name
    return None

def emergency_safety_fallback(grid, my_body, en_body):
    if not my_body: return "UP"
    head = my_body[0]
    best_dir = "UP"
    max_space = -1
    
    for name, (dr, dc) in DIRECTIONS.items():
        npos = (head[0] + dr, head[1] + dc)
        if not is_pos_inside(grid, npos): continue
        cell = grid[npos[0]][npos[1]]
        if cell in {" ", "*"} or (npos == my_body[-1]):
            space, exits, reach, trap, _ = analyze_topology(grid, npos, len(my_body), my_body[-1])
            score = space * 10 + exits * 50 + (1000 if reach else 0) - (5000 if trap else 0)
            if score > max_space:
                max_space = score
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
    if not my_body: return "UP"
        
    is_p1 = str(side) in {"A", "1"}
    my_score = game_data.get("score_1", 0) if is_p1 else game_data.get("score_2", 0)
    en_score = game_data.get("score_2", 0) if is_p1 else game_data.get("score_1", 0)
    remaining = game_data.get("remaining_moves", 300)
    food_list = find_food(grid)
    
    current_dir = _get_current_direction(grid, my_body[0], side)
    candidates = get_ordered_moves_v4(grid, my_body[0], my_body, en_body, food_list, en_body[0] if en_body else None)
    
    if not candidates: return emergency_safety_fallback(grid, my_body, en_body)
    if len(candidates) == 1: return candidates[0][0]
        
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
            score = alpha_beta(grid, depth - 1, -INF, INF, False, my_body, en_body, deadline, n_score, en_score, remaining, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
            if SEARCH_ABORTED: break
                
            if score > layer_best_score or (score == layer_best_score and move_name == current_dir):
                layer_best_score = score
                layer_best_move = move_name
                
        if not SEARCH_ABORTED:
            best_move = layer_best_move
            candidates.sort(key=lambda x: x[0] == best_move, reverse=True)
            depth += 1
        else:
            break
            
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
# 4. WEBSOCKET CLIENT & DESPACHADOR DE VENTANAS
# =====================================================================
def _extract_turn_scores(payload, side):
    p1 = payload.get("player_1", "Jugador 1")
    p2 = payload.get("player_2", "Jugador 2")
    s1, s2 = payload.get("score_1", 0), payload.get("score_2", 0)
    if str(side) in {"A", "1"}: return p1, p2, s1, s2
    return p2, p1, s2, s1

def _ensure_window_running(game_id):
    """Crea un nuevo subproceso y ventana OS si esta partida no tiene una."""
    if game_id not in active_game_queues:
        q = mp.Queue()
        active_game_queues[game_id] = q
        p = mp.Process(target=run_single_game_window, args=(game_id, q), daemon=True)
        p.start()
    return active_game_queues[game_id]

async def _handle_challenge(payload, websocket):
    challenge_id = payload.get("challenge_id")
    opponent = payload.get("opponent", "Desconocido")
    print(f"[*] Desafío recibido de {opponent}. Aceptando...")
    accept_action = {
        "action": "accept_challenge",
        "data": {"challenge_id": challenge_id}
    }
    await websocket.send(json.dumps(accept_action))

async def _handle_your_turn(payload, websocket):
    game_id = payload.get("game_id", "default")
    side = payload.get("side", "A")
    my_name, enemy_name, my_score, enemy_score = _extract_turn_scores(payload, side)
    grid = parse_board(payload.get("board", ""))
    
    # Enviar datos a la ventana individual correspondiente
    q = _ensure_window_running(game_id)
    q.put({
        "grid": grid,
        "my_side": str(side),
        "my_name": my_name,
        "enemy_name": enemy_name,
        "my_score": my_score,
        "enemy_score": enemy_score,
        "remaining_moves": payload.get("remaining_moves", 300),
        "game_over": False
    })
    
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
    if game_id and game_id in active_game_queues:
        active_game_queues[game_id].put({
            "game_over": True,
            "winner": f"Partida terminada ({s1} vs {s2})"
        })

async def _process_ws_event(event_type, payload, websocket):
    if event_type == "your_turn":
        await _handle_your_turn(payload, websocket)
    elif event_type == "challenge":
        await _handle_challenge(payload, websocket)
    elif event_type == "game_over":
        _handle_game_over(payload)
    elif event_type == "list_users":
        print(f"[*] Online: {len(payload.get('users', []))} bots activos")

async def _connect_and_stream(uri):
    print("[*] Conectando al servidor WebSocket...")
    async with websockets.connect(uri) as websocket:
        print("[+] Conectado exitosamente. Esperando partidas...")
        async for message in websocket:
            event_data = json.loads(message)
            await _process_ws_event(event_data.get("event"), event_data.get("data", {}), websocket)

async def websocket_client_loop(token):
    uri = f"wss://server.codechallenge.net.ar/ws?token={token}"
    while True:
        try:
            await _connect_and_stream(uri)
        except Exception as e:
            print(f"[-] Desconectado ({e}). Reintentando en 3s...")
            await asyncio.sleep(3)

# =====================================================================
# 5. ENTRADA PRINCIPAL
# =====================================================================
if __name__ == "__main__":
    mp.freeze_support()  # Requerido para Windows al usar multiprocessing
    
    if len(sys.argv) < 2:
        print("Uso: python bot_multi_windows.py <TU_TOKEN_JWT>")
        sys.exit(1)
        
    bot_token = sys.argv[1]
    
    # El proceso principal se queda escuchando y levantando ventanas por partida
    asyncio.run(websocket_client_loop(bot_token))