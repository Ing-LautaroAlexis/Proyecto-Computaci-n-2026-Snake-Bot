"""WebSocket/runtime layer for Snake V7.6.
Separated from the strategy engine so tests/trainers can import the bot without
loading pygame/websockets or counting UI code as decision logic.
"""
from __future__ import annotations
import asyncio
import json
import sys
import threading

BOT_CHOOSE = None
BOT_PARSE = None
BOT_IS_A = None
FOOD_DIGITS = frozenset("123456789")

visual_state = {"status": "Conectando al servidor...", "games": {}}
visual_lock = threading.Lock()


def _set_status(text):
    with visual_lock:
        visual_state["status"] = text


def _score_view(payload, side):
    p1 = payload.get("player_1", "Jugador 1")
    p2 = payload.get("player_2", "Jugador 2")
    s1 = payload.get("score_1", 0)
    s2 = payload.get("score_2", 0)
    return (p1, p2, s1, s2) if BOT_IS_A(side) else (p2, p1, s2, s1)


def _update_turn_view(payload):
    game_id = payload.get("game_id", "default")
    side = payload.get("side", "A")
    my_name, enemy_name, my_score, enemy_score = _score_view(payload, side)
    data = {
        "grid": BOT_PARSE(payload),
        "my_side": str(side),
        "my_name": my_name,
        "enemy_name": enemy_name,
        "my_score": my_score,
        "enemy_score": enemy_score,
        "remaining_moves": payload.get("remaining_moves", 300),
        "game_over": False,
        "winner": None,
    }
    with visual_lock:
        visual_state["games"][game_id] = data


def _winner_text(game, score_1, score_2):
    mine, enemy = (score_1, score_2) if BOT_IS_A(game["my_side"]) else (score_2, score_1)
    if mine > enemy:
        return f"{game['my_name']} (Ganador)", mine, enemy
    if enemy > mine:
        return f"{game['enemy_name']} (Ganador)", mine, enemy
    return "Empate", mine, enemy


def _update_game_over(payload):
    game_id = payload.get("game_id")
    with visual_lock:
        game = visual_state["games"].get(game_id)
        if game is None:
            return
        winner, mine, enemy = _winner_text(
            game, payload.get("score_1", 0), payload.get("score_2", 0)
        )
        game.update(game_over=True, winner=winner, my_score=mine, enemy_score=enemy)


async def _accept_challenge(payload, websocket):
    _set_status(f"Aceptando reto de {payload.get('opponent', 'Desconocido')}...")
    action = {"action": "accept_challenge", "data": {"challenge_id": payload.get("challenge_id")}}
    await websocket.send(json.dumps(action))


async def _play_turn(payload, websocket):
    _update_turn_view(payload)
    action = {
        "action": "move",
        "data": {
            "game_id": payload.get("game_id", "default"),
            "turn_token": payload.get("turn_token"),
            "direction": BOT_CHOOSE(payload),
        },
    }
    await websocket.send(json.dumps(action))


def _handle_sync_event(event_type, payload):
    handlers = {
        "list_users": lambda p: _set_status(f"Online ({len(p.get('users', []))} bots conectados)"),
        "game_over": _update_game_over,
        "error": lambda p: _set_status(f"Error: {p.get('Error', 'Error desconocido')}"),
    }
    handler = handlers.get(event_type)
    if handler:
        handler(payload)


async def _handle_event(event_type, payload, websocket):
    if event_type == "your_turn":
        await _play_turn(payload, websocket)
        return
    if event_type == "challenge":
        await _accept_challenge(payload, websocket)
        return
    _handle_sync_event(event_type, payload)


async def _listen(websocket):
    _set_status("Conectado. Esperando eventos...")
    async for message in websocket:
        event = json.loads(message)
        await _handle_event(event.get("event"), event.get("data", {}), websocket)


async def _connect_once(uri):
    import websockets
    _set_status("Conectando al servidor...")
    async with websockets.connect(uri) as websocket:
        await _listen(websocket)


async def _client_loop(token):
    uri = f"wss://server.codechallenge.net.ar/ws?token={token}"
    while True:
        try:
            await _connect_once(uri)
        except Exception as exc:
            _set_status(f"Desconectado ({exc}). Reintentando...")
            await asyncio.sleep(3)


def _start_ws_thread(token):
    asyncio.run(_client_loop(token))


def _get_token():
    if len(sys.argv) >= 2:
        return sys.argv[1]
    raise SystemExit("Uso: python botv7.6_v3.py <TU_TOKEN_JWT>")


def run_client(choose_direction, parse_turn_board, is_a_side, food_digits):
    global BOT_CHOOSE, BOT_PARSE, BOT_IS_A, FOOD_DIGITS
    BOT_CHOOSE = choose_direction
    BOT_PARSE = parse_turn_board
    BOT_IS_A = is_a_side
    FOOD_DIGITS = food_digits
    token = _get_token()
    thread = threading.Thread(target=_start_ws_thread, args=(token,), daemon=True)
    thread.start()
    from snake_visualizer import run_visualizer
    run_visualizer(visual_state, visual_lock, FOOD_DIGITS)
