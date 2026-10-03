// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_policy::recovery_target;

const OLD: &str = "/nix/store/00000000000000000000000000000000-nixos-system-old";
const NEW: &str = "/nix/store/11111111111111111111111111111111-nixos-system-new";
const RUNNING: &str = "/nix/store/22222222222222222222222222222222-nixos-system-running";

#[test]
fn uncertain_activation_always_requires_reboot_even_if_links_already_match() {
    for profile in [OLD, NEW] {
        for pending in [None, Some(OLD), Some(NEW)] {
            for running in [OLD, NEW, RUNNING] {
                assert_eq!(
                    recovery_target(OLD, NEW, profile, running, pending).unwrap(),
                    OLD
                );
            }
        }
    }
    assert_eq!(
        recovery_target(OLD, OLD, OLD, RUNNING, Some(OLD)).unwrap(),
        OLD
    );
}

#[test]
fn unrelated_or_malformed_generation_state_refuses_recovery() {
    assert!(recovery_target(OLD, NEW, RUNNING, OLD, None).is_err());
    assert!(recovery_target(OLD, NEW, OLD, OLD, Some(RUNNING)).is_err());
    for bad in [
        "",
        "relative",
        "/nix/store/invalid",
        "../escape",
        "/nix/store/00000000000000000000000000000000-nixos-system-old/child",
        "/nix/store/00000000000000000000000000000000-nixos-system-old\n",
    ] {
        assert!(recovery_target(bad, NEW, NEW, OLD, None).is_err());
        assert!(recovery_target(OLD, bad, OLD, OLD, None).is_err());
        assert!(recovery_target(OLD, NEW, bad, OLD, None).is_err());
        assert!(recovery_target(OLD, NEW, OLD, bad, None).is_err());
        assert!(recovery_target(OLD, NEW, OLD, OLD, Some(bad)).is_err());
    }
}
