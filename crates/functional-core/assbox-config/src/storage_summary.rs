// SPDX-License-Identifier: GPL-3.0-or-later
//! Human confirmation is an additional guard, not a substitute for re-observation.
use assbox_domain::{Disk, Result};
use assbox_policy::InstallPlan;

pub fn terminal_text(text: &str) -> String {
    if text.is_empty() {
        return "(unavailable)".into();
    }
    text.chars().flat_map(char::escape_default).collect()
}

pub fn disk_summary(role: &str, disk: &Disk) -> String {
    format!(
        "{role}: {} | {} bytes ({} GiB) | device {}\n  model: {}\n  serial: {}\n  by-id: {}",
        terminal_text(&disk.path),
        disk.bytes,
        disk.bytes / (1024 * 1024 * 1024),
        terminal_text(&disk.major_minor),
        terminal_text(&disk.model),
        terminal_text(&disk.serial),
        terminal_text(&disk.persistent_path)
    )
}

pub fn plan_storage_summary(plan: &InstallPlan) -> Result<String> {
    let inventory = plan.inventory();
    let target = inventory.disk(&plan.root().parent)?;
    let backup = inventory.disk(&plan.backup().parent)?;
    let mut text = disk_summary("TARGET WHOLE DISK", target);
    text.push_str(&format!(
        "\n  root: {} | {} bytes | UUID {}\n",
        terminal_text(&plan.root().path),
        plan.root().bytes,
        terminal_text(&plan.root().uuid)
    ));
    if let Some(esp) = plan.esp() {
        text.push_str(&format!(
            "  ESP on this target: {} | {} bytes | UUID {}\n",
            terminal_text(&esp.path),
            esp.bytes,
            terminal_text(&esp.uuid)
        ));
    }
    text.push_str(&disk_summary("EXTERNAL BACKUP DISK", backup));
    text.push_str(&format!(
        "\n  backup partition: {} | {} bytes\nINSTALLER MEDIUM: {}",
        terminal_text(&plan.backup().path),
        plan.backup().bytes,
        terminal_text(inventory.live_media.source())
    ));
    Ok(text)
}

pub fn confirmation_phrase(plan: &InstallPlan) -> Result<String> {
    let disk = plan.inventory().disk(&plan.root().parent)?;
    let identity = if disk.persistent_path.is_empty() {
        format!("{} [{}; {} bytes]", disk.path, disk.major_minor, disk.bytes)
    } else {
        disk.persistent_path.clone()
    };
    Ok(format!(
        "INSTALL DISK {} AS {}",
        terminal_text(&identity),
        plan.request().choices.hostname.as_str()
    ))
}
