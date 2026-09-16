// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_system::files::{entry_exists, random_id};
use std::{fs, os::unix::fs::symlink};
#[test]
fn dangling_and_invalid_ancestors_never_mean_absent() {
    let root = std::env::temp_dir().join(format!("assbox-observe-{}", random_id().unwrap()));
    fs::create_dir(&root).unwrap();
    let absent = root.join("absent");
    assert!(!entry_exists(&absent).unwrap());
    let link = root.join("link");
    symlink(&absent, &link).unwrap();
    assert!(entry_exists(&link).unwrap());
    let file = root.join("file");
    fs::write(&file, b"state").unwrap();
    assert!(entry_exists(&file).unwrap());
    assert!(entry_exists(&file.join("child")).is_err());
    fs::remove_dir_all(root).unwrap();
}
