# Read-only release availability probe

`worker.mjs` exposes `GET /health` (and HEAD) for an external service such as
cron-job.org to query and alert on. It has **no GitHub token, App key, write request,
Cron trigger or dispatch route**. It is not an attestation verifier and is not part
of an Assbox client's release-authorization decision.

A plain HTTP request to a GitHub API page is not a useful freshness check: it may
return 200 while the last successful run is months old. This probe returns **503**
when any required observation fails and 200 only when all availability criteria
hold. A non-200 response, timeout or unreachable probe should produce an external
notification.

## Observations

The probe checks the configured repository and owner numeric identities, public
nonfork repository with master as default, and the exact active `release.yml`
workflow, plus the exact active bootstrap-maintenance workflow. It requires a
bootstrap success within 15 days. For each workflow it queries both the
**latest run regardless of outcome**, including scheduled and manual runs, and the last
successful run. A completed failure, cancellation, timeout, skipped/neutral result
or other non-success causes 503 on the next poll even if yesterday's success is
less than 36 hours old.

A queue/wait state receives at most two hours from run creation; an in-progress
pipeline receives at most twenty hours from `run_started_at`. Updates to
`updated_at` do not extend those budgets. These are whole-pipeline limits, not
individual-job limits. Every healthy response still requires a completed success
within 36 hours; active work cannot postpone that requirement indefinitely. A
rerun with old creation metadata may be reported stalled while queued; inspection
is preferable to silently resetting a grace period. Unknown statuses, timestamps
or identities are unhealthy rather than interpreted optimistically.

The probe separately inventories releases **and tags**, then compares the complete
visible **`r-*` sets** and chooses the highest numeric `r-N`, matching CI's channel
namespace. Records must have string tag identities before filtering. Ordinary
source tags/releases such as `v0.1.0` are outside this channel and do not affect its
head; they need not be paired or immutable. Names beginning `r-` remain reserved:
`r-invalid` and `r-001` are errors, not ignorable source tags.

API order and lexical sorting are not trusted; sequence comparison remains exact
beyond JavaScript Number's integer precision. Missing genesis, orphan `r-*` tags,
duplicate/malformed reserved records, nonimmutable channel releases and inconsistent
channel inventories produce 503. There is no healthy empty channel or alternative
genesis: the publisher still permits creation of `r-1` only from a completely empty
raw tag/release namespace. Filtering source tags after genesis does not weaken that
bootstrap rule or establish when any tag was created.

`latest` must name the exact channel head (tag and release ID), never an ordinary
source release. A backwards pointer cannot be healthy merely because its older
manifest is unexpired. The head's manifest must match the tag and have at least 48
hours remaining within the expected seven-day interval.

The raw inventories, including unrelated source tags/releases, are bounded to
**16 pages of 100 records each**. Filtering occurs only after pagination completes;
a page containing only source tags is not an end-of-history signal. A final short
raw page is required, so a full 1,600-record observation is refused rather than
assumed complete. The worst successful request uses at most 44 upstream requests
including three allowed HTTPS asset redirects; the smallest healthy check uses eleven.
Reaching `history-observation-limit` requires a reviewed observer-capacity or hosting
change, never deleting authenticated history or pretending a truncated set is the
head. This monitor bound does not change the CI or installed-client history policy.
API/response bounds and cache headers prevent an old cached answer from becoming a
healthy fallback. Anonymous rate limits and the actual free-tier CPU budget must
still be measured on deployment; bounded requests alone do not establish suitability.

Unchanged dependencies need not produce a release every day. Workflow freshness,
latest/head agreement and manifest expiry are separate checks. During publication,
a new immutable head may be visible before both candidate-verifier jobs finish
and before advertisement; a poll in that interval is deliberately unhealthy rather
than declaring an unadvertised release ready. Separate API observations can also
race a publication and fail conservatively. Inspect the reason and current workflow
before treating a temporary alert as an incident. Required API observations that
fail or time out are never converted to green. Inspect application-hold and
vulnerability reports separately in GitHub.

These observations are **not authenticated history verification**. The probe does
not check signatures or authorize source, establish an installed replay floor, or
replace the Rust client. A 200 is availability telemetry only. Missing or censored
history from a compromised trusted provider is outside what it can establish.

## Provisioning and independent alerts

Deploy this read-only Worker independently of the GitHub workflows.
Replace both public zero IDs in `wrangler.toml` with the values independently
verified for `release/policy.json`. No secret binding is needed or permitted by
this implementation. From the reviewed Nix shell:

```sh
cd infra/release-monitor
wrangler deploy --dry-run
wrangler deploy
```

Record the **actual workers.dev URL reported by deployment**; no hostname/account
is invented by these files. Request its `/health` path and inspect the result.
Before the first real release, an unhealthy result is expected, not a reason to
fabricate a successful run or relax expiry checks.

In cron-job.org, configure a GET to that full health URL every six hours and enable
failure and recovery notifications to a verified destination. Do not supply any
GitHub Authorization header or write credential. Confirm that a non-200 response
and an unreachable endpoint both trigger notification, and perform a real
notification/recovery test. Choose a timeout sufficient for the bounded upstream
requests and observe real response time; do not assume a default is adequate.
No monitor account, schedule, email recipient or notification is created by this
source archive.

The observer's **timer and alert delivery run outside Cloudflare/GitHub Actions**.
A Cloudflare outage makes the probe unreachable and can therefore be detected by
cron-job.org. Compromise of the monitor hosting account could falsify the probe
or change its logic. This is outage detection, not independent evidence against
that compromise. Deploy the same read-only policy on another provider for stronger
separation without changing Assbox clients or granting new GitHub permissions.

There is no payment-method requirement in this design and no paid-plan fallback.
Confirm deployed Workers Free CPU/request limits and current service policies.
Anonymous GitHub API limits apply; the probe is intentionally not used to poll
at high frequency, and an exposed public endpoint can consume quota. Persistent
resource/availability alerts require investigation rather than a security bypass.

## Tests

```sh
node --test infra/release-monitor/tests/*.test.mjs
```

These tests execute the actual read-only logic with synthetic API responses. They
cover recent failures despite older successes, bounded queue/run grace, stale/future
runs, numeric/paginated history, harmless source tags/releases, strict reserved
namespace validation, backwards latest, malformed/orphaned inventories, raw
observation limits, expiry, redirects, credential-free requests and rejected write
routes. The Python tooling suite also compares actual CI and monitor namespace
selection/refusal with identical fixtures. These tests do not deploy Workers,
measure free-tier CPU, deliver notifications or cryptographically authenticate
releases.

See [governance](../../docs/governance.md) for incident handling and
[verification](../../docs/verification.md) for acceptance boundaries.
Service references: [cron-job.org](https://cron-job.org/en/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[GitHub workflow runs](https://docs.github.com/en/rest/actions/workflow-runs).
