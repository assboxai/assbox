# Implementation candidate and qualification status

This source implements the accepted greenfield product contract against exported master `3ca0032cf026c9883a60fa03425a1c9bf2ef4b76`. The 244 baseline file hashes matched before changes. No donor application tree was imported. The architecture is frozen; native, authenticated and hardware qualification remains outstanding.

| Work | Mechanisms in this candidate | Qualification |
|---|---|---|
| W01–W02 | Product documentation, retired component/backend removal, base recovery tools retained | Baseline reviewed; release acceptance not run |
| W03–W04 | Independently held Happier/Hermes/Pi/OMP families, pinned Happier artifacts, minimal Hermes extras, guarded native launchers, existing portals/keyring | Both architecture builds and exact native prerequisites not run |
| W05–W06 | Data presets, pure resolution and exclusions, purpose-first wizard, frozen ordinary Nix settings, transactional `configure` preview/apply | Deterministic core checks pass; complete terminal transcripts not run |
| W07–W08 | Execution-UID IPv4/IPv6 egress, receiving-socket loopback IPC gate, PAM admission and shutdown revocation, root-only Tailscale control and scoped Serve reconciliation | Network namespace, NAT, cgroup/socket behavior and authenticated Serve not run |
| W09–W13 | Configuration/runtime-bound setup markers, durable disable, private diagnostics, Nix-owned foreground services, provider setup and exact Happier agent paths | Provider sessions and pairing effects not run |
| W14–W15 | Exact client/platform/account/policy native contract, separate Codex/Work/local-access inventory, fresh root observations and supervised launch, independent conditional Cowork gate | No native contract ships qualified; selected apps stay inactive until qualified |
| W16 | Optional browser/private desktop resources, environment scrubbing, explicit display lease and cleanup, provider-managed Cursor route and minimal Hermes/OMP launch path | Desktop stacks and provider tool behavior not run |
| W17 | Existing storage/admission/recovery retained; bounded noninteractive Ed25519 identity parsing before mutation | Small identity tests pass; real disk/VM fault qualification not run |
| W18–W19 | Family release gates, exact lock validation, service resource limits, private mutable-state checkpoints and explicit restore/recovery journal | Package/security scans, state schema upgrade/rollback and resource qualification not run |
| W20–W23 | Operational documentation and complete acceptance ledger, dated Linux capability evidence, external Mac/Parallels/SSH procedure | All 116 release qualification requirements remain `not_run` |

The [acceptance ledger](../qualification/acceptance.json) preserves the supplied requirements and their evidence fields. [Work packages](../qualification/work-items.json) retain engineering order. [Qualification instructions](../qualification/README.md) explain how to attach actual results. Source mechanisms and harmless fixtures are not native or account qualification.

The remaining contract-dependent paths are explicit. Antigravity Remote and experimental direct Codex relay require an immutable reviewed foreground argv; an empty contract stages them without starting a service. Native policy needs an exact qualified probe and account scope; installer selection alone cannot establish this. Conditional local Cowork requires independent provider-VM evidence. Hermes authenticated HTTPS requires an exact public URL, native dashboard authentication and owner-approved exposure; tunnel-only is a separate explicit Advanced choice.

No Nix package build, system rebuild, VM run, native login, authenticated provider task, disk operation or publication was performed for this candidate pass. Lightweight checks use a separate temporary Rust target directory. Their tool-path environment is for compilation only and is not a release tool closure.

Happier currently uses the reviewed artifact manifest because its held package-recipe snapshot has no Happier derivation. A changed recipe revision without a Happier derivation fails the family gate and remains held; it cannot masquerade as a runtime update. When an upstream recipe supplies Happier, its independently pinned derivation and compatibility gate become the normal path. Updating the fallback artifact manifest requires a reviewed source change.

The [lightweight candidate check record](../qualification/candidate-checks.json) records the tested commit, lock digest, commands and explicit skips. The 101 deterministic Rust core tests pass; workspace compile/Clippy, cached module fixtures and focused helper/static checks pass. The privilege-dependent helper case is skipped. These results do not advance the 116 release qualification entries. Source changes are granular local commits; repository publication is currently blocked by unavailable GitHub write authentication.
