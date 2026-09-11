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

spec = importlib.util.spec_from_file_location('botv76_tested', BOT)
bot = importlib.util.module_from_spec(spec)
sys.modules['botv76_tested'] = bot
spec.loader.exec_module(bot)


def board_text(rows):
    return '\n'.join('|' + row + '|' for row in rows) + '\n'


class TestV3BoardAndFood(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()

    def test_rectangular_12x20_parses_exact_dimensions(self):
        rows = [' ' * 20 for _ in range(12)]
        rows[1] = '  A' + ' ' * 17
        rows[10] = ' ' * 16 + 'B' + ' ' * 3
        payload = {'board': board_text(rows), 'rows': 12, 'cols': 20, 'board_size': '12x20'}
        grid = bot.parse_turn_board(payload)
        self.assertEqual((len(grid), len(grid[0])), (12, 20))

    def test_rectangular_20x12_parses_board_size_fallback(self):
        rows = [' ' * 12 for _ in range(20)]
        payload = {'board': board_text(rows), 'board_size': '20x12'}
        grid = bot.parse_turn_board(payload)
        self.assertEqual((len(grid), len(grid[0])), (20, 12))

    def test_digits_one_two_are_not_heads(self):
        rows = [
            '       ',
            ' A 1   ',
            ' a     ',
            '   2 B ',
            '     b ',
            '       ',
        ]
        grid = bot.parse_board(board_text(rows))
        self.assertEqual(bot.find_head(grid, 'A'), (1, 1))
        self.assertEqual(bot.find_enemy_head(grid, 'A'), (3, 5))
        my_body, en_body = bot.get_bodies('digits-not-heads', grid, 'A')
        self.assertEqual(len(my_body), 2)
        self.assertEqual(len(en_body), 2)

    def test_correct_digit_1_from_1_to_5(self):
        grid = bot.parse_board(board_text(['A12345B']))
        digit, pos = bot.correct_numbered_food(grid)
        self.assertEqual(digit, '1')
        self.assertEqual(pos, (0, 1))
        self.assertEqual(bot.find_food(grid), [(0, 1)])

    def test_correct_digit_wraps_7_8_9_1_2(self):
        grid = bot.parse_board(board_text(['A78912B']))
        digit, pos = bot.correct_numbered_food(grid)
        self.assertEqual(digit, '7')
        self.assertEqual(pos, (0, 1))

    def test_correct_digit_9_when_9_1_2_3_4_present(self):
        grid = bot.parse_board(board_text(['A91234B']))
        digit, _ = bot.correct_numbered_food(grid)
        self.assertEqual(digit, '9')

    def test_wrong_digits_are_legal_cells(self):
        grid = [list('         '), list(' A2 1345B'), list(' a     b '), list('         ')]
        my = deque([(1, 1), (2, 1)])
        en = deque([(1, 8), (2, 7)])
        legal = dict(bot.get_legal_moves_raw(grid, my[0], my, en))
        self.assertIn('RIGHT', legal)
        self.assertTrue(bot.wrong_numbered_food_at(grid, (1, 2), bot.find_food(grid)))


class TestV3Simulation(unittest.TestCase):
    def test_correct_digit_scores_and_grows(self):
        grid = [list('       '), list(' A12345'), list(' a    B'), list('      b')]
        body = deque([(1, 1), (2, 1)])
        food = bot.find_food(grid)
        before_grid = tuple(map(tuple, grid))
        before_body = tuple(body)
        before_food = tuple(food)
        undo = bot.make_move(grid, body, (1, 2), True, 10, food)
        self.assertTrue(undo[3])
        self.assertEqual(undo[4], 110)  # digit 1 => +100
        self.assertEqual(len(body), 3)
        self.assertEqual(grid[1][3], '2')
        self.assertEqual(food, [(1, 3)])  # next correct target becomes 2
        bot.unmake_move(grid, body, undo[0], undo[1], undo[2], undo[3], True, (1, 2), food, undo[5])
        self.assertEqual(tuple(map(tuple, grid)), before_grid)
        self.assertEqual(tuple(body), before_body)
        self.assertEqual(tuple(food), before_food)

    def test_correct_digit_9_scores_900(self):
        grid = [list('       '), list(' A91234'), list(' a    B'), list('      b')]
        body = deque([(1, 1), (2, 1)])
        food = bot.find_food(grid)
        undo = bot.make_move(grid, body, (1, 2), True, 50, food)
        self.assertEqual(undo[4], 950)
        self.assertEqual(food, [(1, 3)])  # 1 follows 9 cyclically

    def test_wrong_digit_penalty_no_growth_and_reversible(self):
        grid = [list('       '), list(' A21345'), list(' a    B'), list('      b')]
        # Present set 1..5 => correct target is 1 at col 3. Moving right hits wrong 2.
        body = deque([(1, 1), (2, 1)])
        food = bot.find_food(grid)
        before_grid = tuple(map(tuple, grid))
        before_body = tuple(body)
        before_food = tuple(food)
        undo = bot.make_move(grid, body, (1, 2), True, 20, food)
        self.assertFalse(undo[3])
        self.assertEqual(undo[4], -480)
        self.assertEqual(len(body), 2)
        self.assertEqual(food, list(before_food))
        bot.unmake_move(grid, body, undo[0], undo[1], undo[2], undo[3], True, (1, 2), food, undo[5])
        self.assertEqual(tuple(map(tuple, grid)), before_grid)
        self.assertEqual(tuple(body), before_body)
        self.assertEqual(tuple(food), before_food)

    def test_legacy_star_semantics_unchanged(self):
        grid = [list('     '), list(' A*B '), list(' a b '), list('     ')]
        body = deque([(1, 1), (2, 1)])
        food = bot.find_food(grid)
        undo = bot.make_move(grid, body, (1, 2), True, 0, food)
        self.assertTrue(undo[3])
        self.assertEqual(undo[4], 100)
        self.assertEqual(len(body), 3)

    def test_strategy_uses_current_digit_reward(self):
        low = bot.compute_strategy_state(0, 500, 40, food_reward=100)
        high = bot.compute_strategy_state(0, 500, 40, food_reward=900)
        self.assertGreaterEqual(low['required_net_apples'], high['required_net_apples'])
        self.assertEqual(high['food_swing'], 899)


class TestV3DecisionSafety(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()

    def test_choose_direction_handles_numbered_rectangular_board(self):
        rows = [list(' ' * 12) for _ in range(12)]
        rows[1][3] = 'A'; rows[1][2] = 'a'; rows[1][1] = 'a'
        rows[10][8] = 'B'; rows[10][9] = 'b'; rows[10][10] = 'b'
        for (r, c), d in zip([(4,4),(5,6),(7,2),(8,8),(3,9)], '12345'):
            rows[r][c] = d
        payload = {
            'game_id': 'v3-rect', 'board': board_text([''.join(r) for r in rows]),
            'rows': 12, 'cols': 12, 'board_size': '12x12', 'remaining_moves': 300,
            'side': 'A', 'score_1': 0, 'score_2': 0,
        }
        move = bot.choose_direction(payload, search_mode='nodes', node_budget=100)
        self.assertIn(move, bot.DIRECTIONS)
        self.assertNotIn('dimension_warning', bot.LAST_STRATEGY_STATS)
        self.assertEqual(bot.LAST_STRATEGY_STATS.get('food_reward'), 100)
        self.assertTrue(bot.LAST_STRATEGY_STATS.get('apple_freeze', {}).get('enabled'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
