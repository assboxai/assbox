// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_system::{commands::Commands, files, probe};
use std::io::{self, IsTerminal, Write};

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
    println!(
        "Hardware: vendor={:?}, model={:?}",
        inv.hardware.vendor, inv.hardware.model
    );
    for device in &inv.hardware.pci_network {
        println!(
            "PCI network controller {}: {:04x}:{:04x}",
            device.slot, device.vendor, device.device
        );
    }
    for interface in &inv.hardware.wireless {
        println!(
            "Wireless interface {:?}: driver={:?}, in-tree prerequisite={}",
            interface.name,
            interface.driver,
            assbox_policy::hardware::usable_wifi(interface)
        );
    }
    if assbox_policy::hardware::has_bcm4360(&inv.hardware) {
        println!(
            "BCM4360 built-in Wi-Fi is unsupported. Use Ethernet or a supported external Wi-Fi adapter; Assbox does not install the insecure wl driver."
        );
    }
    let recommended = if inv.architecture == Architecture::X86_64 {
        assbox_policy::recommended_platform(&inv.hardware.model)
    } else {
        Platform::Generic
    };
    assbox_policy::hardware::validate_install_hardware(
        inv.architecture,
        &inv.hardware,
        recommended,
        false,
    )?;
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
    let platform: Platform = ask(
        "Platform: generic / macbookpro11-1 / macbookpro12-1",
        Some(recommended.as_str()),
    )?
    .parse()?;
    println!(
        "Optional components: {}",
        Component::ALL
            .iter()
            .map(|c| c.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );
    let mut components: Components =
        ask("Components (comma-separated IDs, or none)", Some("none"))?.parse()?;
    let expanded = components.with_dependencies();
    if expanded != components {
        println!("Required selection: {expanded}");
        if !yes("Include these required components?", Some(false))? {
            return Err(Error::new("component dependencies were not accepted"));
        }
        components = expanded;
    }
    let requested_worker = if components.iter().any(Component::requires_worker) {
        if components
            .iter()
            .any(|c| c.requires_worker() && !c.controller_allowed())
        {
            return Err(Error::new(
                "this sensitive desktop has no qualified Assbox controller adapter; do not combine it with controller agent execution",
            ));
        }
        let controller = assbox_domain::worker::controller_components(components);
        let mut execution = Components::default();
        for component in components.iter().filter(|c| !c.controller_allowed()) {
            if !component.worker_allowed() {
                return Err(Error::new("unqualified component on the controller"));
            }
            execution.insert(component);
        }
        // The proposed dependency is displayed and explicitly accepted below.
        if controller.contains(Component::ChatgptDesktop) {
            execution.insert(Component::Codex);
        }
        println!("Proposed controller: {controller}. Proposed worker: {execution}.");
        if !yes(
            "Use this managed worker-only execution layout?",
            Some(false),
        )? {
            return Err(Error::new(
                "ChatGPT controller requires worker isolation; no controller fallback",
            ));
        }
        components = controller;
        Some(execution)
    } else {
        None
    };
    let happy_backends = if components.contains(Component::HappyRemote) {
        let backends: Components = ask(
            "Happy backends (codex, claude-code, or both comma-separated)",
            None,
        )?
        .parse()?;
        if backends == Components::default()
            || backends
                .iter()
                .any(|id| !matches!(id, Component::Codex | Component::ClaudeCode))
        {
            return Err(Error::new("select at least one supported Happy backend"));
        }
        for backend in backends.iter() {
            components.insert(backend);
        }
        println!("Complete selection including your Happy backends: {components}");
        backends
    } else {
        Components::default()
    };
    let presentation: Presentation = ask(
        "Presentation: headless / wayland / x11",
        Some(if requested_worker.is_some() {
            "x11"
        } else {
            "headless"
        }),
    )?
    .parse()?;
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
        "Allow proprietary packages machine-wide (required by some components; persists after changing the selection)?",
        Some(false),
    )?;
    for component in components.iter().filter(|c| !c.code_notes().is_empty()) {
        println!("{component}: {}", component.code_notes());
    }
    let mutable = components.iter().any(|c| c.mutable_code());
    if mutable {
        println!(
            "Selected desktop components may download executable helpers. Worker selection does not automatically disable a desktop application's built-in controller-local tools."
        );
    }
    let allow_mutable_code = mutable
        && yes(
            "Accept these provider/client-managed executable downloads?",
            Some(false),
        )?;
    if mutable && !allow_mutable_code {
        return Err(Error::new("mutable helper provisioning was not accepted"));
    }
    let worker = requested_worker
        .map(|selected| crate::worker::installation_spec(selected, allow_unfree))
        .transpose()?;
    let autostart = if presentation == Presentation::Headless {
        Vec::new()
    } else {
        let text = ask(
            "Graphical autostart IDs (chatgpt-desktop, claude-desktop, vscode, zed, opencode-attach, openclaw-dashboard; or none)",
            Some("none"),
        )?;
        if text == "none" {
            Vec::new()
        } else {
            text.split(',').map(str::to_owned).collect()
        }
    };
    let key = ask(
        "Optional admin SSH public key (enables Tailscale-only SSH; owner must log in from console; enter none for console-only access)",
        Some("none"),
    )?;
    let admin_ssh_key = if key == "none" { None } else { Some(key) };
    let agent_ssh_key = if components.contains(Component::VscodeRemoteHost)
        || components.contains(Component::ZedRemoteHost)
    {
        Some(ask(
            "Agent SSH public key for remote editors (separate from admin access; enables Tailscale-only SSH and requires console login)",
            None,
        )?)
    } else {
        None
    };
    let choices = Choices {
        hostname,
        timezone,
        components,
        presentation,
        platform,
        devices,
        scale,
        allow_unfree,
        allow_mutable_code,
        autostart,
        admin_ssh_key,
        agent_ssh_key,
        worker,
        happy_backends,
    };
    let request = InstallRequest {
        root,
        esp,
        backup,
        choices,
    };
    let plan = assbox_policy::plan_install(inv, request)?;
    if let Some(spec) = &plan.request().choices.worker {
        let mut hardware = assbox_system::worker::hardware(&c)?;
        hardware.free_gib = plan.root().bytes / (1024 * 1024 * 1024);
        hardware.existing_state_gib = None;
        assbox_policy::worker::validate_host_budget(spec, &hardware)?;
        println!(
            "Worker: {} | {} MiB | {} CPUs | persistent state {} GiB",
            spec.components,
            spec.memory_mib,
            spec.vcpus,
            if spec.auto_state {
                "automatic (resolved after artifact build)".to_owned()
            } else {
                spec.state_gib.to_string()
            }
        );
    }
    println!(
        "\nPlan: {} | {} | {} | {} | {}",
        plan.request().choices.hostname.as_str(),
        plan.inventory().architecture,
        plan.boot(),
        components,
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
    println!(
        "After preflight and backup verification, Assbox builds on the selected Linux root. A failed build can leave an incomplete installation. Bootloader activation follows validation of the built system."
    );
    let phrase = assbox_config::storage_summary::confirmation_phrase(&plan)?;
    if ask(&format!("Type exactly: {phrase}"), None)? != phrase {
        return Err(Error::new(
            "confirmation did not match; no installation writes performed",
        ));
    }
    assbox_engine::install::apply(plan, release_tag)
}
