# SPDX-License-Identifier: GPL-3.0-or-later
# A runtime artifact, not an export of the host's guest build closure.
{
  pkgs,
  guest,
  scratchGiB,
  maxArtifactMiB,
}:
let
  system = guest.config.system.build.toplevel;
  buildId = builtins.hashString "sha256" (toString system);
  builtDisk = import (pkgs.path + "/nixos/lib/make-disk-image.nix") {
    inherit pkgs;
    inherit (pkgs) lib;
    config = guest.config;
    name = "assbox-worker-disk";
    baseName = "assbox-worker";
    format = "qcow2";
    partitionTableType = "none";
    installBootLoader = false;
    touchEFIVars = false;
    copyChannel = false;
    diskSize = "auto";
    additionalSpace = "${toString scratchGiB}G";
    contents = [
      {
        source = pkgs.writeText "assbox-worker-build-id" "${buildId}\n";
        target = "/assbox-worker-build-id";
        mode = "0444";
        user = "root";
        group = "root";
      }
    ];
  };
  # Pinned vmTools already invokes QEMU with accel=kvm:tcg. Its unconditional
  # scheduler feature would nevertheless exclude ARM builders without /dev/kvm.
  # This changes image construction only; the production worker remains KVM-only.
  disk =
    if pkgs.stdenv.hostPlatform.isAarch64 then
      pkgs.lib.overrideDerivation builtDisk (old: {
        requiredSystemFeatures = builtins.filter (feature: feature != "kvm") (
          old.requiredSystemFeatures or [ ]
        );
      })
    else
      builtDisk;
  commandLine = pkgs.writeText "assbox-worker-command-line" (
    pkgs.lib.concatStringsSep " " (
      [
        "root=/dev/vda"
        "rw"
        "init=${system}/init"
      ]
      ++ guest.config.boot.kernelParams
    )
  );
in
pkgs.runCommand "assbox-worker-artifact"
  {
    nativeBuildInputs = [
      pkgs.qemu_kvm
      pkgs.python3
    ];
    __structuredAttrs = true;
    # All store paths in this output refer to the store INSIDE the disk/initrd.
    # There must be no host executable, host symlink or external backing image in it.
    unsafeDiscardReferences.out = true;
    outputChecks.out = {
      allowedReferences = [ ];
      maxSize = maxArtifactMiB * 1024 * 1024;
    };
    # Audit/build output only: never referenced by a host generation or runtime JSON.
    passthru = {
      inherit buildId;
      imageBuildRequiredFeatures = disk.requiredSystemFeatures or [ ];
      auditClosure = system;
      # Evaluation-only policy evidence. This is not a runtime root or export of
      # guest executables into the host system.
      guestPolicy = {
        sshdConfig = guest.config.environment.etc."ssh/sshd_config".source;
        assertions = guest.config.assertions;
        mutableUsers = guest.config.users.mutableUsers;
        allowNoPasswordLogin = guest.config.users.allowNoPasswordLogin;
        rootPassword = guest.config.users.users.root.hashedPassword;
        agentPassword = guest.config.users.users.agent.hashedPassword;
        healthShell = guest.config.users.users.assbox-health.shell;
        healthHome = guest.config.users.users.assbox-health.home;
        passwordAuthentication = guest.config.services.openssh.settings.PasswordAuthentication;
        permitRootLogin = guest.config.services.openssh.settings.PermitRootLogin;
      };
    };
  }
  ''
      mkdir -p "$out"
      qemu-img convert -O qcow2 -c ${disk}/assbox-worker.qcow2 "$out/system.qcow2"
      cp -L ${guest.config.system.build.kernel}/${guest.config.system.boot.loader.kernelFile} "$out/kernel"
      cp -L ${guest.config.system.build.initialRamdisk}/initrd "$out/initrd"
      cp ${commandLine} "$out/cmdline"
      qemu-img info --output=json "$out/system.qcow2" > disk-info.json
      python3 - "$out" "${buildId}" <<'PYCODE'
    import hashlib, json, pathlib, sys
    root = pathlib.Path(sys.argv[1])
    info = json.loads(pathlib.Path("disk-info.json").read_text())
    assert info["format"] == "qcow2" and not info.get("backing-filename")
    files = {}
    for name in ("system.qcow2", "kernel", "initrd", "cmdline"):
        p = root / name
        assert p.is_file() and not p.is_symlink()
        with p.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files[name] = {"bytes": p.stat().st_size, "sha256": digest}
    (root / "manifest.json").write_text(json.dumps({
        "schema": 1, "buildId": sys.argv[2],
        "rootVirtualBytes": info["virtual-size"], "files": files,
    }, sort_keys=True) + "\n")
    PYCODE
  ''
