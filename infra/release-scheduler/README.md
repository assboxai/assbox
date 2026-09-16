# External release dispatcher

This is the **only production scheduler**. Cloudflare Cron invokes `worker.mjs`
daily at **07:23 UTC** using the committed `wrangler.toml`. GitHub's release
workflow declares only `workflow_dispatch`, with no inputs. A human recovery
invocation runs the same workflow and gates. There is no GitHub cron fallback,
keepalive commit or public Worker route that dispatches releases.

```text
Cloudflare Cron -> GitHub App JWT -> repository-scoped installation token
               -> release.yml / workflow_dispatch / master / no inputs
               -> frozen release policy and complete GitHub Actions gates
```

The Worker does not choose dependency pins, source refs, sequences, signing
identities or whether to publish. Repository, workflow, branch and cron are fixed
in source. Public numeric IDs are provisioned separately and checked against GitHub
before dispatch. All HTTP effects have size/time bounds; credentialed redirects
are refused. A timeout after dispatch is ambiguous, so there is no eager retry that
assumes GitHub did not already accept the request. Workflow concurrency and release
head checks protect against duplicate invocations; a dispatch receipt is not a
successful release build.

## Authority and failure policy

Register an organization-owned GitHub App, install it on **only `assboxai/assbox`**,
and grant repository **Actions: write**, with GitHub's mandatory metadata read.
Do not grant Contents write, Administration, user permissions or additional
repository access. Disable unused webhooks and user-authorization flows. The Worker
uses the App client ID, installation ID and private key, not a user's PAT.
It requests a one-repository, Actions-write token on every invocation, validates
returned scope/expiry, and attempts to revoke the token afterward. It never stores
installation tokens between invocations.

**Actions write is not a dispatch-only permission.** It can also enable/disable
workflows and perform other Actions-management operations. This code never enables
a workflow, but a stolen App key is not limited by this code's hardcoded calls.
Treat key theft as an availability and Actions-control incident. The key cannot
directly edit protected source or release assets through a contents permission,
but the entire reviewed workflow must remain safe under malicious repeated
triggers, cancellation and reruns. Repository branch/tag rules and publication-job
isolation remain essential.

The App can dispatch other workflows and rerun existing runs **regardless of
original trigger**; GitHub does not scope its Actions permission to `release.yml`.
The mandatory [workflow authority guard](../../scripts/workflow_policy.py) therefore
checks every workflow, not just dispatchable ones. Only the reviewed `release.yml`
publish/advertise jobs may hold publication authority or a protected environment;
other workflows stay read-only, secret-free and limited to reviewed effect
entrypoints. Changing a trigger or filename grants no exception. This is a
source-review guard, not a narrowing of the stolen key's actual authority or a
proof of arbitrary transitive code. It does not retroactively change historical
workflow versions. Review new workflows/actions and outstanding rerunnable runs
against this constraint before enabling them.

A disabled workflow is an intentional stop: the Worker refuses it. Under suspected
key compromise, suspend/uninstall the App or revoke its private key **and** disable
release automation. Merely disabling a workflow is insufficient because the App
permission can re-enable it. Stop the Cron before credential rotation, revoke old
keys/tokens, provision the replacement securely, and test before resuming.
Never log provider response bodies, the App key, JWTs or installation tokens.

## Provisioning

Complete the [repository bootstrap](../../docs/governance.md) and genuine native
release acceptance first. These files do not create a Cloudflare account, install
the GitHub App, provision IDs, deploy a Worker or schedule notifications.

Use a Workers Free account without adding a billing method. Secure the Cloudflare
account and its recovery path; it holds an online App credential. Deployment access
is another sensitive capability, even though it is not a release signing key.
Use a temporary authenticated administration session or narrowly scoped deployment
credential, not a repo-write PAT. Keep deployment credentials out of Git and logs.

From trusted Linux, use the repository's reviewed Nix development shell, which
supplies Node.js and Wrangler. Populate the public values in `wrangler.toml` with
the actual App client ID, installation ID, repository ID and owner ID. The latter
two must agree with `release/policy.json`. Identifiers are not secrets; the supplied
zeros/UNPROVISIONED values deliberately refuse dispatch.

The Worker imports an RSA **PKCS#8** PEM (`BEGIN PRIVATE KEY`) using WebCrypto.
GitHub's downloaded RSA PEM may need conversion. Perform this outside the repository
on a trusted administrative machine in a private, preferably RAM-backed directory:

```sh
umask 077
openssl pkcs8 -topk8 -nocrypt -in /private/path/github-app.pem \
  -out /private/path/assbox-app-pkcs8.pem
```

The converted key is unencrypted private material. Do not put either PEM in the
repository, command arguments, shell history, CI artifacts, backups with weaker
access or a `[vars]` entry. Upload through stdin to a Worker secret binding:

```sh
nix develop
cd infra/release-scheduler
wrangler deploy --dry-run
wrangler secret put GITHUB_APP_PRIVATE_KEY < /private/path/assbox-app-pkcs8.pem
wrangler deploy
```

Authenticate Wrangler through the deliberately chosen administrator procedure;
these commands do not provision authentication automatically. Inspect the actual
account/deployment target before uploading a secret. Remove temporary key copies
from the administrative environment under its storage policy. Deletion on an SSD
is not a guarantee that prior disk blocks were securely erased.

No HTTP route or workers.dev endpoint is needed. `workers_dev` and preview URLs
are disabled, and the fetch handler returns 404. Confirm the deployed Cron matches
`23 7 * * *` and allow for trigger propagation. The committed file is the schedule's
source of truth; do not leave unrecorded alternate Cron entries in the dashboard.

## Tests and actual platform acceptance

Run without credentials or deployment:

```sh
node --test infra/release-scheduler/tests/*.test.mjs
```

The tests use real ephemeral RSA keys and Node WebCrypto to sign and verify JWTs,
including tampering. GitHub HTTP responses and effects are synthetic. No production
key is generated, retained or included. This is **not** real GitHub attestation
verification, Cloudflare execution, or proof of deployed permissions.

Cloudflare currently documents a **10 ms CPU limit on Workers Free**, including
Cron invocations. The request quota alone does not establish suitability. Measure
CPU on the actual deployed free plan, including key import, RSA signing and JSON
processing; local wall-clock test duration is not that measurement. Do not silently
solve a limit failure with a paid subscription or an expiring billing dependency.
Keep this as a deployment acceptance condition and optimize or move the dispatcher
if it cannot run within the no-payment plan. There is no account-wide quota or
provider-availability guarantee in this source.

Test one real invocation, verify the GitHub run identity/ref/event and absence of
inputs, then test disabled-workflow refusal. Check token permissions and clean logs.
API version `2026-03-10` returns a run-ID response; the code also accepts the older
204 acknowledgment. Neither proves the workflow later succeeded. Configure and
exercise the [separate monitor](../release-monitor/README.md) before relying on the
scheduler. A missed Cron does not weaken update verification, but delayed security
patching is still an operational incident.

Manual recovery, using an authorized administrator identity:

```sh
gh workflow run release.yml --repo assboxai/assbox --ref master
```

There are no bypass/skip-check arguments. A provider outage does not require changing
Assbox's client trust roots; the same dispatch program can be moved to another
scheduler after review.

## Primary interfaces

[Cloudflare Cron](https://developers.cloudflare.com/workers/configuration/cron-triggers/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/),
[WebCrypto](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/),
[GitHub App JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app),
[installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app),
and [workflow permissions/API](https://docs.github.com/en/rest/actions/workflows).
