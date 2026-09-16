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
      inherit (node.locked) owner repo rev;
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
    ];
    sourceRecords = builtins.toJSON records;
    # Preserve references that JSON/path conversion would otherwise discard.
    sourcePaths = map (item: item.value.outPath) sources;
  }
  ''
    mkdir -p "$out"
    python3 - <<'PY'
    import hashlib, json, os, pathlib, subprocess
    out = pathlib.Path(os.environ['out'])
    routes = {}
    for source in json.loads(os.environ['sourceRecords']):
        path = pathlib.Path(source['path'])
        filename = hashlib.sha256(str(path).encode()).hexdigest() + '.tar.gz'
        if not (out / filename).exists():
            subprocess.run(['tar', '-czf', str(out / filename), '--transform=s,^,source/,', '-C', str(path), '.'], check=True)
        routes['/repos/{owner}/{repo}/tarball/{rev}'.format(**source)] = filename
        routes['/{owner}/{repo}/archive/{rev}.tar.gz'.format(**source)] = filename
    (out / 'routes.json').write_text(json.dumps(routes))
    PY
  ''
