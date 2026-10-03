# Development instructions

Use the pinned root Justfile/Chainman entrypoints on native Linux. Read
`docs/development.md`, `docs/repair-loop.md` and `docs/development-maintenance.md`.
The nested developer flake owns local tools; production release/bootstrap paths
use explicit root `release-check`/`release-tools` environments and stay Chainman-free.

Use `just verify-lite` for static/Rust work and `just verify-prepare` for finite
preparation plus mutation/configuration checks. These never dispatch a VM or update
transaction. Full `just verify`, production/Nix stages, VM recipes, repair-once and
dependency previews can build or run VMs. Finish existing gates before interpreting
a new canonical test. Do not substitute targeted checks for a full-gate pass.

Keep the root production lock and release authority under their existing ownership.
Cargo/Actions changes need explicit dependency review; never edit the approval guard
to make a proposal approve itself. Preserve all existing acceptance assertions.
Tracked developer code and locks remain authenticated core source; exclude only
generated caches/artifacts, never create a filtered production source model.

Repair sessions use explicit external private paths and a frozen reviewed oracle.
Modify product code and add regression tests within the session's admission rules.
Do not edit its judge, budgets, pins, workflow authority or old assertions. A required
oracle correction gets a separately reviewed new session. Report real exit/status,
source identity, architecture and cleanup uncertainty. Same-user isolation is
cooperative, not tamper-proof. Never install to a host device or attach real secrets.

Local source edits and verification do not authorize remote writes, publication,
workflow dispatch, automation enablement or repository administration. Maintenance
stays disabled until its separate two-architecture and administrator qualification.
Keep run logs, disk images, credentials, machine profiles and delivery records outside
source. Do not silently stage, commit, waive checks or fabricate a green result.
