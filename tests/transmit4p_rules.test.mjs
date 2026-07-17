import fs from "node:fs";
import test, { after, before, beforeEach } from "node:test";
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";

const HTML = fs.readFileSync("proto/transmitcore_4p_v0.html", "utf8");
const VER = HTML.match(/const VER = "([^"]+)"/)[1];

const PROJECT_ID = "transmit4p-v0-test";
const CODE = "ABC234";
const HOST = "host-uid-0001";
const P2 = "player-uid-0002";
const P3 = "player-uid-0003";
const P4 = "player-uid-0004";
const OUTSIDER = "outsider-uid-0005";
let env;

function db(uid) {
  return uid ? env.authenticatedContext(uid).database() : env.unauthenticatedContext().database();
}
function room(database, path = "") {
  return database.ref(`transmit4pRoomsV0/${CODE}${path ? `/${path}` : ""}`);
}
function meta(phase = "lobby") {
  return { hostUid: HOST, phase, mode: "human4", drainSpeed: "off", hintDrainToggle: "equal", version: VER, createdAt: 1 };
}
function seat(uid, isNpc = false) {
  return { uid, name: "P", lastSeen: 1, isNpc };
}

before(async () => {
  env = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    database: { rules: fs.readFileSync("firebase/transmit4p_rules.json", "utf8") },
  });
});
after(async () => { await env.cleanup(); });
beforeEach(async () => { await env.clearDatabase(); });

test("meta: unauthenticated cannot read or write", async () => {
  await assertFails(room(db(null), "meta").get());
  await assertFails(room(db(null), "meta").set(meta()));
});

test("meta: first writer becomes host (create-once), phase must be lobby", async () => {
  await assertSucceeds(room(db(HOST), "meta").set(meta("lobby")));
  await assertFails(room(db(P2), "meta").set(meta("lobby"))); // already exists, not host
});

test("meta: only host can update after creation; non-host cannot change hostUid", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => { await room(ctx.database(), "meta").set(meta("lobby")); });
  await assertFails(room(db(P2), "meta").update({ phase: "playing" }));
  await assertSucceeds(room(db(HOST), "meta").update({ ...meta("lobby"), phase: "setup" }));
});

test("seats: claim empty seat only during lobby, one seat per uid", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => { await room(ctx.database(), "meta").set(meta("lobby")); });
  await assertSucceeds(room(db(HOST), "seats/0").set(seat(HOST)));
  await assertSucceeds(room(db(P2), "seats/1").set(seat(P2)));
  // P2 cannot also claim seat 2 (already seated at 1)
  await assertFails(room(db(P2), "seats/2").set(seat(P2)));
  // Cannot write someone else's uid into a seat
  await assertFails(room(db(P3), "seats/2").set(seat(P4)));
});

test("seats: cannot claim once phase is playing", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => { await room(ctx.database(), "meta").set(meta("playing")); });
  await assertFails(room(db(P3), "seats/2").set(seat(P3)));
});

test("secrets: only host can read or write, never other players", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").set(meta("playing"));
    await room(ctx.database(), "seats/0").set(seat(HOST));
  });
  await assertSucceeds(room(db(HOST), "secrets").set({ axisA: "体重", axisB: "速さ", createdAt: 1 }));
  await assertFails(room(db(P2), "secrets").get());
  await assertFails(room(db(P2), "secrets").set({ axisA: "体重", axisB: "速さ", createdAt: 1 }));
});

test("private/{uid}: owner can read/write own node; other non-host players cannot read it (secrecy boundary)", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").set(meta("playing"));
  });
  await assertSucceeds(room(db(P2), `private/${P2}`).set({ axis: "体重" }));
  await assertSucceeds(room(db(P2), `private/${P2}`).get());
  // Team B's observer (P3) must NOT be able to read Team A's observer's (P2) private axis
  await assertFails(room(db(P3), `private/${P2}`).get());
  // Host CAN read anyone's private data (needed to relay/deal)
  await assertSucceeds(room(db(HOST), `private/${P2}`).get());
  // A player cannot write into someone else's private node
  await assertFails(room(db(P3), `private/${P2}`).set({ axis: "危険度" }));
});

test("game: readable by anyone once room exists; writable only by host", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").set(meta("playing"));
  });
  await assertSucceeds(room(db(P2), "game").get());
  await assertFails(room(db(P2), "game").set({ roundNum: 1 }));
  await assertSucceeds(room(db(HOST), "game").set({ roundNum: 1 }));
});

test("reveal: only readable/writable while phase is ended, and only by host", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").set(meta("playing"));
  });
  await assertFails(room(db(HOST), "reveal").set({ axisA: "体重", axisB: "速さ", createdAt: 1 }));
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").update({ phase: "ended" });
  });
  await assertSucceeds(room(db(HOST), "reveal").set({ axisA: "体重", axisB: "速さ", createdAt: 1 }));
  await assertFails(room(db(P2), "reveal").set({ axisA: "体重", axisB: "速さ", createdAt: 1 }));
  await assertSucceeds(room(db(P2), "reveal").get());
});

test("root isolation: legacy/other top-level paths remain closed", async () => {
  await assertFails(db(HOST).ref("rooms").set({ x: 1 }));
  await assertFails(db(HOST).ref("seriRoomsV2").set({ x: 1 }));
});

test("outsider (no seat at all) can still read public game/meta but not private/secrets", async () => {
  await env.withSecurityRulesDisabled(async (ctx) => {
    await room(ctx.database(), "meta").set(meta("playing"));
    await room(ctx.database(), "private/"+P2).set({axis:"体重"});
  });
  await assertSucceeds(room(db(OUTSIDER), "meta").get());
  await assertFails(room(db(OUTSIDER), `private/${P2}`).get());
  await assertFails(room(db(OUTSIDER), "secrets").get());
});
