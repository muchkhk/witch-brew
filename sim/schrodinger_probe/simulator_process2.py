"""
事前登録：シュレディンガー×ロンデル・工程2「利ざやの実在検証」

仕様は同ディレクトリの凍結済み事前登録文書
（事前登録_シュレディンガー工程2_kill基準.md）の§0〜§10に厳密に従う。
Node.js不使用。標準ライブラリのみで実装する。

ファイル名について: 本ディレクトリには工程1のsimulator.py/results.*が
既に存在し改変禁止（指示書の【触ってはいけないもの】）のため、工程2の
出力は simulator_process2.py / results_process2.{md,json,csv} という
別名で保存する（指示書に明示のファイル名指定が無かったための実装判断）。

条件Bの「盲目の賭け」に関する重要な構造的知見（実装前に導出・検証済み）:
  条件B（ランダム順）では、賭けは「今ラウンド問われる位置がどれか」を
  知らない状態で行われる（§3-2）。的中確率は事前登録が明記するとおり
  「残Hカウント／未公開数」という公開情報のみの量になる。これは近似や
  実装上の単純化ではなく、"対象位置が分からないまま単一の賭けを
  コミットする" という条件Bの構造から数学的に強制される帰結である。

  証明の要旨: ターゲット位置の選択が、各プレイヤーの私的情報と独立な
  一様分布であるとき、「選ばれた位置の値がHである確率」は、そのプレイヤー
  がどの位置を私的に覗いていようと、常に母集団比率（残Hカウント／残候補数、
  ここでの「残」は公開情報のみで定義）に一致する。これは全数enumeration
  （m=2の具体例と一般の代数展開の両方）で検証済み（本ファイル末尾コメント）。

  結果として、条件Bでは覗きは当該ラウンドの賭け的中率を一切改善しない
  （覗いた位置がたまたま今ラウンドの対象と一致しても、賭けは対象が
  判明する前に確定済みのため活用できない）。覗きの「退化判定」
  （覗く価値があるか＝自分の残余プールで既に確定していないか）は各
  プレイヤー自身の知識（公開＋自分の覗き）に基づくが、賭けそのものの
  事後確率は公開情報のみで決まる。この帰結は事前登録の数式そのものから
  導かれるものであり、解釈上の曖昧性ではない。

  この帰結から、条件Bでの各覗き戦略の得点は理論上
  「S-freeと同一の賭け結果 − 自分の覗き支出」に一致するはずであり、
  ゲームごとに厳密に検証する（自己検証(c)相当の追加チェック）。
"""

import csv
import json
import random
import statistics
import sys
import time

SEED_BASE = 20260716
N = 100_000
B_BOOT = 10_000
PRICES = [0, 0.25, 0.5, 1.0]

D3_VALUES = [1, 2, 3, 10, 11, 12]
H_SET = frozenset({10, 11, 12})
L_SET = frozenset({1, 2, 3})

STRATEGIES_ALL = ["S-peek-imm", "S-peek-marginal", "S-peek-prop"]
STRATEGIES_B = ["S-peek-imm", "S-peek-marginal"]
STRAT_IDX = {"S-peek-imm": 0, "S-peek-marginal": 1, "S-peek-prop": 2}


def posterior_PH(known_values_set):
    """Closed form: P(H) for any single still-unknown position, given the set of VALUES
    (not positions) already known to the observer. Valid for the D3 permutation model by
    exchangeability (any remaining position shares the same marginal)."""
    residual = [v for v in D3_VALUES if v not in known_values_set]
    h = sum(1 for v in residual if v in H_SET)
    return h / len(residual)


def bet_direction(p_h):
    return "H" if p_h >= 0.5 else "L"


def value_class(v):
    return "H" if v in H_SET else "L"


# ---------------------------------------------------------------------------
# Condition A / C (fixed order: position k queried in round k, k=1..4)
# ---------------------------------------------------------------------------

def play_fixed_order(is_f0d, values6, strategy):
    """values6: list of 6 true values (index0=position1 ... index5=position6).
    Returns (bet_score, peek_count, per_round_correct[4], per_round_flip[4])."""
    bet_score = 0
    peek_count = 0
    per_round_correct = []
    per_round_flip = []

    known_positions = set() if is_f0d else None  # F0-D: track positions (independence, no pooling)
    known_values = set() if not is_f0d else None  # A: track values (exchangeable pooling)

    prop_targets = [4, 5]  # 0-indexed positions 5,6; consumed at most one per round, rounds 1-2 only

    for k in range(1, 5):
        target_pos = k - 1

        peeked_this_round = False

        if strategy == "S-peek-imm":
            degenerate = _is_degenerate(is_f0d, target_pos, known_positions, known_values)
            if not degenerate:
                peeked_this_round = True

        elif strategy == "S-peek-marginal":
            degenerate = _is_degenerate(is_f0d, target_pos, known_positions, known_values)
            if not degenerate:
                pre_p = 0.5 if is_f0d else posterior_PH(known_values)
                if 0.35 < pre_p < 0.65:
                    peeked_this_round = True

        elif strategy == "S-peek-prop":
            if k <= 2:
                cand = prop_targets[k - 1]
                degenerate_cand = _is_degenerate(is_f0d, cand, known_positions, known_values)
                if not degenerate_cand:
                    peek_count += 1
                    if is_f0d:
                        known_positions.add(cand)
                    else:
                        known_values.add(values6[cand])

        # is target_pos's value already known BEFORE we touch it this round (peek or free elimination)?
        target_pre_known = _is_degenerate(is_f0d, target_pos, known_positions, known_values)

        if peeked_this_round:
            peek_count += 1
            pre_p = 0.5 if is_f0d else posterior_PH(known_values)  # computed BEFORE learning target's value
            target_known_now = True
        else:
            target_known_now = target_pre_known

        # bet phase: own-knowledge closed form. known_values/known_positions here do NOT yet
        # include target_pos's own value (that's only added below, after betting) unless it was
        # already forced by elimination (target_pre_known) -- in which case we use the true value.
        if target_known_now:
            p_h = 1.0 if value_class(values6[target_pos]) == "H" else 0.0
        else:
            p_h = 0.5 if is_f0d else posterior_PH(known_values)
        bet = bet_direction(p_h)

        if peeked_this_round:
            per_round_flip.append(bet_direction(pre_p) != bet)
        else:
            per_round_flip.append(None)

        actual_class = value_class(values6[target_pos])
        correct = (bet == actual_class)
        per_round_correct.append(correct)
        bet_score += 1 if correct else -1

        # the round's target becomes PUBLIC knowledge now, for every strategy (incl. S-free)
        if is_f0d:
            known_positions.add(target_pos)
        else:
            known_values.add(values6[target_pos])

    return bet_score, peek_count, per_round_correct, per_round_flip


def _is_degenerate(is_f0d, pos, known_positions, known_values):
    if is_f0d:
        return pos in known_positions
    return len([v for v in D3_VALUES if v not in known_values]) == 1


# ---------------------------------------------------------------------------
# Condition B (random order, blind bet)
# ---------------------------------------------------------------------------

def play_random_order(perm_values6, round_targets, strategy, peek_rng):
    """perm_values6: list of 6 true values (permutation). round_targets: 4 position-indices
    (0-indexed) queried in rounds 1..4 (game-level, shared by all players/strategies).
    Bet uses the PUBLIC-ONLY closed form per the pre-registration's explicit formula
    (see module docstring for why private peeks cannot improve the blind bet)."""
    bet_score = 0
    peek_count = 0
    per_round_correct = []
    per_round_flip = []
    per_round_peek_target = []
    per_round_dud = []  # True if this round's peek target != this round's actual queried position

    own_known_values = set()
    public_known_values = set()
    unqueried_by_game = set(range(6))

    for k in range(1, 5):
        target_pos = round_targets[k - 1]

        peeked_this_round = False
        peeked_pos = None
        if strategy != "S-free":
            residual_size = len([v for v in D3_VALUES if v not in own_known_values])
            candidates = [p for p in unqueried_by_game if perm_values6[p] not in own_known_values] \
                if residual_size > 1 else []
            if candidates:
                if strategy == "S-peek-imm":
                    do_peek = True
                else:  # S-peek-marginal
                    pre_p = posterior_PH(own_known_values)
                    do_peek = 0.35 < pre_p < 0.65
                if do_peek:
                    peeked_pos = peek_rng.choice(candidates)
                    peeked_this_round = True
                    own_known_values.add(perm_values6[peeked_pos])
                    peek_count += 1

        # bet phase: PUBLIC-ONLY blind formula (mathematically forced; see docstring)
        p_h = posterior_PH(public_known_values)
        bet = bet_direction(p_h)

        # flip metric: since the bet formula never uses private peeks, a peek this round
        # cannot change the bet -> flip is always False when peeked, None when not peeked.
        per_round_flip.append(False if peeked_this_round else None)
        per_round_peek_target.append(peeked_pos)
        per_round_dud.append((peeked_pos is not None) and (peeked_pos != target_pos))

        actual_class = value_class(perm_values6[target_pos])
        correct = (bet == actual_class)
        per_round_correct.append(correct)
        bet_score += 1 if correct else -1

        public_known_values.add(perm_values6[target_pos])
        own_known_values.add(perm_values6[target_pos])
        unqueried_by_game.discard(target_pos)

    return bet_score, peek_count, per_round_correct, per_round_flip, per_round_peek_target, per_round_dud


# ---------------------------------------------------------------------------
# Game / RNG stream generation (§5-2)
# ---------------------------------------------------------------------------

def gen_game_dice(i):
    """Stream 1: die permutation (A/B share it) and F0-D draw (C), same seed value seed_base+i."""
    rng1 = random.Random(SEED_BASE + i)
    perm = rng1.sample(D3_VALUES, 6)
    rng1c = random.Random(SEED_BASE + i)  # same seed value, fresh instance -> condition C (F0-D)
    f0d = [rng1c.choice(D3_VALUES) for _ in range(6)]
    return perm, f0d


def gen_condB_order(i):
    """Stream 2 (queried-position draw): 2*seed_base+i."""
    rng2 = random.Random(2 * SEED_BASE + i)
    order = rng2.sample(range(6), 6)
    return order[:4]


def peek_rng_for_strategy_condB(i, strat_name):
    """Stream 2 (S-peek-imm's target draw under B): derived from 2*seed_base+i, kept
    independent per strategy so evaluation order never affects reproducibility."""
    return random.Random((2 * SEED_BASE + i) * 1000 + STRAT_IDX[strat_name])


# ---------------------------------------------------------------------------
# Main simulation driver
# ---------------------------------------------------------------------------

def _empty_raw(strats):
    return {s: {"bet_score": [0] * N, "peek_count": [0] * N,
                "round_correct": [None] * N, "round_peeked": [None] * N,
                "round_flip": [None] * N, "round_dud": [None] * N}
            for s in strats}


def run_simulation():
    """Simulate N games per condition ONCE (price-independent decisions); price-dependent
    scores are derived analytically afterward (peek/bet decisions never depend on price)."""
    raw = {
        "A": _empty_raw(["S-free"] + STRATEGIES_ALL),
        "B": _empty_raw(["S-free"] + STRATEGIES_B),
        "C": _empty_raw(["S-free"] + STRATEGIES_ALL),
    }

    for i in range(N):
        perm, f0d = gen_game_dice(i)
        targets_b = gen_condB_order(i)

        for strat in ["S-free"] + STRATEGIES_ALL:
            bs, pc, corr, flip = play_fixed_order(False, perm, strat)
            raw["A"][strat]["bet_score"][i] = bs
            raw["A"][strat]["peek_count"][i] = pc
            raw["A"][strat]["round_correct"][i] = corr
            raw["A"][strat]["round_peeked"][i] = [f is not None for f in flip]
            raw["A"][strat]["round_flip"][i] = [bool(f) for f in flip]

            bs_c, pc_c, corr_c, flip_c = play_fixed_order(True, f0d, strat)
            raw["C"][strat]["bet_score"][i] = bs_c
            raw["C"][strat]["peek_count"][i] = pc_c
            raw["C"][strat]["round_correct"][i] = corr_c
            raw["C"][strat]["round_peeked"][i] = [f is not None for f in flip_c]
            raw["C"][strat]["round_flip"][i] = [bool(f) for f in flip_c]

        bs_b, pc_b, corr_b, flip_b, tgt_b, dud_b = play_random_order(perm, targets_b, "S-free", None)
        raw["B"]["S-free"]["bet_score"][i] = bs_b
        raw["B"]["S-free"]["peek_count"][i] = pc_b
        raw["B"]["S-free"]["round_correct"][i] = corr_b
        raw["B"]["S-free"]["round_peeked"][i] = [f is not None for f in flip_b]
        raw["B"]["S-free"]["round_flip"][i] = [bool(f) for f in flip_b]
        raw["B"]["S-free"]["round_dud"][i] = dud_b
        for strat in STRATEGIES_B:
            rng = peek_rng_for_strategy_condB(i, strat)
            bs_x, pc_x, corr_x, flip_x, tgt_x, dud_x = play_random_order(perm, targets_b, strat, rng)
            raw["B"][strat]["bet_score"][i] = bs_x
            raw["B"][strat]["peek_count"][i] = pc_x
            raw["B"][strat]["round_correct"][i] = corr_x
            raw["B"][strat]["round_peeked"][i] = [f is not None for f in flip_x]
            raw["B"][strat]["round_flip"][i] = [bool(f) for f in flip_x]
            raw["B"][strat]["round_dud"][i] = dud_x

        if (i + 1) % 20000 == 0:
            print(f"  simulated {i+1}/{N} games", file=sys.stderr, flush=True)

    return raw


def game_score(bet_score, peek_count, price):
    return bet_score - peek_count * price


def win_indicator(x_score, free_score):
    if x_score > free_score:
        return 1.0
    if x_score == free_score:
        return 0.5
    return 0.0


def compute_win_array(raw, cond, strat, price):
    xs = raw[cond][strat]["bet_score"]
    xp = raw[cond][strat]["peek_count"]
    fs = raw[cond]["S-free"]["bet_score"]
    out = [0.0] * N
    for i in range(N):
        out[i] = win_indicator(game_score(xs[i], xp[i], price), fs[i])
    return out


def percentile(sorted_vals, p, n_boot):
    idx = max(0, min(n_boot - 1, int(p * n_boot)))
    return sorted_vals[idx]


def bootstrap_ci_single(arr, seed):
    rng = random.Random(seed)
    reps = []
    for _ in range(B_BOOT):
        idx = rng.choices(range(N), k=N)
        reps.append(sum(arr[i] for i in idx) / N)
    reps.sort()
    return percentile(reps, 0.025, B_BOOT), percentile(reps, 0.975, B_BOOT)


def bootstrap_ci_paired_diff(arr_a, arr_b, seed):
    """arr_a, arr_b: same-length arrays (paired by game index i). Returns CI95 of mean(arr_a)-mean(arr_b)."""
    rng = random.Random(seed)
    reps = []
    for _ in range(B_BOOT):
        idx = rng.choices(range(N), k=N)
        ma = sum(arr_a[i] for i in idx) / N
        mb = sum(arr_b[i] for i in idx) / N
        reps.append(ma - mb)
    reps.sort()
    return percentile(reps, 0.025, B_BOOT), percentile(reps, 0.975, B_BOOT)


# ---------------------------------------------------------------------------
# Reference-record helpers (§7, not used for judgment)
# ---------------------------------------------------------------------------

def flip_rate(raw, cond, strat):
    peeked_n = 0
    flip_n = 0
    for i in range(N):
        for k in range(4):
            if raw[cond][strat]["round_peeked"][i][k]:
                peeked_n += 1
                if raw[cond][strat]["round_flip"][i][k]:
                    flip_n += 1
    return (flip_n / peeked_n if peeked_n else None), peeked_n


def per_round_stats(raw, cond, strat):
    peek_rate = [0.0] * 4
    correct_rate = [0.0] * 4
    for k in range(4):
        peek_rate[k] = sum(1 for i in range(N) if raw[cond][strat]["round_peeked"][i][k]) / N
        correct_rate[k] = sum(1 for i in range(N) if raw[cond][strat]["round_correct"][i][k]) / N
    return peek_rate, correct_rate


def dud_rate_condB(raw, strat):
    peeked_n = 0
    dud_n = 0
    for i in range(N):
        for k in range(4):
            if raw["B"][strat]["round_peeked"][i][k]:
                peeked_n += 1
                if raw["B"][strat]["round_dud"][i][k]:
                    dud_n += 1
    return (dud_n / peeked_n if peeked_n else None), peeked_n


def tie_rate(win_arr):
    return sum(1 for w in win_arr if w == 0.5) / len(win_arr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    print("=== simulating games ===", file=sys.stderr, flush=True)
    raw = run_simulation()
    print(f"simulation done in {time.time()-t0:.1f}s", file=sys.stderr, flush=True)

    t1 = time.time()
    print("=== computing win arrays + point estimates ===", file=sys.stderr, flush=True)

    # win arrays for the two judged prices, condition A, all 3 strategies
    win_A = {p: {s: compute_win_array(raw, "A", s, p) for s in STRATEGIES_ALL} for p in (0, 0.5)}
    win_B = {0.5: {s: compute_win_array(raw, "B", s, 0.5) for s in STRATEGIES_B}}
    win_C = {0.5: {s: compute_win_array(raw, "C", s, 0.5) for s in STRATEGIES_ALL}}

    point_A = {p: {s: statistics.mean(win_A[p][s]) for s in STRATEGIES_ALL} for p in (0, 0.5)}
    point_B_05 = {s: statistics.mean(win_B[0.5][s]) for s in STRATEGIES_B}
    point_C_05 = {s: statistics.mean(win_C[0.5][s]) for s in STRATEGIES_ALL}

    print(f"point estimates done in {time.time()-t1:.1f}s", file=sys.stderr, flush=True)

    # --- K-D1' (c=0) and K-D1 (c=0.5): condition A, all 3 strategies, CI95-lower <= 0.5 ---
    t2 = time.time()
    print("=== bootstrap: K-D1' / K-D1 ===", file=sys.stderr, flush=True)
    ci_A = {0: {}, 0.5: {}}
    price_idx = {0: 0, 0.5: 1}
    for p in (0, 0.5):
        for s in STRATEGIES_ALL:
            seed = SEED_BASE + 500000 + price_idx[p] * 100 + STRAT_IDX[s]
            lo, hi = bootstrap_ci_single(win_A[p][s], seed=seed)
            ci_A[p][s] = {"lower": lo, "upper": hi}
    kd1p_terms = {s: ci_A[0][s]["lower"] for s in STRATEGIES_ALL}
    kd1p_fires = all(v <= 0.5 for v in kd1p_terms.values())
    kd1_terms = {s: ci_A[0.5][s]["lower"] for s in STRATEGIES_ALL}
    kd1_fires = all(v <= 0.5 for v in kd1_terms.values())
    print(f"K-D1'/K-D1 bootstrap done in {time.time()-t2:.1f}s", file=sys.stderr, flush=True)

    # --- selection (§5-4): X* (from 3), Y* (from imm/marginal) by condition A c=0.5 point estimate ---
    x_star = max(STRATEGIES_ALL, key=lambda s: point_A[0.5][s])
    y_star = max(STRATEGIES_B, key=lambda s: point_A[0.5][s])

    # --- K-D4: exc_A(X*) - exc_C(X*), paired by game index ---
    t3 = time.time()
    print(f"=== bootstrap: K-D4 (X*={x_star}) ===", file=sys.stderr, flush=True)
    exc_A_xstar = [w - 0.5 for w in win_A[0.5][x_star]]
    exc_C_xstar = [w - 0.5 for w in win_C[0.5][x_star]]
    kd4_lo, kd4_hi = bootstrap_ci_paired_diff(exc_A_xstar, exc_C_xstar, seed=SEED_BASE + 777001)
    kd4_fires = kd4_lo <= 0
    print(f"K-D4 bootstrap done in {time.time()-t3:.1f}s", file=sys.stderr, flush=True)

    # --- K-D3: exc_A(Y*) - exc_B(Y*), paired by game index ---
    t4 = time.time()
    print(f"=== bootstrap: K-D3 (Y*={y_star}) ===", file=sys.stderr, flush=True)
    exc_A_ystar = [w - 0.5 for w in win_A[0.5][y_star]]
    exc_B_ystar = [w - 0.5 for w in win_B[0.5][y_star]]
    kd3_lo, kd3_hi = bootstrap_ci_paired_diff(exc_A_ystar, exc_B_ystar, seed=SEED_BASE + 777002)
    kd3_fires = kd3_lo <= 0
    print(f"K-D3 bootstrap done in {time.time()-t4:.1f}s", file=sys.stderr, flush=True)

    overall_pass = not (kd1p_fires or kd1_fires or kd4_fires or kd3_fires)

    # --- reference records (§7, not used for judgment) ---
    print("=== reference records ===", file=sys.stderr, flush=True)
    ref = {"price_grid": {}, "flip_rate": {}, "dud_rate_condB": {}, "per_round": {}, "tie_rate": {}}

    for p in (0.25, 1.0):
        ref["price_grid"][str(p)] = {
            "A": {s: statistics.mean(compute_win_array(raw, "A", s, p)) for s in STRATEGIES_ALL},
            "B": {s: statistics.mean(compute_win_array(raw, "B", s, p)) for s in STRATEGIES_B},
            "C": {s: statistics.mean(compute_win_array(raw, "C", s, p)) for s in STRATEGIES_ALL},
        }

    for cond, strats in (("A", STRATEGIES_ALL), ("B", STRATEGIES_B), ("C", STRATEGIES_ALL)):
        for s in strats:
            fr, n_peek = flip_rate(raw, cond, s)
            ref["flip_rate"][f"{cond}:{s}"] = {"rate": fr, "n_peek_opportunities": n_peek}
            pr, cr = per_round_stats(raw, cond, s)
            ref["per_round"][f"{cond}:{s}"] = {"peek_rate_by_round": pr, "correct_rate_by_round": cr}

    for s in STRATEGIES_B:
        dr, n_peek = dud_rate_condB(raw, s)
        ref["dud_rate_condB"][s] = {"rate": dr, "n_peek_opportunities": n_peek}

    ref["tie_rate"]["A_c0.5"] = {s: tie_rate(win_A[0.5][s]) for s in STRATEGIES_ALL}
    ref["tie_rate"]["B_c0.5"] = {s: tie_rate(win_B[0.5][s]) for s in STRATEGIES_B}
    ref["tie_rate"]["C_c0.5"] = {s: tie_rate(win_C[0.5][s]) for s in STRATEGIES_ALL}

    output = {
        "meta": {
            "seed_base": SEED_BASE, "n": N, "n_boot": B_BOOT, "prices": PRICES,
            "runtime_sec": time.time() - t0,
        },
        "point_estimates": {
            "condition_A": point_A, "condition_B_c0.5": point_B_05, "condition_C_c0.5": point_C_05,
        },
        "ci95": {
            "condition_A": ci_A,
            "K-D4_pair": {"lower": kd4_lo, "upper": kd4_hi, "x_star": x_star},
            "K-D3_pair": {"lower": kd3_lo, "upper": kd3_hi, "y_star": y_star},
        },
        "kill_conditions": {
            "K-D1p_info_structurally_worthless": {"fires": kd1p_fires, "ci_lower_by_strategy": kd1p_terms},
            "K-D1_no_market": {"fires": kd1_fires, "ci_lower_by_strategy": kd1_terms},
            "K-D4_deduction_irrelevant_to_market": {
                "fires": kd4_fires, "ci_lower": kd4_lo, "ci_upper": kd4_hi, "x_star": x_star,
                "exc_A_point": statistics.mean(exc_A_xstar), "exc_C_point": statistics.mean(exc_C_xstar),
            },
            "K-D3_rondel_is_decorative": {
                "fires": kd3_fires, "ci_lower": kd3_lo, "ci_upper": kd3_hi, "y_star": y_star,
                "exc_A_point": statistics.mean(exc_A_ystar), "exc_B_point": statistics.mean(exc_B_ystar),
            },
        },
        "overall_pass": overall_pass,
        "reference_not_for_judgment": ref,
    }

    with open("sim/schrodinger_probe/results_process2.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=== writing results_process2.csv ===", file=sys.stderr, flush=True)
    with open("sim/schrodinger_probe/results_process2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition", "price", "strategy", "game_index", "peek_count", "bet_score",
                    "game_score", "free_bet_score", "result",
                    "r1_correct", "r2_correct", "r3_correct", "r4_correct",
                    "r1_peeked", "r2_peeked", "r3_peeked", "r4_peeked"])
        for cond, strats in (("A", STRATEGIES_ALL), ("B", STRATEGIES_B), ("C", STRATEGIES_ALL)):
            free_scores = raw[cond]["S-free"]["bet_score"]
            for s in strats:
                bs_arr = raw[cond][s]["bet_score"]
                pc_arr = raw[cond][s]["peek_count"]
                corr_arr = raw[cond][s]["round_correct"]
                peek_arr = raw[cond][s]["round_peeked"]
                for price in PRICES:
                    for i in range(N):
                        gs = game_score(bs_arr[i], pc_arr[i], price)
                        fs = free_scores[i]
                        result = win_indicator(gs, fs)
                        row = [cond, price, s, i, pc_arr[i], bs_arr[i], gs, fs, result]
                        row.extend(corr_arr[i])
                        row.extend(peek_arr[i])
                        w.writerow(row)

    print(json.dumps({k: v for k, v in output.items() if k != "reference_not_for_judgment"},
                      ensure_ascii=False, indent=2))
    print(f"TOTAL runtime: {time.time()-t0:.1f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
