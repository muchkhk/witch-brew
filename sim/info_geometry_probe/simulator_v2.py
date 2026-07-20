#!/usr/bin/env python3
"""
情報幾何検証・工程1 修正版「見立ての改善量による再判定」v2

指示書: 情報幾何検証・工程1 修正版「見立ての改善量による再判定」v2
v1(simulator.py)と同一のディール(同一シード・同一 deal/process 関数)を再現し、
配り直しは一切行わない。M2(形勢逆転率)を廃止し、新指標 M2'(見立ての改善量)を
主指標として手順0検品とKill/Pass判定をやり直す。M3はv1の値を無変更で再掲する。

v1の成果物(simulator.py / results.md / results.csv / run_meta.json / run_log.txt)は
一切変更しない。
"""

import csv
import json
import os
import time

import numpy as np

import simulator as v1  # v1のdeal/process関数・シード・乱数ラッパをそのまま再利用(配り直し禁止)

N_DEALS = v1.N_DEALS
BOOTSTRAP_N = v1.BOOTSTRAP_N
BOOTSTRAP_SEED = v1.BOOTSTRAP_SEED
FOUNDATION_ORDER = v1.FOUNDATION_ORDER
DEAL_SEED = v1.DEAL_SEED

OUT_DIR = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# 1. v1と同一のディール列を再現し、eq_pre / eq_post(符号付き) / pred を保持する
# ---------------------------------------------------------------------------


def reproduce_foundation(name, n=N_DEALS):
    deal_fn, process_fn = v1.FOUNDATIONS[name]
    seed = DEAL_SEED[name]
    rng = v1.SeededRandomChoice(seed)  # v1と全く同じ乱数ラッパ・同じシード

    eq_pre_arr = np.empty(n, dtype=np.float64)
    eq_post_arr = np.empty(n, dtype=np.float64)

    for i in range(n):
        deal = deal_fn(rng)
        eq_pre, eq_post, pred = process_fn(deal, rng)  # v1と同一の呼び出し順序
        eq_pre_arr[i] = eq_pre
        eq_post_arr[i] = eq_post

    return eq_pre_arr, eq_post_arr


def reproduced_m1_m2(eq_pre, eq_post):
    """v1のM1(中央値・平均)・M2(旧: 形勢逆転率)を再現データから再計算する(検算用)。"""
    abs_delta = np.abs(eq_post - eq_pre)
    reversal = np.empty(len(eq_pre), dtype=bool)
    eq_pre_is_half = eq_pre == 0.5
    reversal[eq_pre_is_half] = eq_post[eq_pre_is_half] != 0.5
    other = ~eq_pre_is_half
    reversal[other] = (eq_pre[other] - 0.5) * (eq_post[other] - 0.5) < 0
    return {
        "m1_median": float(np.median(abs_delta)),
        "m1_mean": float(np.mean(abs_delta)),
        "m2_old": float(np.mean(reversal)),
    }


# ---------------------------------------------------------------------------
# 2. 新指標 M2'(見立ての改善量) ―― §3の凍結定義通り
# ---------------------------------------------------------------------------


def compute_g(eq_pre, eq_post):
    a_pre = np.where(eq_pre > 0.5, eq_post,
                      np.where(eq_pre < 0.5, 1.0 - eq_post, 0.5))
    a_post = np.maximum(eq_post, 1.0 - eq_post)
    g = a_post - a_pre
    return g


def flip_mask_old_definition(eq_pre, eq_post):
    """v1のM2(形勢逆転)と同一の定義で「反転」を分類する(報告項目3: 回数と深さの内訳用)。"""
    mask = np.empty(len(eq_pre), dtype=bool)
    eq_pre_is_half = eq_pre == 0.5
    mask[eq_pre_is_half] = eq_post[eq_pre_is_half] != 0.5
    other = ~eq_pre_is_half
    mask[other] = (eq_pre[other] - 0.5) * (eq_post[other] - 0.5) < 0
    return mask


# ---------------------------------------------------------------------------
# 3. ブートストラップCI (M2'のみ。M3はv1の値を無変更で再掲するため再計算しない)
# ---------------------------------------------------------------------------


def bootstrap_m2prime_ci(g, n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    n = len(g)
    rng = np.random.default_rng(seed)  # v1と同様、土台ごとに独立再シード
    samples = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        samples[b] = g[idx].mean()
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return float(lo), float(hi)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def load_v1_csv():
    path = os.path.join(OUT_DIR, "results.csv")
    rows = {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows[row["foundation"]] = row
    return rows


def main():
    t0 = time.time()
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    v1_csv = load_v1_csv()

    all_data = {}
    mismatch_found = False

    for name in FOUNDATION_ORDER:
        t_start = time.time()
        eq_pre, eq_post = reproduce_foundation(name, N_DEALS)
        recomputed = reproduced_m1_m2(eq_pre, eq_post)

        v1_row = v1_csv[name]
        tol = 1e-9
        checks = {
            "m1_median": (recomputed["m1_median"], float(v1_row["m1_median"])),
            "m1_mean": (recomputed["m1_mean"], float(v1_row["m1_mean"])),
            "m2_old": (recomputed["m2_old"], float(v1_row["m2"])),
        }
        for key, (got, expect) in checks.items():
            if abs(got - expect) > tol:
                mismatch_found = True
                log(f"[{name}] MISMATCH {key}: reproduced={got} v1={expect}")

        g = compute_g(eq_pre, eq_post)
        if np.any(g < -1e-12):
            log(f"[{name}] WARNING: negative G detected! min(G)={g.min()}")
        m2prime = float(g.mean())
        m2prime_ci = bootstrap_m2prime_ci(g)

        flip = flip_mask_old_definition(eq_pre, eq_post)
        flip_rate = float(np.mean(flip))
        avg_g_given_flip = float(g[flip].mean()) if flip.any() else 0.0
        # 非反転ディールのGが厳密に0であることの検算 (許容誤差1e-9)
        nonflip_g_max = float(np.abs(g[~flip]).max()) if (~flip).any() else 0.0

        all_data[name] = {
            "eq_pre": eq_pre,
            "eq_post": eq_post,
            "g": g,
            "m1_median": recomputed["m1_median"],
            "m1_mean": recomputed["m1_mean"],
            "m2_old": recomputed["m2_old"],
            "m2prime": m2prime,
            "m2prime_ci": m2prime_ci,
            "flip_rate": flip_rate,
            "avg_g_given_flip": avg_g_given_flip,
            "nonflip_g_max": nonflip_g_max,
            "m3": float(v1_row["m3"]),
            "m3_ci": (float(v1_row["m3_ci_lo"]), float(v1_row["m3_ci_hi"])),
            "m3_degenerate": v1_row["m3_degenerate"] == "True",
        }
        elapsed = time.time() - t_start
        log(f"[{name}] done in {elapsed:.1f}s  M2'={m2prime:.4f} CI={m2prime_ci}  "
            f"flip_rate={flip_rate:.4f} avg_G|flip={avg_g_given_flip:.4f}  "
            f"check_product={flip_rate*avg_g_given_flip:.6f} (vs M2'={m2prime:.6f})")

    total_elapsed = time.time() - t0
    log(f"TOTAL elapsed: {total_elapsed:.1f}s  mismatch_found={mismatch_found}")

    # --- 自己検査v2 ---
    f9 = all_data["F9"]
    f9_g_exact = bool(np.allclose(f9["g"], 0.5, atol=1e-9))
    all_g_nonneg = all(bool(np.all(d["g"] >= -1e-12)) for d in all_data.values())
    reproduction_matches_v1 = not mismatch_found

    log(f"self-check F9 G==0.5 exact: {f9_g_exact}")
    log(f"self-check all G >= 0: {all_g_nonneg}")
    log(f"self-check reproduction matches v1: {reproduction_matches_v1}")

    # --- results_v2.csv ---
    csv_path = os.path.join(OUT_DIR, "results_v2.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "foundation", "n", "seed",
            "m2prime", "m2prime_ci_lo", "m2prime_ci_hi",
            "flip_rate", "avg_g_given_flip", "check_product_vs_m2prime_diff",
            "m1_median_ref", "m1_mean_ref", "m2_old_ref",
            "m3_unchanged", "m3_ci_lo_unchanged", "m3_ci_hi_unchanged", "m3_degenerate",
        ])
        for name in FOUNDATION_ORDER:
            d = all_data[name]
            diff = d["flip_rate"] * d["avg_g_given_flip"] - d["m2prime"]
            w.writerow([
                name, N_DEALS, DEAL_SEED[name],
                d["m2prime"], d["m2prime_ci"][0], d["m2prime_ci"][1],
                d["flip_rate"], d["avg_g_given_flip"], diff,
                d["m1_median"], d["m1_mean"], d["m2_old"],
                d["m3"], d["m3_ci"][0], d["m3_ci"][1], d["m3_degenerate"],
            ])
    log(f"wrote {csv_path}")

    with open(os.path.join(OUT_DIR, "run_log_v2.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")

    meta = {
        "n_deals": N_DEALS,
        "bootstrap_n": BOOTSTRAP_N,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "deal_seeds": DEAL_SEED,
        "elapsed_sec": total_elapsed,
        "self_checks": {
            "f9_g_exact_0_5": f9_g_exact,
            "all_g_nonnegative": all_g_nonneg,
            "reproduction_matches_v1": reproduction_matches_v1,
        },
        "results": {
            name: {k: v for k, v in d.items() if k not in ("eq_pre", "eq_post", "g")}
            for name, d in all_data.items()
        },
    }
    with open(os.path.join(OUT_DIR, "run_meta_v2.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log("wrote run_meta_v2.json")

    return all_data, {
        "f9_g_exact": f9_g_exact,
        "all_g_nonneg": all_g_nonneg,
        "reproduction_matches_v1": reproduction_matches_v1,
    }


if __name__ == "__main__":
    main()
