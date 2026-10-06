# SPDX-License-Identifier: GPL-3.0-or-later
# The real release fixture adds release-context.json to the complete core source.
# Seed that exact package, including its compiler revision, before offline runtime
# builds. Keeping only the context-free package would leave a different CLI to
# compile inside the installer guest. No source files are excluded here.
{
  pkgs,
  assbox,
  revision ? "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
}:
let
  context = {
    coreCommit = revision;
    coreVersion = assbox.version;
    lockSha256 = builtins.hashString "sha256" (builtins.readFile "${assbox.src}/flake.lock");
  };
  source =
    pkgs.runCommand "assbox-disposable-release-source"
      {
        releaseContext = builtins.toJSON context + "\n";
        passAsFile = [ "releaseContext" ];
      }
      ''
        mkdir "$out"
        cp -a ${assbox.src}/. "$out/"
        chmod u+w "$out"
        cp "$releaseContextPath" "$out/release-context.json"
        chmod 0644 "$out/release-context.json"
      '';
in
assbox.overrideAttrs (_: {
  # Normalize the path name exactly as the root package's clean source does.
  src = builtins.path {
    path = source;
    name = "source";
  };
  ASSBOX_SOURCE_REVISION = revision;
})
