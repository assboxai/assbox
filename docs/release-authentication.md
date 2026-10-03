# Authenticated immutable releases

## Trust model and implementation boundary

Assbox delegates cryptography to the Nix-pinned GitHub CLI and its Sigstore/TUF
verification machinery. It does not implement signatures in Rust, hold a release
private key, install a GitHub token, or require a human to sign daily dependency
releases. The trusted repository is `assboxai/assbox`, its default/source branch is
`master`, and the trusted workflow is `.github/workflows/release.yml` at
`refs/heads/master`. Numeric repository and owner IDs prevent silently accepting a
replacement with the same name. These IDs must be independently checked and
provisioned in `release/policy.json`; zero is a hard bootstrap refusal.

Release use requires native compilation, real tokenless GitHub verification and
end-to-end acceptance under the [verification contract](verification.md). Parsed
fixtures do not establish cryptographic verification. Repository protections and
trust identities require separate administrator provisioning.

GitHub, its OIDC issuer, Sigstore trust services, the protected repository/workflow,
and the initial trusted installer remain trust roots. A sufficiently privileged
GitHub compromise can authorize malicious software. Provenance proves origin and
integrity under that trust model, not software safety or independence from GitHub.
A root-owned local Nix customization is a separate administrator trust decision.

## Frozen source, changing dependencies

A release binds the core Git commit to an exact generated dependency lock. The
committed `master` lock is a reviewed bootstrap/development toolchain, not a file a
bot must update daily. Read-only CI builders update `nixpkgs` and the independently pinned package families
listed in the reviewed component catalog. Generated release-family metadata keeps
strict root-input and held-input validation synchronized. Shared-runtime capabilities
advance together; standalone Codex remains separate from ChatGPT. Editors and the
standalone fixed-hash VS Code CLI recipe follow the OS/core release. The catalog is
authenticated as part of the exact source archive and core identity.

Each advancing application is probed with the advancing OS on both native
architectures. A failed application probe retains that application's previous
complete input subtree, not merely its top-level revision. Root-relative follows
paths keep their declared meaning; genuinely shared dependencies are not magically
independent. The composed final release must then pass every application, system,
installation/recovery/authentication and vulnerability gate again. A held pin never
gets an exemption from a security finding. Failures in the final combination block
publication, even when an earlier individual probe passed.

Builders normalize composed locks with Nix before hashing them, checking that every
reachable dependency and input edge retains its selected meaning. This permits
Nix's node renaming and sharing without advancing a pin. Native verification also
requires the source lock to equal Nix's resolved graph exactly, matching the client
binding check; lock-update flags alone do not enforce this equality.

The source tarball contains the exact tracked core bytes and executable modes,
with only `flake.lock` replaced and `release-context.json` added. Context contains
the core commit/version and lock digest. The publisher independently compares all
archive members with the frozen Git commit before attesting or uploading. It never
executes Nix or candidate programs in a job with write/OIDC privileges.

A release has four assets: `release.json`, `release.sigstore.json`, `flake.lock` and
`assbox-source.tar.gz`. The manifest binds schema/protocol, stable channel, monotonic
`r-<sequence>` tag, core version/commit, issue/expiry times, both architectures,
source archive SHA-256, source NAR hash, lock SHA-256, held application inputs,
and the exact predecessor tag and manifest SHA-256.
The source NAR and archive hash describe different representations of the same
release source; neither is a Git commit hash.

The manifest is attested by the exact protected GitHub workflow. The workflow then
creates a draft, uploads all assets, publishes it as an immutable release, and checks
immutability without advertising it as latest. A separate read-only matrix runs a
two-stage public check on both x86-64 and AArch64. The bootstrap client, built from
the reviewed master lock, first authenticates and downloads the exact published tag.
Only its root-owned `verified-source-path` authorizes the candidate build: Nix builds
`assbox` from that immutable store tree with the **release's own lock**, without
updating inputs. The candidate client then independently verifies the same tag in
a second, previously nonexistent directory. Manifest bytes, lock bytes and verified
store path must agree. The candidate may equal the bootstrap binary for an unchanged
authorization renewal; a different output is not a correctness requirement.

Both processes are tokenless. This tests the actual release verifier and its Nix/gh
dependencies, not just the bootstrap verifier. It establishes a current public
round trip when executed, not proof against every future API change or a substitute
for installed-floor/lineage failure injection. Only success of both stages on both
architectures permits the fresh contents-write job to set the latest discovery hint. Release tags
point to the core commit; many dependency releases can share that commit. There is
no push to `master` or `stable`, no PAT and no daily manual environment approval.

## Manifest encoding, genesis and authenticated history

The current manifest has schema **3** and protocol **3**. Its fields are exactly:

```text
schema, protocol, channel, tag, coreCommit, coreVersion, issuedAt, expiresAt,
sourceSha256, sourceNarHash, lockSha256, systems, heldInputs,
previousTag, previousManifestSha256
```

The primary attested object is canonical `release.json`: sorted keys, compact JSON,
ASCII encoding and one final newline. Integer times are Unix seconds; the validity
interval is exactly seven days. Unknown fields, alternate byte encodings and mixed
or missing parent fields are refused. The hash of a manifest always means the
SHA-256 of its exact canonical file bytes, not a reserialized approximation.
Any future executable release asset should also receive its own build attestation.

The first release is reserved as **`r-1`**, with both parent fields null. Only a
completely empty observed release/tag namespace permits its creation. There is no
`bootstrap` workflow input or reset switch. Every later manifest names a lower
sequence and the digest of that predecessor's manifest; its issue time cannot be
earlier. Later sequence values normally use the publication preparation time, or
one above the previous sequence if necessary; they need not be consecutive.

CI inventories all public `r-*` releases and tags with bounded pagination. After
genesis, tags/releases outside `r-*` (for example `v0.1.0`) do not participate in
channel history; this is also the availability monitor's selection rule. Raw
pagination still includes those entries. A malformed reserved `r-*` name is an
error, not an ignorable source tag. A draft, nonimmutable release, malformed/duplicate
identity, mismatched release/tag inventory, or missing genesis stops the operation. The highest sequence is a **candidate**
head until the production verifier authenticates it. A higher invalid release is
not silently ignored in favor of an older one. The authenticated head must name
the second-highest visible sequence as its predecessor. CI recovers dependency pins
from that exact authenticated manifest, never from GitHub's `/releases/latest`.

The attestation step is immediately preceded by evidence and current-master checks.
Each subsequent GitHub write (tag, draft, upload, final publication and advertising)
re-observes the current master SHA before attempting that effect. A stale run cannot
intentionally continue writing after that check fails. These separate API reads and
writes are **not atomic compare-and-swap transactions**: cold-administrator changes,
branch protections and job isolation remain part of the contract.

Immediately before tag creation, publication rechecks the visible head and its
exact predecessor-manifest digest. A changed head invalidates the prepared
candidate. The workflow serializes release attempts; the final advertising job also
refuses any release that is not still the current highest head. Re-running an older
advertising job cannot deliberately move the channel backward, even while `master`
is unchanged. A changed or absent latest hint does not change the CI baseline.

GitHub's immutable-release tag non-reuse rule gives the reserved genesis a useful
additional guard: deleting history does not authorize silently recreating `r-1`.
It is not a separate transparency proof. GitHub API inventories cannot prove that
a compromised trusted authority has not hidden/deleted an entire suffix, including
its tags. Installed clients additionally require a hash-chain extension of their
own persisted floor. New installations require an explicit release chosen through
the trusted bootstrap procedure; an explicit tag establishes identity, not proof
that no newer release exists. Whole-history censorship by the trusted authority is
outside this trust model, and missing history can block availability.

Manifest schemas before 3 are not accepted. This schema is finalized before initial
production commissioning; there are no deployed clients to bridge. Future deployed
protocol changes require an explicit reviewed migration, never a fabricated parent.

## Installed verification order

The latest-release endpoint is an untrusted discovery hint, not an authorization.
It is consulted by ordinary updates only after installed replay state exists. An
explicit release is required when no floor exists; `install --apply` refuses a
missing `--release` before probing or writing disks. Backward or missing discovery
can stop an update, but cannot reset its floor or become a CI baseline.
Before candidate Nix evaluation the shell downloads bounded manifest/bundle bytes,
verifies the manifest as an immutable release asset, then verifies artifact
provenance with the exact certificate identity, issuer, source ref, source digest
and signer digest. Self-hosted runner provenance is refused. Numeric identities and
the allowed `schedule` or `workflow_dispatch` trigger are taken from verified certificate
extensions, not arbitrary claims inside a predicate. A predicate cannot authorize
its own repository, runner or triggering event. The `release-automation` environment
is an externally configured GitHub restriction, not an invented certificate claim;
its name alone is not cryptographic proof that protection rules were enforced.

Pure Rust policy checks schema, channel, architecture matrix, identity, sequence,
equivocation and time bounds. Release expiry is seven days; source-identical heartbeat
releases renew authorization after three days. A broken publisher cannot leave a
valid old release indefinitely replayable. Verification requires systemd to report
synchronized time and applies the local system clock; this is not independent
protection against a compromised clock/NTP infrastructure. An unknown or unsynchronized
clock stops acceptance. No expiry-ignore option exists for updates or installation.

For an installed machine, the verifier walks the candidate's hash-linked parent
manifests back to the exact local floor (sequence, digest and issue time). A parent
is hashed before parsing, then checked for canonical encoding, decreasing sequence
and consistent time. An authenticated child's digest authenticates the parent's
exact bytes; ancestor manifests need not still be unexpired and are not treated as
new installations. Skipped floors, forks, changed/missing parents or a chain longer
than 16,384 links refuse acceptance before candidate Nix processing. A machine
that misses that many releases requires expert recovery instead of an unbounded
network walk.

Next the shell checks the lightweight tag's core commit, verifies the downloaded
source and lock hashes, and uses `nix store prefetch-file --unpack` to unpack into
the Nix store without evaluating the flake or consulting flake registries. The
resulting NAR and embedded lock must agree with
the authenticated manifest/assets. Only then does source binding use Nix metadata,
carry the locked graph into the local flake and evaluate/build with local hardware.
Source binding disables registry lookups too; no mutable branch is resolved at
this point.

The locally generated flake has an ordinary literal immutable release-asset URL
with a `narHash` query. It does not import dynamically computed flake inputs or use
a private configuration database. The CLI edits only its recognized input line;
custom source layouts require ordinary NixOS administration rather than destructive
normalization. Files in `local.nix` remain human-owned.

## Replay state and recovery

`/var/lib/assbox/release-state` is a root-owned high-water mark containing sequence,
manifest digest and issue time. An equal-sequence identical retry is permitted;
a lower sequence, older issue time or equal-sequence different manifest is refused.
An installed updater refuses missing or corrupt state instead of resetting trust.

After authentication and source digest checks, the updater durably advances this
mark **before** candidate Nix metadata/evaluation. It is deliberately outside the
configuration rollback transaction. A failed build can retry exactly that release
but cannot silently fall back to an older authorization. This is an acceptance
watermark, not evidence the machine booted the release.

The multi-file source journal records `flake.nix`, `flake.lock` and
`assbox-release.json` intent before any individual atomic rename. Recovery checks
all changed paths against old/candidate bytes before restoring any; an unrelated
edit causes refusal. Interrupted restoration can resume. Selecting or restoring an
older system generation never decreases the release watermark. Recovery cannot
undo mutable application data or external agent actions.

`assbox release verify TAG DIRECTORY` authenticates and downloads into a new private
directory without installing or changing replay state. Its `verified-source-path`
can be used to build an installer from authenticated source. CI has an internal
historical-baseline inspection route that allows an expired prior release only to
recover tested dependency pins after an outage. It still verifies signatures,
identity, hashes and validity-interval structure. It cannot be used by the install
or update paths and never changes installed acceptance state.

## Tokenless verification and operational constraints

The official GitHub CLI currently places an authentication prompt/check in front
of its read-only release verification commands, even for public data. Assbox's
`nix/anonymous-gh.nix` applies a narrow, fail-on-layout-change patch to remove only
that front-door login requirement for `release verify` and `release verify-asset`.
It does not bypass certificate, signature, transparency, TUF, identity or digest
verification. Bundle-based `gh attestation verify` already supports tokenless use.
The patch and actual no-token path must pass native acceptance on both architectures.

Read-only CI discovery explicitly binds its ephemeral, contents-read job token as
`GH_TOKEN` in a separate API-only Python step. That process exits before the next
step starts Nix or candidate tools. Child-process environments are also scrubbed.
The release helper forwards a token to a subprocess only for the fixed asset-upload
command; tokens are never persisted in source or handed to installed machines.

Explicit environment bindings are not the entire authority boundary. GitHub makes
`github.token` available to actions even when the workflow does not explicitly pass
it, and permissions apply to the whole job. Every action running in a privileged
job is therefore trusted with that job's token permissions. Checkout, artifact
download and attestation actions must remain exactly pinned and allowlisted;
removing an explicit `GH_TOKEN` binding would not make such an action unprivileged.
See GitHub's [job-token documentation](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).

The workflow guard scans mapping keys and values throughout workflow and job
structure, including outputs, conditions, dependencies and matrices. Token access
is permitted only at the exact reviewed command's step-level `env.GH_TOKEN` value,
with its complete expected environment. Whole-context serialization, wildcard or
dynamic GitHub-context indexing, secret contexts and alternate token expressions
are refused. Reviewed scalar identity reads remain allowed. This deliberately
restricted expression policy is not a general expression parser or a restriction
on an action's implicit token access. Fresh job isolation, minimal permissions,
reviewed action code and repository protections remain necessary.

The private command environment clears caller credentials, uses an empty GitHub
configuration directory and the Nix CA/tool closure. Public API limits, GitHub or
Sigstore outages, expired trust metadata and unavailable assets can block updates;
shared public IPs may reach anonymous limits. Bounded retry never weakens checks.
An immutable release can still be removed as a whole, and display metadata/latest
can change; availability and authentic bytes are different properties.

The first trusted installer is an explicit bootstrap trust anchor. Do not evaluate
a moving branch to obtain an allegedly authenticated verifier. A new trust policy,
repository transfer, removed GitHub/Sigstore identity or unsupported schema requires
an exceptional reviewed core change or explicit expert recovery. Candidates cannot
authorize their own new trust root. [Governance](governance.md) describes cold-account
provisioning, incident response and monitoring; this source does not configure them.

## Required acceptance and primary references

The actual authenticated-release VM must exercise valid provenance and immutable
release verification, altered manifests/assets/bundles, wrong repo/owner/workflow/
ref/commit/runner/trigger, malformed or excessive input, expiry and clock failure,
network/TUF failures, NAR/lock mismatch, replay/equivocation, three-file interruption
and rollback without lowering the watermark. Refusal must precede candidate Nix
evaluation. Include backward/missing latest pointers, paginated history, orphan tags,
deleted genesis, invalid highest releases, stale promotion reruns, parent tampering,
forks and skipped floors. The post-publication live verification matrix complements, not replaces,
that VM. Missing acceptance checks deliberately block publication.

Primary interface references: [GitHub attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations),
[immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases),
[artifact verification](https://cli.github.com/manual/gh_attestation_verify),
[release asset verification](https://cli.github.com/manual/gh_release_verify-asset),
[offline verification/trust](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline),
and [Nix prefetch](https://nix.dev/manual/nix/2.35/command-ref/new-cli/nix3-flake-prefetch).
