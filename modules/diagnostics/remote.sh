#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Nix substitutes reviewed unit names, paths and literal argument lists only.
set -euo pipefail
test "$(@id@ -un)" = agent
export HOME=/home/agent
: "${XDG_RUNTIME_DIR:?Run through assbox component diagnose}"
umask 077
exec 9>"$XDG_RUNTIME_DIR/@unit@.lock"
@flock@ -n 9 || { echo 'Onboarding or diagnostics already owns this service.' >&2; exit 1; }
directory="$HOME/.local/state/assbox/diagnostics"
test ! -L "$directory"
@mkdir@ -p "$directory"
@chmod@ 700 "$directory"
log=$(@mktemp@ "$directory/@unit@.XXXXXX.log")
state=$(@systemctl@ --user show --property=ActiveState --value @unit@.service)
restore=false
case "$state" in active|activating|reloading) restore=true ;; esac
session_args=()
if @graphical@; then
  @systemctl@ --user is-active --quiet graphical-session.target
  session_args+=(--property=PartOf=graphical-session.target)
fi
# Invoked by EXIT; cleanup itself removes the trap before exiting.
# shellcheck disable=SC2329
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  # --collect may already have removed the transient unit.
  if ! @systemctl@ --user stop @unit@-diagnostic.service >/dev/null 2>&1; then
    if @systemctl@ --user is-active --quiet @unit@-diagnostic.service; then status=1; fi
  fi
  if "$restore"; then
    if ! @graphical@ || @systemctl@ --user is-active --quiet graphical-session.target; then
      @systemctl@ --user start @unit@.service || status=1
    fi
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
@systemctl@ --user stop @unit@.service
echo 'Capturing up to five minutes and 1 MiB of private provider output. Treat the file as credentials; do not share it unredacted.'
echo "Private diagnostic file: $log"
set +e
@systemd-run@ --user --quiet --collect --wait --pipe --service-type=exec \
  --unit=@unit@-diagnostic.service \
  --property=RuntimeMaxSec=300 --property=TimeoutStopSec=10 \
  --property=KillMode=control-group --property=UMask=0077 \
  --property=NoNewPrivileges=true --property=ConditionUser=agent \
  --property=WorkingDirectory=@workdir@ \
  --property=Environment=PATH=/run/current-system/sw/bin:/run/wrappers/bin \
  "${session_args[@]}" -- @command@ </dev/null 2>&1 | @head@ -c 1048576 > "$log"
results=("${PIPESTATUS[@]}")
set -e
test "${results[1]}" = 0
echo "Diagnostic process exit status: ${results[0]} (may reflect timeout or the output cap)."
echo 'The original service is restored only if it was running or retrying before capture.'
