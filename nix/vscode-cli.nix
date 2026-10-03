# SPDX-License-Identifier: GPL-3.0-or-later
{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
  openssl,
}:
let
  pin = builtins.fromJSON (builtins.readFile ./vscode-cli-source.json);
in
stdenv.mkDerivation {
  pname = "assbox-vscode-cli";
  inherit (pin) version;
  src = fetchurl pin.sources.${stdenv.hostPlatform.system};
  sourceRoot = ".";
  nativeBuildInputs = [ autoPatchelfHook ];
  buildInputs = [
    stdenv.cc.cc.lib
    openssl
  ];
  # The immutable download URL ends in /stable, so stdenv cannot infer the
  # archive format from its name. The pinned upstream artifact is a tar.gz.
  unpackPhase = ''
    runHook preUnpack
    tar -xzf "$src"
    runHook postUnpack
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 code "$out/bin/assbox-vscode"
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = "$out/bin/assbox-vscode --version";
  meta = {
    description = "Standalone VS Code remote CLI, without the desktop";
    homepage = "https://code.visualstudio.com/docs/remote/tunnels";
    license = lib.licenses.unfree;
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
    mainProgram = "assbox-vscode";
  };
}
