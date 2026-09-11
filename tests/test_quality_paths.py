from __future__ import annotations
import importlib.util
import sys
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent / "src" / "bot_final"
BOT = ROOT / 'botv8.0_v5.py'
for name in ('pygame', 'websockets'):
    sys.modules.setdefault(name, types.ModuleType(name))
spec = importlib.util.spec_from_file_location('botv76_quality', BOT)
bot = importlib.util.module_from_spec(spec)
sys.modules['botv76_quality'] = bot
spec.loader.exec_module(bot)


def framed(rows):
    return '\n'.join('|' + row + '|' for row in rows) + '\n'


def simple_grid():
    return [list('       '), list(' A   B '), list(' a   b '), list('       ')]


def simple_bodies():
    return deque([(1, 1), (2, 1)]), deque([(1, 5), (2, 5)])


class TestParsingAndTracking(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()

    def test_parse_variants_and_bad_metadata(self):
        self.assertEqual(bot._strip_board_frame('abc'), 'abc')
        self.assertEqual(bot._board_lines('a\nb'), ['a', 'b'])
        self.assertEqual(bot.parse_board([['A', ' ']]), [['A', ' ']])
        self.assertEqual(bot._dimensions_from_board_size({'board_size': 'oops'}), (None, None))
        self.assertEqual(bot._dimensions_from_board_size({'board_size': '12xno'}), (None, None))
        self.assertEqual(bot._int_dimensions('x', 2), (None, None))
        payload = {'board': framed(['A B', '   ']), 'rows': 9, 'cols': 9}
        grid = bot.parse_turn_board(payload)
        self.assertEqual((len(grid), len(grid[0])), (2, 3))
        self.assertEqual(bot.LAST_STRATEGY_STATS['dimension_warning']['actual'], [2, 3])

    def test_numbered_fallback_and_reward_edges(self):
        present = set('135')
        self.assertGreaterEqual(bot._forward_food_run_length('1', present), 1)
        self.assertIn(bot._fallback_food_digit(present), present)
        empty = [list('A B')]
        self.assertEqual(bot.current_food_reward(empty, []), 100)
        self.assertFalse(bot.wrong_numbered_food_at(empty, (-1, 0), []))
        self.assertFalse(bot.is_pos_inside([], (0, 0)))

    def test_trace_helpers_and_greedy_fallback(self):
        grid = [list('Aaa'), list('  a'), list('aaa')]
        seen = {(0, 0)}
        self.assertEqual(bot._first_unseen_body_neighbor(grid, (0, 0), 'a', seen), (0, 1))
        greedy = bot._trace_greedy_fallback(grid, (0, 0), 'a')
        self.assertGreaterEqual(len(greedy), 2)
        path = [(0, 0)]
        visited = {(0, 0)}
        self.assertFalse(bot._trace_dfs(grid, (0, 0), 'a', 99, path, visited, [1], 0))
        self.assertEqual(list(bot._trace_full_snake([list('A  ')], (0, 0), 'a')), [(0, 0)])

    def test_history_helpers(self):
        h = bot._history_for_game('qhist')
        bot._append_head_if_new(h['my_path'], None)
        bot._append_head_if_new(h['my_path'], (1, 1))
        bot._append_head_if_new(h['my_path'], (1, 1))
        self.assertEqual(list(h['my_path']), [(1, 1)])
        same = bot._resync_path_if_short(h['my_path'], 1, simple_grid(), None, 'a')
        self.assertIs(same, h['my_path'])
        h['my_path'].extend([(1, 2), (1, 3)])
        bot._trim_history_path(h['my_path'], 1)
        self.assertEqual(len(h['my_path']), 1)


class TestTopologyAndSimulation(unittest.TestCase):
    def test_invalid_and_legal_topology_paths(self):
        grid = simple_grid()
        self.assertEqual(bot.bfs_distances(grid, None), {})
        self.assertEqual(bot.get_legal_moves_raw(grid, None, deque(), deque()), [])
        self.assertEqual(bot.analyze_topology(grid, None, 1)[0], 0)
        self.assertEqual(bot.analyze_topology_consolidated(grid, None, 1).space, 0)
        self.assertFalse(bot._open_outside_region(grid, (-1, 0), {}))
        self.assertIsNone(bot._tail_or_none(deque()))
        self.assertEqual(bot._chokepoint_result(None), (False, None, False))
        self.assertEqual(bot._chokepoint_result((1, 2)), (True, (1, 2), True))

    def test_chokepoint_helpers_and_public_versions(self):
        grid = [list('       '), list('       '), list('       '), list('       ')]
        enemy = {(1, 2): 1}
        mine = {(1, 2): 1}
        self.assertGreaterEqual(bot._count_open_connections(grid, (1, 2), enemy), 2)
        self.assertEqual(bot._find_reachable_chokepoint(grid, enemy, mine), (1, 2))
        self.assertIsNone(bot._find_reachable_chokepoint(grid, enemy, {}))
        my, en = simple_bodies()
        self.assertEqual(bot.analyze_corridor_chokepoints(grid, None, en[0], my, en), (False, None, False))
        fake_en = bot.TopologyInfo(1, 1, False, True, enemy)
        fake_my = bot.TopologyInfo(10, 3, True, False, mine)
        self.assertEqual(bot.analyze_corridor_chokepoints_opt(grid, None, en[0], fake_en, fake_my), (False, None, False))
        result = bot.analyze_corridor_chokepoints_opt(grid, my[0], en[0], fake_en, fake_my)
        self.assertTrue(result[0])

    def test_simulation_restore_helpers(self):
        grid = [list('     '), list(' Aa  '), list('     ')]
        body = deque([(1, 1), (1, 2)])
        bot._restore_new_head(grid, deque(), 'A')
        bot._restore_tail(grid, body, None, None, False)
        food = [(0, 0)]
        bot._restore_food_snapshot(food, None)
        self.assertEqual(food, [(0, 0)])
        self.assertEqual(bot._score_move_result(0, ' ', False, False, False), 1)
        self.assertEqual(bot._score_move_result(0, '3', False, False, True), -500)


class TestFutureEscapeBranches(unittest.TestCase):
    def test_fe_risk_helpers(self):
        topo0 = bot.TopologyInfo(1, 0, False, True, {})
        topo1 = bot.TopologyInfo(2, 1, False, False, {})
        topo_tail = bot.TopologyInfo(5, 2, True, False, {})
        self.assertEqual(bot._fe_exit_risk(topo0, False), bot.FE_POCKET_RISK)
        self.assertEqual(bot._fe_exit_risk(topo1, True), bot.FE_SINGLE_EXIT_RISK)
        self.assertEqual(bot._fe_tail_space_risk(topo_tail, 0), 0)
        self.assertEqual(bot._fe_tail_space_risk(topo1, 2), bot.FE_TIGHT_RISK)
        self.assertEqual(bot._fe_tail_space_risk(topo1, 5), 35000)
        self.assertEqual(bot._fe_tail_space_risk(topo1, 10), 0)

    def test_fe_budget_and_cache_paths(self):
        stats = {'nodes': bot.FE_NODE_BUDGET, 'aborted': False}
        risk = bot._fe_early_internal_result(False, 123, float('inf'), stats)
        self.assertEqual(risk, 123)
        self.assertTrue(stats['aborted'])
        self.assertEqual(bot._fe_aborted_best_risk(bot.FE_FATAL_RISK, 77, stats), 77)
        self.assertEqual(bot._fe_explored_result(False, 5, 8), 8)
        self.assertEqual(bot._fe_enemy_moves(simple_grid(), deque(), deque()), [])

    def test_future_escape_cached_and_terminal_paths(self):
        grid = simple_grid()
        my, en = simple_bodies()
        stats = {'nodes': 0, 'aborted': False}
        key = bot._fe_cache_key(my, en, [], 1, True, True)
        memo = {key: 123}
        self.assertEqual(bot.future_escape_risk(grid, my, en, [], True, 1, True, float('inf'), stats, memo), 123)
        no_moves_grid = [list('#####'), list('#A###'), list('#aB##'), list('#####')]
        my2 = deque([(1, 1), (2, 1)])
        en2 = deque([(2, 2)])
        stats2 = {'nodes': 0, 'aborted': False}
        with patch.object(bot, 'get_legal_moves_raw', return_value=[]):
            self.assertEqual(bot._fe_my_turn_risk(no_moves_grid, my2, en2, [], True, 1, float('inf'), stats2, {}, 0), bot.FE_FATAL_RISK)

    def test_fe_collection_aborted(self):
        grid = simple_grid()
        my, en = simple_bodies()
        candidates = [('RIGHT', (1, 2)), ('DOWN', (2, 1))]
        stats = {'nodes': bot.FE_NODE_BUDGET, 'aborted': False}
        penalties = bot._collect_fe_penalties(grid, my, en, [], True, candidates, 1, float('inf'), stats, {})
        self.assertTrue(stats['aborted'])
        self.assertEqual(bot._finalize_fe_penalties(candidates, penalties, True), {'RIGHT': 0, 'DOWN': 0})


class TestStrategyAndEvaluationBranches(unittest.TestCase):
    def test_food_race_secondary_and_modes(self):
        self.assertGreater(bot._weighted_top_two([100, 80]), 100)
        topo = bot.TopologyInfo(10, 2, True, False, {(0, 0): 1, (0, 1): 2})
        en = bot.TopologyInfo(10, 2, True, False, {(0, 0): 4, (0, 1): 6})
        self.assertGreater(bot.compute_food_race_bonus(topo, en, [(0, 0), (0, 1)]), 0)
        self.assertEqual(bot._strategy_adjust_anti_cycle_penalties({'X': 100}, {'mode': 'LEADING'})['X'], 70)
        self.assertEqual(bot._territory_mode_weight(10, None), 10)
        self.assertEqual(bot._territory_mode_weight(10, 'TRAILING'), 4)

    def test_freeze_helper_false_paths(self):
        self.assertFalse(bot._freeze_strength_ok(0, 0, 0))
        topo = bot.TopologyInfo(0, 0, False, False, {})
        self.assertFalse(bot._freeze_candidate_eligible((1, 1), {(1, 2)}, [], topo))
        self.assertFalse(bot._freeze_candidate_eligible((1, 1), {(1, 1)}, [], topo))
        self.assertGreater(bot._freeze_penalty_value(2, 3), bot.APPLE_FREEZE_BASE_PENALTY)
        self.assertEqual(bot._topology_for_body_or_empty(simple_grid(), deque()).space, 0)

    def test_freeze_early_return_variants(self):
        grid = simple_grid()
        my, en = simple_bodies()
        cand = [('RIGHT', (1, 2))]
        zero = {'RIGHT': 0}
        strategy = {'mode': 'NORMAL', 'remaining': 40, 'safe_concedable_apples': 3}
        penalties, stats = bot.compute_apple_freeze_penalties(grid, my, en, [(0, 0), (0, 1)], cand, strategy, zero, zero)
        self.assertFalse(stats['active'])
        strategy2 = {'mode': 'LOCK', 'remaining': 40, 'safe_concedable_apples': 0}
        penalties2, stats2 = bot.compute_apple_freeze_penalties(grid, my, en, [(0, 0), (0, 1)], cand, strategy2, zero, zero)
        self.assertFalse(stats2['active'])

    def test_evaluation_helper_branches(self):
        self.assertEqual(bot._missing_head_value(None, (1, 1)), -bot.INF)
        self.assertEqual(bot._missing_head_value((1, 1), None), bot.INF)
        mine = bot.TopologyInfo(2, 1, False, True, {})
        enemy = bot.TopologyInfo(3, 1, False, False, {})
        self.assertLess(bot._pocket_terminal_value(mine, enemy), 0)
        self.assertGreater(bot._pocket_terminal_value(enemy, mine), 0)
        self.assertEqual(bot._food_distance_contribution(2, 2), 84)
        self.assertEqual(bot._food_distance_contribution(bot.INF, bot.INF), 0)
        self.assertEqual(bot._final_evaluation_value(10, 1, 5, 7, 9, 0, 1, 2), 7)
        self.assertGreater(bot._final_evaluation_value(10, -1, 5, 7, 9, 0, 1, 2), 5)

    def test_territory_owner_and_delta(self):
        grid = [list('   '), list('   ')]
        my = bot.TopologyInfo(6, 2, True, False, {(0, 0): 1, (0, 1): 1})
        en = bot.TopologyInfo(6, 2, True, False, {(0, 0): 3, (0, 1): 0})
        self.assertEqual(bot._territory_cell_owner(grid, (0, 0), my, en), 1)
        self.assertEqual(bot._territory_cell_owner(grid, (0, 1), my, en), -1)
        grid[1][1] = 'A'
        self.assertEqual(bot._territory_cell_owner(grid, (1, 1), my, en), 0)
        self.assertIsInstance(bot._territory_delta(grid, my, en), int)

    def test_choke_bonus_branches(self):
        topo = bot.TopologyInfo(10, 2, True, False, {(1, 1): 0, (1, 2): 2})
        with patch.object(bot, 'analyze_corridor_chokepoints_opt', return_value=(True, (1, 1), True)):
            self.assertEqual(bot._choke_bonus(simple_grid(), (1, 1), (1, 5), topo, topo), 350000)
        with patch.object(bot, 'analyze_corridor_chokepoints_opt', return_value=(True, (1, 2), True)):
            self.assertLess(bot._choke_bonus(simple_grid(), (1, 1), (1, 5), topo, topo), 350000)


class TestSearchAndFallbackBranches(unittest.TestCase):
    def tearDown(self):
        bot.TT.clear()
        bot.SEARCH_ABORTED = False
        bot.SEARCH_MODE = 'time'
        bot.SEARCH_NODE_BUDGET = None
        bot.SEARCH_NODES = 0

    def test_tt_cutoff_variants(self):
        self.assertEqual(bot._tt_cutoff_score({'score': 7, 'flag': bot.TT_EXACT}, 0, 10), 7)
        self.assertEqual(bot._tt_cutoff_score({'score': 10, 'flag': bot.TT_LOWER}, 0, 10), 10)
        self.assertEqual(bot._tt_cutoff_score({'score': 0, 'flag': bot.TT_UPPER}, 0, 10), 0)
        self.assertIs(bot._tt_cutoff_score({'score': 5, 'flag': 999}, 0, 10), bot._NO_SEARCH_RESULT)
        bot.TT[1] = {'score': 3, 'flag': bot.TT_EXACT, 'depth': 1}
        self.assertIs(bot._tt_probe(1, 2, -10, 10), bot._NO_SEARCH_RESULT)

    def test_exact_terminal_body_missing(self):
        self.assertLess(bot._exact_terminal_result(deque(), deque([(0, 0)]), 0, 0, 5), 0)
        self.assertGreater(bot._exact_terminal_result(deque([(0, 0)]), deque(), 0, 0, 5), 0)
        self.assertLess(bot._no_moves_terminal_score(True, 5), 0)
        self.assertGreater(bot._no_moves_terminal_score(False, 5), 0)

    def test_emergency_fallback_and_direction(self):
        grid = [list('     '), list(' A*  '), list(' a   '), list('     ')]
        my = deque([(1, 1), (2, 1)])
        self.assertEqual(bot.emergency_safety_fallback(grid, deque(), deque(), []), 'UP')
        move = bot.emergency_safety_fallback(grid, my, deque(), [(1, 2)])
        self.assertIn(move, bot.DIRECTIONS)
        self.assertIsNone(bot._get_current_direction(grid, None, 'A'))
        self.assertEqual(bot._get_current_direction(grid, (1, 1), 'A'), 'UP')

    def test_fallback_legality_and_food_bonus(self):
        grid = [list('***'), list('*A*'), list('*a*')]
        body = deque([(1, 1), (2, 1)])
        self.assertFalse(bot._fallback_candidate_legal(grid, (-1, 0), body))
        self.assertEqual(bot._fallback_food_bonus({}, [(0, 0)]), 0)
        self.assertIsInstance(bot._fallback_candidate_score(grid, (2, 1), body, []), int)

    def test_search_abort_and_cached_alpha_beta(self):
        bot.SEARCH_MODE = 'nodes'
        bot.SEARCH_NODE_BUDGET = 0
        bot.SEARCH_NODES = 0
        self.assertEqual(bot._search_abort_result(float('inf')), 0)
        grid = simple_grid()
        my, en = simple_bodies()
        bot._reset_search_state('fixed_depth', None)
        key = bot._search_state_hash(my, en, True, [], 50, True, 0, 0)
        bot.TT[key] = {'score': 1234, 'depth': 5, 'flag': bot.TT_EXACT}
        self.assertEqual(bot.alpha_beta(grid, 1, -bot.INF, bot.INF, True, my, en, float('inf'), 0, 0, 50, [], True), 1234)


class TestAntiCycleTacticalAndSafeFood(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()

    def test_anti_cycle_disabled_and_growth(self):
        p = [('UP', (1, 1))]
        self.assertEqual(bot.compute_anti_cycle_penalties('acq', (2, 2), 3, p, enabled=False), {})
        hist = bot.bot_histories['acq']
        hist['ac_last_body_len'] = 3
        hist['ac_no_growth_turns'] = 7
        bot._anti_cycle_growth_update(hist, 4)
        self.assertEqual(hist['ac_no_growth_turns'], 0)
        self.assertEqual(bot._cycle_period_penalty([1, 2], 4, 9)[0], 0)
        self.assertEqual(bot._cycle_period_penalty([1, 2, 1, 2], 2, 1)[0], 0)

    def test_fe_gate_extra_branches(self):
        self.assertGreater(bot._fe_gate_scale(14, 90, 0), bot.FE_SAFETY_GATE_SCALE_LONG)
        self.assertGreaterEqual(bot._fe_gate_scale(10, 90, -400), 3)
        self.assertEqual(bot._scaled_fe_risk(0, 5), 0)
        self.assertEqual(bot._scaled_fe_risk(bot.FE_FATAL_RISK, 5), bot.FE_FATAL_RISK)

    def test_forced_probe_deadline_and_invalid(self):
        grid = simple_grid()
        my, en = simple_bodies()
        stats = {'nodes': 0, 'aborted': False}
        self.assertFalse(bot._enemy_can_force_corridor_death(grid, my, en, [], True, 2, stats, hard_deadline=0.0))
        self.assertTrue(stats['aborted'])
        self.assertFalse(bot._enemy_can_force_corridor_death(grid, my, deque(), [], True, 0, {'nodes': 0, 'aborted': False}))
        penalties, stats2 = bot.compute_forced_trap_penalties(grid, my, en, [], True, [('RIGHT', (1, 2))], hard_deadline=0.0)
        self.assertTrue(stats2['aborted'])
        self.assertEqual(penalties['RIGHT'], 0)

    def test_tactical_helper_branches(self):
        self.assertTrue(bot._tactical_critical_mobility([], [('X', (0, 0))]))
        self.assertTrue(bot._tactical_late_large(20, 30))
        self.assertFalse(bot._tactical_close_contact(99, 30, [], []))
        self.assertFalse(bot._tactical_edge_pressure(2, 1, 30, [], []))
        self.assertEqual(bot._tactical_child_resolution(True, None), (False, None, True))
        self.assertEqual(bot._tactical_child_resolution(True, True)[0], True)
        self.assertEqual(bot._tactical_child_resolution(False, False)[0], True)
        self.assertIsNone(bot._tactical_unresolved_result(True, True))
        self.assertEqual(bot._tactical_unresolved_result(True, False), False)
        self.assertEqual(bot._tactical_turn_bodies(deque([1]), deque([2]), False)[0], deque([2]))
        self.assertEqual(bot._tactical_moves_for_body(simple_grid(), deque(), deque()), [])
        self.assertFalse(bot._tactical_moving_is_a(True, False))
        memo = {}
        self.assertIsNone(bot._tactical_store_result(memo, 'x', None))

    def test_tactical_budget_and_offense_helpers(self):
        stats = bot._new_tactical_stats()
        stats['nodes'] = bot.TACTICAL_SOLVER_NODE_BUDGET
        self.assertTrue(bot._tactical_budget_exhausted(float('inf'), stats))
        self.assertFalse(bot._tactical_offense_promising(deque([(0, 0)]), deque(), []))
        self.assertEqual(bot._tactical_local_deadline(True, 1.0, 0.0), float('inf'))
        self.assertEqual(bot._tactical_offense_deadline(True, 5.0), 5.0)

    def test_straight_and_safe_food_edges(self):
        grid = [list('     '), list(' A * '), list('     ')]
        self.assertEqual(bot._unit_step(0), 0)
        self.assertIsNone(bot._straight_delta((0, 0), (1, 1)))
        self.assertEqual(bot._clear_straight_food_distance(grid, (1, 1), (1, 1)), 0)
        self.assertEqual(bot._straight_food_value(grid, (0, 0), 2), bot.INF)
        self.assertTrue(bot._straight_cell_blocked(grid, (-1, 0)))
        self.assertEqual(bot._walk_straight_food(grid, (1, 1), (1, 4), 0, 1, 3), bot.INF)
        self.assertTrue(bot._safe_food_root_blocked('X', {'X': 1}, {}, {}))
        self.assertEqual(bot._enemy_food_distances(grid, deque()), {})
        self.assertTrue(bot._food_candidate_is_better((1, 2, (0, 0)), None))
        self.assertFalse(bot._missing_safe_food_inputs([(1, 3)], deque([(1, 1)])))
        self.assertTrue(bot._safe_food_lock_window({'mode': 'LOCK', 'remaining': 40}))


class TestRootOrchestrationBranches(unittest.TestCase):

    def test_small_uncovered_branch_helpers(self):
        self.assertEqual(bot._tail_or_none(deque([(3, 4)])), (3, 4))
        self.assertEqual(bot._future_escape_state_risk(simple_grid(), deque(), deque(), [], True), bot.FE_FATAL_RISK)
        stats = {'nodes': 0, 'aborted': False}
        self.assertEqual(bot._fe_early_internal_result(True, bot.FE_FATAL_RISK, float('inf'), stats), bot.FE_FATAL_RISK)
        grid = simple_grid()
        my, en = simple_bodies()
        with patch.object(bot, '_fe_enemy_moves', return_value=[]):
            self.assertEqual(bot._fe_enemy_turn_risk(grid, my, en, [], True, 1, float('inf'), {'nodes': 0, 'aborted': False}, {}, 77), 0)
        deadline, deterministic = bot._decision_deadline('time')
        self.assertFalse(deterministic)
        self.assertNotEqual(deadline, float('inf'))
        ctx = {'candidates': [('UP', (0, 0))]}
        penalties, stats2 = bot._forced_trap_layer(ctx, False, float('inf'), True)
        self.assertEqual(penalties, {'UP': 0})
        self.assertEqual(stats2, {'nodes': 0})
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()
        bot.SEARCH_ABORTED = False

    def test_deadline_and_scores(self):
        deadline, deterministic = bot._decision_deadline('nodes')
        self.assertEqual(deadline, float('inf'))
        self.assertTrue(deterministic)
        self.assertEqual(bot._scores_for_side({'score_1': 1, 'score_2': 2}, False), (2, 1))
        self.assertIsNone(bot._enemy_head_from_body(deque()))

    def test_missing_context_and_early_root(self):
        payload = {'board': framed(['   ', ' B ', ' b ']), 'side': 'A', 'game_id': 'missing'}
        self.assertIsNone(bot._build_turn_context(payload, True))
        ctx = {'candidates': [], 'grid': simple_grid(), 'my_body': deque(), 'en_body': deque(), 'food_list': []}
        self.assertEqual(bot._early_root_decision(ctx, True), 'UP')
        ctx2 = {'candidates': [('LEFT', (0, 0))]}
        self.assertEqual(bot._early_root_decision(ctx2, True), 'LEFT')

    def test_disabled_layers_and_budget_helpers(self):
        ctx = {'candidates': [('UP', (0, 0))], 'grid': simple_grid(), 'my_body': deque([(1, 1)]), 'en_body': deque([(1, 5)]), 'food_list': [], 'my_is_a': True, 'strategy': {'mode': 'NORMAL'}}
        self.assertEqual(bot._future_escape_layer(ctx, False, float('inf'), True), {})
        self.assertTrue(bot._time_expired('time', 0.0))
        bot.SEARCH_MODE = 'nodes'
        bot.SEARCH_NODE_BUDGET = 0
        bot.SEARCH_NODES = 0
        self.assertTrue(bot._node_budget_expired('nodes'))
        self.assertEqual(bot._strategy_adjustments_layer(ctx, 'time', 0.0), {'UP': 0})
        self.assertEqual(bot._safe_food_layer(ctx, {}, {}, {}, 'time', 0.0), ({'UP': 0}, {}))

    def test_freeze_disabled_and_adjust_score(self):
        ctx = {'candidates': [('UP', (0, 0))], 'grid': [list('A1B')], 'my_body': deque([(0, 0)]), 'en_body': deque([(0, 2)]), 'food_list': [(0, 1)], 'strategy': {'mode': 'LOCK'}}
        effective, penalties, stats = bot._apple_freeze_layer(ctx, True, {'UP': 0}, {'UP': 0}, 'nodes', float('inf'))
        self.assertTrue(effective)
        self.assertEqual(penalties, {'UP': 0})
        layers = {'fe': {'UP': 1}, 'forced': {'UP': 2}, 'tactical_loss': {'UP': 3}, 'tactical_win': {'UP': 4}, 'safe': {'UP': 5}, 'strategy': {'UP': 6}, 'effective_freeze': True, 'freeze': {'UP': 7}}
        score = bot._adjust_root_score(100, 'UP', layers, True, True, {'UP': 8})
        self.assertEqual(score, 94)

    def test_nontrap_and_final_safety(self):
        ctx = {'candidates': [('UP', (0, 0)), ('RIGHT', (0, 1))], 'grid': simple_grid(), 'my_body': deque([(1, 1), (2, 1)])}
        with patch.object(bot, '_position_is_trap', side_effect=lambda g, p, b: p == (0, 0)):
            self.assertEqual(bot._nontrap_alternative(ctx, 'UP', 'nodes', float('inf')), 'RIGHT')
            self.assertEqual(bot._final_root_safety(ctx, 'UP', 'nodes', float('inf')), 'RIGHT')
        self.assertEqual(bot._final_root_safety(ctx, 'MISSING', 'nodes', float('inf')), 'MISSING')

    def test_choose_missing_and_single_move(self):
        missing = {'board': framed(['   ', ' B ', ' b ']), 'side': 'A', 'game_id': 'choose-missing'}
        self.assertEqual(bot.choose_direction(missing, search_mode='nodes', node_budget=5), 'UP')
        one = {'board': framed(['#####', '#A###', '#a B#', '#  b#', '#####']), 'side': 'A', 'game_id': 'choose-one', 'remaining_moves': 20, 'score_1': 0, 'score_2': 0}
        self.assertIn(bot.choose_direction(one, search_mode='nodes', node_budget=5), bot.DIRECTIONS)


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestAdditionalBranchCoverage(unittest.TestCase):
    def tearDown(self):
        bot.bot_histories.clear()
        bot.TT.clear()

    def test_trace_backtrack_fallback_and_history_false_branches(self):
        grid = [list('Aaa')]
        path = [(0, 0)]
        visited = {(0, 0)}
        self.assertFalse(bot._trace_dfs(grid, (0, 0), 'a', 4, path, visited, [0], 100))
        with patch.object(bot, '_trace_dfs', return_value=False):
            traced = bot._trace_full_snake(grid, (0, 0), 'a')
        self.assertGreaterEqual(len(traced), 1)
        first = bot._history_for_game('same')
        second = bot._history_for_game('same')
        self.assertIs(first, second)
        existing = deque([(0, 0), (0, 1)])
        self.assertIs(bot._resync_path_if_short(existing, 1, grid, (0, 0), 'a'), existing)
        self.assertEqual(bot._side_body_symbols(False)[2:], ('b', 'a'))

    def test_corridor_positive_path(self):
        grid = [list('     '), list(' A B '), list('     ')]
        my = deque([(1, 1)])
        enemy = deque([(1, 3)])
        with patch.object(bot, 'analyze_topology', return_value=(2, 1, False, False, {(1, 2): 1})), \
             patch.object(bot, 'bfs_distances', return_value={(1, 2): 1}), \
             patch.object(bot, '_find_reachable_chokepoint', return_value=(1, 2)):
            self.assertEqual(bot.analyze_corridor_chokepoints(grid, (1, 1), (1, 3), my, enemy), (True, (1, 2), True))

    def test_fe_abort_and_early_return_branches(self):
        grid = simple_grid()
        my, en = simple_bodies()
        stats = {'nodes': 0, 'aborted': False}
        with patch.object(bot, 'get_legal_moves_raw', return_value=[('R', (1, 2))]), \
             patch.object(bot, '_fe_budget_reached', return_value=True):
            bot._fe_my_turn_risk(grid, my, en, [], True, 2, float('inf'), stats, {}, 5)
        self.assertTrue(stats['aborted'])

        stats2 = {'nodes': 0, 'aborted': False}
        with patch.object(bot, '_fe_enemy_moves', return_value=[('L', (1, 4))]), \
             patch.object(bot, '_fe_budget_reached', return_value=True):
            bot._fe_enemy_turn_risk(grid, my, en, [], True, 2, float('inf'), stats2, {}, 7)
        self.assertTrue(stats2['aborted'])

        stats3 = {'nodes': 0, 'aborted': False}
        with patch.object(bot, '_future_escape_state_risk', return_value=11), \
             patch.object(bot, '_fe_early_internal_result', return_value=11):
            self.assertEqual(bot.future_escape_risk(grid, my, en, [], True, 2, True, float('inf'), stats3, {}), 11)

    def test_food_race_small_helpers_all_sides(self):
        self.assertGreater(bot._food_race_value(5, bot.INF, 1), 0)
        self.assertGreater(bot._food_race_value(5, 7, 1), 0)
        self.assertEqual(bot._food_race_side(bot.INF, bot.INF, 1), (None, 0))
        self.assertEqual(bot._food_race_side(3, 3, 1), (None, 0))
        self.assertEqual(bot._weighted_top_two([]), 0)
        self.assertEqual(bot._weighted_top_two([9]), 9)
        self.assertGreater(bot._freeze_penalty_value(2, 3), bot.APPLE_FREEZE_BASE_PENALTY)
        self.assertEqual(bot._topology_for_body_or_empty(simple_grid(), deque()).space, 0)

    def test_root_layer_false_and_true_paths(self):
        numbered_grid = [list('A1B')]
        ctx = {
            'grid': numbered_grid,
            'my_body': deque([(0, 0)]),
            'en_body': deque([(0, 2)]),
            'food_list': [(0, 1)],
            'candidates': [('RIGHT', (0, 1))],
            'strategy': {'mode': 'LOCK', 'remaining': 30},
        }
        effective, penalties, stats = bot._apple_freeze_layer(ctx, True, {'RIGHT': 0}, {'RIGHT': 0}, 'nodes', float('inf'))
        self.assertTrue(effective)
        self.assertEqual(penalties['RIGHT'], 0)
        self.assertTrue(stats['enabled'])

        legacy = dict(ctx)
        legacy['grid'] = [list('A*B')]
        with patch.object(bot, 'compute_apple_freeze_penalties', return_value=({'RIGHT': 123}, {'active': True})):
            effective2, penalties2, _ = bot._apple_freeze_layer(legacy, True, {'RIGHT': 0}, {'RIGHT': 0}, 'nodes', float('inf'))
        self.assertTrue(effective2)
        self.assertEqual(penalties2['RIGHT'], 123)

        layers = {
            'fe': {'R': 3}, 'forced': {'R': 4}, 'tactical_loss': {'R': 5},
            'tactical_win': {'R': 6}, 'safe': {'R': 7}, 'strategy': {'R': 8},
            'effective_freeze': False, 'freeze': {'R': 9},
        }
        self.assertEqual(bot._adjust_root_score(100, 'R', layers, False, False, {'R': 10}), 116)

    def test_nontrap_alternative_deadline_and_skip(self):
        ctx = {
            'candidates': [('UP', (0, 0)), ('RIGHT', (0, 1))],
            'grid': [list('  ')],
            'my_body': deque([(0, 0)]),
        }
        with patch.object(bot, '_time_expired', return_value=True):
            self.assertIsNone(bot._nontrap_alternative(ctx, 'UP', 'time', 0))
        with patch.object(bot, '_time_expired', return_value=False), \
             patch.object(bot, '_position_is_trap', return_value=False):
            self.assertEqual(bot._nontrap_alternative(ctx, 'UP', 'nodes', float('inf')), 'RIGHT')
