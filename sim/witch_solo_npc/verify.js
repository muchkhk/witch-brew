// witch.html の凍結コアロジックを読み込んで、固定テストケースの出力をJSONで出す。
// solo_npc_sim.py 側で同じテストケースを計算し、突き合わせる(検算ログ)。
// const宣言はevalの外へ漏れないため、コアロジックとテストコードを1つの文字列にまとめてevalする。
const fs = require('fs');
const path = require('path');
const core = fs.readFileSync(path.join(__dirname, 'core_logic.js'), 'utf8');

const testCode = `
const out = {};

out.scoreRecipe_cases = [];
const testPile1 = [0, 0, 3];
for (const r of POOL) {
  out.scoreRecipe_cases.push({ id: r.id, pile: testPile1, score: scoreRecipe(r, testPile1) });
}
const testPile2 = [1, 4, 5];
out.scorePile_case = { hand: ["pair_満星", "cnt2_満火", "abs_影"].map(byId), pile: testPile2,
  score: scorePile(["pair_満星", "cnt2_満火", "abs_影"].map(byId), testPile2) };

function idxOf(id) { return POOL.findIndex(r => r.id === id); }
out.dealConflicts_cases = [
  { ids: ["abs_影", "pair_影蛇"], expect_conflict: true, actual: dealConflicts([idxOf("abs_影"), idxOf("pair_影蛇")]) },
  { ids: ["abs_影", "solo_満"], expect_conflict: false, actual: dealConflicts([idxOf("abs_影"), idxOf("solo_満")]) },
];

const cs9_2 = cutSets(9, 2);
out.cutSets_9_2_count = cs9_2.length;
const bandFixed = [0,1,2,3,4,5,0,1,2];
out.toPiles_case = { band: bandFixed, cuts: [3,6], piles: toPiles(bandFixed, [3,6]) };

out.chooseOrder_cases = [
  { cutter: 0, n: 3, order: chooseOrder(0,3) },
  { cutter: 1, n: 3, order: chooseOrder(1,3) },
  { cutter: 2, n: 4, order: chooseOrder(2,4) },
];

const players3 = [
  ["pair_満星","cnt2_満火","abs_影"].map(byId),
  ["solo_火","abs2_影蛇","pair_霜蛇"].map(byId),
  ["solo_霜","abs_蛇","pair_火霜"].map(byId),
];
const band3 = [0,1,2,3,4,5,0,1,2];
out.omniMax_case = { band: band3, omni: omniMax(band3, players3) };
out.bestForCut_case = { band: band3, cuts: [3,6], best: bestForCut(band3, [3,6], players3) };
out.bestForCut_case2 = { band: band3, cuts: [2,5], best: bestForCut(band3, [2,5], players3) };
out.bestForCut_case3 = { band: band3, cuts: [1,4], best: bestForCut(band3, [1,4], players3) };

console.log(JSON.stringify(out, null, 2));
`;

eval(core + "\n" + testCode);
