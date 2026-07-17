"""
手順5-7: 事前登録_シュレディンガー工程3prime_kill基準.md §5〜§7 に従った
フルスケール実行ドライバ。simulator_process3prime.py の play_single_game
（B規則）・play_game_a_rule（K-F0(a)用）・統計関数を用いる。

実行セル（§5-7・凍結指示書手順5）:
  - 主判定 c=0.5: {S1,S2,S2f,S3,S3f,S4} x {B1,B2,B3,B4} (24)
  - K-F4用 F0-D条件: 同6x4 (24)
  - 観察セル: {S1,S2,S4} x {B1,B4} x c in {0,0.25,1.0}
    (S2,S4は価格非依存なのでc=0.5の生データを再利用。S1のみ価格ごとに再実行)
  - K-F0(a): simulator_process3prime.play_game_a_rule 参照（別スクリプトで実施済み）
"""

import json
import statistics
import sys
import time

import simulator_process3prime as s3p

N = s3p.N
MAIN_PRICE = 0.5
OBS_PRICES = [0, 0.25, 1.0]


def simulate_matchup(name_p, name_b, is_f0d=False, n=None, price=MAIN_PRICE):
    n = n or N
    data = {k: [0.0] * n for k in
            ("g1_bs_p", "g1_pc_p", "g1_bs_b", "g1_pc_b",
             "g2_bs_p", "g2_pc_p", "g2_bs_b", "g2_pc_b",
             "unfired_p", "unfired_b")}
    for i in range(n):
        perm, f0d = s3p.gen_game_dice(i)
        tv = f0d if is_f0d else perm
        rng0 = s3p.move_rng_for(i, 0)
        g1 = s3p.play_single_game(name_p, name_b, tv, True, rng0, price=price)
        rng1 = s3p.move_rng_for(i, 1)
        g2 = s3p.play_single_game(name_p, name_b, tv, False, rng1, price=price)
        data["g1_bs_p"][i] = g1["score_a"]; data["g1_pc_p"][i] = g1["peek_count_a"]
        data["g1_bs_b"][i] = g1["score_b"]; data["g1_pc_b"][i] = g1["peek_count_b"]
        data["g2_bs_p"][i] = g2["score_b"]; data["g2_pc_p"][i] = g2["peek_count_b"]
        data["g2_bs_b"][i] = g2["score_a"]; data["g2_pc_b"][i] = g2["peek_count_a"]
        data["unfired_p"][i] = (g1["unfired_a"] + g2["unfired_b"]) / 2.0
        data["unfired_b"][i] = (g1["unfired_b"] + g2["unfired_a"]) / 2.0
    return data


def win_array(data, n=None):
    """price=MAIN_PRICEで既に得点計算済みのdataから勝敗指標配列を作る
    （生スコアはplay_single_game内でprice適用済みのため、価格別再計算はしない。
    観察セルは別価格で個別にsimulate_matchupし直す）。"""
    n = n or len(data["g1_bs_p"])
    out = [0.0] * n
    for i in range(n):
        s_p1, s_b1 = data["g1_bs_p"][i], data["g1_bs_b"][i]
        w1 = 1.0 if s_p1 > s_b1 else (0.5 if s_p1 == s_b1 else 0.0)
        s_p2, s_b2 = data["g2_bs_p"][i], data["g2_bs_b"][i]
        w2 = 1.0 if s_p2 > s_b2 else (0.5 if s_p2 == s_b2 else 0.0)
        out[i] = (w1 + w2) / 2.0
    return out


def pick_bstar(p_name, matchup_data_at_price):
    """B* = Pの対B勝率点推定を最小にするblind（タイブレーク：番号の小さいB）。"""
    best = None
    for idx, b in enumerate(s3p.BLIND_VARIANTS):
        arr = win_array(matchup_data_at_price[(p_name, b)])
        point = statistics.mean(arr)
        key = (point, idx)
        if best is None or key < best[0]:
            best = (key, b, point, arr)
    return best[1], best[2], best[3]


def argmax_by_point(names, point_of, var_of, roster_order):
    def key(nm):
        return (-point_of[nm], var_of[nm], roster_order.index(nm))
    return sorted(names, key=key)[0]


def conservative_paired_diff(name_x, bx, name_y, by, matchup_data, seed_offset):
    candidates = {bx, by}
    results = []
    for b_align in candidates:
        arr_x = win_array(matchup_data[(name_x, b_align)])
        arr_y = win_array(matchup_data[(name_y, b_align)])
        lo, hi = s3p.bootstrap_ci_paired_diff(
            arr_x, arr_y, seed=s3p.SEED_BASE + seed_offset + s3p.hash_stable(b_align))
        point = statistics.mean(arr_x) - statistics.mean(arr_y)
        results.append({"b_align": b_align, "lo": lo, "hi": hi, "point": point})
    chosen = min(results, key=lambda r: r["lo"])
    return chosen, results


def main():
    t0 = time.time()
    matchup_data = {}  # (name, blind) -> raw data @ price=0.5, D3
    f0d_data = {}       # (name, blind) -> raw data @ price=0.5, F0-D

    print("=== D3条件・c=0.5: 6 tested x 4 blind = 24 ===", file=sys.stderr, flush=True)
    for p in s3p.TESTED_STRATS:
        for b in s3p.BLIND_VARIANTS:
            matchup_data[(p, b)] = simulate_matchup(p, b, is_f0d=False, price=MAIN_PRICE)
            print(f"  done D3 {p} vs {b} @ {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    print("=== F0-D条件・c=0.5: 6 x 4 = 24 (K-F4用) ===", file=sys.stderr, flush=True)
    for p in s3p.TESTED_STRATS:
        for b in s3p.BLIND_VARIANTS:
            f0d_data[(p, b)] = simulate_matchup(p, b, is_f0d=True, price=MAIN_PRICE)
            print(f"  done F0D {p} vs {b} @ {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    print("=== 観察セル: S1 x {B1,B4} x c in {0,0.25,1.0} (S1は価格依存のため再実行) ===",
          file=sys.stderr, flush=True)
    s1_obs_data = {}
    for b in ("B1", "B4"):
        for pr in OBS_PRICES:
            s1_obs_data[(b, pr)] = simulate_matchup("S1", b, is_f0d=False, price=pr)
            print(f"  done S1 vs {b} @price={pr} @ {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    print(f"raw sims done in {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    # --- B* selection & point estimates (D3, c=0.5) ---
    b_star = {}
    point_at_bstar = {}
    arr_at_bstar = {}
    var_at_bstar = {}
    for p in s3p.TESTED_STRATS:
        b, point, arr = pick_bstar(p, matchup_data)
        b_star[p] = b
        point_at_bstar[p] = point
        arr_at_bstar[p] = arr
        var_at_bstar[p] = statistics.pvariance(arr) if len(arr) > 1 else 0.0

    # --- B* selection for F0-D condition independently (K-F4 exc_F0D) ---
    b_star_f0d = {}
    point_at_bstar_f0d = {}
    for p in s3p.TESTED_STRATS:
        best = None
        for idx, b in enumerate(s3p.BLIND_VARIANTS):
            arr = win_array(f0d_data[(p, b)])
            point = statistics.mean(arr)
            key = (point, idx)
            if best is None or key < best[0]:
                best = (key, b, point)
        b_star_f0d[p] = best[1]
        point_at_bstar_f0d[p] = best[2]

    # --- K-F1 (主判定): P in {S2,S2f,S3,S3f,S4} vs S1, 対応ペア差(勝敗指標) ---
    t1 = time.time()
    print("=== K-F1 ===", file=sys.stderr, flush=True)
    kf1_terms = {}
    kf1_fires_each = []
    for p in ("S2", "S2f", "S3", "S3f", "S4"):
        chosen, alts = conservative_paired_diff(p, b_star[p], "S1", b_star["S1"],
                                                 matchup_data, seed_offset=910000 + s3p.hash_stable(p))
        kf1_terms[p] = {"b_star_p": b_star[p], "b_star_s1": b_star["S1"],
                         "chosen": chosen, "alternatives": alts}
        kf1_fires_each.append(chosen["lo"] <= 0)
    kf1_fires = all(kf1_fires_each)
    print(f"K-F1 done in {time.time()-t1:.1f}s", file=sys.stderr, flush=True)

    # --- K-F2 (副判定): Z*m=argmax{S2,S3}, Z*f=argmax{S2f,S3f} ---
    t2 = time.time()
    print("=== K-F2 ===", file=sys.stderr, flush=True)
    z_star_m = argmax_by_point(["S2", "S3"], point_at_bstar, var_at_bstar, s3p.TESTED_STRATS)
    z_star_f = argmax_by_point(["S2f", "S3f"], point_at_bstar, var_at_bstar, s3p.TESTED_STRATS)
    kf2_chosen, kf2_alts = conservative_paired_diff(
        z_star_m, b_star[z_star_m], z_star_f, b_star[z_star_f], matchup_data, seed_offset=920000)
    kf2_fires = kf2_chosen["lo"] <= 0
    print(f"K-F2 done in {time.time()-t2:.1f}s", file=sys.stderr, flush=True)

    # --- K-F3 (保険): 全6戦略 vs own B*, Wilson CI95下限 <=0.5 が全部で発動 ---
    print("=== K-F3 ===", file=sys.stderr, flush=True)
    kf3_terms = {}
    for p in s3p.TESTED_STRATS:
        lo, hi = s3p.wilson_ci95(point_at_bstar[p], N)
        kf3_terms[p] = {"b_star": b_star[p], "point": point_at_bstar[p],
                         "ci_lower": lo, "ci_upper": hi}
    kf3_fires = all(t["ci_lower"] <= 0.5 for t in kf3_terms.values())

    # --- K-F4 (演繹寄与死): P*=argmax(D3,c=0.5,全6), exc_D3(P*)-exc_F0D(P*) ---
    t4 = time.time()
    print("=== K-F4 ===", file=sys.stderr, flush=True)
    p_star = argmax_by_point(s3p.TESTED_STRATS, point_at_bstar, var_at_bstar, s3p.TESTED_STRATS)
    arr_d3 = arr_at_bstar[p_star]
    arr_f0d = win_array(f0d_data[(p_star, b_star_f0d[p_star])])
    exc_d3 = statistics.mean(arr_d3) - 0.5
    exc_f0d = statistics.mean(arr_f0d) - 0.5
    lo_kf4, hi_kf4 = s3p.bootstrap_ci_paired_diff(
        [w - 0.5 for w in arr_d3], [w - 0.5 for w in arr_f0d], seed=s3p.SEED_BASE + 930000)
    kf4_fires = lo_kf4 <= 0
    print(f"K-F4 done in {time.time()-t4:.1f}s", file=sys.stderr, flush=True)

    # --- K-F0 (検品) ---
    print("=== K-F0(a) 結果は別途 test 実施済み・(b)(c)(d) をここで判定 ===", file=sys.stderr, flush=True)
    # (b) 不発の実在: S2 vs B4 の不発率が0なら発動
    s2_vs_b4 = matchup_data[("S2", "B4")]
    s2_unfired_rate = (sum(s2_vs_b4["unfired_p"]) * 2) / \
        (sum(matchup_data[("S2", "B4")]["g1_pc_p"]) + sum(matchup_data[("S2", "B4")]["g2_pc_p"]))
    kf0b_fires = (s2_unfired_rate == 0.0)

    # (c) 安全の実在: S1の不発率が全セルで厳密に0でなければ発動
    kf0c_fires = False
    s1_unfired_detail = {}
    for b in s3p.BLIND_VARIANTS:
        d = matchup_data[("S1", b)]
        total_peeks = sum(d["g1_pc_p"]) + sum(d["g2_pc_p"])
        total_unfired = sum(d["unfired_p"]) * 2
        rate = 0.0 if total_peeks == 0 else total_unfired / total_peeks
        s1_unfired_detail[b] = rate
        if rate != 0.0:
            kf0c_fires = True

    # (d) 交換可能性の実装検証: B3 vs 任意のB の生スコア列が B1 vs 同B と完全一致
    kf0d_fires = False
    kf0d_mismatches = 0
    for other_p in s3p.TESTED_STRATS:
        d_b1 = matchup_data[(other_p, "B1")]
        d_b3 = matchup_data[(other_p, "B3")]
        if d_b1["g1_bs_b"] != d_b3["g1_bs_b"] or d_b1["g2_bs_b"] != d_b3["g2_bs_b"]:
            kf0d_fires = True
            kf0d_mismatches += 1

    # (e) 【v0.3】B5の妨害圧力の実在: いずれかのPでasked_order乖離が1件でもあれば非発動
    kf0e_fires = True
    kf0e_diff_counts = {}
    for other_p in s3p.TESTED_STRATS:
        d_b1 = matchup_data[(other_p, "B1")]
        d_b5 = matchup_data[(other_p, "B5")]
        n = len(d_b1["g1_bs_p"])
        diffs = sum(1 for i in range(n)
                    if d_b1["g1_bs_b"][i] != d_b5["g1_bs_b"][i]
                    or d_b1["g2_bs_b"][i] != d_b5["g2_bs_b"][i])
        kf0e_diff_counts[other_p] = diffs
        if diffs > 0:
            kf0e_fires = False

    # B4≡B1の恒等検証（凍結定義の定理としてそのまま記録。§14-9/v0.3改訂記録）
    b4_b1_identity_mismatches = {}
    for other_p in s3p.TESTED_STRATS:
        d_b1 = matchup_data[(other_p, "B1")]
        d_b4 = matchup_data[(other_p, "B4")]
        n = len(d_b1["g1_bs_p"])
        diffs = sum(1 for i in range(n)
                    if d_b1["g1_bs_b"][i] != d_b4["g1_bs_b"][i]
                    or d_b1["g2_bs_b"][i] != d_b4["g2_bs_b"][i])
        b4_b1_identity_mismatches[other_p] = diffs

    kf0_fires = kf0b_fires or kf0c_fires or kf0d_fires or kf0e_fires  # (a)は別途確認済み(overlap=True, fires=false)

    overall_pass = (not kf0_fires) and (not kf1_fires) and (not kf3_fires) and (not kf4_fires)

    # --- 観察: 不発率（全戦略・c=0.5、own B*で） ---
    unfired_rate_ref = {}
    for p in s3p.TESTED_STRATS:
        d = matchup_data[(p, b_star[p])]
        total_peeks = sum(d["g1_pc_p"]) + sum(d["g2_pc_p"])
        total_unfired = sum(d["unfired_p"]) * 2
        unfired_rate_ref[p] = None if total_peeks == 0 else total_unfired / total_peeks

    # --- 観察: 価格グリッド（§4「観察セルは{S1,S2,S4}x{B1,B4}」。B*とは独立に
    # 両方のblindを個別に報告する） ---
    def recompute_win_array_at_price(d, pr):
        n = len(d["g1_bs_p"])
        out = [0.0] * n
        for i in range(n):
            bet_p1 = d["g1_bs_p"][i] + d["g1_pc_p"][i] * MAIN_PRICE
            bet_b1 = d["g1_bs_b"][i] + d["g1_pc_b"][i] * MAIN_PRICE
            s_p1 = bet_p1 - d["g1_pc_p"][i] * pr
            s_b1 = bet_b1 - d["g1_pc_b"][i] * pr
            w1 = 1.0 if s_p1 > s_b1 else (0.5 if s_p1 == s_b1 else 0.0)
            bet_p2 = d["g2_bs_p"][i] + d["g2_pc_p"][i] * MAIN_PRICE
            bet_b2 = d["g2_bs_b"][i] + d["g2_pc_b"][i] * MAIN_PRICE
            s_p2 = bet_p2 - d["g2_pc_p"][i] * pr
            s_b2 = bet_b2 - d["g2_pc_b"][i] * pr
            w2 = 1.0 if s_p2 > s_b2 else (0.5 if s_p2 == s_b2 else 0.0)
            out[i] = (w1 + w2) / 2.0
        return out

    price_grid = {"0.5": {}}
    for p in ["S2", "S4"]:
        for b in ("B1", "B4"):
            price_grid["0.5"][f"{p}_vs_{b}"] = statistics.mean(win_array(matchup_data[(p, b)]))
    price_grid["0.5"]["S1_vs_B1"] = statistics.mean(win_array(matchup_data[("S1", "B1")]))
    price_grid["0.5"]["S1_vs_B4"] = statistics.mean(win_array(matchup_data[("S1", "B4")]))

    for pr in OBS_PRICES:
        price_grid[str(pr)] = {}
        for p in ["S2", "S4"]:
            for b in ("B1", "B4"):
                out = recompute_win_array_at_price(matchup_data[(p, b)], pr)
                price_grid[str(pr)][f"{p}_vs_{b}"] = statistics.mean(out)
        for b in ("B1", "B4"):
            arr_s1 = win_array(s1_obs_data[(b, pr)])
            price_grid[str(pr)][f"S1_vs_{b}"] = statistics.mean(arr_s1)

    output = {
        "meta": {"seed_base": s3p.SEED_BASE, "n": N, "n_boot": s3p.B_BOOT,
                 "runtime_sec": time.time() - t0,
                 "rng_stream4_note": "B5は決定論的仮想モデル(B4と同枠組み)であり乱数を消費しない。"
                                     "系統4(4*seed_base+i)はM-rand(B2)専用のまま新規インデックス"
                                     "割当は発生していない（割当表は空）。"},
        "b_star": b_star,
        "b_star_f0d": b_star_f0d,
        "point_estimates_at_own_bstar_c0.5": point_at_bstar,
        "kill_conditions": {
            "K-F0_instrument_check": {
                "fires": kf0_fires,
                "a_note": "K-F0(a)はtest_kf0a_regression.py実行で確認済み(fires=false, 全項overlap=true)",
                "b_unfired_exists": {"fires": kf0b_fires, "s2_vs_b4_unfired_rate": s2_unfired_rate},
                "c_safe_unfired_zero": {"fires": kf0c_fires, "s1_unfired_by_blind": s1_unfired_detail},
                "d_exchangeability": {"fires": kf0d_fires, "mismatches": kf0d_mismatches},
                "e_b5_pressure_exists": {"fires": kf0e_fires, "diff_game_counts_by_p": kf0e_diff_counts},
                "b4_b1_identity_verification": {
                    "note": "B4はB1と数学的に恒等（凍結定義の定理・v0.3改訂記録参照）。"
                            "mismatch=0がその機械的確認。",
                    "mismatches_by_p": b4_b1_identity_mismatches,
                },
            },
            "K-F1_scout_premium_absent": {"fires": kf1_fires, "terms": kf1_terms},
            "K-F2_recall_steering_decorative": {
                "fires": kf2_fires, "z_star_m": z_star_m, "z_star_f": z_star_f,
                "chosen": kf2_chosen, "alternatives": kf2_alts,
            },
            "K-F3_insurance_market_death": {"fires": kf3_fires, "terms": kf3_terms},
            "K-F4_deduction_contribution_death": {
                "fires": kf4_fires, "p_star": p_star,
                "b_star_d3": b_star[p_star], "b_star_f0d": b_star_f0d[p_star],
                "exc_D3": exc_d3, "exc_F0D": exc_f0d,
                "ci": [lo_kf4, hi_kf4],
                "process2_baseline_0.0334": 0.0334,
                "process3_K_E4_0.1227": 0.1227,
            },
        },
        "overall_pass": overall_pass,
        "reference_not_for_judgment": {
            "unfired_rate_by_strategy_c0.5_at_own_bstar": unfired_rate_ref,
            "price_grid_S2_S4_S1": price_grid,
        },
    }

    with open("results_process3prime.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"=== 完了 {time.time()-t0:.1f}s ===", file=sys.stderr, flush=True)
    return output


if __name__ == "__main__":
    main()
