import json
import re

def reference_expression(paths, shell):
    assert len(paths) > 1 and len(paths) == len(set(paths))
    store_path = r"/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_?=-]+"
    assert all(re.fullmatch(store_path, path) for path in paths)
    assert re.fullmatch(store_path + "/bin/bash", shell)
    quoted_paths = " ".join(json.dumps(path) for path in paths)
    writer = 'for path in $closureRoots; do printf "%s\\n" "$path"; done > "$out"'
    return (
        f"let roots = map builtins.storePath [ {quoted_paths} ]; in builtins.derivation {{ "
        'name = "assbox-audit-reference"; system = "x86_64-linux"; '
        f"builder = builtins.storePath {json.dumps(shell.rsplit('/bin/bash', 1)[0])} + \"/bin/bash\"; "
        f"args = [ \"-c\" {json.dumps(writer)} ]; "
        'closureRoots = builtins.concatStringsSep " " roots; }'
    )
