import sys
import time
import json
import asyncio
import threading
from collections import deque
import pygame
import websockets

# =====================================================================
# 1. CONFIGURACIÓN VISUAL Y CONSTANTES
# =====================================================================
CELL_SIZE = 30
HUD_HEIGHT = 90
FPS = 30

DEADLINE_TIMEOUT = 0.14  # Margen de seguridad estricto para red

DIRECTIONS = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}
INF = 10**9

current_visual_state = {
    "grid": [],
    "my_side": "A",
    "my_name": "Bot V3 (Differential)",
    "enemy_name": "Rival",
    "my_score": 0,
    "enemy_score": 0,
    "remaining_moves": 300,
    "status": "Esperando conexión...",
    "game_over": False,
    "winner": None
}
visual_lock = threading.Lock()

bot_history = {
    "game_id": None,
    "my_path": deque(),
    "en_path": deque()
}

TT = {}
SEARCH_ABORTED = False

# =====================================================================
# 2. UTILIDADES BASE Y PARSEO
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

# =====================================================================
# 3. ENGINE: SIMULADOR EXACTO (Cuerpo, Cola, Puntuación, Turnos)
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
        if not found: break
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
    
    if bot_history["game_id"] != game_id:
        bot_history["game_id"] = game_id
        bot_history["my_path"].clear()
        bot_history["en_path"].clear()
        
    if head_my and (not bot_history["my_path"] or bot_history["my_path"][-1] != head_my):
        bot_history["my_path"].append(head_my)
    if head_en and (not bot_history["en_path"] or bot_history["en_path"][-1] != head_en):
        bot_history["en_path"].append(head_en)
        
    if len(bot_history["my_path"]) < my_cells and head_my:
        bot_history["my_path"] = _trace_full_snake(grid, head_my, "a" if is_p1 else "b")
    if len(bot_history["en_path"]) < en_cells and head_en:
        bot_history["en_path"] = _trace_full_snake(grid, head_en, "b" if is_p1 else "a")
        
    while len(bot_history["my_path"]) > my_cells: bot_history["my_path"].popleft()
    while len(bot_history["en_path"]) > en_cells: bot_history["en_path"].popleft()
    
    return deque(reversed(bot_history["my_path"])), deque(reversed(bot_history["en_path"]))

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
# 4. ANÁLISIS TÁCTICO: ESPACIO-TIEMPO Y EVALUACIÓN
# =====================================================================
def get_body_expiration_map(my_body, en_body):
    exp = {}
    for i, pos in enumerate(my_body):
        exp[pos] = len(my_body) - 1 - i
    for i, pos in enumerate(en_body):
        exp[pos] = len(en_body) - 1 - i
    return exp

def space_time_bfs(grid, start_pos, expiration_map):
    if not start_pos: return 0, {}, False
    queue = deque([(start_pos, 0)])
    visited = {start_pos: 0}
    tail_reachable = False
    
    while queue:
        curr, dist = queue.popleft()
        for dr, dc in DIRECTIONS.values():
            npos = (curr[0] + dr, curr[1] + dc)
            if not is_pos_inside(grid, npos): continue
            
            cell = grid[npos[0]][npos[1]]
            is_free = False
            
            if cell in {" ", "*"}:
                is_free = True
            elif npos in expiration_map:
                if dist + 1 > expiration_map[npos]:
                    is_free = True
                    
            if is_free and npos not in visited:
                visited[npos] = dist + 1
                queue.append((npos, dist + 1))
                if npos in expiration_map and expiration_map[npos] == 0:
                    tail_reachable = True
                    
    return len(visited), visited, tail_reachable

def evaluate_state_v3(grid, my_body, en_body, my_score, en_score, remaining, food_list):
    my_head = my_body[0] if my_body else None
    en_head = en_body[0] if en_body else None
    if not my_head: return -INF
    if not en_head: return INF
    
    exp_map = get_body_expiration_map(my_body, en_body)
    my_space, my_dists, my_cycle = space_time_bfs(grid, my_head, exp_map)
    en_space, en_dists, en_cycle = space_time_bfs(grid, en_head, exp_map)
    
    # 1. Supervivencia Crítica
    if my_space <= len(my_body) and not my_cycle:
        return -500000 + (my_space * 100)
    if en_space <= len(en_body) and not en_cycle:
        return 500000 - (en_space * 100)
        
    # 2. SCORE DIFFERENTIAL (El Núcleo Estratégico)
    score_diff = my_score - en_score
    base_score = score_diff * 10000
    
    # 3. Utilidad Continua de Comida (Score Swing)
    food_pull = 0
    for f in food_list:
        md = my_dists.get(f, INF)
        ed = en_dists.get(f, INF)
        
        if md < ed:
            # Swing de +200 (Yo gano 100, él pierde 100 potenciales)
            food_pull += (300 - md * 5)
        elif ed < md:
            food_pull -= (200 - ed * 5)
        else:
            if md != INF: food_pull += (50 - md * 5)
            
    # 4. Control de Territorio
    my_territory = 0
    for r in range(len(grid)):
        for c in range(len(grid[0])):
            if grid[r][c] not in {"#", "A", "B", "a", "b"}:
                md = my_dists.get((r, c), INF)
                ed = en_dists.get((r, c), INF)
                if md < ed: my_territory += 1
                
    # 5. Valor Acotado del Ciclo (Ya no vale +5000)
    cycle_bonus = min(my_space, 40) * 10 if my_cycle else 0
    
    # 6. Modos Estratégicos Dinámicos
    if remaining < 30:
        if score_diff > 0:
            # Endgame Ganando: Defensa pura
            return base_score + (my_space * 50) + cycle_bonus + (my_territory * 5)
        else:
            # Endgame Perdiendo: Caza desesperada
            return base_score + (food_pull * 3) + (my_territory * 10)
    elif remaining < 120:
        # Mid-Late Game: Conversión
        return base_score + (food_pull * 2) + (my_territory * 20) + cycle_bonus
    else:
        # Early Game: Expansión e intercepción
        return base_score + food_pull + (my_territory * 15) + cycle_bonus + (my_space * 2)

# =====================================================================
# 5. MOTOR DE BÚSQUEDA Y ALPHA-BETA
# =====================================================================
def get_ordered_moves(grid, head, body):
    moves = []
    my_tail = body[-1] if len(body) > 0 else None
    for name, (dr, dc) in DIRECTIONS.items():
        npos = (head[0] + dr, head[1] + dc)
        if is_pos_inside(grid, npos):
            val = grid[npos[0]][npos[1]]
            if val in {" ", "*"}:
                moves.append((name, npos))
            # Permite seguir la propia cola (asumiendo que se mueve y no come)
            elif npos == my_tail and val != "*": 
                moves.append((name, npos))
    return moves

def alpha_beta(grid, depth, alpha, beta, is_my_turn, my_body, en_body, deadline, my_score, en_score, remaining, food_list):
    global SEARCH_ABORTED
    if time.monotonic() >= deadline:
        SEARCH_ABORTED = True
        return 0
        
    state_hash = hash((tuple(my_body), tuple(en_body), is_my_turn, tuple(food_list), remaining // 5))
    if state_hash in TT and TT[state_hash]['depth'] >= depth:
        return TT[state_hash]['score']
        
    if depth == 0 or len(my_body) == 0 or len(en_body) == 0:
        return evaluate_state_v3(grid, my_body, en_body, my_score, en_score, remaining, food_list)
        
    if is_my_turn:
        best = -INF
        moves = get_ordered_moves(grid, my_body[0], my_body)
        if not moves: return evaluate_state_v3(grid, my_body, en_body, my_score, en_score, remaining, food_list)
        
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list)
            val = alpha_beta(grid, depth-1, alpha, beta, False, my_body, en_body, deadline, n_score, en_score, remaining, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
            if SEARCH_ABORTED: return 0
            best = max(best, val)
            alpha = max(alpha, best)
            if beta <= alpha: break
            
        TT[state_hash] = {'score': best, 'depth': depth}
        return best
    else:
        best = INF
        moves = get_ordered_moves(grid, en_body[0], en_body)
        if not moves: return evaluate_state_v3(grid, my_body, en_body, my_score, en_score, remaining, food_list)
        
        for m, npos in moves:
            tail, pt, ptr, eaten, n_score = make_move(grid, en_body, npos, False, en_score, food_list)
            # El turno completo cierra aquí, se reduce remaining
            val = alpha_beta(grid, depth-1, alpha, beta, True, my_body, en_body, deadline, my_score, n_score, remaining - 1, food_list)
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

def choose_direction(game_data):
    global TT, SEARCH_ABORTED
    TT.clear()
    SEARCH_ABORTED = False
    
    deadline = time.monotonic() + DEADLINE_TIMEOUT
    grid = parse_board(game_data.get("board", ""))
    side = game_data.get("side", "A")
    
    my_body, en_body = get_bodies(game_data.get("game_id"), grid, side)
    if not my_body: return "UP"
    
    is_p1 = str(side) in {"A", "1"}
    my_score = game_data.get("score_1", 0) if is_p1 else game_data.get("score_2", 0)
    en_score = game_data.get("score_2", 0) if is_p1 else game_data.get("score_1", 0)
    remaining = game_data.get("remaining_moves", 300)
    food_list = find_food(grid)
    
    current_dir = _get_current_direction(grid, my_body[0], side)
    candidates = get_ordered_moves(grid, my_body[0], my_body)
    
    if not candidates: return "UP"
    if len(candidates) == 1: return candidates[0][0]
    
    best_move = candidates[0][0]
    depth = 1
    
    while time.monotonic() < deadline and depth <= 16:
        SEARCH_ABORTED = False
        layer_best_move = best_move
        layer_best_score = -INF
        
        for move_name, npos in candidates:
            tail, pt, ptr, eaten, n_score = make_move(grid, my_body, npos, True, my_score, food_list)
            score = alpha_beta(grid, depth-1, -INF, INF, False, my_body, en_body, deadline, n_score, en_score, remaining, food_list)
            unmake_move(grid, my_body, tail, pt, ptr, eaten, True, npos, food_list)
            
            if SEARCH_ABORTED: break
            
            if score > layer_best_score or (score == layer_best_score and move_name == current_dir):
                layer_best_score = score
                layer_best_move = move_name
                
        if not SEARCH_ABORTED:
            best_move = layer_best_move
            # Pone el mejor candidato de la capa actual al principio
            candidates.sort(key=lambda x: x[0] == best_move, reverse=True)
            depth += 1
        else:
            break
            
    return best_move

# =====================================================================
# 6. CLIENTE WEBSOCKET Y SINCRONIZACIÓN
# =====================================================================
def _handle_list_users(payload):
    users = payload.get("users", [])
    with visual_lock:
        current_visual_state["status"] = f"Online ({len(users)} bots activos)"

async def _handle_challenge(payload, websocket):
    challenge_id = payload.get("challenge_id")
    opponent = payload.get("opponent", "Desconocido")
    with visual_lock:
        current_visual_state["status"] = f"Aceptando reto de {opponent}..."
        current_visual_state["enemy_name"] = opponent
        current_visual_state["game_over"] = False
        current_visual_state["winner"] = None
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
    side = payload.get("side", "A")
    my_name, enemy_name, my_score, enemy_score = _extract_turn_scores(payload, side)
    grid = parse_board(payload.get("board", ""))
    with visual_lock:
        current_visual_state["grid"] = grid
        current_visual_state["my_side"] = side
        current_visual_state["my_name"] = my_name
        current_visual_state["enemy_name"] = enemy_name
        current_visual_state["my_score"] = my_score
        current_visual_state["enemy_score"] = enemy_score
        current_visual_state["remaining_moves"] = payload.get("remaining_moves", 300)
        current_visual_state["status"] = f"Jugando contra {enemy_name}"
        current_visual_state["game_over"] = False
    
    move_dir = choose_direction(payload)
    
    response = {
        "action": "move",
        "data": {
            "game_id": payload.get("game_id"),
            "turn_token": payload.get("turn_token"),
            "direction": move_dir
        }
    }
    await websocket.send(json.dumps(response))

def _determine_winner(my_score, enemy_score, my_name, enemy_name):
    if my_score > enemy_score: return f"{my_name} (Ganador)"
    if enemy_score > my_score: return f"{enemy_name} (Ganador)"
    return "Empate"

def _handle_game_over(payload):
    with visual_lock:
        current_visual_state["game_over"] = True
        side = current_visual_state["my_side"]
        s1, s2 = payload.get("score_1", 0), payload.get("score_2", 0)
        if str(side) in {"A", "1"}:
            current_visual_state["my_score"], current_visual_state["enemy_score"] = s1, s2
        else:
            current_visual_state["my_score"], current_visual_state["enemy_score"] = s2, s1
        my_s = current_visual_state["my_score"]
        en_s = current_visual_state["enemy_score"]
        my_n = current_visual_state["my_name"]
        en_n = current_visual_state["enemy_name"]
        current_visual_state["winner"] = _determine_winner(my_s, en_s, my_n, en_n)
        current_visual_state["status"] = "Partida finalizada."

def _handle_ws_error(payload):
    err_msg = payload.get("Error", "Error desconocido")
    with visual_lock:
        current_visual_state["status"] = f"Error: {err_msg}"

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
    with visual_lock:
        current_visual_state["status"] = "Conectado. Esperando eventos..."
    async for message in websocket:
        event_data = json.loads(message)
        await _process_ws_event(event_data.get("event"), event_data.get("data", {}), websocket)

async def _connect_and_stream(uri):
    with visual_lock:
        current_visual_state["status"] = "Conectando al servidor..."
    async with websockets.connect(uri) as websocket:
        await _listen_ws_stream(websocket)

async def websocket_client_loop(token):
    uri = f"wss://server.codechallenge.net.ar/ws?token={token}"
    while True:
        try:
            await _connect_and_stream(uri)
        except Exception as e:
            with visual_lock:
                current_visual_state["status"] = f"Desconectado ({e}). Reintentando..."
            await asyncio.sleep(3)

def start_ws_thread(token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(websocket_client_loop(token))

# =====================================================================
# 7. MOTOR VISUAL PYGAME
# =====================================================================
def _build_side_color_map(my_side):
    is_a = my_side in {'A', '1'}
    p1_head = (50, 255, 50) if is_a else (50, 150, 255)
    p1_body = (0, 150, 0) if is_a else (0, 50, 150)
    p2_head = (50, 150, 255) if is_a else (50, 255, 50)
    p2_body = (0, 50, 150) if is_a else (0, 150, 0)
    return {
        '*': (255, 100, 50), '#': (80, 80, 80),
        'A': p1_head, '1': p1_head, 'a': p1_body,
        'B': p2_head, '2': p2_head, 'b': p2_body
    }

def _draw_board_grid(screen, grid, my_side):
    if not grid: return
    c_map = _build_side_color_map(my_side)
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            color = c_map.get(val, (30, 30, 30))
            rect = (c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, (50, 50, 50), rect, 1)

def _copy_visual_snapshot():
    with visual_lock:
        return {
            "grid": [row[:] for row in current_visual_state["grid"]],
            "my_side": str(current_visual_state["my_side"]),
            "my_name": current_visual_state["my_name"],
            "enemy_name": current_visual_state["enemy_name"],
            "my_score": current_visual_state["my_score"],
            "enemy_score": current_visual_state["enemy_score"],
            "moves_left": current_visual_state["remaining_moves"],
            "status": current_visual_state["status"],
            "game_over": current_visual_state["game_over"],
            "winner": current_visual_state["winner"]
        }

def _draw_hud(screen, state, font_main, font_small, width, hud_y):
    pygame.draw.rect(screen, (20, 20, 20), (0, hud_y, width, HUD_HEIGHT))
    pygame.draw.line(screen, (255, 255, 255), (0, hud_y), (width, hud_y), 2)
    txt_p1 = f"🟢 {state['my_name']}: {state['my_score']} pts"
    txt_p2 = f"🔵 {state['enemy_name']}: {state['enemy_score']} pts"
    txt_turn = f"⏱️ Turnos: {300 - state['moves_left']}/300"
    txt_status = f"Estado: {state['status']}"
    screen.blit(font_main.render(txt_p1, True, (50, 255, 50)), (10, hud_y + 8))
    screen.blit(font_main.render(txt_p2, True, (50, 150, 255)), (10, hud_y + 32))
    screen.blit(font_main.render(txt_turn, True, (255, 255, 255)), (width - 190, hud_y + 8))
    screen.blit(font_small.render(txt_status, True, (200, 200, 200)), (10, hud_y + 60))
    if state["game_over"] and state["winner"]:
        surf_win = font_main.render(f"🏆 {state['winner']}", True, (255, 215, 0))
        screen.blit(surf_win, (width - 280, hud_y + 32))

def _handle_pygame_events():
    for event in pygame.event.get():
        if event.type == pygame.QUIT: return False
    return True

def run_visualizer(rows=16, cols=20):
    pygame.init()
    pygame.font.init()
    font_main = pygame.font.SysFont("consolas", 18, bold=True)
    font_small = pygame.font.SysFont("consolas", 14)
    width, height = cols * CELL_SIZE, rows * CELL_SIZE + HUD_HEIGHT
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("🐍 Code Challenge - Bot V3 Differential")
    clock = pygame.time.Clock()
    running = True
    while running:
        running = _handle_pygame_events()
        screen.fill((30, 30, 30))
        state = _copy_visual_snapshot()
        _draw_board_grid(screen, state["grid"], state["my_side"])
        _draw_hud(screen, state, font_main, font_small, width, rows * CELL_SIZE)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    sys.exit()

# =====================================================================
# 8. ENTRADA PRINCIPAL
# =====================================================================
def _validate_and_get_token():
    if len(sys.argv) < 2:
        print("Uso: python bot_v3.py <TU_TOKEN_JWT>")
        sys.exit(1)
    return sys.argv[1]

def main():
    bot_token = _validate_and_get_token()
    ws_thread = threading.Thread(target=start_ws_thread, args=(bot_token,), daemon=True)
    ws_thread.start()
    run_visualizer(rows=15, cols=15)

if __name__ == "__main__":
    main()