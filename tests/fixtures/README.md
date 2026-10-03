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
