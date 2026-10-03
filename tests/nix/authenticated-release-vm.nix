# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, assbox }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  harness = import ./acceptance-harness.nix { inherit pkgs assbox; };
  unprovisioned = assbox.overrideAttrs (_: {
    ASSBOX_REPOSITORY_ID = "0";
    ASSBOX_OWNER_ID = "0";
  });
  gh = pkgs.callPackage ../../nix/anonymous-gh.nix { };
  # Real signatures, certificates and transparency evidence from the exact pinned
  # verifier source. The custom root is passed only to these direct crypto tests.
  fixtures = "${pkgs.gh.src}/pkg/cmd/attestation/test/data";
in
pkgs.testers.runNixOSTest {
  name = "assbox-authenticated-release";
  requiredFeatures.kvm = !arm;
  nodes.machine = {
    environment.systemPackages = [
      pkgs.nix
      pkgs.python3
      pkgs.jq
      gh
      unprovisioned
    ];
    environment.etc."assbox-acceptance-vm" = {
      text = "disposable\n";
      # The harness deliberately requires a root-owned regular file.
      mode = "0600";
    };
    nix.settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
    # Authenticating an explicit archive must not depend on registry availability.
    # A real registry lookup fails even if a runner happens to have network access.
    nix.settings.flake-registry = "file:///no-such-assbox-registry.json";
    virtualisation.memorySize = 2048;
    virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
    virtualisation.additionalPaths = [
      harness
      pkgs.gh.src
    ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json
    import shlex

    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("mkdir -m700 /var/lib/assbox-acceptance")
    machine.succeed("python3 ${../fixtures/release_cases.py} ${harness}/libexec/assbox-acceptance", timeout=900)
    # Positive real cryptography, including cert identity, issuer, source and
    # signer binding and runner policy, followed by independent negative checks.
    artifact = "${fixtures}/sigstore-js-2.1.0.tgz"
    bundle = "${fixtures}/sigstore-js-2.1.0-bundle.json"
    identity = "https://github.com/sigstore/sigstore-js/.github/workflows/release.yml@refs/heads/main"
    revision = "26d16513386ffaa790b1c32f927544f1322e4194"
    arguments = ["gh", "attestation", "verify", artifact, "--bundle", bundle,
        "--custom-trusted-root", "${fixtures}/trusted_root.json", "--repo", "sigstore/sigstore-js",
        "--digest-alg", "sha512", "--cert-identity", identity,
        "--source-ref", "refs/heads/main", "--source-digest", revision, "--signer-digest", revision,
        "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
        "--deny-self-hosted-runners", "--format", "json"]
    result = json.loads(machine.succeed(shlex.join(arguments)))
    assert result[0]["verificationResult"]["signature"]["certificate"]["sourceRepositoryIdentifier"] == "495574555"
    for option, wrong in [("--cert-identity", identity + "-forged"),
        ("--source-ref", "refs/heads/forged"), ("--source-digest", "a" * 40),
        ("--signer-digest", "b" * 40), ("--cert-oidc-issuer", "https://invalid.example")]:
        invalid = list(arguments)
        invalid[invalid.index(option) + 1] = wrong
        machine.fail(shlex.join(invalid))
    machine.succeed("cp " + artifact + " /var/lib/assbox-acceptance/tampered; printf x >> /var/lib/assbox-acceptance/tampered")
    invalid = list(arguments)
    invalid[3] = "/var/lib/assbox-acceptance/tampered"
    machine.fail(shlex.join(invalid))
    # Test credentials and fixture transports are not shipped in the actual CLI.
    refusal = machine.fail("assbox internal release-baseline r-1 /var/lib/production-release 2>&1")
    assert "release trust is unprovisioned" in refusal
    machine.fail("test -e /var/lib/production-release")
  '';
}
