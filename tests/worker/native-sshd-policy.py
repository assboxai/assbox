#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run only inside the native test VM with the real guest-generated sshd config."""
import pathlib
import subprocess
import sys


def effective(sshd: str, config: str, user: str) -> dict[str, str]:
    result = subprocess.run(
        [sshd, "-T", "-f", config, "-C",
         f"user={user},host=assbox-worker,addr=10.77.0.1,laddr=10.77.0.2,lport=22"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        key = key.lower()
        fields[key] = (fields.get(key, "") + " " + value).strip()
    return fields


def main() -> None:
    sshd, config = sys.argv[1:]
    if not pathlib.Path(config).is_file():
        raise SystemExit("guest-generated SSH configuration is missing")
    health = effective(sshd, config, "assbox-health")
    agent = effective(sshd, config, "agent")
    for policy in (health, agent):
        for name in ("passwordauthentication", "kbdinteractiveauthentication", "permitrootlogin",
                     "allowagentforwarding", "x11forwarding", "permituserrc", "permituserenvironment"):
            assert policy[name] == "no", (name, policy[name])
        assert set(policy["allowusers"].split()) == {"agent", "assbox-health"}
        assert policy["authorizedkeysfile"] == "/run/assbox-seed/%u.pub"
    assert health["forcecommand"].startswith("/nix/store/")
    assert health["forcecommand"].endswith("/bin/assbox-health-shell")
    assert health["disableforwarding"] == "yes"
    assert health["permittty"] == "no"
    assert agent["forcecommand"] == "none"
    assert agent["disableforwarding"] == "no"
    assert agent["permittty"] == "yes"
    assert agent["allowtcpforwarding"] == "local"
    assert set(agent["permitopen"].split()) == {"localhost:*", "127.0.0.1:*", "[::1]:*"}
    print("Effective guest health/workload SSH policy verified with sshd -T.")


if __name__ == "__main__":
    main()
