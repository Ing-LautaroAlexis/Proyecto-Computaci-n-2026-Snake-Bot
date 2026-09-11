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


class TestVisualizer(unittest.TestCase):
    def test_palettes_colors_layout_and_border(self):
        self.assertNotEqual(visualizer._snake_palette(True), visualizer._snake_palette(False))
        self.assertIn("1", visualizer._food_color_map("12"))
        self.assertIn("A", visualizer._side_colors("A", "12"))
        self.assertEqual(visualizer._grid_layout(1), (1, 1))
        self.assertEqual(visualizer._grid_layout(5), (2, 3))
        game = {"game_over": False, "winner": None, "my_name": "me"}
        self.assertEqual(visualizer._border_color(game), (60, 60, 70))
        game.update(game_over=True, winner="me (Ganador)")
        self.assertEqual(visualizer._border_color(game), (255, 215, 0))
        game["winner"] = "other"
        self.assertEqual(visualizer._border_color(game), (160, 50, 50))

    def test_geometry_snapshot_panel_rect_and_quit(self):
        grid = [[" "] * 4 for _ in range(3)]
        cell, ox, oy = visualizer._board_geometry(grid, (0, 0, 200, 200))
        self.assertGreater(cell, 0)
        self.assertIsInstance(ox + oy, int)
        state = {"status": "ok", "games": {"g": {"x": 1}}}
        self.assertEqual(visualizer._snapshot(state, Lock())[0], "ok")
        self.assertEqual(len(visualizer._panel_rect(2, 2, 2)), 4)
        fake = types.SimpleNamespace(QUIT=9, event=FakeEventModule([types.SimpleNamespace(type=9)]))
        self.assertTrue(visualizer._should_quit(fake))
        fake.event = FakeEventModule([])
        self.assertFalse(visualizer._should_quit(fake))

    def test_draw_helpers(self):
        draw = FakeDraw()
        pygame = types.SimpleNamespace(draw=draw)
        screen = FakeScreen()
        fonts = (FakeFont(), FakeFont())
        game = {
            "game_over": True, "winner": "me", "my_name": "me", "enemy_name": "you",
            "my_score": 3, "enemy_score": 2, "remaining_moves": 10,
            "grid": [["A", "1"], ["a", "B"]], "my_side": "A",
        }
        visualizer._draw_panel_header(pygame, screen, game, (0, 0, 300, 250), fonts)
        self.assertTrue(screen.blit_calls)
        visualizer._draw_cells(pygame, screen, game["grid"], (0, 0, 300, 250), visualizer._side_colors("A", "12"))
        self.assertTrue(draw.rect_calls)
        visualizer._draw_panel(pygame, screen, game, (0, 0, 300, 250), fonts, "12")
        empty = dict(game, grid=[])
        visualizer._draw_panel(pygame, screen, empty, (0, 0, 300, 250), fonts, "12")

    def test_hud_and_games_paths(self):
        draw = FakeDraw()
        pygame = types.SimpleNamespace(draw=draw)
        screen = FakeScreen()
        fonts = (FakeFont(), FakeFont(), FakeFont())
        visualizer._draw_hud(pygame, screen, fonts[0], "ready", 0)
        visualizer._draw_games(pygame, screen, [], fonts, "12")
        self.assertTrue(screen.blit_calls)
        game = {
            "game_over": False, "winner": None, "my_name": "me", "enemy_name": "you",
            "my_score": 0, "enemy_score": 0, "remaining_moves": 300,
            "grid": [["A", "1", "B"]], "my_side": "A",
        }
        with patch.object(visualizer, "_draw_panel") as panel:
            visualizer._draw_games(pygame, screen, [game], fonts, "12")
            panel.assert_called_once()

    def test_build_ui(self):
        font_module = types.SimpleNamespace(init=MagicMock(), SysFont=MagicMock(side_effect=[1, 2, 3]))
        display = types.SimpleNamespace(set_mode=MagicMock(return_value="screen"), set_caption=MagicMock())
        clock = MagicMock(return_value="clock")
        pygame = types.SimpleNamespace(init=MagicMock(), font=font_module, display=display, time=types.SimpleNamespace(Clock=clock))
        self.assertEqual(visualizer._build_ui(pygame), ("screen", (1, 2, 3), "clock"))
        pygame.init.assert_called_once()
        display.set_caption.assert_called_once()


if __name__ == "__main__":
    unittest.main()
