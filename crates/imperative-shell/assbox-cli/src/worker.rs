// SPDX-License-Identifier: GPL-3.0-or-later
//! User-facing worker planning and activation. No implicit agent selection.
use assbox_domain::{
    Components, Error, Result,
    worker::{WorkerNetwork, WorkerSpec},
};
use assbox_engine::manage;
use assbox_system::{commands::Commands, files, worker as system};
use std::{
    collections::BTreeSet,
    io::{self, Write},
};

#[derive(Debug)]
struct Request {
    components: Components,

    memory: Option<u32>,
    cpus: Option<u32>,
    state: Option<u32>,
    uplinks: Vec<String>,
    network: WorkerNetwork,
    nameservers: Vec<String>,
    mutable: bool,
    sudo: bool,
    unfree: bool,
    apply: bool,
}

fn number(value: &str) -> Result<u32> {
    value
        .parse()
        .map_err(|_| Error::new("expected an unsigned integer"))
}
fn parse(args: &[&str]) -> Result<Request> {
    let (ids, options) = args
        .split_first()
        .ok_or_else(|| Error::new("worker configure requires explicit component IDs"))?;
    let mut r = Request {
        components: ids.parse()?,

        memory: None,
        cpus: None,
        state: None,
        uplinks: Vec::new(),
        network: WorkerNetwork::Internet,
        nameservers: vec![],
        mutable: false,
        sudo: false,
        unfree: false,
        apply: false,
    };
    if r.components == Components::default() {
        return Err(Error::new(
            "use worker disable instead of an empty component set",
        ));
    }
    let mut seen = BTreeSet::new();
    let mut i = 0;
    while i < options.len() {
        let key = options[i];
        if !matches!(key, "--uplink" | "--dns") && !seen.insert(key) {
            return Err(Error::new("duplicate worker option"));
        }
        let value = |offset: usize| {
            options
                .get(offset)
                .copied()
                .ok_or_else(|| Error::new("missing worker option value"))
        };
        match key {
            "--memory" => {
                i += 1;
                r.memory = if value(i)? == "auto" {
                    None
                } else {
                    Some(number(value(i)?)?)
                };
            }
            "--cpus" => {
                i += 1;
                r.cpus = Some(number(value(i)?)?);
            }
            "--state-gib" => {
                i += 1;
                r.state = if value(i)? == "auto" {
                    None
                } else {
                    Some(number(value(i)?)?)
                };
            }
            "--uplink" => {
                i += 1;
                r.uplinks.push(value(i)?.to_owned());
            }
            "--offline" => r.network = WorkerNetwork::Offline,
            "--network" => {
                i += 1;
                r.network = value(i)?.parse()?;
            }
            "--dns" => {
                i += 1;
                r.nameservers.push(value(i)?.to_owned());
            }
            "--allow-mutable-code" => r.mutable = true,
            "--allow-guest-sudo" => r.sudo = true,
            "--accept-unfree" => r.unfree = true,
            "--apply" => r.apply = true,
            _ => return Err(Error::new("unknown worker option; see assbox --help")),
        }
        i += 1;
    }
    if seen.contains("--offline") && seen.contains("--network") {
        return Err(Error::new("--offline and --network cannot be combined"));
    }
    if r.nameservers.is_empty() {
        r.nameservers = r.network.default_dns();
    }
    if (r.network == WorkerNetwork::Offline) != r.uplinks.is_empty() {
        return Err(Error::new("choose --offline or explicit --uplink NAME"));
    }
    Ok(r)
}

fn configure(request: Request) -> Result<()> {
    files::require_root()?;
    let host = system::hardware(&Commands)?;
    let mut mutable_components = Components::default();
    if request.mutable {
        for component in request.components.iter().filter(|c| c.mutable_code()) {
            mutable_components.insert(component);
        }
    }
    let spec = WorkerSpec {
        components: request.components,

        mutable_components,
        memory_mib: match request.memory {
            Some(m) => m,
            None => assbox_policy::worker::recommended_memory(&host)?,
        },
        vcpus: request
            .cpus
            .unwrap_or_else(|| assbox_policy::worker::recommended_cpus(&host)),
        state_gib: request.state.or(host.existing_state_gib).unwrap_or(8),
        auto_state: request.state.is_none() && host.existing_state_gib.is_none(),
        uplinks: request.uplinks,
        network: request.network,
        nameservers: request.nameservers,
        guest_sudo: request.sudo,
    };
    manage::worker_configure(Some(&spec), request.unfree, request.apply)
}

fn recommend() -> Result<()> {
    let host = system::hardware(&Commands)?;
    println!(
        "Physical RAM: {} MiB | available CPUs: {} | worker filesystem free: {} GiB",
        host.memory_mib, host.cpus, host.free_gib
    );
    println!("Usable KVM for this process: {}", host.kvm_available);
    println!(
        "Observed default-route interfaces (review before selecting): {}",
        host.uplinks.join(", ")
    );
    match assbox_policy::worker::recommended_memory(&host) {
        Ok(memory) => println!(
            "Suggested worker: {memory} MiB, {} CPUs. No agents, uplinks or execution mode were selected.",
            assbox_policy::worker::recommended_cpus(&host)
        ),
        Err(e) => println!(
            "VM recommendation unavailable: {e}. A non-root probe can fail because of device permissions; rerun with sudo."
        ),
    }
    println!(
        "Allow space for persistent state, a fully dirtied root, retained image generations and transient builds; free space is not an image-size forecast."
    );
    Ok(())
}

fn ask(label: &str, default: &str) -> Result<String> {
    print!("{label} [{default}]: ");
    io::stdout()
        .flush()
        .map_err(|e| Error::new(e.to_string()))?;
    let mut text = String::new();
    if io::stdin()
        .read_line(&mut text)
        .map_err(|e| Error::new(e.to_string()))?
        == 0
    {
        return Err(Error::new("worker setup input closed"));
    }
    let text = text.trim();
    Ok(if text.is_empty() {
        default.to_owned()
    } else {
        text.to_owned()
    })
}
fn network_prompt(
    observed: &[String],
    selected: Option<WorkerNetwork>,
) -> Result<(WorkerNetwork, Vec<String>, Vec<String>)> {
    println!(
        "Worker IPv4 networking: normal = internet and LAN; internet = public destinations only; offline = no external access. Controller services and unsolicited inbound traffic remain blocked."
    );
    let network = match selected {
        Some(network) => {
            println!("Worker egress selected in the purpose flow: {network}");
            network
        }
        None => ask("Choose normal / internet / offline (required)", "")?.parse()?,
    };
    if network == WorkerNetwork::Offline {
        return Ok((network, vec![], vec![]));
    }
    println!(
        "Observed uplinks: {}. Confirm interface names for the installed system.",
        observed.join(",")
    );
    let suggested = if observed.len() == 1 {
        observed[0].as_str()
    } else {
        ""
    };
    let uplinks = ask("Worker uplinks, comma-separated", suggested)?
        .split(',')
        .map(str::to_owned)
        .collect();
    let nameservers = ask(
        "Worker IPv4 DNS resolvers, comma-separated",
        "1.1.1.1,9.9.9.9",
    )?
    .split(',')
    .map(str::to_owned)
    .collect();
    Ok((network, uplinks, nameservers))
}

pub(crate) fn accept_dependencies(components: Components) -> Result<Components> {
    let expanded = components.with_dependencies();
    if expanded != components {
        println!("Required selection: {expanded}");
        if ask("Include these dependencies? yes/no", "no")? != "yes" {
            return Err(Error::new("component dependencies were not accepted"));
        }
    }
    Ok(expanded)
}

fn setup() -> Result<()> {
    files::require_root()?;
    recommend()?;
    let host = system::hardware(&Commands)?;
    let memory = assbox_policy::worker::recommended_memory(&host)?;
    let ids = ask("Worker component IDs, comma-separated", "none")?;
    if ids == "none" {
        println!("No worker configured.");
        return Ok(());
    }
    let components = accept_dependencies(ids.parse()?)?;
    let (network, uplinks, nameservers) = network_prompt(&host.uplinks, None)?;
    let ram = ask("Worker memory in MiB", &memory.to_string())?;
    let state = ask(
        "Persistent state GiB: auto or capacity (existing disks retained)",
        "auto",
    )?;
    let unfree = ask("Allow proprietary packages machine-wide? yes/no", "no")?;
    let mutable = ask(
        "Allow provider-managed downloads for selected components? yes/no",
        "no",
    )?;
    for answer in [&unfree, &mutable] {
        if !matches!(answer.as_str(), "yes" | "no") {
            return Err(Error::new("answer yes or no"));
        }
    }
    let mut args = vec![
        components.to_string(),
        "--memory".to_owned(),
        ram,
        "--state-gib".to_owned(),
        state,
    ];

    args.extend(["--network".to_owned(), network.to_string()]);
    for uplink in uplinks {
        args.extend(["--uplink".to_owned(), uplink]);
    }
    for resolver in nameservers {
        args.extend(["--dns".to_owned(), resolver]);
    }
    if unfree == "yes" {
        args.push("--accept-unfree".to_owned());
    }
    if mutable == "yes" {
        args.push("--allow-mutable-code".to_owned());
    }
    configure(parse(&args.iter().map(String::as_str).collect::<Vec<_>>())?)?;
    if ask("Build and stage this plan for reboot? yes/no", "no")? == "yes" {
        args.push("--apply".to_owned());
        configure(parse(&args.iter().map(String::as_str).collect::<Vec<_>>())?)?;
    }
    Ok(())
}

/// First installation defines the guest as part of the OUTER configuration.
/// It never invokes a second installer or creates an independent update channel.
pub fn installation_spec(
    selected: Components,
    accept_unfree: bool,
    egress: WorkerNetwork,
) -> Result<WorkerSpec> {
    let host = system::hardware(&Commands)?;
    let recommended = assbox_policy::worker::recommended_memory(&host)?;
    println!(
        "The controller owns one managed KVM worker. All repositories and development credentials belong in that worker."
    );
    println!(
        "Recommended Git access: a fine-grained PAT for selected staging repositories only. Never enter a PAT in this installer or in Nix."
    );
    let ids = ask(
        "Explicit worker component IDs (Codex is required for ChatGPT)",
        &selected.to_string(),
    )?;
    let components = accept_dependencies(ids.parse()?)?;
    for c in components.iter().filter(|c| !c.code_notes().is_empty()) {
        println!("{c}: {}", c.code_notes());
    }
    let recommended_cpus = assbox_policy::worker::recommended_cpus(&host);
    println!(
        "Recommended resources: {recommended} MiB RAM, {recommended_cpus} CPUs, automatic persistent capacity after building the system."
    );
    let customize = match ask("Customize worker resources? yes/no", "no")?.as_str() {
        "yes" => true,
        "no" => false,
        _ => return Err(Error::new("answer yes or no")),
    };
    let memory_mib = if customize {
        number(&ask("Worker memory MiB", &recommended.to_string())?)?
    } else {
        recommended
    };
    let vcpus = if customize {
        number(&ask("Worker CPUs", &recommended_cpus.to_string())?)?
    } else {
        recommended_cpus
    };
    let state = if customize {
        ask("Persistent worker state GiB: auto or capacity", "auto")?
    } else {
        "auto".to_owned()
    };
    let auto_state = state == "auto";
    let state_gib = if auto_state { 8 } else { number(&state)? };
    let (network, uplinks, nameservers) = network_prompt(&host.uplinks, Some(egress))?;
    let mut mutable_components = Components::default();
    for c in components.iter().filter(|c| c.mutable_code()) {
        if ask(
            &format!("Allow provider-managed executable downloads for {c}? yes/no"),
            "no",
        )? != "yes"
        {
            return Err(Error::new("worker mutable-code consent was not accepted"));
        }
        mutable_components.insert(c);
    }
    let spec = WorkerSpec {
        components,

        mutable_components,
        memory_mib,
        vcpus,
        state_gib,
        auto_state,
        uplinks,
        network,
        nameservers,
        guest_sudo: false,
    };
    spec.validate(accept_unfree)?;
    // RAM/KVM/capacity checks are repeated against target storage in the wizard;
    // live-media free space must not be mistaken for target root free space.
    if u64::from(memory_mib) + 3072 > host.memory_mib || vcpus > host.cpus {
        return Err(Error::new(
            "worker resources exceed observed hardware budget",
        ));
    }
    Ok(spec)
}

pub fn run(args: &[&str]) -> Result<()> {
    match args {
        ["recommend"] => recommend(),
        ["setup"] => setup(),
        ["configure", rest @ ..] => configure(parse(rest)?),
        ["disable"] => manage::worker_configure(None, false, false),
        ["disable", "--apply"] => manage::worker_configure(None, false, true),
        [
            action @ ("status" | "doctor" | "check" | "start" | "stop" | "setup-ssh" | "login"
            | "shell"),
        ] => system::run(action),
        _ => Err(Error::new("unknown worker operation; see assbox --help")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_network_flags_keep_their_meaning() {
        assert_eq!(
            parse(&["codex", "--uplink", "eth0"]).unwrap().network,
            WorkerNetwork::Internet
        );
        assert_eq!(
            parse(&["codex", "--offline"]).unwrap().network,
            WorkerNetwork::Offline
        );
        let normal = parse(&[
            "codex",
            "--network",
            "normal",
            "--uplink",
            "eth0",
            "--dns",
            "192.168.1.1",
        ])
        .unwrap();
        assert_eq!(normal.network, WorkerNetwork::Normal);
        assert_eq!(normal.nameservers, ["192.168.1.1"]);
        assert!(parse(&["codex", "--offline", "--network", "normal"]).is_err());
    }
    #[test]
    fn options_are_explicit_and_plan_is_default() {
        let r = parse(&["codex", "--offline", "--memory", "auto"]).unwrap();
        assert!(!r.apply && !r.sudo && !r.unfree && !r.mutable);
        assert!(r.memory.is_none());
        assert_eq!(r.components.to_string(), "codex");
    }
    #[test]
    fn invalid_options_do_not_start_effects() {
        for args in [
            vec![],
            vec!["none", "--offline"],
            vec!["codex"],
            vec!["codex", "--offline", "--uplink", "eth0"],
            vec!["codex", "--offline", "--apply", "--apply"],
            vec!["codex", "--offline", "--memory"],
            vec!["codex", "--offline", "--force"],
            vec!["codex", "--offline", "--machine", "tcg"],
        ] {
            assert!(parse(&args).is_err(), "{args:?}");
        }
        assert!(run(&["unknown"]).is_err());
    }
}
