// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_policy::{
    MaintenanceAction, Phase, RebootDecision, Recovery, reboot_decision,
    recovery_after_interruption,
};
use assbox_system::{
    commands::{Commands, valid_store_system},
    files::{self, Lock, io},
    probe,
};
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
    thread,
    time::Duration,
};

const CONFIG: &str = "/etc/nixos";
const STATE: &str = "/var/lib/assbox";
const TXN: &str = "/var/lib/assbox/transaction";
const PROFILE: &str = "/nix/var/nix/profiles/system";
const PENDING: &str = "/var/lib/assbox/pending-reboot";
const BOOT_ACCEPTED: &str = "/var/lib/assbox/boot-acceptance";

fn lock() -> Result<Lock> {
    files::require_root()?;
    files::create_private(Path::new(STATE))?;
    files::trusted_dir(Path::new(CONFIG))?;
    Lock::acquire(Path::new(STATE).join("operation.lock").as_path())
}
fn reference(path: &Path) -> Result<String> {
    Ok(format!("path:{}", files::path_text(path)?))
}
fn marker(name: &str) -> PathBuf {
    Path::new(TXN).join(name)
}
fn journal(phase: Phase) -> Result<()> {
    files::atomic_write(&marker("phase"), phase.as_str().as_bytes(), 0o600)?;
    #[cfg(test)]
    crate::acceptance::checkpoint(&format!("manage-{}", phase.as_str()))?;
    Ok(())
}
fn remove_txn() -> Result<()> {
    #[cfg(test)]
    crate::acceptance::checkpoint("manage-pre-retire")?;
    let retired = files::retire_directory(Path::new(TXN))?;
    #[cfg(test)]
    crate::acceptance::checkpoint("manage-retired")?;
    files::remove_retired_directory(&retired)
}
fn snapshot_files(path: &Path) -> Result<BTreeSet<PathBuf>> {
    let mut fileset = BTreeSet::new();
    fn walk(root: &Path, dir: &Path, out: &mut BTreeSet<PathBuf>) -> Result<()> {
        for e in io(fs::read_dir(dir))? {
            let e = io(e)?;
            if e.file_name() == ".git" {
                continue;
            }
            let path = e.path();
            let m = io(fs::symlink_metadata(&path))?;
            if m.is_dir() {
                files::trusted_dir(&path)?;
                walk(root, &path, out)?;
            } else {
                files::regular(&path)?;
                out.insert(
                    path.strip_prefix(root)
                        .map_err(|_| Error::new("invalid snapshot path"))?
                        .to_path_buf(),
                );
            }
        }
        Ok(())
    }
    walk(path, path, &mut fileset)?;
    Ok(fileset)
}
fn unchanged(original: &Path, live: &Path) -> Result<()> {
    let old = snapshot_files(original)?;
    if old != snapshot_files(live)? {
        return Err(Error::new("local configuration changed concurrently"));
    }
    for name in old {
        if files::read(&original.join(&name))? != files::read(&live.join(&name))? {
            return Err(Error::new("local configuration changed concurrently"));
        }
    }
    Ok(())
}
/// Orphans never occupied the active name, or were atomically retired from it.
/// They are safe to discard under the operation lock; unknown names are untouched.
fn clear_orphans() -> Result<()> {
    for entry in io(fs::read_dir(STATE))? {
        let entry = io(entry)?;
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let suffix = name
            .strip_prefix("transaction-preparing-")
            .or_else(|| name.strip_prefix("transaction-retired-"));
        if suffix.is_some_and(|id| id.len() == 24 && id.bytes().all(|b| b.is_ascii_hexdigit())) {
            files::trusted_dir(&entry.path())?;
            io(fs::remove_dir_all(entry.path()))?;
        }
    }
    Ok(())
}
fn begin() -> Result<()> {
    if state_entry_exists(TXN)? {
        return Err(Error::new(
            "an interrupted operation exists; run assbox recover before changing anything",
        ));
    }
    pending_state()?;
    clear_orphans()?;
    let prepared = Path::new(STATE).join(format!("transaction-preparing-{}", files::random_id()?));
    files::create_private(&prepared)?;
    let result = (|| {
        files::atomic_write(
            &prepared.join("old-system"),
            probe::profile_system()?.as_bytes(),
            0o600,
        )?;
        files::copy_tree(Path::new(CONFIG), &prepared.join("original"))?;
        files::copy_tree(Path::new(CONFIG), &prepared.join("candidate"))?;
        files::atomic_write(
            &prepared.join("phase"),
            Phase::Prepared.as_str().as_bytes(),
            0o600,
        )?;
        #[cfg(test)]
        crate::acceptance::checkpoint("manage-pre-publish")?;
        files::publish_directory(&prepared, Path::new(TXN))?;
        #[cfg(test)]
        crate::acceptance::checkpoint("manage-prepared")?;
        Ok(())
    })();
    // If rename succeeded but parent fsync failed, retain the active transaction.
    if result.is_err() && files::entry_exists(&prepared)? {
        let _ = fs::remove_dir_all(&prepared);
    }
    result
}
fn build(c: &Commands) -> Result<String> {
    let candidate = reference(&marker("candidate"))?;
    files::regular(&marker("candidate/flake.lock"))?;
    crate::check_evaluation(c, &candidate)?;
    let target = format!("{candidate}#nixosConfigurations.assbox.config.system.build.toplevel");
    let output = c.text(
        "nix",
        &[
            "build",
            "--no-link",
            "--print-out-paths",
            "--no-update-lock-file",
            "--no-write-lock-file",
            &target,
        ],
    )?;
    let system = output.trim();
    if !valid_store_system(system) {
        return Err(Error::new(
            "build did not return exactly one NixOS system store path",
        ));
    }
    // A GC root retains this exact candidate across the source-publication phase.
    c.run(
        "nix-store",
        &[
            "--add-root",
            files::path_text(&marker("built-system"))?,
            "--indirect",
            "--realise",
            system,
        ],
    )?;
    files::atomic_write(&marker("new-system"), system.as_bytes(), 0o600)?;
    journal(Phase::Built)?;
    Ok(system.to_owned())
}
fn commit(c: &Commands, new_system: &str, changed_files: &[&str], mode: &str) -> Result<()> {
    // Post-build, before source publication, profile mutation, or activation.
    assbox_system::worker::admit_candidate(c, new_system)?;
    let old = files::text(&marker("old-system"))?;
    let pending = pending_state()?;
    let next_pending = assbox_policy::pending_after_activation(
        new_system,
        &probe::booted_system()?,
        &probe::current_system()?,
        &probe::boot_id()?,
        pending.as_ref(),
        mode == "boot",
    )?;
    unchanged(&marker("original"), Path::new(CONFIG))?;
    if probe::profile_system()? != old {
        return Err(Error::new("system profile changed concurrently"));
    }
    // Validate the actual target generation, including retained/foreign rollbacks.
    let guard = crate::boot_guard::BootGuard::capture(c, &marker("boot-before"), new_system)?;
    let names = if changed_files.is_empty() {
        String::new()
    } else {
        assbox_policy::release::managed_changes(changed_files)?
    };
    files::atomic_write(&marker("changed-files"), names.as_bytes(), 0o600)?;
    if !changed_files.is_empty() {
        journal(Phase::Published)?;
        for name in changed_files {
            files::atomic_write(
                &Path::new(CONFIG).join(name),
                &files::read(&marker("candidate").join(name))?,
                0o644,
            )?;
            #[cfg(test)]
            crate::acceptance::checkpoint(&format!("manage-source-{name}"))?;
        }
    }
    journal(Phase::Activating)?;
    if old != new_system {
        c.run("nix-env", &["--profile", PROFILE, "--set", new_system])?;
    }
    #[cfg(test)]
    crate::acceptance::checkpoint("manage-profile")?;
    guard.verify(c)?;
    c.activate(new_system, mode)?;
    #[cfg(test)]
    crate::acceptance::checkpoint("manage-activated")?;
    guard.verify(c)?;
    if let Some(record) = next_pending {
        files::atomic_write(Path::new(PENDING), record.encode().as_bytes(), 0o600)?;
    } else if pending.is_some() {
        files::remove_regular(Path::new(PENDING))?;
    }
    journal(Phase::Committed)?;
    remove_txn()
}
fn fail_before_activation(error: Error) -> Error {
    // Do not turn a partial activation into a fictitious successful rollback.
    match files::text(&marker("phase"))
        .and_then(|s| s.parse::<Phase>())
        .map(recovery_after_interruption)
    {
        Ok(Recovery::DiscardCandidate) => {
            if let Err(cleanup) = remove_txn() {
                return Error::new(format!("{error}; cleanup also failed: {cleanup}"));
            }
        }
        _ => {
            return Error::new(format!(
                "{error}; recovery state retained in {TXN}; run assbox recover"
            ));
        }
    }
    error
}

pub fn check() -> Result<()> {
    let _lock = lock()?;
    begin()?;
    match build(&Commands) {
        Ok(system) => {
            println!("Configuration checks and build passed: {system}");
            remove_txn()
        }
        Err(e) => Err(fail_before_activation(e)),
    }
}
pub fn rebuild(boot: bool) -> Result<()> {
    let _lock = lock()?;
    begin()?;
    let result = (|| {
        let system = build(&Commands)?;
        commit(
            &Commands,
            &system,
            &[],
            if boot { "boot" } else { "switch" },
        )
    })();
    result.map_err(fail_before_activation)
}
pub fn packages() -> Result<BTreeSet<PackageName>> {
    assbox_config::read_packages(&files::text(
        &Path::new(CONFIG).join("assbox-packages.nix"),
    )?)
}
pub fn package_change(name: PackageName, add: bool) -> Result<()> {
    let _lock = lock()?;
    if add {
        let active = Commands.text(
            "nix",
            &[
                "eval",
                "--raw",
                "--no-update-lock-file",
                "--no-write-lock-file",
                "path:/etc/nixos#nixosConfigurations.assbox.config.assbox.controller.active",
                "--apply",
                "v: if v then \"true\" else \"false\"",
            ],
        )?;
        if active.trim() == "true" {
            return Err(Error::new(
                "package add is not supported on a thin controller; configure worker.extraGuestConfig instead",
            ));
        }
        if active.trim() != "false" {
            return Err(Error::new("invalid controller policy"));
        }
    }
    let mut names = packages()?;
    let changed = if add {
        names.insert(name)
    } else {
        names.remove(&name)
    };
    if !changed {
        println!("No managed package changes.");
        return Ok(());
    }
    begin()?;
    let result = (|| {
        files::atomic_write(
            &marker("candidate/assbox-packages.nix"),
            assbox_config::packages(&names).as_bytes(),
            0o644,
        )?;
        let system = build(&Commands)?;
        commit(&Commands, &system, &["assbox-packages.nix"], "switch")
    })();
    result.map_err(fail_before_activation)
}
pub fn search(query: &str) -> Result<()> {
    if query.starts_with('-') || query.len() > 200 || query.chars().any(char::is_control) {
        return Err(Error::new(
            "search expects a package name or regular expression, not command options",
        ));
    }
    // The local flake exports its configured, pinned nixpkgs as legacyPackages.
    Commands.run(
        "nix",
        &["search", "--no-write-lock-file", "path:/etc/nixos", query],
    )
}
fn stage_locked() -> Result<String> {
    // An installed machine must not silently reset missing replay state.
    let floor = crate::release::read_floor()?.ok_or_else(|| Error::new(
        "missing authenticated release high-water mark; inspect/recover it instead of resetting trust"))?;
    for name in ["flake.nix", "flake.lock", "assbox-release.json"] {
        files::regular(&Path::new(CONFIG).join(name))?;
    }
    begin()?;
    let result = (|| {
        let release = crate::release::fetch(
            &Commands,
            None,
            &marker("release-download"),
            Some(&floor),
            false,
        )?;
        // Durable before candidate Nix metadata/evaluation. Deliberately outside
        // source/activation rollback: failed builds permit exact retries, not replay.
        crate::release::record_floor(&release.floor)?;
        let fetched = crate::source::bind(&Commands, release)?;
        let candidate = marker("candidate");
        let flake = assbox_config::retarget_flake(
            &files::text(&candidate.join("flake.nix"))?,
            &fetched.release.manifest,
        )?;
        files::atomic_write(&candidate.join("flake.nix"), flake.as_bytes(), 0o644)?;
        files::atomic_write(&candidate.join("flake.lock"), &fetched.machine_lock, 0o644)?;
        files::atomic_write(
            &candidate.join("assbox-release.json"),
            &fetched.release.manifest_bytes,
            0o644,
        )?;
        let reference = reference(&candidate)?;
        Commands.run(
            "nix",
            &["flake", "lock", "--no-update-lock-file", &reference],
        )?;
        crate::source::verify_local_lock(&Commands, &candidate, &fetched.release.manifest)?;
        let system = build(&Commands)?;
        commit(
            &Commands,
            &system,
            &["flake.nix", "flake.lock", "assbox-release.json"],
            "boot",
        )?;
        Ok(system)
    })();
    result.map_err(fail_before_activation)
}

pub fn update(reboot: bool) -> Result<()> {
    let _lock = lock()?;
    let system = stage_locked()?;
    println!("Staged {system}. Running system is unchanged until reboot.");
    if reboot {
        reboot_pending_locked()?;
    }
    Ok(())
}
const STAGE_RETRY: &str = "/var/lib/assbox/stage-retry";
fn maintenance_numbers() -> Result<(u32, usize)> {
    let data = probe::runtime_json()?;
    let fields = Commands.jq_fields(
        &data,
        r#".updates | [.maximumStageRetries, .keepGenerations] | .[] | tostring + "\u0000""#,
    )?;
    if fields.len() != 2 {
        return Err(Error::new("missing maintenance retention/retry policy"));
    }
    Ok((
        fields[0]
            .parse()
            .map_err(|_| Error::new("invalid retry limit"))?,
        fields[1]
            .parse()
            .map_err(|_| Error::new("invalid generation retention"))?,
    ))
}
// Do not treat a dangling symlink or an unreadable marker as absent state.
fn state_entry_exists(path: &str) -> Result<bool> {
    files::entry_exists(Path::new(path))
}
fn pending_state() -> Result<Option<PendingReboot>> {
    if !state_entry_exists(PENDING)? {
        return Ok(None);
    }
    PendingReboot::parse(&files::text(Path::new(PENDING))?).map(Some)
}
pub fn maintenance(retry_only: bool) -> Result<()> {
    let _lock = lock()?;
    let runtime = probe::runtime(&Commands)?;
    if runtime.len() != 6 {
        return Err(Error::new("runtime policy is missing"));
    }
    let enabled = match runtime[5].as_str() {
        "true" => true,
        "false" => false,
        _ => return Err(Error::new("invalid automatic-maintenance policy")),
    };
    match assbox_policy::maintenance_action(
        enabled,
        state_entry_exists(TXN)?,
        state_entry_exists(PENDING)?,
    ) {
        MaintenanceAction::Disabled => return Ok(()),
        MaintenanceAction::InspectRecovery => {
            return Err(Error::new(
                "an interrupted operation blocks automatic maintenance; run assbox recover before staging or rebooting",
            ));
        }
        MaintenanceAction::RebootPending => return reboot_pending_locked(),
        MaintenanceAction::ConsiderStage => {}
    }
    let (limit, _) = maintenance_numbers()?;
    let attempts = if state_entry_exists(STAGE_RETRY)? {
        let text = files::text(Path::new(STAGE_RETRY))?;
        let used = text
            .parse::<u32>()
            .map_err(|_| Error::new("invalid persisted retry budget"))?;
        if text != used.to_string() {
            return Err(Error::new("noncanonical persisted retry budget"));
        }
        Some(used)
    } else {
        None
    };
    match assbox_policy::stage_attempt(retry_only, attempts, limit) {
        assbox_policy::StageAttempt::Skip => {}
        attempt => {
            let used = match attempt {
                assbox_policy::StageAttempt::Retry { used } => used,
                _ => 0,
            };
            files::atomic_write(Path::new(STAGE_RETRY), used.to_string().as_bytes(), 0o600)?;
            // Never prune a pending boot or an unresolved transaction. A daily
            // stage failure gets a bounded hourly retry, independently of reboot.
            cleanup_locked()?;
            stage_locked()?;
            files::remove_regular(Path::new(STAGE_RETRY))?;
        }
    }
    reboot_pending_locked()
}
fn reboot_pending_locked() -> Result<()> {
    if state_entry_exists(TXN)? {
        return Err(Error::new(
            "an interrupted operation blocks reboot; inspect it with assbox recover",
        ));
    }
    if !state_entry_exists(PENDING)? {
        return Ok(());
    }
    let pending = pending_state()?.ok_or_else(|| Error::new("pending state disappeared"))?;
    if probe::profile_system()? != pending.system() {
        return Err(Error::new(
            "pending reboot generation no longer matches the system profile",
        ));
    }
    if assbox_policy::reboot_completed(
        &pending,
        &probe::booted_system()?,
        &probe::current_system()?,
        &probe::boot_id()?,
    ) {
        require_worker_health(&probe::current_system()?)?;
        files::remove_regular(Path::new(PENDING))?;
        return Ok(());
    }
    let runtime = probe::runtime(&Commands)?;
    if runtime.len() != 6 {
        return Err(Error::new("runtime policy is incomplete"));
    }
    let grace = runtime[3]
        .parse::<u64>()
        .map_err(|_| Error::new("invalid reboot grace"))?;
    let minimum = runtime[4]
        .parse::<u8>()
        .map_err(|_| Error::new("invalid battery policy"))?;
    let (battery_presence, on_ac, battery_percent) = probe::power();
    let facts = MaintenanceFacts {
        changed_generation: true,
        stage_succeeded: true,
        battery_presence,
        on_ac,
        battery_percent,
        minimum_battery: minimum,
    };
    if reboot_decision(facts) == RebootDecision::RetryForPower {
        println!(
            "Update is staged. Reboot deferred for low or uncertain battery power; the hourly retry timer will recheck."
        );
        return Ok(());
    }
    if let Err(error)=Commands.run("wall", &[&format!("Assbox maintenance: rebooting in {grace} seconds. Save work; active agent jobs do not veto patching.")]) {
        eprintln!("Assbox notification failed: {error}; scheduled maintenance still proceeds.");
    }
    thread::sleep(Duration::from_secs(grace));
    // A changed profile or critically low battery invalidates the earlier decision.
    if probe::profile_system()? != pending.system() {
        return Err(Error::new("profile changed during reboot grace"));
    }
    let (battery_presence, on_ac, battery_percent) = probe::power();
    if reboot_decision(MaintenanceFacts {
        battery_presence,
        on_ac,
        battery_percent,
        ..facts
    }) != RebootDecision::Reboot
    {
        return Ok(());
    }
    // systemd performs the bounded graceful stop defined by each workload service.
    Commands.run("systemctl", &["--check-inhibitors=no", "reboot"])
}

pub fn recover(rollback_activation: bool) -> Result<()> {
    let _lock = lock()?;
    let pending = pending_state()?;
    if !state_entry_exists(TXN)? {
        clear_orphans()?;
        println!("No interrupted operation.");
        return Ok(());
    }
    files::trusted_dir(Path::new(TXN))?;
    let phase = files::text(&marker("phase"))?.parse::<Phase>()?;
    if matches!(
        phase,
        Phase::Published | Phase::Activating | Phase::Committed
    ) {
        source_intent(phase)?;
    }
    match recovery_after_interruption(phase) {
        Recovery::DiscardCandidate | Recovery::Nothing => remove_txn(),
        Recovery::RestoreSources => {
            restore_source(phase)?;
            remove_txn()
        }
        Recovery::InspectActivation => {
            if !rollback_activation {
                return Err(Error::new(
                    "activation may have partially changed services/boot files. Review the journal; use assbox recover --rollback only after inspection. User data is not rolled back.",
                ));
            }
            let old = files::text(&marker("old-system"))?;
            let new = files::text(&marker("new-system"))?;
            let profile = probe::profile_system()?;
            let running = probe::current_system()?;
            let restored = assbox_policy::recovery_target(
                &old,
                &new,
                &profile,
                &running,
                pending.as_ref().map(PendingReboot::system),
            )?;
            let restored_pending = PendingReboot::new(restored, probe::boot_id()?)?;
            let guard = crate::boot_guard::BootGuard::capture(
                &Commands,
                &marker("recovery-boot-before"),
                &old,
            )?;
            restore_source(phase)?;
            Commands.run("nix-env", &["--profile", PROFILE, "--set", &old])?;
            guard.verify(&Commands)?;
            Commands.activate(&old, "boot")?;
            guard.verify(&Commands)?;
            files::atomic_write(
                Path::new(PENDING),
                restored_pending.encode().as_bytes(),
                0o600,
            )?;
            println!(
                "Previous generation is selected for the next boot. Reboot to finish recovery; mutable application data was not restored."
            );
            remove_txn()
        }
    }
}
fn source_intent(phase: Phase) -> Result<Vec<String>> {
    let current = if files::entry_exists(&marker("changed-files"))? {
        Some(files::text(&marker("changed-files"))?)
    } else {
        None
    };
    let legacy = if files::entry_exists(&marker("changed-file"))? {
        Some(files::text(&marker("changed-file"))?)
    } else {
        None
    };
    assbox_policy::release::recovery_source_intent(phase, current.as_deref(), legacy.as_deref())
}
fn restore_source(phase: Phase) -> Result<()> {
    let names = source_intent(phase)?;
    for directory in [
        marker("original"),
        marker("candidate"),
        PathBuf::from(CONFIG),
    ] {
        files::trusted_dir(&directory)?;
    }
    let mut originals = Vec::new();
    for name in names {
        let old = files::read(&marker("original").join(&name))?;
        let candidate = files::read(&marker("candidate").join(&name))?;
        let path = Path::new(CONFIG).join(name);
        let live = files::read(&path)?;
        if live != old && live != candidate {
            return Err(Error::new(
                "local file changed after interruption; no recovery source files were overwritten",
            ));
        }
        originals.push((path, old));
    }
    for (path, bytes) in originals {
        files::atomic_write(&path, &bytes, 0o644)?;
    }
    // release-state is not source configuration and is never decreased here.
    Ok(())
}

pub fn status() -> Result<()> {
    println!("Activated: {}", probe::current_system()?);
    println!("Booted: {}", probe::booted_system()?);
    println!("Boot profile: {}", probe::profile_system()?);
    if files::require_root().is_ok() {
        if let Some(floor) = crate::release::read_floor()? {
            println!(
                "Authenticated release high-water mark: r-{} (not a boot-success receipt)",
                floor.sequence
            );
        }
        println!("Interrupted operation: {}", state_entry_exists(TXN)?);
        println!(
            "Pending maintenance reboot: {}",
            state_entry_exists(PENDING)?
        );
    } else {
        println!(
            "Run sudo assbox status to inspect private release, recovery and pending-reboot state."
        );
    }
    let r = probe::runtime(&Commands)?;
    if r.len() == 6 {
        println!(
            "Components: {} | Presentation: {} | Maintenance: {}",
            r[0], r[1], r[2]
        );
    }
    Ok(())
}
fn require_worker_health(current: &str) -> Result<()> {
    let health = assbox_system::worker::boot_health(&Commands, current);
    let outcome = if health.is_ok() {
        "accepted"
    } else {
        "worker-health-failed"
    };
    files::atomic_write(
        Path::new("/var/lib/assbox/worker-boot-status"),
        format!(
            "system={current}\nboot={}\noutcome={outcome}\n",
            probe::boot_id()?.as_str()
        )
        .as_bytes(),
        0o600,
    )?;
    health
}

pub fn boot_check() -> Result<()> {
    boot_check_with_retry(false)
}

pub fn boot_check_retry() -> Result<()> {
    boot_check_with_retry(true)
}

fn boot_check_with_retry(retry_only: bool) -> Result<()> {
    let _lock = lock()?;
    if state_entry_exists(TXN)? {
        return Err(Error::new(
            "unresolved transaction blocks boot success and cleanup",
        ));
    }
    let pending = pending_state()?;
    let current = probe::current_system()?;
    let booted = probe::booted_system()?;
    if current != probe::profile_system()? || current != booted {
        return Err(Error::new(
            "booted, activated and selected generations differ; reboot or inspect bootloader/rollback state",
        ));
    }
    let boot_id = probe::boot_id()?;
    // Never reuse an old success across pending intent, a reboot, a selected
    // generation change, or an unresolved transaction. Manual checks always run.
    if retry_only && pending.is_none() && state_entry_exists(BOOT_ACCEPTED)? {
        let receipt = BootAcceptance::parse(&files::text(Path::new(BOOT_ACCEPTED))?)?;
        if receipt.matches(&current, &boot_id) {
            return assbox_system::worker::quiesce_boot_retry(&Commands, &current);
        }
    }
    Commands.run("systemctl", &["is-active", "network.target"])?;
    if let Some(system) = &pending
        && !assbox_policy::reboot_completed(system, &booted, &current, &boot_id)
    {
        return Err(Error::new(
            "pending reboot has not been completed by this boot",
        ));
    }
    require_worker_health(&current)?;
    if pending.is_some() {
        files::remove_regular(Path::new(PENDING))?;
    }
    println!(
        "Booted, activated and selected system generations agree. Application authentication and real firmware acceptance remain separate checks."
    );
    let runtime = probe::runtime(&Commands)?;
    if runtime.get(5).is_some_and(|enabled| enabled == "true") {
        cleanup_locked()?;
    }
    // Publish only after all acceptance work completed. Failed or interrupted
    // runs remain retryable; the diagnostic worker status is not this receipt.
    let receipt = BootAcceptance::new(&current, boot_id)?;
    files::atomic_write(Path::new(BOOT_ACCEPTED), receipt.encode().as_bytes(), 0o600)?;
    assbox_system::worker::quiesce_boot_retry(&Commands, &current)
}

pub fn components_set(
    components: Components,
    presentation: Presentation,
    accept_unfree: bool,
) -> Result<()> {
    let _lock = lock()?;
    let existing = Commands.text(
        "nix",
        &[
            "eval",
            "--json",
            "--no-update-lock-file",
            "--no-write-lock-file",
            "path:/etc/nixos#nixosConfigurations.assbox.config.assbox.acceptUnfree",
        ],
    )?;
    if !matches!(existing.trim(), "true" | "false") {
        return Err(Error::new("invalid evaluated proprietary-package policy"));
    }
    assbox_policy::validate_component_selection(
        components,
        presentation,
        accept_unfree || existing.trim() == "true",
    )?;
    let settings = assbox_config::selection(
        &files::text(&Path::new(CONFIG).join("assbox-settings.nix"))?,
        components,
        presentation,
        accept_unfree,
    )?;
    begin()?;
    let result = (|| {
        files::atomic_write(
            &marker("candidate/assbox-settings.nix"),
            settings.as_bytes(),
            0o644,
        )?;
        let candidate = reference(&marker("candidate"))?;
        let consent = Commands.text(
            "nix",
            &[
                "eval",
                "--json",
                "--no-update-lock-file",
                "--no-write-lock-file",
                &format!("{candidate}#nixosConfigurations.assbox.config.assbox.acceptUnfree"),
            ],
        )?;
        if !matches!(consent.trim(), "true" | "false") {
            return Err(Error::new("invalid candidate proprietary-package policy"));
        }
        if accept_unfree && consent.trim() != "true" {
            return Err(Error::new(
                "a local override denies proprietary packages; review local.nix instead of repeating --accept-unfree",
            ));
        }
        assbox_policy::validate_component_selection(
            components,
            presentation,
            consent.trim() == "true",
        )?;
        for (attribute, expected) in [
            (
                "selectedComponents",
                format!(
                    "[{}]",
                    components
                        .iter()
                        .map(|c| format!("\"{c}\""))
                        .collect::<Vec<_>>()
                        .join(",")
                ),
            ),
            ("presentation", format!("\"{presentation}\"")),
        ] {
            let output = Commands.text(
                "nix",
                &[
                    "eval",
                    "--json",
                    "--no-write-lock-file",
                    &format!("{candidate}#nixosConfigurations.assbox.config.assbox.{attribute}"),
                ],
            )?;
            if output.trim() != expected {
                return Err(Error::new(
                    "a local override conflicts with the requested components/presentation; no changes activated",
                ));
            }
        }
        let system = build(&Commands)?;
        // A session/backend change is staged for a clean reboot, not switched underneath a GUI.
        commit(&Commands, &system, &["assbox-settings.nix"], "boot")?;
        println!(
            "Component selection is staged for reboot. Stored application data and credentials were not deleted."
        );
        Ok(())
    })();
    result.map_err(fail_before_activation)
}

pub fn rollback() -> Result<()> {
    let _lock = lock()?;
    let link = io(fs::read_link(PROFILE))?;
    let name = link
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or_else(|| Error::new("unknown profile link"))?;
    let generation = name
        .strip_prefix("system-")
        .and_then(|s| s.strip_suffix("-link"))
        .and_then(|s| s.parse::<u64>().ok())
        .ok_or_else(|| Error::new("unknown profile generation"))?;
    let mut previous: Option<(u64, String)> = None;
    for e in io(fs::read_dir("/nix/var/nix/profiles"))? {
        let e = io(e)?;
        let n = e.file_name().to_string_lossy().into_owned();
        let number = n
            .strip_prefix("system-")
            .and_then(|s| s.strip_suffix("-link"))
            .and_then(|s| s.parse::<u64>().ok());
        if let Some(number) = number
            && number < generation
            && previous.as_ref().is_none_or(|(old, _)| number > *old)
        {
            let target = io(fs::canonicalize(e.path()))?
                .to_string_lossy()
                .into_owned();
            if valid_store_system(&target) {
                previous = Some((number, target));
            }
        }
    }
    let (_, system) = previous.ok_or_else(|| Error::new("no retained previous generation"))?;
    begin()?;
    let result = (|| {
        files::atomic_write(&marker("new-system"), system.as_bytes(), 0o600)?;
        journal(Phase::Built)?;
        commit(&Commands, &system, &[], "boot")?;
        println!(
            "Previous generation staged. Reboot to use it. Local source configuration and mutable application data were not rolled back."
        );
        Ok(())
    })();
    result.map_err(fail_before_activation)
}

fn generations() -> Result<Vec<(u64, String)>> {
    let mut out = Vec::new();
    for entry in io(fs::read_dir("/nix/var/nix/profiles"))? {
        let entry = io(entry)?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let number = name
            .strip_prefix("system-")
            .and_then(|s| s.strip_suffix("-link"))
            .and_then(|s| s.parse::<u64>().ok());
        if let Some(number) = number {
            let system = io(fs::canonicalize(entry.path()))?
                .to_string_lossy()
                .into_owned();
            if !valid_store_system(&system) {
                return Err(Error::new("invalid system generation target"));
            }
            out.push((number, system));
        }
    }
    out.sort_by_key(|(number, _)| *number);
    Ok(out)
}
fn cleanup_locked() -> Result<()> {
    if state_entry_exists(TXN)? || state_entry_exists(PENDING)? {
        return Ok(());
    }
    let current = probe::current_system()?;
    if probe::profile_system()? != current || probe::booted_system()? != current {
        return Ok(());
    }
    // No pending marker is not proof of worker health (for example first boot).
    // Manual and scheduled cleanup must preserve fallback generations on failure.
    require_worker_health(&current)?;
    let (_, keep) = maintenance_numbers()?;
    let before = generations()?;
    let obsolete =
        assbox_policy::obsolete_generations(&before, std::slice::from_ref(&current), keep)?;
    if !obsolete.is_empty() {
        begin()?;
        let result = (|| {
            let guard =
                crate::boot_guard::BootGuard::capture(&Commands, &marker("boot-before"), &current)?;
            files::atomic_write(&marker("new-system"), current.as_bytes(), 0o600)?;
            files::atomic_write(&marker("operation"), b"retention", 0o600)?;
            for (number, system) in &before {
                if obsolete.contains(number) {
                    let root = marker(&format!("retained-{number}"));
                    Commands.run(
                        "nix-store",
                        &[
                            "--add-root",
                            files::path_text(&root)?,
                            "--indirect",
                            "--realise",
                            system,
                        ],
                    )?;
                }
            }
            if generations()? != before || probe::profile_system()? != current {
                return Err(Error::new("generation links changed before retention"));
            }
            files::atomic_write(&marker("changed-files"), b"", 0o600)?;
            journal(Phase::Activating)?;
            let numbers: Vec<_> = obsolete.iter().map(u64::to_string).collect();
            let mut args = vec!["--profile", PROFILE, "--delete-generations"];
            args.extend(numbers.iter().map(String::as_str));
            Commands.run("nix-env", &args)?;
            guard.verify(&Commands)?;
            // Remove stale boot-menu entries before releasing the temporary roots.
            Commands.activate(&current, "boot")?;
            guard.verify(&Commands)?;
            journal(Phase::Committed)?;
            remove_txn()
        })();
        result.map_err(fail_before_activation)?;
    }
    Commands.run("nix-store", &["--gc"])
}
pub fn cleanup() -> Result<()> {
    let _lock = lock()?;
    cleanup_locked()
}

/// Stage worker placement and resources atomically with the existing Assbox
/// candidate/build/boot transaction. Never rewrite local.nix or copy credentials.
pub fn worker_configure(
    spec: Option<&assbox_domain::worker::WorkerSpec>,
    accept_unfree: bool,
    apply: bool,
) -> Result<()> {
    let _lock = lock()?;
    let live = Commands.capture(
        "nix",
        &[
            "eval",
            "--json",
            "--no-update-lock-file",
            "--no-write-lock-file",
            "path:/etc/nixos#nixosConfigurations.assbox.config.assbox",
            "--apply",
            "c: { inherit (c) acceptUnfree selectedComponents presentation; }",
        ],
    )?;
    let fields = Commands.jq_fields(&live,
        r#"[(.acceptUnfree|tostring),(.selectedComponents|join(",")),.presentation] | .[] | . + "\u0000""#)?;
    if fields.len() != 3 || !matches!(fields[0].as_str(), "true" | "false") {
        return Err(Error::new("invalid evaluated host component policy"));
    }
    let old: Components = fields[1].parse()?;
    if spec.is_some()
        && old
            .iter()
            .any(|c| c.requires_worker() && !c.controller_allowed())
    {
        return Err(Error::new(
            "remove the unqualified sensitive controller before changing worker placement",
        ));
    }
    // Configuration never silently removes installed controller components.
    // The operator must remove incompatible selections in a separate explicit
    // transaction before enabling the worker profile.
    let host = old;
    let presentation: Presentation = fields[2].parse()?;
    assbox_domain::worker::validate_host_selection(host, spec)?;
    if spec.is_some() && !packages()?.is_empty() {
        return Err(Error::new(
            "remove managed host packages before enabling the thin controller; worker tools are configured separately",
        ));
    }
    if let Some(spec) = spec {
        if spec.auto_state {
            println!(
                "Worker capacity: automatic; the construction placeholder is not the final size. Resolve after building the artifact, retaining controller recovery headroom."
            );
        }
        spec.validate(accept_unfree || fields[0] == "true")?;
        assbox_policy::worker::validate_host_budget(
            spec,
            &assbox_system::worker::hardware(&Commands)?,
        )?;
    }
    let settings = assbox_config::selection(
        &files::text(&Path::new(CONFIG).join("assbox-settings.nix"))?,
        host,
        presentation,
        accept_unfree,
    )?;
    let settings = assbox_config::worker::selection(&settings, spec)?;
    println!("Host curated components: {old} -> {host}");
    if let Some(spec) = spec {
        println!(
            "Worker components: {} | memory {} MiB | {} CPUs | state {} GiB",
            spec.components,
            spec.memory_mib,
            spec.vcpus,
            if spec.auto_state {
                "automatic".to_owned()
            } else {
                spec.state_gib.to_string()
            }
        );
    } else {
        println!(
            "Worker disabled at next boot; no agent is moved to the host and no worker data is deleted."
        );
    }
    if !apply {
        println!("Plan only. Add --apply to build and stage this configuration for reboot.");
        return Ok(());
    }
    begin()?;
    let result = (|| {
        files::atomic_write(
            &marker("candidate/assbox-settings.nix"),
            settings.as_bytes(),
            0o644,
        )?;
        let candidate = reference(&marker("candidate"))?;
        let mut resolved = spec.cloned();
        if let Some(worker) = resolved.as_mut().filter(|s| s.auto_state) {
            let target =
                format!("{candidate}#nixosConfigurations.assbox.config.system.build.toplevel");
            let sizing_system = Commands.text(
                "nix",
                &[
                    "build",
                    "--out-link",
                    files::path_text(&marker("sizing-system"))?,
                    "--print-out-paths",
                    "--no-update-lock-file",
                    "--no-write-lock-file",
                    &target,
                ],
            )?;
            if !valid_store_system(sizing_system.trim()) {
                return Err(Error::new("invalid sizing system"));
            }
            let artifact = files::io(fs::read_link(
                Path::new(sizing_system.trim()).join("assbox-worker-image"),
            ))?;
            let root_bytes = assbox_system::worker::artifact_root_bytes(
                &Commands,
                Path::new("/"),
                files::path_text(&artifact)?,
            )?;
            let (total, free) = assbox_system::worker::filesystem_capacity(
                &Commands,
                if Path::new("/var/lib/assbox-worker-data").exists() {
                    Path::new("/var/lib/assbox-worker-data")
                } else {
                    Path::new("/var/lib")
                },
            )?;
            worker.state_gib = assbox_policy::worker::automatic_state_gib(total, free, root_bytes)?;
            worker.auto_state = false;
            let settings = assbox_config::worker::selection(&settings, Some(worker))?;
            files::atomic_write(
                &marker("candidate/assbox-settings.nix"),
                settings.as_bytes(),
                0o644,
            )?;
            println!(
                "Resolved persistent worker capacity: {} GiB (sparse allocation).",
                worker.state_gib
            );
        }
        let spec = resolved.as_ref();
        let evaluated = Commands.capture(
            "nix",
            &[
                "eval",
                "--json",
                "--no-update-lock-file",
                "--no-write-lock-file",
                &format!("{candidate}#nixosConfigurations.assbox.config.assbox"),
                "--apply",
                assbox_config::worker::EVALUATED_SELECTION,
            ],
        )?;
        let filter = if spec.is_some() {
            r#"[(.enable|tostring),(.components|join(",")),
             (.allowMutableCodeFor|join(",")),(.memoryMiB|tostring),(.vcpus|tostring),
             (.stateGiB|tostring),(.uplinkInterfaces|join(",")),.egress,
             (.allowGuestSudo|tostring),
             (.nameservers|join(","))] | .[] | . + "\u0000""#
        } else {
            r#"(.enable|tostring) + "\u0000""#
        };
        if Commands.jq_fields(&evaluated, filter)? != assbox_config::worker::expected_fields(spec) {
            return Err(Error::new(
                "a local override conflicts with the requested worker settings; no changes activated",
            ));
        }
        let host_evaluated = Commands.capture(
            "nix",
            &[
                "eval",
                "--json",
                "--no-update-lock-file",
                "--no-write-lock-file",
                &format!("{candidate}#nixosConfigurations.assbox.config.assbox"),
                "--apply",
                "c: { inherit (c) selectedComponents presentation acceptUnfree; }",
            ],
        )?;
        let host_fields = Commands.jq_fields(&host_evaluated,
            r#"[(.selectedComponents|join(",")),.presentation,(.acceptUnfree|tostring)] | .[] | . + "\u0000""#)?;
        if host_fields
            != [
                host.to_string(),
                presentation.to_string(),
                (accept_unfree || fields[0] == "true").to_string(),
            ]
        {
            return Err(Error::new(
                "a local override conflicts with requested host placement or consent",
            ));
        }
        let system = build(&Commands)?;
        commit(&Commands, &system, &["assbox-settings.nix"], "boot")?;
        println!(
            "Worker configuration staged for reboot. Credentials and project data were not copied or removed. Verify Desktop worker-targeted tool routing before use."
        );
        Ok(())
    })();
    result.map_err(fail_before_activation)
}

/// Reuse the transaction journal and worker admission; ordinary Nix remains authority.
pub fn instance_configure(
    request: &assbox_policy::instances::ResolvedInstance,
    accept_unfree: bool,
    allow_mutable: bool,
    apply: bool,
) -> Result<()> {
    let _lock = lock()?;
    request.config.validate()?;
    let existing=Commands.text("nix", &["eval","--json","--no-update-lock-file","--no-write-lock-file","path:/etc/nixos#nixosConfigurations.assbox.config.assbox","--apply","c: { worker = c.worker.enable; protected = c.kiosk.localExecution; consent = c.acceptUnfree; agentSsh = c.network.ssh.agent.enable; }"])?;
    let fields=Commands.jq_fields(existing.as_bytes(),r#"[.worker|tostring] + [.protected,.consent|tostring] + [.agentSsh|tostring] | .[] | . + "\u0000""#)?;
    if fields.len() != 4 {
        return Err(Error::new("incomplete current instance observations"));
    }
    let requested_worker = request.worker != Components::default();
    if requested_worker != (fields[0] == "true") {
        return Err(Error::new(
            "execution topology changes require explicit worker configuration/export first; repositories and credentials are never moved by a preset change",
        ));
    }
    if request.workload_ssh && fields[3] != "true" {
        return Err(Error::new(
            "configure a workload public key and approved SSH exposure in local.nix before selecting this SSH route",
        ));
    }
    request
        .host
        .validate(request.presentation, accept_unfree || fields[2] == "true")?;
    let original = files::text(&Path::new(CONFIG).join("assbox-settings.nix"))?;
    let selected =
        assbox_config::selection(&original, request.host, request.presentation, accept_unfree)?;
    let mut selected = assbox_config::instances::selection(&selected, &request.config)?;
    if requested_worker {
        let current = Commands.text(
            "nix",
            &[
                "eval",
                "--json",
                "--no-update-lock-file",
                "--no-write-lock-file",
                "path:/etc/nixos#nixosConfigurations.assbox.config.assbox",
                "--apply",
                assbox_config::worker::EVALUATED_SELECTION,
            ],
        )?;
        let values = Commands.jq_fields(current.as_bytes(),r#"[.enable|tostring] + [(.components|join(",")),(.allowMutableCodeFor|join(",")),(.memoryMiB|tostring),(.vcpus|tostring),(.stateGiB|tostring),(.uplinkInterfaces|join(",")),.egress,(.allowGuestSudo|tostring),(.nameservers|join(","))] | .[] | . + "\u0000""#)?;
        if values.len() != 10 {
            return Err(Error::new("incomplete worker resource observations"));
        }
        let retained: Components = values[2].parse()?;
        let mut mutable = Components::default();
        for c in request
            .worker
            .iter()
            .filter(|c| c.mutable_code() && (allow_mutable || retained.contains(*c)))
        {
            mutable.insert(c);
        }
        let list = |s: &str| {
            if s.is_empty() {
                vec![]
            } else {
                s.split(',').map(str::to_owned).collect()
            }
        };
        let number = |s: &str| {
            s.parse::<u32>()
                .map_err(|_| Error::new("invalid existing worker resources"))
        };
        let spec = assbox_domain::worker::WorkerSpec {
            components: request.worker,
            mutable_components: mutable,
            memory_mib: number(&values[3])?,
            vcpus: number(&values[4])?,
            state_gib: number(&values[5])?,
            auto_state: false,
            uplinks: list(&values[6]),
            network: values[7].parse()?,
            guest_sudo: values[8] == "true",
            nameservers: list(&values[9]),
        };
        let spec = assbox_policy::worker::with_egress(
            spec,
            request.config.egress,
            accept_unfree || fields[2] == "true",
        )?;
        selected = assbox_config::worker::selection(&selected, Some(&spec))?;
    }
    // Consent is explicit and scoped to selected components; it never changes local.nix.
    if allow_mutable {
        let mut permissions = String::new();
        for c in request.host.iter().filter(|c| c.mutable_code()) {
            let denied =
                format!("  assbox.components.{c}.allowMutableCode = lib.mkDefault false;\n");
            selected = selected.replace(&denied, "");
            if !selected.contains(&format!("assbox.components.{c}.allowMutableCode")) {
                permissions.push_str(&format!(
                    "  assbox.components.{c}.allowMutableCode = lib.mkDefault true;\n"
                ));
            }
        }
        selected.insert_str(selected.len() - 2, &permissions);
    }
    println!(
        "Requested preset {} revision {} | host {} | presentation {} | Tailscale {} | egress {}",
        request.config.preset,
        request.config.revision,
        request.host,
        request.presentation,
        request.config.tailscale,
        request.config.egress
    );
    print!(
        "{}",
        assbox_config::settings_diff::render(&original, &selected)?
    );
    begin()?;
    let result = (|| {
        files::atomic_write(
            &marker("candidate/assbox-settings.nix"),
            selected.as_bytes(),
            0o644,
        )?;
        let candidate = reference(&marker("candidate"))?;
        let failures = Commands.text(
            "nix",
            &[
                "eval",
                "--json",
                "--no-update-lock-file",
                "--no-write-lock-file",
                &format!("{candidate}#nixosConfigurations.assbox.config.assertions"),
                "--apply",
                "xs: map (x: x.message) (builtins.filter (x: !x.assertion) xs)",
            ],
        )?;
        if failures.trim() != "[]" {
            return Err(Error::new(format!(
                "candidate configuration assertions failed: {failures}"
            )));
        }
        let effective=Commands.text("nix", &["eval","--json","--no-update-lock-file","--no-write-lock-file",&format!("{candidate}#nixosConfigurations.assbox.config.assbox"),"--apply","c: { components = c.selectedComponents; presentation = c.presentation; instance = c.instance; tailscale = c.network.tailscale.enable; egress = c.network.execution.egress; computerUse = c.computerUse.mode; workerComputerUse = c.worker.computerUseMode; workerComponents = c.worker.components; protected = c.kiosk.localExecution; webApps = c.kiosk.webApps; hermes = c.components.hermes-dashboard; serve = c.network.tailscale.serveMappings; workerEgress = if c.worker.enable then c.worker.egress else null; consent = c.acceptUnfree; mutable = builtins.filter (id: c.components.${id}.allowMutableCode) c.selectedComponents; }"])?;
        let observed=Commands.jq_fields(effective.as_bytes(),r#"[.components|join(",")] + [.presentation,.instance.preset,(.instance.revision|tostring),(.tailscale|tostring),.egress,.computerUse,.workerComputerUse,(.workerComponents|sort|join(",")),.protected,(.webApps|join(",")),(.instance.exclusions|sort|join(",")),.instance.purpose,.hermes.publicUrl,.hermes.accessProfile,(.hermes.consentTunnelOnly|tostring),(.serve|map(.component+"|"+.publicUrl+"|"+(.port|tostring))|sort|join(",")),(.consent|tostring),(.workerEgress // "")] | .[] | . + "\u0000""#)?;
        let expected = vec![
            request.host.to_string(),
            request.presentation.to_string(),
            request.config.preset.clone(),
            request.config.revision.to_string(),
            request.config.tailscale.to_string(),
            request.config.egress.to_string(),
            if requested_worker {
                "none".into()
            } else {
                request.config.computer_use.as_str().into()
            },
            if requested_worker {
                request.config.computer_use.as_str().into()
            } else {
                "none".into()
            },
            request.worker.to_string(),
            if request.config.protected_code {
                "managed-worker".into()
            } else {
                "none".into()
            },
            request.config.web_apps.join(","),
            request.config.exclusions.to_string(),
            request.config.purpose.as_str().into(),
            request.config.hermes_public_url.clone(),
            if request.config.hermes_tunnel_only {
                "tunnel-only".into()
            } else {
                "authenticated".into()
            },
            request.config.hermes_tunnel_only.to_string(),
            if request.config.dashboard_serve {
                format!("hermes-dashboard|{}|9119", request.config.hermes_public_url)
            } else {
                String::new()
            },
            (accept_unfree || fields[2] == "true").to_string(),
            if requested_worker {
                request.config.egress.to_string()
            } else {
                String::new()
            },
        ];
        if observed != expected {
            return Err(Error::new(
                "effective configuration differs from the preview; review local.nix overrides before applying",
            ));
        }
        if allow_mutable {
            let permitted =
                Commands.jq_fields(effective.as_bytes(), r#".mutable[] | . + "\u0000""#)?;
            if request
                .host
                .iter()
                .filter(|c| c.mutable_code())
                .any(|c| !permitted.iter().any(|id| id == c.as_str()))
            {
                return Err(Error::new(
                    "effective mutable-code consent differs from the preview; review local.nix overrides before applying",
                ));
            }
        }
        println!(
            "Effective selection matches the preview. Native applications still require their independent policy gate."
        );
        if !apply {
            remove_txn()?;
            println!(
                "Preview complete; no build or activation. Use assbox configure --apply to build and stage the chosen settings."
            );
            return Ok(());
        }
        let system = build(&Commands)?;
        commit(&Commands, &system, &["assbox-settings.nix"], "boot")?;
        println!(
            "Instance configuration staged for reboot; provider setup and qualification remain independent."
        );
        Ok(())
    })();
    result.map_err(fail_before_activation)
}
