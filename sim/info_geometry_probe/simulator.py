#!/usr/bin/env python3
"""
情報幾何検証・工程1「買える事実の実在検証」（7土台比較） モンテカルロ検証シミュレータ

指示書: 情報幾何検証・工程1「買える事実の実在検証」（7土台比較） v1
7つの土台(F0/F9/F+/FA/FB/FC1/FC2)について、開示1回あたりのequity変動を
M1(針の動き幅)/M2(形勢逆転率)/M3(めくりどきの読めるさ)で測定する。
賭け・経済・コストは実装しない。equityは各ディールとも厳密な周辺化(組合せ全列挙)で計算し、
モンテカルロはどのディール・どのカードが開示されるかのサンプリングにのみ使う。
"""

import csv
import json
import os
import time
from functools import lru_cache
from itertools import combinations

import numpy as np

# ---------------------------------------------------------------------------
# 凍結パラメータ
# ---------------------------------------------------------------------------

N_DEALS = 50_000
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 20260800
TIEBREAK_SEED = 20260799

FOUNDATION_ORDER = ["F0", "F9", "F+", "FA", "FB", "FC1", "FC2"]
DEAL_SEED = {name: 20260716 + k for k, name in enumerate(FOUNDATION_ORDER)}

OUT_DIR = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# 汎用: 「自分専用の山」からの相手手札の周辺化 (F0 / FA / FB(内部) / FC1 / FC2 で共用)
# ---------------------------------------------------------------------------


def _canon(hand):
    """キャッシュキー用の正規化 (int と 'R' が混在しても安全にソート)"""
    return tuple(sorted(hand, key=lambda c: (1, 0) if c == "R" else (0, c)))


@lru_cache(maxsize=None)
def _combos(remaining_deck, need):
    return list(combinations(remaining_deck, need))


def generate_opp_hands(known_values, deck_values, hand_size):
    """known_values: 相手の手札のうち既知の値のタプル。
    戻り値: [(weight, full_hand_tuple), ...]  weight は同一 deck 内で正規化済み(合計1)。"""
    known = tuple(known_values)
    remaining_deck = tuple(v for v in deck_values if v not in known)
    need = hand_size - len(known)
    if need == 0:
        return [(1.0, known)]
    combos = _combos(remaining_deck, need)
    w = 1.0 / len(combos)
    return [(w, known + c) for c in combos]


def marginal_equity(buyer_hand, known_opp_values, deck_values, hand_size, outcome_fn, ctx=None):
    scenarios = generate_opp_hands(known_opp_values, deck_values, hand_size)
    total_w = 0.0
    win = 0.0
    for w, opp_hand in scenarios:
        total_w += w
        win += w * outcome_fn(buyer_hand, opp_hand, ctx)
    return win / total_w


# ---------------------------------------------------------------------------
# F0: 死亡対照(低)
# ---------------------------------------------------------------------------

F0_DECK = (1, 2, 3, 4, 5, 6)


def f0_outcome(buyer_hand, opp_hand, ctx):
    bs, os_ = sum(buyer_hand), sum(opp_hand)
    if bs > os_:
        return 1.0
    if bs < os_:
        return 0.0
    return 0.5


@lru_cache(maxsize=None)
def f0_eq(buyer_hand, known_opp):
    return marginal_equity(buyer_hand, known_opp, F0_DECK, 3, f0_outcome)


def f0_deal(rng):
    buyer_hand = tuple(rng.sample(F0_DECK, 3))
    opp_hand = tuple(rng.sample(F0_DECK, 3))
    return {"buyer_hand": buyer_hand, "opp_hand": opp_hand}


def f0_process(deal, rng):
    buyer_hand = _canon(deal["buyer_hand"])
    opp_hand = deal["opp_hand"]
    eq_pre = f0_eq(buyer_hand, ())
    revealed = rng.choice(opp_hand)
    eq_post = f0_eq(buyer_hand, (revealed,))
    # pred: 相手手札はbuyerの山と独立な一様抽選なので、開示値vの周辺確率は deck 上で一様
    pred = 0.0
    for v in F0_DECK:
        p_v = 3.0 / len(F0_DECK)  # P(v in opp hand)
        eq_v = f0_eq(buyer_hand, (v,))
        pred += (p_v / 3.0) * abs(eq_v - eq_pre)
    return eq_pre, eq_post, pred


# ---------------------------------------------------------------------------
# F9: 死亡対照(高) ―― コイン
# ---------------------------------------------------------------------------


def f9_deal(rng):
    coin = rng.choice(("WIN", "LOSE"))  # WIN=相手勝ち, LOSE=自分勝ち
    return {"coin": coin}


def f9_process(deal, rng):
    eq_pre = 0.5
    eq_post = 1.0 if deal["coin"] == "LOSE" else 0.0
    pred = None  # 定数(公開情報なし) -> M3は定義によりあとで1.0にする
    return eq_pre, eq_post, pred


# ---------------------------------------------------------------------------
# F+: 生存対照 ―― Leduc型
# ---------------------------------------------------------------------------

RANK_VALUE = {"J": 0, "Q": 1, "K": 2}
FPLUS_DECK = ("J", "J", "Q", "Q", "K", "K")


def fplus_deal(rng):
    deck = list(FPLUS_DECK)
    rng.shuffle(deck)
    buyer_card, opp_card, board = deck[0], deck[1], deck[2]
    return {"buyer_card": buyer_card, "opp_card": opp_card, "board": board}


def fplus_outcome(buyer_card, opp_card, board):
    b_pair = buyer_card == board
    o_pair = opp_card == board
    if b_pair and not o_pair:
        return 1.0
    if o_pair and not b_pair:
        return 0.0
    if RANK_VALUE[buyer_card] > RANK_VALUE[opp_card]:
        return 1.0
    if RANK_VALUE[buyer_card] < RANK_VALUE[opp_card]:
        return 0.0
    return 0.5


@lru_cache(maxsize=None)
def fplus_opp_dist(buyer_card, board):
    remaining = list(FPLUS_DECK)
    remaining.remove(buyer_card)
    remaining.remove(board)
    total = len(remaining)
    counts = {}
    for r in remaining:
        counts[r] = counts.get(r, 0) + 1
    return [(cnt / total, rank) for rank, cnt in counts.items()]


@lru_cache(maxsize=None)
def fplus_eq_pre(buyer_card, board):
    dist = fplus_opp_dist(buyer_card, board)
    return sum(w * fplus_outcome(buyer_card, r, board) for w, r in dist)


def fplus_process(deal, rng):
    buyer_card, opp_card, board = deal["buyer_card"], deal["opp_card"], deal["board"]
    eq_pre = fplus_eq_pre(buyer_card, board)
    # 相手の伏せ札は1枚のみなので、開示は必ずその1枚を明かす
    eq_post = fplus_outcome(buyer_card, opp_card, board)
    dist = fplus_opp_dist(buyer_card, board)
    pred = sum(w * abs(fplus_outcome(buyer_card, r, board) - eq_pre) for w, r in dist)
    return eq_pre, eq_post, pred


# ---------------------------------------------------------------------------
# FA: 候補・反転札
# ---------------------------------------------------------------------------

FA_DECK = (1, 2, 3, 4, 5, 6, "R")


def _fa_value(c):
    return 0 if c == "R" else c


def fa_outcome(buyer_hand, opp_hand, ctx):
    bs = sum(_fa_value(c) for c in buyer_hand)
    os_ = sum(_fa_value(c) for c in opp_hand)
    r_count = buyer_hand.count("R") + opp_hand.count("R")
    if r_count % 2 == 1:
        if bs < os_:
            return 1.0
        if bs > os_:
            return 0.0
        return 0.5
    else:
        if bs > os_:
            return 1.0
        if bs < os_:
            return 0.0
        return 0.5


@lru_cache(maxsize=None)
def fa_eq(buyer_hand, known_opp):
    return marginal_equity(buyer_hand, known_opp, FA_DECK, 3, fa_outcome)


def fa_deal(rng):
    buyer_hand = tuple(rng.sample(FA_DECK, 3))
    opp_hand = tuple(rng.sample(FA_DECK, 3))
    return {"buyer_hand": buyer_hand, "opp_hand": opp_hand}


def fa_process(deal, rng):
    buyer_hand = _canon(deal["buyer_hand"])
    opp_hand = deal["opp_hand"]
    eq_pre = fa_eq(buyer_hand, ())
    revealed = rng.choice(opp_hand)
    eq_post = fa_eq(buyer_hand, (revealed,))
    pred = 0.0
    for v in FA_DECK:
        p_v = 3.0 / len(FA_DECK)
        eq_v = fa_eq(buyer_hand, (v,))
        pred += (p_v / 3.0) * abs(eq_v - eq_pre)
    return eq_pre, eq_post, pred


# ---------------------------------------------------------------------------
# FB: 候補・二山
# ---------------------------------------------------------------------------

FB_H_DECK = (4, 5, 6, 7, 8, 9)
FB_L_DECK = (1, 2, 3, 4, 5, 6)
FB_DECKS = {"H": FB_H_DECK, "L": FB_L_DECK}
FB_ALL_VALUES = tuple(sorted(set(FB_H_DECK) | set(FB_L_DECK)))


def fb_outcome(buyer_hand, opp_hand, ctx):
    bs, os_ = sum(buyer_hand), sum(opp_hand)
    if bs > os_:
        return 1.0
    if bs < os_:
        return 0.0
    return 0.5


@lru_cache(maxsize=None)
def fb_opp_scenarios(known_value):
    """known_value: None(開示前) または既知の1枚。戻り値: [(weight, opp_hand), ...] (未正規化、合計で正規化して使う)"""
    scenarios = []
    for deck_name, deck_values in FB_DECKS.items():
        if known_value is not None and known_value not in deck_values:
            continue
        known = (known_value,) if known_value is not None else ()
        for w, hand in generate_opp_hands(known, deck_values, 3):
            scenarios.append((0.5 * w, hand))
    return scenarios


@lru_cache(maxsize=None)
def fb_eq(buyer_hand, known_value):
    scenarios = fb_opp_scenarios(known_value)
    total_w = sum(w for w, _ in scenarios)
    win = sum(w * fb_outcome(buyer_hand, h, None) for w, h in scenarios)
    return win / total_w


@lru_cache(maxsize=None)
def fb_prior_value_prob(v):
    """P(v が相手の手札に含まれる | 公開情報なし)"""
    p = 0.0
    for deck_values in FB_DECKS.values():
        if v in deck_values:
            p += 0.5 * (3.0 / 6.0)
    return p


def fb_deal(rng):
    buyer_deck_name = rng.choice(("H", "L"))
    opp_deck_name = rng.choice(("H", "L"))
    buyer_hand = tuple(rng.sample(FB_DECKS[buyer_deck_name], 3))
    opp_hand = tuple(rng.sample(FB_DECKS[opp_deck_name], 3))
    return {"buyer_hand": buyer_hand, "opp_hand": opp_hand, "opp_deck": opp_deck_name}


def fb_process(deal, rng):
    buyer_hand = _canon(deal["buyer_hand"])
    opp_hand = deal["opp_hand"]
    eq_pre = fb_eq(buyer_hand, None)
    revealed = rng.choice(opp_hand)
    eq_post = fb_eq(buyer_hand, revealed)
    pred = 0.0
    for v in FB_ALL_VALUES:
        p_v = fb_prior_value_prob(v)
        if p_v <= 0:
            continue
        eq_v = fb_eq(buyer_hand, v)
        pred += (p_v / 3.0) * abs(eq_v - eq_pre)
    return eq_pre, eq_post, pred


# ---------------------------------------------------------------------------
# FC1 / FC2: 候補・役型
# ---------------------------------------------------------------------------

FC_DECK = (1, 2, 3, 4, 5, 6)
FC_BOARD_DECK = (1, 2, 3, 4, 5, 6)


def fc_multiplier(hand, board_ranks):
    mult = 1
    for b in board_ranks:
        if b in hand:
            mult *= 2
    return mult


def fc1_outcome(buyer_hand, opp_hand, board_ranks):
    bscore = sum(buyer_hand) * fc_multiplier(buyer_hand, board_ranks)
    oscore = sum(opp_hand) * fc_multiplier(opp_hand, board_ranks)
    if bscore > oscore:
        return 1.0
    if bscore < oscore:
        return 0.0
    return 0.5


def fc2_outcome(buyer_hand, opp_hand, board_ranks):
    b_match = any(b in buyer_hand for b in board_ranks)
    o_match = any(b in opp_hand for b in board_ranks)
    if b_match and not o_match:
        return 1.0
    if o_match and not b_match:
        return 0.0
    bs, os_ = sum(buyer_hand), sum(opp_hand)
    if bs > os_:
        return 1.0
    if bs < os_:
        return 0.0
    return 0.5


@lru_cache(maxsize=None)
def fc1_eq(buyer_hand, board_ranks, known_opp):
    def outcome_fn(bh, oh, ctx):
        return fc1_outcome(bh, oh, board_ranks)

    return marginal_equity(buyer_hand, known_opp, FC_DECK, 3, outcome_fn)


@lru_cache(maxsize=None)
def fc2_eq(buyer_hand, board_ranks, known_opp):
    def outcome_fn(bh, oh, ctx):
        return fc2_outcome(bh, oh, board_ranks)

    return marginal_equity(buyer_hand, known_opp, FC_DECK, 3, outcome_fn)


def fc_deal(rng):
    board = tuple(rng.sample(FC_BOARD_DECK, 2))
    buyer_hand = tuple(rng.sample(FC_DECK, 3))
    opp_hand = tuple(rng.sample(FC_DECK, 3))
    return {"buyer_hand": buyer_hand, "opp_hand": opp_hand, "board": board}


def _fc_process(deal, rng, eq_fn):
    buyer_hand = _canon(deal["buyer_hand"])
    board_ranks = tuple(sorted(deal["board"]))
    opp_hand = deal["opp_hand"]
    eq_pre = eq_fn(buyer_hand, board_ranks, ())
    revealed = rng.choice(opp_hand)
    eq_post = eq_fn(buyer_hand, board_ranks, (revealed,))
    pred = 0.0
    for v in FC_DECK:
        p_v = 3.0 / len(FC_DECK)
        eq_v = eq_fn(buyer_hand, board_ranks, (v,))
        pred += (p_v / 3.0) * abs(eq_v - eq_pre)
    return eq_pre, eq_post, pred


def fc1_process(deal, rng):
    return _fc_process(deal, rng, fc1_eq)


def fc2_process(deal, rng):
    return _fc_process(deal, rng, fc2_eq)


# ---------------------------------------------------------------------------
# 土台テーブル
# ---------------------------------------------------------------------------

FOUNDATIONS = {
    "F0": (f0_deal, f0_process),
    "F9": (f9_deal, f9_process),
    "F+": (fplus_deal, fplus_process),
    "FA": (fa_deal, fa_process),
    "FB": (fb_deal, fb_process),
    "FC1": (fc_deal, fc1_process),
    "FC2": (fc_deal, fc2_process),
}

# ---------------------------------------------------------------------------
# MC 実行
# ---------------------------------------------------------------------------


class SeededRandomChoice:
    """random.Random 互換の rng.choice(iterable) を、numpy Generator ベースで提供する薄いラッパ。
    土台の乱数はすべてこの1本(numpy Generator)から派生させ、シードで完全再現できるようにする。"""

    def __init__(self, seed):
        self._rng = np.random.default_rng(seed)

    def sample(self, population, k):
        population = list(population)
        idx = self._rng.choice(len(population), size=k, replace=False)
        return [population[i] for i in idx]

    def choice(self, population):
        population = list(population)
        idx = self._rng.integers(0, len(population))
        return population[idx]

    def shuffle(self, x):
        self._rng.shuffle(x)


def run_foundation(name, n=N_DEALS):
    deal_fn, process_fn = FOUNDATIONS[name]
    seed = DEAL_SEED[name]
    rng = SeededRandomChoice(seed)

    eq_pre_arr = np.empty(n, dtype=np.float64)
    abs_delta_arr = np.empty(n, dtype=np.float64)
    pred_arr = np.empty(n, dtype=np.float64)
    reversal_arr = np.empty(n, dtype=bool)
    pred_is_none = False

    for i in range(n):
        deal = deal_fn(rng)
        eq_pre, eq_post, pred = process_fn(deal, rng)
        delta = eq_post - eq_pre
        eq_pre_arr[i] = eq_pre
        abs_delta_arr[i] = abs(delta)
        if pred is None:
            pred_is_none = True
            pred_arr[i] = np.nan
        else:
            pred_arr[i] = pred
        if eq_pre == 0.5:
            reversal_arr[i] = eq_post != 0.5
        else:
            reversal_arr[i] = (eq_pre - 0.5) * (eq_post - 0.5) < 0

    return {
        "name": name,
        "eq_pre": eq_pre_arr,
        "abs_delta": abs_delta_arr,
        "pred": pred_arr,
        "pred_is_none": pred_is_none,
        "reversal": reversal_arr,
    }


# ---------------------------------------------------------------------------
# 指標計算
# ---------------------------------------------------------------------------


def compute_m3(abs_delta, pred, pred_is_none, tiebreak):
    n = len(abs_delta)
    if pred_is_none or np.allclose(pred, pred[0]):
        return 1.0, True  # 定義により1.0 (定数predまたは公開情報なし)
    order = np.lexsort((tiebreak, pred))  # pred 昇順、同値は tiebreak 昇順
    sorted_abs = abs_delta[order]
    q = n // 4
    bottom = sorted_abs[:q]
    top = sorted_abs[3 * q:]
    denom = bottom.mean()
    if denom == 0.0:
        return 1.0, True
    return top.mean() / denom, False


def compute_stats(result, tiebreak):
    abs_delta = result["abs_delta"]
    eq_pre = result["eq_pre"]
    reversal = result["reversal"]
    pred = result["pred"]
    m1_median = float(np.median(abs_delta))
    m1_mean = float(np.mean(abs_delta))
    m2 = float(np.mean(reversal))
    m3, m3_degenerate = compute_m3(abs_delta, pred, result["pred_is_none"], tiebreak)
    eq_pre_mean = float(np.mean(eq_pre))
    return {
        "m1_median": m1_median,
        "m1_mean": m1_mean,
        "m2": m2,
        "m3": m3,
        "m3_degenerate": m3_degenerate,
        "eq_pre_mean": eq_pre_mean,
    }


def bootstrap_ci(result, tiebreak, n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    n = len(result["abs_delta"])
    abs_delta = result["abs_delta"]
    reversal = result["reversal"].astype(np.float64)
    pred = result["pred"]
    pred_is_none = result["pred_is_none"]
    pred_const = (not pred_is_none) and np.allclose(pred, pred[0])

    rng = np.random.default_rng(seed)
    m1_med_samples = np.empty(n_boot)
    m1_mean_samples = np.empty(n_boot)
    m2_samples = np.empty(n_boot)
    m3_samples = np.empty(n_boot)

    q = n // 4
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        ad = abs_delta[idx]
        m1_med_samples[b] = np.median(ad)
        m1_mean_samples[b] = np.mean(ad)
        m2_samples[b] = np.mean(reversal[idx])
        if pred_is_none or pred_const:
            m3_samples[b] = 1.0
        else:
            pr = pred[idx]
            tb = tiebreak[idx]
            order = np.lexsort((tb, pr))
            sorted_ad = ad[order]
            bottom_mean = sorted_ad[:q].mean()
            top_mean = sorted_ad[3 * q:].mean()
            m3_samples[b] = 1.0 if bottom_mean == 0.0 else top_mean / bottom_mean

    def ci(samples):
        lo, hi = np.percentile(samples, [2.5, 97.5])
        return float(lo), float(hi)

    return {
        "m1_median_ci": ci(m1_med_samples),
        "m1_mean_ci": ci(m1_mean_samples),
        "m2_ci": ci(m2_samples),
        "m3_ci": ci(m3_samples),
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main():
    t0 = time.time()
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    all_stats = {}
    all_ci = {}
    all_results = {}

    for name in FOUNDATION_ORDER:
        t_start = time.time()
        result = run_foundation(name, N_DEALS)
        all_results[name] = result
        tiebreak_rng = np.random.default_rng(TIEBREAK_SEED)
        tiebreak = tiebreak_rng.random(N_DEALS)
        stats = compute_stats(result, tiebreak)
        ci = bootstrap_ci(result, tiebreak)
        all_stats[name] = stats
        all_ci[name] = ci
        elapsed = time.time() - t_start
        log(f"[{name}] done in {elapsed:.1f}s  "
            f"M1_med={stats['m1_median']:.4f} M1_mean={stats['m1_mean']:.4f} "
            f"M2={stats['m2']:.4f} M3={stats['m3']:.4f} eq_pre_mean={stats['eq_pre_mean']:.4f}")

    total_elapsed = time.time() - t0
    log(f"TOTAL elapsed: {total_elapsed:.1f}s")

    # --- results.csv ---
    csv_path = os.path.join(OUT_DIR, "results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "foundation", "n", "seed",
            "m1_median", "m1_median_ci_lo", "m1_median_ci_hi",
            "m1_mean", "m1_mean_ci_lo", "m1_mean_ci_hi",
            "m2", "m2_ci_lo", "m2_ci_hi",
            "m3", "m3_degenerate", "m3_ci_lo", "m3_ci_hi",
            "eq_pre_mean",
        ])
        for name in FOUNDATION_ORDER:
            s = all_stats[name]
            c = all_ci[name]
            w.writerow([
                name, N_DEALS, DEAL_SEED[name],
                s["m1_median"], c["m1_median_ci"][0], c["m1_median_ci"][1],
                s["m1_mean"], c["m1_mean_ci"][0], c["m1_mean_ci"][1],
                s["m2"], c["m2_ci"][0], c["m2_ci"][1],
                s["m3"], s["m3_degenerate"], c["m3_ci"][0], c["m3_ci"][1],
                s["eq_pre_mean"],
            ])
    log(f"wrote {csv_path}")

    # --- run_meta / raw stats dump (results.md 生成用) ---
    meta = {
        "n_deals": N_DEALS,
        "bootstrap_n": BOOTSTRAP_N,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "tiebreak_seed": TIEBREAK_SEED,
        "deal_seeds": DEAL_SEED,
        "elapsed_sec": total_elapsed,
        "stats": all_stats,
        "ci": all_ci,
    }
    with open(os.path.join(OUT_DIR, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log(f"wrote run_meta.json")

    with open(os.path.join(OUT_DIR, "run_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")

    return all_stats, all_ci, all_results


if __name__ == "__main__":
    main()
