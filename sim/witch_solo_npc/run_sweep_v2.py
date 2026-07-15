#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_sweep_v2.py — 「witch ソロNPC方策計測 v2（A3置換・能力下限D追加）」の実行スクリプト。

v1の資産(solo_npc_sim.py)を流用し、A-3'(最初の選択者の予測的中率)とD(能力下限)を追加計測する。
グリッド: λ∈{0.5,0.8,1.0} × τ∈{2.5,3.5,4.5,6.0} の12組。
τ=6.0の3組(v1のτ=large=6.0と同一パラメータ)は、B-1(計測B)をv1のsweep_results.jsonから
再利用できる(A-3'/Dはv1未計測のため常に新規計測)。

使い方:
    python run_sweep_v2.py --n-trials 2000 --out sweep_results_v2.json --v1 sweep_results.json
"""
import argparse
import json
import sys
import time

import numpy as np

import solo_npc_sim as w

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def load_v1_b1(v1_path):
    """v1のsweep_results.jsonから、(lambda, tau)をキーにB1関連の値を引けるdictを作る。"""
    with open(v1_path, encoding="utf-8") as f:
        v1 = json.load(f)
    out = {}
    for row in v1["rows"]:
        key = (row["lambda"], row["tau"])
        out[key] = {
            "b1_pass": row["b1_pass"], "b1_diff": row["b1_diff"],
            "b1_ci_lo": row["b1_ci_lo"], "b1_ci_hi": row["b1_ci_hi"],
            "b1_rel_pct": row["b1_rel_pct"],
            "b1_mean_consistent": row["b1_mean_consistent"], "b1_mean_random": row["b1_mean_random"],
            "reused_from_v1": True,
        }
    return out


LAMBDA_GRID_V2 = [0.5, 0.8, 1.0]
TAU_GRID_V2 = {"2.5": 2.5, "3.5": 3.5, "4.5": 4.5, "6.0": 6.0}
GRID_V2 = [(lam, tn, tv) for lam in LAMBDA_GRID_V2 for tn, tv in TAU_GRID_V2.items()]
assert len(GRID_V2) == 12


def run_sweep_v2(n_trials=2000, seed=w.MASTER_SEED, v1_b1_lookup=None, log=print):
    rng = np.random.default_rng(seed)
    v1_b1_lookup = v1_b1_lookup or {}

    rows = []
    for i, (lam, tau_name, tau_val) in enumerate(GRID_V2):
        t0 = time.time()
        ad = w.measurement_a_and_d(lam, tau_val, n_trials, rng)
        t_ad = time.time() - t0

        v1_key = (lam, tau_val)
        if v1_key in v1_b1_lookup:
            b = dict(v1_b1_lookup[v1_key])
            t_b = 0.0
        else:
            t0 = time.time()
            b_full = w.measurement_b(lam, tau_val, n_trials, rng)
            t_b = time.time() - t0
            b = {"b1_pass": b_full["b1_pass"], "b1_diff": b_full["diff"],
                 "b1_ci_lo": b_full["ci_lo"], "b1_ci_hi": b_full["ci_hi"],
                 "b1_rel_pct": b_full["rel_pct"],
                 "b1_mean_consistent": b_full["mean_consistent"], "b1_mean_random": b_full["mean_random"],
                 "reused_from_v1": False}

        all_pass = ad["a1_pass"] and ad["a2_pass"] and ad["a3prime_pass"] and b["b1_pass"] and ad["d_pass"]

        row = {
            "lambda": lam, "tau_name": tau_name, "tau": tau_val,
            "a1_pass": ad["a1_pass"], "a2_pass": ad["a2_pass"], "a3prime_pass": ad["a3prime_pass"],
            "b1_pass": b["b1_pass"], "d_pass": ad["d_pass"], "all_pass": all_pass,
            "median_curve": ad["median_curve"], "q1_curve": ad["q1_curve"], "q3_curve": ad["q3_curve"],
            "hit_rate_curve": ad["hit_rate_curve"],
            "a3prime_avg_round56": ad["a3prime_avg_round56"], "a3prime_avg_round12": ad["a3prime_avg_round12"],
            "a3prime_delta": ad["a3prime_delta"],
            "top1_hit_rate_round6": ad["top1_hit_rate_round6"],
            "pct_mean": ad["pct_mean"], "pct_median": ad["pct_median"],
            "b1_diff": b["b1_diff"], "b1_ci_lo": b["b1_ci_lo"], "b1_ci_hi": b["b1_ci_hi"],
            "b1_rel_pct": b["b1_rel_pct"], "b1_mean_consistent": b["b1_mean_consistent"],
            "b1_mean_random": b["b1_mean_random"], "b1_reused_from_v1": b["reused_from_v1"],
            "time_ad_s": t_ad, "time_b_s": t_b,
        }
        rows.append(row)
        log(f"[{i+1}/12] lambda={lam} tau={tau_name} "
            f"A1={ad['a1_pass']} A2={ad['a2_pass']} A3'={ad['a3prime_pass']}(r56={ad['a3prime_avg_round56']:.2f},Δ={ad['a3prime_delta']:.2f}) "
            f"B1={b['b1_pass']}{'(reused)' if b['reused_from_v1'] else ''} D={ad['d_pass']}(pct={ad['pct_mean']:.1f}) "
            f"ALL={all_pass} | t=({t_ad:.1f}/{t_b:.1f}s)")

    # 選定規則: 全通過組の中で、A-3'儀式5-6的中率が最大の組。同率はB-1効果量最大の組。
    passers = [r for r in rows if r["all_pass"]]
    selected = None
    if passers:
        max_r56 = max(r["a3prime_avg_round56"] for r in passers)
        tied = [r for r in passers if abs(r["a3prime_avg_round56"] - max_r56) < 1e-9]
        selected = max(tied, key=lambda r: r["b1_rel_pct"])

    return {"n_trials": n_trials, "seed": seed, "rows": rows,
            "n_passers": len(passers), "selected": selected}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--n-trials", type=int, default=2000)
    ap.add_argument("--out", default="sweep_results_v2.json")
    ap.add_argument("--v1", default="sweep_results.json")
    args = ap.parse_args()

    n_trials = 20 if args.smoke else args.n_trials
    v1_lookup = load_v1_b1(args.v1)
    print(f"v1から流用可能なB-1: {len(v1_lookup)}件 {list(v1_lookup.keys())}", file=sys.stderr)

    result = run_sweep_v2(n_trials=n_trials, seed=w.MASTER_SEED, v1_b1_lookup=v1_lookup)

    class NumpyJSONEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, np.bool_):
                return bool(o)
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                return float(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
            return super().default(o)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, cls=NumpyJSONEncoder)
    print(f"結果を {args.out} に書き出しました (全通過組: {result['n_passers']}/12)", file=sys.stderr)


if __name__ == "__main__":
    main()
