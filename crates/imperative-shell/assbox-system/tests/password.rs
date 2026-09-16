// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_system::{cancellation, commands::Commands};

#[test]
fn real_password_terminal_and_cancellation() {
    let status = std::process::Command::new("python3")
        .arg("-c")
        .arg(include_str!(
            "../../../../tests/fixtures/password_terminal.py"
        ))
        .arg(std::env::current_exe().unwrap())
        .status()
        .expect("Python is required for the real password PTY regression");
    assert!(status.success(), "real password PTY regression failed");
}

#[test]
#[ignore = "subprocess entrypoint driven by the real password PTY regression"]
fn password_terminal_child() {
    let mode = std::env::var("ASSBOX_PASSWORD_TEST_MODE").unwrap();
    cancellation::install_handlers().unwrap();
    let result = cancellation::password(&Commands, "Assbox password regression:");
    if mode == "success" {
        assert_eq!(result.unwrap(), b"disposable-test-password\n");
        // A second prompt verifies restoration does not leave the next reader
        // in raw mode or with a stale cancellation/terminal state.
        let second = cancellation::password(&Commands, "Assbox second password:").unwrap();
        assert_eq!(second, b"second-disposable-password\n");
    } else {
        assert!(result.is_err(), "interrupted password client succeeded");
        assert_eq!(
            cancellation::check().is_err(),
            !mode.starts_with("helper-failure")
        );
    }
}
