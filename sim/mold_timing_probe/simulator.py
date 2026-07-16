"""
事前登録：鋳型のサイコロ・工程1「タイミング市場の実在検証」

仕様は本ファイルと同じディレクトリに凍結されている事前登録文書に厳密に従う。
Node.js不使用（CLAUDE.md §9-f）。標準ライブラリのみで実装する。

方向決定の補完規則（ユーザー確認済み、2026-07-16）:
  S-early / S-wait / S-mold の「どちらの側に賭けるか」は、事前登録文書に
  明示的なモデルが無かったため、S-blind以外の全戦略は「真の生成モデル
  （鋳型ベイズ）」の勝ち事後 P を方向決定にも流用する、という解釈で
  実装する。S-blind のみ、自身の周辺分布モデルの事後を方向決定にも使う。
"""

import csv
import json
import random
import statistics
import sys
import time
from bisect import bisect_right

SEED = 20260716
N_DEALS = 100_000
N_BOOT = 10_000

H_VALUES = (4, 5, 6, 7, 8, 9)
L_VALUES = (1, 2, 3, 4, 5, 6)
SHARED = frozenset((4, 5, 6))
L_ONLY = frozenset((1, 2, 3))
H_ONLY = frozenset((7, 8, 9))

H_DIST = {v: 1 / 6 for v in H_VALUES}
L_DIST = {v: 1 / 6 for v in L_VALUES}
MARGINAL_DIST = {1: 1/12, 2: 1/12, 3: 1/12, 4: 1/6, 5: 1/6, 6: 1/6, 7: 1/12, 8: 1/12, 9: 1/12}

CURVES = {
    "C1": [2.6, 2.4, 2.2, 2.0, 1.8, 1.6],
    "C2": [2.80, 2.38, 2.02, 1.72, 1.46, 1.24],
    "C3": [2.4, 2.4, 2.4, 1.8, 1.8, 1.3],
}

STRATEGIES = ["S-early", "S-wait", "S-th65", "S-mold", "S-blind"]


def pmf_sum_from_dist(base_dist, n):
    dist = {0: 1.0}
    for _ in range(n):
        new = {}
        for s, pr in dist.items():
            for v, pv in base_dist.items():
                key = s + v
                new[key] = new.get(key, 0.0) + pr * pv
        dist = new
    return dist


def diff_pmf(pmf_x, pmf_y):
    d = {}
    for a, pa in pmf_x.items():
        for b, pb in pmf_y.items():
            k = a - b
            d[k] = d.get(k, 0.0) + pa * pb
    return d


def make_lookup(d):
    keys = sorted(d.keys())
    n = len(keys)
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + d[keys[i]]
    return keys, suffix, d


def survival_strict(lookup, k):
    keys, suffix, _ = lookup
    idx = bisect_right(keys, k)
    return suffix[idx]


def pmf_at(lookup, k):
    _, _, d = lookup
    return d.get(k, 0.0)


def build_tables():
    pmf_H = {}
    pmf_L = {}
    pmf_M = {}
    for n in range(0, 7):
        pmf_H[n] = pmf_sum_from_dist(H_DIST, n)
        pmf_L[n] = pmf_sum_from_dist(L_DIST, n)
        pmf_M[n] = pmf_sum_from_dist(MARGINAL_DIST, n)

    diff_lookup = {}
    diff_lookup_blind = {}
    base = {"H": pmf_H, "L": pmf_L}
    for n in range(0, 7):
        diff_lookup[n] = {}
        for X in ("H", "L"):
            for Y in ("H", "L"):
                diff_lookup[n][(X, Y)] = make_lookup(diff_pmf(base[X][n], base[Y][n]))
        diff_lookup_blind[n] = make_lookup(diff_pmf(pmf_M[n], pmf_M[n]))
    return diff_lookup, diff_lookup_blind


def first_exclusive_index(faces):
    for i, v in enumerate(faces, start=1):
        if v not in SHARED:
            return i
    return None


def unresolved_count(faces):
    idx = first_exclusive_index(faces)
    return 6 if idx is None else idx - 1


def mold_state_at(resolved_mold):
    if resolved_mold == "H":
        return 1.0, 0.0
    if resolved_mold == "L":
        return 0.0, 1.0
    return 0.5, 0.5


def true_win_posterior(diff_lookup, remaining_n, PH_own, PL_own, PH_opp, PL_opp, k):
    p_self = 0.0
    p_tie = 0.0
    for X, PX in (("H", PH_own), ("L", PL_own)):
        if PX == 0.0:
            continue
        for Y, PY in (("H", PH_opp), ("L", PL_opp)):
            if PY == 0.0:
                continue
            w = PX * PY
            lookup = diff_lookup[remaining_n][(X, Y)]
            p_self += w * survival_strict(lookup, k)
            p_tie += w * pmf_at(lookup, k)
    return p_self + 0.5 * p_tie


def blind_win_posterior(diff_lookup_blind, remaining_n, k):
    lookup = diff_lookup_blind[remaining_n]
    p_self = survival_strict(lookup, k)
    p_tie = pmf_at(lookup, k)
    return p_self + 0.5 * p_tie


def run_simulation():
    diff_lookup, diff_lookup_blind = build_tables()
    rng = random.Random(SEED)

    payoff = {c: {s: [0.0] * N_DEALS for s in STRATEGIES} for c in CURVES}
    bet_t_records = {"S-th65": [0] * N_DEALS, "S-mold": [0] * N_DEALS, "S-blind": [0] * N_DEALS}
    unresolved_counts = []  # K-A2: over all 2*N_DEALS individual dice
    csv_rows = []  # raw per-deal record for results.csv

    for d in range(N_DEALS):
        self_mold = H_VALUES if rng.random() < 0.5 else L_VALUES
        self_faces = [rng.choice(self_mold) for _ in range(6)]
        opp_mold = H_VALUES if rng.random() < 0.5 else L_VALUES
        opp_faces = [rng.choice(opp_mold) for _ in range(6)]

        unresolved_self = unresolved_count(self_faces)
        unresolved_opp = unresolved_count(opp_faces)
        unresolved_counts.append(unresolved_self)
        unresolved_counts.append(unresolved_opp)

        own_resolve_idx = first_exclusive_index(self_faces)
        opp_resolve_idx = first_exclusive_index(opp_faces)

        own_total = sum(self_faces)
        opp_total = sum(opp_faces)

        own_resolved_mold = None
        opp_resolved_mold = None
        own_cumsum = 0
        opp_cumsum = 0

        P_true_by_t = [0.0] * 6
        P_blind_by_t = [0.0] * 6

        for t in range(0, 6):
            if t > 0:
                v_own = self_faces[t - 1]
                own_cumsum += v_own
                if own_resolved_mold is None and v_own not in SHARED:
                    own_resolved_mold = "L" if v_own in L_ONLY else "H"
                v_opp = opp_faces[t - 1]
                opp_cumsum += v_opp
                if opp_resolved_mold is None and v_opp not in SHARED:
                    opp_resolved_mold = "L" if v_opp in L_ONLY else "H"

            PH_own, PL_own = mold_state_at(own_resolved_mold)
            PH_opp, PL_opp = mold_state_at(opp_resolved_mold)

            shift = own_cumsum - opp_cumsum
            k = -shift
            remaining_n = 6 - t

            P_true_by_t[t] = true_win_posterior(
                diff_lookup, remaining_n, PH_own, PL_own, PH_opp, PL_opp, k
            )
            P_blind_by_t[t] = blind_win_posterior(diff_lookup_blind, remaining_n, k)

        # --- strategy timing + direction decisions ---
        se_t = 0
        se_side = "self" if P_true_by_t[se_t] >= 0.5 else "opp"

        sw_t = 5
        sw_side = "self" if P_true_by_t[sw_t] >= 0.5 else "opp"

        st_t = 5
        for t in range(0, 6):
            fav = max(P_true_by_t[t], 1.0 - P_true_by_t[t])
            if fav > 0.65:
                st_t = t
                break
        st_side = "self" if P_true_by_t[st_t] >= 0.5 else "opp"

        candidates = [x for x in (own_resolve_idx, opp_resolve_idx) if x is not None and x <= 5]
        sm_t = min(candidates) if candidates else 5
        sm_side = "self" if P_true_by_t[sm_t] >= 0.5 else "opp"

        sb_t = 5
        for t in range(0, 6):
            fav = max(P_blind_by_t[t], 1.0 - P_blind_by_t[t])
            if fav > 0.65:
                sb_t = t
                break
        sb_side = "self" if P_blind_by_t[sb_t] >= 0.5 else "opp"

        bet_t_records["S-th65"][d] = st_t
        bet_t_records["S-mold"][d] = sm_t
        bet_t_records["S-blind"][d] = sb_t

        decisions = {
            "S-early": (se_t, se_side),
            "S-wait": (sw_t, sw_side),
            "S-th65": (st_t, st_side),
            "S-mold": (sm_t, sm_side),
            "S-blind": (sb_t, sb_side),
        }

        for strat, (bt, side) in decisions.items():
            if side == "self":
                if own_total > opp_total:
                    W = 1.0
                elif own_total == opp_total:
                    W = 0.5
                else:
                    W = 0.0
            else:
                if opp_total > own_total:
                    W = 1.0
                elif opp_total == own_total:
                    W = 0.5
                else:
                    W = 0.0
            for cname, curve in CURVES.items():
                m = curve[bt]
                payoff[cname][strat][d] = m * W - 1.0

        row = [d, unresolved_self, unresolved_opp, own_total, opp_total]
        for strat in STRATEGIES:
            bt, side = decisions[strat]
            row.extend([bt, side])
        for cname in CURVES:
            for strat in STRATEGIES:
                row.append(payoff[cname][strat][d])
        csv_rows.append(row)

        if (d + 1) % 20000 == 0:
            print(f"  simulated {d+1}/{N_DEALS} deals", file=sys.stderr, flush=True)

    return payoff, bet_t_records, unresolved_counts, csv_rows


def bootstrap_diffs(payoff, n_boot, seed_offset):
    """Paired bootstrap. Returns, per curve, dict of diff-name -> sorted list of bootstrap replicate values."""
    boot_rng = random.Random(SEED + seed_offset)
    results = {}
    pair_specs = [
        ("S-early_minus_S-wait", "S-early", "S-wait"),
        ("S-th65_minus_S-wait", "S-th65", "S-wait"),
        ("S-mold_minus_S-wait", "S-mold", "S-wait"),
        ("S-wait_minus_S-early", "S-wait", "S-early"),
        ("S-th65_minus_S-early", "S-th65", "S-early"),
        ("S-mold_minus_S-early", "S-mold", "S-early"),
        ("S-th65_minus_S-blind", "S-th65", "S-blind"),
    ]
    for cname, arrs in payoff.items():
        replicate_diffs = {name: [] for name, _, _ in pair_specs}
        t0 = time.time()
        for rep in range(n_boot):
            idx = boot_rng.choices(range(N_DEALS), k=N_DEALS)
            means = {s: sum(arrs[s][i] for i in idx) / N_DEALS for s in STRATEGIES}
            for name, a, b in pair_specs:
                replicate_diffs[name].append(means[a] - means[b])
            if (rep + 1) % 2000 == 0:
                print(f"  [{cname}] bootstrap {rep+1}/{n_boot} ({time.time()-t0:.1f}s)", file=sys.stderr, flush=True)
        for name in replicate_diffs:
            replicate_diffs[name].sort()
        results[cname] = replicate_diffs
    return results


def percentile(sorted_vals, p):
    n = len(sorted_vals)
    idx = int(p * n)
    idx = max(0, min(n - 1, idx))
    return sorted_vals[idx]


def main():
    t0 = time.time()
    print("=== simulating deals ===", file=sys.stderr)
    payoff, bet_t_records, unresolved_counts, csv_rows = run_simulation()
    print(f"simulation done in {time.time()-t0:.1f}s", file=sys.stderr)

    point_estimates = {
        c: {s: statistics.mean(payoff[c][s]) for s in STRATEGIES} for c in CURVES
    }

    t1 = time.time()
    print("=== bootstrap ===", file=sys.stderr)
    boot = bootstrap_diffs(payoff, N_BOOT, seed_offset=1)
    print(f"bootstrap done in {time.time()-t1:.1f}s", file=sys.stderr)

    ci_lower = {}
    for c in CURVES:
        ci_lower[c] = {}
        for name, vals in boot[c].items():
            ci_lower[c][name] = percentile(vals, 0.025)
            ci_lower[c][name + "_upper"] = percentile(vals, 0.975)

    # --- kill condition judgments ---
    def ci_low(c, x, y):
        key = f"{x}_minus_{y}"
        return ci_lower[c][key]

    ka1_terms = []
    for c in CURVES:
        for x in ("S-early", "S-th65", "S-mold"):
            v = ci_low(c, x, "S-wait")
            ka1_terms.append((c, x, v))
    ka1_fires = all(v <= 0 for _, _, v in ka1_terms)

    ka1p_terms = []
    for c in CURVES:
        for x in ("S-wait", "S-th65", "S-mold"):
            v = ci_low(c, x, "S-early")
            ka1p_terms.append((c, x, v))
    ka1p_fires = all(v <= 0 for _, _, v in ka1p_terms)

    median_unresolved = statistics.median(unresolved_counts)
    ka2_fires = median_unresolved < 2

    ka3_terms = []
    for c in CURVES:
        v = ci_low(c, "S-th65", "S-blind")
        ka3_terms.append((c, v))
    ka3_fires = all(v <= 0 for _, v in ka3_terms)

    overall_pass = not (ka1_fires or ka1p_fires or ka2_fires or ka3_fires)

    # reference records (not used for judgment)
    bet_t_dist = {
        strat: {t: bet_t_records[strat].count(t) for t in range(6)}
        for strat in ("S-th65", "S-mold", "S-blind")
    }

    best_gap_by_curve = {}
    for c in CURVES:
        conditional_best = max(point_estimates[c][s] for s in ("S-th65", "S-mold"))
        unconditional_best = max(point_estimates[c][s] for s in ("S-early", "S-wait"))
        best_gap_by_curve[c] = conditional_best - unconditional_best
    best_gap_curve = max(best_gap_by_curve, key=lambda c: best_gap_by_curve[c])

    output = {
        "meta": {
            "seed": SEED,
            "n_deals": N_DEALS,
            "n_boot": N_BOOT,
            "runtime_sec": time.time() - t0,
        },
        "point_estimates": point_estimates,
        "ci95": ci_lower,
        "kill_conditions": {
            "K-A1_wait_dominance": {"fires": ka1_fires, "terms": ka1_terms},
            "K-A1p_info_worthless": {"fires": ka1p_fires, "terms": ka1p_terms},
            "K-A2_ambiguous_band_decorative": {
                "fires": ka2_fires,
                "median_unresolved_t_count": median_unresolved,
            },
            "K-A3_hidden_var_decorative": {"fires": ka3_fires, "terms": ka3_terms},
        },
        "overall_pass": overall_pass,
        "reference_not_for_judgment": {
            "bet_t_distribution": bet_t_dist,
            "conditional_minus_unconditional_best_gap_by_curve": best_gap_by_curve,
            "largest_gap_curve": best_gap_curve,
        },
    }

    with open("sim/mold_timing_probe/results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    header = ["deal_index", "unresolved_self", "unresolved_opp", "own_total", "opp_total"]
    for strat in STRATEGIES:
        header.extend([f"bet_t_{strat}", f"side_{strat}"])
    for cname in CURVES:
        for strat in STRATEGIES:
            header.append(f"payoff_{cname}_{strat}")

    with open("sim/mold_timing_probe/results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(csv_rows)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"TOTAL runtime: {time.time()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
