// SPDX-License-Identifier: GPL-3.0-or-later
//! User-facing worker planning and activation. No implicit agent selection.
use assbox_domain::{Components, Error, Result, worker::WorkerSpec};
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
    state: u32,
    uplinks: Vec<String>,
    offline: bool,
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
        state: 32,
        uplinks: Vec::new(),
        offline: false,
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
        if key != "--uplink" && !seen.insert(key) {
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
                r.state = number(value(i)?)?;
            }
            "--uplink" => {
                i += 1;
                r.uplinks.push(value(i)?.to_owned());
            }
            "--offline" => r.offline = true,
            "--allow-mutable-code" => r.mutable = true,
            "--allow-guest-sudo" => r.sudo = true,
            "--accept-unfree" => r.unfree = true,
            "--apply" => r.apply = true,
            _ => return Err(Error::new("unknown worker option; see assbox --help")),
        }
        i += 1;
    }
    if r.offline != r.uplinks.is_empty() {
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
        state_gib: request.state,
        uplinks: request.uplinks,
        offline: request.offline,
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
    let network_default = if host.uplinks.len() == 1 {
        host.uplinks[0].as_str()
    } else {
        "offline"
    };
    let network = ask("Uplink interface, or offline", network_default)?;
    let ram = ask("Worker memory in MiB", &memory.to_string())?;
    let state = ask("Persistent state in GiB (never auto-resized)", "32")?;
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
        ids,
        "--memory".to_owned(),
        ram,
        "--state-gib".to_owned(),
        state,
    ];
    if network == "offline" {
        args.push("--offline".to_owned());
    } else {
        args.extend(["--uplink".to_owned(), network]);
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
pub fn installation_spec(selected: Components, accept_unfree: bool) -> Result<WorkerSpec> {
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
    let components: Components = ids.parse()?;
    for c in components.iter().filter(|c| !c.code_notes().is_empty()) {
        println!("{c}: {}", c.code_notes());
    }
    let memory_mib = number(&ask("Worker memory MiB", &recommended.to_string())?)?;
    let vcpus = number(&ask(
        "Worker CPUs",
        &assbox_policy::worker::recommended_cpus(&host).to_string(),
    )?)?;
    let state_gib = number(&ask("Persistent worker state GiB", "32")?)?;
    println!(
        "Observed uplinks: {}. Review the target machine's interface names.",
        host.uplinks.join(", ")
    );
    let network = ask("Worker uplinks, comma-separated, or offline", "offline")?;
    let offline = network == "offline";
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
        uplinks: if offline {
            Vec::new()
        } else {
            network.split(',').map(str::to_owned).collect()
        },
        offline,
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
