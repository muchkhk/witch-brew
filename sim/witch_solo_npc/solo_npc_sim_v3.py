#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solo_npc_sim_v3.py — 「witch ソロNPC方策計測 v3（疑似好みバイアス方策族）」

v1/v2（solo_npc_sim.py）を一切変更せず、import して新方策族(疑似好みバイアス)を追加する。
softmaxの揺らぎ(τ)一本でノイズを作る方式（v1/v2）は事前登録どおり全滅・kill済み。
v3は別のノイズ源（非公開の「気まぐれカード」による行動バイアス）を試す。

【方式】各NPCは毎ゲーム開始時、実手札3枚と重複しない気まぐれカードq枚を引く。
効用の自己項 = 実手札の好み点 + w×気まぐれカードの好み点。得点計算(scorePile)には一切関与しない。
切り役の評価にはλ・気まぐれとも関与しない(v1.1裁定を維持。npc_cut_decision/update_belief_for_cutは
v1/v2のものをそのまま再利用する)。

【推定エンジンの変更】手札仮説の尤度は気まぐれの可能性を周辺化する。
q=1(18通り)・q=2(153通り)はいずれも全列挙が可能な規模のため、本実装ではモンテカルロ近似ではなく
「厳密な周辺化」(全気まぐれ候補を尤度計算に使い、平均を取る)を用いた。
理由：指示書は近似を許可しているが必須とはしていない(「よい」であり「モンテカルロで行うこと」ではない)。
全列挙が可能な規模で近似を選ぶ理由がないため、より精度の高い厳密計算を採用した。

実行方法:
    python solo_npc_sim_v3.py --pilot              # 1組・小規模での所要時間実測(必須の事前確認)
    python solo_npc_sim_v3.py --sweep --n-trials 2000
"""
import argparse
import itertools
import json
import sys
import time

import numpy as np

import solo_npc_sim as w1

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MASTER_SEED = w1.MASTER_SEED
WHIM_TAU = 0.3

# ============================================================
# 1. 気まぐれの全列挙と、手札仮説との排他マスク(厳密周辺化の下準備)
# ============================================================

ALL_WHIM_TUPLES = {
    1: list(itertools.combinations(range(18), 1)),
    2: list(itertools.combinations(range(18), 2)),
}
assert len(ALL_WHIM_TUPLES[1]) == 18
assert len(ALL_WHIM_TUPLES[2]) == 153


def _build_valid_mask(q):
    """(816, T_q) の真偽行列。True=そのwhimタプルが手札Hの3枚と重複しない。
    重複しないタプル数はどのHについても必ず C(15,q) 個になる(全18枚からH自身の3枚を除いた
    15枚の中からの組合せ数であり、Hの内容には依らない)。"""
    tuples = ALL_WHIM_TUPLES[q]
    hand_sets = [set(h) for h in w1.ALL_HAND_INDICES]
    mask = np.zeros((w1.N_HANDS, len(tuples)), dtype=bool)
    for hi, hs in enumerate(hand_sets):
        for ti, t in enumerate(tuples):
            mask[hi, ti] = hs.isdisjoint(t)
    return mask


print("v3: 気まぐれ排他マスクを構築中...", file=sys.stderr)
_t0 = time.time()
WHIM_VALID_MASK = {q: _build_valid_mask(q) for q in (1, 2)}
print(f"  完了 ({time.time()-_t0:.2f}s)", file=sys.stderr)
for q in (1, 2):
    # 検算: 有効タプル数はHに依らず一定 = C(15,q)
    counts = WHIM_VALID_MASK[q].sum(axis=1)
    expected = len(list(itertools.combinations(range(15), q)))
    assert np.all(counts == expected), (q, set(counts.tolist()), expected)


class WhimParams:
    __slots__ = ("q", "w")

    def __init__(self, q, w):
        self.q = q
        self.w = w


def draw_whim(hand, q, rng):
    """実際のゲーム内で1人のNPCが引く気まぐれ(q枚、手札3枚と重複しない)。"""
    pool = [i for i in range(18) if i not in hand]
    idx = rng.choice(len(pool), size=q, replace=False)
    return tuple(sorted(pool[i] for i in idx))


def whim_bias_self_scores(true_hand, whim, piles_counts, w):
    """実際のNPCの意思決定用: 実手札+w*気まぐれ の坩堝ごとの合成スコア(スカラーのリスト)。"""
    out = []
    for pc in piles_counts:
        base = w1.score_pile(true_hand, pc)
        whim_score = sum(w1.score_recipe(w1.POOL[c], pc) for c in whim)
        out.append(base + w * whim_score)
    return np.array(out)


# ============================================================
# 2. 実際のNPC意思決定(気まぐれバイアス版・塊選びのみ。切り役はv1/v2をそのまま再利用)
# ============================================================

def npc_choose_decision_whim(available_piles_counts, chooser_true_hand, chooser_whim, w,
                              other_future_players, beliefs, policy, rng):
    k = len(available_piles_counts)
    self_scores = whim_bias_self_scores(chooser_true_hand, chooser_whim, available_piles_counts, w)

    team_scores = np.zeros(k)
    if other_future_players and k > 1:
        for taken_i in range(k):
            remaining = [pc for i, pc in enumerate(available_piles_counts) if i != taken_i]
            m = len(remaining)
            if m == 0:
                continue
            best = -1e18
            for perm in itertools.permutations(range(m)):
                total = 0.0
                for pile_i, player_slot in enumerate(perm):
                    p = other_future_players[player_slot]
                    total += w1.expected_value_vector(beliefs[p], remaining[pile_i])
                best = max(best, total)
            team_scores[taken_i] = best

    utility = policy.lam * self_scores + (1 - policy.lam) * team_scores
    probs = w1.softmax(utility[None, :], policy.tau)[0]
    choice = rng.choice(k, p=probs)
    return choice


def _team_scores_for_choice(available_piles_counts, other_future_players, beliefs):
    """chooserの手札仮説に依存しない「残りメンバーへの期待値」部分(taken_iごと)。1回だけ計算して使い回す。"""
    k = len(available_piles_counts)
    team_scores = np.zeros(k)
    if other_future_players and k > 1:
        for taken_i in range(k):
            remaining = [pc for i, pc in enumerate(available_piles_counts) if i != taken_i]
            m = len(remaining)
            if m == 0:
                continue
            best = -1e18
            for perm in itertools.permutations(range(m)):
                total = 0.0
                for pile_i, player_slot in enumerate(perm):
                    p = other_future_players[player_slot]
                    total += w1.expected_value_vector(beliefs[p], remaining[pile_i])
                best = max(best, total)
            team_scores[taken_i] = best
    return team_scores


def marginalized_update_belief_for_choice(beliefs, chooser, available_piles_counts, chosen_idx,
                                           other_future_players, policy, whim_params):
    """
    v3の核心: 気まぐれを厳密周辺化した尤度で信念を更新する。
    L(H) = (1/C(15,q)) * sum_{有効なwhimタプルT} softmax(utility(H,T))[chosen_idx]
    """
    q, w = whim_params.q, whim_params.w
    k = len(available_piles_counts)

    hand_scores = np.stack([w1.all_hand_scores_for_pile(pc) for pc in available_piles_counts], axis=1)  # (816,k)
    recipe_scores = np.stack([w1.recipe_scores_vector(pc) for pc in available_piles_counts], axis=1)  # (18,k)

    tuples = ALL_WHIM_TUPLES[q]
    T = len(tuples)
    whim_contrib = np.zeros((T, k))
    for ti, t in enumerate(tuples):
        for c in t:
            whim_contrib[ti] += recipe_scores[c]

    team_scores = _team_scores_for_choice(available_piles_counts, other_future_players, beliefs)  # (k,)

    # utility[H,T,k]
    utility = policy.lam * (hand_scores[:, None, :] + w * whim_contrib[None, :, :]) \
        + (1 - policy.lam) * team_scores[None, None, :]
    # softmaxを最終軸(k=坩堝)に対して計算
    u = utility / policy.tau if policy.tau > 1e-9 else None
    if u is None:
        # ほぼ決定的(tau->0): argmaxのみ1、他0
        idx = np.argmax(utility, axis=-1)  # (816,T)
        probs = np.zeros_like(utility)
        np.put_along_axis(probs, idx[..., None], 1.0, axis=-1)
    else:
        u = u - np.max(u, axis=-1, keepdims=True)
        e = np.exp(u)
        probs = e / np.sum(e, axis=-1, keepdims=True)

    p_chosen = probs[:, :, chosen_idx]  # (816, T)
    mask = WHIM_VALID_MASK[q]  # (816, T)
    valid_count = mask.sum(axis=1)[0]  # 定数 = C(15,q)（全Hで共通。検算済み）
    L = (p_chosen * mask).sum(axis=1) / valid_count  # (816,)
    loglik = np.log(np.clip(L, 1e-300, None))
    beliefs[chooser] = beliefs[chooser] + loglik


# ============================================================
# 3. 1試行(6儀式)のシミュレーション
# ============================================================

class TrialResultV3:
    __slots__ = ("candidate_curve", "team_total", "omni", "pct", "target_score_when_npc_cutter")

    def __init__(self):
        self.candidate_curve = []
        self.team_total = 0
        self.omni = 0
        self.pct = 0
        self.target_score_when_npc_cutter = 0


def simulate_trial_v3(n, rounds, policies, whim_params_list, rng, target_seat=0, track_curve=True):
    """
    policies: 長さnのPolicy(lam, tau=WHIM_TAU固定を推奨)。
    whim_params_list: 長さnのWhimParams、またはNone(気まぐれ無し=「一貫プレイヤー」役)。
    """
    w1.clear_pile_cache()
    w1.clear_norm_cache()
    true_hands = w1.deal_recipe_idxs(n, rng)
    whims = [None if whim_params_list[p] is None else draw_whim(true_hands[p], whim_params_list[p].q, rng)
             for p in range(n)]
    beliefs = [np.zeros(w1.N_HANDS) for _ in range(n)]
    target_row = w1.HAND_TO_ROW[tuple(sorted(true_hands[target_seat]))]

    result = TrialResultV3()
    cutter = 0

    for _r in range(rounds):
        band = w1.make_band(n, rng)
        candidates = w1.cut_sets(len(band), n - 1)
        # 切り役: v1/v2のnpc_cut_decision/update_belief_for_cutをそのまま再利用(気まぐれ非関与)
        chosen_cs, _cands, _ebas = w1.npc_cut_decision(band, n, cutter, true_hands, beliefs,
                                                        policies[cutter], rng)
        w1.update_belief_for_cut(beliefs, cutter, band, n, chosen_cs, candidates, policies[cutter].tau)

        piles = w1.to_piles(band, chosen_cs)
        piles_counts = [w1.pile_to_counts(p) for p in piles]
        order = w1.choose_order(cutter, n)
        available = list(range(len(piles)))
        assign = {}

        for oi, chooser in enumerate(order):
            future_players = [order[k] for k in range(oi + 1, len(order))] + [cutter]
            avail_counts = [piles_counts[i] for i in available]
            wp = whim_params_list[chooser]

            if wp is None:
                choice_local = w1.npc_choose_decision(
                    avail_counts, true_hands[chooser], future_players, beliefs, policies[chooser], rng)[0]
                w1.update_belief_for_choice(beliefs, chooser, avail_counts, choice_local,
                                             future_players, policies[chooser])
            else:
                choice_local = npc_choose_decision_whim(
                    avail_counts, true_hands[chooser], whims[chooser], wp.w,
                    future_players, beliefs, policies[chooser], rng)
                marginalized_update_belief_for_choice(beliefs, chooser, avail_counts, choice_local,
                                                       future_players, policies[chooser], wp)

            chosen_pile_idx = available[choice_local]
            assign[chosen_pile_idx] = chooser
            available.remove(chosen_pile_idx)

        assert len(available) == 1
        assign[available[0]] = cutter

        seat_pile_counts = [None] * n
        for pi, seat in assign.items():
            seat_pile_counts[seat] = piles_counts[pi]

        round_scores = [w1.score_pile(true_hands[s], seat_pile_counts[s]) for s in range(n)]
        team_total = sum(round_scores)
        result.team_total += team_total
        if cutter != target_seat:
            result.target_score_when_npc_cutter += round_scores[target_seat]

        # チーム合計更新: 得点は実手札のみに依存するため、v1/v2の関数をそのまま再利用できる
        w1.update_belief_for_team_total(beliefs, n, seat_pile_counts, team_total)

        result.omni += w1.omni_max(band, true_hands, n)

        if track_curve:
            result.candidate_curve.append(w1.candidate_count(beliefs[target_seat]))

        cutter = (cutter + 1) % n

    result.pct = min(100, round(result.team_total / result.omni * 100)) if result.omni > 0 else (100 if result.team_total >= 0 else 0)
    return result


# ============================================================
# 4. 事前登録済みの合格基準 v3（変更禁止。v1のcheck_a1/a2をそのまま流用）
# ============================================================

def check_d(mean_pct):
    return mean_pct >= 60.0


CONSISTENT_POLICY = w1.Policy(1.0, WHIM_TAU)  # 一貫プレイヤー = λ=1.0・気まぐれ無し・τ=0.3


def ci95_diff(a, b):
    return w1.ci95_diff(a, b)


def check_b1(consistent_scores, random_scores):
    diff, lo, hi, m_c, m_r = w1.ci95_diff(consistent_scores, random_scores)
    rel = (diff / m_r) if m_r > 0 else (float("inf") if diff > 0 else 0.0)
    passed = (rel >= 0.10) and not (lo <= 0 <= hi)
    return passed, {"diff": diff, "ci_lo": lo, "ci_hi": hi, "rel_pct": rel * 100,
                     "mean_consistent": m_c, "mean_random": m_r}


# ============================================================
# 5. 計測ドライバ
# ============================================================

def measurement_a_and_d_v3(lam, q, w, n_trials, rng):
    """計測A(候補数曲線)と計測D(能力下限)を同一試行データから同時に求める。"""
    policies = [w1.Policy(lam, WHIM_TAU)] * 3
    whim_params = [WhimParams(q, w)] * 3
    curves = np.empty((n_trials, 6))
    pcts = np.empty(n_trials)
    for t in range(n_trials):
        res = simulate_trial_v3(3, 6, policies, whim_params, rng, target_seat=0, track_curve=True)
        curves[t] = res.candidate_curve
        pcts[t] = res.pct
    medians = np.median(curves, axis=0)
    q1c = np.percentile(curves, 25, axis=0)
    q3c = np.percentile(curves, 75, axis=0)
    return {
        "median_curve": medians.tolist(), "q1_curve": q1c.tolist(), "q3_curve": q3c.tolist(),
        "a1_pass": w1.check_a1(medians[2]), "a2_pass": w1.check_a2(medians[5]),
        "pct_mean": float(np.mean(pcts)), "pct_median": float(np.median(pcts)),
        "d_pass": check_d(float(np.mean(pcts))),
        "n_trials": n_trials,
    }


def measurement_b_v3(lam, q, w, n_trials, rng):
    """読まれる感: 一貫プレイヤー(気まぐれ無し)vs無作為プレイヤーを、当該組パラメータのNPC切り役2体下で比較。"""
    npc_policy = w1.Policy(lam, WHIM_TAU)
    npc_whim = WhimParams(q, w)

    consistent_scores = np.empty(n_trials)
    random_scores = np.empty(n_trials)
    for t in range(n_trials):
        policies = [CONSISTENT_POLICY, npc_policy, npc_policy]
        whim_params = [None, npc_whim, npc_whim]
        res = simulate_trial_v3(3, 6, policies, whim_params, rng, target_seat=0, track_curve=False)
        consistent_scores[t] = res.target_score_when_npc_cutter
    for t in range(n_trials):
        policies = [w1.RANDOM_POLICY, npc_policy, npc_policy]
        whim_params = [None, npc_whim, npc_whim]
        res = simulate_trial_v3(3, 6, policies, whim_params, rng, target_seat=0, track_curve=False)
        random_scores[t] = res.target_score_when_npc_cutter

    passed, stats = check_b1(consistent_scores, random_scores)
    stats["b1_pass"] = passed
    stats["n_trials"] = n_trials
    return stats


# ============================================================
# 6. グリッドとスイープ実行
# ============================================================

Q_GRID = [1, 2]
W_GRID = [0.5, 1.0]
LAMBDA_GRID_V3 = [0.65, 0.8]
GRID_V3 = [(lam, q, w) for q in Q_GRID for w in W_GRID for lam in LAMBDA_GRID_V3]
assert len(GRID_V3) == 8


def run_one_combo(lam, q, w, n_trials, rng, log=print):
    t0 = time.time()
    ad = measurement_a_and_d_v3(lam, q, w, n_trials, rng)
    t_ad = time.time() - t0
    t0 = time.time()
    b = measurement_b_v3(lam, q, w, n_trials, rng)
    t_b = time.time() - t0

    all_pass = ad["a1_pass"] and ad["a2_pass"] and b["b1_pass"] and ad["d_pass"]
    row = {
        "lambda": lam, "q": q, "w": w,
        "a1_pass": ad["a1_pass"], "a2_pass": ad["a2_pass"], "b1_pass": b["b1_pass"], "d_pass": ad["d_pass"],
        "all_pass": all_pass,
        "median_curve": ad["median_curve"], "q1_curve": ad["q1_curve"], "q3_curve": ad["q3_curve"],
        "pct_mean": ad["pct_mean"], "pct_median": ad["pct_median"],
        "b1_diff": b["diff"], "b1_ci_lo": b["ci_lo"], "b1_ci_hi": b["ci_hi"], "b1_rel_pct": b["rel_pct"],
        "b1_mean_consistent": b["mean_consistent"], "b1_mean_random": b["mean_random"],
        "time_ad_s": t_ad, "time_b_s": t_b,
    }
    log(f"lambda={lam} q={q} w={w}: A1={ad['a1_pass']} A2={ad['a2_pass']} B1={b['b1_pass']} "
        f"D={ad['d_pass']}(pct={ad['pct_mean']:.1f}) ALL={all_pass} | t=({t_ad:.1f}/{t_b:.1f}s)")
    return row


def run_sweep_v3(n_trials=2000, seed=MASTER_SEED, log=print):
    rng = np.random.default_rng(seed)
    rows = []
    for i, (lam, q, w) in enumerate(GRID_V3):
        log(f"[{i+1}/8] lambda={lam} q={q} w={w} 計測中...")
        row = run_one_combo(lam, q, w, n_trials, rng, log=log)
        rows.append(row)

    passers = [r for r in rows if r["all_pass"]]
    selected = None
    if passers:
        max_d = max(r["pct_mean"] for r in passers)
        tied = [r for r in passers if abs(r["pct_mean"] - max_d) < 1e-9]
        selected = max(tied, key=lambda r: r["b1_rel_pct"])

    return {"n_trials": n_trials, "seed": seed, "rows": rows, "n_passers": len(passers), "selected": selected}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="1組(q=2,w=1.0,lambda=0.8=最重量ケース)をn=2000で実測し、全体見積もりを出す")
    ap.add_argument("--smoke", action="store_true", help="全8組をn=20で動作確認")
    ap.add_argument("--sweep", action="store_true", help="全8組本番(n=2000)")
    ap.add_argument("--n-trials", type=int, default=2000)
    ap.add_argument("--out", default="sweep_results_v3.json")
    args = ap.parse_args()

    if args.pilot:
        rng = np.random.default_rng(MASTER_SEED)
        print("パイロット実行: lambda=0.8, q=2, w=1.0 (最重量ケース) n=2000", file=sys.stderr)
        t0 = time.time()
        row = run_one_combo(0.8, 2, 1.0, 2000, rng, log=print)
        elapsed = time.time() - t0
        est_total = elapsed * 8
        print(f"\n1組(最重量ケース)所要時間: {elapsed:.1f}秒", file=sys.stderr)
        print(f"全8組の見積もり(最重量ケース基準の上限見積もり): {est_total/60:.1f}分 ({est_total/3600:.2f}時間)", file=sys.stderr)
        if est_total > 3 * 3600:
            print("★見積もりが3時間を超えました。指示書により、ここで停止して報告してください。", file=sys.stderr)
            sys.exit(2)
        else:
            print("見積もりは3時間以内です。--sweep で本実行してください。", file=sys.stderr)
        return

    if args.smoke:
        result = run_sweep_v3(n_trials=20, seed=MASTER_SEED)
    elif args.sweep:
        result = run_sweep_v3(n_trials=args.n_trials, seed=MASTER_SEED)
    else:
        print("--pilot / --smoke / --sweep のいずれかを指定してください", file=sys.stderr)
        sys.exit(1)

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
    print(f"結果を {args.out} に書き出しました (全通過組: {result['n_passers']}/8)", file=sys.stderr)


if __name__ == "__main__":
    main()
