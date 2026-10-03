// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_system::{
    commands::{Commands, valid_store_system},
    files,
};
use std::path::Path;
#[test]
fn subprocesses_receive_literal_arguments_without_a_shell() {
    let argument = "$(false); echo not-executed | cat > nowhere";
    assert_eq!(
        Commands.text("printf", &["%s", argument]).unwrap(),
        argument
    );
    assert_eq!(Commands.input("cat", &[], b"a\0b\n").unwrap(), b"a\0b\n");
    assert!(Commands.run("false", &[]).is_err());
    assert!(Commands.capture("false", &[]).is_err());
    assert!(Commands.input("false", &[], b"").is_err());
    assert!(Commands.executable("../bin/sh").is_err());
    assert!(
        Commands
            .executable("assbox-nonexistent-test-command")
            .is_err()
    );
}
#[test]
fn activation_only_accepts_system_store_paths_and_known_actions() {
    let valid = "/nix/store/00000000000000000000000000000000-nixos-system-assbox-26.05";
    assert!(valid_store_system(valid));
    for bad in [
        "",
        "/tmp/system",
        "/nix/store/a-nixos-system-x",
        "/nix/store/00000000000000000000000000000000-nixos-system-x/bin/sh",
        "/nix/store/00000000000000000000000000000000-other-package",
    ] {
        assert!(!valid_store_system(bad));
    }
    assert!(Commands.activate("/tmp/system", "switch").is_err());
    assert!(Commands.activate(valid, "arbitrary").is_err());
}
#[test]
fn writable_ancestors_and_relative_paths_are_never_trusted() {
    assert!(files::trusted_dir(Path::new("relative")).is_err());
    assert!(files::trusted_dir(Path::new("/tmp")).is_err());
    assert!(files::regular(Path::new("/dev/null")).is_err());
}

#[test]
fn prepared_root_observation_does_not_follow_links_or_ignore_recovered_files() {
    use std::{fs, os::unix::fs::symlink};
    struct Fixture(std::path::PathBuf);
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    let fixture = Fixture(
        std::env::temp_dir().join(format!("assbox-root-test-{}", files::random_id().unwrap())),
    );
    fs::create_dir(&fixture.0).unwrap();
    assert!(files::prepared_root_entries(&fixture.0).unwrap().is_empty());
    let recovery = fixture.0.join("lost+found");
    fs::create_dir(&recovery).unwrap();
    let observed = files::prepared_root_entries(&fixture.0).unwrap();
    assert_eq!(observed.len(), 1);
    assert!(observed[0].is_directory && observed[0].empty && observed[0].same_filesystem);
    fs::write(recovery.join("#1234"), b"recovered user data").unwrap();
    assert!(!files::prepared_root_entries(&fixture.0).unwrap()[0].empty);
    assert_eq!(
        fs::read(recovery.join("#1234")).unwrap(),
        b"recovered user data"
    );
    fs::remove_dir_all(&recovery).unwrap();
    symlink("/", &recovery).unwrap();
    let observed = files::prepared_root_entries(&fixture.0).unwrap();
    assert!(!observed[0].is_directory && !observed[0].empty);
    fs::remove_file(&recovery).unwrap();
    fs::write(&recovery, b"not a directory").unwrap();
    assert!(!files::prepared_root_entries(&fixture.0).unwrap()[0].is_directory);
    fs::write(fixture.0.join("extra"), b"extra data").unwrap();
    assert_eq!(files::prepared_root_entries(&fixture.0).unwrap().len(), 2);
    assert!(files::prepared_root_entries(&recovery).is_err());
}

#[test]
fn boot_receipt_is_resolved_only_in_the_target_store() {
    use std::{fs, os::unix::fs::symlink};
    let root =
        std::env::temp_dir().join(format!("assbox-store-test-{}", files::random_id().unwrap()));
    let system = "/nix/store/00000000000000000000000000000000-nixos-system-target";
    let physical = root.join(system.trim_start_matches('/'));
    fs::create_dir_all(&physical).unwrap();
    let receipt = "/nix/store/11111111111111111111111111111111-assbox-boot-policy.json";
    let leaf = root.join(receipt.trim_start_matches('/'));
    fs::write(&leaf, b"target receipt").unwrap();
    let link = physical.join("assbox-boot-policy.json");
    symlink(receipt, &link).unwrap();
    assert_eq!(
        files::target_store_receipt(&root, system).unwrap(),
        b"target receipt"
    );
    for bad in [
        "/etc/shadow",
        "/nix/store/../secret",
        "/nix/store/relative/nested",
        "relative",
    ] {
        fs::remove_file(&link).unwrap();
        symlink(bad, &link).unwrap();
        assert!(files::target_store_receipt(&root, system).is_err());
    }
    fs::remove_file(&link).unwrap();
    symlink(receipt, &link).unwrap();
    fs::remove_file(&leaf).unwrap();
    symlink("/etc/passwd", &leaf).unwrap();
    assert!(files::target_store_receipt(&root, system).is_err());
    fs::remove_dir_all(root).unwrap();
}
