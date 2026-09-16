#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Nix substitutes only the executable placeholders; no user text is evaluated.
# The appliance has one graphical session per agent account. Its session target
# pulls in graphical-session.target as a dependency (never a manual start).
set -eu
child=
# Invoked by the EXIT trap; cleanup itself clears that trap before exiting.
# shellcheck disable=SC2329
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [[ -n "$child" ]]; then
    kill -TERM "$child" 2>/dev/null || true
  fi
  if ! @systemctl@ --user stop assbox-graphical-session.target graphical-session.target; then
    echo 'Assbox could not stop the graphical session target.' >&2
    status=1
  fi
  if ! @systemctl@ --user unset-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; then
    echo 'Assbox could not clear the graphical session environment.' >&2
    status=1
  fi
  exit "$status"
}
trap 'cleanup' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

export XDG_SESSION_TYPE=x11
export XDG_CURRENT_DESKTOP=openbox:X-NIXOS-SYSTEMD-AWARE
# Stop stale services before replacing credentials/display variables. This also
# handles the next login after an uncatchable SIGKILL or X-server crash.
@systemctl@ --user stop assbox-graphical-session.target graphical-session.target
@systemctl@ --user unset-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
variables=()
for variable in DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; do
  if [[ -v $variable ]]; then
    variables+=("$variable")
  fi
done
@systemctl@ --user import-environment "${variables[@]}"
# DPMS may be unavailable on virtual/older hardware. Failure is not a login error.
@xset@ s off || true
@xset@ +dpms || true
@xset@ dpms 0 0 600 || true
@systemctl@ --user start assbox-graphical-session.target
@openbox@ &
child=$!
status=0
wait "$child" || status=$?
child=
exit "$status"
