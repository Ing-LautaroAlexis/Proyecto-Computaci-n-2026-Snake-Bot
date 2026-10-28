"""Rival heurístico para el simulador: imita a Alejo / Santino / Agustín.

PARAMS se puede cambiar por instancia:
  x_weight   : cuánto valora una X (1 = valor "justo" de un paso de multiplicador)
  camp       : si se queda esperando al lado del número que viene cuando pierde la carrera
  chase      : si igual va al número que toca aunque vaya perdiendo la carrera
  star_bonus : cuánto suma una estrella además de sus +100 x multiplicador
"""
from collections import deque

STATS = {"lose": 0, "camp": 0, "turns": 0}
PARAMS = {"x_weight": 1.0, "camp": True, "turns_per_digit": 22, "camp_bonus": 1.0, "chase": False,
          "star_bonus": 1500}
DIRS = {"UP": (-1, 0), "DOWN": (1, 0), "LEFT": (0, -1), "RIGHT": (0, 1)}
BIG, SMALL = "\U0001f4a3", "\U0001f9e8"
BOMB_RADIUS = {BIG: 2, SMALL: 1}
TAIL_FOR = {"A": "Ⓐ", "B": "Ⓑ"}
STAR = "⭐"
INF = 10 ** 6
SOLID = frozenset(("#", "a", "b", "A", "B", BIG, SMALL))


def _grid(board):
    return [list(r[1:-1]) for r in board.replace("️", "").strip("\n").split("\n")]


def _digits(grid):
    return {int(c) for row in grid for c in row if c.isdigit()}


def _target(grid):
    present = _digits(grid)
    firsts = [d for d in sorted(present) if (d + 7) % 9 + 1 not in present]
    return firsts[0] if firsts else None


def _cells(grid, pred):
    return [(r, c) for r, row in enumerate(grid) for c, v in enumerate(row) if pred(v)]


def _neighbors(cur):
    return [(cur[0] + dr, cur[1] + dc) for dr, dc in DIRS.values()]


def _inside(grid, n):
    return 0 <= n[0] < len(grid) and 0 <= n[1] < len(grid[0])


def _can_visit(grid, n, dist, blocked):
    return _inside(grid, n) and n not in dist and n not in blocked


def _bfs(grid, start, blocked):
    dist = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        for n in _neighbors(cur):
            if _can_visit(grid, n, dist, blocked):
                dist[n] = dist[cur] + 1
                q.append(n)
    return dist


def _reach(dist, p, inf=INF):
    """Distancia a una celda bloqueada (p. ej. un número que todavía no toca)."""
    if p in dist:
        return dist[p]
    return 1 + min((dist.get(n, inf) for n in _neighbors(p)), default=inf)


def _normalize_case(grid, game_data):
    """v10: invencible = cabeza minúscula y cuerpo mayúscula; lo dejo como siempre."""
    for letter, key in (("A", "invincible_1"), ("B", "invincible_2")):
        if game_data.get(key):
            swap = {letter: letter.lower(), letter.lower(): letter}
            for row in grid:
                row[:] = [swap.get(v, v) for v in row]


def _find(grid, letter):
    found = _cells(grid, lambda v: v == letter)
    return found[0] if found else None


def _bomb_zone(grid):
    zone = set()
    for (r, c) in _cells(grid, lambda v: v in BOMB_RADIUS):
        rad = BOMB_RADIUS[grid[r][c]]
        span = range(-rad, rad + 1)
        zone.update((r + i, c + j) for i in span for j in span)
    return zone


def _sides(game_data):
    if str(game_data.get("side", "A")).upper() in ("A", "1"):
        return "A", "B"
    return "B", "A"


def _my_mult(game_data, me):
    return game_data.get("multiplier_1" if me == "A" else "multiplier_2", 1) or 1


def _read_state(game_data):
    """Todo lo que hace falta para decidir, en un dict."""
    grid = _grid(game_data["board"])
    _normalize_case(grid, game_data)
    me, en = _sides(game_data)
    t = _target(grid)
    st = {
        "grid": grid, "me": me, "head": _find(grid, me), "ehead": _find(grid, en),
        "mult": _my_mult(game_data, me),
        "remaining": game_data.get("remaining_moves", 400), "t": t,
        "zone": _bomb_zone(grid),
        "walls": set(_cells(grid, lambda v: v in SOLID)),
        "wrong": set(_cells(grid, lambda v: v.isdigit() and int(v) != t)),
        "my_len": sum(row.count(me.lower()) for row in grid) + 1,
    }
    st["blocked"] = st["walls"] | st["zone"] | st["wrong"]
    return st


def _distances(st):
    st["dme"] = _bfs(st["grid"], st["head"], st["blocked"] - {st["head"]})
    ehead = st["ehead"]
    st["den"] = _bfs(st["grid"], ehead, st["blocked"] - {ehead}) if ehead else {}


# ------------------------------------------------------------ objetivos
def _item_goals(st):
    grid, mult = st["grid"], st["mult"]
    x_val = PARAMS["x_weight"] * (st["remaining"] / 2) / PARAMS["turns_per_digit"] * 500
    goals = [(x_val, p, False) for p in _cells(grid, lambda v: v == "X")
             if st["dme"].get(p, INF) < st["den"].get(p, INF) + 2]
    bonus = (TAIL_FOR[st["me"]], "*")
    goals += [(100 * mult, p, False) for p in _cells(grid, lambda v: v in bonus)]
    star = 100 * mult + PARAMS["star_bonus"]
    goals += [(star, p, False) for p in _cells(grid, lambda v: v == STAR)]
    return goals


def _best_camp_spot(st, copies):
    """Copia del número que viene donde llego antes que el rival (margen, celda)."""
    e_t = min(copies, key=lambda p: st["den"].get(p, INF)) if copies else st["ehead"]
    de_from = _bfs(st["grid"], e_t, st["blocked"] - {e_t})
    nxt = str(st["t"] % 9 + 1)
    spots = [(_reach(de_from, p) - _reach(st["dme"], p), p)
             for p in _cells(st["grid"], lambda v: v == nxt) if _reach(st["dme"], p) < INF]
    return max(spots, key=lambda item: item[0], default=None)


def _camp_goals(st, copies):
    best = _best_camp_spot(st, copies)
    if not best or best[0] <= 0:
        return []
    STATS["camp"] += 1
    value = (st["t"] % 9 + 1) * 100 * st["mult"] * PARAMS["camp_bonus"]
    return [(value, best[1], True)]


def _losing_goals(st, copies):
    """Pierdo la carrera: voy igual (chase) o espero al lado del que viene (camp)."""
    STATS["lose"] += 1
    goals = []
    if PARAMS["chase"]:
        goals += [(st["t"] * 100 * st["mult"] * 0.5, p, False) for p in copies]
    if PARAMS["camp"] and st["ehead"]:
        goals += _camp_goals(st, copies)
    return goals


def _winning_copies(st, copies):
    en_best = min((st["den"].get(p, INF) for p in copies), default=INF)
    return [p for p in copies if st["dme"].get(p, INF) <= en_best]


def _digit_goals(st):
    t = st["t"]
    if not t:
        return []
    copies = _cells(st["grid"], lambda v: v == str(t))
    win = _winning_copies(st, copies)
    STATS["turns"] += 1
    if win:
        return [(t * 100 * st["mult"] * 1.5, p, False) for p in win]
    return _losing_goals(st, copies)


# ------------------------------------------------------------ puntuación
def _camp_goal_value(val, spot, n, dn):
    if n == spot:
        return 0
    if abs(n[0] - spot[0]) + abs(n[1] - spot[1]) > 2:
        return val / (1 + max(0, _reach(dn, spot) - 1))
    return val * 0.9


def _goal_value(goal, n, dn):
    val, g, camp = goal
    if camp:
        return _camp_goal_value(val, g, n, dn)
    d = 0 if n == g else dn.get(g, INF)
    return val / (1 + d) if d < INF else 0


def _danger(st, n, area):
    score = -5e6 if n in st["zone"] else 0.0
    if n in st["wrong"]:
        score -= 3e6
    short = st["my_len"] + 2 - area
    return score - 1e6 * short if short > 0 else score


def _move_score(st, goals, n):
    dn = _bfs(st["grid"], n, (st["blocked"] | {st["head"]}) - {n})
    area = len(dn)
    gscore = max([0] + [_goal_value(goal, n, dn) for goal in goals])
    return _danger(st, n, area) + gscore + area * 0.5


def _candidate_moves(st):
    head = st["head"]
    moves = [(name, (head[0] + dr, head[1] + dc)) for name, (dr, dc) in DIRS.items()]
    return [(name, n) for name, n in moves
            if _inside(st["grid"], n) and n not in st["walls"]]


def choose_direction(game_data):
    st = _read_state(game_data)
    if st["head"] is None:
        return "UP"
    _distances(st)
    goals = _item_goals(st) + _digit_goals(st)
    best_move, best_score = None, -INF
    for name, n in _candidate_moves(st):
        score = _move_score(st, goals, n)
        if score > best_score:
            best_move, best_score = name, score
    return best_move or "UP"
