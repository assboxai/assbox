# Lifecycle and maintenance contract

Assbox owns managed packages, one reproducible upstream-compatible supervisor, updates and access policy. Upstream applications own conversation/session/task behavior. Do not install two service supervisors or run a vendor service-registration command as though it were a foreground daemon. In particular, inspect native remote startup contracts rather than assuming every `start` command stays in the foreground. [S01](sources.md#s01), [S20](sources.md#s20)

Use `happier-daemon` for the persistent Happier component. Inspect the selected supported user-systemd unit or export/dry-run and declare its equivalent through Nix with exact runtime paths. Upstream-compatible supervision does not authorize a mutable provider installer, competing unit or self-updater.

Presets install selected code; users authenticate/pair and approve meaningful authority separately. Service observations distinguish setup-required, ready, temporary failure, auth-required, configuration error, disabled and retired. Credential expiry or a provider outage is not by itself an unhealthy OS generation. Local liveness probes must not spend inference credits.

Pin selected agents, frontend bridges, plugins, browsers and helpers independently where required. Keep unselected CLIs omitted and stop frontend auto-installers from restoring them. Disclose unavoidable bundled SDKs and any explicitly qualified client-managed-runtime exception. Do not claim an exception is fully Nix-reproducible.

Retain immutable authenticated release consumption, staged build/publication, worker admission and boot acceptance. Routine maintenance remains automated with power checks, bounded retries and explicit grace behavior. An always-running assistant must not indefinitely veto security updates. Ordinary third-party application updates must not mutate system policy or run with administrative authority.

Restore availability after reboot without automatically replaying tasks with uncertain external effects. Account reauthentication, locked keyrings, upstream outages and damaged persistent state may still require owner attention. Diagnose them honestly rather than weakening permissions to keep a green light.

Nix rollback is not database rollback, token revocation or restoration of arbitrary persistent home content. Test application migrations and the supported rollback/recovery path. Backups require an actual configured destination and restore test; generation retention alone is not an independent backup.

Disabling/removing a managed service withdraws owned exposure, stops process groups and prevents resurrection across boot. Retain data unless the owner explicitly deletes it. Do not automatically migrate credentials or state when changing standalone/worker topology.

Resource policies account for the full selected combination: CLIs idle/active, physical GUI, Assbox worker, optional provider VM and optional virtual desktop. Preserve support for qualified older hardware; no assistant selection implies downloading a local model. Record measured hardware/capability results, not optimistic concurrency guesses.

External Desktop SSH may start its own remote process for the connection. Disable workload SSH before activating the experimental direct Codex relay to avoid sharing Codex session and credential state. Cloud Cowork, local bridges and any eligible provider VM have their own availability requirements.

## Native-policy activation lifecycle

Release qualification and effective local policy must both cover the current native client, platform, account/workspace and enabled features. A requested no-local-execution setting is not a readiness signal. Revalidate relevant changes before re-enable, preserve only compatibility-scoped evidence, and keep affected capability inactive on missing/ineffective/stale controls. Authentication/bootstrap cannot rely on briefly enabling the unrestricted client. Transient provider outage is not automatically loss of a locally enforceable policy, nor is a native safety hold an OS boot failure. See [instance policy](instance-types.md#native-kiosk-capability-selection).


## Happier setup ownership

Run `assbox component setup happier-daemon` to pair using the one-time URL from the upstream headless login (`happier auth login --no-open --method web`). The pinned SSH pairing flow can invoke an interactive repair of the vendor service, so SSH pairing is unavailable on this version. The managed CLI keeps vendor repair report-only and permits the install dry run for inspection. Assbox starts its declarative user service after successful setup. [S01](sources.md#s01)

Qualify expiry, interruption, cancellation, retry and revocation; protect every emitted URL/code and credential. Inspect whether pairing starts a daemon, installs code or changes a service. Preserve one Nix-declared supervisor and the owner's disabled state; a flow that cannot do so stays unavailable rather than weakening management. Happier authentication is distinct from the agent provider's authentication.

Native policy evidence includes independent Work/Codex/local-computer controls and permitted cloud transitions. Account changes or newly available helpers cannot inherit an unrelated Code-only pass. Refer to the [authority inventory](architecture.md#chatgpt-work-and-codex-are-separate-authority-surfaces); lack of a valid control is an activation hold, not an OS failure.
