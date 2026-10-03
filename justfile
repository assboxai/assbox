set positional-arguments

default:
    @just --list

# Stable consumer bootstrap. Runtime behavior belongs to the pinned Git revision.
[group("Chainman")]
[positional-arguments]
chainman +args:
    #!/bin/sh
    set -eu
    mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
    XDG_CACHE_HOME=$(CDPATH= cd -P -- "${XDG_CACHE_HOME:-$HOME/.cache}" && pwd)
    export XDG_CACHE_HOME
    export CHAINMAN_MODE=${CHAINMAN_MODE:-host-nix}
    IFS= read -r revision < chainman.lock
    case "$revision" in ''|*[!0-9a-f]*) echo 'chainman.lock requires a full lowercase Git SHA' >&2; exit 2 ;; esac
    test "${#revision}" -eq 40 && test "$(wc -c < chainman.lock)" -eq 41
    cache=${XDG_CACHE_HOME:-$HOME/.cache}/chainman/git/github.com-chainmandev-chainman/$revision.git
    g() (
        unset $(GIT_CONFIG_PARAMETERS='' GIT_CONFIG_COUNT=0 git rev-parse --local-env-vars)
        GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_COUNT=0 GIT_TERMINAL_PROMPT=0 git --no-replace-objects -c core.hooksPath=/dev/null -c core.fsmonitor=false "$@"
    )
    if test ! -e "$cache"; then
        mkdir -p "${cache%/*}"
        temporary=$(mktemp -d "$cache.XXXXXX")
        g init --bare --quiet --template= "$temporary"
        ln -sn "$temporary" "$cache" 2>/dev/null || rm -rf "$temporary"
    fi
    if ! g --git-dir="$cache" cat-file -e "$revision" 2>/dev/null; then
        g --git-dir="$cache" -c gc.auto=0 fetch --no-auto-maintenance --no-write-fetch-head https://github.com/chainmandev/chainman.git "$revision"
    fi
    g --git-dir="$cache" fsck --full --strict --no-reflogs --no-dangling
    test "$(g --git-dir="$cache" cat-file -t "$revision")" = commit
    entry=$(g --git-dir="$cache" cat-file blob "$revision:bootstrap/git-entry.sh")
    exec sh -c "$entry" chainman "$PWD" "$cache" "$revision" "$@"

[positional-arguments]
build *args:
    #!/bin/sh
    exec just chainman run build -- "$@"

[positional-arguments]
test *args:
    #!/bin/sh
    exec just chainman run test -- "$@"

[positional-arguments]
generate *args:
    #!/bin/sh
    exec just chainman run generate -- "$@"

[positional-arguments]
format-write *args:
    #!/bin/sh
    exec just chainman run format-write -- "$@"

[positional-arguments]
format-check *args:
    #!/bin/sh
    exec just chainman run format-check -- "$@"

[positional-arguments]
verify-lite *args:
    #!/bin/sh
    exec just chainman run verify-lite -- "$@"

[positional-arguments]
verify-prepare *args:
    #!/bin/sh
    exec just chainman run verify-prepare -- "$@"

[positional-arguments]
verify *args:
    #!/bin/sh
    exec just chainman run verify -- "$@"

[positional-arguments]
verify-production *args:
    #!/bin/sh
    exec just chainman run verify-production -- "$@"

[positional-arguments]
verify-production-candidate *args:
    #!/bin/sh
    exec just chainman run verify-production-candidate -- "$@"

[positional-arguments]
verify-canonical *args:
    #!/bin/sh
    exec just chainman run verify-canonical -- "$@"

[positional-arguments]
clean *args:
    #!/bin/sh
    exec just chainman run clean -- "$@"

[positional-arguments]
maintenance-inspect *args:
    #!/bin/sh
    exec just chainman run maintenance-inspect -- "$@"

[positional-arguments]
deps-propose-rust *args:
    #!/bin/sh
    exec just chainman recipe deps-update targets=rust --skip-chainman mode=dry-run --json "$@"

[positional-arguments]
deps-propose-actions *args:
    #!/bin/sh
    exec just chainman recipe deps-update targets=actions --skip-chainman mode=dry-run --json "$@"

[positional-arguments]
verify-static *args:
    #!/bin/sh
    exec just chainman run verify-static -- "$@"

[positional-arguments]
verify-rust *args:
    #!/bin/sh
    exec just chainman run verify-rust -- "$@"

[positional-arguments]
verify-mutations *args:
    #!/bin/sh
    exec just chainman run verify-mutations -- "$@"

[positional-arguments]
verify-nix *args:
    #!/bin/sh
    exec just chainman run verify-nix -- "$@"

[positional-arguments]
vm-install-boot *args:
    #!/bin/sh
    exec just chainman run vm-install-boot -- "$@"

[positional-arguments]
vm-activation-recovery *args:
    #!/bin/sh
    exec just chainman run vm-activation-recovery -- "$@"

[positional-arguments]
vm-authenticated-release *args:
    #!/bin/sh
    exec just chainman run vm-authenticated-release -- "$@"

[positional-arguments]
repair-init *args:
    #!/bin/sh
    exec just chainman run repair-init -- "$@"

[positional-arguments]
repair-preflight *args:
    #!/bin/sh
    exec just chainman run repair-preflight -- "$@"

[positional-arguments]
repair-build *args:
    #!/bin/sh
    exec just chainman run repair-build -- "$@"

[positional-arguments]
repair-once *args:
    #!/bin/sh
    exec just chainman run repair-once -- "$@"

[positional-arguments]
repair-status *args:
    #!/bin/sh
    exec just chainman run repair-status -- "$@"

[positional-arguments]
repair-finalize *args:
    #!/bin/sh
    exec just chainman run repair-finalize -- "$@"

[positional-arguments]
setup *args:
    #!/bin/sh
    exec just chainman setup "$@"

[positional-arguments]
shell *args:
    #!/bin/sh
    exec just chainman shell "$@"

[positional-arguments]
explain *args:
    #!/bin/sh
    exec just chainman explain "$@"

[positional-arguments]
doctor *args:
    #!/bin/sh
    exec just chainman recipe doctor "$@"

[positional-arguments]
format-staged *args:
    #!/bin/sh
    exec just chainman format-staged "$@"

[positional-arguments]
hooks *args:
    #!/bin/sh
    exec just chainman hooks "$@"

[positional-arguments]
deps-check *args:
    #!/bin/sh
    exec just chainman deps-check "$@"

[positional-arguments]
deps-coverage *args:
    #!/bin/sh
    exec just chainman deps-coverage "$@"

[positional-arguments]
deps-policy-report *args:
    #!/bin/sh
    exec just chainman deps-policy-report "$@"

[positional-arguments]
deps-update *args:
    #!/bin/sh
    exec just chainman recipe deps-update "$@"

[positional-arguments]
chainman-update *args:
    #!/bin/sh
    exec just chainman recipe chainman-update "$@"
