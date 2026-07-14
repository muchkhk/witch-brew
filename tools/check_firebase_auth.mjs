import fs from "node:fs";

function extractApiKey(html) {
  const m = html.match(/FIREBASE_CONFIG\s*=\s*(\{[\s\S]*?\});/);
  if (!m) throw new Error("FIREBASE_CONFIGが見つかりません");
  const config = new Function(`return ${m[1]}`)();
  if (!config.apiKey) throw new Error("apiKeyが見つかりません");
  return config.apiKey;
}

async function main() {
  const html = fs.readFileSync("seri.html", "utf8");
  const apiKey = extractApiKey(html);

  const signUpRes = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ returnSecureToken: true }),
  });
  const signUpBody = await signUpRes.json();

  if (!signUpRes.ok || !signUpBody.idToken) {
    console.error(`FAIL: signUp http=${signUpRes.status}`);
    if (signUpBody.error) console.error(`  error: ${signUpBody.error.message}`);
    process.exitCode = 1;
    return;
  }

  const uid = signUpBody.localId;
  const idToken = signUpBody.idToken;
  console.log(`signUp: OK http=${signUpRes.status} uid=...${uid.slice(-4)}`);

  const delRes = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:delete?key=${apiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idToken }),
  });
  const delBody = await delRes.json();

  if (!delRes.ok) {
    console.error(`FAIL: delete http=${delRes.status}`);
    if (delBody.error) console.error(`  error: ${delBody.error.message}`);
    process.exitCode = 1;
    return;
  }

  console.log(`delete: OK http=${delRes.status}`);
  console.log("RESULT: PASS");
}

main().catch(e => {
  console.error(`FAIL: ${e.message}`);
  process.exitCode = 1;
});
