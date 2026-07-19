/* 静的テスト: ui_template.html / net.js のソーステキストに対する不変条件を検証する。
 * ランタイム挙動ではなく「書かれているべきこと／書かれていてはいけないこと」の検査。
 * v4指示書（§3-1/§3-3/§5-3の文言確定・§3-4新規追加）に対応。 */
'use strict';
const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;
function ok(c, m) { if (c) passed++; else { failed++; console.error('  FAIL:', m); } }

const uiSrc = fs.readFileSync(path.join(__dirname, 'ui_template.html'), 'utf-8');
const netSrc = fs.readFileSync(path.join(__dirname, 'net.js'), 'utf-8');

console.log('alert()/confirm()の撲滅（§5-5）:');
{
  const alertCount = (uiSrc.match(/\balert\(/g) || []).length;
  const confirmCount = (uiSrc.match(/\bconfirm\(/g) || []).length;
  ok(alertCount === 0, `alert( が0件であること (実:${alertCount})`);
  ok(confirmCount === 0, `confirm( が0件であること (実:${confirmCount})`);
}

console.log('版不一致ガード（§2-4）:');
{
  const verDefCount = (uiSrc.match(/const VER\s*=/g) || []).length;
  ok(verDefCount === 1, `VER の定義が1箇所だけであること (実:${verDefCount})`);
  ok(/ver:\s*VER/.test(uiSrc), 'createRoom() 呼び出しで meta.ver に VER を書いていること');
  ok(/ver:\s*ver\s*\|\|\s*null/.test(netSrc), 'net.js の createRoom() が meta.ver を保存すること');
  ok(/verNum\(/.test(uiSrc), '版比較ロジック(verNum)が存在すること');
  ok(/meta\.ver/.test(uiSrc), 'meta.ver を参照する比較分岐が存在すること');
  ok(/再読み込みしてください/.test(uiSrc), '「部屋の方が新しい」ケースのバナー文言が存在すること');
  ok(/部屋を作り直してください/.test(uiSrc), '「部屋の方が古い」ケースのバナー文言が存在すること');
  // べた書きの版番号（"v0.6" 等）が VER の定義行以外に残っていないこと（実際にv0.6のロビー見出しが
  // べた書きのまま残っていた回帰があったため、再発防止として静的テストに追加）
  const hardcodedVer = uiSrc.split('\n').filter((line) => {
    const t = line.trim();
    if (t.startsWith('//') || t.startsWith('/*') || t.startsWith('*')) return false; // コードコメントは対象外
    return /\bv0\.\d+\b/.test(line) && !/const VER\s*=/.test(line);
  });
  ok(hardcodedVer.length === 0, `VER定義行以外にべた書きの版番号が無いこと (実:${hardcodedVer.length}行: ${hardcodedVer.join(' / ')})`);
}

console.log('全画面からルールに到達できること（§2-5）:');
{
  ok(/id="rulesbtn"/.test(uiSrc), 'ヘッダーに❓ボタン(#rulesbtn)が存在すること');
  const showRulesCallCount = (uiSrc.match(/UI\.showRules\(\)/g) || []).length;
  // ホットシート/ソロ用ヘッダー(frame())とオンライン用ヘッダー(Online.render())の双方に必要 → 最低2箇所
  ok(showRulesCallCount >= 2, `UI.showRules() の呼び出しがホットシート/オンライン双方のヘッダーに存在すること (実:${showRulesCallCount})`);
  ok(/function frame\(body\)[\s\S]{0,300}rulesbtn/.test(uiSrc), 'ホットシート/ソロのヘッダー(frame())に❓ボタンがあること');
  const onlineHeaderIdx = uiSrc.indexOf('  render() {\n    const app = document.getElementById');
  ok(onlineHeaderIdx >= 0 && uiSrc.slice(onlineHeaderIdx, onlineHeaderIdx + 1800).includes('rulesbtn'), 'オンラインのヘッダー(Online.render())に❓ボタンがあること');
}

console.log('決着ラウンド画面文言（§4・D-1）:');
{
  const hotseatIdx = uiSrc.indexOf('決着ラウンド — ${esc(p)} の選択');
  const hotseatWin = hotseatIdx >= 0 ? uiSrc.slice(hotseatIdx, hotseatIdx + 400) : '';
  ok(/マッチ/.test(hotseatWin) && /前半/.test(hotseatWin) && /後半/.test(hotseatWin),
    'ホットシート版 decisionPick 画面文言に「マッチ」「前半」「後半」を含むこと');

  const onlineIdx = uiSrc.indexOf('決着ラウンド — 最後の1枚を選ぶ');
  const onlineWin = onlineIdx >= 0 ? uiSrc.slice(onlineIdx, onlineIdx + 400) : '';
  ok(/マッチ/.test(onlineWin) && /前半/.test(onlineWin) && /後半/.test(onlineWin),
    'オンライン版 decisionPick 画面文言に「マッチ」「前半」「後半」を含むこと');
}

console.log('ルール説明の核漏洩防止（§3-1/§3-3・RULES_HTML/GLOSSARY_HTML）:');
{
  const rulesMatch = /const RULES_HTML = `([\s\S]*?)`;/.exec(uiSrc);
  ok(!!rulesMatch, 'RULES_HTML 定数を検出できること');
  const rulesBody = rulesMatch ? rulesMatch[1] : '';
  const glossMatch = /const GLOSSARY_HTML = `([\s\S]*?)`;/.exec(uiSrc);
  ok(!!glossMatch, 'GLOSSARY_HTML 定数を検出できること');
  const glossBody = glossMatch ? glossMatch[1] : '';
  for (const bad of ['序盤', '終盤', 'スレイ・ザ・スパイア']) {
    ok(!rulesBody.includes(bad), `RULES_HTML に「${bad}」が含まれないこと`);
    ok(!glossBody.includes(bad), `GLOSSARY_HTML に「${bad}」が含まれないこと`);
  }
  // 「マッチ」はRULES_HTMLのみ禁止（§3-3: 決着の判定者はルール説明で明かさない。
  // 用語集・画面文言では既存どおり許容範囲＝GLOSSARY_HTMLには元々登場していない）
  ok(!rulesBody.includes('マッチ'), 'RULES_HTML に「マッチ」が含まれないこと');
  ok(!glossBody.includes('マッチ'), 'GLOSSARY_HTML に「マッチ」が含まれないこと');

  // §3-1: 一字一句指定文がRULES_HTMLに完全一致で含まれること
  const sec31Exact = '「前半」「後半」とは？\n札の強さは、2種類記録されている。GMがラウンドごとに「前半で判定」「後半で判定」のどちらかを宣言し、宣言された側の強さで勝負する。同じ札でも、前半と後半で強さが違うことがある。\nこの2つが何を指しているのかは、あえて伏せてある。\n遊びながら気づいてほしい。';
  ok(rulesBody.includes(sec31Exact), 'RULES_HTML に §3-1 の定義文が一字一句含まれること');
}

console.log('ネタばらし画面の前半/後半併記（§3-4）:');
{
  ok(/function halfPairHtml\(/.test(uiSrc), 'halfPairHtml() が定義されていること');
  ok(/scoreZen/.test(uiSrc) && /scoreKou/.test(uiSrc), 'halfPairHtml() が scoreZen/scoreKou を参照すること');
  const hotseatTL = /showTimeline\(\) \{[\s\S]*?\n  \},/.exec(uiSrc);
  const onlineTL = /showTimelineV\(\) \{[\s\S]*?\n  \},/.exec(uiSrc);
  ok(!!hotseatTL && /halfPairHtml\(/.test(hotseatTL[0]), 'ホットシート showTimeline() が halfPairHtml()（scoreZen/scoreKou併記）を呼ぶこと');
  ok(!!onlineTL && /halfPairHtml\(/.test(onlineTL[0]), 'オンライン showTimelineV() が halfPairHtml()（scoreZen/scoreKou併記）を呼ぶこと');

  // 非対象: roundEnd/finalのカードタイル生成・resultBoard・renderFinalV には現れないこと
  const noLeakTargets = [
    ['function renderRoundEnd\\(\\)[\\s\\S]*?\\n\\}', 'renderRoundEnd()'],
    ['function renderFinal\\(\\)[\\s\\S]*?\\n\\}', 'renderFinal()'],
    ['resultBoard\\(r\\)[\\s\\S]*?\\n  \\},', 'resultBoard()'],
    ['renderFinalV\\(v\\)[\\s\\S]*?\\n  \\},', 'renderFinalV()'],
  ];
  for (const [pat, label] of noLeakTargets) {
    const m = new RegExp(pat).exec(uiSrc);
    ok(!!m, `${label} を検出できること`);
    ok(!m || (!/scoreZen/.test(m[0]) && !/scoreKou/.test(m[0]) && !/halfPairHtml\(/.test(m[0])), `${label} に scoreZen/scoreKou/halfPairHtml() が現れないこと`);
  }
}

console.log('hostState の DB書き込み撤去（§2-2）:');
{
  ok(!/updates\['hostState'\]/.test(netSrc) && !/updates\.hostState\s*=/.test(netSrc),
    'net.js に hostState への DB書き込みが存在しないこと');
  ok(/self\.store\.set\(storeKey/.test(netSrc), 'net.js が hostState をローカルstoreに保存していること');
  ok(!netSrc.includes('${base}/hostState'), 'loadOrCreate() がDBのhostStateパスを参照しないこと（storeベースに置換済み）');
}

console.log('render()停止バグの再発防止（v2指示書対応）:');
{
  // gmAnswerPanel: RTDBが空answersをストリップしてもクラッシュしない防御が入っていること
  const gmPanelIdx = uiSrc.indexOf('gmAnswerPanel(v) {');
  const gmPanelWin = gmPanelIdx >= 0 ? uiSrc.slice(gmPanelIdx, gmPanelIdx + 400) : '';
  ok(/Object\.keys\(v\.gm\.answers \|\| \{\}\)/.test(gmPanelWin), 'gmAnswerPanel が Object.keys(v.gm.answers || {}) で防御していること');
  ok(/Object\.entries\(v\.gm\.answers \|\| \{\}\)/.test(gmPanelWin), 'gmAnswerPanel が Object.entries(v.gm.answers || {}) で防御していること');

  // render()例外の可視化: showCrashBanner が定義され、ホットシート/オンライン双方のrender()から呼ばれていること
  ok(/function showCrashBanner\(/.test(uiSrc), 'showCrashBanner() が定義されていること');
  const showCrashCallCount = (uiSrc.match(/showCrashBanner\(e\)/g) || []).length;
  ok(showCrashCallCount >= 2, `showCrashBanner(e) の呼び出しがホットシート/オンライン双方のrender()に存在すること (実:${showCrashCallCount})`);

  // 部屋コード常時表示（§5・v0.8.2工程1でGM専用から全ロールへ汎化）
  ok(/codeBadge/.test(uiSrc), '部屋コードバッジ(codeBadge)が実装されていること');
  ok(/saveLastGmCode/.test(uiSrc) && /loadLastGmCode/.test(uiSrc), '部屋コードのlocalStorage保持(saveLastGmCode/loadLastGmCode)が実装されていること');

  // __onlineSelfTest: fbStripを通してから描画していること（MockDBが空値を保存し続ける問題への対処）
  const selfTestIdx = uiSrc.indexOf('window.__onlineSelfTest = async function');
  const selfTestBody = selfTestIdx >= 0 ? uiSrc.slice(selfTestIdx, selfTestIdx + 6000) : '';
  ok(/function fbStrip\(/.test(selfTestBody), '__onlineSelfTest が fbStrip() を持つこと（MockDBの非ストリップ挙動を補うため）');
  ok(/coverage/.test(selfTestBody), '__onlineSelfTest がカバレッジ情報(coverage)を返すこと');
}

console.log('合成viewテストと自己診断の3値化（v0.8.1指示書対応）:');
{
  // rtdbFallback機構と5箇所への適用（#3 v.scores / #7 v.config.players / #8 v.myHand / #9 v.myReserved / #15 r.winners）
  ok(/function rtdbFallback\(/.test(uiSrc), 'rtdbFallback() が定義されていること');
  ok(/function safeScores\(/.test(uiSrc), 'safeScores()（#3 v.scores防御）が定義されていること');
  ok(/function safePlayers\(/.test(uiSrc), 'safePlayers()（#7 v.config.players防御）が定義されていること');
  ok(/function safeMyHand\(/.test(uiSrc), 'safeMyHand()（#8 v.myHand防御）が定義されていること');
  ok(/function safeMyReserved\(/.test(uiSrc), 'safeMyReserved()（#9 v.myReserved防御）が定義されていること');
  ok(/function safeWinners\(/.test(uiSrc), 'safeWinners()（#15 r.winners防御）が定義されていること');

  // __syntheticViewTest: 存在し、5箇所すべてを最低4パターンで検証していること
  ok(/window\.__syntheticViewTest = function/.test(uiSrc), '__syntheticViewTest() が定義されていること');
  const synthIdx = uiSrc.indexOf('window.__syntheticViewTest = function');
  const onlineSelfIdx2 = uiSrc.indexOf('window.__onlineSelfTest = async function');
  const synthBody = (synthIdx >= 0 && onlineSelfIdx2 > synthIdx) ? uiSrc.slice(synthIdx, onlineSelfIdx2) : '';
  ok(synthBody.length > 0, '__syntheticViewTest() の本体を抽出できること');
  for (const label of ["scoreV:v.scores", "scoreV:v.config.players", "committedProgress:v.config.players", "facesBoard:v.config.players", "renderFinalV:v.config.players", "renderPlayer:commit:v.myHand", "renderPlayer:decisionPick:v.myReserved", "resultBoard:r.winners", "renderPlayer:roundEnd:r.winners", "renderGM:roundEnd:r.winners", "gmAnswerPanel:v.gm.answers"]) {
    ok(synthBody.includes(label), `__syntheticViewTest() が "${label}" を検証していること`);
  }
  ok(/PATTERNS = \[/.test(synthBody) && /正常値/.test(synthBody) && /undefined/.test(synthBody) && /null/.test(synthBody), '正常値/undefined/null/空の4パターンが定義されていること');

  // __onlineSelfTest: status(pass/fail/inconclusive)・reasonを返し、冒頭でsyntheticを呼ぶこと
  const selfTestIdx2 = uiSrc.indexOf('window.__onlineSelfTest = async function');
  const selfTestBody2 = selfTestIdx2 >= 0 ? uiSrc.slice(selfTestIdx2, selfTestIdx2 + 8000) : '';
  ok(/__syntheticViewTest\(\)/.test(selfTestBody2), '__onlineSelfTest() が冒頭で __syntheticViewTest() を呼ぶこと');
  ok(/'pass'/.test(selfTestBody2) && /'fail'/.test(selfTestBody2) && /'inconclusive'/.test(selfTestBody2), "__onlineSelfTest() が status に 'pass'/'fail'/'inconclusive' の3値を使うこと");
  ok(/reason/.test(selfTestBody2), '__onlineSelfTest() が reason フィールドを返すこと');
  ok(/ok: status === 'pass'/.test(selfTestBody2), 'ok が status===\'pass\'と等価に定義されていること（後方互換）');
}

console.log('版番号バッジがv0.8.2であること:');
{
  ok(/const VER = 'v0\.8\.2';/.test(uiSrc), "const VER = 'v0.8.2'; であること");
}

console.log('障害の可視化（診断ログ・不活性理由表示・部屋コード常時表示 / v0.8.2指示書対応）:');
{
  // 工程0.5-b: 診断ログのリングバッファ
  ok(/const DiagLog = \{/.test(uiSrc), 'DiagLog リングバッファが定義されていること');
  ok(/function makeDiagStore\(/.test(uiSrc), 'makeDiagStore() が定義されていること');
  const diagPushKinds = ['room:create', 'room:join', 'seat:claim', 'view:received', 'startGame:click', 'startGame:success', 'startGame:error', 'gmResume:attempt', 'gmHost:start', 'gmHost:success', 'startButton:judge', 'rtdb-fallback'];
  for (const kind of diagPushKinds) {
    ok(uiSrc.includes(`'${kind}'`), `DiagLog.push で "${kind}" イベント種別が記録されていること`);
  }
  // 既存のRTDBフォールバック機構がDiagLogにも書くこと（タイミング変更なしの結線確認）
  const fallbackIdx = uiSrc.indexOf('function rtdbFallback(');
  const fallbackBody = fallbackIdx >= 0 ? uiSrc.slice(fallbackIdx, fallbackIdx + 400) : '';
  ok(/DiagLog\.push\('rtdb-fallback'/.test(fallbackBody), 'rtdbFallback() が DiagLog にも記録すること');

  // 工程0.5-a: 開始ボタン不活性理由の名指し表示
  ok(/missingReasons\(\)\s*\{/.test(uiSrc), 'missingReasons() が定義されていること');
  const renderWaitIdx = uiSrc.indexOf('renderWait() {');
  const renderWaitBody = renderWaitIdx >= 0 ? uiSrc.slice(renderWaitIdx, renderWaitIdx + 2500) : '';
  ok(/開始できません/.test(renderWaitBody), 'renderWait() が不活性理由バナー「開始できません」を表示すること');
  ok(/this\.missingReasons\(\)/.test(renderWaitBody), 'renderWait() が missingReasons() を参照すること');

  // 工程0.5-c: 診断ログの書き出しボタン（待機ロビー・ゲーム中GM操作の両方から到達できること）
  ok(/async exportDiagLog\(\)/.test(uiSrc), 'exportDiagLog() が定義されていること');
  ok(/Online\.exportDiagLog\(\)/.test(renderWaitBody), '待機ロビー画面(renderWait())に診断ログ書き出しボタンがあること');
  const ctrlBarIdx = uiSrc.indexOf('const ctrlBar = ');
  const ctrlBarLine = ctrlBarIdx >= 0 ? uiSrc.slice(ctrlBarIdx, ctrlBarIdx + 900) : '';
  ok(/Online\.exportDiagLog\(\)/.test(ctrlBarLine), 'ゲーム中GM操作バー(ctrlBar)に診断ログ書き出しボタンがあること');

  // 工程1: 部屋コードバッジがGM専用ではなく全ロール共通の条件になっていること
  const codeBadgeLineIdx = uiSrc.indexOf('const codeBadge = ');
  ok(codeBadgeLineIdx >= 0, 'codeBadge の定義行を検出できること');
  const codeBadgeLine = codeBadgeLineIdx >= 0 ? uiSrc.slice(codeBadgeLineIdx, uiSrc.indexOf('\n', codeBadgeLineIdx)) : '';
  ok(codeBadgeLine.length > 0 && !/this\.role === 'gm'/.test(codeBadgeLine), 'codeBadge がGMロール限定条件を含まないこと（全ロール共通化）');
  ok(/function copyCode\(/.test(uiSrc) || /copyCode\(\)\s*\{/.test(uiSrc), 'copyCode() が定義されていること');

  // 工程2: 前回の部屋コード記憶（プレイヤー側にも汎用の入り口があること）
  ok(/saveLastCode\(/.test(uiSrc) && /loadLastCode\(/.test(uiSrc), '汎用の部屋コード記憶(saveLastCode/loadLastCode)が実装されていること');
  ok(/前回の部屋（/.test(uiSrc), '「前回の部屋に戻る」エントリーポイントの文言が存在すること');
  const joinFormIdx = uiSrc.indexOf('renderJoinForm() {');
  const joinFormBody = joinFormIdx >= 0 ? uiSrc.slice(joinFormIdx, joinFormIdx + 500) : '';
  ok(/this\.loadLastCode\(\)/.test(joinFormBody), 'renderJoinForm() が loadLastCode() で参加コード欄を事前入力すること');
}

console.log(`\n==== static結果: ${passed} passed, ${failed} failed ====`);
process.exit(failed ? 1 : 0);
