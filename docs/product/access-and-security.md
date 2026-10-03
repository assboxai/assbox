# Access, credentials and trust

## Installed is not authorized

Package selection installs code. Authentication grants account authority. Service activation starts persistent behavior. Network exposure makes a route reachable. These are separate actions and states. Turning a managed service off must stop its autostart and owned exposure; it cannot prevent arbitrary internet-capable code from implementing another remote service.

## Tailscale and internet access

Tailscale support is selected by default in guided presets but can be deselected. A supported/unenrolled root daemon has not joined a tailnet. Enrollment, HTTPS consent and application routes require deliberate owner action. Hosted Happier communicates through its relay and does not require incoming connectivity or an overlay. [S02](sources.md#s02)

Recommend private authenticated Serve for optional assistant dashboards and ordinary keyed OpenSSH for administration/workload access. Root owns Tailscale configuration. No default workload operator access, Tailscale SSH, subnet/exit advertisement, accepted routes or public Funnel. Access policy must distinguish administrator-to-Assbox reachability from Assbox-to-private-peer authority. [S26–S28](sources.md#s26)

Maintain root-owned execution-egress policy for both standalone and worker deployments: internet-only by default, explicit private exceptions, reviewed resolver/reply paths and IPv6 coverage. Do not assume a daemon-only wrapper controls SSH-launched tasks or that a permissive tailnet is safe. Internet-only is not protection against exfiltration to permitted public services.

The recommended dashboard profile uses application authentication plus private transport. Validate HTTP/WS/PTY authorization and Host/Origin/proxy behavior. An execution user must not spoof trusted identity headers or use a local helper to obtain blocked authority. Never publicly expose raw VNC, X11, browser debugging or an unprotected shell.

## Hermes dashboard profiles

Recommended: root-owned Tailscale Serve HTTPS to a loopback Hermes backend, with an exact non-loopback HTTPS `public_url` and configured native auth. Current documentation says the public URL activates authentication even behind loopback; verify it on the pinned build, including missing-auth refusal, protected HTTP/WS/PTY, Secure cookies and strict origins. Do not trust local identity headers as a replacement for app login. [S09](sources.md#s09), [S42](sources.md#s42)

An explicitly selected Advanced tunnel-only mode may instead rely on narrow tailnet/SSH authorization without Hermes login. State that app auth is absent; never expose it publicly, call it defense-in-depth, or use it as a silent fallback. A failed recommended auth contract blocks that route. Native app login does not isolate the dashboard from hostile code under the same execution UID.

## External controllers

Codex SSH from a Mac to a standalone Parallels guest requires no Tailscale when the reviewed local route works. Guest egress restrictions must still block unapproved new connections to the Mac/private peers while allowing authorized SSH replies. NAT and guest-shared folders are not security controls. Mac tool permissions and hypervisor sharing belong to the owner; [Coder options](coder-options.md) records their acceptance requirements.

## Credential boundaries

Assume compromise exposes deliberately supplied credentials, repositories and state within the execution domain. Use narrowly scoped development-repository credentials and dedicated control-plane accounts/scopes where appropriate. Do not pair an untrusted appliance and unrelated privileged workstation into one broad remote-control scope by default.

Encryption protects specified transport/storage paths, not a compromised endpoint. Happier encrypted sessions, metadata and connected-service credentials have different protections. Use real validated encryption settings for the selected release. [S03–S04](sources.md#s03)

Claude Remote requires a full-scope login rather than an inference-only setup token. This documentation does **not** establish that stolen execution-machine credentials can never access ordinary Claude chat history. Provider token authority requires explicit evidence; placing a token in a VM does not narrow its remote powers. [S16](sources.md#s16)

Do not store secrets in Nix expressions/store paths, normal logs or global browser profiles. Native kiosk keyring unlock is not automatically guaranteed after reboot. Keep ordinary first-use/keyring behavior rather than secretly weakening it to simulate unattended readiness.

## Failure and recovery

Canonical worker identities/persistent disks are validated and damaged state is refused, not silently replaced. Derived transport files may be regenerated from verified canonical material. These are consistency checks, not tamper attestation.

Separate root administration from agent execution. No passwordless agent sudo, root Docker socket or broad virtualization/device group as a setup shortcut. Report actual source/qualification limitations through [implementation status](../implementation-status.md); do not turn absence of evidence into a security guarantee.

## Native kiosk activation

The installer requests no controller-local agent execution; it does not create that security property by writing a setting. Before activation, verify the exact native build/platform/account and effective qualified controls. Unknown or failed controls keep the affected capability inactive, with only explicit independently qualified alternatives. Observe the same requirement on reconfiguration, launch, account/build changes and update/rollback; stale or execution-writable readiness records never authorize a native client. Authentication/bootstrap must not temporarily expose unrestricted local tooling to discover the policy. Browser policies and Code-only switches have limited scope; record which local file, browser, connector and helper surfaces remain enabled. [S15](sources.md#s15), [S39](sources.md#s39), [S51](sources.md#s51), [S52](sources.md#s52)

A managed worker is useful only when the client actually routes selected work there without local fallback. Linux Desktop worker routing requires its own evidence; the upstream-documented Mac and mobile-through-Mac routes do not establish it. See [platform evidence](coder-options.md#platform-specific-evidence-boundary).


For ChatGPT, evaluate [Work, Codex and cloud-to-computer authority separately](architecture.md#chatgpt-work-and-codex-are-separate-authority-surfaces). Neither a cloud label nor a valid SSH project constrains an unrelated controller-local tool. Any selected cloud executor has its own data/network policy; Assbox does not enforce its local firewall there.
