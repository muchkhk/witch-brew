/* v0.9・工程6: 開始ゲートの構造修正（presenceをハードゲートから外す）の回帰テスト。
 * 静的なソース文字列検査ではなく、実際の関数を抽出・実行して振る舞いを検証する
 * （抽出はGM画面render停止バグ修正の際に確立した「regex抽出 + new Function()」方式を踏襲）。
 * A: Online.seatsClaimed/seatsPresent/missingReasons/presenceWarnings の実挙動
 * B: net.js keepPresence() のハートビート自己修復・unsub後の停止・失敗コールバック */
'use strict';
const fs = require('fs');
const path = require('path');
const E = require('./engine.js');
const N = require('./net.js');

let passed = 0, failed = 0;
function ok(c, m) { if (c) passed++; else { failed++; console.error('  FAIL:', m); } }

const PLAYERS = E.DEFAULT_CONFIG.players;
const GM = E.DEFAULT_CONFIG.gmName;
const uiSrc = fs.readFileSync(path.join(__dirname, 'ui_template.html'), 'utf-8');

/* ---------------- A: Online の座席判定系メソッドを抽出して実行 ---------------- */
function extractMethod(name) {
  const re = new RegExp(`${name}\\(\\) \\{([\\s\\S]*?)\\n  \\},`);
  const m = re.exec(uiSrc);
  if (!m) throw new Error(`${name}() をui_template.htmlから抽出できませんでした`);
  return new Function('PLAYERS', `return function ${name}() {${m[1]}\n}`)(PLAYERS);
}

console.log('工程1: seatsClaimed()/seatsPresent() の抽出・実行検証:');
{
  const seatsClaimed = extractMethod('seatsClaimed');
  const seatsPresent = extractMethod('seatsPresent');
  const missingReasons = extractMethod('missingReasons');
  const presenceWarnings = extractMethod('presenceWarnings');

  const full = { からあげ: { uid: 'u0' }, てかさ: { uid: 'u1' }, 逆廻: { uid: 'u2' } };

  // 完全一致テスト用ヘルパー
  function roomInfo(seats, presenceMap) { return { roomInfo: { seats, presence: presenceMap } }; }

  // シナリオ1: 3席とも占有・presence全部true → 通常状態
  {
    const ctx = roomInfo(full, { u0: true, u1: true, u2: true });
    ok(seatsClaimed.call(ctx) === 3, 'seatsClaimed(): 3席占有・presence全true → 3');
    ok(seatsPresent.call(ctx) === 3, 'seatsPresent(): 3席占有・presence全true → 3（既存の意味は不変）');
    ok(missingReasons.call(ctx).length === 0, 'missingReasons(): 全員揃っていれば理由0件');
    ok(presenceWarnings.call(ctx).length === 0, 'presenceWarnings(): presence全trueなら警告0件');
  }

  // シナリオ2（★指示書必須): 3席とも占有・presence全部false → 開始できるべき
  {
    const ctx = roomInfo(full, { u0: false, u1: false, u2: false });
    ok(seatsClaimed.call(ctx) === 3, 'seatsClaimed(): presence全falseでも席が埋まっていれば3（開始可能）');
    ok(seatsPresent.call(ctx) === 0, 'seatsPresent(): presence全falseなら0（既存の意味は不変・開始判定には使われない）');
    ok(missingReasons.call(ctx).length === 0, 'missingReasons(): presenceが理由で不活性にならない（空席理由のみ）');
    const warns = presenceWarnings.call(ctx);
    ok(warns.length === 3, `presenceWarnings(): 3件の警告が出る (実:${warns.length})`);
    ok(warns.every((w) => /未接続の可能性があります/.test(w) && /そのまま開始して構いません/.test(w)), '警告文言が「そのまま開始して構いません」という許可のトーンを含む');
  }

  // シナリオ3（★指示書必須): 席が2つしか埋まっていない（presenceは全部true）→ 開始できないべき
  {
    const partial = { からあげ: { uid: 'u0' }, てかさ: { uid: 'u1' } };
    const ctx = roomInfo(partial, { u0: true, u1: true });
    ok(seatsClaimed.call(ctx) === 2, 'seatsClaimed(): 2席のみ占有 → 2（開始不可）');
    const reasons = missingReasons.call(ctx);
    ok(reasons.length === 1 && /席「逆廻」が空/.test(reasons[0]), 'missingReasons(): 空席「逆廻」のみを理由に挙げる');
    ok(presenceWarnings.call(ctx).length === 0, 'presenceWarnings(): 埋まっている席のpresenceは全trueなので警告0件');
  }

  // シナリオ4: 空席1・presence不整合1が混在
  {
    const partial = { からあげ: { uid: 'u0' }, てかさ: { uid: 'u1' } };
    const ctx = roomInfo(partial, { u0: true, u1: false });
    ok(seatsClaimed.call(ctx) === 2, 'seatsClaimed(): 空席1+presence不整合1でも占有数は2');
    ok(missingReasons.call(ctx).length === 1, 'missingReasons(): 空席分のみ1件（presence不整合は理由に含めない）');
    const warns = presenceWarnings.call(ctx);
    ok(warns.length === 1 && /席「てかさ」/.test(warns[0]), 'presenceWarnings(): presence不整合の「てかさ」だけ1件警告');
  }
}

console.log('工程2: 開始ボタンの活性条件がclaimedベースであること（renderWait内の分岐を静的確認）:');
{
  const idx = uiSrc.indexOf('renderWait() {');
  const body = idx >= 0 ? uiSrc.slice(idx, idx + 2500) : '';
  ok(/const claimed = this\.seatsClaimed\(\);/.test(body), 'renderWait() が seatsClaimed() を使うこと');
  ok(/\$\{claimed >= 3 \? '' : 'disabled'\}/.test(body), '開始ボタンのdisabled判定が claimed>=3 であること（presence条件を含まない）');
  ok(!/present >= 3/.test(body), '旧来の present>=3（presence込み）判定が残っていないこと');
}

/* ---------------- B: net.js keepPresence() のハートビート挙動 ---------------- */
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

async function testHeartbeatSelfHeals() {
  const db = N.createMockDb();
  await N.createRoom(db, 'H1', { gmUid: 'g', gmName: GM, deckKey: 't', now: 1 });
  await N.claimSeat(db, 'H1', PLAYERS[0], 'u0', PLAYERS[0]);
  await N.setPresence(db, 'H1', 'u0');

  // MockDBは .info/connected の変化イベントを一切発火しない（getNode()が常にundefined）ため、
  // ここで自己修復するとしたらハートビート以外の経路ではありえない。
  const unsub = N.keepPresence(db, 'H1', 'u0', { heartbeatMs: 40 });
  await tick(10);
  await db.ref('rooms/H1/presence/u0').set(false); // 落ちたことをシミュレート
  const droppedVal = await db.ref('rooms/H1/presence/u0').get();
  ok(droppedVal === false, 'ハートビート試験の前提: presenceをfalseに落とせている');

  await tick(130); // heartbeatMs=40なので3回前後は発火する
  const healed = await db.ref('rooms/H1/presence/u0').get();
  ok(healed === true, `ハートビートが.info/connectedの変化イベントなしに自己修復すること (実:${healed})`);

  unsub();
  await db.ref('rooms/H1/presence/u0').set(false); // unsub後に再度落とす
  await tick(130);
  const afterUnsub = await db.ref('rooms/H1/presence/u0').get();
  ok(afterUnsub === false, 'unsub()後はハートビートが停止し、presenceが自己修復されないこと（インターバルの後始末確認）');
}

async function testHeartbeatDoesNotOscillate() {
  const db = N.createMockDb();
  await N.createRoom(db, 'H2', { gmUid: 'g', gmName: GM, deckKey: 't', now: 1 });
  await N.claimSeat(db, 'H2', PLAYERS[0], 'u0', PLAYERS[0]);
  await N.setPresence(db, 'H2', 'u0');
  const seen = [];
  const ref = db.ref('rooms/H2/presence/u0');
  ref.on('value', (v) => seen.push(v));
  const unsub = N.keepPresence(db, 'H2', 'u0', { heartbeatMs: 30 });
  await tick(140);
  unsub();
  ok(seen.every((v) => v === true || v === null), `ハートビートはtrueのみを書き込み、falseとの振動を起こさないこと (観測値:${JSON.stringify(seen)})`);
}

async function testHeartbeatErrorIsReported() {
  const real = N.createMockDb();
  await N.createRoom(real, 'H3', { gmUid: 'g', gmName: GM, deckKey: 't', now: 1 });
  await N.claimSeat(real, 'H3', PLAYERS[0], 'u0', PLAYERS[0]);
  // presenceパスへの書き込みだけ例外を投げるdbラッパー（工程3: 失敗を握り潰さないことの検証）
  const throwingDb = {
    ref(p) {
      const r = real.ref(p);
      if (p.includes('/presence/')) return Object.assign({}, r, { set: async () => { throw new Error('simulated write failure'); } });
      return r;
    },
  };
  let errCount = 0;
  const unsub = N.keepPresence(throwingDb, 'H3', 'u0', { heartbeatMs: 30, onHeartbeatError: () => { errCount++; } });
  await tick(110);
  unsub();
  ok(errCount >= 2, `presence書き込み失敗のたびに onHeartbeatError が呼ばれること (実:${errCount}回)`);
}

async function main() {
  console.log('工程3: presenceハートビートの自己修復・後始末・エラー通知:');
  await testHeartbeatSelfHeals();
  await testHeartbeatDoesNotOscillate();
  await testHeartbeatErrorIsReported();

  console.log('工程4: startGame()早期returnの可視化（静的確認・onclickの実挙動はブラウザ依存のため）:');
  {
    const idx = uiSrc.indexOf('async startGame() {');
    const body = idx >= 0 ? uiSrc.slice(idx, idx + 800) : '';
    ok(/this\.flashError\(this\._starting \? '開始処理を実行中です…' : 'すでにホストとして起動済みです'\)/.test(body), 'startGame() の早期returnがflashError()で可視化されていること');
    ok(/if \(this\._starting \|\| this\.host\) \{/.test(body), '早期returnのガード条件自体は変更されていないこと');
  }

  console.log(`\n==== gate結果: ${passed} passed, ${failed} failed ====`);
  process.exit(failed ? 1 : 0);
}

main();
