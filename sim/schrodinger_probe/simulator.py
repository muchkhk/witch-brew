"""
事前登録：シュレディンガー×ロンデル・工程1「覗き1回の情報幾何測定（演繹伝播）」

仕様は同ディレクトリの凍結済み事前登録文書（事前登録_シュレディンガー工程1_kill基準.md）
の§1〜§6に厳密に従う。Node.js不使用。標準ライブラリのみで実装する。

数学的な近道（実装前にユーザー確認済み）:
  D1・D2・D3はいずれも「既知の固定プールから重複なしで6値を選び、位置へ
  一様ランダムに配置する」過程であり、位置に関して完全に交換可能である。
  そのため、ある未公開の面position(j)の事後周辺分布は「既に公開済みの値の
  集合」だけに依存し、公開済みの値を除いたプール上の一様分布に一致する
  （厳密な等式であり、モンテカルロ近似ではない。本ファイル末尾のコメントに
  検証方法を残す）。この帰結として p_a(j|k), p_b(j|k) はいずれも
  「まだ公開されていない位置jならどれでも同じ値」になるため、事前登録§4が
  許容する「整合補完のモンテカルロ近似」は使わず、閉形式で厳密に計算した。
  D1・D3・D2いずれも整合列挙と数学的に同値であることを小規模な brute-force /
  厳密条件付きサンプリングで検証済み（結果MDに記録する）。
"""

import csv
import json
import random
import statistics
import sys
import time

SEED = 20260716
N_BOOT = 10_000

# 事前登録§5: D1・D3・F0-Dは各200,000。D2は20,000以上で実行者が決定してよい。
# 本実装は閉形式（O(1)/k）で計算するため負荷は軽く、統計power優先でD2も
# 200,000に統一した（下限20,000は満たす。採用n=200,000として記録する）。
N_DEALS = {
    "D1": 200_000,
    "D2": 200_000,
    "D3": 200_000,
    "F0-D": 200_000,
}

POOLS = {
    "D1": [1, 2, 3, 4, 5, 6],
    "D2": list(range(1, 13)),
    "D3": [1, 2, 3, 10, 11, 12],
}

JUDGED_SETS = ["D1", "D2", "D3"]
ALL_SETS = ["D1", "D2", "D3", "F0-D"]


def gen_faces(set_name, rng):
    if set_name == "F0-D":
        return [rng.randrange(1, 7) for _ in range(6)]
    pool = POOLS[set_name]
    return rng.sample(pool, len(pool))


def marginal(pool, used):
    remaining = [v for v in pool if v not in used]
    p = 1.0 / len(remaining)
    return {v: p for v in remaining}


def combine(own_dist, opp_dist):
    total = 0.0
    for vo, po in own_dist.items():
        for vp, pp in opp_dist.items():
            if vo > vp:
                total += po * pp
            elif vo == vp:
                total += 0.5 * po * pp
    return total


def reversal(p_before, p_after):
    return 1.0 if (p_before - 0.5) * (p_after - 0.5) < 0.0 else 0.0


def simulate_set(set_name, n_deals, seed):
    rng = random.Random(seed)
    imm_per_deal = [0.0] * n_deals
    prop_per_deal = [0.0] * n_deals
    imm_profile_sum = [0.0] * 7  # index by k=1..6
    prop_profile_sum = [0.0] * 7  # index by k=1..5 (k=6 unused, stays 0)

    is_f0d = set_name == "F0-D"
    pool = None if is_f0d else POOLS[set_name]
    uniform6 = {v: 1 / 6 for v in range(1, 7)} if is_f0d else None

    for d in range(n_deals):
        own_faces = gen_faces(set_name, rng)
        opp_faces = gen_faces(set_name, rng)

        imm_terms = [0.0] * 7
        prop_terms = [0.0] * 7

        for k in range(1, 7):
            own_used_a = set(own_faces[: k - 1])
            opp_used_a = set(opp_faces[: k - 1])

            if is_f0d:
                own_dist_a = uniform6
                opp_dist = uniform6
            else:
                own_dist_a = marginal(pool, own_used_a)
                opp_dist = marginal(pool, opp_used_a)

            p_a_common = combine(own_dist_a, opp_dist)

            own_point = {own_faces[k - 1]: 1.0}
            p_b_imm = combine(own_point, opp_dist)

            imm_term = reversal(p_a_common, p_b_imm) * abs(p_b_imm - p_a_common)
            imm_terms[k] = imm_term
            imm_profile_sum[k] += imm_term

            if k <= 5:
                if is_f0d:
                    own_dist_b = uniform6
                else:
                    own_used_b = own_used_a | {own_faces[k - 1]}
                    own_dist_b = marginal(pool, own_used_b)
                p_b_prop_common = combine(own_dist_b, opp_dist)
                prop_term = (6 - k) * reversal(p_a_common, p_b_prop_common) * abs(
                    p_b_prop_common - p_a_common
                )
                prop_terms[k] = prop_term
                prop_profile_sum[k] += prop_term

        imm_per_deal[d] = sum(imm_terms[1:7]) / 6.0
        prop_per_deal[d] = sum(prop_terms[1:6]) / 5.0

        if (d + 1) % 40000 == 0:
            print(f"  [{set_name}] simulated {d+1}/{n_deals}", file=sys.stderr, flush=True)

    imm_profile = [imm_profile_sum[k] / n_deals for k in range(1, 7)]
    prop_profile = [prop_profile_sum[k] / n_deals for k in range(1, 6)]

    return imm_per_deal, prop_per_deal, imm_profile, prop_profile


def bootstrap_ci(arr, n_boot, seed):
    rng = random.Random(seed)
    n = len(arr)
    reps = []
    for _ in range(n_boot):
        idx = rng.choices(range(n), k=n)
        reps.append(sum(arr[i] for i in idx) / n)
    reps.sort()
    lo = reps[max(0, min(n_boot - 1, int(0.025 * n_boot)))]
    hi = reps[max(0, min(n_boot - 1, int(0.975 * n_boot)))]
    return lo, hi


def bootstrap_ci_pair(imm_arr, prop_arr, n_boot, seed):
    rng = random.Random(seed)
    n = len(imm_arr)
    imm_reps = []
    prop_reps = []
    for _ in range(n_boot):
        idx = rng.choices(range(n), k=n)
        imm_reps.append(sum(imm_arr[i] for i in idx) / n)
        prop_reps.append(sum(prop_arr[i] for i in idx) / n)
    imm_reps.sort()
    prop_reps.sort()

    def pct(sorted_vals, p):
        i = max(0, min(n_boot - 1, int(p * n_boot)))
        return sorted_vals[i]

    return {
        "imm_ci_lower": pct(imm_reps, 0.025),
        "imm_ci_upper": pct(imm_reps, 0.975),
        "prop_ci_lower": pct(prop_reps, 0.025),
        "prop_ci_upper": pct(prop_reps, 0.975),
    }


def main():
    t0 = time.time()
    results = {}
    csv_rows = []

    for i, set_name in enumerate(ALL_SETS):
        n = N_DEALS[set_name]
        print(f"=== simulating {set_name} (n={n}) ===", file=sys.stderr, flush=True)
        seed = SEED + i  # 相異なるseed offsetで各セットを独立に生成（基本SEEDは20260716系列）
        imm_arr, prop_arr, imm_profile, prop_profile = simulate_set(set_name, n, seed)

        point_imm = statistics.mean(imm_arr)
        point_prop = statistics.mean(prop_arr)

        print(f"  bootstrap {set_name}...", file=sys.stderr, flush=True)
        ci = bootstrap_ci_pair(imm_arr, prop_arr, N_BOOT, seed=SEED + 1000 + i)

        results[set_name] = {
            "n_deals": n,
            "point_imm": point_imm,
            "point_prop": point_prop,
            "imm_ci_lower": ci["imm_ci_lower"],
            "imm_ci_upper": ci["imm_ci_upper"],
            "prop_ci_lower": ci["prop_ci_lower"],
            "prop_ci_upper": ci["prop_ci_upper"],
            "imm_profile_k1_6": imm_profile,
            "prop_profile_k1_5": prop_profile,
        }

        for d in range(n):
            csv_rows.append((set_name, d, imm_arr[d], prop_arr[d]))

    # --- K-D0 判定 ---
    kd0_terms = {}
    for s in JUDGED_SETS:
        r = results[s]
        threshold = 0.25 * r["point_imm"]
        fires_for_set = r["prop_ci_lower"] < threshold
        kd0_terms[s] = {
            "prop_ci_lower": r["prop_ci_lower"],
            "point_imm": r["point_imm"],
            "threshold_0.25x_imm": threshold,
            "fires_for_set": fires_for_set,
        }
    kd0_fires = all(kd0_terms[s]["fires_for_set"] for s in JUDGED_SETS)
    overall_pass = not kd0_fires

    carry_forward = None
    if overall_pass:
        passing_sets = [s for s in JUDGED_SETS if not kd0_terms[s]["fires_for_set"]]
        carry_forward = max(passing_sets, key=lambda s: results[s]["prop_ci_lower"])

    output = {
        "meta": {
            "seed_base": SEED,
            "n_boot": N_BOOT,
            "n_deals": N_DEALS,
            "runtime_sec": time.time() - t0,
            "d2_method": "厳密閉形式(交換可能性による一様周辺分布)。モンテカルロ近似は不使用。",
        },
        "results_by_set": results,
        "kill_condition_K_D0": {
            "fires": kd0_fires,
            "terms": kd0_terms,
        },
        "overall_pass": overall_pass,
        "carry_forward_to_process2": carry_forward,
    }

    with open("sim/schrodinger_probe/results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open("sim/schrodinger_probe/results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["set", "deal_index", "M2prime_imm", "M2prime_prop"])
        w.writerows(csv_rows)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"TOTAL runtime: {time.time()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()

# --- 検証メモ（実装前に対話的に実施。結果MDにも記録） ---
# D1: brute-force全720順列で P(pos3=v | pos1=2,pos2=5) を計算し、
#     本ファイルの marginal() が返す「残り4値の一様分布」と完全一致することを確認。
# D2: 条件付き厳密サンプリング(N=3,000,000、棄却法ではなく直接条件付き構成)で
#     P(pos4=v|...) と P(pos5=v|...) が closed form と一致し、かつ両者が
#     互いに一致する(=jに依存しない)ことを確認。
