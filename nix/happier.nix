# SPDX-License-Identifier: GPL-3.0-or-later
{
  lib,
  stdenv,
  stdenvNoCC,
  fetchurl,
  autoPatchelfHook,
  makeWrapper,
  zlib,
  openssl,
  libgcc,
  nodejs,
  cacert,
}:
let
  source = builtins.fromJSON (builtins.readFile ./happier-source.json);
  artifact =
    source.systems.${stdenv.hostPlatform.system}
      or (throw "Happier has no pinned artifact for this architecture");
in
stdenvNoCC.mkDerivation {
  pname = "happier";
  inherit (source) version;
  src = fetchurl { inherit (artifact) url hash; };
  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = [
    stdenv.cc.cc.lib
    zlib
    openssl
    libgcc
  ];
  sourceRoot = "happier-v${source.version}-linux-${
    if stdenv.hostPlatform.isAarch64 then "arm64" else "x64"
  }";
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib/happier" "$out/bin"
    cp -a . "$out/lib/happier/"
    # Assbox's Node runtime uses glibc. ARM archives also bundle alternate
    # musl native modules, which cannot load into that interpreter and make
    # autoPatchelf require an unrelated libc. Keep their glibc counterparts.
    find "$out/lib/happier" -type f -name '*.musl.node' -delete
    find "$out/lib/happier" -type d -name '*-linuxmusl-*' -prune \
      -exec rm -rf -- {} +
    # The executable shipped as "happier" is the Bun runtime. Launch the
    # declared JavaScript entrypoint with our pinned Node instead of presenting
    # the runtime's version and command parser as the application.
    entrypoint="$out/lib/happier/package-dist/index.mjs"
    test -f "$entrypoint"
    rm "$out/lib/happier/happier"
    makeWrapper ${nodejs}/bin/node "$out/bin/happier" \
      --add-flags "$entrypoint" \
      --set HAPPIER_NO_BROWSER_OPEN 1 \
      --set HAPPIER_ENCRYPTION_REQUIREMENT require_e2ee \
      --set SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt \
      --prefix PATH : ${lib.makeBinPath [ nodejs ]}
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/happier-install-check-home"
    export HAPPIER_HOME_DIR="$HOME/.happier"
    mkdir -p "$HOME"
    "$out/bin/happier" --version | grep -Fx ${lib.escapeShellArg source.version}
    runHook postInstallCheck
  '';
  meta = {
    description = "Pinned Happier CLI and daemon runtime";
    homepage = "https://happier.dev";
    license = lib.licenses.mit;
    platforms = builtins.attrNames source.systems;
    mainProgram = "happier";
  };
}
