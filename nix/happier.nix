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
  sourceRoot = ".";
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
    # Upstream archives carry a complete runtime. Refuse an unexpected layout.
    binary=$(find "$out/lib/happier" -type f -name happier -perm /111 -print -quit)
    test -n "$binary"
    makeWrapper "$binary" "$out/bin/happier" \
      --set HAPPIER_NO_BROWSER_OPEN 1 \
      --set HAPPIER_ENCRYPTION_REQUIREMENT require_e2ee \
      --set SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt \
      --prefix PATH : ${lib.makeBinPath [ nodejs ]}
    runHook postInstall
  '';
  meta = {
    description = "Pinned Happier CLI and daemon runtime";
    homepage = "https://happier.dev";
    license = lib.licenses.mit;
    platforms = builtins.attrNames source.systems;
    mainProgram = "happier";
  };
}
