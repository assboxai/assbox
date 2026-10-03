// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_system::{commands::Commands, files, probe};
use std::io::{self, IsTerminal, Write};

pub(crate) fn ask(label: &str, default: Option<&str>) -> Result<String> {
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
    answer_value(&answer, default)
}

fn answer_value(answer: &str, default: Option<&str>) -> Result<String> {
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
pub(crate) fn yes(label: &str, default: Option<bool>) -> Result<bool> {
    TerminalSelectionUi.yes(label, default)
}

trait SelectionUi {
    fn ask(&mut self, label: &str, default: Option<&str>) -> Result<String>;
    fn show(&mut self, text: &str);
    fn native_status(&mut self, app: Component, requested: &str) -> Result<(String, String)>;
    fn yes(&mut self, label: &str, default: Option<bool>) -> Result<bool> {
        loop {
            match self
                .ask(label, default.map(|b| if b { "y" } else { "n" }))?
                .to_ascii_lowercase()
                .as_str()
            {
                "y" | "yes" => return Ok(true),
                "n" | "no" => return Ok(false),
                _ => self.show("Answer y or n."),
            }
        }
    }
}

struct TerminalSelectionUi;
impl SelectionUi for TerminalSelectionUi {
    fn ask(&mut self, label: &str, default: Option<&str>) -> Result<String> {
        ask(label, default)
    }
    fn show(&mut self, text: &str) {
        println!("{text}");
    }
    fn native_status(&mut self, app: Component, requested: &str) -> Result<(String, String)> {
        super::user::native_policy_status(app, requested)
    }
}

fn ssh_access_prompt(enabled: bool, c: &Commands, tailscale: bool) -> Result<access::SshAccess> {
    if !enabled {
        return Ok(Default::default());
    }
    println!(
        "SSH accepts keys only. The exposure choice applies to both enabled SSH accounts. Tailscale requires console enrollment after boot; LAN can connect directly over a Parallels private network."
    );
    match ask(
        "SSH exposure: tailscale / lan",
        Some(if tailscale { "tailscale" } else { "lan" }),
    )?
    .as_str()
    {
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
pub(crate) fn instance_prompt(
    installed: bool,
) -> Result<assbox_policy::instances::ResolvedInstance> {
    selection_with_ui(&mut TerminalSelectionUi, installed)
}

fn selection_with_ui(
    ui: &mut impl SelectionUi,
    installed: bool,
) -> Result<assbox_policy::instances::ResolvedInstance> {
    use instances::{ComputerUse, Purpose};
    loop {
        ui.show("Purpose: Assistant / Coder / Kiosk / Custom. Type back in a branch to choose again. No authentication or enrollment occurs here.");
        let purpose: Purpose = ui
            .ask(
                "What will this Assbox primarily do? assistant / coder / kiosk / custom",
                None,
            )?
            .to_ascii_lowercase()
            .parse()?;
        let id = match purpose {
            Purpose::Assistant => {
                match ui
                    .ask("Assistant: openclaw / hermes / back", Some("openclaw"))?
                    .as_str()
                {
                    "openclaw" => "assistant-openclaw",
                    "hermes" => "assistant-hermes",
                    "back" => continue,
                    _ => return Err(Error::new("choose OpenClaw or Hermes")),
                }
            }
            Purpose::Coder => match ui
                .ask(
                    "Coder: happier / codex / claude / more / ssh / desktop / back",
                    Some("happier"),
                )?
                .as_str()
            {
                "happier" => "coder-happier",
                "codex" => "coder-codex-ssh",
                "ssh" => "coder-ssh",
                "back" => continue,
                "claude" => match ui
                    .ask("Claude access: relay / ssh / back", Some("relay"))?
                    .as_str()
                {
                    "relay" => "coder-claude-native",
                    "ssh" => "coder-claude-ssh",
                    "back" => continue,
                    _ => return Err(Error::new("choose relay or ssh")),
                },
                "more" => match ui
                    .ask(
                        "Native route: cursor / antigravity / opencode / back",
                        Some("cursor"),
                    )?
                    .as_str()
                {
                    "cursor" => "coder-cursor",
                    "antigravity" => "coder-antigravity",
                    "opencode" => "coder-opencode",
                    "back" => continue,
                    _ => return Err(Error::new("unknown native route")),
                },
                "desktop" => "kiosk-native",
                _ => return Err(Error::new("unknown Coder route")),
            },
            Purpose::Kiosk => match ui
                .ask("Kiosk: native / web / back", Some("native"))?
                .as_str()
            {
                "native" => "kiosk-native",
                "web" => "kiosk-web",
                "back" => continue,
                _ => return Err(Error::new("choose native or web kiosk")),
            },
            Purpose::Custom => "custom",
        };
        let preset = instances::Preset::find(id)?;
        let (transport, controller) = match id {
            "coder-happier" => ("Happier provider connection", "external Happier client"),
            "coder-codex-ssh" => (
                "SSH; ChatGPT owns its app-server channel",
                "external ChatGPT Desktop (Mac to Parallels is supported topology)",
            ),
            "coder-claude-ssh" => (
                "SSH; native helper behavior requires qualification",
                "external Claude Desktop",
            ),
            "coder-claude-native" => (
                "Claude native Remote Control relay",
                "external Claude client",
            ),
            "coder-cursor" => (
                "Cursor native self-hosted worker connection",
                "external Cursor client",
            ),
            "coder-antigravity" => (
                "reviewed Antigravity foreground contract; otherwise staged",
                "external Antigravity client",
            ),
            "coder-opencode" => (
                "OpenCode loopback server; private access selected separately",
                "external browser/client",
            ),
            "coder-ssh" => ("plain SSH", "external terminal/editor"),
            "kiosk-native" => (
                "native client; optional independently qualified worker SSH",
                "local native kiosk",
            ),
            "kiosk-web" => ("browser HTTPS", "local browser kiosk"),
            "assistant-openclaw" => ("OpenClaw gateway", "selected external channel/client"),
            "assistant-hermes" => ("Hermes gateway", "selected external channel/client"),
            _ => ("explicit component choices", "chosen by the owner"),
        };
        ui.show(&format!(
            "Transport: {transport} | controller: {controller}"
        ));
        ui.show("Installation: requested, not applied | authentication: unobserved | integration qualification: not established by preset selection");
        if purpose == Purpose::Custom {
            ui.show("Advanced experimental Codex relay is available as codex,codex-relay. It remains staged without a reviewed immutable foreground contract; it is separate from the normal Codex SSH route.");
        }
        let defaults = assbox_policy::instances::resolve(id, None, Components::default(), false)?;
        ui.show(&format!("Initially checked components: {}", defaults.host));
        ui.show("Curated agent tools can be removed individually. Installing a CLI does not authenticate it or qualify every frontend adapter.");
        let selected_text = ui.ask(
            "Selected components, comma-separated; remove unwanted entries, none, or back",
            Some(&defaults.host.to_string()),
        )?;
        if selected_text == "back" {
            continue;
        }
        let mut selected: Components = selected_text.parse()?;
        if !id.starts_with("kiosk-")
            && id != "coder-happier"
            && purpose != Purpose::Assistant
            && ui.yes("Add all eight curated coding agents?", Some(false))?
        {
            for c in [
                Component::Codex,
                Component::ClaudeCode,
                Component::AntigravityCli,
                Component::CursorAgent,
                Component::Grok,
                Component::Opencode,
                Component::Pi,
                Component::Omp,
            ] {
                selected.insert(c);
            }
        }
        let mut exclusions = Components::default();
        for c in defaults.host.iter() {
            if !selected.contains(c) {
                exclusions.insert(c);
            }
        }
        let expanded = selected.with_dependencies();
        if expanded != selected {
            ui.show(&format!("Required dependencies: {expanded}"));
            if !ui.yes("Accept the required dependencies?", Some(false))? {
                continue;
            }
            for c in expanded.iter() {
                exclusions.remove(c);
            }
            selected = expanded;
        }
        let protected = id == "kiosk-native"
            && ui.yes(
                "Select protected local Code in the managed worker?",
                Some(purpose == Purpose::Coder),
            )?;
        let split_custom = purpose == Purpose::Custom
            && ui.yes(
                "Use a managed worker for execution components?",
                Some(false),
            )?;
        let host_selection = if split_custom {
            worker::controller_components(selected)
        } else {
            selected
        };
        let mut resolved =
            assbox_policy::instances::resolve(id, Some(host_selection), exclusions, protected)?;
        if split_custom {
            for c in selected.iter().filter(|c| !c.controller_allowed()) {
                if !c.worker_allowed() {
                    return Err(Error::new("component cannot run in the headless worker"));
                }
                resolved.worker.insert(c);
            }
        }
        resolved.config.execution_in_worker = resolved.worker != Components::default();
        resolved.presentation = ui
            .ask(
                "Presentation: headless / x11 / wayland",
                Some(preset.presentation.as_str()),
            )?
            .parse()?;
        resolved.config.tailscale = ui.yes(
            "Install Tailscale support (enrollment happens separately)?",
            Some(true),
        )?;
        resolved.config.egress = ui
            .ask(
                "Execution egress: internet / normal / offline",
                Some("internet"),
            )?
            .parse()?;
        resolved.config.computer_use = ui
            .ask(
                "Execution computer use: none / browser / virtual-desktop",
                Some("none"),
            )?
            .parse()?;
        if resolved.config.computer_use != ComputerUse::None
            && (selected.contains(Component::ChatgptDesktop)
                || selected.contains(Component::ClaudeDesktop))
            && resolved.worker == Components::default()
        {
            return Err(Error::new(
                "autonomous computer use needs an execution-side worker or standalone instance",
            ));
        }
        if selected.contains(Component::HermesDashboard) {
            resolved.config.hermes_tunnel_only = ui.yes(
                "Advanced: use only an SSH tunnel, without claiming native dashboard authentication?",
                Some(false),
            )?;
            if !resolved.config.hermes_tunnel_only {
                resolved.config.hermes_public_url = ui.ask(
                    "Exact private HTTPS dashboard URL (for example https://assbox.example.ts.net/)",
                    None,
                )?;
                if resolved.config.tailscale {
                    resolved.config.dashboard_serve = ui.yes(
                        "Approve root-managed private Tailscale Serve for this exact dashboard URL?",
                        Some(false),
                    )?;
                }
            }
            resolved.config.validate()?;
        }
        if id == "kiosk-web" {
            let apps = ui.ask(
                "Web kiosk sites: chatgpt,claude (remove either if desired)",
                Some("chatgpt,claude"),
            )?;
            resolved.config.web_apps = apps.split(',').map(|a| a.trim().to_owned()).collect();
            resolved.config.validate()?;
        }
        if resolved.host.contains(Component::ChatgptDesktop)
            || resolved.host.contains(Component::ClaudeDesktop)
        {
            ui.show("Native policy: None requested unless protected Code is selected. Each selected app remains inactive until its exact release/account/platform policy contract is verified. A worker does not override this gate. Web mode is a separate explicit choice.");
            for app in [Component::ChatgptDesktop, Component::ClaudeDesktop]
                .into_iter()
                .filter(|app| resolved.host.contains(*app))
            {
                let mode = if protected { "managed-worker" } else { "none" };
                let (state, reason) = if installed {
                    ui.native_status(app, mode).unwrap_or_else(|_| ("pending".into(), "installed policy observations are unavailable; activation remains gated".into()))
                } else {
                    ("pending".into(), "exact installed client/account/platform must be qualified after installation".into())
                };
                ui.show(&format!(
                    "{app}: requested {mode} | gate {state} | {reason}"
                ));
            }
            match ui
                .ask(
                    "Native policy action: stage / back (deselect apps after Back)",
                    Some("stage"),
                )?
                .to_ascii_lowercase()
                .as_str()
            {
                "stage" | "y" | "yes" => {}
                "back" | "n" | "no" => continue,
                _ => {
                    return Err(Error::new(
                        "choose stage or back; native activation is never granted by this screen",
                    ));
                }
            }
        }
        ui.show(&format!(
            "Host: {} | worker: {} | presentation: {} | setup/auth/integration qualification remains separate",
            resolved.host, resolved.worker, resolved.presentation
        ));
        ui.show(&format!(
            "Execution location: {} | computer use: {} | egress: {} | Tailscale support: {} (enrollment unobserved here)",
            if resolved.config.execution_in_worker {
                "managed worker"
            } else if id.starts_with("kiosk-") {
                "no local execution requested"
            } else {
                "standalone host"
            },
            resolved.config.computer_use.as_str(),
            resolved.config.egress,
            resolved.config.tailscale
        ));
        if ui.yes("Use this selection?", Some(true))? {
            return Ok(resolved);
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
    let resolved = instance_prompt(false)?;
    let components = resolved.host;
    let managed = resolved.worker != Components::default();
    let presentation = resolved.presentation;
    let requested_worker = managed.then_some(resolved.worker);
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
    let mutable = components.iter().any(|c| c.mutable_code())
        || resolved.worker.iter().any(|c| c.mutable_code());
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
        .map(|selected| {
            crate::worker::installation_spec(selected, allow_unfree, resolved.config.egress)
        })
        .transpose()?;
    let autostart = if presentation == Presentation::Headless {
        Vec::new()
    } else {
        let native_launchers = components
            .iter()
            .filter(|c| matches!(c, Component::ChatgptDesktop | Component::ClaudeDesktop))
            .map(|c| c.as_str())
            .collect::<Vec<_>>()
            .join(",");
        let text = ask(
            "Graphical autostart IDs (chatgpt-desktop, claude-desktop, vscode, zed, chromium, opencode-attach, openclaw-dashboard; or none)",
            Some(
                if resolved.config.purpose == instances::Purpose::Kiosk
                    && resolved.config.web_apps.is_empty()
                {
                    native_launchers.as_str()
                } else {
                    "none"
                },
            ),
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
                Some(resolved.workload_ssh),
            )?) {
        Some(ask(
            "Workload SSH public key (unprivileged agent account; separate from administrator access)",
            None,
        )?)
    } else {
        None
    };
    if resolved.workload_ssh && agent_ssh_key.is_none() {
        return Err(Error::new(
            "this SSH Coder route requires a workload public key",
        ));
    }
    let ssh_access = ssh_access_prompt(
        admin_ssh_key.is_some() || agent_ssh_key.is_some(),
        &c,
        resolved.config.tailscale,
    )?;
    if (admin_ssh_key.is_some() || agent_ssh_key.is_some())
        && ssh_access.exposure == access::SshExposure::Tailscale
        && !resolved.config.tailscale
    {
        return Err(Error::new(
            "select LAN SSH when Tailscale support is deselected",
        ));
    }

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
        instance: resolved.config,
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

pub fn configure(apply: bool) -> Result<()> {
    files::require_root()?;
    println!("Current effective configuration:");
    Commands.run("nix", &["eval","--json","--no-update-lock-file","--no-write-lock-file","path:/etc/nixos#nixosConfigurations.assbox.config.assbox","--apply","c: { inherit (c) instance selectedComponents presentation; worker = c.worker.enable; }"])?;
    let resolved = instance_prompt(true)?;
    let unfree = yes("Accept proprietary packages if required?", Some(false))?;
    let mutable = (resolved.host.iter().any(|c| c.mutable_code())
        || resolved.worker.iter().any(|c| c.mutable_code()))
        && yes(
            "Accept the disclosed client-managed helpers for the selected native clients?",
            Some(false),
        )?;
    assbox_engine::manage::instance_configure(&resolved, unfree, mutable, apply)
}

#[cfg(test)]
mod selection_tests;
