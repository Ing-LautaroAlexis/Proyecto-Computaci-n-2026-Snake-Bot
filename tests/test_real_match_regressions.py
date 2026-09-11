import importlib.util
import sys
import types
import unittest
from collections import deque
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
BOT = ROOT / 'botv8.0_v5.py'
for name in ('pygame', 'websockets'):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
spec = importlib.util.spec_from_file_location('botv76_real_reg', BOT)
bot = importlib.util.module_from_spec(spec)
sys.modules['botv76_real_reg'] = bot
spec.loader.exec_module(bot)


class TestRealMatchRegressions(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()

    def test_edge_distance_uses_real_rectangular_board_edges(self):
        grid = [list(' ' * 15) for _ in range(12)]
        self.assertEqual(bot._edge_distance(grid, (0, 7)), 0)
        self.assertEqual(bot._edge_distance(grid, (11, 7)), 0)
        self.assertEqual(bot._edge_distance(grid, (5, 0)), 0)
        self.assertEqual(bot._edge_distance(grid, (5, 14)), 0)
        self.assertEqual(bot._edge_distance(grid, (5, 1)), 1)
        self.assertEqual(bot._edge_distance(grid, (5, 13)), 1)

    def test_candela_edge_food_is_not_marked_safe(self):
        # Real position from the Candela loss at remaining=214.
        rows = [
            '    *          ',
            '               ',
            '               ',
            '               ',
            '     bb        ',
            '     bb        ',
            '     b         ',
            '     b         ',
            '     B         ',
            '               ',
            ' aaaA         *',
            ' aaa  *        ',
        ]
        grid = [list(row) for row in rows]
        my_body = deque([(10, 4), (10, 3), (10, 2), (10, 1), (11, 1), (11, 2), (11, 3)])
        en_body = deque([(8, 5), (7, 5), (6, 5), (5, 5), (4, 5), (4, 6), (5, 6)])
        food = [(0, 4), (10, 14), (11, 6)]
        candidates = [('DOWN', (11, 4)), ('RIGHT', (10, 5)), ('UP', (9, 4))]
        zero = {name: 0 for name, _ in candidates}
        strategy = bot.compute_strategy_state(439, 439, 214)
        adjustments, details = bot.compute_safe_food_opportunity_adjustments(
            grid, my_body, en_body, food, True, candidates, strategy,
            zero, zero, zero,
        )
        self.assertEqual(adjustments['DOWN'], 0)
        self.assertNotIn('DOWN', details)

    def test_thiago_bank_defers_controlled_catchup_apple(self):
        # Real position from the Thiago loss at remaining=44.
        rows = [
            '                 ',
            '                *',
            '                *',
            '                 ',
            '        bbbbbbbb ',
            '        bb    bb ',
            '              b  ',
            '            Bbb  ',
            ' aaa             ',
            ' a a             ',
            ' a a             ',
            ' a a             ',
            ' a A             ',
            ' a *             ',
            ' aaa             ',
        ]
        grid = [list(row) for row in rows]
        my_body = deque([(12, 3), (12, 1), (11, 1)])
        # Exact body order is not important for the distance-based bank test;
        # topology only needs a valid connected head/tail approximation here.
        my_body = deque([(12, 3), (11, 3), (10, 3), (9, 3), (8, 3), (8, 2), (8, 1),
                         (9, 1), (10, 1), (11, 1), (12, 1), (13, 1), (14, 1), (14, 2), (14, 3)])
        en_body = deque([(7, 12), (7, 13), (7, 14), (6, 14), (5, 14), (5, 13), (4, 13),
                         (4, 12), (4, 11), (4, 10), (4, 9), (4, 8), (5, 8), (5, 9)])
        food = [(1, 16), (2, 16), (13, 3)]
        candidates = [('DOWN', (13, 3)), ('LEFT', (12, 2)), ('RIGHT', (12, 4))]
        zero = {name: 0 for name, _ in candidates}
        strategy = bot.compute_strategy_state(1316, 1415, 44)
        penalties, stats = bot.compute_apple_freeze_penalties(
            grid, my_body, en_body, food, candidates, strategy, zero, zero
        )
        self.assertTrue(stats['deferred_catchup'])
        self.assertGreater(penalties['DOWN'], 0)
        self.assertEqual(penalties['LEFT'], 0)
        self.assertEqual(penalties['RIGHT'], 0)

    def test_bank_cashout_stops_deferring_at_last_eight_moves(self):
        grid = [list(' ' * 12) for _ in range(12)]
        grid[5][5] = 'A'; grid[5][4] = 'a'; grid[5][3] = 'a'
        grid[1][1] = 'B'; grid[1][2] = 'b'; grid[1][3] = 'b'
        grid[6][5] = '*'
        my_body = deque([(5, 5), (5, 4), (5, 3)])
        en_body = deque([(1, 1), (1, 2), (1, 3)])
        food = [(6, 5)]
        candidates = [('DOWN', (6, 5)), ('UP', (4, 5))]
        zero = {'DOWN': 0, 'UP': 0}
        strategy = bot.compute_strategy_state(0, 99, 8)
        penalties, stats = bot.compute_apple_freeze_penalties(
            grid, my_body, en_body, food, candidates, strategy, zero, zero
        )
        self.assertFalse(stats['active'])
        self.assertEqual(penalties['DOWN'], 0)

    def test_numbered_target_bank_scales_penalty(self):
        grid = [list(' ' * 12) for _ in range(12)]
        grid[5][5] = 'A'; grid[5][4] = 'a'; grid[5][3] = 'a'
        grid[1][1] = 'B'; grid[1][2] = 'b'; grid[1][3] = 'b'
        # 7 is the correct target for the cyclic set 7,8,9,1,2.
        for (r, c), digit in zip([(6,5),(8,8),(9,9),(9,10),(8,10)], '78912'):
            grid[r][c] = digit
        food = bot.find_food(grid)
        my_body = deque([(5, 5), (5, 4), (5, 3)])
        en_body = deque([(1, 1), (1, 2), (1, 3)])
        candidates = [('DOWN', (6, 5)), ('UP', (4, 5))]
        zero = {'DOWN': 0, 'UP': 0}
        strategy = bot.compute_strategy_state(0, 699, 44, food_reward=700)
        penalties, stats = bot.compute_apple_freeze_penalties(
            grid, my_body, en_body, food, candidates, strategy, zero, zero
        )
        self.assertTrue(stats['deferred_catchup'])
        self.assertGreaterEqual(penalties['DOWN'], 2_000_000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
