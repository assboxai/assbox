// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_system::files::{entry_exists, random_id};
use std::{fs, os::unix::fs::symlink};

#[test]
fn permission_denied_never_means_absent() {
    use std::os::unix::fs::PermissionsExt;
    // Root bypasses discretionary permissions; this case runs in the unprivileged
    // development/build sandbox, while VM tests cover root-owned durable state.
    if assbox_system::files::require_root().is_ok() {
        return;
    }
    let root = std::env::temp_dir().join(format!("assbox-denied-{}", random_id().unwrap()));
    fs::create_dir(&root).unwrap();
    fs::set_permissions(&root, fs::Permissions::from_mode(0o000)).unwrap();
    let result = entry_exists(&root.join("state"));
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
    fs::remove_dir(root).unwrap();
    assert!(result.is_err());
}
#[test]
fn dangling_and_invalid_ancestors_never_mean_absent() {
    let root = std::env::temp_dir().join(format!("assbox-observe-{}", random_id().unwrap()));
    fs::create_dir(&root).unwrap();
    let absent = root.join("absent");
    assert!(!entry_exists(&absent).unwrap());
    let link = root.join("link");
    symlink(&absent, &link).unwrap();
    assert!(entry_exists(&link).unwrap());
    assert!(entry_exists(&link.join("child")).is_err());
    assert!(entry_exists(&absent.join("child")).is_err());
    let directory = root.join("directory");
    fs::create_dir(&directory).unwrap();
    let alias = root.join("alias");
    symlink(&directory, &alias).unwrap();
    assert!(entry_exists(&alias.join("child")).is_err());
    assert!(entry_exists(std::path::Path::new("relative-state")).is_err());
    let file = root.join("file");
    fs::write(&file, b"state").unwrap();
    assert!(entry_exists(&file).unwrap());
    assert!(entry_exists(&file.join("child")).is_err());
    fs::remove_dir_all(root).unwrap();
}
