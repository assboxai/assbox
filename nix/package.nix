# SPDX-License-Identifier: GPL-3.0-or-later
{
  lib,
  pkgs,
  rustPlatform,
  sourceRevision ? "",
  releasePolicy,
}:
let
  tools = import ./tool-environment.nix { inherit pkgs; };
in
rustPlatform.buildRustPackage {
  pname = "assbox";
  version = (builtins.fromTOML (builtins.readFile ../Cargo.toml)).workspace.package.version;
  src = lib.cleanSourceWith {
    src = ../.;
    filter =
      path: type:
      lib.cleanSourceFilter path type
      && !(builtins.elem (baseNameOf path) [
        "target"
        "reports"
        "result"
        "__pycache__"
        ".chainman"
        ".cache"
      ]);
  };
  cargoLock.lockFile = ../Cargo.lock;
  cargoBuildFlags = [ "--workspace" ];
  cargoTestFlags = [ "--workspace" ];
  # PTY tests exercise the real password helper; libnm reads rendered Wi-Fi files.
  nativeCheckInputs = [ (pkgs.python3.withPackages (ps: [ ps.pygobject3 ])) ];
  GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [
    pkgs.networkmanager
    pkgs.glib
  ];
  ASSBOX_TOOL_PATH = tools.path;
  ASSBOX_NIX_LIB = "${pkgs.path}/lib";
  ASSBOX_SOURCE_REVISION = sourceRevision;
  ASSBOX_REPOSITORY_ID = toString releasePolicy.repositoryId;
  ASSBOX_OWNER_ID = toString releasePolicy.ownerId;
  ASSBOX_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  doCheck = true;
  meta = {
    description = "NixOS appliance installation and administration";
    homepage = "https://assbox.com";
    license = lib.licenses.gpl3Plus;
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
    mainProgram = "assbox";
  };
}
