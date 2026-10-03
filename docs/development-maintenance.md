# Development dependency maintenance

The committed workflow is disabled unless the repository variable
`ASSBOX_DEVELOPMENT_MAINTENANCE` equals `enabled`. Do not enable it during initial
implementation or the first repair exercise. It uses the fixed Tuesday
`17 7 * * 2` UTC schedule and inputless manual recovery, on canonical master only.
No implementation command provisions an Environment, edits repository settings,
dispatches Actions, pushes a commit or publishes a release.

## Ownership and evidence

Only existing mode-0644 `chainman.lock` and `nix/dev/flake.lock` may change. Root
`flake.lock`, Cargo/Actions approval policy, production artifact pins and release
identity remain separately owned. Developer changes still affect the existing
whole-repository authenticated core and can select a later production release.
This workflow does not dispatch publication or filter developer files out of source.

Preparation freezes one base, records the exact numeric run-attempt job via API,
then uses the documented Chainman `deps-update commit=off` operation in a disposable
checkout. Untargeted updates deliberately trust the canonical upstream runtime's
advertised default branch frozen to an exact SHA, plus mature developer Nixpkgs.
The 30-day project dependency window does not apply to runtime selection. Executing
candidate runtime/toolchain code is an intentional upstream supply-chain trust
decision; native compatibility tests cannot prove it benign.

The candidate envelope contains bounded raw lock replacements and whole-source
content/tree/synthetic-commit identity. No change produces no usable envelope and
no empty keepalive commit. Independent x86-64 and ARM jobs reconstruct the exact
candidate and run the complete gate, including a fresh canonical CLI installation.
Reports bind base, candidate, oracle, policy/gates, both locks, runtime SHA,
repository/owner, numeric job/run/attempt, native architecture and accelerator.
Skipped, cancelled, missing or stale evidence blocks writing.

Workflow permissions are empty by default. Prepare/native receive Contents-read
and Actions-read; the fresh writer receives Contents-write and Actions-read. Grants
are job-wide. API discovery ends before candidate execution. Candidate children
receive a limited environment without repository tokens, artifact/OIDC credentials,
SSH agents, Git configuration, or writable runner command channels. Their output
cannot issue runner commands through normal log interpretation. This limits
accidental exposure; same-user hostile-code isolation is not claimed.

The writer job has zero Actions, checkouts, containers, services or dependency
installation. Its fixed `/usr/bin/python3 -I -B` bootstrap loads the exact controller
and policy blobs from the trusted workflow-base Git tree, verifies Git object
identities/modes, and runs the standalone standard-library controller in a private
directory. It never imports or executes candidate code, Nix or Chainman. Ordinary
authenticated API redirects are refused. Artifact downloads validate the one signed
HTTPS redirect and fetch it without forwarding authorization, then validate digest,
bounded ZIP shape and exact JSON names. Artifact/job linkage is the trusted CI job's
operational claim, not an invented cryptographic attestation.

After all evidence matches, the writer creates exactly the allowed blobs/tree and
one sole-parent commit. The ref mutation is one nonforcing GraphQL `updateRefs`
request with explicit `beforeOid=base`. A moving master stops the transaction.
Ambiguous outcomes get read-only reconciliation against the exact created commit;
there is no blind write retry, rebase, alternate credential or ruleset bypass.

## Ordered administrator handoff

Complete these outside the implementation task, in order:

1. Review the committed workflow, writer/bootstrap, policies, source identity and
   runtime trust decision. Provision actual positive numeric repository/owner IDs
   in `release/policy.json` through the existing cold-administrator procedure.
2. Qualify both native full gates, fresh canonical runs, no-change behavior,
   malformed/stale artifact refusals, expected-head races, uncertain API outcomes
   and administrative controls in a disposable nonproduction repository. Qualify
   the hosted runner's absolute Python and artifact transport. Static tests alone
   do not establish these capabilities.
3. Manually precreate the distinct `development-maintenance` Environment. Select
   selected-branches-and-tags deployment policy, one exact **Branch** rule
   `master`, and **no Tag** rules. An automatically created empty Environment
   is not protection. Only the writer job references this Environment.
4. Independently inspect the actual Environment and branch/ruleset protections.
   Decide whether the ephemeral repository token may perform this bounded write.
   A rejected write requires administrator attention, not a stronger secret.
5. Set `ASSBOX_DEVELOPMENT_MAINTENANCE_READY=provisioned-v1` **only on that
   Environment**. Verify it is absent at repository and organization scope so
   a shadow cannot fake readiness. The fixed writer step checks it after
   Environment admission and before mutation. The marker is operator readiness
   data, not live API attestation of protections.
6. Only then set repository `ASSBOX_DEVELOPMENT_MAINTENANCE=enabled`. Keep optional
   per-run reviewers according to operator policy; unattended operation after
   qualification is supported. Arrange independent read-only failure/freshness
   monitoring and inputless manual recovery.

To disable writing, remove the repository enablement switch. Missing/wrong readiness
or unprovisioned numeric IDs yields administration-required and no write. Disabling
the switch does not delete GitHub's scheduled events. In development copies, disable
all three production-only scheduled workflows (`release`, `bootstrap`, `maintenance`)
to suppress skipped run history. `verify.yml` remains manual-only.

## Read-only status contract

`just maintenance-inspect --base-source /absolute/clean/base --envelope
/private/candidate.json --report /private/x86.json --report /private/arm.json`
validates local structure and source bindings. Its result explicitly leaves local
artifact provenance unverified and grants no write authorization. The writer must
still discover the exact run, attempt, jobs and immutable artifacts independently.

Operators can inspect Actions runs and exact attempt-qualified candidate/native
artifacts with read access. Report disabled, no-change, failed, blocked,
stale/incomplete, or applied distinctly; only an applied result includes a verified
real commit/ref observation. Preserve base-moved and uncertain outcomes for inspection.
Do not call a skipped job or no-change resolution a fresh verification pass. A
monitor needs no dispatch, write, OIDC, deployment or administrator permission.

`python3 scripts/development_maintenance_status.py` reports disabled without making
an API call. Add `--enabled --observe-public-run` only when enablement was observed
by the operator, or `--enabled --summary /private/controller-outcome.json` to inspect
an exact outcome. The public probe makes one anonymous fixed-origin GET; it never
infers applied/no-change from workflow success alone. Its switch is operator data,
not live repository-variable or Environment attestation.

The schema/policy documents under [development](../development/maintenance-policy.json)
describe acceptance. They are not runtime qualification records; keep machine logs
and rollout evidence outside distributable source.
