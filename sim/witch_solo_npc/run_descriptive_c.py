#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_descriptive_c.py — v1.1裁定に基づく記述的計測C(利己型/チーム型プロキシ)を、
sweep_results.json でA・B双方に合格した組についてのみ実行する。

使い方:
    python run_descriptive_c.py sweep_results.json --out descriptive_c_results.json
"""
import argparse
import json
import sys

import numpy as np

import solo_npc_sim as w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep_json")
    ap.add_argument("--out", default="descriptive_c_results.json")
    ap.add_argument("--n-trials", type=int, default=2000)
    args = ap.parse_args()

    with open(args.sweep_json, encoding="utf-8") as f:
        sweep = json.load(f)

    passing = [r for r in sweep["rows"]
               if r["a1_pass"] and r["a2_pass"] and r["a3_pass"] and r["b1_pass"]]
    print(f"A・B全通過の組: {len(passing)}/15", file=sys.stderr)
    for r in passing:
        print(f"  lambda={r['lambda']} tau={r['tau_name']}({r['tau']})", file=sys.stderr)

    if not passing:
        print("A・B双方に合格した組がありません。記述的Cは空のまま出力します。", file=sys.stderr)
        result = {"passing_combos": [], "descriptive_c": []}
    else:
        desc = w.run_descriptive_c_for_passers(passing, n_trials=args.n_trials, log=print)
        result = {"passing_combos": passing, "descriptive_c": desc}

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
    print(f"結果を {args.out} に書き出しました", file=sys.stderr)


if __name__ == "__main__":
    main()
