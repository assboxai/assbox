// SPDX-License-Identifier: GPL-3.0-or-later
//! Read-only inspection of the agent user manager, never provider output or state.
use crate::commands::Commands;
use assbox_domain::{Error, Result};
use std::{collections::BTreeMap, process::Stdio};

const FIELDS: [&str; 9] = [
    "Id",
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
    "NRestarts",
    "ConditionResult",
];

fn unit_name(name: &str) -> bool {
    name.starts_with("assbox-")
        && name.ends_with(".service")
        && name.len() <= 128
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
}

fn listed_units(text: &str) -> Result<Vec<String>> {
    let mut names = Vec::new();
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let name = line.split_whitespace().next().unwrap_or("");
        if !unit_name(name) || names.len() >= 128 || names.iter().any(|n| n == name) {
            return Err(Error::new("unexpected agent service listing"));
        }
        names.push(name.to_owned());
    }
    Ok(names)
}

fn safe_properties(text: &str, names: &[String]) -> Result<String> {
    let mut found = BTreeMap::new();
    for block in text.trim().split("\n\n").filter(|block| !block.is_empty()) {
        let mut fields = BTreeMap::new();
        for line in block.lines() {
            let Some((key, value)) = line.split_once('=') else {
                return Err(Error::new("malformed agent service properties"));
            };
            if !FIELDS.contains(&key) {
                continue; // Never relay environment, command lines, StatusText or logs.
            }
            if value.len() > 128
                || !value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
                || fields.insert(key, value).is_some()
            {
                return Err(Error::new("invalid agent service property"));
            }
        }
        let name = fields.get("Id").copied().unwrap_or("");
        if !names.iter().any(|n| n == name) || found.insert(name, fields).is_some() {
            return Err(Error::new("unexpected or duplicate agent service identity"));
        }
    }
    if found.len() != names.len() {
        return Err(Error::new("agent service inspection was incomplete"));
    }
    let mut report = String::new();
    for name in names {
        report.push_str(&format!("{name}\n"));
        for key in &FIELDS[1..] {
            let value = found[name.as_str()]
                .get(key)
                .filter(|v| !v.is_empty())
                .copied()
                .unwrap_or("unknown");
            report.push_str(&format!("  {key}={value}\n"));
        }
    }
    Ok(report)
}

fn inspect(args: &[&str]) -> Result<String> {
    let uid = Commands.text("id", &["-u", "agent"])?;
    let uid = uid
        .trim()
        .parse::<u32>()
        .map_err(|_| Error::new("invalid agent UID"))?;
    if uid == 0 {
        return Err(Error::new("agent must be unprivileged"));
    }
    let current = Commands.text("id", &["-u"])?;
    let current = current
        .trim()
        .parse::<u32>()
        .map_err(|_| Error::new("invalid caller UID"))?;
    if current != 0 && current != uid {
        return Err(Error::new(
            "agent services were not inspected; run sudo assbox doctor, or run it as agent",
        ));
    }
    let mut command = Commands.command("timeout", &[])?;
    command.args(["--kill-after=2s", "10s"]);
    if current == 0 {
        command
            .arg(Commands.executable("runuser")?)
            .args(["-u", "agent", "--"]);
    }
    let runtime = format!("/run/user/{uid}");
    command
        .arg(Commands.executable("systemctl")?)
        .args(["--user", "--no-pager", "--no-legend", "--plain"])
        .args(args)
        .env("HOME", "/home/agent")
        .env("XDG_RUNTIME_DIR", &runtime)
        .env(
            "DBUS_SESSION_BUS_ADDRESS",
            format!("unix:path={runtime}/bus"),
        )
        .env("SYSTEMD_COLORS", "0")
        .stdin(Stdio::null());
    let output = command.output().map_err(|e| Error::new(e.to_string()))?;
    if !output.status.success() || output.stdout.len() > 1024 * 1024 {
        return Err(Error::new(
            "agent user-manager inspection failed or timed out; its state is unknown",
        ));
    }
    String::from_utf8(output.stdout).map_err(|_| Error::new("invalid agent service output"))
}

pub fn agent_report() -> Result<String> {
    let names = listed_units(&inspect(&["list-unit-files", "assbox-*.service"])?)?;
    if names.is_empty() {
        return Ok("No Assbox agent services are configured.\n".to_owned());
    }
    let properties = format!("--property={}", FIELDS.join(","));
    let mut args = vec!["show", "--all", properties.as_str()];
    args.extend(names.iter().map(String::as_str));
    safe_properties(&inspect(&args)?, &names)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_structured_nonsecret_service_state_is_reported() {
        let names = listed_units("assbox-cursor-worker.service enabled enabled\n").unwrap();
        let text = "Id=assbox-cursor-worker.service\nActiveState=activating\nSubState=auto-restart\nResult=exit-code\nExecMainStatus=7\nNRestarts=4\nStatusText=pairing-secret\nEnvironment=TOKEN=secret\nExecStart=/provider --token secret\n";
        let report = safe_properties(text, &names).unwrap();
        assert!(report.contains("SubState=auto-restart") && report.contains("ExecMainStatus=7"));
        assert!(report.contains("ConditionResult=unknown"));
        assert!(!report.contains("secret") && !report.contains("ExecStart"));
        for bad in [
            "",
            "Id=foreign.service",
            "Id=assbox-cursor-worker.service\nResult=bad\u{1b}",
            "Id=assbox-cursor-worker.service\nActiveState=active\nActiveState=failed",
        ] {
            assert!(safe_properties(bad, &names).is_err());
        }
    }
    #[test]
    fn service_names_cannot_be_options_paths_or_control_sequences() {
        for bad in [
            "--system",
            "/tmp/assbox-x.service",
            "assbox-../x.service",
            "assbox-x.service\u{1b}",
        ] {
            assert!(listed_units(bad).is_err());
        }
        assert!(listed_units("assbox-x.service enabled\nassbox-x.service enabled").is_err());
        assert_eq!(listed_units("").unwrap(), Vec::<String>::new());
    }
}
