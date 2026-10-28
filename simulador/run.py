"""Juega partidas entre dos bots en el simulador v10.

python run.py BOT1 BOT2 N [--params1 json] [--params2 json] [--seed S] [--procs 4]
Cada semilla se juega dos veces cambiando de lado.
"""
import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_v10 import Game  # noqa: E402


def load(path, params=None, tag=""):
    name = f"bot_{tag}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    for k, v in (params or {}).items():
        if k == "PARAMS":
            mod.PARAMS.update(v)
        else:
            setattr(mod, k, v)
    return mod


def _safe_choice(bot, payload, kw, errors, letter):
    try:
        return bot.choose_direction(payload, **kw)
    except Exception:
        errors[letter] += 1
        if errors[letter] == 1:
            traceback.print_exc()
        return "UP"


def _snake_stats(s):
    return {"score": s.score, "mult": s.mult, "xs": s.xs, "digits": s.digits,
            "dpts": s.digit_points, "crashes": s.crashes, "boom": s.explosions,
            "wrong": s.wrong, "tail": s.tail_food, "len": len(s.body),
            "stars": s.stars, "rams": s.rams}


def play_one(args):
    seed, bot_a, bot_b, pa, pb, choose_kw = args
    bots = {"A": load(bot_a, pa, "a"), "B": load(bot_b, pb, "b")}
    g = Game.new(seed)
    gid = uuid.uuid4().hex
    times = {"A": 0.0, "B": 0.0}
    errors = {"A": 0, "B": 0}
    while not g.over():
        letter = "A" if g.remaining % 2 == 0 else "B"
        payload = g.payload(letter, gid)
        t0 = time.perf_counter()
        action = _safe_choice(bots[letter], payload, choose_kw.get(letter, {}), errors, letter)
        times[letter] = max(times[letter], time.perf_counter() - t0)
        g.play(letter, action)
    res = {"seed": seed, "winner": g.winner(), "rows": g.rows, "cols": g.cols,
           "maxms": {k: round(v * 1000) for k, v in times.items()}, "errors": errors}
    res.update({k: _snake_stats(s) for k, s in g.snakes.items()})
    return res


def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot1")
    ap.add_argument("bot2")
    ap.add_argument("n", type=int)
    for name in ("--p1", "--p2", "--kw1", "--kw2"):
        ap.add_argument(name, default="{}")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--out", default="")
    return ap.parse_args()


def _jobs(a):
    p1, p2 = json.loads(a.p1), json.loads(a.p2)
    k1, k2 = json.loads(a.kw1), json.loads(a.kw2)
    jobs = []
    for i in range(a.n):
        s = a.seed + i
        jobs.append((s, a.bot1, a.bot2, p1, p2, {"A": k1, "B": k2}))  # bot1 = A
        jobs.append((s, a.bot2, a.bot1, p2, p1, {"A": k2, "B": k1}))  # bot1 = B
    return jobs


def _outcome(r, one):
    if r["winner"] is None:
        return "d"
    return "w1" if r["winner"] == one else "w2"


def _add_stats(agg, stats):
    for k, v in stats.items():
        agg[k] = agg.get(k, 0) + v


def _tally(results):
    counts = {"w1": 0, "w2": 0, "d": 0}
    agg = {1: {}, 2: {}}
    for i, r in enumerate(results):
        one = "A" if i % 2 == 0 else "B"
        r["bot1_side"] = one
        counts[_outcome(r, one)] += 1
        _add_stats(agg[1], r[one])
        _add_stats(agg[2], r["B" if one == "A" else "A"])
    return counts, agg


def _report(a, results):
    counts, agg = _tally(results)
    n = len(results)
    print(f"{os.path.basename(a.bot1)} {a.p1} {a.kw1}  vs  {os.path.basename(a.bot2)} {a.p2} {a.kw2}")
    print(f"partidas {n}: bot1 gana {counts['w1']} ({100*counts['w1']/n:.0f}%), "
          f"bot2 gana {counts['w2']}, empates {counts['d']}")
    for idx in (1, 2):
        print(f"  bot{idx} promedio: " + _averages(agg[idx], n))
    _report_times(results)


def _averages(stats, n):
    return ", ".join(f"{k}={v/n:.1f}" for k, v in stats.items())


def _report_times(results):
    slowest = [max(r["maxms"][side] for r in results) for side in ("A", "B")]
    errors = sum(sum(r["errors"].values()) for r in results)
    print("  max ms:", slowest[0], slowest[1], "errores:", errors)


def main():
    a = _parse_args()
    with mp.Pool(a.procs) as pool:
        results = pool.map(play_one, _jobs(a), chunksize=1)
    _report(a, results)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(results, f)


if __name__ == "__main__":
    main()
