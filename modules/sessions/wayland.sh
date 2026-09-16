#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# The compositor establishes WAYLAND_DISPLAY in its autostart child. The outer
# session owns cleanup even when the compositor or its startup hook fails.
set -eu
child=
# Invoked by the EXIT trap; cleanup itself clears that trap before exiting.
# shellcheck disable=SC2329
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [[ -n "$child" ]]; then kill -TERM "$child" 2>/dev/null || true; fi
  if ! @systemctl@ --user stop assbox-graphical-session.target graphical-session.target; then status=1; fi
  if ! @systemctl@ --user unset-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; then status=1; fi
  exit "$status"
}
trap 'cleanup' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
@systemctl@ --user stop assbox-graphical-session.target graphical-session.target
@systemctl@ --user unset-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
unset DISPLAY XAUTHORITY WAYLAND_DISPLAY
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=labwc
export ASSBOX_WAYLAND_OWNER=$$
@labwc@ &
child=$!
status=0
wait "$child" || status=$?
child=
exit "$status"
