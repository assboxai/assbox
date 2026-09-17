// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_system::{commands::Commands, files, probe};
use std::{
    fs,
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
    process::Command,
};

fn interactive(program: &str, args: &[&str]) -> Result<()> {
    interactive_executable(&installed_program(program)?, args)
}

fn interactive_executable(program: &Path, args: &[&str]) -> Result<()> {
    let status = interactive_command(program, args)?
        .status()
        .map_err(|e| Error::new(e.to_string()))?;
    if status.success() {
        Ok(())
    } else {
        Err(Error::new(format!(
            "{} exited with {status}",
            program.display()
        )))
    }
}

fn interactive_command(program: &Path, args: &[&str]) -> Result<Command> {
    let uid = Commands.text("id", &["-u"])?;
    let uid = uid
        .trim()
        .parse::<u32>()
        .map_err(|_| Error::new("invalid user identity"))?;
    let runtime = format!("/run/user/{uid}");
    let mut command = Command::new(program);
    command
        .args(args)
        .env(
            "PATH",
            format!("{}:/run/current-system/sw/bin", Commands::path()),
        )
        .env("HOME", "/home/agent")
        .env("XDG_RUNTIME_DIR", &runtime)
        .env(
            "DBUS_SESSION_BUS_ADDRESS",
            format!("unix:path={runtime}/bus"),
        )
        .current_dir("/home/agent");
    Ok(command)
}

fn start_application(backend: &str, launcher: &str, frontend: &str) -> Result<()> {
    let autostart = Commands.jq_fields(
        &probe::runtime_json()?,
        r#"(.session.autostart // []) | .[] | . + "\u0000""#,
    )?;
    let frontend = autostart
        .iter()
        .any(|id| id == launcher)
        .then_some(frontend);
    let systemctl = Commands.executable("systemctl")?;
    start_application_units(backend, frontend, |args| {
        let status = interactive_command(&systemctl, args)?
            .status()
            .map_err(|e| Error::new(e.to_string()))?;
        if status.success() {
            Ok(true)
        } else if args.get(1) == Some(&"is-active") && status.code() == Some(3) {
            Ok(false)
        } else {
            Err(Error::new(format!(
                "systemctl {} exited with {status}",
                args.join(" ")
            )))
        }
    })
}

/// Explicit successful setup may open a selected frontend once. Background
/// backend restarts never call this and must not reopen a closed window.
fn start_application_units(
    backend: &str,
    frontend: Option<&str>,
    mut systemctl: impl FnMut(&[&str]) -> Result<bool>,
) -> Result<()> {
    systemctl(&["--user", "restart", backend])?;
    if let Some(frontend) = frontend
        && systemctl(&["--user", "is-active", "--quiet", "graphical-session.target"])?
    {
        systemctl(&["--user", "start", frontend])?;
    }
    Ok(())
}
fn require_selected(component: Component) -> Result<()> {
    if Commands.text("id", &["-un"])?.trim() != "agent" {
        return Err(Error::new(
            "run onboarding as the unprivileged agent user: sudo -iu agent assbox component setup ID",
        ));
    }
    let runtime = probe::runtime(&Commands)?;
    let selected: Components = runtime
        .first()
        .ok_or_else(|| Error::new("component configuration missing"))?
        .parse()?;
    if !selected.contains(component) {
        return Err(Error::new("component is not enabled"));
    }
    Ok(())
}

pub fn diagnose(component: Component) -> Result<()> {
    require_selected(component)?;
    let path = Path::new("/etc/assbox/diagnostics").join(component.as_str());
    let script = fs::canonicalize(path)
        .map_err(|_| Error::new("this component has no managed remote diagnostic command"))?;
    if !script.starts_with("/nix/store") {
        return Err(Error::new("diagnostic script is not immutable Nix code"));
    }
    interactive_executable(&script, &[])
}

pub fn setup(component: Component) -> Result<()> {
    require_selected(component)?;
    let onboarding = Path::new("/etc/assbox/onboarding").join(component.as_str());
    if onboarding.exists() {
        let script = files::io(fs::canonicalize(onboarding))?;
        if !script.starts_with("/nix/store") {
            return Err(Error::new("onboarding script is not immutable Nix code"));
        }
        return interactive_executable(&script, &[]);
    }
    match component {
        Component::ChatgptDesktop => {
            println!(
                "Sign in using the ChatGPT window in the X11 session. Linux Remote pairing is not yet established."
            );
            Ok(())
        }
        Component::OpencodeServer => {
            let dir = Path::new("/home/agent/.config/assbox");
            files::io(fs::create_dir_all(dir))?;
            files::io(fs::set_permissions(dir, fs::Permissions::from_mode(0o700)))?;
            let env = dir.join("opencode.env");
            if let Ok(meta) = fs::symlink_metadata(&env) {
                let uid = Commands.text("id", &["-u"])?;
                let uid = uid
                    .trim()
                    .parse::<u32>()
                    .map_err(|_| Error::new("invalid user identity"))?;
                if !meta.is_file() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
                    return Err(Error::new(
                        "OpenCode credential file must be a private regular file owned by agent",
                    ));
                }
            } else {
                let secret: String = files::random_bytes::<32>()?
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect();
                let mut file = files::io(
                    fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .mode(0o600)
                        .open(&env),
                )?;
                files::io(
                    file.write_all(format!("OPENCODE_SERVER_PASSWORD={secret}\n").as_bytes()),
                )?;
                files::io(file.sync_all())?;
            }
            interactive("opencode", &["auth", "login"])?;
            start_application(
                "assbox-opencode.service",
                "opencode-attach",
                "assbox-opencode-ui.service",
            )?;
            println!(
                "OpenCode server is configured on loopback. Its password stays in ~/.config/assbox/opencode.env."
            );
            Ok(())
        }
        Component::OpenclawGateway => {
            interactive("openclaw", &["onboard", "--skip-daemon"])?;
            start_application(
                "assbox-openclaw.service",
                "openclaw-dashboard",
                "assbox-openclaw-ui.service",
            )?;
            println!(
                "Assbox owns the gateway service. Other agent runtimes are separate selections."
            );
            Ok(())
        }
        Component::Happy => interactive("happy", &["auth", "login"]),
        Component::Codex => interactive("codex", &["login"]),
        Component::ClaudeCode => interactive("claude", &[]),
        Component::GeminiCli => interactive("gemini", &[]),
        Component::Grok => interactive("grok", &[]),
        Component::CursorAgent => interactive("cursor-agent", &["login"]),
        Component::AntigravityCli => interactive("agy", &[]),
        Component::Opencode => interactive("opencode", &["auth", "login"]),
        Component::Openclaw => interactive("openclaw", &["onboard", "--skip-daemon"]),
        _ => {
            println!(
                "{component}: see /etc/assbox/components.json for setup requirements. No authentication or remote health is inferred from installation."
            );
            Ok(())
        }
    }
}

/// Only explicit editor/onboarding requests may resolve an installed UI program.
/// Storage, Nix and maintenance commands never use this fallback.
pub(crate) fn installed_program(name: &str) -> Result<std::path::PathBuf> {
    if name.is_empty()
        || name.starts_with('-')
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
    {
        return Err(Error::new(
            "use an installed program basename, not a path or shell expression",
        ));
    }
    if let Ok(path) = Commands.executable(name) {
        return Ok(path);
    }
    let path = files::io(fs::canonicalize(
        Path::new("/run/current-system/sw/bin").join(name),
    ))?;
    if !path.starts_with("/nix/store") || !path.is_file() {
        return Err(Error::new(
            "requested UI program is not an installed Nix executable",
        ));
    }
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn setup_opens_only_a_selected_frontend_in_an_active_session() {
        for selected in [false, true] {
            for active in [false, true] {
                let mut calls = Vec::new();
                start_application_units(
                    "backend.service",
                    selected.then_some("frontend.service"),
                    |args| {
                        calls.push(args.join(" "));
                        Ok(args[1] != "is-active" || active)
                    },
                )
                .unwrap();
                let mut expected = vec!["--user restart backend.service"];
                if selected {
                    expected.push("--user is-active --quiet graphical-session.target");
                    if active {
                        expected.push("--user start frontend.service");
                    }
                }
                assert_eq!(calls, expected);
            }
        }
    }

    #[test]
    fn setup_propagates_failures_and_stops_before_subsequent_actions() {
        for fail_at in 1..=3 {
            let mut calls = 0;
            let result = start_application_units("backend", Some("frontend"), |_| {
                calls += 1;
                if calls == fail_at {
                    Err(Error::new("test failure"))
                } else {
                    Ok(true)
                }
            });
            assert!(result.is_err());
            assert_eq!(calls, fail_at);
        }
    }
}
