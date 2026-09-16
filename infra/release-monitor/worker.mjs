// SPDX-License-Identifier: GPL-3.0-or-later
// Read-only availability probe. NOT an attestation verifier or update authority.
const REPO = "assboxai/assbox";
const API = `https://api.github.com/repos/${REPO}`;
const WORKFLOW = ".github/workflows/release.yml";
const RUNS = `${API}/actions/workflows/release.yml/runs?branch=master`;
export const HISTORY_PAGES = 16; // Per inventory, 100 entries/page; no partial success.
export const RUN_GRACE = 20 * 3600; // Full multi-stage native pipeline, not one job.
export const QUEUE_GRACE = 2 * 3600;
const RUN_FRESHNESS = 36 * 3600;
export const BOOTSTRAP_FRESHNESS = 15 * 86400;
const BOOTSTRAP = ".github/workflows/bootstrap.yml";

class ObservationError extends Error {}
const fail = reason => { throw new ObservationError(reason); };
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const positive = value => typeof value === "string" && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value));
const identifier = value => Number.isSafeInteger(value) && value > 0;
const timestamp = value => typeof value === "string" ? Date.parse(value) / 1000 : NaN;
const validTime = (time, now) => Number.isFinite(time) && time > 0 && time <= now + 300;
function sequence(tag) {
  if (typeof tag !== "string" || !/^r-[1-9][0-9]{0,15}$/.test(tag)) fail("release-history-invalid");
  // Rust/Python accept 16-digit sequences, which can exceed Number's exact range.
  return BigInt(tag.slice(2));
}

export function assessIdentity(env, repo, workflow) {
  if (!positive(env.GITHUB_REPOSITORY_ID) || !positive(env.GITHUB_OWNER_ID)) return "unprovisioned";
  if (!object(repo) || repo.id !== Number(env.GITHUB_REPOSITORY_ID) || repo.owner?.id !== Number(env.GITHUB_OWNER_ID) ||
      repo.full_name !== REPO || repo.default_branch !== "master" || repo.private !== false || repo.fork !== false) return "repository-changed";
  if (!object(workflow) || !identifier(workflow.id) || workflow.state !== "active" || workflow.path !== WORKFLOW) return "workflow-disabled-or-changed";
  return null;
}

function runIdentity(run, repo, workflow) {
  return object(run) && identifier(run.id) && run.head_branch === "master" && ["schedule", "workflow_dispatch"].includes(run.event) &&
    run.repository?.id === repo.id && run.workflow_id === workflow.id;
}
function firstRun(response) {
  if (!object(response) || !Array.isArray(response.workflow_runs) || response.workflow_runs.length > 1) return undefined;
  return response.workflow_runs[0];
}
export function assessRuns(repo, workflow, latestRuns, successfulRuns, now, freshness = RUN_FRESHNESS) {
  const latest = firstRun(latestRuns);
  if (!runIdentity(latest, repo, workflow)) return "latest-run-invalid-or-missing";
  const created = timestamp(latest.created_at), updated = timestamp(latest.updated_at);
  if (!validTime(created, now) || !validTime(updated, now) || updated < created) return "run-time-invalid";
  if (latest.status === "completed") {
    // A fresh prior success must not hide today's cancellation/failure, including
    // neutral/skipped/action_required results that did not complete the gates.
    if (latest.conclusion !== "success") return "latest-run-failed";
  } else if (["queued", "requested", "pending", "waiting"].includes(latest.status)) {
    if (latest.conclusion !== null) return "latest-run-invalid-or-missing";
    if (now - created > QUEUE_GRACE) return "run-queue-stalled";
  } else if (latest.status === "in_progress") {
    const started = timestamp(latest.run_started_at);
    if (latest.conclusion !== null || !validTime(started, now) || started < created || started > updated) return "run-time-invalid";
    // updated_at may change throughout a stuck run; it cannot extend this grace.
    if (now - started > RUN_GRACE) return "run-in-progress-stalled";
  } else return "latest-run-invalid-or-missing";
  const successful = firstRun(successfulRuns);
  if (!runIdentity(successful, repo, workflow) || successful.status !== "completed" || successful.conclusion !== "success") return "no-successful-run";
  const completed = timestamp(successful.updated_at);
  const successCreated = timestamp(successful.created_at), successStarted = timestamp(successful.run_started_at);
  if (!validTime(completed, now) || !validTime(successCreated, now) || !validTime(successStarted, now) ||
      successStarted < successCreated || successStarted > completed) return "run-time-invalid";
  if (now - completed > freshness) return "run-stale";
  return null;
}

export function historyHead(releases, tags) {
  if (!Array.isArray(releases) || !Array.isArray(tags) || releases.length === 0) fail("release-history-invalid");
  const byTag = new Map(), ids = new Set(), tagNames = new Set();
  let head = null, maximum = 0n;
  for (const release of releases) {
    if (!object(release) || typeof release.tag_name !== "string") fail("release-history-invalid");
    // Match CI's history namespace. Validate the prefix before the sequence so a
    // malformed reserved name cannot disappear as an unrelated source release.
    if (!release.tag_name.startsWith("r-")) continue;
    const number = sequence(release.tag_name);
    if (!identifier(release.id) || ids.has(release.id) || byTag.has(release.tag_name) ||
        release.immutable !== true || release.draft !== false || release.prerelease !== false) fail("release-history-invalid");
    ids.add(release.id); byTag.set(release.tag_name, release);
    if (number > maximum) { head = release; maximum = number; }
  }
  for (const tag of tags) {
    if (!object(tag) || typeof tag.name !== "string") fail("release-history-invalid");
    if (!tag.name.startsWith("r-")) continue;
    sequence(tag.name);
    if (tagNames.has(tag.name) || typeof tag.commit?.sha !== "string" || !/^[0-9a-f]{40}$/.test(tag.commit.sha)) fail("release-history-invalid");
    tagNames.add(tag.name);
  }
  if (!byTag.has("r-1") || byTag.size !== tagNames.size || [...byTag.keys()].some(tag => !tagNames.has(tag))) fail("release-history-invalid");
  return head;
}

export function assessRelease(latest, head, manifest, now) {
  if (!object(latest) || latest.immutable !== true || latest.draft !== false || latest.prerelease !== false) return "release-unavailable";
  if (latest.id !== head.id || latest.tag_name !== head.tag_name) return "latest-not-history-head";
  if (!object(manifest) || manifest.schema !== 3 || manifest.protocol !== 3 || manifest.channel !== "stable" || manifest.tag !== head.tag_name ||
      !Number.isSafeInteger(manifest.issuedAt) || manifest.issuedAt <= 0 || !Number.isSafeInteger(manifest.expiresAt) ||
      manifest.issuedAt > now + 300 || manifest.expiresAt - manifest.issuedAt !== 604800) return "release-metadata-invalid";
  if (manifest.expiresAt - now < 48 * 3600) return "release-expiry-near";
  return null;
}

async function json(fetcher, url, asset = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    let response;
    for (let redirects = 0; ; redirects++) {
      response = await fetcher(url, { redirect: "manual", signal: controller.signal,
        headers: { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "Assbox-release-health" } });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      const location = response.headers.get("Location");
      await response.body?.cancel();
      if (!asset || redirects >= 3 || !location) fail("upstream-unavailable");
      const target = new URL(location, url);
      if (target.protocol !== "https:" || target.username || target.password ||
          !["github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"].includes(target.hostname)) fail("upstream-unavailable");
      url = target.href;
    }
    if (!response.ok || !response.body) fail("upstream-unavailable");
    const reader = response.body.getReader();
    const chunks = []; let size = 0;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > (asset ? 64 * 1024 : 1024 * 1024)) fail("response-too-large");
        chunks.push(value);
      }
      const bytes = new Uint8Array(size); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  } finally { clearTimeout(timeout); }
}

async function inventory(fetcher, endpoint) {
  const result = [];
  for (let page = 1; page <= HISTORY_PAGES; page++) {
    const values = await json(fetcher, `${API}/${endpoint}?per_page=100&page=${page}`);
    if (!Array.isArray(values) || values.length > 100 || values.some(v => !object(v))) fail("release-history-invalid");
    result.push(...values);
    if (values.length < 100) return result;
  }
  fail("history-observation-limit"); // Never infer a maximum from a truncated page set.
}

export async function check(env, fetcher = fetch, now = Math.floor(Date.now() / 1000)) {
  // These are unauthenticated availability observations, not release authority.
  if (!positive(env.GITHUB_REPOSITORY_ID) || !positive(env.GITHUB_OWNER_ID)) return "unprovisioned";
  const repo = await json(fetcher, API);
  const workflow = await json(fetcher, `${API}/actions/workflows/release.yml`);
  const identity = assessIdentity(env, repo, workflow);
  if (identity) return identity;
  const latestRuns = await json(fetcher, `${RUNS}&per_page=1`);
  const successfulRuns = await json(fetcher, `${RUNS}&status=success&per_page=1`);
  const runState = assessRuns(repo, workflow, latestRuns, successfulRuns, now);
  if (runState) return runState;
  const bootstrap = await json(fetcher, `${API}/actions/workflows/bootstrap.yml`);
  if (!object(bootstrap) || !identifier(bootstrap.id) || bootstrap.state !== "active" || bootstrap.path !== BOOTSTRAP) {
    return "bootstrap-workflow-disabled-or-changed";
  }
  const bootstrapRuns = `${API}/actions/workflows/bootstrap.yml/runs?branch=master`;
  const bootstrapLatest = await json(fetcher, `${bootstrapRuns}&per_page=1`);
  const bootstrapSuccess = await json(fetcher, `${bootstrapRuns}&status=success&per_page=1`);
  const bootstrapState = assessRuns(repo, bootstrap, bootstrapLatest, bootstrapSuccess, now, BOOTSTRAP_FRESHNESS);
  if (bootstrapState) return `bootstrap-${bootstrapState}`;
  const releases = await inventory(fetcher, "releases");
  const tags = await inventory(fetcher, "tags");
  const head = historyHead(releases, tags);
  const latest = await json(fetcher, `${API}/releases/latest`);
  if (!object(latest) || latest.id !== head.id || latest.tag_name !== head.tag_name) return "latest-not-history-head";
  const manifest = await json(fetcher, `https://github.com/${REPO}/releases/download/${head.tag_name}/release.json`, true);
  return assessRelease(latest, head, manifest, now);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/health" || !["GET", "HEAD"].includes(request.method)) return new Response("Not found\n", { status: 404 });
    let reason;
    try { reason = await check(env); } catch (error) { reason = error instanceof ObservationError ? error.message : "upstream-unavailable"; }
    const payload = { healthy: reason === null, reason, scope: "availability-only-not-release-authorization" };
    return new Response(request.method === "HEAD" ? null : JSON.stringify(payload) + "\n", {
      status: reason === null ? 200 : 503,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  },
};
