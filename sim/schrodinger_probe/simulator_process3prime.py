"""
事前登録：シュレディンガー×ロンデル 工程3'「覗き規則B・先読み覗きの経済検証」

仕様は同ディレクトリの凍結済み事前登録文書
（事前登録_シュレディンガー工程3prime_kill基準.md）の§0〜§11に厳密に従う。
Node.js不使用。標準ライブラリのみで実装する。

工程3実装(simulator_process3.py)からの流用:
  - D3_VALUES / H_SET / L_SET / posterior_PH / value_class: 完全流用
  - gen_game_dice（ダイス生成・系統1）: 完全流用
  - wilson_ci95 / percentile / bootstrap_ci_paired_diff / bootstrap_ci_single_percentile
    / ci_overlap: 完全流用（工程2由来）
  - 座席対称化の枠組み・argmax_by_point のタイブレーク方式: 流用

工程3'固有の新規実装:
  - B規則（覗きフェーズ→移動フェーズの順、§2）: 新規
  - banked（未回収覗き）の追跡・FIFO回収（S2/S3のM-seek）: 新規
  - S1（安全覗き・自己指名・全価格対応ゲート(c/2,1-c/2)）: 新規
  - S4（scout-near・最小番号覗き）: 新規
  - B4のM-deny仮想相手モデル（S2の対象規則を公開情報のみで模倣）: 新規
  - 系統4（4×seed_base+i）: M-rand専用の新規乱数系統
"""

import csv
import json
import math
import random
import statistics
import sys
import time

SEED_BASE = 20260716
N = 100_000
B_BOOT = 10_000
PRICES = [0, 0.25, 0.5, 1.0]
MAIN_PRICE = 0.5

D3_VALUES = [1, 2, 3, 10, 11, 12]
H_SET = frozenset({10, 11, 12})
L_SET = frozenset({1, 2, 3})

# ---------------------------------------------------------------------------
# 工程3から流用: 残余プール閉形式・値クラス・ダイス生成
# ---------------------------------------------------------------------------


def posterior_PH(known_values_set):
    residual = [v for v in D3_VALUES if v not in known_values_set]
    h = sum(1 for v in residual if v in H_SET)
    return h / len(residual)


def value_class(v):
    return "H" if v in H_SET else "L"


def is_degenerate(known_values_set):
    residual = [v for v in D3_VALUES if v not in known_values_set]
    if not residual:
        return True
    classes = {value_class(v) for v in residual}
    return len(classes) == 1


def gen_game_dice(i):
    rng1 = random.Random(SEED_BASE + i)
    perm = rng1.sample(D3_VALUES, 6)
    rng1c = random.Random(SEED_BASE + i)
    f0d = [rng1c.choice(D3_VALUES) for _ in range(6)]
    return perm, f0d


def move_rng_for(i, seat_flag):
    """系統4（4*seed_base+i）。M-rand専用（§1）。座席対称化の2局を独立させる。"""
    return random.Random((4 * SEED_BASE + i) * 2 + seat_flag)


# ---------------------------------------------------------------------------
# 戦略ロスター
# ---------------------------------------------------------------------------
# 情報方策: blind / safe / scout / scout-marg / scout-near
# 移動方策: M-fix / M-rand / M-value / M-seek / M-deny
ROSTER = {
    "B1": ("blind", "M-fix"),
    "B2": ("blind", "M-rand"),
    "B3": ("blind", "M-value"),
    "B4": ("blind", "M-deny"),
    "B5": ("blind", "M-deny-near"),
    "S1": ("safe", "M-self"),
    "S2": ("scout", "M-seek"),
    "S2f": ("scout", "M-fix"),
    "S3": ("scout-marg", "M-seek"),
    "S3f": ("scout-marg", "M-fix"),
    "S4": ("scout-near", "M-fix"),
}
BLIND_VARIANTS = ["B1", "B2", "B3", "B4", "B5"]
TESTED_STRATS = ["S1", "S2", "S2f", "S3", "S3f", "S4"]
SCOUT_STRATS = ["S2", "S2f", "S3", "S3f"]
MFIX_LIKE = {"B1", "B3", "S2f", "S3f", "S4"}  # M-fix系の移動をそのまま使う


class PlayerState:
    """1ゲーム中の1プレイヤーの私的状態。"""

    __slots__ = ("own_known", "banked", "peek_count", "unfired_peeks")

    def __init__(self):
        self.own_known = {}   # pos -> value（公開開示 ＋ 自分の覗き）
        self.banked = []      # [(pos, value, peeked_round)]（覗き済み・未問のFIFO順）
        self.peek_count = 0
        self.unfired_peeks = 0  # ゲーム終了時にbankedへ残った覗き数


def eligible_peek_candidates(state, asked_set, true_values):
    """未公開（未実施）かつ自分が未覗きの位置一覧（昇順）。"""
    banked_pos = {p for p, _, _ in state.banked}
    return [p for p in range(1, 7)
            if p not in asked_set and p not in banked_pos]


def do_peek(state, target_pos, true_values, round_idx):
    v = true_values[target_pos - 1]
    state.own_known[target_pos] = v
    state.banked.append((target_pos, v, round_idx))
    state.peek_count += 1


def recall_fifo(state):
    """bankedの先入先出。存在すれば (pos, value) を返し、bankedから除く。"""
    if not state.banked:
        return None
    item = state.banked.pop(0)
    return item[0], item[1]


def bet_for_position(state, pos, public_known):
    """当該位置の賭け方向。既知なら確定、非既知なら残余プール事後。"""
    known = dict(public_known)
    known.update(state.own_known)
    if pos in known:
        p_h = 1.0 if value_class(known[pos]) == "H" else 0.0
    else:
        p_h = posterior_PH(set(known.values()))
    direction = "H" if p_h >= 0.5 else "L"
    return direction, p_h


def marginal_ph(state, public_known):
    """交換可能性により、未知位置すべてに共通の周辺事後P(H)（§3）。"""
    known = dict(public_known)
    known.update(state.own_known)
    return posterior_PH(set(known.values()))


# ---------------------------------------------------------------------------
# 移動フェーズ（B4の仮想相手モデルは公開情報のみで決定論的に判定・D-8の前例）
# ---------------------------------------------------------------------------


def _virtual_deny_targets(asked_order, all_public_known_by_round, k, target_fn):
    """B4/B5共通の枠組み: 仮想相手の覗き対象規則(target_fn=max/min)だけを差し替えて
    公開情報のみの仮想覗き履歴をラウンド1から決定論的に構成し、まだ未実施の位置
    のうち「相手が覗いたはず」の集合を返す。"""
    asked_set = set()
    virtual_known = {}
    virtual_banked = []
    for r in range(1, k):
        pub_known_before_r = all_public_known_by_round[r - 1]
        known_now = dict(pub_known_before_r)
        known_now.update(virtual_known)
        if not is_degenerate(set(known_now.values())):
            banked_pos = {p for p, _ in virtual_banked}
            candidates = [p for p in range(1, 7)
                          if p not in asked_set and p not in banked_pos]
            if candidates:
                target = target_fn(candidates)
                # 値は公開情報だけからは分からないため、危険集合の構成にのみ使う
                virtual_banked.append((target, None))
                virtual_known[target] = None
        asked_set.add(asked_order[r - 1])
        virtual_banked = [(p, v) for (p, v) in virtual_banked if p != asked_order[r - 1]]
        virtual_known.pop(asked_order[r - 1], None)
    return {p for p, _ in virtual_banked}


def virtual_scout_deny_targets(asked_order, all_public_known_by_round, k):
    """B4: 相手をS2（情報方策scout・最大番号覗き）と仮定した仮想モデル。"""
    return _virtual_deny_targets(asked_order, all_public_known_by_round, k, max)


def virtual_scout_near_deny_targets(asked_order, all_public_known_by_round, k):
    """B5(v0.3新設): 相手をS4（情報方策scout-near・最小番号覗き）と仮定した
    仮想モデル。B4の枠組みを流用し、対象規則のみ最小番号に置換する。"""
    return _virtual_deny_targets(asked_order, all_public_known_by_round, k, min)


def choose_move(name, state, asked_order, asked_set, public_known,
                 all_public_known_by_round, k, rng, controller_state):
    remaining = [p for p in range(1, 7) if p not in asked_set]
    move_policy = ROSTER[name][1]

    if name == "S1":
        # 自己指名 or 最小番号（peek_phaseで既に決定済みのbanked先頭を使う）
        if state.banked:
            return state.banked[0][0]
        return min(remaining)

    if move_policy == "M-fix":
        return min(remaining)

    if move_policy == "M-rand":
        return rng.choice(remaining)

    if move_policy == "M-value":
        # blind系: 公開事後は全候補で同一（§3）→ argmax同値・タイブレーク最小番号
        # (B3の恒等をそのまま実装する。K-F0(d)の検品対象)
        ph = marginal_ph(state, public_known)
        scores = [(abs(ph - 0.5), -p) for p in remaining]
        best = max(scores)
        return -best[1]

    if move_policy == "M-seek":
        if state.banked:
            return state.banked[0][0]
        return min(remaining)

    if move_policy == "M-deny":
        denied = virtual_scout_deny_targets(asked_order, all_public_known_by_round, k)
        candidates = [p for p in remaining if p not in denied]
        if not candidates:
            candidates = remaining
        return min(candidates)

    if move_policy == "M-deny-near":
        denied = virtual_scout_near_deny_targets(asked_order, all_public_known_by_round, k)
        candidates = [p for p in remaining if p not in denied]
        if not candidates:
            candidates = remaining
        return min(candidates)

    raise ValueError(f"unknown move policy for {name}")


def play_single_game(name_a, name_b, true_values, a_controls_first, move_rng, price=MAIN_PRICE):
    """B規則1ゲーム。§2の4フェーズを4ラウンド実行する。
    戻り値: dict(score_a, score_b, peek_count_a, peek_count_b,
                 unfired_a, unfired_b, asked_order)
    """
    state_a, state_b = PlayerState(), PlayerState()
    public_known = {}
    asked_order = []
    asked_set = set()
    all_public_known_by_round = [dict(public_known)]
    score_a = 0.0
    score_b = 0.0

    control_seq = ["A", "B", "A", "B"] if a_controls_first else ["B", "A", "B", "A"]

    for k in range(1, 5):
        controller = control_seq[k - 1]

        for pname, state, is_ctrl in (
            (name_a, state_a, controller == "A"),
            (name_b, state_b, controller == "B"),
        ):
            info_policy = ROSTER[pname][0]
            if info_policy == "blind":
                continue
            known_now = dict(public_known)
            known_now.update(state.own_known)
            if is_degenerate(set(known_now.values())):
                continue
            if info_policy == "safe" and not is_ctrl:
                continue
            do_peek_flag = False
            target = None
            if info_policy == "safe":
                ph = marginal_ph(state, public_known)
                lo, hi = price / 2.0, 1.0 - price / 2.0
                candidates = eligible_peek_candidates(state, asked_set, true_values)
                if candidates and (lo < ph < hi):
                    do_peek_flag = True
                    target = max(candidates)
            elif info_policy == "scout":
                candidates = eligible_peek_candidates(state, asked_set, true_values)
                if candidates:
                    do_peek_flag = True
                    target = max(candidates)
            elif info_policy == "scout-marg":
                ph = marginal_ph(state, public_known)
                candidates = eligible_peek_candidates(state, asked_set, true_values)
                if candidates and (0.35 < ph < 0.65):
                    do_peek_flag = True
                    target = max(candidates)
            elif info_policy == "scout-near":
                candidates = eligible_peek_candidates(state, asked_set, true_values)
                if candidates:
                    do_peek_flag = True
                    target = min(candidates)
            if do_peek_flag:
                do_peek(state, target, true_values, k)

        for pname, state, is_ctrl, seat in (
            (name_a, state_a, controller == "A", "A"),
            (name_b, state_b, controller == "B", "B"),
        ):
            if not is_ctrl:
                continue
            queried = choose_move(pname, state, asked_order, asked_set, public_known,
                                   all_public_known_by_round, k, move_rng, None)

        dir_a, _ = bet_for_position(state_a, queried, public_known)
        dir_b, _ = bet_for_position(state_b, queried, public_known)

        true_v = true_values[queried - 1]
        true_dir = value_class(true_v)

        round_score_a = 1.0 if dir_a == true_dir else -1.0
        round_score_b = 1.0 if dir_b == true_dir else -1.0
        score_a += round_score_a
        score_b += round_score_b

        public_known[queried] = true_v
        asked_set.add(queried)
        asked_order.append(queried)
        all_public_known_by_round.append(dict(public_known))

        for state in (state_a, state_b):
            state.banked = [(p, v, r) for (p, v, r) in state.banked if p != queried]
            state.own_known[queried] = true_v

    score_a -= state_a.peek_count * price
    score_b -= state_b.peek_count * price
    unfired_a = len(state_a.banked)
    unfired_b = len(state_b.banked)

    return {
        "score_a": score_a, "score_b": score_b,
        "peek_count_a": state_a.peek_count, "peek_count_b": state_b.peek_count,
        "unfired_a": unfired_a, "unfired_b": unfired_b,
        "asked_order": list(asked_order),
    }


# ---------------------------------------------------------------------------
# K-F0(a): A規則再現（工程3のM-fix対角セルを、本モジュール内で独立に再実装し、
# results_process3.jsonとの回帰一致を確認する。§7 K-F0(a)）
#
# 工程3のimm/marginal/prop情報方策・固定順M-fix・A規則（移動→覗き→賭け→開示）を
# 本モジュール内で独立に再実装する（simulator_process3.pyをインポートして流用せず、
# 別実装で一致すること自体を回帰検証とする）。位置は1-indexed（本モジュールの規約）。
# ---------------------------------------------------------------------------

def play_game_a_rule(info_a, info_b, true_values, is_f0d=False):
    """A規則1ゲーム（工程3のM-fix固定順・imm/marginal/prop）。
    移動は固定順（ラウンドk→位置k）。戻り値: dict(score_a, score_b, peek_count_a, peek_count_b)。
    """
    own_known_a, own_known_b = {}, {}
    peek_count_a = peek_count_b = 0
    public_known = {}
    score_a = score_b = 0.0

    def ph_for(own_known, pos):
        if pos in own_known:
            return 1.0 if value_class(own_known[pos]) == "H" else 0.0
        if is_f0d:
            return 0.5
        known = dict(public_known)
        known.update(own_known)
        return posterior_PH(set(known.values()))

    def eligible(own_known, unqueried_set, pos):
        if pos not in unqueried_set or pos in own_known:
            return False
        if is_f0d:
            return True
        known = dict(public_known)
        known.update(own_known)
        return (6 - len(known)) > 1

    for k in range(1, 5):
        queried = k  # 固定順（D-6）: ラウンドkで位置k
        unqueried_set = {p for p in range(1, 7) if p not in public_known}

        for info_policy, own_known in ((info_a, own_known_a), (info_b, own_known_b)):
            if info_policy == "blind":
                continue
            if info_policy in ("imm", "marginal"):
                if eligible(own_known, unqueried_set, queried):
                    do_it = True
                    if info_policy == "marginal":
                        pre_p = ph_for(own_known, queried)
                        do_it = 0.35 < pre_p < 0.65
                    if do_it:
                        own_known[queried] = true_values[queried - 1]
                        if own_known is own_known_a:
                            peek_count_a += 1
                        else:
                            peek_count_b += 1
            elif info_policy == "prop":
                schedule = [5, 6]
                if k <= 2:
                    cand = schedule[k - 1]
                    if eligible(own_known, unqueried_set, cand):
                        own_known[cand] = true_values[cand - 1]
                        if own_known is own_known_a:
                            peek_count_a += 1
                        else:
                            peek_count_b += 1
            else:
                raise ValueError(info_policy)

        p_a = ph_for(own_known_a, queried)
        p_b = ph_for(own_known_b, queried)
        dir_a = "H" if p_a >= 0.5 else "L"
        dir_b = "H" if p_b >= 0.5 else "L"

        true_v = true_values[queried - 1]
        true_dir = value_class(true_v)
        score_a += 1.0 if dir_a == true_dir else -1.0
        score_b += 1.0 if dir_b == true_dir else -1.0

        public_known[queried] = true_v
        own_known_a[queried] = true_v
        own_known_b[queried] = true_v

    return {
        "score_a": score_a, "score_b": score_b,
        "peek_count_a": peek_count_a, "peek_count_b": peek_count_b,
    }


def simulate_matchup_a_rule(info_a, is_f0d=False, n=None):
    """info_a vs blind(info='blind') のN局。工程3のsimulate_matchupと同じ
    seed_base+iダイス生成・座席対称化2局を用いる。"""
    n = n or N
    data = {k: [0.0] * n for k in
            ("g1_bs_p", "g1_pc_p", "g1_bs_b", "g1_pc_b",
             "g2_bs_p", "g2_pc_p", "g2_bs_b", "g2_pc_b")}
    for i in range(n):
        perm, f0d = gen_game_dice(i)
        true_values = f0d if is_f0d else perm
        g1 = play_game_a_rule(info_a, "blind", true_values, is_f0d=is_f0d)
        g2 = play_game_a_rule("blind", info_a, true_values, is_f0d=is_f0d)
        data["g1_bs_p"][i] = g1["score_a"]; data["g1_pc_p"][i] = g1["peek_count_a"]
        data["g1_bs_b"][i] = g1["score_b"]; data["g1_pc_b"][i] = g1["peek_count_b"]
        data["g2_bs_p"][i] = g2["score_b"]; data["g2_pc_p"][i] = g2["peek_count_b"]
        data["g2_bs_b"][i] = g2["score_a"]; data["g2_pc_b"][i] = g2["peek_count_a"]
    return data


def compute_win_array_a_rule(data, price, n=None):
    n = n or len(data["g1_bs_p"])
    out = [0.0] * n
    for i in range(n):
        s_p1 = data["g1_bs_p"][i] - data["g1_pc_p"][i] * price
        s_b1 = data["g1_bs_b"][i] - data["g1_pc_b"][i] * price
        s_p2 = data["g2_bs_p"][i] - data["g2_pc_p"][i] * price
        s_b2 = data["g2_bs_b"][i] - data["g2_pc_b"][i] * price
        w1 = 1.0 if s_p1 > s_b1 else (0.5 if s_p1 == s_b1 else 0.0)
        w2 = 1.0 if s_p2 > s_b2 else (0.5 if s_p2 == s_b2 else 0.0)
        out[i] = (w1 + w2) / 2.0
    return out


# ---------------------------------------------------------------------------
# 統計関数（工程3 simulator_process3.pyから流用: Wilson score interval・
# パーセンタイル法ブートストラップ・CI重なり判定）
# ---------------------------------------------------------------------------

Z_95 = 1.959963984540054


def wilson_ci95(p_hat, n):
    z = Z_95
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    return center - margin, center + margin


def percentile(sorted_vals, p, n_boot):
    idx = max(0, min(n_boot - 1, int(p * n_boot)))
    return sorted_vals[idx]


def bootstrap_ci_paired_diff(arr_a, arr_b, seed, n_boot=B_BOOT):
    n = len(arr_a)
    rng = random.Random(seed)
    reps = []
    for _ in range(n_boot):
        idx = rng.choices(range(n), k=n)
        ma = sum(arr_a[i] for i in idx) / n
        mb = sum(arr_b[i] for i in idx) / n
        reps.append(ma - mb)
    reps.sort()
    return percentile(reps, 0.025, n_boot), percentile(reps, 0.975, n_boot)


def bootstrap_ci_single_percentile(arr, seed, n_boot=B_BOOT):
    n = len(arr)
    rng = random.Random(seed)
    reps = []
    for _ in range(n_boot):
        idx = rng.choices(range(n), k=n)
        reps.append(sum(arr[i] for i in idx) / n)
    reps.sort()
    return percentile(reps, 0.025, n_boot), percentile(reps, 0.975, n_boot)


def ci_overlap(lo1, hi1, lo2, hi2):
    return lo1 <= hi2 and lo2 <= hi1


def hash_stable(name):
    return sum((i + 1) * ord(c) for i, c in enumerate(name)) % 100000
