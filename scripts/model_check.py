#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded requirements model; does not execute Rust or prove Linux durability."""
from dataclasses import dataclass, replace
from itertools import product


@dataclass(frozen=True)
class State:
    active: bool = False
    complete: bool = False
    phase: str | None = None
    source: str = "old"
    profile: str = "old"
    activation_checked: bool = False


def run() -> tuple[int, int]:
    # Ordered fsync and atomic same-filesystem rename are assumptions, not modeled
    # implementations. Include cuts before the very first active journal exists,
    # and after retirement while deletion may be only partially complete.
    state = State()
    prefixes = [state]
    for change in [dict(), dict(phase="prepared"), dict(), dict(), dict(complete=True),
                   dict(active=True), dict(phase="built"), dict(phase="published"),
                   dict(source="new"), dict(phase="activating"), dict(profile="new"),
                   dict(activation_checked=True), dict(phase="committed"),
                   dict(active=False), dict(complete=False), dict(phase=None)]:
        state = replace(state, **change)
        prefixes.append(state)
    count = 0
    for cut, rebooted in product(prefixes, [False, True]):
        count += 1
        if cut.active:
            assert cut.complete and cut.phase is not None
            if cut.phase in {"prepared", "built"}:
                assert cut.source == "old" and cut.profile == "old"
            elif cut.phase == "published":
                assert cut.profile == "old"
            elif cut.phase == "activating":
                # A selected profile is not evidence of successful activation.
                assert cut.source == "new"
            elif cut.phase == "committed":
                assert cut.source == cut.profile == "new" and cut.activation_checked
            else:
                raise AssertionError(cut)
        elif cut.source == "new":
            assert cut.activation_checked and cut.profile == "new"
        else:
            assert cut.profile == "old"
        assert isinstance(rebooted, bool)

    cases = 0
    for changed, staged, presence, ac, battery, threshold in product(
            [False, True], [False, True], ["present", "absent", "unknown"],
            [None, False, True], [None, 0, 19, 20, 100, 101], [0, 20, 100]):
        cases += 1
        enough_battery = presence != "absent" and battery is not None and threshold <= battery <= 100
        desktop = presence == "absent" and ac is not False and battery is None
        reboot = changed and staged and (ac is True or enough_battery or desktop)
        if reboot:
            assert changed and staged
            if ac is not True and not desktop:
                assert battery is not None and threshold <= battery <= 100
        if presence != "absent" and ac is not True and (battery is None or battery < threshold or battery > 100):
            assert not reboot
    return count, cases


if __name__ == "__main__":
    recoveries, maintenance = run()
    print(f"Bounded specification passed: {recoveries} interruption observations; {maintenance} maintenance combinations.")
    print("This is not execution, verification or coverage measurement of the Rust implementation.")
