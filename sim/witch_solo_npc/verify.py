import sys
import json

sys.path.insert(0, r"D:\ゲーム\ボドゲ\オリジナル用ローカル\original\sim\witch_solo_npc")
import solo_npc_sim as w

out = {}

testPile1 = w.pile_to_counts([0, 0, 3])
out["scoreRecipe_cases"] = [{"id": r["id"], "score": w.score_recipe(r, testPile1)} for r in w.POOL]

testPile2 = w.pile_to_counts([1, 4, 5])
hand = [w.POOL.index(next(r for r in w.POOL if r["id"] == x)) for x in ["pair_満星", "cnt2_満火", "abs_影"]]
out["scorePile_case"] = {"score": w.score_pile(hand, testPile2)}


def idx_of(rid):
    return next(i for i, r in enumerate(w.POOL) if r["id"] == rid)


out["dealConflicts_cases"] = [
    {"ids": ["abs_影", "pair_影蛇"], "actual": w.deal_conflicts([idx_of("abs_影"), idx_of("pair_影蛇")])},
    {"ids": ["abs_影", "solo_満"], "actual": w.deal_conflicts([idx_of("abs_影"), idx_of("solo_満")])},
]

out["cutSets_9_2_count"] = len(w.cut_sets(9, 2))
band_fixed = [0, 1, 2, 3, 4, 5, 0, 1, 2]
out["toPiles_case"] = {"piles": w.to_piles(band_fixed, [3, 6])}

out["chooseOrder_cases"] = [
    {"cutter": 0, "n": 3, "order": w.choose_order(0, 3)},
    {"cutter": 1, "n": 3, "order": w.choose_order(1, 3)},
    {"cutter": 2, "n": 4, "order": w.choose_order(2, 4)},
]

players3 = [
    tuple(sorted(idx_of(x) for x in ["pair_満星", "cnt2_満火", "abs_影"])),
    tuple(sorted(idx_of(x) for x in ["solo_火", "abs2_影蛇", "pair_霜蛇"])),
    tuple(sorted(idx_of(x) for x in ["solo_霜", "abs_蛇", "pair_火霜"])),
]
band3 = [0, 1, 2, 3, 4, 5, 0, 1, 2]
out["omniMax_case"] = {"omni": w.omni_max(band3, players3, 3)}


def best_for_cut(band, cuts, players, n):
    piles = w.to_piles(band, cuts)
    piles_counts = [w.pile_to_counts(p) for p in piles]
    best = -1e18
    for perm in w.PERMS[n]:
        total = sum(w.score_pile(players[perm[i]], piles_counts[i]) for i in range(n))
        best = max(best, total)
    return best


out["bestForCut_case"] = {"best": best_for_cut(band3, [3, 6], players3, 3)}
out["bestForCut_case2"] = {"best": best_for_cut(band3, [2, 5], players3, 3)}
out["bestForCut_case3"] = {"best": best_for_cut(band3, [1, 4], players3, 3)}

print(json.dumps(out, ensure_ascii=False, indent=2))
