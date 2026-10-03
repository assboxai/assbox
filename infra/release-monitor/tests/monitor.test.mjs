// SPDX-License-Identifier: GPL-3.0-or-later
import test from "node:test";
import assert from "node:assert/strict";
import worker, { assessIdentity, assessRuns, assessRelease, historyHead, check, HISTORY_PAGES, RUN_GRACE, QUEUE_GRACE, BOOTSTRAP_FRESHNESS } from "../worker.mjs";
const now = 1800000000;
const iso = offset => new Date((now + offset) * 1000).toISOString();
const env = { GITHUB_REPOSITORY_ID: "22", GITHUB_OWNER_ID: "33" };
const repo = { id: 22, owner: { id: 33 }, full_name: "assboxai/assbox", default_branch: "master", private: false, fork: false };
const workflow = { id: 44, state: "active", path: ".github/workflows/release.yml" };
const run = { id: 55, status: "completed", conclusion: "success", head_branch: "master", event: "workflow_dispatch",
  repository: { id: 22 }, workflow_id: 44, created_at: iso(-3600), run_started_at: iso(-3500), updated_at: iso(-1800) };
const bootstrap = { id: 66, state: "active", path: ".github/workflows/bootstrap.yml" };
const bootstrapRun = { ...run, id: 77, workflow_id: 66 };
const list = r => ({ workflow_runs: r ? [r] : [] });
const assess = (newest = run, success = run) => assessRuns(repo, workflow, list(newest), list(success), now);
const record = number => ({ id: number, tag_name: `r-${number}`, immutable: true, draft: false, prerelease: false });
const tag = number => ({ name: `r-${number}`, commit: { sha: "a".repeat(40) } });
const manifest = { schema: 3, protocol: 3, channel: "stable", tag: "r-1000", issuedAt: now - 1000, expiresAt: now - 1000 + 604800 };

function fixture(changes = {}) {
  const replies = new Map([
    ["/repos/assboxai/assbox", repo],
    ["/repos/assboxai/assbox/actions/workflows/release.yml", workflow],
    ["/repos/assboxai/assbox/actions/workflows/release.yml/runs?branch=master&per_page=1", list(changes.run ?? run)],
    ["/repos/assboxai/assbox/actions/workflows/release.yml/runs?branch=master&status=success&per_page=1", list(run)],
    ["/repos/assboxai/assbox/actions/workflows/bootstrap.yml", changes.bootstrap ?? bootstrap],
    ["/repos/assboxai/assbox/actions/workflows/bootstrap.yml/runs?branch=master&per_page=1", list(changes.bootstrapRun ?? bootstrapRun)],
    ["/repos/assboxai/assbox/actions/workflows/bootstrap.yml/runs?branch=master&status=success&per_page=1", list(changes.bootstrapSuccess ?? bootstrapRun)],
    ["/repos/assboxai/assbox/releases?per_page=100&page=1", changes.releases ?? [record(1), record(1000)]],
    ["/repos/assboxai/assbox/tags?per_page=100&page=1", changes.tags ?? [tag(1), tag(1000)]],
    ["/repos/assboxai/assbox/releases/latest", changes.latest ?? record(1000)],
    ["/assboxai/assbox/releases/download/r-1000/release.json", changes.manifest ?? manifest],
  ]);
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push(url);
    assert.equal(options.method, undefined);
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.redirect, "manual");
    assert.ok(url.startsWith("https://"));
    const u = new URL(url); const key = u.pathname + u.search;
    assert.ok(replies.has(key), `unexpected read ${key}`);
    return Response.json(replies.get(key));
  };
  return { fetcher, calls, replies };
}

test("current successful run and release head with expiry headroom are healthy", async () => {
  assert.equal(assessIdentity(env, repo, workflow), null);
  assert.equal(assess(), null);
  assert.equal(assessRelease(record(1000), record(1000), manifest, now), null);
  const f = fixture(); assert.equal(await check(env, f.fetcher, now), null); assert.equal(f.calls.length, 11);
});
test("a previous success cannot hide a completed failure/cancellation", () => {
  for (const conclusion of ["failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "startup_failure", null]) {
    assert.equal(assess({ ...run, conclusion }), "latest-run-failed");
  }
});
test("latest-run failures are returned before release freshness can hide them", async () => {
  const f = fixture({ run: { ...run, conclusion: "failure" } });
  assert.equal(await check(env, f.fetcher, now), "latest-run-failed");
  assert.equal(f.calls.length, 4);
});
test("latest and successful run identities, shapes and times are required", () => {
  assert.equal(assess(null), "latest-run-invalid-or-missing");
  assert.equal(assess(run, null), "no-successful-run");
  for (const patch of [{ head_branch: "other" }, { event: "push" }, { workflow_id: 99 }, { repository: { id: 99 } }, { id: null }]) {
    assert.equal(assess({ ...run, ...patch }), "latest-run-invalid-or-missing");
    assert.equal(assess(run, { ...run, ...patch }), "no-successful-run");
  }
  for (const patch of [{ created_at: "bad" }, { updated_at: iso(3600) }, { created_at: iso(-1000) }]) {
    assert.equal(assess({ ...run, ...patch }), "run-time-invalid");
  }
  assert.equal(assess(run, { ...run, created_at: iso(-37 * 3600 - 100), run_started_at: iso(-37 * 3600 - 50), updated_at: iso(-37 * 3600) }), "run-stale");
  assert.equal(assessRuns(repo, workflow, { workflow_runs: [run, run] }, list(run), now), "latest-run-invalid-or-missing");
});
test("queue and running grace periods are bounded and cannot be refreshed by updated_at", () => {
  for (const status of ["queued", "pending", "waiting", "requested"]) {
    const active = { ...run, status, conclusion: null, created_at: iso(-600), updated_at: iso(-100) };
    assert.equal(assess(active), null);
    assert.equal(assess({ ...active, created_at: iso(-QUEUE_GRACE - 1) }), "run-queue-stalled");
  }
  const running = { ...run, status: "in_progress", conclusion: null };
  assert.equal(assess(running), null);
  assert.equal(assess({ ...running, created_at: iso(-RUN_GRACE - 100), run_started_at: iso(-RUN_GRACE - 1), updated_at: iso(-1) }), "run-in-progress-stalled");
  assert.equal(assess({ ...running, run_started_at: null }), "run-time-invalid");
  assert.equal(assess({ ...running, status: "unknown" }), "latest-run-invalid-or-missing");
  assert.equal(assess(running, null), "no-successful-run");
});
test("unprovisioned IDs, changed ownership and disabled workflow are unhealthy", async () => {
  assert.equal(assessIdentity({ ...env, GITHUB_OWNER_ID: "0" }, repo, workflow), "unprovisioned");
  assert.equal(assessIdentity(env, { ...repo, id: 99 }, workflow), "repository-changed");
  assert.equal(assessIdentity(env, repo, { ...workflow, state: "disabled_manually" }), "workflow-disabled-or-changed");
  assert.equal(await check({ ...env, GITHUB_OWNER_ID: "0" }, () => { throw new Error("must not call"); }, now), "unprovisioned");
});
test("numeric history is independent of API order, latest and Number precision", () => {
  assert.equal(historyHead([record(100), record(9), record(1)], [tag(9), tag(1), tag(100)]).tag_name, "r-100");
  const releases = [record(1), { ...record(2), tag_name: "r-9007199254740992" }, { ...record(3), tag_name: "r-9007199254740993" }];
  const tags = releases.map(r => ({ ...tag(1), name: r.tag_name }));
  assert.equal(historyHead(releases, tags).tag_name, "r-9007199254740993");
});
test("orphan, malformed, mutable, duplicate and deleted-genesis history fails", () => {
  const releases = [record(1), record(1000)], tags = [tag(1), tag(1000)];
  for (const [r, t] of [[[], []], [releases.slice(1), tags.slice(1)], [releases, tags.slice(1)],
    [releases.slice(0, 1), tags], [releases.concat(record(1)), tags], [releases, tags.concat(tag(1))],
    [[record(1), { ...record(1000), id: 1 }], tags], [[record(1), null], tags],
    [releases, [tag(1), { ...tag(1000), commit: { sha: "bad" } }]]]) {
    assert.throws(() => historyHead(r, t), /release-history-invalid/);
  }
  for (const patch of [{ immutable: false }, { draft: true }, { prerelease: true }, { tag_name: "r-001" }, { tag_name: "other" }]) {
    assert.throws(() => historyHead([record(1), { ...record(1000), ...patch }], tags), /release-history-invalid/);
  }
});
test("source tags and non-Assbox releases do not alter the established channel", async () => {
  const releases = [record(1), record(1000)], tags = [tag(1), tag(1000)];
  const sourceRelease = { tag_name: "v0.1.0", id: 9999, immutable: false, draft: false, prerelease: true };
  const sourceTag = { name: "v0.1.0", commit: { sha: "b".repeat(40) } };
  for (const [r, t] of [[releases, [...tags, sourceTag]], [[sourceRelease, ...releases], tags],
                        [[sourceRelease, ...releases], [...tags, sourceTag]]]) {
    assert.equal(historyHead(r, t).tag_name, "r-1000");
    const f = fixture({ releases: r, tags: t });
    assert.equal(await check(env, f.fetcher, now), null);
    assert.equal(f.calls.length, 11);
    assert.ok(f.calls.at(-1).endsWith("/r-1000/release.json"));
  }
});
test("unrelated inventories cannot replace genesis, hide orphans or become latest", async () => {
  const sourceRelease = { tag_name: "v0.1.0", id: 9999 };
  const sourceTag = { name: "v0.1.0" };
  for (const [r, t] of [[[sourceRelease], [sourceTag]], [[record(1000), sourceRelease], [tag(1000), sourceTag]],
                        [[record(1), sourceRelease], [tag(1), tag(1000), sourceTag]],
                        [[record(1), record(1000), sourceRelease], [tag(1), sourceTag]]]) {
    assert.throws(() => historyHead(r, t), /release-history-invalid/);
  }
  const f = fixture({ latest: { ...record(9999), tag_name: "v0.1.0" } });
  assert.equal(await check(env, f.fetcher, now), "latest-not-history-head");
});
test("r-prefix filtering never discards malformed reserved release identities", () => {
  for (const bad of ["r-", "r-invalid", "r-0", "r-01", "r-1x", "r-10000000000000000"]) {
    assert.throws(() => historyHead([record(1), { ...record(2), tag_name: bad }], [tag(1)]), /release-history-invalid/);
    assert.throws(() => historyHead([record(1)], [tag(1), { ...tag(2), name: bad }]), /release-history-invalid/);
  }
});
test("records must have string identities before namespace filtering", () => {
  for (const bad of [null, [], {}, { tag_name: null }, { tag_name: 12 }]) {
    assert.throws(() => historyHead([record(1), bad], [tag(1)]), /release-history-invalid/);
  }
  for (const bad of [null, [], {}, { name: null }, { name: 12 }]) {
    assert.throws(() => historyHead([record(1)], [tag(1), bad]), /release-history-invalid/);
  }
});
test("namespace filtering waits for complete raw inventories, not a filtered short page", async () => {
  const releases = Array.from({ length: 100 }, (_, i) => ({ tag_name: `v${i}` }));
  const tags = releases.map(r => ({ name: r.tag_name }));
  const f = fixture({ releases, tags });
  f.replies.set("/repos/assboxai/assbox/releases?per_page=100&page=2", [record(1), record(1000)]);
  f.replies.set("/repos/assboxai/assbox/tags?per_page=100&page=2", [tag(1), tag(1000)]);
  assert.equal(await check(env, f.fetcher, now), null);
  assert.equal(f.calls.filter(url => url.includes("page=2")).length, 2);
});
test("ignored source tags still consume the raw observation bound", async () => {
  const f = fixture();
  for (let page = 1; page <= HISTORY_PAGES; page++) {
    f.replies.set(`/repos/assboxai/assbox/releases?per_page=100&page=${page}`,
      Array.from({ length: 100 }, (_, i) => ({ tag_name: `v${page}-${i}` })));
  }
  await assert.rejects(check(env, f.fetcher, now), /history-observation-limit/);
});
test("backward latest never reports healthy even if that older manifest is unexpired", async () => {
  const f = fixture({ latest: record(1) });
  assert.equal(await check(env, f.fetcher, now), "latest-not-history-head");
  assert.ok(!f.calls.some(url => url.includes("/releases/download/")));
  assert.equal(assessRelease(record(1), record(1000), { ...manifest, tag: "r-1" }, now), "latest-not-history-head");
});
test("history fetches all pages before selecting the head", async () => {
  const releases = Array.from({ length: 101 }, (_, i) => record(i + 1));
  const tags = releases.map(r => tag(r.id));
  const f = fixture({ releases: releases.slice(0, 100), tags: tags.slice(0, 100), latest: record(101), manifest: { ...manifest, tag: "r-101" } });
  f.replies.set("/repos/assboxai/assbox/releases?per_page=100&page=2", releases.slice(100));
  f.replies.set("/repos/assboxai/assbox/tags?per_page=100&page=2", tags.slice(100));
  f.replies.set("/assboxai/assbox/releases/download/r-101/release.json", { ...manifest, tag: "r-101" });
  assert.equal(await check(env, f.fetcher, now), null);
  assert.equal(f.calls.filter(url => url.includes("page=2")).length, 2);
});
test("page overflow or exhaustion cannot certify a partial history", async () => {
  const f = fixture({ releases: Array.from({ length: 101 }, (_, i) => record(i + 1)) });
  await assert.rejects(check(env, f.fetcher, now), /release-history-invalid/);
  const g = fixture();
  for (let page = 1; page <= HISTORY_PAGES; page++) {
    g.replies.set(`/repos/assboxai/assbox/releases?per_page=100&page=${page}`, Array.from({ length: 100 }, (_, i) => record((page - 1) * 100 + i + 1)));
  }
  await assert.rejects(check(env, g.fetcher, now), /history-observation-limit/);
  assert.equal(g.calls.filter(url => url.includes("/releases?")).length, HISTORY_PAGES);
});
test("expiry alert precedes an authorization outage; malformed metadata is refused", () => {
  assert.equal(assessRelease(record(1000), record(1000), { ...manifest, issuedAt: now - 6 * 86400, expiresAt: now + 86400 }, now), "release-expiry-near");
  for (const patch of [{ tag: "r-42" }, { protocol: 1 }, { issuedAt: -1 }, { issuedAt: now + 3600 }, { expiresAt: manifest.expiresAt + 1 }]) {
    assert.equal(assessRelease(record(1000), record(1000), { ...manifest, ...patch }, now), "release-metadata-invalid");
  }
});
test("public asset redirects are bounded and no credentials are attached", async () => {
  const f = fixture(); let redirects = 0;
  const fetcher = async (url, options) => {
    assert.equal(options.headers.Authorization, undefined);
    if (url.includes("/releases/download/")) return new Response(null, { status: 302, headers: { Location: "https://release-assets.githubusercontent.com/test" } });
    if (url.includes("release-assets.githubusercontent.com")) { redirects++; return Response.json(manifest); }
    return f.fetcher(url, options);
  };
  assert.equal(await check(env, fetcher, now), null); assert.equal(redirects, 1);
  await assert.rejects(check(env, async () => new Response(null, { status: 302, headers: { Location: "https://example.test" } }), now), /upstream-unavailable/);
});
test("invalid JSON, oversized responses and API outages do not produce healthy results", async () => {
  for (const response of [new Response("{bad"), new Response("a".repeat(1024 * 1024 + 1)), new Response("private diagnostic", { status: 429 })]) {
    await assert.rejects(check(env, async () => response, now));
  }
});
test("health endpoint has no write route, never caches success and sanitizes failures", async () => {
  assert.equal((await worker.fetch(new Request("https://example/health", { method: "POST" }), env)).status, 404);
  assert.equal((await worker.fetch(new Request("https://example/dispatch"), env)).status, 404);
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("secret diagnostic"); };
  try {
    const response = await worker.fetch(new Request("https://example/health"), env);
    assert.equal(response.status, 503); assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal((await response.json()).reason, "upstream-unavailable");
    assert.equal(await (await worker.fetch(new Request("https://example/health", { method: "HEAD" }), env)).text(), "");
  } finally { globalThis.fetch = original; }
});

test("both reviewed triggers work and neither hides the other's newer failure", async () => {
  for (const event of ["schedule", "workflow_dispatch"]) {
    const other = event === "schedule" ? "workflow_dispatch" : "schedule";
    assert.equal(assess({ ...run, event }, { ...run, event: other }), null);
    assert.equal(assess({ ...run, event, conclusion: "failure" }, { ...run, event: other }), "latest-run-failed");
    const f = fixture({ run: { ...run, event } });
    assert.equal(await check(env, f.fetcher, now), null);
    assert.ok(f.calls.filter(url => url.includes("/runs?")).every(url => !url.includes("event=")));
  }
  for (const event of ["push", "pull_request", "pull_request_target", "repository_dispatch", "workflow_run", "", null]) {
    assert.equal(assess({ ...run, event }), "latest-run-invalid-or-missing");
  }
});
test("bootstrap liveness is independent of release freshness", async () => {
  for (const [patch, reason] of [
    [{ bootstrap: { ...bootstrap, state: "disabled_inactivity" } }, "bootstrap-workflow-disabled-or-changed"],
    [{ bootstrap: { ...bootstrap, path: ".github/workflows/other.yml" } }, "bootstrap-workflow-disabled-or-changed"],
    [{ bootstrapRun: { ...bootstrapRun, conclusion: "failure" } }, "bootstrap-latest-run-failed"],
    [{ bootstrapRun: { ...bootstrapRun, event: "push" } }, "bootstrap-latest-run-invalid-or-missing"],
    [{ bootstrapSuccess: { ...bootstrapRun, created_at: iso(-BOOTSTRAP_FRESHNESS - 100), run_started_at: iso(-BOOTSTRAP_FRESHNESS - 50), updated_at: iso(-BOOTSTRAP_FRESHNESS - 1) } }, "bootstrap-run-stale"],
    [{ bootstrapRun: { ...bootstrapRun, status: "queued", conclusion: null, created_at: iso(-QUEUE_GRACE - 1) } }, "bootstrap-run-queue-stalled"],
  ]) {
    const f = fixture(patch);
    assert.equal(await check(env, f.fetcher, now), reason);
    assert.ok(!f.calls.some(url => url.endsWith("/releases/latest")));
  }
  const weekly = { ...bootstrapRun, created_at: iso(-8 * 86400 - 100), run_started_at: iso(-8 * 86400 - 50), updated_at: iso(-8 * 86400) };
  const f = fixture({ bootstrapRun: weekly, bootstrapSuccess: weekly });
  assert.equal(await check(env, f.fetcher, now), null);
});

test("bootstrap observations reject wrong identities, impossible chronology and stalled work", async () => {
  for (const [patch, reason] of [
    [{ bootstrapRun: { ...bootstrapRun, repository: { id: 999 } } }, "bootstrap-latest-run-invalid-or-missing"],
    [{ bootstrapRun: { ...bootstrapRun, workflow_id: 999 } }, "bootstrap-latest-run-invalid-or-missing"],
    [{ bootstrapSuccess: { ...bootstrapRun, workflow_id: 999 } }, "bootstrap-no-successful-run"],
    [{ bootstrapSuccess: { ...bootstrapRun, created_at: "unknown" } }, "bootstrap-run-time-invalid"],
    [{ bootstrapSuccess: { ...bootstrapRun, run_started_at: iso(1000) } }, "bootstrap-run-time-invalid"],
    [{ bootstrapSuccess: { ...bootstrapRun, updated_at: iso(-4000) } }, "bootstrap-run-time-invalid"],
    [{ bootstrapRun: { ...bootstrapRun, status: "in_progress", conclusion: null,
       created_at: iso(-RUN_GRACE - 100), run_started_at: iso(-RUN_GRACE - 1), updated_at: iso(-1) } }, "bootstrap-run-in-progress-stalled"],
  ]) {
    const f = fixture(patch);
    assert.equal(await check(env, f.fetcher, now), reason);
    assert.ok(!f.calls.some(url => url.endsWith("/releases/latest")));
  }
  for (const conclusion of ["failure", "cancelled", "timed_out", "neutral", "skipped", "action_required"]) {
    const f = fixture({ bootstrapRun: { ...bootstrapRun, conclusion } });
    assert.equal(await check(env, f.fetcher, now), "bootstrap-latest-run-failed");
  }
});
