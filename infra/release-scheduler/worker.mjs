// SPDX-License-Identifier: GPL-3.0-or-later
// Availability actuator only. No release decisions, inputs, account login or PAT.
export const TARGET = Object.freeze({
  repository: "assboxai/assbox",
  workflow: "release.yml",
  ref: "master",
  cron: "23 7 * * *",
});
const API = "https://api.github.com";
const VERSION = "2026-03-10";
const ALGORITHM = { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" };

export class DispatchError extends Error {
  constructor(stage, status = 0) {
    // Never include an API body, credential, PEM, JWT or remote error message.
    super(`Assbox dispatch failed at ${stage} (status ${status})`);
    this.stage = stage;
    this.status = status;
  }
}

function positiveId(value) {
  if (typeof value !== "string" || !/^[1-9][0-9]{0,15}$/.test(value)) {
    throw new DispatchError("configuration");
  }
  const number = Number(value);
  if (!Number.isSafeInteger(number)) throw new DispatchError("configuration");
  return number;
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export async function appJwt(env, now, subtle) {
  if (!Number.isSafeInteger(now) || now <= 60 ||
      typeof env.GITHUB_APP_CLIENT_ID !== "string" ||
      !/^[A-Za-z0-9_.-]{1,80}$/.test(env.GITHUB_APP_CLIENT_ID) ||
      env.GITHUB_APP_CLIENT_ID === "UNPROVISIONED") {
    throw new DispatchError("configuration");
  }
  const pem = env.GITHUB_APP_PRIVATE_KEY;
  if (typeof pem !== "string" || pem.length > 5000 ||
      !/^-----BEGIN PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END PRIVATE KEY-----\s*$/.test(pem)) {
    throw new DispatchError("private-key-format");
  }
  try {
    const encoded = pem.replace(/-----[A-Z ]+-----/g, "").replace(/\s/g, "");
    const der = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
    const key = await subtle.importKey("pkcs8", der, ALGORITHM, false, ["sign"]);
    const encode = value => base64url(new TextEncoder().encode(JSON.stringify(value)));
    const unsigned = `${encode({ alg: "RS256", typ: "JWT" })}.${encode({
      iat: now - 60, exp: now + 300, iss: env.GITHUB_APP_CLIENT_ID,
    })}`;
    const signature = await subtle.sign(ALGORITHM.name, key, new TextEncoder().encode(unsigned));
    return `${unsigned}.${base64url(signature)}`;
  } catch {
    throw new DispatchError("private-key-signing");
  }
}

async function boundedJson(response, stage) {
  if (!response.body) throw new DispatchError(stage, response.status);
  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 65536) throw new DispatchError(stage, response.status);
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    await reader.cancel().catch(() => {});
    throw new DispatchError(stage, response.status);
  } finally {
    reader.releaseLock();
  }
}

async function request(fetcher, stage, path, token, { method = "GET", body, statuses = [200] } = {}) {
  // Call sites use fixed paths. Never follow redirects with a bearer credential.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetcher(API + path, {
      method, redirect: "error", signal: controller.signal,
      headers: {
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": VERSION,
        "User-Agent": "Assbox-release-scheduler",
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!statuses.includes(response.status)) {
      await response.body?.cancel();
      throw new DispatchError(stage, response.status);
    }
    return response.status === 204 ? null : await boundedJson(response, stage);
  } catch (error) {
    if (error instanceof DispatchError) throw error;
    throw new DispatchError(stage);
  } finally {
    clearTimeout(timer);
  }
}

export async function dispatch(env, { fetcher = fetch, subtle = crypto.subtle,
  now = Math.floor(Date.now() / 1000) } = {}) {
  const installation = positiveId(env.GITHUB_APP_INSTALLATION_ID);
  const repositoryId = positiveId(env.GITHUB_REPOSITORY_ID);
  const ownerId = positiveId(env.GITHUB_OWNER_ID);
  const jwt = await appJwt(env, now, subtle);
  const minted = await request(fetcher, "token", `/app/installations/${installation}/access_tokens`, jwt, {
    method: "POST", statuses: [201],
    body: { repository_ids: [repositoryId], permissions: { actions: "write" } },
  });
  const token = minted?.token;
  if (typeof token !== "string" || token.length < 20 || token.length > 1024 || /\s/.test(token)) {
    throw new DispatchError("token-shape");
  }
  try {
    const expiry = Date.parse(minted.expires_at) / 1000;
    const permissions = minted.permissions;
    if (!Number.isFinite(expiry) || expiry <= now + 60 || expiry > now + 3900 ||
        !permissions || permissions.actions !== "write" ||
        Object.entries(permissions).some(([key, value]) =>
          key !== "actions" && !(key === "metadata" && value === "read"))) {
      throw new DispatchError("token-scope");
    }
    // If GitHub includes a repository list, it must agree with the explicitly
    // requested one-repository scope. The endpoint can omit it in some versions.
    if (minted.repositories !== undefined && (!Array.isArray(minted.repositories) ||
        minted.repositories.length !== 1 || minted.repositories[0].id !== repositoryId ||
        minted.repositories[0].full_name !== TARGET.repository)) {
      throw new DispatchError("repository-scope");
    }
    const repo = await request(fetcher, "repository", `/repos/${TARGET.repository}`, token);
    if (repo.id !== repositoryId || repo.owner?.id !== ownerId || repo.full_name !== TARGET.repository ||
        repo.default_branch !== TARGET.ref || repo.private !== false || repo.fork !== false) {
      throw new DispatchError("repository-identity");
    }
    const workflow = await request(fetcher, "workflow", `/repos/${TARGET.repository}/actions/workflows/${TARGET.workflow}`, token);
    if (workflow.path !== `.github/workflows/${TARGET.workflow}` || workflow.state !== "active") {
      // A disabled workflow is an emergency stop, never something to re-enable.
      throw new DispatchError("workflow-disabled-or-changed");
    }
    const result = await request(fetcher, "dispatch", `/repos/${TARGET.repository}/actions/workflows/${TARGET.workflow}/dispatches`, token, {
      method: "POST", statuses: [200, 204], body: { ref: TARGET.ref },
    });
    if (result !== null && (!Number.isSafeInteger(result.workflow_run_id) || result.workflow_run_id <= 0 ||
        result.run_url !== `${API}/repos/${TARGET.repository}/actions/runs/${result.workflow_run_id}` ||
        result.html_url !== `https://github.com/${TARGET.repository}/actions/runs/${result.workflow_run_id}`)) {
      throw new DispatchError("dispatch-response");
    }
    return { accepted: true, runId: result?.workflow_run_id ?? null };
  } finally {
    // Best effort: no token persists across invocations. Even if revocation fails,
    // GitHub's installation token expires independently of Worker state.
    try { await request(fetcher, "revoke", "/installation/token", token, { method: "DELETE", statuses: [204] }); }
    catch { console.warn("Assbox scheduler: token revocation failed; short-lived token will expire"); }
  }
}

export default {
  async scheduled(controller, env) {
    // A duplicate delivery is safe but unnecessary. Dispatch timeout is ambiguous:
    // do not guess that GitHub did not enqueue the run and issue an eager retry.
    if (typeof controller.noRetry === "function") controller.noRetry();
    if (controller.cron !== TARGET.cron) throw new DispatchError("unexpected-cron");
    try {
      const result = await dispatch(env);
      console.log(JSON.stringify({ event: "assbox-dispatch-accepted", runId: result.runId }));
    } catch (error) {
      const safe = error instanceof DispatchError ? error : new DispatchError("unexpected");
      console.error(JSON.stringify({ event: "assbox-dispatch-failed", stage: safe.stage, status: safe.status }));
      throw safe;
    }
  },
  async fetch() {
    // No public webhook, request-body input, or remotely callable dispatch route.
    return new Response("Not found\n", { status: 404 });
  },
};
