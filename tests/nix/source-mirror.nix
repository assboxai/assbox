# SPDX-License-Identifier: GPL-3.0-or-later
# Offline HTTPS responses for the exact input sources recorded in flake.lock.
{ pkgs, inputs }:
let
  sources = builtins.genericClosure {
    startSet = map (value: {
      key = toString value.outPath;
      inherit value;
    }) (builtins.attrValues inputs);
    operator =
      item:
      map (value: {
        key = toString value.outPath;
        inherit value;
      }) (builtins.attrValues (item.value.inputs or { }));
  };
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  nodes = builtins.filter (node: node ? locked) (builtins.attrValues lock.nodes);
  records = map (
    node:
    let
      source = builtins.head (builtins.filter (item: item.value.narHash == node.locked.narHash) sources);
    in
    {
      inherit (node.locked)
        owner
        repo
        rev
        narHash
        ;
      path = source.key;
    }
  ) nodes;
in
pkgs.runCommand "assbox-input-source-mirror"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.gnutar
      pkgs.gzip
      pkgs.nix
    ];
    sourceRecords = builtins.toJSON records;
    # Preserve references that JSON/path conversion would otherwise discard.
    sourcePaths = map (item: item.value.outPath) sources;
  }
  ''
    mkdir -p "$out"
    python3 ${../fixtures/source_mirror.py}
  ''
