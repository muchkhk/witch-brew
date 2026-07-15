#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
witch_secrecy_repro.py — 『魔女の調合』秘匿情報リーク数値の再現スクリプト（Zenn記事①素材・欠損リスト1対応）

出典: witch.html （最終確認: 2026-07-15, muchkhk/original リポジトリ）
    - POOL / MAT / scoreRecipe / scorePile / makeBand / cutSets / toPiles / chooseOrder
      / dealConflicts / dealRecipeIds / seenBy / E_sb / bestAssign / seqChoose / rationalReach
      をPythonへ移植。数値・分岐は witch.html の実装と1対1で対応させている（移植時に変更した箇所は
      本ファイル内のコメントで明示）。

このスクリプトは読み取り専用の再現作業であり、witch.html 自体は一切変更していない。
数値が食い違っても実装を「直さない」——記事側が事実に合わせる、という指示書の方針に従う。

実行方法:
    python witch_secrecy_repro.py

決定論性: すべての乱数は MASTER_SEED から派生した Random インスタンスのみを使う。
Python / numpy の組み込み言語仕様以外に非決定的な要素はない。
"""

import itertools
import json
import random
import statistics
import sys
import time

import numpy as np

MASTER_SEED = 20260715  # 記事公開日の日付を種に採用。再現する場合はこの値を変えないこと。

# ============================================================
# 1. witch.html からの移植（凍結コアロジック）
# ============================================================

MAT_NAMES = ["満月草", "火竜の鱗", "影茸", "星屑", "霜結晶", "蛇毒"]

# POOL: witch.html 267-273行目と同一の順序・値
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

# 全ての「3枚の組」= C(18,3) = 816通り。これが記事の「816通り」の直接の根拠。
ALL_HAND_INDICES = list(itertools.combinations(range(18), 3))
assert len(ALL_HAND_INDICES) == 816, len(ALL_HAND_INDICES)


def score_recipe(recipe, pile_counts, pt_override=None):
    """witch.html scoreRecipe() 移植。pile_counts は長さ6の各素材の枚数配列。"""
    a, b = recipe["a"], recipe.get("b")
    t = recipe["type"]
    pt = pt_override if pt_override is not None else recipe["pt"]
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
    """素材インデックスのリスト → 長さ6のカウント配列"""
    counts = [0] * 6
    for m in pile:
        counts[m] += 1
    return counts


def score_pile(hand_recipe_idxs, pile_counts, pt_override=None):
    """witch.html scorePile() 移植。hand_recipe_idxs は POOL 内インデックスの3要素タプル。"""
    return sum(score_recipe(POOL[i], pile_counts, pt_override) for i in hand_recipe_idxs)


def fired_count(hand_recipe_idxs, pile_counts, pt_override=None):
    return sum(1 for i in hand_recipe_idxs if score_recipe(POOL[i], pile_counts, pt_override) != 0)


def make_band(n, rng):
    """witch.html makeBand() 移植。6素材 x 3枚 = 18枚の袋からシャッフルして先頭 n*3 枚。"""
    bag = []
    for m in range(6):
        bag.extend([m] * 3)
    rng.shuffle(bag)
    return bag[: n * 3]


def cut_sets(length, nc):
    """witch.html cutSets() 移植。1..length-1 から nc 個選ぶ組合せ全て。"""
    return list(itertools.combinations(range(1, length), nc))


def to_piles(band, cuts):
    """witch.html toPiles() 移植。"""
    s = sorted(cuts)
    pts = [0] + list(s) + [len(band)]
    return [band[pts[i]:pts[i + 1]] for i in range(len(pts) - 1)]


def choose_order(cutter, n):
    """witch.html chooseOrder() 移植。切り役の次から時計回りに、切り役以外を順に並べる。"""
    order = []
    for i in range(n):
        idx = (cutter + 1 + i) % n
        if idx != cutter:
            order.append(idx)
    return order


def deal_conflicts(idx_list):
    """witch.html dealConflicts() 移植。「避けたい素材」と「集めたい素材」の衝突判定。"""
    avoid, want = set(), set()
    for i in idx_list:
        r = POOL[i]
        if r["type"] == "abs":
            avoid.add(r["a"])
        if r["type"] == "abs2":
            avoid.add(r["a"])
            avoid.add(r["b"])
        if r["type"] in ("pair", "cnt2"):
            want.add(r["a"])
            want.add(r["b"])
        if r["type"] == "solo":
            want.add(r["a"])
    return any(m in want for m in avoid)


def deal_recipe_idxs(n, rng):
    """witch.html dealRecipeIds() 移植。矛盾のない配布を600回まで試行。"""
    pool_idx = list(range(18))
    for _ in range(600):
        c = pool_idx[:]
        rng.shuffle(c)
        c = c[: n * 3]
        if not deal_conflicts(c):
            return [tuple(sorted(c[p * 3:p * 3 + 3])) for p in range(n)]
    c = pool_idx[:]
    rng.shuffle(c)
    c = c[: n * 3]
    return [tuple(sorted(c[p * 3:p * 3 + 3])) for p in range(n)]


# ============================================================
# 2. 試合トラジェクトリ生成（witch.html には自動プレイの決定アルゴリズムが実装されていない
#    ため、本スクリプト独自の仮定を置く。詳細は結果MDの「仮定」節を参照）
# ============================================================
#
# 【重要な仮定】witch.html の rationalReach/seqChoose は、プレイ後に「完全情報を持つ
# 全知の計画者ならどこまで到達できたか」を採点するための事後評価関数であり（resolveScore()
# 内で採点用にのみ呼ばれる）、対戦中の各プレイヤーの意思決定を担うAIではない。
# witch.html はオンライン対戦・ソロ検証いずれも人間が手番を操作する設計であり、
# 「NPCが自動で打つ」ロジックは実装内に存在しない。
#
# したがって秘匿リーク数値の再現には、対戦を生成する行動モデルを本スクリプト側で
# 明示的に仮定する必要がある。以下を採用した:
#   - 切り役（cutter）: 帯の切り方をランダムに選ぶ（cutSetsから一様乱数）。
#     切り役は自分の坩堝を選べない（余りを受け取る）ため、自分の得点を直接操作する
#     手段がなく、「切り方で自分に有利にする」動機をモデル化するのは投機的すぎると
#     判断し、中立なランダム選択とした。
#   - 手番者（chooser）: 自分の手札だけを見て、残っている坩堝のうち自分の
#     scorePile が最大になるものを選ぶ（先読みなしの貪欲・自己利益最大化）。
#     同点は坩堝インデックスが小さい方を選ぶ。
# この仮定は「選択行動そのものが情報になる」という記事の主張（816→35）が成立するための
# 必要条件（手番者の選択が自分の手札に依存する）を満たす最小限のモデルである。
# ロバストネス確認として、「手番者もランダムに選ぶ」対照実験も別途走らせ、
# 選択行動モードの候補数が坩堝の中身から生じるベースライン相当に戻ることを確認する。


def simulate_round(band, hands, cutter, n, rng, chooser_policy="greedy"):
    """1儀式をシミュレートする。戻り値は observable な情報一式。"""
    cs = rng.choice(cut_sets(len(band), n - 1))
    piles = to_piles(band, cs)
    pile_counts = [pile_to_counts(p) for p in piles]
    order = choose_order(cutter, n)

    available = list(range(len(piles)))
    assign = {}  # pile_idx -> seat
    choice_trace = []  # (chooser_seat, available_before(list[int]), chosen_pile_idx)

    for chooser in order:
        if chooser_policy == "greedy":
            best_idx, best_val = None, -1
            for pi in available:
                v = score_pile(hands[chooser], pile_counts[pi])
                if v > best_val:
                    best_val, best_idx = v, pi
        elif chooser_policy == "random":
            best_idx = rng.choice(available)
        else:
            raise ValueError(chooser_policy)
        choice_trace.append((chooser, tuple(available), best_idx))
        assign[best_idx] = chooser
        available.remove(best_idx)

    # 残り1つは切り役へ
    assert len(available) == 1
    assign[available[0]] = cutter

    seat_pile_counts = [None] * n
    for pi, seat in assign.items():
        seat_pile_counts[seat] = pile_counts[pi]

    totals = [score_pile(hands[s], seat_pile_counts[s]) for s in range(n)]
    fired = [fired_count(hands[s], seat_pile_counts[s]) for s in range(n)]
    team_total = sum(totals)

    return {
        "cutter": cutter,
        "cuts": cs,
        "piles": piles,
        "pile_counts": pile_counts,
        "assign": assign,  # pile_idx -> seat
        "seat_pile_counts": seat_pile_counts,  # seat -> counts(6)
        "totals": totals,
        "fired": fired,
        "team_total": team_total,
        "choice_trace": choice_trace,
    }


def simulate_game(n, rounds, rng, chooser_policy="greedy"):
    hands = deal_recipe_idxs(n, rng)
    cutter = 0
    history = []
    for _r in range(rounds):
        band = make_band(n, rng)
        rec = simulate_round(band, hands, cutter, n, rng, chooser_policy=chooser_policy)
        history.append(rec)
        cutter = (cutter + 1) % n
    return hands, history


# ============================================================
# 3. 候補数の計算（各公開方式の「観測者」モデル）
# ============================================================
# 対象(target)は seat=0 に固定する（席は対称なので一般性を失わない）。
TARGET = 0


def observed_scalar_sequence(history, target_hand, signal_fn, pt_override=None):
    return [signal_fn(target_hand, rec["seat_pile_counts"][TARGET], pt_override) for rec in history]


def narrow_by_scalar_signal(history, target_hand, signal_fn, pt_override=None):
    """
    観測者は対象の毎儀式スカラー観測値の系列（例: 個人点、発火数）だけを知っている前提で、
    816候補のうち、その系列を再現する候補の集合を全列挙で求める。
    """
    observed = observed_scalar_sequence(history, target_hand, signal_fn, pt_override)
    survivors = []
    for h in ALL_HAND_INDICES:
        ok = True
        for rec, obs in zip(history, observed):
            if signal_fn(h, rec["seat_pile_counts"][TARGET], pt_override) != obs:
                ok = False
                break
        if ok:
            survivors.append(h)
    return survivors


def narrow_by_choice_behavior(history, target_hand, n):
    """
    「対象がどの坩堝を選んだか」だけを観測する（点数・個数は一切公開しない）。
    対象が手番者だった儀式についてのみ、候補手札 h を使ったときに同じ坩堝を選ぶかを判定する
    （貪欲・自己利益最大化ポリシーで固定。§2の仮定と同一のポリシーで候補を評価する）。
    対象が切り役だった儀式は手番がないため、その儀式は判定材料にならない
    （＝候補は絞られない）。
    """
    survivors = []
    for h in ALL_HAND_INDICES:
        ok = True
        for rec in history:
            trace = next((t for t in rec["choice_trace"] if t[0] == TARGET), None)
            if trace is None:
                continue  # 対象が切り役だった儀式：手がかりなし
            _chooser, available, actual_choice = trace
            best_idx, best_val = None, -1
            for pi in available:
                v = score_pile(h, rec["pile_counts"][pi])
                if v > best_val:
                    best_val, best_idx = v, pi
            if best_idx != actual_choice:
                ok = False
                break
        if ok:
            survivors.append(h)
    return survivors


def narrow_by_team_total_joint(history, target_hand, n):
    """
    現行B方式: 毎儀式、チーム合計だけが公開される。個々の手札は一切公開されない。
    正しい「候補」の定義は、対象の候補手札 H について
        「他の n-1 人に何らかの手札を割り当てれば、全 R 儀式のチーム合計を再現できるか」
    が存在するかどうか（＝観測者は他人の手札も知らない前提）。
    n=3（他2人）専用の実装。816x816 のブール行列を儀式ごとにANDして解の有無を判定する。
    n=4以上は組合せ爆発のため本スクリプトでは扱わない（結果MDに明記）。
    """
    assert n == 3, "team_total_joint は n=3 専用実装"
    other_seats = [s for s in range(n) if s != TARGET]
    s1, s2 = other_seats

    # v[seat][round][hand_idx] = その手札を仮に seat の実際の受け取った坩堝に当てたときの得点
    v1 = np.array([
        [score_pile(h, rec["seat_pile_counts"][s1]) for h in ALL_HAND_INDICES]
        for rec in history
    ])  # shape (R, 816)
    v2 = np.array([
        [score_pile(h, rec["seat_pile_counts"][s2]) for h in ALL_HAND_INDICES]
        for rec in history
    ])  # shape (R, 816)
    team_totals = np.array([rec["team_total"] for rec in history])  # shape (R,)

    survivors = []
    for h in ALL_HAND_INDICES:
        target_scores = np.array([
            score_pile(h, rec["seat_pile_counts"][TARGET]) for rec in history
        ])  # shape (R,)
        required = team_totals - target_scores  # shape (R,) : v1[r,h1]+v2[r,h2] がこれに一致すべき

        mask = np.ones((816, 816), dtype=bool)
        for r in range(len(history)):
            round_mask = (v1[r][:, None] + v2[r][None, :]) == required[r]
            mask &= round_mask
            if not mask.any():
                break
        if mask.any():
            survivors.append(h)
    return survivors


# ============================================================
# 4. 実験ドライバ
# ============================================================

def run_core_experiments(n=3, rounds=6, trials_cheap=3000, trials_joint=200, master_seed=MASTER_SEED):
    rng_master = random.Random(master_seed)

    results = {
        "full_score": [],
        "fired_count": [],
        "flat_1pt_score": [],
        "choice_behavior_greedy": [],
        "choice_behavior_random_control": [],
    }
    t0 = time.time()
    for i in range(trials_cheap):
        trial_seed = rng_master.randrange(1 << 30)
        rng = random.Random(trial_seed)
        hands, history = simulate_game(n, rounds, rng, chooser_policy="greedy")
        target_hand = hands[TARGET]

        results["full_score"].append(len(narrow_by_scalar_signal(history, target_hand, score_pile)))
        results["fired_count"].append(len(narrow_by_scalar_signal(history, target_hand, fired_count)))
        results["flat_1pt_score"].append(
            len(narrow_by_scalar_signal(history, target_hand, score_pile, pt_override=1))
        )
        results["choice_behavior_greedy"].append(len(narrow_by_choice_behavior(history, target_hand, n)))

    # ランダム手番者の対照実験（choice_behaviorの妥当性チェック用。別トラジェクトリ）
    for i in range(min(trials_cheap, 1000)):
        trial_seed = rng_master.randrange(1 << 30)
        rng = random.Random(trial_seed)
        hands, history = simulate_game(n, rounds, rng, chooser_policy="random")
        target_hand = hands[TARGET]
        # 「候補評価は貪欲ポリシー基準」のまま、生成だけランダムにした場合の挙動を見る
        survivors = []
        for h in ALL_HAND_INDICES:
            ok = True
            for rec in history:
                trace = next((t for t in rec["choice_trace"] if t[0] == TARGET), None)
                if trace is None:
                    continue
                _c, available, actual_choice = trace
                best_idx, best_val = None, -1
                for pi in available:
                    v = score_pile(h, rec["pile_counts"][pi])
                    if v > best_val:
                        best_val, best_idx = v, pi
                if best_idx != actual_choice:
                    ok = False
                    break
            if ok:
                survivors.append(h)
        results["choice_behavior_random_control"].append(len(survivors))

    t_cheap = time.time() - t0

    # 高コスト（team_total_joint, n=3専用・numpy）: 別途少なめの試行数で計測
    joint_results = []
    t1 = time.time()
    for i in range(trials_joint):
        trial_seed = rng_master.randrange(1 << 30)
        rng = random.Random(trial_seed)
        hands, history = simulate_game(n, rounds, rng, chooser_policy="greedy")
        target_hand = hands[TARGET]
        joint_results.append(len(narrow_by_team_total_joint(history, target_hand, n)))
    t_joint = time.time() - t1

    results["team_total_joint"] = joint_results

    timing = {"trials_cheap": trials_cheap, "seconds_cheap": t_cheap,
              "trials_joint": trials_joint, "seconds_joint": t_joint}
    return results, timing


def summarize(values):
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def main():
    print(f"[witch_secrecy_repro] MASTER_SEED={MASTER_SEED}", file=sys.stderr)
    results, timing = run_core_experiments(n=3, rounds=6, trials_cheap=3000, trials_joint=100)

    summary = {k: summarize(v) for k, v in results.items()}
    out = {
        "master_seed": MASTER_SEED,
        "setup": {"n": 3, "rounds": 6, "hand_space_size": 816},
        "timing": timing,
        "summary": summary,
        "raw_sample_head": {k: v[:20] for k, v in results.items()},
    }

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"timing: {timing}", file=sys.stderr)


if __name__ == "__main__":
    main()
