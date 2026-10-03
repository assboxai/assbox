# Contributing

Keep the product ordinary NixOS and keep machine hardware state local. Read the
[architecture](docs/architecture.md), [development](docs/development.md) and
[verification](docs/verification.md) documents before changing policy or effects.

Contributions must respect the internal-crate dependency direction, pure-core
boundary, explicit privileged operations and failure/recovery contracts. Unsafe
Rust is forbidden in project code. Do not hide effects in injected core callbacks,
weaken checks to make tests pass, or describe unavailable validation as successful.

Change requirements, production behavior and independent acceptance tests together.
Tests must assert intended behavior and meaningful forbidden outcomes, not just
repeat the implementation. Include stale observations, interrupted effects and
negative cases when extending boot/storage/maintenance behavior. Review both test
code and production code for omissions.

Run `just setup` and the genuine locked `just verify` gate. Use `just verify-prepare`
for finite work without VM execution. Follow the [repair protocol](docs/repair-loop.md)
and [dependency ownership](docs/development-maintenance.md). Formatting is done with the locked Rust
and Nix formatters, not a handwritten imitation. Keep documentation about maintained
behavior, interfaces and operational requirements. Put captured validation results,
delivery notes and development-session commentary outside the source archive.
Do not commit private machine profiles, credentials or generated caches.

Contributions to Assbox code are under GPL-3.0-or-later. Retain appropriate copyright
and third-party notices. Do not introduce a dependency without reviewing its
license and transitive supply chain. There is no mandatory contributor agreement
in this source tree.
