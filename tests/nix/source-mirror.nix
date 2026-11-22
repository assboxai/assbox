# SPDX-License-Identifier: GPL-3.0-or-later
# Offline HTTPS responses for the exact input sources recorded in flake.lock.
{ pkgs, inputs }:
let
  inherit (pkgs) lib;
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  # The same source tree can appear in several lock nodes with different inputs.
  # Follow node IDs so a shared source path cannot hide one node's dependencies.
  closure = builtins.genericClosure {
    startSet = [
      {
        key = lock.root;
        value = { inherit inputs; };
      }
    ];
    operator =
      item:
      # Follow references alias nodes reached through their direct inputs.
      lib.mapAttrsToList (name: key: {
        inherit key;
        value = item.value.inputs.${name};
      }) (lib.filterAttrs (_: builtins.isString) (lock.nodes.${item.key}.inputs or { }));
  };
  sources = builtins.listToAttrs (
    map (item: {
      name = item.key;
      inherit (item) value;
    }) closure
  );
  records = lib.mapAttrsToList (
    name: node:
    let
      source = sources.${name};
    in
    assert lib.assertMsg (
      source.narHash == node.locked.narHash
    ) "Assbox source mirror: lock hash does not match input ${name}";
    {
      inherit (node.locked)
        owner
        repo
        rev
        narHash
        lastModified
        ;
      path = source.outPath;
    }
  ) (lib.filterAttrs (_: node: node ? locked) lock.nodes);
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
    # Keep the matched source trees as explicit build dependencies.
    sourcePaths = map (record: record.path) records;
  }
  ''
    mkdir -p "$out"
    python3 ${../fixtures/source_mirror.py}
  ''
