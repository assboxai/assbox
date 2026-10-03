# Autonomous maintenance and release authority

Source verification (`verify.yml`) uses inputless manual dispatch only. Pushes and
pull requests do not start it. Dispatch the branch to review deliberately and verify
the run's exact SHA; a pass on an earlier commit does not qualify a newer one.

Release creation runs on GitHub Actions at `23 4 * * *` and through inputless
manual dispatch. Both events follow the same prepare, native architecture,
publication, public verification and advertisement gates. Installed provenance
policy accepts only `schedule` and `workflow_dispatch`. A successful workflow or
GitHub's mutable latest pointer does not replace authenticated release evidence.

Bootstrap maintenance runs weekly at `41 3 * * 0`, with inputless manual recovery.
After genesis it takes the lock from the highest authenticated immutable release.
An expired historical baseline is eligible for tooling maintenance, not installation.
Only a truly empty raw tag and release namespace permits initial `nix flake lock`.
A failed candidate may fall back to the committed lock only when both native
architectures verify that existing lock. No passing candidate or current lock
means no write, including no empty keepalive.

The prepare and native jobs have no write authority. Their evidence binds the
base master SHA, run ID, run attempt, plan digest, lock digest, native architecture,
and complete gate list. The writer rejects missing, duplicate, stale or mismatched
reports. Its only write credential is the ephemeral `GITHUB_TOKEN` in one Python
step. It never evaluates candidate Nix or invokes candidate binaries. It constructs
a single-parent commit whose tree differs only at `flake.lock`, or an empty commit
with the unchanged tree. An exact expected-head, non-force GraphQL ref update
rejects a concurrent master change. An uncertain API result is not retried with force.

Native verification precedes the write; the writer never relies on a follow-up
push-triggered run. Weekly verified commits address GitHub's public
repository inactivity suspension without requiring an external credentialed
scheduler. All required acceptance checks must exist and pass before this route
can maintain the branch. A missing check is a blocking failure, not optional coverage.

## Repository administration

Only `release.yml`, `bootstrap.yml` and the disabled-by-default development
`maintenance.yml` may declare schedules. Their entry jobs
require `assboxai/assbox`, `master`, and the reviewed schedule/manual events. The
workflow policy checks that every subsequent job remains dependent on that entry
guard and cannot run via an independent job or an `always()` job condition.

GitHub job conditions skip work but can still leave skipped scheduled runs in a
development copy's history. To suppress those events completely, disable the three
production-only workflows in that development repository using GitHub's
[workflow controls](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow).
After confirming the selected repository is **not** `assboxai/assbox`:

```sh
gh workflow disable release.yml --repo DEVELOPMENT_OWNER/DEVELOPMENT_REPO
gh workflow disable bootstrap.yml --repo DEVELOPMENT_OWNER/DEVELOPMENT_REPO
gh workflow list --all --repo DEVELOPMENT_OWNER/DEVELOPMENT_REPO
```

This repository setting also disables manual dispatch of those two workflows.
Leave `verify.yml` enabled for deliberate verification. Repeat this setup for each
independent development copy; YAML cannot disable workflows in other repositories.
Keep the schedules and production guard in source so the canonical repository
retains its reviewed release and bootstrap maintenance behavior.

The repository is expected at `assboxai/assbox`, on `master`. The zero repository
and owner IDs in `release/policy.json` are deliberately unprovisioned and must be
replaced with observed immutable identities only after repository creation. Release
authentication continues to reject zero IDs. Bootstrap supports this cold start,
then enforces each numeric identity once provisioned.

Protect `master` against deletion and force-push. Configure the `release-automation`
and `bootstrap-maintenance` environments for the exact master branch. Autonomous
maintenance requires a governance path that permits its bounded direct commit;
`GITHUB_TOKEN` does not inherently bypass arbitrary repository rulesets. A blanket
pull-request-only rule may block this operation. Do not grant broad bypass rights
or add a long-lived GitHub App credential as a workaround.

The external release monitor remains anonymous, read-only telemetry. It cannot
publish, dispatch, authenticate releases, or alter repository state. Operate an
independent health poll and alert route; do not treat a configured cron as proof
of scheduler liveness. No provider credentials belong in source or workflow artifacts.
