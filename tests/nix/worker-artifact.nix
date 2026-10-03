# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, module }:
let
  system = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      module
      ./fixture.nix
      {
        assbox.updates.enable = false;
        assbox.worker = {
          stateGiB = 8;
          enable = true;
          components = [ "vim" ];
          egress = "offline";
          nameservers = [ ];
        };
      }
    ];
  };
  artifact = system.config.system.build.assboxWorkerImage;
  closure = pkgs.closureInfo { rootPaths = [ artifact ]; };
in
assert
  !pkgs.stdenv.hostPlatform.isAarch64 || !(builtins.elem "kvm" artifact.imageBuildRequiredFeatures);
pkgs.runCommand "assbox-worker-artifact-check"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.qemu_kvm
    ];
  }
  ''
    # A retained runtime artifact must not also retain its guest build closure.
    test "$(wc -l < ${closure}/store-paths)" -eq 1
    test "$(cat ${closure}/store-paths)" = "${artifact}"
    python3 ${../../scripts/worker}/check-artifact.py ${artifact}
    qemu-img info --output=json ${artifact}/system.qcow2 > image.json
    python3 -c 'import json; d=json.load(open("image.json")); assert d["format"] == "qcow2"; assert not d.get("backing-filename")'
    touch "$out"
  ''
