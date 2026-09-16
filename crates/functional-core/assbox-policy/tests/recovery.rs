// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_policy::recovery_pending;

const OLD: &str = "/nix/store/00000000000000000000000000000000-nixos-system-old";
const NEW: &str = "/nix/store/11111111111111111111111111111111-nixos-system-new";
const RUNNING: &str = "/nix/store/22222222222222222222222222222222-nixos-system-running";

#[test]
fn recovery_retains_a_reboot_until_the_selected_generation_is_running() {
    for profile in [OLD, NEW] {
        for pending in [None, Some(OLD), Some(NEW)] {
            for running in [OLD, NEW, RUNNING] {
                assert_eq!(
                    recovery_pending(OLD, NEW, profile, running, pending).unwrap(),
                    if running == OLD { None } else { Some(OLD) }
                );
            }
        }
    }
    assert_eq!(
        recovery_pending(OLD, OLD, OLD, RUNNING, Some(OLD)).unwrap(),
        Some(OLD)
    );
}

#[test]
fn unrelated_or_malformed_generation_state_refuses_recovery() {
    assert!(recovery_pending(OLD, NEW, RUNNING, OLD, None).is_err());
    assert!(recovery_pending(OLD, NEW, OLD, OLD, Some(RUNNING)).is_err());
    for bad in [
        "",
        "relative",
        "/nix/store/invalid",
        "../escape",
        "/nix/store/00000000000000000000000000000000-nixos-system-old/child",
        "/nix/store/00000000000000000000000000000000-nixos-system-old\n",
    ] {
        assert!(recovery_pending(bad, NEW, NEW, OLD, None).is_err());
        assert!(recovery_pending(OLD, bad, OLD, OLD, None).is_err());
        assert!(recovery_pending(OLD, NEW, bad, OLD, None).is_err());
        assert!(recovery_pending(OLD, NEW, OLD, bad, None).is_err());
        assert!(recovery_pending(OLD, NEW, OLD, OLD, Some(bad)).is_err());
    }
}
