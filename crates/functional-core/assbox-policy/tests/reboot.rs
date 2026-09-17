// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{BootId, PendingReboot};
use assbox_policy::{pending_after_activation, reboot_completed};

const A: &str = "/nix/store/00000000000000000000000000000000-nixos-system-a";
const B: &str = "/nix/store/11111111111111111111111111111111-nixos-system-b";
const C: &str = "/nix/store/22222222222222222222222222222222-nixos-system-c";
fn boot(first: bool) -> BootId {
    BootId::parse(if first {
        "00000000-0000-0000-0000-000000000000"
    } else {
        "11111111-1111-1111-1111-111111111111"
    })
    .unwrap()
}

#[test]
fn stage_switch_and_repeat_cannot_substitute_for_reboot() {
    let pending = pending_after_activation(B, A, A, &boot(true), None, true)
        .unwrap()
        .unwrap();
    for activated in [A, B, C] {
        for target in [A, B, C] {
            for stage in [false, true] {
                let next = pending_after_activation(
                    target,
                    A,
                    activated,
                    &boot(true),
                    Some(&pending),
                    stage,
                )
                .unwrap()
                .unwrap();
                assert_eq!(next.system(), target);
                assert!(!reboot_completed(&next, A, target, &boot(true)));
                // Even switching back to booted A needs the requested reboot.
                assert!(!reboot_completed(&next, target, target, &boot(true)));
                assert!(reboot_completed(&next, target, target, &boot(false)));
            }
        }
    }
    // Ordinary NixOS switch changes userspace, leaving the marker alone.
    assert!(!reboot_completed(&pending, A, B, &boot(true)));
    // A same-generation update after that switch still records a reboot.
    assert!(
        pending_after_activation(B, A, B, &boot(true), None, true)
            .unwrap()
            .is_some()
    );
}

#[test]
fn completion_requires_matching_booted_and_activated_generations() {
    let pending = PendingReboot::new(B, boot(true)).unwrap();
    for booted in [A, B, C] {
        for activated in [A, B, C] {
            assert_eq!(
                reboot_completed(&pending, booted, activated, &boot(false)),
                booted == B && activated == B
            );
        }
    }
    // Live package changes need no new reboot when no intent is pending.
    assert!(
        pending_after_activation(C, A, B, &boot(true), None, false)
            .unwrap()
            .is_none()
    );
    assert!(
        pending_after_activation(B, B, B, &boot(false), Some(&pending), true)
            .unwrap()
            .is_none()
    );
    let legacy = PendingReboot::parse(B).unwrap();
    assert!(!reboot_completed(&legacy, A, B, &boot(false)));
    assert!(reboot_completed(&legacy, B, B, &boot(false)));
}

#[test]
fn reboot_record_round_trip_and_malformed_state() {
    let record = PendingReboot::new(B, boot(true)).unwrap();
    assert_eq!(PendingReboot::parse(&record.encode()).unwrap(), record);
    assert_eq!(PendingReboot::parse(B).unwrap().encode(), B);
    for bad in [
        "",
        "bad",
        "1",
        "00000000-0000-0000-0000-00000000000z",
        "00000000-0000-0000-0000-000000000000\n",
    ] {
        assert!(BootId::parse(bad).is_err());
    }
    for bad in [
        "",
        "relative",
        &format!("{B}\n"),
        &record.encode().replace("-v1", "-v2"),
        &record.encode().replace(boot(true).as_str(), "bad"),
        &format!("{}extra", record.encode()),
        record.encode().trim_end(),
        &record.encode().replace(B, "/nix/store/invalid"),
    ] {
        assert!(PendingReboot::parse(bad).is_err(), "{bad}");
    }
    assert!(PendingReboot::new("bad", boot(true)).is_err());
}
