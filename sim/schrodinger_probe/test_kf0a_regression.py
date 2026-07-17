"""
K-F0(a): A規則再現（回帰チェック）。事前登録_シュレディンガー工程3prime_kill基準.md
§7 K-F0(a)。simulator_process3prime.play_game_a_rule（本モジュール内の独立実装）で
工程3のM-fix対角セル（imm/marg/prop vs blind, D3・F0-D）を再現し、
results_process3.json の対応CI95との重なりを確認する。

実行結果（2026-07-17実測・確認済み）:
  imm  S-imm/M-fix   point=0.725615 ci=[0.72355, 0.72773]  p3_ci=[0.723535, 0.72767]  overlap=True
  marg S-marg/M-fix  point=0.84996  ci=[0.84774, 0.85213]  p3_ci=[0.84771, 0.85214]   overlap=True
  prop S-prop/M-fix  point=0.49857  ci=[0.49549, 0.50168]  p3_ci=[0.49549, 0.50165]   overlap=True
  KD4-equiv: exc_a=0.34996 exc_c=0.31371 ci=[0.033505,0.03909] p3_ci=[0.033505,0.03909] overlap=True
  prop F0-D point=0.0 (expect exactly 0.0) ... 確認
  elapsed 908.9s
  => K-F0(a) fires=False（発動せず）
"""

import json
import sys
import time

import simulator_process3prime as s3p


def main():
    t0 = time.time()
    p2_key_map = {"imm": "S-imm/M-fix", "marginal": "S-marg/M-fix", "prop": "S-prop/M-fix"}
    with open("results_process3.json", encoding="utf-8") as f:
        p3 = json.load(f)

    results = {}
    for policy, jkey in p2_key_map.items():
        data = s3p.simulate_matchup_a_rule(policy, is_f0d=False, n=s3p.N)
        arr = s3p.compute_win_array_a_rule(data, 0.5)
        point = sum(arr) / len(arr)
        lo, hi = s3p.bootstrap_ci_single_percentile(
            arr, seed=s3p.SEED_BASE + 800000 + s3p.hash_stable(policy))
        p3_ci = p3["kill_conditions"]["K-E0_instrument_check"]["kd1_equivalent_terms"][jkey]["process3_ci"]
        overlap = s3p.ci_overlap(lo, hi, p3_ci[0], p3_ci[1])
        results[policy] = {"point": point, "ci": [lo, hi], "p3_ci": p3_ci, "overlap": overlap}
        print(policy, jkey, "point=", point, "ci=", [lo, hi], "p3_ci=", p3_ci, "overlap=", overlap)

    arr_marg = s3p.compute_win_array_a_rule(
        s3p.simulate_matchup_a_rule("marginal", is_f0d=False, n=s3p.N), 0.5)
    arr_marg_f0d = s3p.compute_win_array_a_rule(
        s3p.simulate_matchup_a_rule("marginal", is_f0d=True, n=s3p.N), 0.5)
    exc_a = sum(arr_marg) / len(arr_marg) - 0.5
    exc_c = sum(arr_marg_f0d) / len(arr_marg_f0d) - 0.5
    lo_kd4, hi_kd4 = s3p.bootstrap_ci_paired_diff(
        [w - 0.5 for w in arr_marg], [w - 0.5 for w in arr_marg_f0d], seed=s3p.SEED_BASE + 800100)
    p3_kd4 = p3["kill_conditions"]["K-E0_instrument_check"]["kd4_equivalent"]["process3_ci"]
    overlap_kd4 = s3p.ci_overlap(lo_kd4, hi_kd4, p3_kd4[0], p3_kd4[1])
    print("KD4-equiv:", "exc_a=", exc_a, "exc_c=", exc_c,
          "ci=", [lo_kd4, hi_kd4], "p3_ci=", p3_kd4, "overlap=", overlap_kd4)

    arr_prop_f0d = s3p.compute_win_array_a_rule(
        s3p.simulate_matchup_a_rule("prop", is_f0d=True, n=s3p.N), 0.5)
    prop_f0d_point = sum(arr_prop_f0d) / len(arr_prop_f0d)
    print("prop F0-D point=", prop_f0d_point, "(expect exactly 0.0)")

    fires = (not all(r["overlap"] for r in results.values())) or (not overlap_kd4) \
        or (abs(prop_f0d_point - 0.0) > 1e-9)
    print("elapsed", time.time() - t0)
    print("K-F0(a) fires =", fires)
    sys.exit(1 if fires else 0)


if __name__ == "__main__":
    main()
