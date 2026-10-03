// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
#[cfg(test)]
mod acceptance;
mod boot_guard;
pub mod install;
pub mod manage;
mod release;
mod source;

use assbox_domain::*;
use assbox_system::commands::Commands;

pub fn check_evaluation(c: &Commands, flake: &str) -> Result<()> {
    let target = format!("{flake}#nixosConfigurations.assbox.config.assbox.audit");
    let json = c.capture(
        "nix",
        &[
            "eval",
            "--json",
            "--no-write-lock-file",
            "--no-update-lock-file",
            &target,
        ],
    )?;
    let f = c.jq_fields(
        &json,
        r#"[.enabled,(.selectedComponents|join(",")),.presentation,.firewall,.rootLocked,.agentLocked,
        (.agentGroups|join(",")),(.trustedUsers|join(",")),.sandbox,.requireSignatures,
        .acceptFlakeConfig,.automount,.passwordlessSudo,.efiWrites,.boot] |
        .[] | tostring + "\u0000""#,
    )?;
    if f.len() != 15 {
        return Err(Error::new("unsupported Assbox audit schema"));
    }
    let yes = |s: &str| -> Result<bool> {
        match s {
            "true" => Ok(true),
            "false" => Ok(false),
            _ => Err(Error::new("missing audit boolean")),
        }
    };
    let list = |s: &str| -> Vec<String> {
        if s.is_empty() {
            Vec::new()
        } else {
            s.split(',').map(str::to_owned).collect()
        }
    };
    assbox_policy::validate_audit(&Audit {
        enabled: yes(&f[0])?,
        components: f[1].parse()?,
        presentation: f[2].parse()?,
        firewall: yes(&f[3])?,
        root_locked: yes(&f[4])?,
        agent_locked: yes(&f[5])?,
        agent_groups: list(&f[6]),
        trusted_users: list(&f[7]),
        sandbox: yes(&f[8])?,
        require_signatures: yes(&f[9])?,
        accept_flake_config: yes(&f[10])?,
        automount: yes(&f[11])?,
        passwordless_sudo: yes(&f[12])?,
        efi_writes: yes(&f[13])?,
        boot: f[14].parse()?,
    })
}

/// Read-only release inspection for bootstrap/release-building tools. A historical
/// baseline is not installed, evaluated, or recorded as an accepted update.
pub fn inspect_release(tag: &str, directory: &std::path::Path, historical: bool) -> Result<()> {
    assbox_system::files::require_root()?;
    let authenticated = release::fetch(&Commands, Some(tag), directory, None, historical)?;
    assbox_system::files::atomic_write(
        &directory.join("verified-source-path"),
        assbox_system::files::path_text(&authenticated.source_path)?.as_bytes(),
        0o600,
    )?;
    println!(
        "Authenticated {}{}; no system or replay state changed.",
        authenticated.manifest.tag.as_str(),
        if historical {
            " (historical inspection only)"
        } else {
            ""
        }
    );
    Ok(())
}
