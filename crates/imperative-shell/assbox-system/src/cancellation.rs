// SPDX-License-Identifier: GPL-3.0-or-later
//! Installer-only cooperative cancellation. Effects run in a systemd cgroup so
//! cancellation stops builders and grandchildren before owned mounts are dropped.
use crate::{commands::Commands, files};
use assbox_domain::{Error, Result};
use rustix::termios::{self, OptionalActions, Termios};
use std::{
    fs::{self, OpenOptions},
    io::{self, IsTerminal, Read, Write},
    os::unix::{fs::OpenOptionsExt, process::CommandExt},
    path::Path,
    process::Stdio,
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread,
    time::Duration,
};

static CANCELLED: OnceLock<Arc<AtomicBool>> = OnceLock::new();

pub fn install_handlers() -> Result<()> {
    if CANCELLED.get().is_some() {
        return Err(Error::new("installer cancellation already initialized"));
    }
    let flag = Arc::new(AtomicBool::new(false));
    for signal in [
        signal_hook::consts::SIGINT,
        signal_hook::consts::SIGTERM,
        signal_hook::consts::SIGHUP,
    ] {
        files::io(signal_hook::flag::register(signal, Arc::clone(&flag)))?;
    }
    CANCELLED
        .set(flag)
        .map_err(|_| Error::new("installer cancellation initialization raced"))
}

pub fn check() -> Result<()> {
    if CANCELLED
        .get()
        .is_some_and(|flag| flag.load(Ordering::SeqCst))
    {
        Err(Error::new(
            "installation cancelled; inspect the recorded phase before retrying",
        ))
    } else {
        Ok(())
    }
}

/// No unattended retries and no blocked stdin read that prevents cancellation.
pub fn retry_build() -> Result<bool> {
    check()?;
    if !io::stdin().is_terminal() {
        return Ok(false);
    }
    print!("Retry this exact build after correcting the problem? [y/N]: ");
    files::io(io::stdout().flush())?;
    Ok(matches!(read_line()?.trim(), "y" | "yes"))
}

/// The CLI exits on cancellation; an outstanding stdin reader cannot delay that
/// exit or hold a mount. Do not issue another prompt after this returns an error.
pub fn read_line() -> Result<String> {
    check()?;
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut answer = String::new();
        let result = io::stdin().read_line(&mut answer).and_then(|length| {
            if length == 0 {
                Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "installation input closed",
                ))
            } else {
                Ok(answer)
            }
        });
        let _ = sender.send(result);
    });
    loop {
        check()?;
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(answer) => return files::io(answer),
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(_) => return Err(Error::new("installation input closed")),
        }
    }
}

/// Restore terminal modes and discard unread secrets on every unsuccessful exit.
/// Noninteractive callers retain systemd's password-agent behavior.
struct TerminalState {
    saved: Option<Termios>,
}

impl TerminalState {
    fn save() -> Result<Self> {
        let saved = if io::stdin().is_terminal() {
            Some(termios::tcgetattr(io::stdin()).map_err(|e| Error::new(e.to_string()))?)
        } else {
            None
        };
        Ok(Self { saved })
    }

    fn restore(&mut self, action: OptionalActions) -> Result<()> {
        if let Some(saved) = &self.saved {
            termios::tcsetattr(io::stdin(), action, saved)
                .map_err(|e| Error::new(format!("cannot restore password terminal: {e}")))?;
            self.saved = None;
        }
        Ok(())
    }
}

impl Drop for TerminalState {
    fn drop(&mut self) {
        // The password helper has been reaped before this guard is dropped.
        // TCSAFLUSH discards queued input as the original modes are restored.
        if let Err(error) = self.restore(OptionalActions::Flush) {
            eprintln!("{error}");
        }
    }
}

/// Only the fixed, single-process systemd password client uses this adapter.
/// Secret output is bounded in memory and never written into command logs.
pub fn password(c: &Commands, prompt: &str) -> Result<Vec<u8>> {
    check()?;
    let mut terminal = TerminalState::save()?;
    let mut child = c
        .command("systemd-ask-password", &["--echo=no", prompt])?
        // TTY reads must stay in the installer's foreground process group.
        .stdin(Stdio::inherit())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| Error::new(e.to_string()))?;
    // stdout is piped above; handle even an unexpected missing pipe before exit.
    let Some(stream) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(Error::new("password output unavailable"));
    };
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stream.take(4097).read_to_end(&mut bytes).map(|_| bytes)
    });
    let status = loop {
        if let Err(error) = check() {
            let _ = child.kill();
            let _ = child.wait();
            break Err(error);
        }
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(Error::new(error.to_string()));
            }
        }
    };
    let output = reader
        .join()
        .map_err(|_| Error::new("password reader failed"))?;
    if !status?.success() {
        return Err(Error::new("password request failed"));
    }
    let output = files::io(output)?;
    if output.len() > 4096 {
        return Err(Error::new("password output exceeds limit"));
    }
    check()?;
    terminal.restore(OptionalActions::Now)?;
    Ok(output)
}

/// stdout/stderr go to private files, never unbounded in-memory capture. The
/// service gets the same fixed environment as ordinary privileged commands.
pub fn run(c: &Commands, program: &str, args: &[&str], logs: &Path) -> Result<String> {
    check()?;
    files::create_private(logs)?;
    let id = files::random_id()?;
    let unit = format!("assbox-install-{id}.service");
    let output = logs.join(format!("{id}.stdout"));
    let errors = logs.join(format!("{id}.stderr"));
    let out = files::io(
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&output),
    )?;
    let err = files::io(
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&errors),
    )?;
    let executable = c.executable(program)?;
    let command = c.command(program, args)?;
    let mut invocation = vec![
        "--quiet".to_owned(),
        "--wait".to_owned(),
        "--pipe".to_owned(),
        "--collect".to_owned(),
        format!("--unit={unit}"),
        "--service-type=exec".to_owned(),
        "--property=KillMode=control-group".to_owned(),
        "--property=ExitType=cgroup".to_owned(),
        "--property=TimeoutStopSec=30s".to_owned(),
    ];
    for (key, value) in command.get_envs() {
        if let Some(value) = value {
            invocation.push(format!(
                "--setenv={}={}",
                key.to_string_lossy(),
                value.to_string_lossy()
            ));
        }
    }
    invocation.push("--".to_owned());
    invocation.push(files::path_text(&executable)?.to_owned());
    invocation.extend(args.iter().map(|arg| (*arg).to_owned()));
    let borrowed: Vec<_> = invocation.iter().map(String::as_str).collect();
    let mut child = c
        .command("systemd-run", &borrowed)?
        .process_group(0)
        .stdin(Stdio::null())
        .stdout(out)
        .stderr(err)
        .spawn()
        .map_err(|e| Error::new(e.to_string()))?;
    eprintln!(
        "{program}: progress is in {} (service {unit})",
        errors.display()
    );
    let status = loop {
        if let Some(status) = files::io(child.try_wait())? {
            break status;
        }
        if check().is_err() {
            // A signal may arrive before systemd has created the service. Keep
            // trying until the waiting client exits; never abandon the writer.
            let _ = c
                .command("systemctl", &["stop", &unit])?
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
        thread::sleep(Duration::from_millis(100));
    };
    // Also stop after an unexpected bridge failure: systemd-run exiting alone
    // must not let a still-running service outlive the mount leases.
    loop {
        let stopped = c
            .command("systemctl", &["stop", &unit])?
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let state = c.text(
            "systemctl",
            &["show", &unit, "--property=LoadState", "--value"],
        );
        if stopped.is_ok_and(|status| status.success())
            || state.is_ok_and(|state| state.trim() == "not-found")
        {
            break;
        }
        eprintln!(
            "Cannot establish that {unit} stopped; retaining mount ownership until systemd is reachable."
        );
        thread::sleep(Duration::from_secs(1));
    }
    check()?;
    if !status.success() {
        return Err(Error::new(format!(
            "{program} failed ({status}); inspect {}",
            errors.display()
        )));
    }
    if files::io(fs::metadata(&output))?.len() > 1024 * 1024 {
        return Err(Error::new("installer command output exceeds limit"));
    }
    files::text(&output)
}
