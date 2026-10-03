# SPDX-License-Identifier: GPL-3.0-or-later
# This output contains only a Rust test executable, never a replacement appliance.
{
  pkgs,
  assbox,
  testCa ? null,
}:
let
  tools = import ../../nix/tool-environment.nix { inherit pkgs; };
  adapters = pkgs.runCommand "assbox-acceptance-transports" { } ''
    mkdir -p "$out/bin"
    for tool in curl gh timedatectl systemd-ask-password; do
      cat > "$out/bin/$tool" <<EOF
    #!${pkgs.runtimeShell}
    exec ${pkgs.python3}/bin/python3 ${../fixtures/release_transport.py} $tool "\$@"
    EOF
      chmod +x "$out/bin/$tool"
    done
  '';
in
pkgs.rustPlatform.buildRustPackage {
  pname = "assbox-acceptance-harness";
  inherit (assbox) version src;
  cargoLock.lockFile = ../../Cargo.lock;
  nativeBuildInputs = [ pkgs.jq ];
  ASSBOX_TOOL_PATH = "${adapters}/bin:${tools.path}";
  ASSBOX_SOURCE_REVISION = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  ASSBOX_REPOSITORY_ID = "123";
  ASSBOX_OWNER_ID = "456";
  ASSBOX_CA_BUNDLE = if testCa == null then "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt" else testCa;
  buildPhase = ''
    runHook preBuild
    cargo test --offline --locked --release -p assbox-engine --lib --no-run --message-format=json > artifacts.json
    jq -r 'select(.profile.test == true and .target.name == "assbox_engine") | .executable // empty' artifacts.json > executable
    test "$(wc -l < executable)" = 1
    runHook postBuild
  '';
  doCheck = false; # The root/effect tests execute in the dependent VM, not a builder.
  installPhase = ''
    mkdir -p "$out/libexec"
    cp "$(cat executable)" "$out/libexec/assbox-acceptance"
  '';
}
