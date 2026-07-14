import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

function extractConfig(html) {
  const m = html.match(/FIREBASE_CONFIG\s*=\s*(\{[\s\S]*?\});/);
  assert.ok(m, "FIREBASE_CONFIGが見つかりません");
  return new Function(`return ${m[1]}`)();
}

const seriHtml = fs.readFileSync("seri.html", "utf8");
const witchHtml = fs.readFileSync("witch.html", "utf8");

test("seri v2のFIREBASE_CONFIGがパース可能である", () => {
  assert.doesNotThrow(() => extractConfig(seriHtml));
});

const seriConfig = extractConfig(seriHtml);
const witchConfig = extractConfig(witchHtml);

test("projectIdがboadgame2である", () => {
  assert.equal(seriConfig.projectId, "boadgame2");
});

test("databaseURLがboadgame2-default-rtdbを含む", () => {
  assert.match(seriConfig.databaseURL, /boadgame2-default-rtdb/);
});

test("authDomainがboadgame2を含む", () => {
  assert.match(seriConfig.authDomain, /boadgame2/);
});

test("storageBucketがboadgame2を含む", () => {
  assert.match(seriConfig.storageBucket, /boadgame2/);
});

test("apiKeyが空でなくプレースホルダ的文字列を含まない", () => {
  assert.ok(seriConfig.apiKey && seriConfig.apiKey.length > 0);
  assert.doesNotMatch(seriConfig.apiKey, /YOUR_|XXX|<|TODO/i);
});

test("seriのapiKeyがwitchのapiKeyと異なる", () => {
  assert.notEqual(seriConfig.apiKey, witchConfig.apiKey);
});

test("witchのprojectIdがbalance-simulator-firebaseである", () => {
  assert.equal(witchConfig.projectId, "balance-simulator-firebase");
});
