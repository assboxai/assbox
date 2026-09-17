// SPDX-License-Identifier: GPL-3.0-or-later
use std::io::Write;
use std::process::{Command, Stdio};

#[test]
fn wifi_credentials_roundtrip_through_libnm() {
    // These are disposable samples, never actual network credentials. The test
    // invokes the consumer's parser without a daemon, D-Bus or network changes.
    let ssids = [
        "ordinary",
        "65;66;",
        "0;255;",
        "65; 66; ",
        " 65;66; ",
        "65;66",
        "999;",
        ";",
        ";;",
        "ordinary;value",
        r"65\;66;",
        r"65\\;66;",
        r"literal\s\n\\",
        " leading and trailing ",
        " ",
        "réseau-日本語",
        "01234567890123456789012345678901",
        "éééééééééééééééé", // Exactly 32 UTF-8 bytes.
        "[section]#=${literal}",
    ];
    let passwords = [
        "passphrase",
        " pass word ",
        r"pass\s\word;",
        "65;66;67;",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    ];
    for (index, ssid) in ssids.iter().enumerate() {
        let password = passwords[index % passwords.len()];
        let keyfile = assbox_config::wifi_keyfile(ssid, password).unwrap();
        let mut child = Command::new("python3")
            .args([
                "-c",
                include_str!("../../../../tests/fixtures/wifi_keyfile.py"),
                ssid,
                password,
            ])
            .stdin(Stdio::piped())
            .spawn()
            .expect("Python with PyGObject and libnm is required; use the Nix development shell");
        child
            .stdin
            .take()
            .unwrap()
            .write_all(keyfile.as_bytes())
            .unwrap();
        assert!(
            child.wait().unwrap().success(),
            "libnm sample {index} failed"
        );
    }
}
