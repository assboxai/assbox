// SPDX-License-Identifier: GPL-3.0-or-later
//! Noninstalled test harness. No test transport or fixture entrypoint is compiled
//! into the appliance binary. Invoked explicitly inside disposable NixOS VMs.
use assbox_domain::release::ReleaseFloor;
use assbox_system::{commands::Commands, files};
use std::path::Path;

fn require_vm() {
    files::require_root().unwrap();
    assert_eq!(
        files::text(Path::new("/etc/assbox-acceptance-vm")).unwrap(),
        "disposable\n"
    );
}

#[test]
#[ignore = "requires the disposable authenticated-release VM and its test-only tool closure"]
fn release_fetch() {
    require_vm();
    let directory = Path::new("/var/lib/assbox-acceptance");
    let floor = if files::entry_exists(&directory.join("floor")).unwrap() {
        Some(ReleaseFloor::parse(&files::text(&directory.join("floor")).unwrap()).unwrap())
    } else {
        None
    };
    let tag = std::env::var("ASSBOX_TEST_TAG").unwrap();
    let expected = std::env::var("ASSBOX_TEST_ERROR").unwrap();
    let result = crate::release::fetch(
        &Commands,
        (tag != "latest").then_some(tag.as_str()),
        &directory.join("download"),
        floor.as_ref(),
        false,
    );
    if expected.is_empty() {
        let verified = result.unwrap();
        assert!(verified.source_path.starts_with("/nix/store"));
        assert!(verified.source_path.join("flake.lock").is_file());
        files::atomic_write(
            &directory.join("accepted-floor"),
            verified.floor.encode().as_bytes(),
            0o600,
        )
        .unwrap();
    } else {
        let error = result
            .err()
            .expect("untrusted release was accepted")
            .to_string();
        assert!(
            error.contains(&expected),
            "expected {expected:?}, got {error:?}"
        );
        assert!(!files::entry_exists(&directory.join("accepted-floor")).unwrap());
    }
}
