#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solo_npc_sim.py — 『魔女の調合』ソロNPC方策の事前計測シミュレーション

指示書: 「魔女の調合 ソロNPC方策の事前計測シミュレーション（v1）」2026-07-15 design chat発行

witch.html は読み取り専用（構造を読み取って移植しただけ）。編集していない。
既存の「冴えNPC」Pythonシミュレーションはリポジトリ内・git履歴のどこにも見つからなかった
（sim/, git log --all -- "*.py" を確認済み）。そのため本スクリプトは witch.html から
POOL/scoreRecipe/scorePile/makeBand/cutSets/toPiles/chooseOrder/dealConflicts/dealRecipeIds を
全面的に新規移植している（sim/witch_privacy/witch_secrecy_repro.py で同じ移植を既に行っており、
そこから流用・再検証済み）。

実行方法:
    python solo_npc_sim.py --smoke      # 動作確認用の小規模実行
    python solo_npc_sim.py --sweep      # 本番のパラメータスイープ（15組 x 計測A/B/C）

決定論性: MASTER_SEED から派生した numpy.random.Generator のみを使用。
"""

import argparse
import itertools
import json
import sys
import time

import numpy as np

# Windows既定のcp932コンソールでは絵文字・数学記号(≥等)の出力でUnicodeEncodeErrorになるため、
# 標準出力/エラーをUTF-8に固定する(reconfigureはPython 3.7+)。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MASTER_SEED = 20260715

# ============================================================
# 1. witch.html からの移植（凍結コアロジック。sim/witch_privacy と同一定義）
# ============================================================

POOL = [
    {"id": "pair_満星", "type": "pair", "a": 0, "b": 3, "pt": 4},
    {"id": "pair_火霜", "type": "pair", "a": 1, "b": 4, "pt": 4},
    {"id": "pair_影蛇", "type": "pair", "a": 2, "b": 5, "pt": 4},
    {"id": "pair_満火", "type": "pair", "a": 0, "b": 1, "pt": 4},
    {"id": "pair_星影", "type": "pair", "a": 3, "b": 2, "pt": 4},
    {"id": "pair_霜蛇", "type": "pair", "a": 4, "b": 5, "pt": 4},
    {"id": "cnt2_満火", "type": "cnt2", "a": 0, "b": 1, "pt": 5},
    {"id": "cnt2_影星", "type": "cnt2", "a": 2, "b": 3, "pt": 5},
    {"id": "cnt2_霜蛇", "type": "cnt2", "a": 4, "b": 5, "pt": 5},
    {"id": "cnt2_満霜", "type": "cnt2", "a": 0, "b": 4, "pt": 5},
    {"id": "solo_星", "type": "solo", "a": 3, "pt": 3},
    {"id": "solo_霜", "type": "solo", "a": 4, "pt": 3},
    {"id": "solo_満", "type": "solo", "a": 0, "pt": 3},
    {"id": "solo_火", "type": "solo", "a": 1, "pt": 3},
    {"id": "abs2_影蛇", "type": "abs2", "a": 2, "b": 5, "pt": 3},
    {"id": "abs2_火星", "type": "abs2", "a": 1, "b": 3, "pt": 3},
    {"id": "abs_影", "type": "abs", "a": 2, "pt": 2},
    {"id": "abs_蛇", "type": "abs", "a": 5, "pt": 2},
]
assert len(POOL) == 18

ALL_HAND_INDICES = list(itertools.combinations(range(18), 3))
assert len(ALL_HAND_INDICES) == 816
N_HANDS = 816
HAND_IDX_MATRIX = np.array(ALL_HAND_INDICES, dtype=np.int64)  # shape (816, 3)


def score_recipe(recipe, pile_counts):
    a, b = recipe["a"], recipe.get("b")
    t, pt = recipe["type"], recipe["pt"]
    ca = pile_counts[a]
    if t == "pair":
        return pt if (ca >= 1 and pile_counts[b] >= 1) else 0
    if t == "cnt2":
        return pt if (ca >= 2 or pile_counts[b] >= 2) else 0
    if t == "solo":
        return pt if ca == 1 else 0
    if t == "abs2":
        return pt if (ca == 0 and pile_counts[b] == 0) else 0
    if t == "abs":
        return pt if ca == 0 else 0
    raise ValueError(t)


def pile_to_counts(pile):
    counts = [0] * 6
    for m in pile:
        counts[m] += 1
    return counts


def score_pile(hand_idxs, pile_counts):
    return sum(score_recipe(POOL[i], pile_counts) for i in hand_idxs)


def recipe_scores_vector(pile_counts):
    """全18レシピの、このpileに対する得点ベクトル(長さ18)。"""
    return np.array([score_recipe(r, pile_counts) for r in POOL], dtype=np.float64)


# 1試行(6儀式)の中で同じpile_countsが何度も問い合わせられる(カット決定→信念更新で同じ
# カット候補集合を2回走査する等)ため、キャッシュして重複計算を消す。
# キーは試行をまたいで再利用されないよう、trial境界でクリアする(clear_pile_cache参照)。
_PILE_SCORE_CACHE = {}


def all_hand_scores_for_pile(pile_counts):
    """816通り全手札の、このpileに対する得点(長さ816のnumpy配列)。ベクトル化の要。キャッシュ付き。"""
    key = tuple(pile_counts)
    cached = _PILE_SCORE_CACHE.get(key)
    if cached is not None:
        return cached
    rv = recipe_scores_vector(pile_counts)  # (18,)
    result = rv[HAND_IDX_MATRIX].sum(axis=1)  # (816,)
    _PILE_SCORE_CACHE[key] = result
    return result


def clear_pile_cache():
    _PILE_SCORE_CACHE.clear()


def make_band(n, rng):
    bag = []
    for m in range(6):
        bag.extend([m] * 3)
    bag = np.array(bag)
    rng.shuffle(bag)
    return list(bag[: n * 3])


def cut_sets(length, nc):
    return list(itertools.combinations(range(1, length), nc))


def to_piles(band, cuts):
    s = sorted(cuts)
    pts = [0] + list(s) + [len(band)]
    return [band[pts[i]:pts[i + 1]] for i in range(len(pts) - 1)]


def choose_order(cutter, n):
    order = []
    for i in range(n):
        idx = (cutter + 1 + i) % n
        if idx != cutter:
            order.append(idx)
    return order


def deal_conflicts(idx_list):
    avoid, want = set(), set()
    for i in idx_list:
        r = POOL[i]
        if r["type"] == "abs":
            avoid.add(r["a"])
        if r["type"] == "abs2":
            avoid.add(r["a"]); avoid.add(r["b"])
        if r["type"] in ("pair", "cnt2"):
            want.add(r["a"]); want.add(r["b"])
        if r["type"] == "solo":
            want.add(r["a"])
    return any(m in want for m in avoid)


def deal_recipe_idxs(n, rng):
    pool_idx = np.arange(18)
    for _ in range(600):
        c = pool_idx.copy()
        rng.shuffle(c)
        c = c[: n * 3].tolist()
        if not deal_conflicts(c):
            return [tuple(sorted(c[p * 3:p * 3 + 3])) for p in range(n)]
    c = pool_idx.copy()
    rng.shuffle(c)
    c = c[: n * 3].tolist()
    return [tuple(sorted(c[p * 3:p * 3 + 3])) for p in range(n)]


def hand_to_row(hand):
    """手札(3要素タプル、POOLインデックス、ソート済み) -> ALL_HAND_INDICESでの行番号"""
    return ALL_HAND_INDICES.index(tuple(sorted(hand)))


# 全ハンドの行検索を高速化するための辞書
HAND_TO_ROW = {h: i for i, h in enumerate(ALL_HAND_INDICES)}


# ============================================================
# 2. 信念（belief）状態と尤度更新
# ============================================================
# belief[p] は長さ816の対数尤度ベクトル(log-space、正規化はしない。相対値のみ使う)。
# 「候補数」定義（事前登録・変更禁止）：最尤仮説の尤度の1/20以上の尤度を持つ仮説の数
#   = log空間では: logbelief >= logmax - log(20)
LOG_1_20 = np.log(1.0 / 20.0)


def softmax(utilities, tau):
    """utilities: numpy配列(最後の軸がソフトマックス対象)。tau<=1e-9ならone-hot(argmax)。"""
    if tau <= 1e-9:
        out = np.zeros_like(utilities)
        idx = np.argmax(utilities, axis=-1)
        np.put_along_axis(out, np.expand_dims(idx, -1), 1.0, axis=-1)
        return out
    u = utilities / tau
    u = u - np.max(u, axis=-1, keepdims=True)
    e = np.exp(u)
    return e / np.sum(e, axis=-1, keepdims=True)



# 【2026-07-15 重大バグ修正】以前はid(belief_logw)をキーにキャッシュしていたが、
# Pythonのメモリアロケータは解放直後の配列のメモリアドレスをほぼ即座に再利用するため
# （実測: beliefs[p]=beliefs[p]+loglik を2000回繰り返すパターンで2000回中1995回id衝突）、
# 無関係な信念配列に対して古いキャッシュ値が誤ってヒットし続けていた。
# v1〜v3の全スイープ結果はこのバグの影響下で計算されたものであり、再計測が必要。
# 修正: 配列の「内容」をキーにする(id()は使わない。内容が同じなら結果も同じなので安全)。
_NORM_CACHE = {}


def clear_norm_cache():
    _NORM_CACHE.clear()


def _normalized_weights(belief_logw):
    key = belief_logw.tobytes()
    cached = _NORM_CACHE.get(key)
    if cached is not None:
        return cached
    w = belief_logw - np.max(belief_logw)
    w = np.exp(w)
    w = w / np.sum(w)
    _NORM_CACHE[key] = w
    return w


def expected_value_vector(belief_logw, pile_counts):
    """belief（対数尤度、正規化前）に基づく、このpileに対する期待得点(スカラー)。正規化はキャッシュする。"""
    w = _normalized_weights(belief_logw)
    scores = all_hand_scores_for_pile(pile_counts)
    return float(np.dot(w, scores))


def candidate_count(belief_logw):
    m = np.max(belief_logw)
    return int(np.sum(belief_logw >= m + LOG_1_20))


def top1_hit(belief_logw, true_hand_row):
    """最尤仮説(タイなら全部)に真の手札が含まれるか。"""
    m = np.max(belief_logw)
    top_rows = np.where(belief_logw >= m - 1e-9)[0]
    return true_hand_row in top_rows


PERMS = {n: list(itertools.permutations(range(n))) for n in (3, 4)}


def best_assignment_value(piles_counts, hand_rows_or_none, belief_logws, self_idx, self_hand_row):
    """
    複数の坩堝(piles_counts: list of pile_counts)を、self_idx番目のプレイヤー(既知の手札=self_hand_row)と
    それ以外のプレイヤー(信念分布 belief_logws[i] で期待値評価)に最適配置したときの合計期待値(スカラー)。
    witch.html の bestForCut/omniMax の「期待値版」。
    """
    n = len(piles_counts)
    pile_scores_by_slot = []  # pile_scores_by_slot[pile_i] = {"self": v, "others": [v_for_player_j,...]}
    self_scores = [all_hand_scores_for_pile(pc)[self_hand_row] for pc in piles_counts]
    other_scores = []  # other_scores[player_slot][pile_i]
    for j in range(n):
        if j == self_idx:
            other_scores.append(None)
            continue
        vals = [expected_value_vector(belief_logws[j], pc) for pc in piles_counts]
        other_scores.append(vals)

    best = -1e18
    for perm in PERMS[n]:
        total = 0.0
        for pile_i, player_slot in enumerate(perm):
            if player_slot == self_idx:
                total += self_scores[pile_i]
            else:
                total += other_scores[player_slot][pile_i]
        if total > best:
            best = total
    return best


def best_assignment_value_hypothesis_vector(piles_counts, belief_logws, self_idx):
    """
    self_idx番目のプレイヤーの手札仮説を816通り全て試したときの、
    「最適配置での合計期待値」を816通り分まとめて返す(numpy配列, shape(816,))。
    他プレイヤーは信念分布による期待値、self_idxのみ816通りの仮説を動かす。
    """
    n = len(piles_counts)
    self_scores_per_pile = np.stack([all_hand_scores_for_pile(pc) for pc in piles_counts], axis=1)  # (816, n_piles)
    other_scores = []
    for j in range(n):
        if j == self_idx:
            other_scores.append(None)
            continue
        vals = [expected_value_vector(belief_logws[j], pc) for pc in piles_counts]
        other_scores.append(vals)

    best = np.full(N_HANDS, -1e18)
    for perm in PERMS[n]:
        total = np.zeros(N_HANDS)
        for pile_i, player_slot in enumerate(perm):
            if player_slot == self_idx:
                total = total + self_scores_per_pile[:, pile_i]
            else:
                total = total + other_scores[player_slot][pile_i]
        best = np.maximum(best, total)
    return best  # (816,)


# ============================================================
# 3. NPC方策(λ, τ)によるカット・チョイス
# ============================================================

class Policy:
    __slots__ = ("lam", "tau")

    def __init__(self, lam, tau):
        self.lam = lam
        self.tau = tau


def npc_cut_decision(band, n, cutter, true_hands, beliefs, policy, rng):
    """
    切り役の意思決定。全カット候補についてEBA(期待最適配置値)を計算し、softmax(τ)でサンプル。
    戻り値: (選ばれたcutSet, 全カット候補のリスト, 各候補のEBA値の配列)
    """
    candidates = cut_sets(len(band), n - 1)
    ebas = np.empty(len(candidates))
    self_hand_row = HAND_TO_ROW[tuple(sorted(true_hands[cutter]))]
    for ci, cs in enumerate(candidates):
        piles = to_piles(band, cs)
        piles_counts = [pile_to_counts(p) for p in piles]
        ebas[ci] = best_assignment_value(piles_counts, None, beliefs, cutter, self_hand_row)
    probs = softmax(ebas[None, :], policy.tau)[0]
    choice = rng.choice(len(candidates), p=probs)
    return candidates[choice], candidates, ebas


def npc_choose_decision(available_piles_counts, chooser_true_hand, other_future_players,
                         beliefs, policy, rng):
    """
    手番者の意思決定。効用 = λ*自分の得点 + (1-λ)*残りメンバーへの期待値。
    available_piles_counts: 残っている坩堝のcountsのリスト
    other_future_players: このチョイスの後にまだ坩堝を受け取る他プレイヤー(切り役含む)のインデックスのリスト
    """
    k = len(available_piles_counts)
    self_scores = np.array([score_pile(chooser_true_hand, pc) for pc in available_piles_counts])

    team_scores = np.zeros(k)
    if other_future_players and k > 1:
        for taken_i in range(k):
            remaining = [pc for i, pc in enumerate(available_piles_counts) if i != taken_i]
            # 残りの坩堝を、残りの未来プレイヤーへ最適配置(信念期待値)したときの合計値
            m = len(remaining)
            if m == 0:
                continue
            best = -1e18
            for perm in itertools.permutations(range(m)):
                total = 0.0
                for pile_i, player_slot in enumerate(perm):
                    p = other_future_players[player_slot]
                    total += expected_value_vector(beliefs[p], remaining[pile_i])
                best = max(best, total)
            team_scores[taken_i] = best

    utility = policy.lam * self_scores + (1 - policy.lam) * team_scores
    probs = softmax(utility[None, :], policy.tau)[0]
    choice = rng.choice(k, p=probs)
    return choice, utility, probs


# ============================================================
# 4. 信念更新(尤度)
# ============================================================

def update_belief_for_choice(beliefs, chooser, available_piles_counts, chosen_idx,
                              other_future_players, policy):
    """手番者の実際の選択から、chooser の信念を更新する(対数尤度を加算)。"""
    k = len(available_piles_counts)
    self_scores_h = np.stack([all_hand_scores_for_pile(pc) for pc in available_piles_counts], axis=1)  # (816,k)

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
                    total += expected_value_vector(beliefs[p], remaining[pile_i])
                best = max(best, total)
            team_scores[taken_i] = best

    utility_h = policy.lam * self_scores_h + (1 - policy.lam) * team_scores[None, :]  # (816, k)
    probs_h = softmax(utility_h, policy.tau)  # (816, k) 仮説ごとの選択確率
    loglik = np.log(np.clip(probs_h[:, chosen_idx], 1e-300, None))
    beliefs[chooser] = beliefs[chooser] + loglik


def update_belief_for_cut(beliefs, cutter, band, n, chosen_cutset, candidates, tau):
    """切り役の実際のカットから、cutter の信念を更新する。"""
    log_liks_by_cs = np.empty((len(candidates), N_HANDS))
    for ci, cs in enumerate(candidates):
        piles = to_piles(band, cs)
        piles_counts = [pile_to_counts(p) for p in piles]
        log_liks_by_cs[ci] = best_assignment_value_hypothesis_vector(piles_counts, beliefs, cutter)
    # softmax over candidates, for each hypothesis h (transpose to hypothesis-major for clarity)
    ebas = log_liks_by_cs.T  # (816, n_candidates)
    probs_h = softmax(ebas, tau)
    chosen_idx = candidates.index(chosen_cutset)
    loglik = np.log(np.clip(probs_h[:, chosen_idx], 1e-300, None))
    beliefs[cutter] = beliefs[cutter] + loglik


def update_belief_for_team_total(beliefs, n, piles_counts_by_seat, team_total, tau_unused=None):
    """
    毎儀式のチーム合計を用いた近似ベイズ更新(畳み込み)。
    各プレイヤーの「自分の坩堝に対する得点」の信念加重分布を作り、他プレイヤー分を畳み込んで
    残差の確率を尤度として乗せる(§本文参照：joint厳密解ではなく畳み込み近似)。
    """
    # 各プレイヤーについて、得点分布(0..MAXSCORE)を信念で重み付けして作る
    MAXSCORE = 40  # 3枚レシピ・最大pt5x3=15程度だが余裕を持たせる
    score_dists = []
    all_scores_by_p = []
    for p in range(n):
        scores = all_hand_scores_for_pile(piles_counts_by_seat[p])  # (816,)
        all_scores_by_p.append(scores)
        w = _normalized_weights(beliefs[p])
        int_scores = scores.astype(np.int64)
        # np.bincount で加重ヒストグラムを作る(純Pythonループのzip版より大幅に速い)
        dist = np.bincount(int_scores, weights=w, minlength=MAXSCORE + 1)[:MAXSCORE + 1]
        score_dists.append(dist)

    for target in range(n):
        # target以外の分布を畳み込む
        conv = np.array([1.0])
        for q in range(n):
            if q == target:
                continue
            conv = np.convolve(conv, score_dists[q])
        # conv[s] = P(他プレイヤー合計 == s)
        target_scores = all_scores_by_p[target].astype(int)  # (816,)
        required = team_total - target_scores  # (816,)
        lik = np.zeros(N_HANDS)
        valid = (required >= 0) & (required < len(conv))
        lik[valid] = conv[required[valid]]
        lik = np.clip(lik, 1e-12, None)
        beliefs[target] = beliefs[target] + np.log(lik)


# ============================================================
# 5. omni（全知の理論上限。witch.html omniMax の移植。pct計算専用・真の手札を使う）
# ============================================================

def omni_max(band, true_hands, n):
    best = -1e18
    for cs in cut_sets(len(band), n - 1):
        piles = to_piles(band, cs)
        piles_counts = [pile_to_counts(p) for p in piles]
        for perm in PERMS[n]:
            total = sum(score_pile(true_hands[perm[i]], piles_counts[i]) for i in range(n))
            if total > best:
                best = total
    return best


# ============================================================
# 6. 1試行(6儀式)のシミュレーション
# ============================================================

class TrialResult:
    __slots__ = ("candidate_curve", "top1_hit_final", "player_totals", "team_total",
                 "omni", "pct", "target_score_when_npc_cutter", "first_chooser_hits")

    def __init__(self):
        self.candidate_curve = []  # 対象プレイヤーの候補数の推移(儀式ごと)
        self.top1_hit_final = None
        self.player_totals = None
        self.team_total = 0
        self.omni = 0
        self.pct = 0
        self.target_score_when_npc_cutter = 0
        self.first_chooser_hits = []  # v2 A-3': 各儀式で「最初の選択者」の予測が的中したか(bool)


def predict_first_choice(available_piles_counts, belief_of_chooser, future_players, beliefs, policy):
    """
    v2 A-3': 観測者が「最初の選択者」の実際の手札を知らず、信念(belief_of_chooser)だけを
    持っている状態で、chooserがどの坩堝を選ぶと予測するか。npc_choose_decisionと同じ効用式を
    使うが、self_scoresを「真の手札」ではなく「信念による期待得点」で置き換える。
    """
    k = len(available_piles_counts)
    self_scores = np.array([expected_value_vector(belief_of_chooser, pc) for pc in available_piles_counts])

    team_scores = np.zeros(k)
    if future_players and k > 1:
        for taken_i in range(k):
            remaining = [pc for i, pc in enumerate(available_piles_counts) if i != taken_i]
            m = len(remaining)
            if m == 0:
                continue
            best = -1e18
            for perm in itertools.permutations(range(m)):
                total = 0.0
                for pile_i, player_slot in enumerate(perm):
                    p = future_players[player_slot]
                    total += expected_value_vector(beliefs[p], remaining[pile_i])
                best = max(best, total)
            team_scores[taken_i] = best

    utility = policy.lam * self_scores + (1 - policy.lam) * team_scores
    return int(np.argmax(utility))


def simulate_trial(n, rounds, policies, rng, target_seat=0, track_curve=True):
    """
    n人・rounds儀式を1回シミュレートする。
    policies: 長さnのPolicyリスト(各プレイヤーの意思決定パラメータ)。
    target_seat: 候補数を追跡する対象の席番号。
    """
    clear_pile_cache()  # 試行をまたぐキャッシュ肥大化を防ぐ(pile_countsは試行ごとにほぼ別物のため)
    clear_norm_cache()
    true_hands = deal_recipe_idxs(n, rng)
    beliefs = [np.zeros(N_HANDS) for _ in range(n)]  # 一様事前(対数尤度0)
    target_row = HAND_TO_ROW[tuple(sorted(true_hands[target_seat]))]

    result = TrialResult()
    result.player_totals = [0] * n
    cutter = 0

    for _r in range(rounds):
        band = make_band(n, rng)
        candidates = cut_sets(len(band), n - 1)
        chosen_cs, _cands, _ebas = npc_cut_decision(band, n, cutter, true_hands, beliefs,
                                                     policies[cutter], rng)
        # 切り役の信念更新(自分がどのカットを選んだかから)
        update_belief_for_cut(beliefs, cutter, band, n, chosen_cs, candidates, policies[cutter].tau)

        piles = to_piles(band, chosen_cs)
        piles_counts = [pile_to_counts(p) for p in piles]
        order = choose_order(cutter, n)
        available = list(range(len(piles)))
        assign = {}

        for oi, chooser in enumerate(order):
            future_players = [order[k] for k in range(oi + 1, len(order))] + [cutter]
            avail_counts = [piles_counts[i] for i in available]

            if oi == 0:
                # v2 A-3': 最初の選択者の実選択より前に、信念だけを使った予測を記録する
                predicted_local = predict_first_choice(avail_counts, beliefs[chooser], future_players,
                                                        beliefs, policies[chooser])

            choice_local, _util, _probs = npc_choose_decision(
                avail_counts, true_hands[chooser], future_players, beliefs, policies[chooser], rng)
            chosen_pile_idx = available[choice_local]

            if oi == 0:
                result.first_chooser_hits.append(predicted_local == choice_local)

            update_belief_for_choice(beliefs, chooser, avail_counts, choice_local,
                                      future_players, policies[chooser])
            assign[chosen_pile_idx] = chooser
            available.remove(chosen_pile_idx)

        assert len(available) == 1
        assign[available[0]] = cutter

        seat_pile_counts = [None] * n
        for pi, seat in assign.items():
            seat_pile_counts[seat] = piles_counts[pi]

        round_scores = [score_pile(true_hands[s], seat_pile_counts[s]) for s in range(n)]
        team_total = sum(round_scores)
        for s in range(n):
            result.player_totals[s] += round_scores[s]
        result.team_total += team_total
        if cutter != target_seat:
            result.target_score_when_npc_cutter += round_scores[target_seat]

        # チーム合計による近似ベイズ更新(全員)
        update_belief_for_team_total(beliefs, n, seat_pile_counts, team_total)

        result.omni += omni_max(band, true_hands, n)

        if track_curve:
            result.candidate_curve.append(candidate_count(beliefs[target_seat]))

        cutter = (cutter + 1) % n

    result.top1_hit_final = top1_hit(beliefs[target_seat], target_row)
    result.pct = min(100, round(result.team_total / result.omni * 100)) if result.omni > 0 else (100 if result.team_total >= 0 else 0)
    return result


# ============================================================
# 7. パラメータグリッドと方策の定義
# ============================================================
# tau の具体値は効用スケール(得点1回あたり2〜5点)に合わせて決めた:
#   小=0.5(かなり決定的) 中=2.0(中程度の揺らぎ) 大=6.0(ほぼ均等に近い)
LAMBDA_GRID = [0.5, 0.65, 0.8, 0.9, 1.0]
TAU_GRID = {"small": 0.5, "mid": 2.0, "large": 6.0}
PARAM_GRID = [(lam, tau_name, tau_val) for lam in LAMBDA_GRID for tau_name, tau_val in TAU_GRID.items()]
assert len(PARAM_GRID) == 15

RATIONAL_POLICY = Policy(1.0, 1e-6)   # 合理的プレイヤー = 自己利益のみ・決定的
RANDOM_POLICY = Policy(0.5, 1e6)      # 無作為プレイヤー = 効用に関係なくほぼ一様選択の近似


# ============================================================
# 8. 事前登録済みの合格基準（変更禁止）
# ============================================================

def check_a1(curve_round3_median):
    return curve_round3_median >= 150


def check_a2(curve_round6_median):
    return 30 <= curve_round6_median <= 500


def check_a3(top1_rate_round6):
    return top1_rate_round6 >= 0.55


def ci95_diff(sample1, sample2):
    """2標本の平均差と95%信頼区間(正規近似)。"""
    a1, a2 = np.asarray(sample1, dtype=np.float64), np.asarray(sample2, dtype=np.float64)
    m1, m2 = a1.mean(), a2.mean()
    se = np.sqrt(a1.var(ddof=1) / len(a1) + a2.var(ddof=1) / len(a2))
    diff = m1 - m2
    lo, hi = diff - 1.96 * se, diff + 1.96 * se
    return diff, lo, hi, m1, m2


def check_b1(consistent_scores, random_scores):
    diff, lo, hi, m_c, m_r = ci95_diff(consistent_scores, random_scores)
    if m_r <= 0:
        rel = float("inf") if diff > 0 else 0.0
    else:
        rel = diff / m_r
    passed = (rel >= 0.10) and not (lo <= 0 <= hi)
    return passed, {"diff": diff, "ci_lo": lo, "ci_hi": hi, "rel_pct": rel * 100,
                     "mean_consistent": m_c, "mean_random": m_r}


TITLE_BANDS = [("≥92", 92, 101), ("82-92", 82, 92), ("70-82", 70, 82), ("58-70", 58, 70), ("<58", -1, 58)]


def pct_band_shares(pct_values):
    arr = np.asarray(pct_values)
    shares = {}
    for name, lo, hi in TITLE_BANDS:
        shares[name] = float(np.mean((arr >= lo) & (arr < hi)))
    return shares


def check_c1(solo_shares, multi_shares):
    deviations = {name: (solo_shares[name] - multi_shares[name]) * 100 for name, _, _ in TITLE_BANDS}
    passed = all(abs(v) <= 8.0 for v in deviations.values())
    return passed, deviations


# ============================================================
# 9. 計測A/B/Cのドライバ
# ============================================================

def measurement_a(lam, tau, n_trials, rng):
    """解読感：候補数曲線 + 最有力1枚の的中率(6儀式後)。"""
    policies = [Policy(lam, tau)] * 3
    curves = np.empty((n_trials, 6))
    top1_hits = np.empty(n_trials, dtype=bool)
    for t in range(n_trials):
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=True)
        curves[t] = res.candidate_curve
        top1_hits[t] = res.top1_hit_final
    medians = np.median(curves, axis=0)
    q1 = np.percentile(curves, 25, axis=0)
    q3 = np.percentile(curves, 75, axis=0)
    return {
        "median_curve": medians.tolist(),
        "q1_curve": q1.tolist(),
        "q3_curve": q3.tolist(),
        "top1_hit_rate_round6": float(np.mean(top1_hits)),
        "a1_pass": check_a1(medians[2]),
        "a2_pass": check_a2(medians[5]),
        "a3_pass": check_a3(float(np.mean(top1_hits))),
        "n_trials": n_trials,
    }


# ============================================================
# 9c. v2追加: A-3'（最初の選択者の予測的中率）・D（能力下限）
# ============================================================

def check_a3_prime(hit_curve):
    """儀式5-6平均的中率>=50% かつ (儀式5-6平均 - 儀式1-2平均)>=+10pt。hit_curveは長さ6の的中率配列。"""
    avg_56 = float(np.mean(hit_curve[4:6]))
    avg_12 = float(np.mean(hit_curve[0:2]))
    passed = (avg_56 >= 0.50) and ((avg_56 - avg_12) >= 0.10)
    return passed, avg_56, avg_12, avg_56 - avg_12


def check_d(mean_pct):
    return mean_pct >= 60.0


def measurement_a_and_d(lam, tau, n_trials, rng):
    """
    v2: 計測A(候補数曲線・A-3'的中率曲線)と計測D(能力下限)を同一試行データから同時に求める
    （候補方策のNPC3体卓は共通のため、指示書の「計測Aの試行データを流用してよい」に従う）。
    """
    policies = [Policy(lam, tau)] * 3
    curves = np.empty((n_trials, 6))
    hit_curves = np.empty((n_trials, 6), dtype=bool)
    top1_hits = np.empty(n_trials, dtype=bool)
    pcts = np.empty(n_trials)
    for t in range(n_trials):
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=True)
        curves[t] = res.candidate_curve
        hit_curves[t] = res.first_chooser_hits
        top1_hits[t] = res.top1_hit_final
        pcts[t] = res.pct

    medians = np.median(curves, axis=0)
    q1 = np.percentile(curves, 25, axis=0)
    q3 = np.percentile(curves, 75, axis=0)
    hit_rate_curve = np.mean(hit_curves, axis=0)  # 儀式ごとの的中率(1..6)

    a3p_pass, avg_56, avg_12, delta = check_a3_prime(hit_rate_curve)
    d_pass = check_d(float(np.mean(pcts)))

    return {
        "median_curve": medians.tolist(), "q1_curve": q1.tolist(), "q3_curve": q3.tolist(),
        "top1_hit_rate_round6": float(np.mean(top1_hits)),
        "a1_pass": check_a1(medians[2]), "a2_pass": check_a2(medians[5]),
        "hit_rate_curve": hit_rate_curve.tolist(),
        "a3prime_avg_round56": avg_56, "a3prime_avg_round12": avg_12, "a3prime_delta": delta,
        "a3prime_pass": a3p_pass,
        "pct_mean": float(np.mean(pcts)), "pct_median": float(np.median(pcts)),
        "d_pass": d_pass,
        "n_trials": n_trials,
    }


def measurement_b(lam, tau, n_trials, rng):
    """読まれる感：一貫方策 vs 無作為方策の、NPC切り役下での個人点合計比較。"""
    npc_policy = Policy(lam, tau)
    consistent_scores = np.empty(n_trials)
    random_scores = np.empty(n_trials)
    for t in range(n_trials):
        policies = [RATIONAL_POLICY, npc_policy, npc_policy]  # target=RATIONAL_POLICYの位置(一貫)
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=False)
        consistent_scores[t] = res.target_score_when_npc_cutter
    for t in range(n_trials):
        policies = [RANDOM_POLICY, npc_policy, npc_policy]  # target=RANDOM_POLICYの位置(無作為)
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=False)
        random_scores[t] = res.target_score_when_npc_cutter
    passed, stats = check_b1(consistent_scores, random_scores)
    stats["b1_pass"] = passed
    stats["n_trials"] = n_trials
    return stats


def measurement_c(lam, tau, n_trials, rng, multi_baseline_shares):
    """称号互換性：ソロ想定卓(合理1+NPC2)のpct分布 vs マルチ基準(合理NPC3)。"""
    policies = [RATIONAL_POLICY, Policy(lam, tau), Policy(lam, tau)]
    pcts = np.empty(n_trials)
    for t in range(n_trials):
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=False)
        pcts[t] = res.pct
    shares = pct_band_shares(pcts)
    passed, deviations = check_c1(shares, multi_baseline_shares)
    return {
        "pct_mean": float(np.mean(pcts)),
        "pct_median": float(np.median(pcts)),
        "band_shares": shares,
        "deviations_pt": deviations,
        "c1_pass": passed,
        "n_trials": n_trials,
    }


def multi_baseline(n_trials, rng):
    """マルチ基準(合理NPC3人)のpct分布。計測Cの比較対象として1回だけ計測する。
    【2026-07-15 design chat裁定によりC-1判定自体は無効化されたため、現在は参考値としてのみ残す。】"""
    policies = [RATIONAL_POLICY, RATIONAL_POLICY, RATIONAL_POLICY]
    pcts = np.empty(n_trials)
    for t in range(n_trials):
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=False)
        pcts[t] = res.pct
    return pct_band_shares(pcts), float(np.mean(pcts))


# ============================================================
# 9b. 計測C（記述的版・v1.1裁定）
# ============================================================
# 2026-07-15 design chat裁定により、C-1の合否判定（86.2%基準との比較）は
# 「比較対象の分布データが存在しない」ため無効化された。代わりに、計測A・Bの両方を
# 通過したパラメータ組についてのみ、2種のプロキシプレイヤーで称号帯分布を記述的に報告する。
TEAM_TYPE_POLICY = Policy(0.5, 1e-6)   # チーム型プロキシ = 自己利益とチーム利益を五分五分・決定的
SELFISH_PROXY_POLICY = RATIONAL_POLICY  # 利己型プロキシ = 既存のRATIONAL_POLICY(λ=1.0,τ→0)と同一定義


def measurement_c_descriptive(lam, tau, n_trials, rng, proxy_policy):
    """称号帯分布を記述的に返す（合否判定なし）。"""
    policies = [proxy_policy, Policy(lam, tau), Policy(lam, tau)]
    pcts = np.empty(n_trials)
    for t in range(n_trials):
        res = simulate_trial(3, 6, policies, rng, target_seat=0, track_curve=False)
        pcts[t] = res.pct
    return {
        "pct_mean": float(np.mean(pcts)),
        "pct_median": float(np.median(pcts)),
        "band_shares": pct_band_shares(pcts),
        "n_trials": n_trials,
    }


def run_descriptive_c_for_passers(passing_rows, n_trials=2000, seed=MASTER_SEED + 1, log=print):
    """A・B双方に合格した組についてのみ、利己型・チーム型2プロキシで記述的Cを実行する。"""
    rng = np.random.default_rng(seed)
    results = []
    for i, row in enumerate(passing_rows):
        lam, tau = row["lambda"], row["tau"]
        t0 = time.time()
        selfish = measurement_c_descriptive(lam, tau, n_trials, rng, SELFISH_PROXY_POLICY)
        team = measurement_c_descriptive(lam, tau, n_trials, rng, TEAM_TYPE_POLICY)
        dt = time.time() - t0
        results.append({
            "lambda": lam, "tau_name": row["tau_name"], "tau": tau,
            "selfish_proxy": selfish, "team_proxy": team,
        })
        log(f"[descriptive-C {i+1}/{len(passing_rows)}] lambda={lam} tau={row['tau_name']} "
            f"selfish_mean={selfish['pct_mean']:.1f} team_mean={team['pct_mean']:.1f} (t={dt:.1f}s)")
    return results


# ============================================================
# 10. スイープ実行
# ============================================================

def run_sweep(n_trials=2000, seed=MASTER_SEED, log=print):
    rng = np.random.default_rng(seed)

    log("マルチ基準(合理NPC3人)を計測中...")
    t0 = time.time()
    multi_shares, multi_mean_pct = multi_baseline(n_trials, rng)
    log(f"  完了 ({time.time()-t0:.1f}s) mean_pct={multi_mean_pct:.2f} shares={multi_shares}")

    rows = []
    for i, (lam, tau_name, tau_val) in enumerate(PARAM_GRID):
        t0 = time.time()
        a = measurement_a(lam, tau_val, n_trials, rng)
        ta = time.time() - t0
        t0 = time.time()
        b = measurement_b(lam, tau_val, n_trials, rng)
        tb = time.time() - t0
        t0 = time.time()
        c = measurement_c(lam, tau_val, n_trials, rng, multi_shares)
        tc = time.time() - t0

        row = {
            "lambda": lam, "tau_name": tau_name, "tau": tau_val,
            "a1_pass": a["a1_pass"], "a2_pass": a["a2_pass"], "a3_pass": a["a3_pass"],
            "b1_pass": b["b1_pass"], "c1_pass": c["c1_pass"],
            "all_pass": a["a1_pass"] and a["a2_pass"] and a["a3_pass"] and b["b1_pass"] and c["c1_pass"],
            "median_curve": a["median_curve"], "q1_curve": a["q1_curve"], "q3_curve": a["q3_curve"],
            "top1_hit_rate_round6": a["top1_hit_rate_round6"],
            "b1_diff": b["diff"], "b1_ci_lo": b["ci_lo"], "b1_ci_hi": b["ci_hi"], "b1_rel_pct": b["rel_pct"],
            "b1_mean_consistent": b["mean_consistent"], "b1_mean_random": b["mean_random"],
            "c1_pct_mean": c["pct_mean"], "c1_pct_median": c["pct_median"],
            "c1_band_shares": c["band_shares"], "c1_deviations_pt": c["deviations_pt"],
            "time_a_s": ta, "time_b_s": tb, "time_c_s": tc,
        }
        rows.append(row)
        log(f"[{i+1}/15] lambda={lam} tau={tau_name}({tau_val}) "
            f"A1={a['a1_pass']} A2={a['a2_pass']} A3={a['a3_pass']} B1={b['b1_pass']} C1={c['c1_pass']} "
            f"| t=({ta:.1f}/{tb:.1f}/{tc:.1f}s)")

    return {"multi_baseline_shares": multi_shares, "multi_baseline_mean_pct": multi_mean_pct,
            "n_trials": n_trials, "seed": seed, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="小規模動作確認(n=20)")
    ap.add_argument("--sweep", action="store_true", help="本番スイープ(n=2000 x 15組)")
    ap.add_argument("--n-trials", type=int, default=2000)
    ap.add_argument("--out", default="sweep_results.json")
    args = ap.parse_args()

    if args.smoke:
        result = run_sweep(n_trials=20, seed=MASTER_SEED)
    elif args.sweep:
        result = run_sweep(n_trials=args.n_trials, seed=MASTER_SEED)
    else:
        print("--smoke または --sweep を指定してください", file=sys.stderr)
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
    print(f"結果を {args.out} に書き出しました", file=sys.stderr)


if __name__ == "__main__":
    main()

