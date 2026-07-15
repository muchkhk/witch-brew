#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_reference_traces.py — v3エンジン(solo_npc_sim_v3.py)を使い、固定シードで完全な6儀式トレースを
記録する。JS移植の同値性検証(proto/verify_equivalence.js)の基準データ。

sim/witch_solo_npc/ の既存ファイルは一切変更していない(import して利用するのみ)。

出力: proto/reference_traces.json
  各トレース: 真の手札・気まぐれ・各儀式の帯/カット/選択の実際の観測イベント・
  各プレイヤーの信念からの候補数の推移・最終pct を記録する。
  JS側はこのイベント列を「そのまま与えられた」ものとして再生し、同じ信念更新結果になるかを確認する
  (JS側で乱数から選択をやり直すのではなく、記録された選択を入力として belief 更新のみ照合する)。
"""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\ゲーム\ボドゲ\オリジナル用ローカル\original\sim\witch_solo_npc")
import solo_npc_sim as w1
import solo_npc_sim_v3 as w3


def record_trial(n, rounds, policies, whim_params_list, rng, seed_label):
    w1.clear_pile_cache()
    w1.clear_norm_cache()
    true_hands = w1.deal_recipe_idxs(n, rng)
    whims = [None if whim_params_list[p] is None else w3.draw_whim(true_hands[p], whim_params_list[p].q, rng)
             for p in range(n)]
    beliefs = [np.zeros(w1.N_HANDS) for _ in range(n)]

    trace = {
        "seed_label": seed_label,
        "n": n, "rounds": rounds,
        "true_hands": [list(h) for h in true_hands],
        "whims": [None if wm is None else list(wm) for wm in whims],
        "policies": [{"lam": p.lam, "tau": p.tau} for p in policies],
        "whim_params": [None if wp is None else {"q": wp.q, "w": wp.w} for wp in whim_params_list],
        "round_events": [],
        "candidate_curves": {str(p): [] for p in range(n)},
    }

    cutter = 0
    for _r in range(rounds):
        band = w1.make_band(n, rng)
        candidates = w1.cut_sets(len(band), n - 1)
        chosen_cs, _cands, _ebas = w1.npc_cut_decision(band, n, cutter, true_hands, beliefs,
                                                        policies[cutter], rng)
        w1.update_belief_for_cut(beliefs, cutter, band, n, chosen_cs, candidates, policies[cutter].tau)

        piles = w1.to_piles(band, chosen_cs)
        piles_counts = [w1.pile_to_counts(p) for p in piles]
        order = w1.choose_order(cutter, n)
        available = list(range(len(piles)))
        assign = {}
        choice_events = []

        for oi, chooser in enumerate(order):
            future_players = [order[k] for k in range(oi + 1, len(order))] + [cutter]
            avail_counts = [piles_counts[i] for i in available]
            avail_before = list(available)
            wp = whim_params_list[chooser]

            if wp is None:
                choice_local = w1.npc_choose_decision(
                    avail_counts, true_hands[chooser], future_players, beliefs, policies[chooser], rng)[0]
                w1.update_belief_for_choice(beliefs, chooser, avail_counts, choice_local,
                                             future_players, policies[chooser])
            else:
                choice_local = w3.npc_choose_decision_whim(
                    avail_counts, true_hands[chooser], whims[chooser], wp.w,
                    future_players, beliefs, policies[chooser], rng)
                w3.marginalized_update_belief_for_choice(beliefs, chooser, avail_counts, choice_local,
                                                          future_players, policies[chooser], wp)

            chosen_pile_idx = available[choice_local]
            choice_events.append({
                "chooser": chooser, "available_before": avail_before,
                "future_players": future_players, "chosen_local": choice_local,
                "chosen_pile_idx": chosen_pile_idx,
            })
            assign[chosen_pile_idx] = chooser
            available.remove(chosen_pile_idx)

        assert len(available) == 1
        assign[available[0]] = cutter

        seat_pile_counts = [None] * n
        for pi, seat in assign.items():
            seat_pile_counts[seat] = piles_counts[pi]

        round_scores = [w1.score_pile(true_hands[s], seat_pile_counts[s]) for s in range(n)]
        team_total = sum(round_scores)
        w1.update_belief_for_team_total(beliefs, n, seat_pile_counts, team_total)
        omni = w1.omni_max(band, true_hands, n)

        trace["round_events"].append({
            "cutter": cutter, "band": band, "chosen_cutset": list(chosen_cs),
            "piles": piles, "assign": {str(k): v for k, v in assign.items()},
            "choice_events": choice_events, "round_scores": round_scores,
            "team_total": team_total, "omni": omni,
        })
        for p in range(n):
            trace["candidate_curves"][str(p)].append(w1.candidate_count(beliefs[p]))

        cutter = (cutter + 1) % n

    total_team = sum(e["team_total"] for e in trace["round_events"])
    total_omni = sum(e["omni"] for e in trace["round_events"])
    pct = min(100, round(total_team / total_omni * 100)) if total_omni > 0 else (100 if total_team >= 0 else 0)
    trace["final_team_total"] = total_team
    trace["final_omni"] = total_omni
    trace["final_pct"] = pct
    return trace


def main():
    # v3計測済み・プロトタイプで採用する3タイプ
    MIRA = (0.65, w3.WhimParams(1, 0.5))     # 世話焼き
    ZORA = (0.8, w3.WhimParams(1, 0.5))      # 欲張り
    LU = (0.65, w3.WhimParams(2, 1.0))       # 気分屋

    traces = []
    configs = [
        ("case1_mira_zora", 111, MIRA, ZORA),
        ("case2_mira_lu", 222, MIRA, LU),
        ("case3_zora_lu", 333, ZORA, LU),
    ]
    for label, seed, npc1, npc2 in configs:
        rng = np.random.default_rng(seed)
        lam1, wp1 = npc1
        lam2, wp2 = npc2
        policies = [w1.Policy(1.0, w3.WHIM_TAU), w1.Policy(lam1, w3.WHIM_TAU), w1.Policy(lam2, w3.WHIM_TAU)]
        whim_params_list = [None, wp1, wp2]  # プレイヤー役(席0)は気まぐれ無し
        trace = record_trial(3, 6, policies, whim_params_list, rng, label)
        traces.append(trace)
        print(f"{label}: final_pct={trace['final_pct']} candidate_curves(p0)={trace['candidate_curves']['0']}")

    class NumpyJSONEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.bool_,)):
                return bool(o)
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                return float(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
            return super().default(o)

    with open("reference_traces.json", "w", encoding="utf-8") as f:
        json.dump(traces, f, ensure_ascii=False, indent=2, cls=NumpyJSONEncoder)
    print("reference_traces.json に書き出しました")


if __name__ == "__main__":
    main()
