# SPDX-License-Identifier: GPL-3.0-or-later
# Rebase the authenticated release's actual Nix graph. No resolution occurs here.
. as $metadata |
.locks as $lock |
if $lock.version != 7 or ($lock.nodes | type) != "object"
   or ($lock.nodes[$lock.root].inputs.nixpkgs == null)
   or ($lock.nodes | has("_assbox_machine"))
   or any($lock.nodes[]; has("parent") or (.locked.type == "path"))
   or $metadata.path != $path
   or $metadata.locked.type != "path"
   or $metadata.locked.path != $path or $metadata.locked.narHash != $hash
   or $metadata.original.type != "path" or $metadata.original.path != $path
then error("unsupported or unauthenticated release input graph") else . end |
($lock.nodes | with_entries(
  if .value.inputs then
    .value.inputs |= with_entries(
      if (.value | type) == "array" then .value = ["assbox"] + .value else . end
    )
  else . end
)) as $nodes |
# Metadata was evaluated from the already authenticated local store object.
# Persist the immutable release identity from the signed manifest rather than
# its transaction-local path reference.
({type: "tarball", url: $url, narHash: $hash}) as $release |
($nodes | .[$lock.root] += {locked: $release, original: $release}) as $bound |
{version: 7, root: "_assbox_machine", nodes: ($bound + {
  "_assbox_machine": {inputs: {assbox: $lock.root, nixpkgs: ["assbox", "nixpkgs"]}}
})}
