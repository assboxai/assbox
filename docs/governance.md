# Low-change core and release governance

## Administrative authority

The public core branch is `master`. After the first public release, core changes
should normally address security defects, upstream breakage, hardware compatibility
or materially important reliability issues. Prefer ordinary local NixOS customization
over expanding the substrate. Frozen source still needs continuous dependency
builds, acceptance and monitoring; it does not mean unattended abandonment.
Include the chosen NixOS input branch and release-verifier toolchain in periodic
support review. Moving to another supported NixOS branch is an intentional
core-maintenance event, not a daily bot update or a reason to retain unsupported
dependencies indefinitely.

Use a dedicated cold GitHub administrator, never for routine browsing or development.
An everyday identity can contribute through forks and pull requests without write
access. Keep the cold password offline; avoid persisted sessions, saved browser
credentials, app passwords, PATs and deploy keys. Use a dedicated clean browser/device
for rare administration and end/revoke sessions afterward. Security at login still
depends on that device, not just password entropy.

Register at least two hardware security keys, with the spare stored separately.
Print recovery codes and protect them separately from ordinary login material.
Protect the associated email and its recovery path to a comparable standard. A sole
owner is a conscious succession risk; an independently secured cold break-glass
owner can be appointed when a genuinely trusted custodian is available. Never
create an everyday second administrator merely for nominal redundancy. Test
recovery deliberately without copying credentials into this repository or logs.

GitHub documents [2FA recovery](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication-recovery-methods)
and recommends multiple organization owners for continuity in its
[organization role guidance](https://docs.github.com/en/organizations/managing-peoples-access-to-your-organization-with-roles/roles-in-an-organization).
This document is a provisioning procedure, not evidence any account is configured.

## One-time repository provisioning

Set the default branch to `master`. Enable immutable releases and private vulnerability
reporting. Read the actual public repository and owner numeric IDs through GitHub,
independently verify ownership, and commit them in `release/policy.json` with a real
reviewed bootstrap `flake.lock`. The supplied zero IDs intentionally disable release
acceptance/publication until this is done. Do not guess IDs or substitute name-only
matching. Review formatter/compiler fixes with native tools before core acceptance.

Protect `master` against force-push, deletion and unreviewed changes. Require the
native verification checks and PR-based core changes; protect workflow/tool/policy
files as strongly as Rust. If only one human can approve, do not configure an
impossible two-person review requirement or a silent bot bypass. Document the
specific cold-maintainer exceptional merge path and audit its use. The Actions app
must not bypass the master branch rules. Separate `r-*` tag rules may permit only
the protected publisher to create new release tags, never rewrite protected core.

Pin allowed third-party Actions to complete commits, use GitHub-hosted runners,
read-only default job permissions and no persisted checkout credentials. Do not run
untrusted PR code in `pull_request_target`, a privileged `workflow_run` handler or a
release environment. Read-only build jobs and fresh publication jobs are separate.
The publisher validates frozen-core bytes and final evidence but executes neither
Nix nor candidate programs.

`scripts/workflow_policy.py`, invoked by the mandatory gate, checks **every
workflow regardless of trigger**. Only `release.yml`'s reviewed `publish` and
`advertise` jobs may hold publication authority. The separately reviewed bootstrap
`write` job has lock-only/empty-commit authority and its own protected environment.
All remaining jobs must have explicit contents-read permissions, no secret/environment
access (including reusable-workflow secret declarations), no reusable/local
unreviewed action calls, only reviewed hosted runners, and allowlisted command/action
entrypoints. Read-only preparation/verification may write local build results and upload run
artifacts; "read-only" refers to repository, release and administrative authority,
not a prohibition on local build effects. A new filename or a push-only,
workflow-run, scheduled or reusable trigger does not grant an exception.

GitHub's Actions-write permission also allows [rerunning workflow runs and jobs](https://docs.github.com/en/rest/actions/workflow-runs).
A [rerun uses the original actor's privileges and original ref/SHA](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs),
so absence of `workflow_dispatch` is not an authority boundary. The lint inspects
the current source, not historical workflow versions or existing remote runs;
review outstanding rerunnable privileged runs when changing policy.

The guard is an architectural lint and an explicit review boundary, not a proof
of all transitive script, action or dependency behavior. Review its allowlist and
the called source together. Branch rules and actual GitHub permissions cannot be
established from this check. Privileged publication uses fresh jobs, fixed artifact
paths/checkout identity and per-effect current-master checks; stale-head refusal
is tested independently of the YAML lint.

Create a `release-automation` environment restricted to `master`. **Do not require a
human approval for every daily run.** Human controls apply to rare changes of the
workflow, core, branch/environment rules and identities. No ordinary successful PR
can publish. Routine scheduled and inputless manual execution of the reviewed
master workflow is automatic after every gate passes. No workflow input changes
source, dependencies, checks or release identity.

The short-lived `GITHUB_TOKEN` with `contents: write` is not a release-only privilege;
it can authorize broader repository-content operations. Permissions apply to a
whole job, not one step: all actions in that job can access its token implicitly.
Treat every pinned checkout, download and attestation action in a privileged job
as part of the trusted computing base. The guard restricts explicit token reads to
exact approved step environments; it does not remove implicit action access.
See [token boundaries](release-authentication.md#tokenless-verification-and-operational-constraints).

Isolation and branch rules are essential. OIDC/attestation permission is confined
to the fresh publisher. A separate fresh advertising job gets contents-write only
after production verification of the published immutable asset. No permanent
release-signing secret is stored in Actions or on appliances.

After all required end-to-end checks pass, manually dispatch
`release.yml` on `master` with no inputs. The first publication must be `r-1`, with
null predecessor fields and an empty release/tag inventory. Later dispatches verify
the highest authenticated visible release and extend its manifest hash-chain;
there is no bootstrap/reset input. Both native architectures must pass the actual
public bootstrap-and-candidate tokenless checks before advertising the new release.

A partial publication can leave an orphan tag, draft or non-latest immutable
release. Inventory mismatch deliberately stops routine automation; it must not
invent a baseline, hide a failed release, reuse an immutable tag, or drop an
interrupted publication silently. The cold maintainer must inspect exact hashes,
evidence and remote state, then recover the original publication or perform an
explicit reviewed recovery. A completed but non-latest release remains part of
history. Keep all published predecessor manifests available for clients catching
up from older floors.

## One scheduler, separate observation

Release creation runs daily at 04:23 UTC through GitHub Actions, with inputless
manual dispatch using the same gates. Weekly bootstrap maintenance runs Sunday
at 03:41 UTC and makes a verified lock-only or empty keepalive commit. See
[automation](automation.md) for exact writer boundaries and repository-rule setup.
The ephemeral repository token must be allowed to perform this bounded write;
do not assume it bypasses arbitrary branch rules. Native verification happens
before the write; source verification is manual-only, and the writer must not rely
on a later verification dispatch.

These schedules are separate from appliance maintenance at 18:00 local. Releases
renew authorization after three days even when dependency contents are unchanged;
manifest expiry remains seven days. A configured schedule is not execution evidence.

The [monitor probe](../infra/release-monitor/README.md) has no credentials or write
operations. Independently poll its `/health` endpoint and configure failure and
recovery alerts. It checks both manual and scheduled runs, release success within
36 hours, bootstrap success within 15 days, workflow enablement, and at least
48 hours of release lifetime. It does not verify signatures or authorize updates.

Deployment, observed repository IDs, environment/branch rules and tested alert
routing remain external provisioning. The probe may run on Cloudflare or another
provider; measure actual request/resource limits before unattended operation.

## Outage and incident handling

On a build/application/security failure, retain the last accepted pin only where
its complete final acceptance and vulnerability gates still pass. A vulnerable
held package is not an excuse to publish a green OS update. A failure that cannot
be isolated is an exceptional core-maintenance or support-policy decision; clients
fail closed rather than weakening verification to keep a schedule green.

If GitHub/provenance policy is compromised, suspend the dispatch App, disable
publication using the cold identity, revoke active sessions/credentials as needed,
preserve evidence and notify users.
Do not treat a cryptographically valid attestation from a compromised trusted
workflow as proof of safety. Trust-root or verifier recovery is explicit and may
require out-of-band administrator action. An immutable release prevents asset/tag
rewriting, not whole-release deletion or malicious creation of a newer release by
an authorized compromised workflow. Maintain source/release backups outside GitHub
for continuity without describing those copies as an independently authorized update.

A locked or expired release does not stop the currently running machine. It stops
acceptance of an unqualified update and leaves operational failure visible. The
absence of new patches is still a security problem that needs attention.

Publish a corrected higher-sequence release rather than automatically downgrading
clients. Deleting an attestation from GitHub is not cryptographic revocation of a
bundle someone already downloaded, and changing latest does not revoke an immutable
release. Preserve predecessor manifests needed for lineage and describe remediation
honestly. No signed revocation feed or automatic quarantine mechanism is implemented.
Removing a harmful asset may be an exceptional containment choice, but can block
clients traversing history; it is not normal release cleanup. A compromised running
system may need out-of-band recovery, not merely a new attestation.
