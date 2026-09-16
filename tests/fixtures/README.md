# Disposable acceptance fixtures

`install_release.py` packages the actual source under test. `release_transport.py`
controls external HTTP and verified-certificate observations in a separate Rust
test executable. It does **not** supply cryptographic proof and is never installed
as the production `assbox` command. The authenticated-release VM separately runs
the pinned real verifier against genuine upstream signed fixtures.

`source_server.py` serves the exact locked source archives over isolated VM HTTPS.
Nix still verifies their NAR hashes. `mirror-test.key` and `mirror-cert.crt` are
public, disposable test TLS material, trusted only by this isolated test closure.
They are not release signing keys or production credentials. Never trust this CA
on a real machine or expose this fixture server outside the test network.

`installed_cases.py` installs and boots a real disk. `activation_cases.py` runs on
that installed disk. Their destructive commands address disposable guest devices.
The injected local NixOS module supplies the normal test-driver console and
isolated network settings; it is not part of the installed product configuration.
`installer_terminal.py` supplies explicit retry input through a test PTY.

The system-adapter Cargo tests separately run `password_terminal.py` against the
real password helper in a private PTY. They cover entry, cancellation, helper
failure, terminal restoration and secret output; no password agent or VM is needed.

The optical image is an installation-media observation fixture, not a claim that
the VM booted the public NixOS ISO. The Intel Mac fixture boots real rEFInd and
preserves an unrelated ESP payload and APFS-type partition. It contains no macOS.
Public release trust, real ISO boot, provider login and physical firmware/macOS
acceptance remain separate gates described in `docs/verification.md`.
