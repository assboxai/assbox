# Disposable acceptance fixtures

`install_release.py` packages the actual source under test. `release_transport.py`
controls external HTTP and verified-certificate observations in a separate Rust
test executable. It does **not** supply cryptographic proof and is never installed
as the production `assbox` command. The authenticated-release VM separately runs
the pinned real verifier against genuine upstream signed fixtures.

`source_server.py` serves the exact locked source archives over isolated VM HTTPS.
`source_mirror.py` preserves link targets and verifies each archive's unpacked NAR
against the lock before publishing its routes. Nix also verifies the downloads.
Small-tree tooling regressions exercise the same packer and reject the old link
transformation without building a VM. `mirror-test.key` and `mirror-cert.crt` are
public, disposable test TLS material, trusted only by this isolated test closure.
They are not release signing keys or production credentials. Never trust this CA
on a real machine or expose this fixture server outside the test network.

The disposable installer reads the entire offline Nix closure from a compressed
SquashFS block image. `store_image.py` adapts only the pinned QEMU module's exact
image-builder invocation to the real pinned `mksquashfs` tool. The guest mounts
that actual filesystem read-only by the declared virtio serial and keeps the
normal independent writable store overlay. The complete tar stream, source,
derivations and locked build inputs are retained. Additional content de-duplication
in the image writer is disabled; tar hardlinks retain their normal semantics. The
adapter removes Nix's inherited `SOURCE_DATE_EPOCH` before invoking `mksquashfs`
because the reviewed command already fixes both filesystem and file timestamps.
Compression does not replace
any installation, boot, interruption or recovery assertion.

`fixture-release-package.nix` also seeds the exact ordinary package compiled from
the fixture's complete source plus generated `release-context.json`. The compiler
revision and normalized source path match the real runtime release evaluation.
This avoids a redundant offline CLI compilation; the guest still evaluates and
builds the actual target configuration. The canonical fixture uses its actual
candidate revision, while the engine fixture keeps its declared disposable
revision. Source assembly uses the native host's production-pinned tools and does
not invoke a VM. Building that package remains a native target operation.

`nix-cache-test.key` and `nix-cache-test.pub` are also public disposable fixtures.
Only the test installer guest signs its harness dependency closure, and only the
disposable installed guest trusts that public key. This lets Nix enforce signatures
while the harness copies test dependencies into the target store. The fixture key
is never a production release key or host-store signing key; never add it to a real
machine's trusted keys. The fixture module embeds the public key in machine-local
configuration so pure evaluation does not need an unrelated source-store path.

`installed_cases.py` installs and boots a real disk. `activation_cases.py` runs on
that installed disk. Their destructive commands address disposable guest devices.
The injected local NixOS module supplies the normal test-driver console and
isolated network settings; it is not part of the installed product configuration.
`installer_terminal.py` supplies explicit retry input through a test PTY.

The system-adapter Cargo tests separately run `password_terminal.py` against the
real password helper in a private PTY. They cover entry, cancellation, helper
failure, terminal restoration and secret output; no password agent or VM is needed.

`remote_provider.py` supplies harmless executables for the remote lifecycle VM's
real adapter units. It can fail, exit cleanly or leave a child running and emits
only a synthetic diagnostic sentinel. It never authenticates or contacts providers
and is not installed by production modules.

The optical image is an installation-media observation fixture, not a claim that
the VM booted the public NixOS ISO. The Intel Mac fixture boots real rEFInd and
preserves an unrelated ESP payload and APFS-type partition. It contains no macOS.
Public release trust, real ISO boot, provider login and physical firmware/macOS
acceptance remain separate gates described in `docs/verification.md`.
