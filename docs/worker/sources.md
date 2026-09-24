# Sources and repository evidence

OpenAI Remote and authentication interfaces (S1/S2) checked on **September 24, 2026**. Account lifecycle and tmpfiles semantics (S12/S13) checked on September 24, 2026. Other source entries retain their September 22, 2026 review date. Product behavior may change; the release acceptance record must include actual client versions. This ledger supports narrow interface facts. The architecture, defaults, threat model and implementation decisions are Assbox design choices, not claims that a vendor has certified this configuration.

## Primary external sources

### S1 — OpenAI remote connections

<https://developers.openai.com/codex/remote-connections>

Canonical documentation currently redirects to:
<https://learn.chatgpt.com/docs/remote-connections>

Interface mapping: Desktop/app host = controller; SSH host = worker. The SSH
project section places commands and file operations on the SSH machine and
requires its Codex installation/authentication. Mobile remains connected to
Desktop. This supports the normal controller-to-worker coding path; generic
host-capability wording does not establish a return path to controller tools.
The app-server transport should not be exposed publicly.

The worker-or-unavailable rule for skills, MCP, browser/Computer Use and other
integrations is Assbox's deployment acceptance requirement, not a published
blanket token-isolation or tool-routing guarantee. See
[client routing](client-routing.md) for the required observations.

Linux Remote is the user-supplied deployment premise. This source still contains
platform wording that does not independently establish Linux Remote support;
record behavior of the installed Linux build instead of treating that wording
as either a veto or proof of success.

### S2 — OpenAI authentication

<https://developers.openai.com/codex/auth>

Canonical documentation currently redirects to:
<https://learn.chatgpt.com/docs/auth>

Relevant facts: ChatGPT sign-in uses subscription access; API-key sign-in is separately usage-billed. Headless device-code login is available subject to account settings. The worker displays a URL/code; the user enters that code in the trusted browser, and the worker completes authorization. Codex stores its cached credential according to its configured credential backend. Cached tokens must be treated as sensitive. The proposal does **not** derive a guarantee about access to historical chats from these documentation pages.

### S3 — Chromium Linux password storage

<https://chromium.googlesource.com/chromium/src/+/HEAD/docs/linux/password_storage.md>

The documented `basic` backend is plaintext; `gnome-libsecret` selects that integration. Chromium also documents falling back to `basic` if the selected backend is unavailable. This supports removing a forced-basic launcher argument, not claiming every session secret is now encrypted or that an unattended keyring unlock has been solved.

### S4 — QEMU security guidance

<https://www.qemu.org/docs/master/system/security.html>

Relevant principles: use an unprivileged VMM process, restrict its controller resources, and protect management interfaces. The design therefore uses a separate VMM user, private QMP, controller resource controls and KVM-only operation. It does not present software emulation as an equivalent failover security mode or claim that hardware virtualization prevents all escapes.

### S5 — NixOS full image builder

<https://raw.githubusercontent.com/NixOS/nixpkgs/master/nixos/lib/make-disk-image.nix>

The implementation uses the existing nixpkgs image-builder interface with a full qcow2 worker image, no installed bootloader and direct kernel/initrd boot. Source inspection informed the parameter choices; native Nix evaluation/build remains required. Deployment uses the repository's exact lock, not the moving branch URL in this explanatory source ledger.

### S6 — NixOS development VM defaults

<https://raw.githubusercontent.com/NixOS/nixpkgs/nixos-26.05/nixos/modules/virtualisation/qemu-vm.nix>

The development VM module includes controller-store sharing conveniences. The production worker does not rely on those defaults: it uses an image-contained worker store and explicit QEMU arguments. A NixOS network test fixture is not mistaken for the production no-share boundary.

### S7 — NixOS networking and SSH modules

<https://raw.githubusercontent.com/NixOS/nixpkgs/nixos-26.05/nixos/modules/services/networking/nftables.nix>

<https://raw.githubusercontent.com/NixOS/nixpkgs/nixos-26.05/nixos/modules/services/networking/firewall-nftables.nix>

<https://raw.githubusercontent.com/NixOS/nixpkgs/nixos-26.05/nixos/modules/services/networking/ssh/sshd.nix>

These are the primary module interfaces reviewed for nftables table composition, forwarding policy, reload behavior and SSH configuration. The production packet tests, key bootstrapping and actual image boot must confirm that the evaluated deployment behaves as designed.

### S9 — Nix self-contained output references

<https://nix.dev/manual/nix/latest/language/advanced-attributes.html>

Nix documents structured `unsafeDiscardReferences` for outputs such as self-contained filesystem images with an embedded Nix store, and structured per-output `allowedReferences`/`maxSize` checks. Discarding references is unsafe for ordinary executable outputs with real runtime dependencies. The worker artifact consists only of self-contained image/initrd/kernel blobs, command-line data and its manifest; a native closure/layout test enforces the intended boundary. Worker vulnerability scanning remains separate.

### S10 — Pinned NixOS account and shell evaluation

<https://raw.githubusercontent.com/NixOS/nixpkgs/c3eea5b2156db11c7eeeada3dc737711255b253e/nixos/modules/config/users-groups.nix>

<https://raw.githubusercontent.com/NixOS/nixpkgs/c3eea5b2156db11c7eeeada3dc737711255b253e/nixos/lib/utils.nix>

These are the repository's pinned nixpkgs sources. The account module's static lockout assertion considers privileged passwords and static user SSH keys, not keys later supplied on a runtime seed. `users.allowNoPasswordLogin` explicitly permits that intentional account configuration; it does not change SSH authentication settings. `utils.toShellPath` accepts a shell package with `shellPath`, or a shell path string, but rejects a derivation that is merely a script package. The worker uses the executable subpath and a native worker-assertion evaluation gate.

### S11 — OpenSSH configuration scope

<https://man.openbsd.org/ssh_config>

OpenSSH supports `Host` blocks, whitespace or equals separators, quoted arguments and global defaults. Most directives take their first obtained value, while identities and forwarding declarations can accumulate. The managed worker block restores wildcard scope before existing text and explicitly fixes its destination, port and authentication controls. Advanced controller-supplied includes and forwarding rules require inspection; the merge is not a general SSH configuration sandbox. The native policy gate parses the generated configurations without initiating a network connection.

### S12 — Pinned NixOS account lifetime and activation

<https://raw.githubusercontent.com/NixOS/nixpkgs/c3eea5b2156db11c7eeeada3dc737711255b253e/nixos/modules/config/update-users-groups.pl>

<https://raw.githubusercontent.com/NixOS/nixpkgs/c3eea5b2156db11c7eeeada3dc737711255b253e/nixos/modules/system/activation/specialisation.nix>

This is the root flake's nixpkgs revision, resolved through `nodes.root.inputs.nixpkgs`
in the supplied lock. Declarative users/groups removed from a configuration are
removed from the live account database; saved UID/GID maps are used when those
identities are reactivated. That does not make the absent account resolvable to a
pre-activation admission check. The worker therefore retains its inert ownership
identities while Assbox is enabled. A native specialisation/disabled-reboot test
exercises actual activation, not only source-string matching.

### S13 — systemd tmpfiles directory handling

<https://raw.githubusercontent.com/systemd/systemd/main/man/tmpfiles.d.xml>

A `d` rule can adjust owner, group and mode on an existing directory. The worker
state directory instead has explicit create-only provisioning and non-mutating
validation so unexpected metadata is not hidden before admission. The native
lifecycle gate checks this behavior on the pinned deployment; the moving manual
is not evidence that the gate has run.

## Repository evidence index

The proposal is based on the uploaded source archive, inspected as files rather than inferred from a project summary. Input hash and deliverable hashes are recorded in the package manifest.

| Concern | Source locations |
| --- | --- |
| Assbox module composition | `modules/default.nix`, `modules/options.nix` |
| Controller accounts and baseline | `modules/base.nix`, `modules/access.nix` |
| Explicit component consent and placement | `catalog/components.json`, `modules/components.nix`, `crates/functional-core/assbox-domain/src/components.rs` |
| Desktop launcher/keyring | `modules/applications.nix`, `modules/components.nix`, `modules/presentation.nix`, `docs/configuration.md` |
| Reusable worker applications | `modules/applications.nix`, `modules/remotes.nix`, `modules/editors.nix` |
| Local configuration escape hatch | `docs/configuration.md`, `crates/imperative-shell/assbox-engine/src/manage.rs` |
| Generation/recovery integration | `modules/generation.nix`, `modules/maintenance.nix`, `crates/imperative-shell/assbox-engine` |
| Source/authenticated release checks | `flake.lock`, `release/policy.json`, `scripts/release.py`, `scripts/release-check` |
| Verification architecture | `scripts/verify`, `tests/nix`, `tests/tooling` |
| Persistent infrastructure identity and admission | `modules/worker/identities.nix`, `scripts/worker/worker.py`, `tests/nix/worker-lifecycle-vm.nix` |
| Worker design implementation | `modules/worker`, `nix/worker-image.nix`, `scripts/worker`, `tests/worker` |

No exported personal chats, account tokens, SSH private keys, generated VM images, provider binaries or font files are part of this source package. Runtime identity creation happens on the installed controller, not during artifact generation.
