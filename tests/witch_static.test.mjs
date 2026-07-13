import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";

const html = fs.readFileSync("witch.html", "utf8");

test("全インラインscriptにJavaScript構文エラーがない", () => {
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
    .map(match => match[1])
    .filter(source => source.trim());
  assert.ok(scripts.length >= 3);
  scripts.forEach((source, index) => new vm.Script(source, { filename: `witch-inline-${index + 1}.js` }));
});

test("オンラインDBはroomsV2と6文字コードだけを使う", () => {
  assert.match(html, /function roomPath\(p\)\{ return "roomsV2\/"/);
  assert.match(html, /for\(let i=0;i<6;i\+\+\)/);
  assert.match(html, /maxlength="6"/);
  assert.doesNotMatch(html, /_db\.ref\("rooms\//);
});

test("通常購読と観戦購読はprivateRecipes全体を含めない", () => {
  const playerSub = html.slice(html.indexOf("function subscribeRoom()"), html.indexOf("// 生存フラグ"));
  const spectatorSub = html.slice(html.indexOf("async function spectate()"), html.indexOf("function spectatorHTML()"));
  assert.doesNotMatch(playerSub, /roomPath\("privateRecipes/);
  assert.doesNotMatch(spectatorSub, /roomPath\("privateRecipes/);
  assert.match(playerSub, /roomPath\("reveal"\)/);
  assert.match(spectatorSub, /roomPath\("reveal"\)/);
});

test("オンライン採点公開値にtotalsやfiredを保存しない", () => {
  const resolve = html.slice(html.indexOf("async function resolveScore()"), html.indexOf("function onGameUpdate()"));
  assert.match(resolve, /cur\.roundEval=\{roundScore:rs,omni,rational:rat,pct,cutPct\}/);
  assert.doesNotMatch(resolve, /cur\.roundEval=\{[^}]*totals/);
  assert.doesNotMatch(resolve, /cur\.history\.push\(\{[^;]*fired/);
});

test("採点と終了公開はホスト固定で再接続待ちを表示する", () => {
  assert.match(html, /return !!\(myUid&&ST\.meta&&ST\.meta\.host===myUid\)/);
  assert.match(html, /進行役の再接続を待っています/);
  assert.match(html, /game\.phase==="end"&&amResolver\(\)/);
});
