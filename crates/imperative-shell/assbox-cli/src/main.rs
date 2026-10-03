// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
mod opencode;
mod user;
mod wizard;
mod worker;

use assbox_domain::*;
use assbox_engine::manage;
use assbox_system::{commands::Commands, files, probe};
use std::{
    env,
    process::{Command, ExitCode},
};

const HELP: &str = r#"Assbox — Assistant Box

  assbox install [--apply] [--release r-SEQUENCE]
      Interactive prepared-storage installer. --apply requires --release. Without --apply, display the plan only.
  assbox state backup|list|restore NAME [--apply]  Private provider-state checkpoints (sudo)
  assbox configure [--apply]            Preview or build/stage purpose-first reconfiguration
  assbox component stop|disable|enable ID  Explicit service lifecycle as agent
  assbox release verify TAG DIRECTORY   Authenticate/download without installing
  assbox release verify-kernel TAG DIRECTORY   Authenticate/import the default kernel in a fresh store
  assbox status                         Show running, boot and maintenance state
  assbox doctor                         Inspect system and agent-service state (sudo or agent)
  assbox check                          Validate and build without activation
  assbox rebuild [--boot]                Rebuild local NixOS configuration
  assbox update [--reboot]               Authenticate an immutable release and stage
  assbox cleanup                        Retain recovery generations and collect garbage
  assbox rollback                       Select a retained previous boot generation
  assbox recover [--rollback]            Inspect/recover an interrupted operation
  assbox package search NAME            Search this machine's pinned nixpkgs
  assbox package list                   List only CLI-managed additional packages
  assbox package add NAME                Build and activate one additional package
  assbox package remove NAME             Remove one CLI-managed additional package
  assbox config edit                    Edit human-owned /etc/nixos/local.nix
  assbox component set IDS MODE [--accept-unfree]
                                        Stage an explicit component set and presentation;
                                        ChatGPT requires X11; consent permits unfree packages machine-wide
  assbox component list                  List curated IDs, dependencies and blockers
  assbox component setup ID               Onboard as the unprivileged agent user
  assbox component diagnose ID            Capture private remote-service diagnostics as agent
  assbox worker recommend               Inspect KVM, RAM, storage and candidate uplinks
  assbox worker setup                   Interactive plan/build/stage workflow (sudo)
  assbox worker configure IDS [OPTIONS]  Plan explicit guest agents and move curated
                                        execution packages off the host (sudo)
      --network normal|internet|offline IPv4 egress policy (interactive selection required)
      --uplink NAME --dns IPV4          Repeat for explicit uplinks and resolvers
      --offline                        Legacy offline flag; uplink alone retains internet-only
      --memory auto|MIB --cpus N --state-gib auto|N
      --allow-mutable-code --allow-guest-sudo --accept-unfree
      --apply                           Build and stage for reboot; otherwise plan only
  assbox worker disable [--apply]        Disable without controller fallback or data deletion
  assbox worker status|doctor|check      Observe worker state; check requires sudo
  assbox worker start|stop               Lifecycle controls (sudo)
  assbox worker setup-ssh|login|shell    Controller-user transport/onboarding
  assbox logs                           Show the maintenance journal

Changes to machine configuration require sudo from the admin account.
Ordinary nixos-rebuild and /etc/nixos/local.nix remain fully supported.
"#;
fn edit() -> Result<()> {
    files::require_root()?;
    files::trusted_dir(std::path::Path::new("/etc/nixos"))?;
    files::regular(std::path::Path::new("/etc/nixos/local.nix"))?;
    let editor = env::var("EDITOR").unwrap_or_else(|_| "nano".to_owned());
    let mut words = editor.split_whitespace();
    let name = words.next().ok_or_else(|| Error::new("EDITOR is empty"))?;
    let status = Command::new(user::installed_program(name)?)
        .args(words)
        .arg("/etc/nixos/local.nix")
        .env("PATH", Commands::path())
        .status()
        .map_err(|e| Error::new(e.to_string()))?;
    if !status.success() {
        return Err(Error::new("editor failed"));
    }
    println!(
        "Saved local configuration. Use sudo assbox check, then sudo assbox rebuild (or standard nixos-rebuild)."
    );
    Ok(())
}
fn run(args: &[&str]) -> Result<()> {
    match args {
        [] | ["--help"] | ["-h"] | ["help"] => {
            print!("{HELP}");
            Ok(())
        }
        ["--version"] => {
            println!(
                "assbox {} ({})",
                env!("CARGO_PKG_VERSION"),
                std::env::consts::ARCH
            );
            Ok(())
        }
        ["install", rest @ ..] => wizard::install(rest),
        ["worker", rest @ ..] => worker::run(rest),
        ["status"] => manage::status(),
        ["doctor"] => {
            manage::status()?;
            Commands.run("systemctl", &["--failed", "--no-pager"])?;
            println!(
                "Agent service state (does not establish provider authentication or readiness):"
            );
            print!("{}", assbox_system::services::agent_report()?);
            Ok(())
        }
        ["check"] => manage::check(),
        ["rebuild"] => manage::rebuild(false),
        ["rebuild", "--boot"] => manage::rebuild(true),
        ["update"] => manage::update(false),
        ["update", "--reboot"] => manage::update(true),
        ["cleanup"] => manage::cleanup(),
        ["rollback"] => manage::rollback(),
        ["recover"] => manage::recover(false),
        ["recover", "--rollback"] => manage::recover(true),
        ["package", "search", query] => manage::search(query),
        ["package", "list"] => {
            for name in manage::packages()? {
                println!("{}", name.as_str());
            }
            Ok(())
        }
        ["package", "add", name] => manage::package_change(PackageName::parse(name)?, true),
        ["package", "remove", name] => manage::package_change(PackageName::parse(name)?, false),
        ["config", "edit"] => edit(),
        ["component", "list"] => {
            for component in Component::ALL {
                let dependencies = component
                    .dependencies()
                    .iter()
                    .map(|d| d.as_str())
                    .collect::<Vec<_>>()
                    .join(",");
                println!(
                    "{component} | dependencies: {dependencies} | proprietary: {} | mutable helpers: {}{}",
                    component.unfree(),
                    component.mutable_code(),
                    if component.blocked().is_empty() {
                        String::new()
                    } else {
                        format!(" | unavailable: {}", component.blocked())
                    }
                );
                if !component.code_notes().is_empty() {
                    println!("  {}", component.code_notes());
                }
            }
            Ok(())
        }
        ["component", "set", app, presentation] => {
            manage::components_set(app.parse()?, presentation.parse()?, false)
        }
        ["component", "set", app, presentation, "--accept-unfree"] => {
            manage::components_set(app.parse()?, presentation.parse()?, true)
        }
        ["state", rest @ ..] => {
            files::require_root()?;
            let helper = std::fs::canonicalize("/etc/assbox/state-helper")
                .map_err(|_| Error::new("state helper is not configured"))?;
            if !helper.starts_with("/nix/store") {
                return Err(Error::new("state helper must be immutable Nix code"));
            }
            let status = std::process::Command::new(helper)
                .args(rest)
                .status()
                .map_err(|e| Error::new(e.to_string()))?;
            if status.success() {
                Ok(())
            } else {
                Err(Error::new(
                    "state operation did not complete; inspect root-private recovery records",
                ))
            }
        }
        ["configure"] => wizard::configure(false),
        ["configure", "--apply"] => wizard::configure(true),
        ["component", action @ ("stop" | "disable" | "enable"), id] => {
            if Commands.text("id", &["-u"])?.trim() == "0" {
                let script = std::fs::canonicalize("/etc/assbox/service-helper")
                    .map_err(|_| Error::new("owner service helper is not configured"))?;
                if !script.starts_with("/nix/store") {
                    return Err(Error::new("service helper must be immutable"));
                }
                let status = std::process::Command::new(script)
                    .args([action, id])
                    .status()
                    .map_err(|e| Error::new(e.to_string()))?;
                if status.success() {
                    Ok(())
                } else {
                    Err(Error::new("owner service action did not complete"))
                }
            } else {
                user::service_control(id.parse()?, action)
            }
        }
        ["component", "setup", id] => user::setup(id.parse()?),
        ["component", "diagnose", id] => user::diagnose(id.parse()?),
        ["logs"] => Commands.run(
            "journalctl",
            &[
                "--unit=assbox-maintenance.service",
                "--no-pager",
                "-n",
                "100",
            ],
        ),
        ["internal", "release-baseline", tag, directory] => {
            assbox_engine::inspect_release(tag, std::path::Path::new(directory), true)
        }
        ["release", "verify", tag, directory] => {
            assbox_engine::inspect_release(tag, std::path::Path::new(directory), false)
        }
        ["release", "verify-kernel", tag, directory] => {
            assbox_engine::inspect_release_kernel(tag, std::path::Path::new(directory))
        }
        ["internal", "maintenance"] => manage::maintenance(false),
        ["internal", "maintenance", "--retry"] => manage::maintenance(true),
        ["internal", "boot-check"] => manage::boot_check(),
        ["internal", "boot-check", "--retry"] => manage::boot_check_retry(),
        ["internal", "opencode", mode] => opencode::launch(mode),
        ["internal", "hardware"] => {
            println!("{:#?}", probe::inventory(&Commands)?);
            Ok(())
        }
        _ => Err(Error::new(
            "unknown command or arguments; use assbox --help",
        )),
    }
}
fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let borrowed: Vec<&str> = args.iter().map(String::as_str).collect();
    match run(&borrowed) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("assbox: {e}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_arguments_do_not_start_operations() {
        for args in [
            vec!["nonsense"],
            vec!["update", "--force-unverified"],
            vec!["install", "--yes"],
            vec!["package", "add", "--impure"],
            vec!["internal", "opencode", "unknown"],
        ] {
            assert!(run(&args).is_err());
        }
    }
    #[test]
    fn help_and_version_do_not_require_a_machine() {
        assert!(run(&["--help"]).is_ok());
        assert!(run(&["--version"]).is_ok());
    }
}
