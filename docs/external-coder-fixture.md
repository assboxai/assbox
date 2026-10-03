# External Coder canary and reconnect fixture

This owner-run fixture prepares separate private canaries on the controller and
guest, emits one reproducible task, and checks initial/disconnected/reconnected
observations. It does not drive a Desktop app, authenticate, connect over SSH,
change networking, stop services or qualify a provider route. Use a disposable
project and scoped credentials when the real integration test is authorized.

Copy [external_coder.py](../tests/fixtures/external_coder.py) to both machines and
use the same fresh UUID. Run preparation and collection as the controller's app
user on macOS and as `agent` inside Assbox, so the task's `Path.home()` selects the
actual execution identity. Python 3 is required on both machines. Start a new UUID
after a failed run; preparation refuses to overwrite an existing fixture.

Create a private `versions.json` on each machine with the same four non-secret
fields: `app`, `agent`, `hypervisor`, and `authMode`. Fill in exact observed
versions and the authentication method, then `chmod 600 versions.json`. These
values are recorded as owner-reported scope, separate from automatic OS/CPU and
process-name observations. Never put credentials in this file.

Prepare each role with its own command:

```sh
python3 external_coder.py prepare --run-id REPLACE_WITH_UUID --role controller \
  --route mac-codex-ssh --tailscale selected-unenrolled --versions versions.json
python3 external_coder.py prepare --run-id REPLACE_WITH_UUID --role guest \
  --route mac-codex-ssh --tailscale selected-unenrolled --versions versions.json
```

The separate `mac-claude-ssh` and `phone-mac-codex-ssh` labels require their own
native client/helper and mobile-coordinator evidence. Repeat the entire run with
`--tailscale deselected` for the no-overlay variant. The flag records the intended
variant; independently verify its actual installed closure, daemon/enrollment
state, SSH exposure and egress. It does not assert those properties itself.

1. Select the prepared guest project in the real external app. Emit the initial
   task with `python3 external_coder.py prompt --run-id REPLACE_WITH_UUID --phase initial`,
   then ask the app to run the printed command once. Record `initial` on both
   machines with `python3 external_coder.py record --run-id REPLACE_WITH_UUID --phase initial`.
2. Disconnect or suspend the guest using the reviewed owner-managed procedure.
   Request the emitted `disconnected` task in the same selected project. It must
   report unavailability. Collect `disconnected` observations from the Mac and
   guest console, without restoring the app's connection. The guest counter must
   remain one and no controller attempt may exist. Retain the actual app outcome.
   If the VM was suspended or powered off, resume it for console collection while
   keeping the app's SSH route disconnected.
3. Reconnect deliberately. Do not replay the uncertain disconnected request.
   Emit and request the distinct `reconnected` task once, then record that phase
   on both machines. The guest counter must now be exactly two, with only
   `initial` and `reconnected` in its history.
4. Copy each private `record.json` from the printed fixture directory to a trusted
   review location and run `python3 external_coder.py verify --controller CONTROLLER_RECORD --guest GUEST_RECORD`.

The payload writes an attempt before reading a role canary. Running it in the
prepared Mac account is detectable even when the guest canary cannot be read.
Duplicate or late execution increments the guest counter and fails the fixture.
Reports bind the run, route, variant, fixture source digest and declared versions;
collection refuses changed canaries, skipped phases or repeated observations.
Process snapshots contain command names and PIDs, without arguments, environment,
tokens or pairing URLs. No automatic cleanup deletes evidence.

A passed canary fixture covers these prepared paths and this task only. It leaves
route qualification `not_established`: independently inspect app-started helper/
app-server lifetime, SSH identities/certificates/channels, host sharing, private
network denial, actual versions/account scope, reboot/suspend behavior and mobile
availability. A cloud task that never reaches either prepared filesystem also
needs its own app evidence. Neither file absence nor process names alone proves
that every capability remained in the guest.
