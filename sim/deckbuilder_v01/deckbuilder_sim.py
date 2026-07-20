#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deckbuilder_sim.py ― 新作デッキ構築ゲーム チャーン支配検証シミュレータ

指示書「新作デッキ構築ゲーム チャーン支配検証シミュレーション」の実装。
- 3人対戦・各10手番（ラウンド制）
- 固定8枚デッキ・使用後に「継続 or 引退」選択
- 5戦略（S1〜S5）・共通の貪欲盤面評価
- V1（成長各2枚=16）/ V2（各3枚=24）

環境注記: このPCに Node.js は無い（CLAUDE.md §9-f）。指示書は Node.js と書くが Python で実装。

使い方:
    python deckbuilder_sim.py --variant v1 --games 300 --out results_v1.json --jobs 8
    python deckbuilder_sim.py --trace 12345          # 1ゲームの全手番トレース
    python deckbuilder_sim.py --selftest             # 盤面採点などの自己検査

再現性: 乱数は各ゲームの座標 (variant, combo_idx, game_idx) から決定的に導出。
        戦略判断は完全決定的（乱数はデッキ/供給山シャッフルのみ）。集計は加算のみ。
"""

import sys
import json
import argparse
import random
import itertools
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# カード定義（指示書 §2）
# ─────────────────────────────────────────────────────────────
APPRENTICE = "見習い"
EXPERT     = "専門家"
PIONEER    = "開拓者"
COORDINATOR= "調整役"
VETERAN    = "古参"
MASTER     = "親方"
CHALLENGER = "挑戦者"
LIAISON    = "連携役"
STRATEGIST = "戦略家"
FOLLOWER   = "追随者"
MEDIATOR   = "調停者"
VIRTUOSO   = "名手"
ELDER      = "長老"

# 固定カード順（使用カード選択の同増分タイ break に使う・報告 §5）
CARD_ORDER = [APPRENTICE, EXPERT, PIONEER, COORDINATOR, VETERAN,
              MASTER, CHALLENGER, LIAISON, STRATEGIST, FOLLOWER,
              MEDIATOR, VIRTUOSO, ELDER]
CARD_RANK = {c: i for i, c in enumerate(CARD_ORDER)}

RETIRE_PTS = {
    APPRENTICE: 0, EXPERT: 1, PIONEER: 1, COORDINATOR: 1, VETERAN: 2,
    MASTER: 1, CHALLENGER: 2, LIAISON: 2, STRATEGIST: 2, FOLLOWER: 3,
    MEDIATOR: 3, VIRTUOSO: 2, ELDER: 3,
}

GROWTH_CARDS = [MASTER, CHALLENGER, LIAISON, STRATEGIST, FOLLOWER, MEDIATOR, VIRTUOSO, ELDER]

def initial_deck():
    return [APPRENTICE, APPRENTICE, APPRENTICE, EXPERT, EXPERT, PIONEER, COORDINATOR, VETERAN]

BASE_POINTS = (5, 3, 1)   # 1位/2位/3位

# ─────────────────────────────────────────────────────────────
# 盤面採点（§3-1 タイ処理: 同順位は該当順位以下を合算し floor 均等分配）
# ─────────────────────────────────────────────────────────────
_AREA_CACHE = {}

def area_points(counts):
    """counts=(c0,c1,c2) の領域で各プレイヤーが得る点 (p0,p1,p2)。0影響は順位対象外。"""
    v = _AREA_CACHE.get(counts)
    if v is not None:
        return v
    ranked = [i for i in range(3) if counts[i] > 0]
    ranked.sort(key=lambda i: -counts[i])
    pts = [0, 0, 0]
    pos = 0
    i = 0
    n = len(ranked)
    while i < n:
        j = i
        while j < n and counts[ranked[j]] == counts[ranked[i]]:
            j += 1
        group = ranked[i:j]
        pool = sum(BASE_POINTS[pos:pos + len(group)])
        share = pool // len(group)
        for pl in group:
            pts[pl] = share
        pos += len(group)
        i = j
    res = (pts[0], pts[1], pts[2])
    _AREA_CACHE[counts] = res
    return res

def my_points(inf, me):
    """現盤面で me が得る盤面点合計（3領域）。"""
    return (area_points((inf[0][0], inf[0][1], inf[0][2]))[me]
            + area_points((inf[1][0], inf[1][1], inf[1][2]))[me]
            + area_points((inf[2][0], inf[2][1], inf[2][2]))[me])

def score_delta(inf, me, delta, before):
    """me の各領域に delta を一時適用して増分を測り、必ず元に戻す。"""
    inf[0][me] += delta[0]; inf[1][me] += delta[1]; inf[2][me] += delta[2]
    v = my_points(inf, me) - before
    inf[0][me] -= delta[0]; inf[1][me] -= delta[1]; inf[2][me] -= delta[2]
    return v

def sole_first(inf, a, me):
    """me が領域 a で単独1位か（正の影響を持ち、他全員より厳密に多い）。"""
    mc = inf[a][me]
    if mc <= 0:
        return False
    for p in range(3):
        if p != me and inf[a][p] >= mc:
            return False
    return True

# ─────────────────────────────────────────────────────────────
# カード効果の解決（§5 貪欲評価・A→B→C タイ break・救済は「好きな領域に1個」）
#   返り値: (increment, delta(list3), met_condition, placed_areas(set))
#   delta は me の各領域への純増減（移動は src-,dst+ で表現）。inf は変更しない。
# ─────────────────────────────────────────────────────────────
def _best_place(inf, me, k, cands, before):
    """cands の中から +k を1領域に置く最良（増分最大, A→B→C タイ break）。"""
    best_inc = None
    best_a = cands[0]
    for a in cands:            # cands は昇順（A→B→C）で渡す
        d = (k if a == 0 else 0, k if a == 1 else 0, k if a == 2 else 0)
        inc = score_delta(inf, me, d, before)
        if best_inc is None or inc > best_inc:
            best_inc = inc
            best_a = a
    d = [0, 0, 0]; d[best_a] = k
    return best_inc, d, best_a

def resolve(card, inf, me):
    before = my_points(inf, me)
    A = (0, 1, 2)

    if card == APPRENTICE:
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, True, {a}

    if card == EXPERT:
        cands = [a for a in A if inf[a][me] > 0]
        if cands:
            inc, d, a = _best_place(inf, me, 2, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == PIONEER:
        cands = [a for a in A if inf[a][me] == 0]
        if cands:
            inc, d, a = _best_place(inf, me, 2, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == VETERAN:
        cands = [a for a in A if not sole_first(inf, a, me)]
        if cands:
            inc, d, a = _best_place(inf, me, 2, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == MASTER:
        cands = [a for a in A if inf[a][me] > 0]
        if cands:
            inc, d, a = _best_place(inf, me, 3, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == CHALLENGER:
        cands = [a for a in A if any(inf[a][p] > inf[a][me] for p in range(3) if p != me)]
        if cands:
            inc, d, a = _best_place(inf, me, 3, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == FOLLOWER:
        cands = [a for a in A if inf[a][me] == min(inf[a][0], inf[a][1], inf[a][2])]
        if cands:
            inc, d, a = _best_place(inf, me, 3, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == MEDIATOR:
        cands = []
        for a in A:
            cs = sorted((inf[a][0], inf[a][1], inf[a][2]), reverse=True)
            if cs[0] - cs[1] <= 2:
                cands.append(a)
        if cands:
            inc, d, a = _best_place(inf, me, 2, cands, before)
            return inc, d, True, {a}
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == LIAISON:
        # 異なる2領域に1個ずつ（全ペアから合計増分最大）
        best_inc = None; best_pair = (0, 1)
        for a, b in ((0, 1), (0, 2), (1, 2)):
            d = [0, 0, 0]; d[a] = 1; d[b] = 1
            inc = score_delta(inf, me, d, before)
            if best_inc is None or inc > best_inc:
                best_inc = inc; best_pair = (a, b)
        d = [0, 0, 0]; d[best_pair[0]] = 1; d[best_pair[1]] = 1
        return best_inc, d, True, {best_pair[0], best_pair[1]}

    if card == VIRTUOSO:
        # 2個置き→単独1位化したら別領域に+1
        best_inc = None; best_delta = None; best_areas = None
        for a in A:
            d = [0, 0, 0]; d[a] = 2
            inf[a][me] += 2
            solo = sole_first(inf, a, me)
            if solo:
                others = [x for x in A if x != a]
                sub_before = my_points(inf, me)
                bi = None; bb = others[0]
                for b in others:
                    dd = (1 if b == 0 else 0, 1 if b == 1 else 0, 1 if b == 2 else 0)
                    v = score_delta(inf, me, dd, sub_before)
                    if bi is None or v > bi:
                        bi = v; bb = b
                inf[a][me] -= 2
                dd = [0, 0, 0]; dd[a] = 2; dd[bb] = 1
                inc = score_delta(inf, me, dd, before)
                areas = {a, bb}
                cand = (inc, dd, areas)
            else:
                inf[a][me] -= 2
                inc = score_delta(inf, me, d, before)
                cand = (inc, d, {a})
            if best_inc is None or cand[0] > best_inc:
                best_inc = cand[0]; best_delta = cand[1]; best_areas = cand[2]
        return best_inc, list(best_delta), True, best_areas

    if card == ELDER:
        cands = [a for a in A if sole_first(inf, a, me)]
        if cands:
            d = [0, 0, 0]
            for a in cands:
                d[a] = 1          # 各単独1位領域に+1（最大3）
            inc = score_delta(inf, me, d, before)
            return inc, d, True, set(cands)
        inc, d, a = _best_place(inf, me, 1, A, before)
        return inc, d, False, {a}

    if card == COORDINATOR:
        sources = [a for a in A if inf[a][me] > 0]
        if not sources:
            inc, d, a = _best_place(inf, me, 1, A, before)
            return inc, d, False, {a}
        best_inc = None; best_delta = None; best_areas = None
        for src in sources:
            for dst in A:
                if dst == src:
                    continue
                d = [0, 0, 0]; d[src] -= 1; d[dst] += 2   # 移動1(src-1,dst+1)+さらに1(dst+1)
                inc = score_delta(inf, me, d, before)
                if best_inc is None or inc > best_inc:
                    best_inc = inc; best_delta = d; best_areas = {dst}
        return best_inc, best_delta, True, best_areas

    if card == STRATEGIST:
        # 影響を合計2個まで自由移動→その後好きな領域に+1
        base = (inf[0][me], inf[1][me], inf[2][me])
        move_deltas = {(0, 0, 0)}
        for src in A:
            if base[src] >= 1:
                for dst in A:
                    if dst == src:
                        continue
                    md = [0, 0, 0]; md[src] -= 1; md[dst] += 1
                    move_deltas.add(tuple(md))
                    st = (base[0] + md[0], base[1] + md[1], base[2] + md[2])
                    for s2 in A:
                        if st[s2] >= 1:
                            for d2 in A:
                                if d2 == s2:
                                    continue
                                md2 = list(md); md2[s2] -= 1; md2[d2] += 1
                                move_deltas.add(tuple(md2))
        best_inc = None; best_delta = None; best_areas = None
        for md in move_deltas:
            for a in A:
                d = [md[0], md[1], md[2]]; d[a] += 1
                inc = score_delta(inf, me, d, before)
                if best_inc is None or inc > best_inc:
                    best_inc = inc; best_delta = d
                    best_areas = {i for i in A if d[i] > 0}
        return best_inc, best_delta, True, best_areas

    raise ValueError("unknown card: %r" % card)


# ─────────────────────────────────────────────────────────────
# 戦略（§4）。差は「使用カード選択」と「継続/引退判断」のみ。
# 返り値の決定は Game.play_turn 内で使う。
# ─────────────────────────────────────────────────────────────
S3_PRIORITY = (0, 1)                 # 相乗温存の優先2領域（A,B・決定的）
S3_KEEP_SET = {EXPERT, MASTER, ELDER}  # 「優勢を伸ばす」継続対象（報告 §5）

def eval_hand(inf, me, hand):
    """手札各カードの (increment, delta, met, areas) を返す（順序=hand）。"""
    return [resolve(c, inf, me) for c in hand]

def pick_max_board(hand, evals):
    """盤面増分最大のカード index（同増分は CARD_ORDER 昇順で決定的）。"""
    best_i = 0
    best_key = None
    for i, c in enumerate(hand):
        key = (evals[i][0], -CARD_RANK[c])   # 増分大 > 、次に CARD_ORDER 昇順
        if best_key is None or key > best_key:
            best_key = key; best_i = i
    return best_i


# ─────────────────────────────────────────────────────────────
# ゲーム本体
# ─────────────────────────────────────────────────────────────
TURNS = 10
HAND_SIZE = 3
MARKET_SIZE = 5

class Rec:
    """1ワークユニット（1 variant×combo）ぶんの集計。加算のみ。"""
    def __init__(self):
        z = lambda: [0]*(TURNS+1)
        self.strat = defaultdict(lambda: {'inst':0,'score':0.0,'board':0,'retire':0,'win':0.0,'retires':0})
        self.retire_turn = defaultdict(z)                 # sid -> [turn]
        self.retire_card = defaultdict(lambda: defaultdict(int))
        self.market_take = defaultdict(lambda: defaultdict(int))
        # S5 スラック（手番4〜7で集計、全手番も参考に保持）
        self.s5_keep = z(); self.s5_total = z(); self.s5_close = z(); self.s5_forced = z()
        self.s5_diffhist = defaultdict(int)               # 0.5刻みのビン
        self.games = 0
        self.deplete_games = 0
        self.deplete_turn_sum = 0


class Game:
    def __init__(self, strategies, variant_growth_copies, rng, rec, trace=False):
        self.strat = strategies              # [sid, sid, sid] by seat
        self.rng = rng
        self.rec = rec
        self.trace = trace
        self.inf = [[0,0,0],[0,0,0],[0,0,0]]      # inf[area][player]
        self.deck = [initial_deck() for _ in range(3)]
        self.hand = [[] for _ in range(3)]
        self.discard = [[] for _ in range(3)]
        self.retire_total = [0,0,0]
        # 市場（共有）
        supply = []
        for c in GROWTH_CARDS:
            supply += [c]*variant_growth_copies
        rng.shuffle(supply)
        self.supply = supply
        self.market = []
        for _ in range(MARKET_SIZE):
            if self.supply:
                self.market.append(self.supply.pop())
        self.market_emptied_turn = None
        # 初期手札
        for p in range(3):
            rng.shuffle(self.deck[p])
            self._draw_to_three(p)

    def _draw_to_three(self, p):
        h = self.hand[p]; d = self.deck[p]
        while len(h) < HAND_SIZE:
            if not d:
                if not self.discard[p]:
                    break
                d = self.discard[p]; self.discard[p] = []
                self.rng.shuffle(d); self.deck[p] = d
            h.append(d.pop())

    def _refill_market(self):
        while len(self.market) < MARKET_SIZE and self.supply:
            self.market.append(self.supply.pop())

    # 市場最良カード: 「引退点＋盤面価値」最大（S1用） or 貪欲価値最大（汎用）
    def _best_market(self, me, mode="churn"):
        if not self.market:
            return None
        before = my_points(self.inf, me)
        best_i = 0; best_v = None
        for i, c in enumerate(self.market):
            inc, _, _, _ = resolve(c, self.inf, me)
            if mode == "churn":
                v = RETIRE_PTS[c] + inc
            else:                              # S5: 将来盤面寄与 = 貪欲増分
                v = inc
            key = (v, -CARD_RANK[c])
            if best_v is None or key > best_v:
                best_v = key; best_i = i
        return best_i

    def _expected_uses(self, per_use_value, deck_cards, R):
        """S5 期待残り使用回数の近似（報告 §報告2）:
           R × min(1, (3/D) × v_card/avg_v_deck)。R=残り手番, D=デッキ枚数。"""
        D = len(deck_cards)
        if D == 0 or R <= 0:
            return 0.0
        before = my_points(self.inf, self.cur)
        tot = 0.0
        for c in deck_cards:
            inc, _, _, _ = resolve(c, self.inf, self.cur)
            tot += inc
        avg_v = tot / D
        ratio = (per_use_value / avg_v) if avg_v > 0 else 1.0
        factor = (3.0 / D) * ratio
        if factor > 1.0:
            factor = 1.0
        if factor < 0.0:
            factor = 0.0
        return R * factor

    def play_turn(self, p, turn):
        self.cur = p
        sid = self.strat[p]
        hand = self.hand[p]
        inf = self.inf
        evals = eval_hand(inf, p, hand)

        # ── 使用カード選択 ──
        if sid == "S2":
            play_i = self._s2_pick(hand, evals)
        elif sid == "S3":
            play_i = self._s3_pick(hand, evals)
        elif sid == "S4":
            play_i = self._s4_pick(hand, evals)
        else:
            play_i = pick_max_board(hand, evals)   # S1/S5

        card = hand[play_i]
        inc, delta, met, areas = evals[play_i]
        # 効果適用
        inf[0][p] += delta[0]; inf[1][p] += delta[1]; inf[2][p] += delta[2]

        # ── 継続/引退判断 ──
        can_retire = len(self.market) > 0
        retire, market_pick = self._decide(sid, p, turn, card, inc, delta, met, areas,
                                           hand, evals, play_i, can_retire)

        # 使用カードを手札から外す
        hand.pop(play_i)

        if retire and can_retire:
            # 引退点即時得点（効果解決後・§3-4）
            self.retire_total[p] += RETIRE_PTS[card]
            # 市場から1枚取得→捨札
            mi = market_pick if market_pick is not None else self._best_market(p, "churn")
            taken = self.market.pop(mi)
            self.discard[p].append(taken)
            self._refill_market()
            # 集計
            self.rec.strat[sid]['retires'] += 1
            self.rec.retire_turn[sid][turn] += 1
            self.rec.retire_card[sid][card] += 1
            self.rec.market_take[sid][taken] += 1
            action = "RETIRE(+%d, take %s)" % (RETIRE_PTS[card], taken)
        else:
            # 継続: 使用カード→捨札
            self.discard[p].append(card)
            action = "keep"

        # 市場枯渇（供給山も空で市場も空）の記録
        if not self.market and not self.supply and self.market_emptied_turn is None:
            self.market_emptied_turn = turn

        # 未使用手札→捨札、3枚に補充
        self.discard[p].extend(hand)
        hand.clear()
        self._draw_to_three(p)

        if self.trace:
            print("  R%2d seat%d %-3s play %-3s inc=%d %s | inf=%s retireTot=%d"
                  % (turn, p, sid, card, inc, action,
                     [tuple(self.inf[a]) for a in range(3)], self.retire_total[p]))

    # ---- 戦略別: 使用カード選択 ----
    def _s2_pick(self, hand, evals):
        # 意図重視: 弱カード（引退点≤1 かつ 増分が手札中最低）があれば選んで使用→引退。
        # 無ければ盤面増分最大を使用→継続。
        min_inc = min(e[0] for e in evals)
        disp = [i for i, c in enumerate(hand) if RETIRE_PTS[c] <= 1 and evals[i][0] == min_inc]
        if disp:
            best_i = min(disp, key=lambda i: (RETIRE_PTS[hand[i]], CARD_RANK[hand[i]]))
            self._s2_dispose = True
            return best_i
        self._s2_dispose = False
        return pick_max_board(hand, evals)

    def _s3_pick(self, hand, evals):
        disposable = []
        for i, c in enumerate(hand):
            met = evals[i][2]; areas = evals[i][3]
            keep_worthy = (c in S3_KEEP_SET and met and bool(areas & set(S3_PRIORITY)))
            if not keep_worthy:
                disposable.append(i)
        pool = disposable if disposable else list(range(len(hand)))
        # プール内で盤面増分最大
        best_i = pool[0]; best_key = None
        for i in pool:
            key = (evals[i][0], -CARD_RANK[hand[i]])
            if best_key is None or key > best_key:
                best_key = key; best_i = i
        self._s3_disposable = set(disposable)
        return best_i

    def _s4_pick(self, hand, evals):
        # 見習いがあり市場が取れるなら見習いを処分優先、なければ盤面最大
        appr = [i for i, c in enumerate(hand) if c == APPRENTICE]
        if appr and self.market:
            best_i = appr[0]; best_inc = None
            for i in appr:
                if best_inc is None or evals[i][0] > best_inc:
                    best_inc = evals[i][0]; best_i = i
            self._s4_playing_appr = True
            return best_i
        self._s4_playing_appr = False
        return pick_max_board(hand, evals)

    # ---- 戦略別: 継続/引退＋市場選択 ----
    def _decide(self, sid, p, turn, card, inc, delta, met, areas, hand, evals, play_i, can_retire):
        if not can_retire:
            if sid == "S5":
                self.rec.s5_forced[turn] += 1   # 市場枯渇による強制継続（選択の余地なし）
            return False, None

        if sid == "S1":
            return True, self._best_market(p, "churn")

        if sid == "S2":
            # 弱カードを選んで使用した手番のみ引退（_s2_pick が判定）
            if getattr(self, "_s2_dispose", False):
                return True, self._best_market(p, "churn")
            return False, None

        if sid == "S3":
            # disposable として選ばれたカードなら引退、keep-worthy を選んだなら継続
            if play_i in getattr(self, "_s3_disposable", set()):
                return True, self._best_market(p, "churn")
            return False, None

        if sid == "S4":
            if getattr(self, "_s4_playing_appr", False):
                return True, self._best_market(p, "churn")
            return False, None

        if sid == "S5":
            R = TURNS - turn                     # 当該手番以降の残り手番
            per_use = inc
            # この時点で hand は使用カードを含む3枚（pop 前）。全カード=deck+discard+hand=8枚。
            deck_cards = self.deck[p] + self.discard[p] + list(hand)      # 継続時デッキ（8枚）
            cont_val = self._expected_uses(per_use, deck_cards, R) * per_use
            mi = self._best_market(p, "expected")
            ret_market = 0.0
            if mi is not None:
                mcard = self.market[mi]
                m_inc, _, _, _ = resolve(mcard, self.inf, p)
                # 引退時デッキ = 使用カード除外＋市場カード追加（8枚）
                hand_wo = [c for i, c in enumerate(hand) if i != play_i]
                deck_after = self.deck[p] + self.discard[p] + hand_wo + [mcard]
                ret_market = self._expected_uses(m_inc, deck_after, R) * m_inc
            ret_val = RETIRE_PTS[card] + ret_market
            # スラック集計（手番4〜7）
            diff = cont_val - ret_val
            keep = cont_val >= ret_val
            self.rec.s5_total[turn] += 1
            if keep:
                self.rec.s5_keep[turn] += 1
            if abs(diff) <= 0.5:
                self.rec.s5_close[turn] += 1
            if 4 <= turn <= 7:                   # §7-4c 評価差分布は中盤帯のみ
                b = round(diff * 2) / 2.0        # 0.5刻みビン
                self.rec.s5_diffhist[b] += 1
            if keep:
                return False, None
            return True, mi

        return False, None

    def run(self):
        for turn in range(1, TURNS+1):
            for seat in range(3):
                self.play_turn(seat, turn)
        # 終了時得点
        board = [my_points(self.inf, p) for p in range(3)]
        score = [board[p] + self.retire_total[p] for p in range(3)]
        # 勝者（1位按分）
        mx = max(score)
        winners = [p for p in range(3) if score[p] == mx]
        wshare = 1.0 / len(winners)
        for p in range(3):
            sid = self.strat[p]
            st = self.rec.strat[sid]
            st['inst'] += 1
            st['score'] += score[p]
            st['board'] += board[p]
            st['retire'] += self.retire_total[p]
            st['win'] += (wshare if p in winners else 0.0)
        self.rec.games += 1
        if self.market_emptied_turn is not None:
            self.rec.deplete_games += 1
            self.rec.deplete_turn_sum += self.market_emptied_turn
        return score, board


# ─────────────────────────────────────────────────────────────
# 実行ドライバ
# ─────────────────────────────────────────────────────────────
STRATS = ["S1", "S2", "S3", "S4", "S5"]
VARIANT_COPIES = {"v1": 2, "v2": 3}
SEED_BASE = 0x5EED

def all_combos():
    return list(itertools.combinations_with_replacement(STRATS, 3))

def combo_seed(variant, combo_idx, game_idx):
    v = 1 if variant == "v1" else 2
    return (SEED_BASE * 1000003 + v * 700003 + combo_idx * 100003 + game_idx) & 0x7FFFFFFF

def run_work(args):
    """1ワークユニット = (variant, combo_idx) を games 回。決定的。"""
    variant, combo_idx, games = args
    combos = all_combos()
    combo = combos[combo_idx]
    copies = VARIANT_COPIES[variant]
    perms = sorted(set(itertools.permutations(combo)))   # 相異なる席順
    rec = Rec()
    for g in range(games):
        seats = list(perms[g % len(perms)])
        rng = random.Random(combo_seed(variant, combo_idx, g))
        Game(seats, copies, rng, rec).run()
    # Rec を素の dict に変換して返す（プロセス間シリアライズ）
    return {
        'variant': variant,
        'combo_idx': combo_idx,
        'combo': list(combo),
        'games': games,
        'strat': {k: dict(v) for k, v in rec.strat.items()},
        'retire_turn': {k: list(v) for k, v in rec.retire_turn.items()},
        'retire_card': {k: dict(v) for k, v in rec.retire_card.items()},
        'market_take': {k: dict(v) for k, v in rec.market_take.items()},
        's5_keep': rec.s5_keep, 's5_total': rec.s5_total,
        's5_close': rec.s5_close, 's5_forced': rec.s5_forced,
        's5_diffhist': {str(k): v for k, v in rec.s5_diffhist.items()},
        'deplete_games': rec.deplete_games, 'deplete_turn_sum': rec.deplete_turn_sum,
    }

def run_variant(variant, games, jobs):
    combos = all_combos()
    work = [(variant, ci, games) for ci in range(len(combos))]
    results = []
    if jobs and jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            for i, r in enumerate(pool.imap_unordered(run_work, work)):
                results.append(r)
                print("  [%s] %d/%d combos" % (variant, len(results), len(work)), file=sys.stderr)
    else:
        for w in work:
            results.append(run_work(w))
            print("  [%s] %d/%d combos" % (variant, len(results), len(work)), file=sys.stderr)
    results.sort(key=lambda r: r['combo_idx'])
    meta = {
        'variant': variant,
        'growth_copies_each': VARIANT_COPIES[variant],
        'games_per_combo': games,
        'combos': len(combos),
        'turns': TURNS, 'players': 3, 'hand': HAND_SIZE, 'market': MARKET_SIZE,
        'seed_base': SEED_BASE,
        'note': 'Python (no Node on this machine, CLAUDE.md §9-f). Deterministic seeds by (variant,combo,game).',
    }
    return {'meta': meta, 'combos': results}


# ─────────────────────────────────────────────────────────────
# トレース / セルフテスト
# ─────────────────────────────────────────────────────────────
def do_trace(seed):
    combo = ("S1", "S3", "S5")
    print("=== TRACE seed=%d combo=%s (V1) ===" % (seed, combo))
    rng = random.Random(seed)
    rec = Rec()
    g = Game(list(combo), VARIANT_COPIES["v1"], rng, rec, trace=True)
    print("初期市場:", g.market)
    score, board = g.run()
    print("最終 inf:", [tuple(g.inf[a]) for a in range(3)])
    print("board:", board, "retire:", g.retire_total, "score:", score)

def do_selftest():
    ok = True
    def check(name, got, want):
        nonlocal ok
        s = "OK " if got == want else "NG "
        if got != want: ok = False
        print("%s %s: got=%s want=%s" % (s, name, got, want))
    check("area (3,3,1) tie1", area_points((3,3,1)), (4,4,1))
    check("area (2,2,2) all-tie", area_points((2,2,2)), (3,3,3))
    check("area (5,2,2) tie2", area_points((5,2,2)), (5,2,2))
    check("area (3,2,0)", area_points((3,2,0)), (5,3,0))
    check("area (4,0,0) solo", area_points((4,0,0)), (5,0,0))
    check("area (0,0,0)", area_points((0,0,0)), (0,0,0))
    # 専門家: 既にある領域に2個
    inf = [[1,0,0],[0,0,0],[0,0,0]]
    inc,d,met,ar = resolve(EXPERT, inf, 0)
    check("expert delta", d, [2,0,0]); check("expert met", met, True)
    # 開拓者: 無い領域に2個（A→B→C先頭 = 空きの最初）
    inf = [[1,0,0],[0,0,0],[0,0,0]]
    inc,d,met,ar = resolve(PIONEER, inf, 0)
    check("pioneer delta", d, [0,2,0])
    print("SELFTEST:", "ALL OK" if ok else "FAILURES")
    return ok

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["v1","v2"])
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--trace", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        do_selftest(); return
    if a.trace is not None:
        do_trace(a.trace); return
    if not a.variant:
        ap.error("--variant required (or use --trace/--selftest)")

    import time
    t0 = time.time()
    res = run_variant(a.variant, a.games, a.jobs)
    dt = time.time() - t0
    res['meta']['elapsed_sec'] = round(dt, 2)
    out = a.out or ("results_%s.json" % a.variant)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("wrote %s  (%d combos × %d games, %.1fs)" % (out, len(res['combos']), a.games, dt), file=sys.stderr)

if __name__ == "__main__":
    main()
