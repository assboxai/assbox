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
    files::retire_directory(Path::new(TXN))
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
    let old = files::text(&marker("old-system"))?;
    pending_state()?;
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
    if mode == "boot" && probe::current_system()? != new_system {
        files::atomic_write(Path::new(PENDING), new_system.as_bytes(), 0o600)?;
    } else if probe::current_system()? == new_system && state_entry_exists(PENDING)? {
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
fn pending_state() -> Result<Option<String>> {
    if !state_entry_exists(PENDING)? {
        return Ok(None);
    }
    let system = files::text(Path::new(PENDING))?;
    if !valid_store_system(&system) {
        return Err(Error::new("invalid pending reboot generation"));
    }
    Ok(Some(system))
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
    if !valid_store_system(&pending) || probe::profile_system()? != pending {
        return Err(Error::new(
            "pending reboot generation no longer matches the system profile",
        ));
    }
    let current = probe::current_system()?;
    if current == pending {
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
    if probe::profile_system()? != pending {
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
            let restored_pending = assbox_policy::recovery_pending(
                &old,
                &new,
                &profile,
                &running,
                pending.as_deref(),
            )?;
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
            if let Some(system) = restored_pending {
                files::atomic_write(Path::new(PENDING), system.as_bytes(), 0o600)?;
            } else if pending.is_some() {
                files::remove_regular(Path::new(PENDING))?;
            }
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
    println!("Running: {}", probe::current_system()?);
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
            "Application: {} | Presentation: {} | Maintenance: {}",
            r[0], r[1], r[2]
        );
    }
    Ok(())
}
pub fn boot_check() -> Result<()> {
    let _lock = lock()?;
    if state_entry_exists(TXN)? {
        return Err(Error::new(
            "unresolved transaction blocks boot success and cleanup",
        ));
    }
    let pending = pending_state()?;
    if probe::current_system()? != probe::profile_system()? {
        return Err(Error::new(
            "running generation differs from the selected boot profile; inspect bootloader/rollback state",
        ));
    }
    Commands.run("systemctl", &["is-active", "network.target"])?;
    if let Some(system) = pending {
        if system != probe::current_system()? {
            return Err(Error::new("pending reboot differs from running generation"));
        }
        files::remove_regular(Path::new(PENDING))?;
    }
    println!(
        "Running and selected system generations agree. Application authentication and real firmware acceptance remain separate checks."
    );
    let runtime = probe::runtime(&Commands)?;
    if runtime.get(5).is_some_and(|enabled| enabled == "true") {
        cleanup_locked()?;
    }
    Ok(())
}

pub fn application_set(
    application: Application,
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
    assbox_policy::validate_application_selection(
        application,
        presentation,
        accept_unfree || existing.trim() == "true",
    )?;
    let settings = assbox_config::selection(
        &files::text(&Path::new(CONFIG).join("assbox-settings.nix"))?,
        application,
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
        assbox_policy::validate_application_selection(
            application,
            presentation,
            consent.trim() == "true",
        )?;
        for (attribute, expected) in [
            ("application", application.as_str()),
            ("presentation", presentation.as_str()),
        ] {
            let output = Commands.text(
                "nix",
                &[
                    "eval",
                    "--raw",
                    "--no-write-lock-file",
                    &format!("{candidate}#nixosConfigurations.assbox.config.assbox.{attribute}"),
                ],
            )?;
            if output != expected {
                return Err(Error::new(
                    "a local override conflicts with the requested application/presentation; no changes activated",
                ));
            }
        }
        let system = build(&Commands)?;
        // A session/backend change is staged for a clean reboot, not switched underneath a GUI.
        commit(&Commands, &system, &["assbox-settings.nix"], "boot")?;
        println!(
            "Application selection is staged for reboot. Stored application data and credentials were not deleted."
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
    if probe::profile_system()? != current {
        return Ok(());
    }
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
