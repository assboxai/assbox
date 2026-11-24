# SPDX-License-Identifier: GPL-3.0-or-later
# Build-only tool from the verified upstream release.
pkgs:
let
  inherit (pkgs) lib;
  assets = {
    x86_64-linux = {
      platform = "x64";
      hash = "sha256-tRXinyrBrcD75jFzQUpmgoJ7r/JPF+etNHaCG97yNqw=";
    };
    aarch64-linux = {
      platform = "arm64";
      hash = "sha256-3QP3YWYl/48T2VL2QfCGSiMA1z0KdRpoJzdhW9n5p6I=";
    };
  };
  asset = assets.${pkgs.stdenv.hostPlatform.system};
in
pkgs.stdenvNoCC.mkDerivation (final: {
  pname = "pnpm";
  version = "12.23.0";
  src = pkgs.fetchurl {
    url = "https://github.com/pnpm/pnpm/releases/download/v${final.version}/pnpm-linux-${asset.platform}.tar.gz";
    inherit (asset) hash;
  };
  nativeBuildInputs = [ pkgs.autoPatchelfHook ];
  buildInputs = [ pkgs.stdenv.cc.cc.lib ];
  unpackPhase = ''
    runHook preUnpack
    tar -xzf "$src"
    runHook postUnpack
  '';
  installPhase = ''
    runHook preInstall
    tool="$out/libexec/pnpm"
    install -Dm755 pnpm "$tool/pnpm"
    cp -r dist "$tool/"
    install -d "$out/bin"
    ln -s ../libexec/pnpm/pnpm "$out/bin/pnpm"
    runHook postInstall
  '';
  dontStrip = true;
  passthru = {
    inherit (pkgs.pnpm_12) nodejs-slim;
    majorVersion = "12";
  };
  meta = {
    license = lib.licenses.mit;
    mainProgram = "pnpm";
    platforms = builtins.attrNames assets;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
