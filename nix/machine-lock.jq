# SPDX-License-Identifier: GPL-3.0-or-later
# Rebase the authenticated release's actual Nix graph. No resolution occurs here.
. as $metadata |
.locks as $lock |
if $lock.version != 7 or ($lock.nodes | type) != "object"
   or ($lock.nodes[$lock.root].inputs.nixpkgs == null)
   or ($lock.nodes | has("_assbox_machine"))
   or any($lock.nodes[]; has("parent") or (.locked.type == "path"))
   or $metadata.locked.type != "tarball"
   or $metadata.locked.url != $url or $metadata.locked.narHash != $hash
   or $metadata.original.type != "tarball" or $metadata.original.url != $url
   or $metadata.original.narHash != $hash
then error("unsupported or unauthenticated release input graph") else . end |
($lock.nodes | with_entries(
  if .value.inputs then
    .value.inputs |= with_entries(
      if (.value | type) == "array" then .value = ["assbox"] + .value else . end
    )
  else . end
)) as $nodes |
# Metadata exposes the fetcher's internal final marker. Nix lock files imply
# final inputs and reject that marker when reading an otherwise valid graph.
($nodes | .[$lock.root] += {locked: ($metadata.locked | del(.__final)), original: $metadata.original}) as $bound |
{version: 7, root: "_assbox_machine", nodes: ($bound + {
  "_assbox_machine": {inputs: {assbox: $lock.root, nixpkgs: ["assbox", "nixpkgs"]}}
})}
