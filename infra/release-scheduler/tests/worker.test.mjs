// SPDX-License-Identifier: GPL-3.0-or-later
// Real WebCrypto with ephemeral test keys; GitHub effects are explicit fixtures.
import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import worker, { appJwt, dispatch, TARGET } from "../worker.mjs";

const now = 1800000000;
const key = await webcrypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const pem = `-----BEGIN PRIVATE KEY-----\n${Buffer.from(await webcrypto.subtle.exportKey("pkcs8", key.privateKey)).toString("base64")}\n-----END PRIVATE KEY-----\n`;
const env = { GITHUB_APP_CLIENT_ID: "Iv1.fixture", GITHUB_APP_INSTALLATION_ID: "11",
  GITHUB_REPOSITORY_ID: "22", GITHUB_OWNER_ID: "33", GITHUB_APP_PRIVATE_KEY: pem };
const token = "fixture_installation_token_never_a_real_credential";
const mint = () => ({ token, permissions: { actions: "write", metadata: "read" },
  expires_at: new Date((now + 3600) * 1000).toISOString(),
  repositories: [{ id: 22, full_name: "assboxai/assbox" }] });
const repository = () => ({ id: 22, owner: { id: 33 }, full_name: "assboxai/assbox", default_branch: "master", private: false, fork: false });
const workflow = () => ({ path: ".github/workflows/release.yml", state: "active" });
const accepted = () => ({ workflow_run_id: 44,
  run_url: "https://api.github.com/repos/assboxai/assbox/actions/runs/44",
  html_url: "https://github.com/assboxai/assbox/actions/runs/44" });
function fixture(overrides = {}) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, ...options });
    assert.equal(options.redirect, "error");
    assert.ok(options.signal instanceof AbortSignal);
    let stage;
    if (url.endsWith("/access_tokens")) stage = "token";
    else if (url.endsWith("/installation/token")) stage = "revoke";
    else if (url.endsWith("/dispatches")) stage = "dispatch";
    else if (url.endsWith("/release.yml")) stage = "workflow";
    else if (url.endsWith("/assbox")) stage = "repository";
    else throw new Error("unexpected effect URL");
    if (stage !== "token") assert.equal(options.headers.Authorization, `Bearer ${token}`);
    if (overrides[stage]) return overrides[stage](url, options);
    if (stage === "token") return Response.json(mint(), { status: 201 });
    if (stage === "repository") return Response.json(repository());
    if (stage === "workflow") return Response.json(workflow());
    if (stage === "dispatch") return Response.json(accepted());
    return new Response(null, { status: 204 });
  };
  return { calls, fetcher };
}
const execute = (f, values = env) => dispatch(values, { fetcher: f.fetcher, subtle: webcrypto.subtle, now });

test("JWT is a genuine RS256 signature with bounded GitHub claims", async () => {
  const value = await appJwt(env, now, webcrypto.subtle);
  const [h, p, signature] = value.split(".");
  assert.deepEqual(JSON.parse(Buffer.from(h, "base64url")), { alg: "RS256", typ: "JWT" });
  assert.deepEqual(JSON.parse(Buffer.from(p, "base64url")), { iat: now - 60, exp: now + 300, iss: "Iv1.fixture" });
  assert.ok(await webcrypto.subtle.verify("RSASSA-PKCS1-v1_5", key.publicKey,
    Buffer.from(signature, "base64url"), new TextEncoder().encode(`${h}.${p}`)));
  assert.equal(await webcrypto.subtle.verify("RSASSA-PKCS1-v1_5", key.publicKey,
    Buffer.from(signature, "base64url"), new TextEncoder().encode(`${h}.${p}x`)), false);
});

test("dispatch is fixed master/no-inputs, scoped to one repo, and revokes its token", async () => {
  const f = fixture();
  assert.deepEqual(await execute(f), { accepted: true, runId: 44 });
  assert.equal(f.calls.length, 5);
  assert.deepEqual(JSON.parse(f.calls[0].body), { repository_ids: [22], permissions: { actions: "write" } });
  assert.deepEqual(JSON.parse(f.calls[3].body), { ref: "master" });
  assert.equal(f.calls[3].url, "https://api.github.com/repos/assboxai/assbox/actions/workflows/release.yml/dispatches");
  assert.equal(f.calls[4].method, "DELETE");
});

test("legacy 204 dispatch response means accepted, not release success", async () => {
  const f = fixture({ dispatch: () => new Response(null, { status: 204 }) });
  assert.deepEqual(await execute(f), { accepted: true, runId: null });
});

test("disabled workflow is an emergency stop, never enabled or dispatched", async () => {
  for (const state of ["disabled_manually", "disabled_inactivity", "deleted"]) {
    const f = fixture({ workflow: () => Response.json({ ...workflow(), state }) });
    await assert.rejects(execute(f), /workflow-disabled-or-changed/);
    assert.equal(f.calls.filter(c => c.url.endsWith("/dispatches")).length, 0);
    assert.equal(f.calls.some(c => c.method === "PUT"), false);
    assert.equal(f.calls.at(-1).method, "DELETE");
  }
});

test("configuration and PKCS8 key errors cannot cause network calls", async () => {
  for (const patch of [{ GITHUB_APP_INSTALLATION_ID: "0" }, { GITHUB_OWNER_ID: "../x" },
    { GITHUB_REPOSITORY_ID: "9007199254740992" }, { GITHUB_APP_CLIENT_ID: "UNPROVISIONED" },
    { GITHUB_APP_PRIVATE_KEY: "-----BEGIN RSA PRIVATE KEY-----\nAA==\n-----END RSA PRIVATE KEY-----" },
    { GITHUB_APP_PRIVATE_KEY: "-----BEGIN PRIVATE KEY-----\nAA==\n-----END PRIVATE KEY-----\n" }]) {
    const f = fixture(); await assert.rejects(execute(f, { ...env, ...patch }));
    assert.equal(f.calls.length, 0);
  }
});

test("overbroad or expired installation tokens are rejected and revoked", async () => {
  for (const patch of [{ permissions: { actions: "write", contents: "write" } },
    { permissions: { actions: "read" } }, { expires_at: "nonsense" },
    { expires_at: new Date(now * 1000).toISOString() },
    { expires_at: new Date((now + 4000) * 1000).toISOString() },
    { repositories: [{ id: 99, full_name: "someone/else" }] }]) {
    const f = fixture({ token: () => Response.json({ ...mint(), ...patch }, { status: 201 }) });
    await assert.rejects(execute(f));
    assert.equal(f.calls.length, 2);
    assert.equal(f.calls.at(-1).method, "DELETE");
  }
});

test("repository ID, owner, default branch and workflow path are rechecked", async () => {
  for (const patch of [{ id: 99 }, { owner: { id: 1 } }, { default_branch: "other" }, { fork: true }, { private: true }]) {
    const f = fixture({ repository: () => Response.json({ ...repository(), ...patch }) });
    await assert.rejects(execute(f), /repository-identity/);
    assert.equal(f.calls.some(c => c.url.endsWith("/dispatches")), false);
  }
  const f = fixture({ workflow: () => Response.json({ ...workflow(), path: ".github/workflows/other.yml" }) });
  await assert.rejects(execute(f), /workflow-disabled-or-changed/);
});

test("API failures do not leak response bodies or retry an ambiguous dispatch", async () => {
  for (const status of [401, 403, 404, 422, 429, 500, 503]) {
    const f = fixture({ dispatch: () => new Response(token, { status }) });
    await assert.rejects(execute(f), error => !error.message.includes(token) && error.status === status);
    assert.equal(f.calls.filter(c => c.url.endsWith("/dispatches")).length, 1);
  }
  const f = fixture({ dispatch: () => { throw new Error(token); } });
  await assert.rejects(execute(f), error => !error.message.includes(token));
  assert.equal(f.calls.filter(c => c.url.endsWith("/dispatches")).length, 1);
});

test("excessive/malformed API data and unexpected dispatch shape fail closed", async () => {
  for (const response of [() => new Response("{"), () => new Response(" ".repeat(65537)),
    () => Response.json({ ...accepted(), workflow_run_id: 0 }),
    () => Response.json({ ...accepted(), run_url: "https://untrusted.example/" })]) {
    const f = fixture({ dispatch: response }); await assert.rejects(execute(f));
  }
});

test("an HTTP request never triggers the scheduler", async () => {
  const result = await worker.fetch(new Request("https://example/dispatch", { method: "POST", body: "{}" }), env);
  assert.equal(result.status, 404);
});

test("unexpected cron is rejected before any credential operation", async () => {
  let stopped = false;
  await assert.rejects(worker.scheduled({ cron: "* * * * *", noRetry: () => { stopped = true; } }, env), /unexpected-cron/);
  assert.equal(stopped, true);
  assert.equal(TARGET.cron, "23 7 * * *");
});
