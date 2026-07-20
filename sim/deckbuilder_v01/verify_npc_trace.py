#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_npc_trace.py ― solo.html のNPC(S1/S3)判断が deckbuilder_sim.py の決定ロジックと
一致するかを、ブラウザ側(solo.html?dev=1)で書き出したトレースJSONを使って突合する。
指示書「新作デッキ構築ゲーム ブラウザソロ版プロトタイプ」完了条件3の検証手段。

トレースJSONの各手番レコードは、solo.html の resolveNpcTurn() が生成する:
  {turn, seat, sid, handBefore, infBefore, marketBefore, s3Priority,
   playIdx, canRetire, retireDecision, marketPickIdx}
本スクリプトは deckbuilder_sim.py の resolve()/pick_max_board() を「正」としてそのまま import し、
同じ (infBefore, handBefore, marketBefore) からNPCが取るべき決定を独立に再計算して比較する。
JSの乱数と突合する必要はない（手番ごとの盤面/手札/市場のスナップショットを起点にするため）。

使い方:
    python verify_npc_trace.py trace.json
"""
import sys
import json
from deckbuilder_sim import resolve, pick_max_board, CARD_RANK, RETIRE_PTS, S3_KEEP_SET


def best_market_churn(market, inf, me):
    if not market:
        return None
    best_i = 0
    best_key = None
    for i, c in enumerate(market):
        inc, _, _, _ = resolve(c, inf, me)
        v = RETIRE_PTS[c] + inc
        key = (v, -CARD_RANK[c])
        if best_key is None or key > best_key:
            best_key = key
            best_i = i
    return best_i


def s3_pick(inf, me, hand, priority):
    evals = [resolve(c, inf, me) for c in hand]
    disposable = []
    for i, c in enumerate(hand):
        met = evals[i][2]
        areas = evals[i][3]
        keep_worthy = (c in S3_KEEP_SET and met and bool(areas & set(priority)))
        if not keep_worthy:
            disposable.append(i)
    pool = disposable if disposable else list(range(len(hand)))
    best_i = pool[0]
    best_key = None
    for i in pool:
        key = (evals[i][0], -CARD_RANK[hand[i]])
        if best_key is None or key > best_key:
            best_key = key
            best_i = i
    return best_i, set(disposable)


def check_turn(rec):
    # infBefore は「使用カードの効果を解決する前」の盤面。カード選択・継続/引退の判定基準は
    # deckbuilder_sim.py の play_turn と同じくこの時点の inf を使う。一方で市場カードの評価
    # （_best_market 相当）は「使用カードの効果を解決した後」の inf を使う点に注意
    # （self.play_turn 内で resolve→delta適用→_decide の順に呼ばれているため）。
    inf = rec['infBefore']
    me = rec['seat']
    hand = rec['handBefore']
    sid = rec['sid']

    if sid == 'S1':
        evals = [resolve(c, inf, me) for c in hand]
        want_i = pick_max_board(hand, evals)
        want_retire = True if rec['canRetire'] else False
    elif sid == 'S3':
        want_i, disposable = s3_pick(inf, me, hand, rec['s3Priority'])
        want_retire = (want_i in disposable) if rec['canRetire'] else False
    else:
        return False, {'reason': 'unknown sid %r' % sid}

    want_market = None
    if want_retire:
        _, delta, _, _ = resolve(hand[want_i], inf, me)
        inf_after = [row[:] for row in inf]
        for a in range(3):
            inf_after[a][me] += delta[a]
        want_market = best_market_churn(rec['marketBefore'], inf_after, me)

    got_i = rec['playIdx']
    got_retire = rec.get('retireDecision')
    got_market = rec.get('marketPickIdx')

    ok = (got_i == want_i) and (got_retire == want_retire)
    if want_retire:
        ok = ok and (got_market == want_market)

    detail = None
    if not ok:
        detail = {
            'turn': rec['turn'], 'seat': me, 'sid': sid,
            'hand': hand, 'want_playIdx': want_i, 'got_playIdx': got_i,
            'want_retire': want_retire, 'got_retire': got_retire,
            'want_market': want_market, 'got_market': got_market,
        }
    return ok, detail


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'trace.json'
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    turns = data['turns']
    mism = []
    n_ok = 0
    for rec in turns:
        ok, detail = check_turn(rec)
        if ok:
            n_ok += 1
        else:
            mism.append(detail)

    total = len(turns)
    print("突合対象NPC手番: %d / 一致: %d / 不一致: %d" % (total, n_ok, len(mism)))
    if mism:
        print(json.dumps(mism, ensure_ascii=False, indent=1))
        sys.exit(1)
    print("ALL MATCH")


if __name__ == "__main__":
    main()
