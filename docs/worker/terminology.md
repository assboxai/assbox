# Controller, worker and mobile client

## Role names

Use role names in product documentation, operator messages and security claims.
The local managed-KVM topology contains three roles, even though only two run
on the Assbox appliance.

| Assbox role | Responsibility | Upstream or virtualization term |
| --- | --- | --- |
| **Controller** | Linux system running ChatGPT Desktop, Assbox management, QEMU/KVM and the SSH client | Desktop/app host; hypervisor host |
| **Worker** | Managed headless VM running the SSH server, Codex app server, selected agents, tools, repositories and scoped credentials | SSH host / remote development environment; VM guest |
| **Mobile client** | Phone or tablet sending prompts, approvals and follow-ups through Desktop Remote | Remote-control client |

```text
Mobile client
    |
    | Desktop Remote
    v
Controller: Desktop session + Assbox lifecycle + QEMU/KVM + SSH client
    |
    | controller-initiated SSH; private VM network
    v
Worker: SSH server + Codex app server + selected agents + project filesystem
```

“Host” alone does not identify a trust domain. In an SSH instruction, the SSH
host is the **worker**. In a virtualization instruction, the hypervisor host is
the **controller**. The SSH server's host key belongs to the worker; that is a
protocol identity, not a controller login credential. The controller owns a
separate client private key whose public half authorizes access to the worker.

The controller need not be bare metal. Running the controller inside another
VM requires working nested virtualization; the worker is still managed by that
controller. Neither a second independent installer nor a manually maintained
nested Assbox installation is part of the user workflow.

## Local and remote are relative

A shell running after `assbox worker shell` is local to the worker, despite being
displayed in a controller terminal. A path displayed in a Desktop SSH project
is a worker path. A local tool configured inside the worker is not thereby a
controller tool. Conversely, “This computer” in the Desktop UI designates the
controller in this topology; deliberately moving a coding chat there leaves
the supported worker-only operating mode.

Use **controller-local** and **worker-local** when the distinction matters.
Reserve **hypervisor host** and **VM guest** for low-level kernel, filesystem,
networking and device-model explanations. Use **SSH host** only for the SSH
endpoint and **SSH host key** for that endpoint's identity. Refer to another
trusted computer used for enrollment or review as a **trusted workstation**,
not simply another host.

OpenAI's SSH-project documentation supplies the shell/project-file routing
contract. Assbox separately qualifies each enabled integration and failure
path. See [source evidence](sources.md#s1--openai-remote-connections) and the
[client-routing procedure](client-routing.md). Do not infer all tool routing
or token permissions from a generic reference to host capabilities.

## Stable implementation names

Role terminology does not require renaming established configuration fields,
protocol directives, component IDs or on-disk state. Keeping these names avoids
an unnecessary migration while the architecture is being qualified.

| Existing identifier | Meaning in this implementation |
| --- | --- |
| `assbox.worker.hostAddress` | Controller side of the private VM link |
| `assbox.worker.guestAddress` | Worker side of the private VM link / SSH destination |
| `assbox.worker.hostReserveMiB` | Controller RAM reserve used for resource admission |
| `assbox.worker.extraGuestConfig` | Administrator-declared worker NixOS customization |
| `assbox.worker.allowGuestSudo` | Optional sudo inside the worker, never on the controller |
| `guestGeneration` / `GuestComponents` | Worker generation and worker selections in helper diagnostics |
| `hostLocalTools` / `HostLocalTools` | Whether the infrastructure helper enforces controller-local app tools; `not-enforced` is not a report that the remote agent can call them |
| `Host`, `HostName`, `HostKeyAlias`, `known_hosts`, `ssh_host_ed25519_key` | OpenSSH configuration/identity names; use their literal protocol spelling |
| `-cpu host`, QEMU `host` device parameters, Nix `hostPlatform` | Upstream virtualization/build syntax, not product-role selectors |
| Component IDs ending in `-remote-host` | Named remote execution backends; eligible selections belong in the worker |

The role meanings also apply to internal variables such as `guest` for the
separate NixOS evaluation. A wording update must not silently change wire
formats, addresses, storage paths, SSH identities or permission behavior.

## Product status

The controller/worker architecture is chosen. ChatGPT Desktop is the first
implemented adapter and the initial target for qualification, not an already
runtime-qualified integration. External workers, multiple workers and other
controller adapters are not selectable supported modes simply because the
roles can describe them. See [implementation status](implementation-status.md).
