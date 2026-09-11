import asyncio
import json
import sys
import websockets
import os
import pygame

# ==========================================
# 1. EL MOTOR GRÁFICO (PYGAME MEJORADO)
# ==========================================
CELL_SIZE = 30  
HUD_HEIGHT = 80 # Espacio extra abajo para los puntajes
screen = None
font = None

def draw_board(game_data):
    """Dibuja el tablero, la cuadrícula y el marcador de puntos."""
    global screen, font
    
    board_raw = game_data.get("board", "")
    grid = board_raw.strip().split("\n")
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    
    # 1. Inicializar la ventana si no existe
    if screen is None:
        pygame.init()
        pygame.font.init()
        font = pygame.font.SysFont("consolas", 18, bold=True)
        # La ventana ahora es más alta para que quepa el texto
        screen = pygame.display.set_mode((cols * CELL_SIZE, rows * CELL_SIZE + HUD_HEIGHT))
        pygame.display.set_caption("🐍 Torneo de Snake En Vivo")

    # 2. Evitar que la ventana diga "(No responde)" en Windows
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

    # 3. Dibujar el mapa y las cuadrículas
    screen.fill((30, 30, 30))
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            color = (30, 30, 30) 
            if val == '*':
                color = (255, 100, 50)    # Naranja/Rojo (Comida)
            elif val == '#':
                color = (100, 100, 100)   # Gris (Paredes)
            elif val == 'A' or val == '1':
                color = (50, 255, 50)     # Verde Claro (Jugador 1)
            elif val == 'a':
                color = (0, 150, 0)       # Verde Oscuro 
            elif val == 'B' or val == '2':
                color = (50, 150, 255)    # Azul Claro (Jugador 2)
            elif val == 'b':
                color = (0, 50, 150)      # Azul Oscuro

            rect = (c * CELL_SIZE, r * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(screen, color, rect)
            # Líneas de cuadrícula más claras (Gris 80 en lugar de 10)
            pygame.draw.rect(screen, (80, 80, 80), rect, 1)

    # 4. Dibujar el Marcador (HUD) en la parte inferior
    hud_rect = (0, rows * CELL_SIZE, cols * CELL_SIZE, HUD_HEIGHT)
    pygame.draw.rect(screen, (20, 20, 20), hud_rect)
    pygame.draw.line(screen, (255, 255, 255), (0, rows * CELL_SIZE), (cols * CELL_SIZE, rows * CELL_SIZE), 3)

    p1_name = game_data.get("player_1", "Jugador 1")
    p2_name = game_data.get("player_2", "Jugador 2")
    p1_score = game_data.get("score_1", 0)
    p2_score = game_data.get("score_2", 0)
    mi_bando = str(game_data.get("side", "A"))

    # Identificar quién eres tú para ponerle "(TÚ)"
    if mi_bando in ["A", "1"]:
        txt_p1 = f"🟢 {p1_name} (TÚ): {p1_score} pts"
        txt_p2 = f"🔵 {p2_name}: {p2_score} pts"
    else:
        txt_p1 = f"🟢 {p1_name}: {p1_score} pts"
        txt_p2 = f"🔵 {p2_name} (TÚ): {p2_score} pts"

    # Renderizar los textos en pantalla
    render_p1 = font.render(txt_p1, True, (50, 255, 50))
    render_p2 = font.render(txt_p2, True, (50, 150, 255))
    screen.blit(render_p1, (10, rows * CELL_SIZE + 15))
    screen.blit(render_p2, (10, rows * CELL_SIZE + 45))

    pygame.display.flip()

# ==========================================
# 2. EL CEREBRO DEL BOT (SISTEMA DE PUNTUACIÓN Y COMBATE)
# ==========================================
def parse_board(board_raw):
    if isinstance(board_raw, str):
        return [list(line.replace('\r', '')) for line in board_raw.strip().split("\n")]
    return [list(row) for row in board_raw]

def find_head(grid, side):
    targets = ['A', '1'] if str(side) in ['A', '1'] else ['B', '2']
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in targets:
                return (r, c)
    return (0, 0)

def find_enemy_head(grid, side):
    """Busca exactamente dónde está la cabeza del enemigo."""
    targets = ['B', '2'] if str(side) in ['A', '1'] else ['A', '1']
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val in targets:
                return (r, c)
    return None

def find_food(grid):
    positions = []
    for r, row in enumerate(grid):
        for c, val in enumerate(row):
            if val == "*":
                positions.append((r, c))
    return positions

def is_safe(grid, pos):
    r, c = pos
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    if r < 0 or r >= rows or c < 0 or c >= cols:
        return False
    return grid[r][c] in [' ', '*']

def count_free_space(grid, start_pos, max_spaces=300):
    """Mide cuánto espacio libre real hay en una dirección."""
    queue = [start_pos]
    visited = set([start_pos])
    count = 0
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    
    while queue and count < max_spaces:
        r, c = queue.pop(0)
        count += 1
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                if grid[nr][nc] in [' ', '*'] and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))
    return count

def get_real_distance_to_food(grid, start_pos, food_positions):
    """Calcula la distancia real a la comida ESQUIVANDO obstáculos (BFS)."""
    if not food_positions:
        return float('inf')
        
    queue = [(start_pos, 0)]
    visited = set([start_pos])
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    
    while queue:
        (r, c), dist = queue.pop(0)
        
        if (r, c) in food_positions:
            return dist
            
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                if grid[nr][nc] in [' ', '*'] and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append(((nr, nc), dist + 1))
                    
    return float('inf')

def evaluate_move(grid, next_pos, food_list, enemy_head):
    """
    EVALUADOR PONDERADO: Asigna un puntaje matemático a cada movimiento.
    """
    free_space = count_free_space(grid, next_pos, max_spaces=200)
    dist_to_food = get_real_distance_to_food(grid, next_pos, food_list)
    
    SCORE = 0
    
    # 1. SUPERVIVENCIA BÁSICA: Callejones sin salida
    if free_space < 15:
        SCORE -= 10000 
        
    # Premiar espacio disponible (+10 puntos por casilla)
    SCORE += (free_space * 10)
    
    # Premiar cercanía a la comida
    if dist_to_food != float('inf'):
        SCORE -= (dist_to_food * 5)
    else:
        SCORE -= 500

    # 2. DETECCIÓN DE ZONA DE MUERTE (Especial para evitar choques)
    if enemy_head:
        dist_to_enemy = abs(next_pos[0] - enemy_head[0]) + abs(next_pos[1] - enemy_head[1])
        # Si dar este paso nos deja al lado de la cabeza del rival, penalizamos fuertemente
        if dist_to_enemy == 1:
            SCORE -= 5000

    return SCORE

def choose_direction(game_data):
    board_raw = game_data.get("board", "")
    side = game_data.get("side", 1) 

    grid = parse_board(board_raw)
    head = find_head(grid, side)
    enemy_head = find_enemy_head(grid, side)
    food_list = find_food(grid)

    directions = {
        "UP": (head[0] - 1, head[1]),
        "DOWN": (head[0] + 1, head[1]),
        "LEFT": (head[0], head[1] - 1),
        "RIGHT": (head[0], head[1] + 1),
    }

    # 1. Filtrar solo movimientos que no causen muerte instantánea (paredes/cuerpos)
    safe_moves = {}
    for move_name, next_pos in directions.items():
        if is_safe(grid, next_pos):
            safe_moves[move_name] = next_pos

    if not safe_moves:
        return "UP" # Muerte inevitable

    # 2. Evaluar cada movimiento seguro y calcular su puntaje
    move_scores = {}
    for move_name, next_pos in safe_moves.items():
        move_scores[move_name] = evaluate_move(grid, next_pos, food_list, enemy_head)

    # 3. Elegir la dirección con el mayor puntaje
    best_move = max(move_scores, key=move_scores.get)

    return best_move

# ==========================================
# 3. CONEXIÓN A INTERNET
# ==========================================
async def run_bot(token):
    uri = f"wss://codechallenge-server.up.railway.app/ws?token={token}"
    print("Conectando al torneo...")

    async with websockets.connect(uri) as websocket:
        print("¡Bot fiero conectado! Esperando rival...")

        async for message in websocket:
            data = json.loads(message)
            event = data.get("event")
            payload = data.get("data", {})

            if event == "challenge":
                print(f"¡Desafío recibido! Aceptando...")
                await websocket.send(json.dumps({
                    "action": "accept_challenge",
                    "data": {"challenge_id": payload.get("challenge_id")}
                }))

            elif event == "your_turn":
                # Dibuja la pantalla con todos los datos
                draw_board(payload)
                direction = choose_direction(payload)

                await websocket.send(json.dumps({
                    "action": "move",
                    "data": {
                        "game_id": payload.get("game_id"),
                        "turn_token": payload.get("turn_token"),
                        "direction": direction
                    }
                }))

            elif event == "game_over":
                draw_board(payload)
                ganador = payload.get('winner')
                print(f"🚨 PARTIDA TERMINADA 🚨 ¡Ganador: {ganador}!")

            elif event == "error":
                print("Error:", payload)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python snake1.py TU_TOKEN")
        sys.exit(1)
    asyncio.run(run_bot(sys.argv[1]))