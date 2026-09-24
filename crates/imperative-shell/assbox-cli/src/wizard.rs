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

fn ssh_access_prompt(enabled: bool, c: &Commands) -> Result<access::SshAccess> {
    if !enabled {
        return Ok(Default::default());
    }
    println!(
        "SSH accepts keys only. The exposure choice applies to both enabled SSH accounts. Tailscale requires console enrollment after boot; LAN can connect directly over a Parallels private network."
    );
    match ask("SSH exposure: tailscale / lan", Some("tailscale"))?.as_str() {
        "tailscale" => Ok(Default::default()),
        "lan" => {
            let links = c.capture("ip", &["-j", "link", "show"])?;
            let names = c.jq_fields(
                &links,
                r#".[] | select(.ifname != "lo") | .ifname + "\u0000""#,
            )?;
            println!("Observed interfaces: {}", names.join(", "));
            let interfaces = ask(
                "Interfaces admitting SSH, comma-separated (confirm target names)",
                None,
            )?
            .split(',')
            .map(|s| s.trim().to_owned())
            .collect();
            let sources = ask(
                "Allowed source CIDRs, comma-separated, or none for any source on those interfaces",
                Some("none"),
            )?;
            let source_cidrs = if sources == "none" {
                vec![]
            } else {
                sources.split(',').map(|s| s.trim().to_owned()).collect()
            };
            let access = access::SshAccess {
                exposure: access::SshExposure::Lan,
                interfaces,
                source_cidrs,
            };
            access.validate(true)?;
            Ok(access)
        }
        _ => Err(Error::new("choose tailscale or lan SSH exposure")),
    }
}

fn print_connection_summary(choices: &Choices) {
    if choices.admin_ssh_key.is_some() || choices.agent_ssh_key.is_some() {
        println!("{}", assbox_config::connection_guide(choices));
        if let Ok(addresses) = Commands.capture("ip", &["-j", "-4", "address", "show"])
            && let Ok(rows) = Commands.jq_fields(&addresses, r#".[] | .ifname as $interface | .addr_info[] | select(.scope == "global") | ($interface + ": " + .local + "\u0000")"#) {
            println!("Live environment IPv4 observations (not permanent installed addresses): {}", rows.join(", "));
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
        "Standalone: selected tools run directly here, including when another computer connects over SSH. Managed-worker: this system owns an isolated headless VM; only approved controller components stay outside it."
    );
    let mut managed = match ask(
        "Arrangement: standalone / managed-worker",
        Some("standalone"),
    )?
    .as_str()
    {
        "standalone" => false,
        "managed-worker" => true,
        _ => return Err(Error::new("choose standalone or managed-worker")),
    };
    println!(
        "Optional components: {}",
        Component::ALL
            .iter()
            .filter(|c| c.blocked().is_empty() && (!c.requires_worker() || c.controller_allowed()))
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
    if !managed && components.iter().any(Component::requires_worker) {
        println!("Selected sensitive desktop components require a managed worker.");
        if !yes("Switch to the managed-worker arrangement?", Some(false))? {
            return Err(Error::new(
                "select a managed worker or remove the sensitive desktop components",
            ));
        }
        managed = true;
    }
    let requested_worker = if managed {
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
            return Err(Error::new("managed-worker placement was not accepted"));
        }
        components = controller;
        Some(execution)
    } else {
        None
    };
    let happy_backends = crate::worker::happy_prompt(&mut components)?;
    let presentation: Presentation = ask(
        "Presentation: headless / wayland / x11",
        Some(if components.contains(Component::ChatgptDesktop) {
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
            "Graphical autostart IDs (chatgpt-desktop, claude-desktop, vscode, zed, chromium, opencode-attach, openclaw-dashboard; or none)",
            Some("none"),
        )?;
        if text == "none" {
            Vec::new()
        } else {
            text.split(',').map(str::to_owned).collect()
        }
    };
    let key = ask(
        "Optional administrator SSH public key, or none",
        Some("none"),
    )?;
    let admin_ssh_key = if key == "none" { None } else { Some(key) };
    let editor_ssh = components.contains(Component::VscodeRemoteHost)
        || components.contains(Component::ZedRemoteHost);
    let agent_ssh_key = if !managed
        && (editor_ssh
            || yes(
                "Allow an external controller/editor/terminal to connect to the workload account over SSH?",
                Some(false),
            )?) {
        Some(ask(
            "Workload SSH public key (unprivileged agent account; separate from administrator access)",
            None,
        )?)
    } else {
        None
    };
    let ssh_access = ssh_access_prompt(admin_ssh_key.is_some() || agent_ssh_key.is_some(), &c)?;
    let additional_packages = if managed {
        Default::default()
    } else {
        let text = ask(
            "Additional nixpkgs package attributes, comma-separated, or none",
            Some("none"),
        )?;
        if text == "none" {
            Default::default()
        } else {
            text.split(',')
                .map(|s| PackageName::parse(s.trim()))
                .collect::<Result<std::collections::BTreeSet<_>>>()?
        }
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
        ssh_access,
        additional_packages,
        worker,
        happy_backends,
    };
    print_connection_summary(&choices);
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
