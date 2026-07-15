// verify_equivalence.js — proto/reference_traces.json (Python生成) を、実際に出荷する
// proto/witch_solo_proto.html に埋め込まれたJSエンジンで「再生」し、信念更新の結果
// （候補数の推移・最終pct）が一致するか確認する。
// 乱数で選択をやり直すのではなく、記録された選択(band/カット/選ばれた坩堝)をそのまま入力として
// 与え、信念更新の数式(周辺化・畳み込み含む)がPython版と同じ結果になるかを検証する。

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'witch_solo_proto.html'), 'utf8');
// witch_solo_proto.html内の2つの<script>ブロック(凍結コアロジック・NPC方策/推定エンジン)を
// そのまま抜き出す(第3の<script>はUI/ゲーム進行なのでここでは不要)。
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length < 2) throw new Error('witch_solo_proto.html からエンジン用scriptを抽出できませんでした');
const coreLogic = scripts[0];
const engine = scripts[1];

const traces = JSON.parse(fs.readFileSync(path.join(__dirname, 'reference_traces.json'), 'utf8'));

const mainCode = `
let totalChecks = 0, totalMismatches = 0;
const report = [];
const traces = ${JSON.stringify(traces)};

for (const trace of traces) {
  const n = trace.n;
  const beliefs = Array.from({ length: n }, () => new Float64Array(N_HANDS));
  const whimParamsList = trace.whim_params;
  const policies = trace.policies;
  const curveJS = { 0: [], 1: [], 2: [] };
  const caseReport = { seed_label: trace.seed_label, rounds: [] };

  for (const ev of trace.round_events) {
    const cutter = ev.cutter;
    const band = ev.band;
    const candidates = cutSets(band.length, n - 1);

    updateBeliefForCut(beliefs, cutter, band, n, ev.chosen_cutset, candidates, policies[cutter].tau);

    const piles = toPiles(band, ev.chosen_cutset);
    for (const ce of ev.choice_events) {
      const chooser = ce.chooser;
      const availCounts = ce.available_before.map(i => piles[i]);
      const wp = whimParamsList[chooser];
      if (wp === null) {
        updateBeliefForChoicePlain(beliefs, chooser, availCounts, ce.chosen_local, ce.future_players, policies[chooser]);
      } else {
        marginalizedUpdateBeliefForChoice(beliefs, chooser, availCounts, ce.chosen_local, ce.future_players, policies[chooser], wp);
      }
    }

    const seatPiles = new Array(n);
    for (const [pi, seat] of Object.entries(ev.assign)) seatPiles[seat] = piles[parseInt(pi)];
    updateBeliefForTeamTotal(beliefs, n, seatPiles, ev.team_total);

    for (let p = 0; p < n; p++) curveJS[p].push(candidateCount(beliefs[p]));
  }

  for (let p = 0; p < n; p++) {
    const pyC = trace.candidate_curves[String(p)];
    const jsC = curveJS[p];
    const match = pyC.length === jsC.length && pyC.every((v, i) => v === jsC[i]);
    totalChecks++;
    if (!match) totalMismatches++;
    caseReport.rounds.push({ player: p, python: pyC, js: jsC, match });
  }
  report.push(caseReport);
}

console.log(JSON.stringify(report, null, 2));
console.log("\\n=== " + (totalMismatches === 0 ? "全一致" : "不一致あり") + ": " + (totalChecks - totalMismatches) + "/" + totalChecks + " 系列が一致 ===");
process.exitCode = totalMismatches === 0 ? 0 : 1;
`;

eval(coreLogic + '\n' + engine + '\n' + mainCode);
