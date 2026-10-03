#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu
case "${ASSBOX_WAYLAND_OWNER:-}" in ''|*[!0-9]*) exit 1 ;; esac
# A failed startup must not leave a visible but nonfunctional appliance session.
trap 'kill -TERM "$ASSBOX_WAYLAND_OWNER" 2>/dev/null || true' ERR
variables=()
for variable in WAYLAND_DISPLAY DISPLAY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; do
  if [[ -v $variable ]]; then variables+=("$variable"); fi
done
if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
  kill -TERM "$ASSBOX_WAYLAND_OWNER" 2>/dev/null || true
  exit 1
fi
@systemctl@ --user import-environment "${variables[@]}"
@systemctl@ --user start assbox-graphical-session.target
trap - ERR
