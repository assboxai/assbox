// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_system::{commands::Commands, files, probe};
use std::{
    fs,
    io::{self, IsTerminal, Write},
};

fn ask(label: &str, default: Option<&str>) -> Result<String> {
    if !io::stdin().is_terminal() {
        return Err(Error::new("the installer requires an interactive terminal"));
    }
    match default {
        Some(d) => print!("{label} [{d}]: "),
        None => print!("{label}: "),
    };
    files::io(io::stdout().flush())?;
    let mut answer = String::new();
    if files::io(io::stdin().read_line(&mut answer))? == 0 {
        return Err(Error::new("input closed; installation cancelled"));
    }
    let answer = answer.trim();
    if answer.is_empty() {
        return default
            .map(str::to_owned)
            .ok_or_else(|| Error::new("an explicit answer is required"));
    }
    if answer.chars().any(char::is_control) {
        return Err(Error::new("control characters are not accepted"));
    }
    Ok(answer.to_owned())
}
fn yes(label: &str, default: Option<bool>) -> Result<bool> {
    loop {
        match ask(label, default.map(|b| if b { "y" } else { "n" }))?
            .to_ascii_lowercase()
            .as_str()
        {
            "y" | "yes" => return Ok(true),
            "n" | "no" => return Ok(false),
            _ => println!("Answer y or n."),
        }
    }
}
pub fn install(args: &[&str]) -> Result<()> {
    let mut apply = false;
    let mut release_tag = None;
    let mut i = 0;
    while i < args.len() {
        match args[i] {
            "--apply" if !apply => apply = true,
            "--release" if i + 1 < args.len() && release_tag.is_none() => {
                i += 1;
                release_tag = Some(args[i]);
            }
            _ => {
                return Err(Error::new(
                    "installer accepts --apply and --release TAG only",
                ));
            }
        }
        i += 1;
    }
    if apply && release_tag.is_none() {
        return Err(Error::new(
            "--apply requires --release r-SEQUENCE; authenticate the chosen tag with assbox release verify first",
        ));
    }
    if let Some(tag) = release_tag {
        assbox_domain::release::ReleaseTag::parse(tag)?;
    }
    files::require_root()?;
    let c = Commands;
    let inv = probe::inventory(&c)?;
    println!(
        "Prepared-storage installation. Assbox will NOT partition, format, resize or repair disks."
    );
    println!(
        "Target and backup must be separate disks, neither containing the live installer. Optical ISO media are supported."
    );
    println!(
        "Detected architecture: {}. Firmware: {}. Live medium: {}",
        inv.architecture,
        inv.firmware,
        inv.live_media.source()
    );
    for disk in &inv.disks {
        println!(
            "{}",
            assbox_config::storage_summary::disk_summary("DISK", disk)
        );
    }
    for p in &inv.partitions {
        println!(
            "  {:20} {:7} {:7} MiB  parent={}  mounts={:?}",
            p.path,
            p.fs,
            p.bytes / (1024 * 1024),
            p.parent,
            p.mounts
        );
    }
    let root = ask("Prepared empty ext4 root partition", None)?;
    let esp = if inv.firmware == Firmware::Uefi {
        Some(ask("Existing FAT EFI System Partition", None)?)
    } else {
        None
    };
    let backup = ask("External backup partition (ext4/FAT/exFAT)", None)?;
    let hostname = Hostname::from_entropy(files::random_bytes::<6>()?);
    let hostname = Hostname::parse(&ask("Hostname", Some(hostname.as_str()))?)?;
    let timezone = c
        .text("timedatectl", &["show", "--property=Timezone", "--value"])
        .unwrap_or_else(|_| "UTC".to_owned());
    let timezone = ask("Local timezone", Some(timezone.trim()))?;
    if timezone != "UTC"
        && !c
            .text("timedatectl", &["list-timezones"])?
            .lines()
            .any(|line| line == timezone)
    {
        return Err(Error::new(
            "timezone is not in the installed timezone database",
        ));
    }
    let model = fs::read_to_string("/sys/class/dmi/id/product_name").unwrap_or_default();
    let recommended = if inv.architecture == Architecture::X86_64 {
        assbox_policy::recommended_platform(&model)
    } else {
        Platform::Generic
    };
    let platform: Platform = ask(
        "Platform: generic / apple-intel / macbookpro11-1 / macbookpro12-1",
        Some(recommended.as_str()),
    )?
    .parse()?;
    let application: Application = ask(
        "Application: none / chatgpt / opencode / openclaw",
        Some("none"),
    )?
    .parse()?;
    let presentation: Presentation = if application == Application::Chatgpt {
        println!("ChatGPT Remote uses the X11 graphical profile on Linux.");
        Presentation::X11
    } else {
        ask("Presentation: headless / wayland / x11", Some("headless"))?.parse()?
    };
    let network = probe::default_network(&c).unwrap_or_default();
    let wifi = assbox_policy::suggested_wifi(&network);
    if wifi.is_none() {
        println!("The active network is ambiguous/offline/tunneled; choose Wi-Fi explicitly.");
    }
    let devices = DevicePolicy {
        wifi: yes("Enable Wi-Fi?", wifi)?,
        audio: yes("Enable audio and microphone devices?", Some(false))?,
        camera: yes("Enable camera devices?", Some(false))?,
        bluetooth: yes("Enable Bluetooth?", Some(false))?,
        suspend: yes("Allow suspend?", Some(false))?,
    };
    let scale = if presentation == Presentation::Headless {
        1
    } else {
        let edids = probe::display_edids().unwrap_or_default();
        let suggestions: Vec<_> = edids
            .iter()
            .filter_map(|b| assbox_policy::suggested_scale(b))
            .collect();
        let suggested =
            if !suggestions.is_empty() && suggestions.iter().all(|s| *s == suggestions[0]) {
                suggestions[0]
            } else {
                1
            };
        ask("Display scale (1, 2 or 3)", Some(&suggested.to_string()))?
            .parse::<u8>()
            .map_err(|_| Error::new("invalid display scale"))?
    };
    let allow_unfree = yes(
        "Allow unfree nixpkgs packages machine-wide (required for ChatGPT, persists after switching applications)?",
        Some(false),
    )?;
    let key = ask(
        "Optional admin SSH public key (enter none for console-only access)",
        Some("none"),
    )?;
    let admin_ssh_key = if key == "none" { None } else { Some(key) };
    let choices = Choices {
        hostname,
        timezone,
        application,
        presentation,
        platform,
        devices,
        scale,
        allow_unfree,
        admin_ssh_key,
    };
    let request = InstallRequest {
        root,
        esp,
        backup,
        choices,
    };
    let plan = assbox_policy::plan_install(inv, request)?;
    println!(
        "\nPlan: {} | {} | {} | {} | {}",
        plan.request().choices.hostname.as_str(),
        plan.inventory().architecture,
        plan.boot(),
        application,
        presentation
    );
    println!(
        "{}",
        assbox_config::storage_summary::plan_storage_summary(&plan)?
    );
    println!(
        "Daily maintenance defaults to 18:00 local; successful changed updates are staged then rebooted after a warning."
    );
    println!(
        "USB input/network work normally. Removable storage is administrator-mounted, never automounted for workloads."
    );
    if !apply {
        println!(
            "Plan only: no filesystem checks, mounts or installation writes were performed. Run again with --apply to install."
        );
        return Ok(());
    }
    plan.revalidate(&probe::inventory(&c)?, &[])?;
    println!(
        "Confirm the physical disks again before proceeding:\n{}",
        assbox_config::storage_summary::plan_storage_summary(&plan)?
    );
    let phrase = assbox_config::storage_summary::confirmation_phrase(&plan)?;
    if ask(&format!("Type exactly: {phrase}"), None)? != phrase {
        return Err(Error::new(
            "confirmation did not match; no installation writes performed",
        ));
    }
    assbox_engine::install::apply(plan, release_tag)
}
