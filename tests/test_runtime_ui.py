from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
from threading import Lock
from unittest.mock import MagicMock, patch

import snake_runtime as runtime
import snake_visualizer as visualizer


class FakeWebSocket:
    def __init__(self, messages=None):
        self.sent = []
        self.messages = list(messages or [])

    async def send(self, message):
        self.sent.append(message)

    def __aiter__(self):
        self._iter = iter(self.messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeFont:
    def render(self, text, antialias, color):
        return (text, antialias, color)


class FakeScreen:
    def __init__(self):
        self.blit_calls = []
        self.fill_calls = []

    def blit(self, item, position):
        self.blit_calls.append((item, position))

    def fill(self, color):
        self.fill_calls.append(color)


class FakeDraw:
    def __init__(self):
        self.rect_calls = []
        self.line_calls = []

    def rect(self, *args, **kwargs):
        self.rect_calls.append((args, kwargs))

    def line(self, *args, **kwargs):
        self.line_calls.append((args, kwargs))


class FakeEventModule:
    def __init__(self, events):
        self.events = events

    def get(self):
        return self.events


class TestRuntime(unittest.TestCase):
    def setUp(self):
        runtime.visual_state["status"] = "x"
        runtime.visual_state["games"].clear()
        runtime.BOT_IS_A = lambda side: str(side).upper() in {"A", "1"}
        runtime.BOT_PARSE = lambda payload: [["A", "1", "B"]]
        runtime.BOT_CHOOSE = lambda payload: "right"

    def test_status_score_and_turn_view(self):
        runtime._set_status("ready")
        self.assertEqual(runtime.visual_state["status"], "ready")
        payload = {"player_1": "p1", "player_2": "p2", "score_1": 7, "score_2": 9}
        self.assertEqual(runtime._score_view(payload, "A"), ("p1", "p2", 7, 9))
        self.assertEqual(runtime._score_view(payload, "B"), ("p2", "p1", 9, 7))
        turn = dict(payload, game_id="g", side="B", remaining_moves=23)
        runtime._update_turn_view(turn)
        self.assertEqual(runtime.visual_state["games"]["g"]["remaining_moves"], 23)

    def test_winner_and_game_over_paths(self):
        game = {"my_side": "A", "my_name": "me", "enemy_name": "you"}
        self.assertIn("me", runtime._winner_text(game, 5, 1)[0])
        self.assertIn("you", runtime._winner_text(game, 1, 5)[0])
        self.assertEqual(runtime._winner_text(game, 2, 2)[0], "Empate")
        runtime._update_game_over({"game_id": "missing"})
        runtime.visual_state["games"]["g"] = dict(game, game_over=False)
        runtime._update_game_over({"game_id": "g", "score_1": 4, "score_2": 3})
        self.assertTrue(runtime.visual_state["games"]["g"]["game_over"])

    def test_async_actions_and_dispatch(self):
        ws = FakeWebSocket()
        asyncio.run(runtime._accept_challenge({"opponent": "x", "challenge_id": "c"}, ws))
        self.assertEqual(json.loads(ws.sent[-1])["action"], "accept_challenge")
        asyncio.run(runtime._play_turn({"game_id": "g", "side": "A", "turn_token": "t"}, ws))
        self.assertEqual(json.loads(ws.sent[-1])["data"]["direction"], "right")
        asyncio.run(runtime._handle_event("challenge", {"challenge_id": "c2"}, ws))
        asyncio.run(runtime._handle_event("your_turn", {"game_id": "g2", "side": "A"}, ws))
        asyncio.run(runtime._handle_event("unknown", {}, ws))
        self.assertGreaterEqual(len(ws.sent), 4)

    def test_sync_handlers_and_listener(self):
        runtime._handle_sync_event("list_users", {"users": [1, 2]})
        self.assertIn("2", runtime.visual_state["status"])
        runtime._handle_sync_event("error", {"Error": "boom"})
        self.assertIn("boom", runtime.visual_state["status"])
        runtime._handle_sync_event("none", {})
        ws = FakeWebSocket([json.dumps({"event": "list_users", "data": {"users": []}})])
        asyncio.run(runtime._listen(ws))
        self.assertIn("Online", runtime.visual_state["status"])

    def test_token_and_thread_paths(self):
        with patch.object(sys, "argv", ["bot", "abc"]):
            self.assertEqual(runtime._get_token(), "abc")
        with patch.object(sys, "argv", ["bot"]):
            with self.assertRaises(SystemExit):
                runtime._get_token()
        async def noop_client(token):
            return token
        with patch.object(runtime, "_client_loop", side_effect=noop_client):
            runtime._start_ws_thread("t")

    def test_run_client_path(self):
        fake_visualizer = types.ModuleType("snake_visualizer")
        fake_visualizer.run_visualizer = MagicMock()
        fake_thread = MagicMock()
        with patch.object(sys, "argv", ["bot", "token"]), \
             patch.object(runtime.threading, "Thread", return_value=fake_thread), \
             patch.dict(sys.modules, {"snake_visualizer": fake_visualizer}):
            runtime.run_client(lambda p: "up", lambda p: [[]], lambda s: True, frozenset("12"))
        fake_thread.start.assert_called_once()
        fake_visualizer.run_visualizer.assert_called_once()


class TestRuntimeLiveView(unittest.TestCase):
    def setUp(self):
        runtime.visual_state["games"].clear()
        runtime.BOT_IS_A = lambda side: str(side).upper() in {"A", "1"}
        runtime.BOT_PARSE = lambda payload: [["A"]]

    def test_raw_board_multipliers_and_history(self):
        payload = {"game_id": "g", "side": "B", "board": "|A1\U0001f4a3|\n|aXB|\n",
                   "multiplier_1": 2, "multiplier_2": 5, "invincible_2": 7,
                   "score_1": 10, "score_2": 20, "remaining_moves": 300}
        runtime._update_turn_view(payload, "up")
        runtime._update_turn_view(payload, "left")
        game = runtime.visual_state["games"]["g"]
        self.assertEqual(game["board"][0], ["A", "1", "\U0001f4a3"])
        self.assertEqual((game["my_mult"], game["enemy_mult"]), (5, 2))
        self.assertEqual((game["my_inv"], game["my_score"]), (7, 20))
        self.assertEqual(len(game["history"]), 2)
        self.assertEqual(game["direction"], "left")

    def test_missing_board_falls_back_and_game_over_board(self):
        runtime._update_turn_view({"game_id": "g", "side": "A"})
        self.assertEqual(runtime.visual_state["games"]["g"]["board"], [["A"]])
        runtime._update_game_over({"game_id": "g", "score_1": 1, "score_2": 0, "board": "|B|\n"})
        self.assertEqual(runtime.visual_state["games"]["g"]["board"], [["B"]])


def _live_game(**extra):
    board = [list(row) for row in (
        "A1 2  ",
        "a  3 #",
        "aX    ",
        "   B4 ",
        "\U0001f4a3    \U0001f9e8",
        "\u24b6\u24b7\u2b50*  ",
    )]
    game = {
        "game_over": False, "winner": None, "my_name": "me", "enemy_name": "you",
        "my_side": "A", "my_score": 1500, "enemy_score": 20, "remaining_moves": 300,
        "my_mult": 2, "enemy_mult": 3, "my_inv": 0, "enemy_inv": 0, "direction": "down",
        "board": board, "grid": board,
    }
    game.update(extra)
    return game


class FakeSurface:
    def __init__(self, text):
        self.text = text

    def get_size(self):
        return (len(self.text) * 6, 10)


class SizedFont:
    def render(self, text, antialias, color):
        return FakeSurface(text)


def _fake_pygame():
    draw = FakeDraw()
    draw.circle = lambda *args, **kwargs: draw.rect_calls.append((args, kwargs))
    return types.SimpleNamespace(draw=draw, display=types.SimpleNamespace(flip=MagicMock()))


class TestVisualizer(unittest.TestCase):
    def setUp(self):
        visualizer.VIEW.update(mode=0, zones=True, back=0, error="")

    def test_rules_helpers(self):
        game = _live_game()
        board = game["board"]
        self.assertEqual(visualizer.target_digit(board), 1)
        self.assertEqual(visualizer.target_digit([list("6789"), list("1")]), 6)
        self.assertIsNone(visualizer.target_digit([[" "]]))
        self.assertEqual(visualizer.find_head(board, "A", 0), (0, 0))
        self.assertEqual(visualizer.find_head(board, "A", 5), (1, 0))
        self.assertIsNone(visualizer.min_dist(None, [(0, 0)]))
        self.assertEqual(visualizer.min_dist((0, 0), [(2, 3)]), 5)
        zone = visualizer.bomb_zone(board)
        self.assertIn((2, 1), zone)
        self.assertIn((3, 4), zone)
        self.assertEqual(visualizer.short_points(700), "700")
        self.assertEqual(visualizer.short_points(4000), "4k")
        self.assertEqual(visualizer.short_points(4500), "4,5k")
        self.assertEqual(visualizer.other_side("A"), "B")
        self.assertEqual(visualizer.other_side("B"), "A")

    def test_game_view_history_and_apples(self):
        game = _live_game()
        older = dict(game, board=[list("A2"), list("aB")], my_score=5)
        game["history"] = [older, {"board": game["board"]}]
        visualizer.VIEW["back"] = 5
        view = visualizer.game_view(game)
        self.assertEqual((view["back"], view["my_score"]), (1, 5))
        visualizer.VIEW["back"] = 0
        view = visualizer.game_view(game)
        self.assertEqual(view["enemy_head"], (3, 3))
        rows = visualizer.apple_rows(view)
        self.assertEqual(rows[0][:4], (1, 1, 200, 300))
        self.assertEqual(visualizer.enemy_camping(view), 2)

    def test_enemy_camping(self):
        board = [list(row) for row in ("A1      ", "        ", "     B3 ")]
        view = visualizer.game_view(_live_game(board=board))
        self.assertEqual(visualizer.enemy_camping(view), 3)
        view = visualizer.game_view(_live_game(board=[list("AB")]))
        self.assertIsNone(visualizer.enemy_camping(view))

    def test_draw_board_all_modes(self):
        pygame = _fake_pygame()
        screen = FakeScreen()
        fonts = (SizedFont(), SizedFont(), SizedFont())
        for mode in range(3):
            visualizer.VIEW["mode"] = mode
            visualizer._draw_panel(pygame, screen, _live_game(), (0, 0, 1000, 600), fonts)
        visualizer.VIEW["zones"] = False
        visualizer._draw_panel(pygame, screen, _live_game(my_side="B", my_inv=3, enemy_inv=2, direction=None), (0, 0, 400, 300), fonts)
        visualizer._draw_panel(pygame, screen, _live_game(board=[], grid=[]), (0, 0, 400, 300), fonts)
        self.assertTrue(pygame.draw.rect_calls)
        self.assertTrue(screen.blit_calls)
        visualizer._blit_center(screen, "plain", (1, 1))

    def test_header_border_and_table(self):
        pygame = _fake_pygame()
        screen = FakeScreen()
        fonts = (FakeFont(), FakeFont(), FakeFont())
        view = visualizer.game_view(_live_game(game_over=True, winner="me (Ganador)"))
        visualizer._draw_panel_header(pygame, screen, view, (0, 0, 500, 300), fonts)
        self.assertEqual(visualizer._border_color(view), (255, 215, 0))
        self.assertEqual(visualizer._border_color(dict(view, winner="you")), (160, 50, 50))
        self.assertEqual(visualizer._border_color(dict(view, game_over=False)), (60, 60, 70))
        board = [list(row) for row in ("A1      ", "        ", "     B3 ")]
        visualizer._draw_apple_table(pygame, screen, fonts, visualizer.game_view(_live_game(board=board)), (0, 0))
        self.assertIn("INVENCIBLE", visualizer._player_line("x", 1000, 2, 3))

    def test_layout_snapshot_hud_and_games(self):
        self.assertEqual(visualizer._grid_layout(1), (1, 1))
        self.assertEqual(visualizer._grid_layout(5), (2, 3))
        self.assertEqual(len(visualizer._panel_rect(2, 2, 2)), 4)
        cell, ox, oy = visualizer._board_geometry([[" "] * 4] * 3, (0, 0, 200, 200))
        self.assertGreater(cell, 0)
        state = {"status": "ok", "games": {"g": _live_game()}}
        self.assertEqual(visualizer._snapshot(state, Lock())[0], "ok")
        pygame = _fake_pygame()
        screen = FakeScreen()
        fonts = (FakeFont(), FakeFont(), FakeFont(), FakeFont())
        visualizer._draw_hud(pygame, screen, fonts[0], "ready", 0)
        visualizer.VIEW["error"] = "boom"
        visualizer._draw_hud(pygame, screen, fonts[0], "ready", 0)
        visualizer._draw_games(pygame, screen, [], fonts)
        with patch.object(visualizer, "_draw_panel") as panel:
            visualizer._draw_games(pygame, screen, [_live_game()], fonts)
            panel.assert_called_once()
        with patch.object(visualizer, "_draw_games"):
            visualizer.draw_frame(pygame, screen, fonts, state, Lock())
        pygame.display.flip.assert_called_once()

    def test_keys_and_events(self):
        for key in ("m", "z", "left", "left", "right", "space"):
            self.assertTrue(visualizer.handle_key(key))
        self.assertFalse(visualizer.handle_key("q"))
        self.assertEqual((visualizer.VIEW["mode"], visualizer.VIEW["zones"], visualizer.VIEW["back"]), (1, False, 0))
        events = [types.SimpleNamespace(type=2, key=1), types.SimpleNamespace(type=9)]
        fake = types.SimpleNamespace(QUIT=9, KEYDOWN=2, event=FakeEventModule(events),
                                     key=types.SimpleNamespace(name=lambda k: "m"))
        self.assertTrue(visualizer._process_events(fake))
        self.assertEqual(visualizer.VIEW["mode"], 2)
        self.assertTrue(visualizer._should_quit(fake))
        fake.event = FakeEventModule([])
        self.assertFalse(visualizer._should_quit(fake))

    def test_live_reload(self):
        module = types.SimpleNamespace(__file__="/no/such/file.py")
        self.assertEqual(visualizer._reload_if_changed(module, 1), (module, 1))
        with patch.object(visualizer.os.path, "getmtime", return_value=5):
            self.assertEqual(visualizer._reload_if_changed(module, 5), (module, 5))
            with patch.object(visualizer.importlib, "reload", side_effect=SyntaxError("bad")):
                _, mtime = visualizer._reload_if_changed(module, 1)
            self.assertEqual(mtime, 5)
            self.assertIn("bad", visualizer.VIEW["error"])
            fresh = types.SimpleNamespace(VIEW={})
            with patch.object(visualizer.importlib, "reload", return_value=fresh):
                result, _ = visualizer._reload_if_changed(module, 1)
            self.assertIs(result, fresh)
            self.assertEqual(fresh.VIEW["error"], "")

    def test_build_ui_and_run(self):
        font_module = types.SimpleNamespace(init=MagicMock(), SysFont=MagicMock(side_effect=[1, 2, 3, 4]))
        display = types.SimpleNamespace(set_mode=MagicMock(return_value="screen"), set_caption=MagicMock())
        clock = MagicMock(return_value="clock")
        pygame = types.SimpleNamespace(init=MagicMock(), font=font_module, display=display,
                                       time=types.SimpleNamespace(Clock=clock), quit=MagicMock())
        self.assertEqual(visualizer._build_ui(pygame), ("screen", (1, 2, 3, 4), "clock"))
        fake_clock = MagicMock()
        with patch.dict(sys.modules, {"pygame": pygame}), \
             patch.object(visualizer, "_build_ui", return_value=("s", (), fake_clock)), \
             patch.object(visualizer, "_process_events", side_effect=[False, True]), \
             patch.object(visualizer, "draw_frame") as frame:
            visualizer.run_visualizer({}, Lock(), "12")
        frame.assert_called_once()
        pygame.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
