// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_policy::{InstallPlan, filesystem_check};
use assbox_system::{
    cancellation,
    commands::Commands,
    files::{self, Lock, Mount, io},
    probe,
};
use std::{
    collections::BTreeMap,
    fs::{self, File},
    io::{Read, Seek, SeekFrom},
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

const WORK: &str = "/run/assbox-install";

fn point(name: &str) -> PathBuf {
    Path::new(WORK).join(name)
}
fn recheck(plan: &InstallPlan, c: &Commands, mounts: &[&Mount]) -> Result<()> {
    cancellation::check()?;
    let allowed: Vec<(&str, &str)> = mounts
        .iter()
        .map(|m| Ok((m.device(), files::path_text(&m.point)?)))
        .collect::<Result<_>>()?;
    plan.revalidate(&probe::inventory(c)?, &allowed)
}
fn make_dirs(root: &Path, relative: &str) -> Result<PathBuf> {
    let mut path = root.to_path_buf();
    for component in relative.split('/') {
        if component.is_empty() || component == ".." || component == "." {
            return Err(Error::new("invalid target directory"));
        }
        path.push(component);
        if !files::entry_exists(&path)? {
            files::create_private(&path)?;
            io(fs::set_permissions(
                &path,
                fs::Permissions::from_mode(0o755),
            ))?;
        }
        files::trusted_dir(&path)?;
    }
    Ok(path)
}
fn hash(c: &Commands, path: &Path) -> Result<String> {
    let text = c.text("sha256sum", &["--", files::path_text(path)?])?;
    let h = text
        .split_whitespace()
        .next()
        .ok_or_else(|| Error::new("hash output missing"))?;
    if h.len() != 64 || !h.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(Error::new("invalid hash output"));
    }
    Ok(h.to_owned())
}
pub(crate) fn esp_manifest(
    c: &Commands,
    root: &Path,
    apple: bool,
) -> Result<BTreeMap<String, String>> {
    fn walk(
        c: &Commands,
        root: &Path,
        dir: &Path,
        apple: bool,
        out: &mut BTreeMap<String, String>,
    ) -> Result<()> {
        for e in io(fs::read_dir(dir))? {
            let e = io(e)?;
            let path = e.path();
            let name = files::path_text(
                path.strip_prefix(root)
                    .map_err(|_| Error::new("ESP path escaped"))?,
            )?
            .to_owned();
            let lower = name.to_ascii_lowercase();
            if apple && (lower == "efi/assbox" || lower.starts_with("efi/assbox/")) {
                continue;
            }
            if name.chars().any(char::is_control) {
                return Err(Error::new("control character in ESP filename"));
            }
            let meta = io(fs::symlink_metadata(&path))?;
            if meta.is_dir() {
                walk(c, root, &path, apple, out)?;
            } else if meta.is_file() {
                out.insert(name, hash(c, &path)?);
            } else {
                return Err(Error::new("special file on ESP"));
            }
            if out.len() > 10000 {
                return Err(Error::new("ESP manifest is too large"));
            }
        }
        Ok(())
    }
    let mut out = BTreeMap::new();
    walk(c, root, root, apple, &mut out)?;
    Ok(out)
}
fn write_backup_file(path: &Path, bytes: &[u8]) -> Result<()> {
    // The backup may be FAT/exFAT: Unix ownership is supplied by mount options.
    let mut opts = fs::OpenOptions::new();
    opts.write(true).create_new(true).mode(0o600);
    let mut f = io(opts.open(path))?;
    use std::io::Write;
    io(f.write_all(bytes))?;
    io(f.sync_all())
}
fn raw_boot_backup(device: &str, destination: &Path, disk_bytes: u64) -> Result<()> {
    let length = 1024 * 1024;
    if disk_bytes < 2 * length {
        return Err(Error::new("disk too small for boot preservation"));
    }
    let mut f = io(File::open(device))?;
    let mut buffer = vec![0u8; length as usize];
    io(f.read_exact(&mut buffer))?;
    write_backup_file(&destination.join("disk-first-1MiB.bin"), &buffer)?;
    io(f.seek(SeekFrom::Start(disk_bytes - length)))?;
    io(f.read_exact(&mut buffer))?;
    write_backup_file(&destination.join("disk-last-1MiB.bin"), &buffer)
}

fn installed_wifi(c: &Commands, enabled: bool) -> Result<Option<String>> {
    if !enabled {
        return Ok(None);
    }
    use std::io::{self, Write};
    print!(
        "Installed Wi-Fi SSID (personal WPA; blank means configure later from the admin console): "
    );
    files::io(io::stdout().flush())?;
    let ssid = cancellation::read_line()?;
    let ssid = ssid.trim_end_matches(['\r', '\n']);
    if ssid.is_empty() {
        println!(
            "No Wi-Fi credentials will be carried into the installed system. Keep Ethernet connected or configure Wi-Fi from the local admin console."
        );
        return Ok(None);
    }
    let bytes = cancellation::password(c, "Installed Wi-Fi passphrase:")?;
    let password =
        String::from_utf8(bytes).map_err(|_| Error::new("Wi-Fi password must be UTF-8"))?;
    assbox_config::wifi_keyfile(ssid, password.trim_end_matches(['\r', '\n'])).map(Some)
}

pub fn apply(plan: InstallPlan, release_tag: Option<&str>) -> Result<()> {
    cancellation::install_handlers()?;
    let result = apply_inner(plan, release_tag);
    if result.is_err() {
        eprintln!(
            "Installation did not complete. Inspect /run/assbox-install and the target's .assbox-install.json. Do not reboot into an incomplete target or delete its files blindly; see docs/install-recovery.md."
        );
    }
    result
}

fn validate_ssh_keys(c: &Commands, admin: Option<&str>, agent: Option<&str>) -> Result<()> {
    for (role, key) in [("admin", admin), ("agent", agent)] {
        if let Some(key) = key {
            c.input("ssh-keygen", &["-l", "-f", "-"], key.as_bytes())
                .map_err(|error| {
                    Error::new(format!("{role} SSH public key validation failed: {error}"))
                })?;
        }
    }
    Ok(())
}

fn apply_inner(plan: InstallPlan, release_tag: Option<&str>) -> Result<()> {
    files::require_root()?;
    if !Path::new("/etc/NIXOS").exists() {
        return Err(Error::new(
            "run the installer from trusted NixOS live media",
        ));
    }
    let c = Commands;
    for tool in [
        "nix",
        "systemd-run",
        "systemctl",
        "nixos-install",
        "nixos-generate-config",
        "nix-instantiate",
        "nixfmt",
        "lsblk",
        "findmnt",
        "mount",
        "umount",
        "mountpoint",
        "e2fsck",
        "fsck.fat",
        "fsck.exfat",
        "sfdisk",
        "tar",
        "sha256sum",
        "stat",
        "sync",
        "mkpasswd",
        "systemd-ask-password",
    ] {
        c.executable(tool)?;
    }
    if plan.boot() == BootKind::AppleRefind {
        c.executable("efibootmgr")?;
    }
    if plan.inventory().disk(&plan.root().parent)?.table == Table::Gpt {
        c.executable("sgdisk")?;
    }
    validate_ssh_keys(
        &c,
        plan.request().choices.admin_ssh_key.as_deref(),
        plan.request().choices.agent_ssh_key.as_deref(),
    )?;
    let _lock = Lock::acquire(Path::new("/run/assbox-install.lock"))?;
    files::create_private(Path::new(WORK))?;
    // nixos-install rejects non-traversable ancestors of --root. Only this empty
    // parent is public; the generated machine tree and secrets remain private.
    io(fs::set_permissions(WORK, fs::Permissions::from_mode(0o755)))?;
    if io(fs::read_dir(WORK))?.next().is_some() {
        return Err(Error::new(
            "installer work directory is not empty; inspect/unmount a previous attempt before continuing",
        ));
    }
    let fetched = crate::source::resolve(&c, release_tag, &point("release-download"))?;
    let flake = assbox_config::flake(&fetched.release.manifest, plan.inventory().architecture);
    recheck(&plan, &c, &[])?;
    let selected: Vec<&Partition> = std::iter::once(plan.root())
        .chain(plan.esp())
        .chain(std::iter::once(plan.backup()))
        .collect();
    // All selected filesystems are checked before the first mount, including backup.
    for p in selected {
        recheck(&plan, &c, &[])?;
        let (program, flags) = filesystem_check(p.fs)?;
        let mut args = flags.to_vec();
        args.push(&p.path);
        c.run(program, &args)?;
    }
    recheck(&plan, &c, &[])?;
    let mut root_probe = Mount::new(
        &c,
        &plan.root().path,
        &point("root-check"),
        "ro,noload,nosuid,nodev,noexec",
    )?;
    let mut esp_probe = if let Some(esp) = plan.esp() {
        Some(Mount::new(
            &c,
            &esp.path,
            &point("esp-check"),
            "ro,nosuid,nodev,noexec",
        )?)
    } else {
        None
    };
    if files::entry_exists(&root_probe.point.join(".assbox-install.json"))? {
        return Err(Error::new(
            "target contains an installation record; incomplete or existing installations require inspection, never automatic resume",
        ));
    }
    assbox_policy::validate_prepared_root(&files::prepared_root_entries(&root_probe.point)?)?;
    let apple = plan.boot() == BootKind::AppleRefind;
    let before_esp = match &esp_probe {
        Some(esp) => esp_manifest(&c, &esp.point, apple)?,
        None => BTreeMap::new(),
    };
    if !apple && !before_esp.is_empty() {
        return Err(Error::new(
            "generic UEFI installation requires an empty dedicated ESP; shared-ESP preservation is the Apple profile only",
        ));
    }
    if apple {
        let name = before_esp.keys().find(|p| p.eq_ignore_ascii_case("EFI/refind/refind_x64.efi"))
            .ok_or_else(|| Error::new("standard rEFInd EFI application not found; this installer does not install or replace rEFInd"))?;
        let image_path = esp_probe
            .as_ref()
            .ok_or_else(|| Error::new("missing Apple ESP"))?
            .point
            .join(name);
        files::regular(&image_path)?;
        if io(fs::metadata(&image_path))?.len() > 32 * 1024 * 1024 {
            return Err(Error::new("rEFInd image exceeds inspection limit"));
        }
        let image = io(fs::read(&image_path))?;
        assbox_policy::efi::validate_refind_image(name, &image)?;
    }
    let before_table = c.capture("sfdisk", &["--json", &plan.root().parent])?;
    let firmware = if apple {
        c.capture("efibootmgr", &["-v"])?
    } else {
        Vec::new()
    };
    // Authenticate and evaluate the pinned machine graph before target writes.
    // The full closure is built in the target store after backup verification.
    let config = point("machine");
    files::create_private(&config)?;
    let hardware = c.text(
        "nixos-generate-config",
        &[
            "--root",
            files::path_text(&root_probe.point)?,
            "--no-filesystems",
            "--show-hardware-config",
        ],
    )?;
    for (name, content) in [
        ("flake.nix", flake),
        ("hardware-configuration.nix", hardware),
        ("storage.nix", assbox_config::storage(&plan)),
        (
            "assbox-settings.nix",
            assbox_config::settings(&plan.request().choices)?,
        ),
        (
            "assbox-packages.nix",
            assbox_config::packages(&plan.request().choices.additional_packages),
        ),
        ("local.nix", assbox_config::LOCAL.to_owned()),
    ] {
        files::atomic_write(&config.join(name), content.as_bytes(), 0o644)?;
    }
    files::atomic_write(&config.join("flake.lock"), &fetched.machine_lock, 0o644)?;
    files::atomic_write(
        &config.join("assbox-release.json"),
        &fetched.release.manifest_bytes,
        0o644,
    )?;
    c.run(
        "nixfmt",
        &[files::path_text(
            &config.join("hardware-configuration.nix"),
        )?],
    )?;
    c.run(
        "nix-instantiate",
        &[
            "--parse",
            files::path_text(&config.join("hardware-configuration.nix"))?,
        ],
    )?;
    #[cfg(test)]
    crate::acceptance::install_configuration(&config)?;
    // Ask real Nix to validate the rebased graph; it is forbidden to update pins.
    let local = format!("path:{}", files::path_text(&config)?);
    c.run("nix", &["flake", "lock", "--no-update-lock-file", &local])?;
    crate::source::verify_local_lock(&c, &config, &fetched.release.manifest)?;
    crate::check_evaluation(&c, &local)?;
    let mut configuration = configuration_snapshot(&config)?;
    let configuration_digest = configuration_digest(&c, &configuration)?;
    let mut mounts = vec![&root_probe];
    if let Some(e) = &esp_probe {
        mounts.push(e);
    }
    recheck(&plan, &c, &mounts)?;
    let backup_options = if plan.backup().fs == FileSystem::Ext4 {
        "rw,nosuid,nodev,noexec"
    } else {
        "rw,nosuid,nodev,noexec,uid=0,gid=0,fmask=0177,dmask=0077"
    };
    let mut backup = Mount::new(&c, &plan.backup().path, &point("backup"), backup_options)?;
    let available = c.text(
        "stat",
        &["-f", "--format=%a %S", files::path_text(&backup.point)?],
    )?;
    let values: Vec<u64> = available
        .split_whitespace()
        .map(|s| {
            s.parse::<u64>()
                .map_err(|_| Error::new("invalid backup free-space result"))
        })
        .collect::<Result<_>>()?;
    // Count all GNU tar headers, directory entries and long paths while the ESP
    // is read-only. Reserve bounded command output, raw boot/table metadata and
    // backup filesystem allocation slack in addition to the exact archive size.
    let tar_bytes = match &esp_probe {
        Some(esp) => c.output_size(
            "tar",
            &[
                "--create",
                "--file",
                "-",
                "--one-file-system",
                "--directory",
                files::path_text(&esp.point)?,
                ".",
            ],
        )?,
        None => 0,
    };
    let required = tar_bytes
        .checked_add(128 * 1024 * 1024)
        .ok_or_else(|| Error::new("backup size overflow"))?;
    if values.len() != 2
        || values[0]
            .checked_mul(values[1])
            .is_none_or(|free| free < required)
    {
        return Err(Error::new(
            "backup lacks room for the full ESP plus boot/table metadata",
        ));
    }
    let backup_name = format!("assbox-{}", files::random_id()?);
    let archive = backup.point.join(&backup_name);
    io(fs::create_dir(&archive))?;
    if plan.backup().fs == FileSystem::Ext4 {
        io(fs::set_permissions(
            &archive,
            fs::Permissions::from_mode(0o700),
        ))?;
    }
    write_backup_file(&archive.join("partition-table.json"), &before_table)?;
    write_backup_file(
        &archive.join("partition-table.sfdisk"),
        &c.capture("sfdisk", &["--dump", &plan.root().parent])?,
    )?;
    write_backup_file(&archive.join("firmware.txt"), &firmware)?;
    raw_boot_backup(
        &plan.root().parent,
        &archive,
        plan.inventory().disk(&plan.root().parent)?.bytes,
    )?;
    if plan.inventory().disk(&plan.root().parent)?.table == Table::Gpt {
        c.run(
            "sgdisk",
            &[
                &format!("--backup={}", files::path_text(&archive.join("gpt.bin"))?),
                &plan.root().parent,
            ],
        )?;
    }
    if let Some(esp) = &esp_probe {
        c.run(
            "tar",
            &[
                "--create",
                "--file",
                files::path_text(&archive.join("esp.tar"))?,
                "--one-file-system",
                "--directory",
                files::path_text(&esp.point)?,
                ".",
            ],
        )?;
    }
    let mut hashes = BTreeMap::new();
    for e in io(fs::read_dir(&archive))? {
        let e = io(e)?;
        if plan.backup().fs == FileSystem::Ext4 {
            io(fs::set_permissions(
                e.path(),
                fs::Permissions::from_mode(0o600),
            ))?;
        }
        hashes.insert(
            e.file_name().to_string_lossy().into_owned(),
            hash(&c, &e.path())?,
        );
    }
    let manifest = hashes
        .iter()
        .map(|(name, h)| format!("{h}  {name}\n"))
        .collect::<String>();
    write_backup_file(&archive.join("SHA256SUMS"), manifest.as_bytes())?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-backup-written")?;
    c.run("sync", &[])?;
    backup.unmount(&c)?;
    backup = Mount::new(
        &c,
        &plan.backup().path,
        &point("backup"),
        "ro,nosuid,nodev,noexec",
    )?;
    for (name, expected) in &hashes {
        if hash(&c, &backup.point.join(&backup_name).join(name))? != *expected {
            return Err(Error::new("external backup read-back failed"));
        }
    }
    if io(fs::read(backup.point.join(&backup_name).join("SHA256SUMS")))? != manifest.as_bytes() {
        return Err(Error::new(
            "external backup checksum manifest read-back failed",
        ));
    }
    assbox_policy::validate_prepared_root(&files::prepared_root_entries(&root_probe.point)?)?;
    root_probe.unmount(&c)?;
    if let Some(e) = &mut esp_probe {
        e.unmount(&c)?;
    }
    recheck(&plan, &c, &[&backup])?;
    // Password is obtained before target writes and never enters argv or Nix source.
    let password = cancellation::password(&c, "Choose an administrator password:")?;
    let confirm = cancellation::password(&c, "Repeat the administrator password:")?;
    if password != confirm || password.iter().filter(|b| !b.is_ascii_whitespace()).count() < 12 {
        return Err(Error::new(
            "administrator passwords must match and contain at least 12 non-whitespace characters",
        ));
    }
    let password_hash = c.input("mkpasswd", &["--method=yescrypt", "--stdin"], &password)?;
    drop(password);
    drop(confirm);
    let wifi = installed_wifi(&c, plan.request().choices.devices.wifi)?;
    recheck(&plan, &c, &[&backup])?;
    crate::release::check_freshness(&c, &fetched.release.manifest)?;
    if configuration_snapshot(&config)? != configuration {
        return Err(Error::new("configuration changed before target writes"));
    }
    let mut record = install_record(
        &c,
        &plan,
        fetched.release.floor.manifest_sha256.as_str(),
        &configuration_digest,
        &backup_name,
    )?;
    // The backup contains the durable write intent even if the first target
    // record cannot be created. This file is separate from the immutable archive.
    backup.unmount(&c)?;
    backup = Mount::new(&c, &plan.backup().path, &point("backup"), backup_options)?;
    write_backup_file(
        &backup
            .point
            .join(format!("{backup_name}-install-intent.json")),
        &record,
    )?;
    c.run("sync", &[])?;
    backup.unmount(&c)?;
    backup = Mount::new(
        &c,
        &plan.backup().path,
        &point("backup"),
        "ro,nosuid,nodev,noexec",
    )?;
    if io(fs::read(
        backup
            .point
            .join(format!("{backup_name}-install-intent.json")),
    ))? != record
    {
        return Err(Error::new("installation write intent read-back failed"));
    }
    recheck(&plan, &c, &[&backup])?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-pre-write")?;
    // FIRST TARGET WRITE: preflight and independent backup succeeded. A failed
    // build can now leave an incomplete Linux root; boot files stay read-only.
    let mut root = Mount::new(&c, &plan.root().path, &point("target"), "rw")?;
    files::atomic_write(&root.point.join(".assbox-install.json"), &record, 0o600)?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-target-writes")?;
    let mut esp = if let Some(p) = plan.esp() {
        let parent = make_dirs(&root.point, "boot")?;
        Some(Mount::new(
            &c,
            &p.path,
            &parent.join("efi"),
            "ro,nosuid,nodev,noexec",
        )?)
    } else {
        None
    };
    let mut mounts = vec![&root, &backup];
    if let Some(e) = &esp {
        mounts.push(e);
    }
    recheck(&plan, &c, &mounts)?;
    let installed_config = make_dirs(&root.point, "etc/nixos")?;
    files::copy_tree(&config, &installed_config)?;
    crate::source::verify_local_lock(&c, &installed_config, &fetched.release.manifest)?;
    if let Some(keyfile) = wifi {
        let connections = make_dirs(&root.point, "etc/NetworkManager/system-connections")?;
        io(fs::set_permissions(
            &connections,
            fs::Permissions::from_mode(0o700),
        ))?;
        files::atomic_write(
            &connections.join("assbox-wifi.nmconnection"),
            keyfile.as_bytes(),
            0o600,
        )?;
    }
    let secrets = make_dirs(&root.point, "var/lib/assbox-secrets")?;
    io(fs::set_permissions(
        &secrets,
        fs::Permissions::from_mode(0o700),
    ))?;
    files::atomic_write(&secrets.join("admin-password.hash"), &password_hash, 0o600)?;
    let state = make_dirs(&root.point, "var/lib/assbox")?;
    io(fs::set_permissions(
        &state,
        fs::Permissions::from_mode(0o700),
    ))?;
    files::atomic_write(
        &state.join("release-state"),
        fetched.release.floor.encode().as_bytes(),
        0o600,
    )?;
    // Use the upstream chroot-store mechanism and disk-backed build directory.
    let store = files::path_text(&root.point)?;
    let build_dir = make_dirs(&root.point, "var/tmp/assbox-build")?;
    let logs = make_dirs(&root.point, "var/log/assbox-install")?;
    io(fs::set_permissions(
        &logs,
        fs::Permissions::from_mode(0o700),
    ))?;
    let output_link = root.point.join(".assbox-built-system");
    let image_link = root.point.join(".assbox-sizing-system");
    let target = format!(
        "path:{}#nixosConfigurations.assbox.config.system.build.toplevel",
        files::path_text(&installed_config)?
    );
    // Both the provisional sizing build and the final build use the same
    // cancellation, retry and revalidation path. The snapshot changes only
    // after sizing resolves, never while retrying a particular build.
    let build_system = |output_link: &Path, configuration: &BTreeMap<String, Vec<u8>>| {
        build_with_retry(
            || {
                recheck(&plan, &c, &mounts)?;
                crate::release::check_freshness(&c, &fetched.release.manifest)?;
                if &configuration_snapshot(&installed_config)? != configuration {
                    return Err(Error::new(
                        "installation configuration changed; retry refused",
                    ));
                }
                Ok(())
            },
            || {
                cancellation::run(
                    &c,
                    "nix",
                    &[
                        "build",
                        "--store",
                        store,
                        "--extra-substituters",
                        "auto?trusted=1",
                        "--option",
                        "build-dir",
                        files::path_text(&build_dir)?,
                        "--out-link",
                        files::path_text(output_link)?,
                        "--print-out-paths",
                        "--no-update-lock-file",
                        "--no-write-lock-file",
                        &target,
                    ],
                    &logs,
                )
            },
            cancellation::retry_build,
        )
    };
    let mut worker_spec = plan.request().choices.worker.clone();
    if let Some(worker) = worker_spec.as_mut().filter(|w| w.auto_state) {
        write_phase(&c, &root.point, &record, "building", None)?;
        let sizing_system = build_system(&image_link, &configuration)?;
        let artifact = io(fs::read_link(
            root.point
                .join(sizing_system.trim().trim_start_matches('/'))
                .join("assbox-worker-image"),
        ))?;
        let root_bytes = assbox_system::worker::artifact_root_bytes(
            &c,
            &root.point,
            files::path_text(&artifact)?,
        )?;
        let (total, free) = assbox_system::worker::filesystem_capacity(&c, &root.point)?;
        worker.state_gib = assbox_policy::worker::automatic_state_gib(total, free, root_bytes)?;
        worker.auto_state = false;
        let settings_path = installed_config.join("assbox-settings.nix");
        let settings =
            assbox_config::worker::selection(&files::text(&settings_path)?, Some(worker))?;
        files::atomic_write(&settings_path, settings.as_bytes(), 0o644)?;
        configuration.insert("assbox-settings.nix".to_owned(), settings.into_bytes());
        let digest = self::configuration_digest(&c, &configuration)?;
        record = c.input("jq", &["--arg", "configuration", &digest, "--argjson", "capacity", &worker.state_gib.to_string(),
            ". + {requestedConfigurationSha256:.configurationSha256, configurationSha256:$configuration, resolvedWorkerStateGiB:$capacity}"], &record)?;
        write_phase(&c, &root.point, &record, "building", None)?;
        println!(
            "Resolved persistent worker capacity: {} GiB (sparse allocation).",
            worker.state_gib
        );
    }
    write_phase(&c, &root.point, &record, "building", None)?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-building")?;
    let system = build_system(&output_link, &configuration)?;
    recheck(&plan, &c, &mounts)?;
    crate::release::check_freshness(&c, &fetched.release.manifest)?;
    if configuration_snapshot(&installed_config)? != configuration {
        return Err(Error::new(
            "installation configuration changed during build",
        ));
    }
    #[cfg(test)]
    crate::acceptance::checkpoint("install-built")?;
    if let Some(worker) = &worker_spec {
        assbox_system::worker::admit_install(&c, &root.point, &system, worker.state_gib)?;
    }
    crate::boot_guard::verify_install_target_in_store(&c, &root.point, &system, &plan)?;
    crate::source::verify_local_lock(&c, &installed_config, &fetched.release.manifest)?;
    if let Some(e) = &esp
        && esp_manifest(&c, &e.point, apple)? != before_esp
    {
        return Err(Error::new("ESP changed during build"));
    }
    if c.capture("sfdisk", &["--json", &plan.root().parent])? != before_table
        || (apple && c.capture("efibootmgr", &["-v"])? != firmware)
    {
        return Err(Error::new("boot state changed during build"));
    }
    // This phase is durable before the first writable ESP mount/activation.
    write_phase(&c, &root.point, &record, "activating", Some(&system))?;
    drop(mounts);
    if let Some(e) = &mut esp {
        e.unmount(&c)?;
    }
    esp = if let Some(p) = plan.esp() {
        Some(Mount::new(
            &c,
            &p.path,
            &root.point.join("boot/efi"),
            "rw,nosuid,nodev,noexec,fmask=0077,dmask=0077",
        )?)
    } else {
        None
    };
    let mut mounts = vec![&root, &backup];
    if let Some(e) = &esp {
        mounts.push(e);
    }
    recheck(&plan, &c, &mounts)?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-activating")?;
    // Install this already-built closure. Never evaluate/refetch the machine flake here.
    cancellation::run(
        &c,
        "nixos-install",
        &[
            "--root",
            files::path_text(&root.point)?,
            "--system",
            &system,
            "--no-root-passwd",
            "--no-channel-copy",
        ],
        &logs,
    )?;
    #[cfg(test)]
    crate::acceptance::checkpoint("install-activated")?;
    c.run("sync", &[])?;
    recheck(&plan, &c, &mounts)?;
    if c.capture("sfdisk", &["--json", &plan.root().parent])? != before_table {
        return Err(Error::new(
            "partition table changed unexpectedly; retain backups and inspect before booting",
        ));
    }
    if apple {
        if c.capture("efibootmgr", &["-v"])? != firmware {
            return Err(Error::new("EFI firmware state changed unexpectedly"));
        }
        if let Some(e) = &esp
            && esp_manifest(&c, &e.point, true)? != before_esp
        {
            return Err(Error::new("unrelated EFI files changed unexpectedly"));
        }
    }
    for (name, expected) in &hashes {
        if hash(&c, &backup.point.join(&backup_name).join(name))? != *expected {
            return Err(Error::new("final backup verification failed"));
        }
    }
    files::atomic_write(&state.join("install-receipt"),format!("hostname={}\narchitecture={}\nboot={}\nsource={}\nnar-hash={}\nsystem={}\nexternal-backup={}\n",
        plan.request().choices.hostname.as_str(),plan.inventory().architecture,plan.boot(),fetched.release.manifest.source_url(),fetched.release.manifest.source_nar_hash,system,backup_name).as_bytes(),0o600)?;
    c.run("sync", &[])?;
    cancellation::check()?;
    if !io(fs::symlink_metadata(&output_link))?
        .file_type()
        .is_symlink()
    {
        return Err(Error::new("build root link changed unexpectedly"));
    }
    io(fs::remove_file(&output_link))?;
    if files::entry_exists(&image_link)? {
        if !io(fs::symlink_metadata(&image_link))?
            .file_type()
            .is_symlink()
        {
            return Err(Error::new("worker image GC root changed unexpectedly"));
        }
        io(fs::remove_file(&image_link))?;
    }
    #[cfg(test)]
    crate::acceptance::checkpoint("install-completing")?;
    write_phase(&c, &root.point, &record, "complete", Some(&system))?;
    drop(mounts);
    if let Some(e) = &mut esp {
        e.unmount(&c)?;
    }
    root.unmount(&c)?;
    backup.unmount(&c)?;
    println!(
        "Installed {}. External boot recovery copy: {backup_name}. Keep it separate from the installer. No reboot was requested.",
        plan.request().choices.hostname.as_str()
    );
    Ok(())
}

/// Each retry uses unchanged build arguments and a fresh validation of the
/// release, target mounts and captured configuration. Effects remain injectable
/// so failure/cancellation ordering can be checked without touching a disk.
fn build_with_retry(
    mut validate: impl FnMut() -> Result<()>,
    mut build: impl FnMut() -> Result<String>,
    mut retry: impl FnMut() -> Result<bool>,
) -> Result<String> {
    loop {
        validate()?;
        match build() {
            Ok(output) => {
                validate()?;
                let system = output.trim();
                if !assbox_domain::source::valid_store_system(system) {
                    return Err(Error::new(
                        "build did not return one immutable NixOS system",
                    ));
                }
                return Ok(system.to_owned());
            }
            Err(error) => {
                eprintln!(
                    "{error}. Linux root is incomplete; bootloader activation has not started."
                );
                if !retry()? {
                    return Err(error);
                }
            }
        }
    }
}

fn configuration_snapshot(directory: &Path) -> Result<BTreeMap<String, Vec<u8>>> {
    files::trusted_dir(directory)?;
    let mut result = BTreeMap::new();
    for entry in io(fs::read_dir(directory))? {
        let entry = io(entry)?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| Error::new("invalid configuration filename"))?;
        if result.len() >= 32 {
            return Err(Error::new("unexpected installation configuration entries"));
        }
        result.insert(name, files::read(&entry.path())?);
    }
    Ok(result)
}
fn configuration_digest(c: &Commands, snapshot: &BTreeMap<String, Vec<u8>>) -> Result<String> {
    let mut bytes = Vec::new();
    for (name, value) in snapshot {
        bytes.extend_from_slice(name.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(value.len().to_string().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(value);
    }
    let output = c.input("sha256sum", &["-"], &bytes)?;
    Ok(String::from_utf8(output)
        .map_err(|_| Error::new("invalid configuration hash"))?
        .split_whitespace()
        .next()
        .ok_or_else(|| Error::new("missing configuration hash"))?
        .to_owned())
}
fn install_record(
    c: &Commands,
    plan: &InstallPlan,
    manifest: &str,
    configuration: &str,
    backup: &str,
) -> Result<Vec<u8>> {
    c.capture("jq", &["-n", "--arg", "operation", &files::random_id()?,
        "--arg", "disk", &plan.inventory().disk(&plan.root().parent)?.persistent_path,
        "--arg", "root", &plan.root().uuid, "--arg", "rootPart", &plan.root().partuuid,
        "--arg", "esp", plan.esp().map_or("", |p| p.uuid.as_str()),
        "--arg", "backupDevice", &plan.backup().uuid, "--arg", "backup", backup,
        "--arg", "manifest", manifest, "--arg", "configuration", configuration,
        r#"{schema:1,operation:$operation,phase:"target-writes",disk:$disk,rootUuid:$root,rootPartUuid:$rootPart,espUuid:$esp,backupUuid:$backupDevice,backup:$backup,manifestSha256:$manifest,configurationSha256:$configuration}"#])
}
fn write_phase(
    c: &Commands,
    root: &Path,
    record: &[u8],
    phase: &str,
    system: Option<&str>,
) -> Result<()> {
    cancellation::check()?;
    let bytes = c.input(
        "jq",
        &[
            "--arg",
            "phase",
            phase,
            "--arg",
            "system",
            system.unwrap_or(""),
            ". + {phase:$phase,system:$system}",
        ],
        record,
    )?;
    files::atomic_write(&root.join(".assbox-install.json"), &bytes, 0o600)
}

#[cfg(test)]
mod build_retry_tests {
    use super::build_with_retry;
    use assbox_domain::Error;
    use std::cell::{Cell, RefCell};

    const SYSTEM: &str = "/nix/store/00000000000000000000000000000000-nixos-system-assbox-1";

    #[test]
    fn transient_failure_retries_only_after_consent_and_revalidation() {
        let events = RefCell::new(Vec::new());
        let attempts = Cell::new(0);
        let system = build_with_retry(
            || {
                events.borrow_mut().push("validate");
                Ok(())
            },
            || {
                events.borrow_mut().push("build");
                attempts.set(attempts.get() + 1);
                if attempts.get() == 1 {
                    Err(Error::new("temporary download failure"))
                } else {
                    Ok(format!("{SYSTEM}\n"))
                }
            },
            || {
                events.borrow_mut().push("retry");
                Ok(true)
            },
        )
        .unwrap();
        assert_eq!(system, SYSTEM);
        assert_eq!(
            *events.borrow(),
            [
                "validate", "build", "retry", "validate", "build", "validate"
            ]
        );
    }

    #[test]
    fn changed_state_refuses_before_first_build_retry_or_acceptance() {
        for fail_at in 1..=3 {
            let checks = Cell::new(0);
            let attempts = Cell::new(0);
            let error = build_with_retry(
                || {
                    checks.set(checks.get() + 1);
                    if checks.get() == fail_at {
                        Err(Error::new("changed configuration, release or mounts"))
                    } else {
                        Ok(())
                    }
                },
                || {
                    attempts.set(attempts.get() + 1);
                    if attempts.get() == 1 {
                        Err(Error::new("temporary download failure"))
                    } else {
                        Ok(SYSTEM.to_owned())
                    }
                },
                || Ok(true),
            )
            .unwrap_err();
            assert!(error.to_string().starts_with("changed configuration"));
            assert_eq!(attempts.get(), fail_at - 1);
        }
    }

    #[test]
    fn decline_or_cancellation_never_starts_another_build() {
        for cancelled in [false, true] {
            let attempts = Cell::new(0);
            let error = build_with_retry(
                || Ok(()),
                || {
                    attempts.set(attempts.get() + 1);
                    Err(Error::new("build failure"))
                },
                || {
                    if cancelled {
                        Err(Error::new("cancelled"))
                    } else {
                        Ok(false)
                    }
                },
            )
            .unwrap_err();
            assert_eq!(attempts.get(), 1);
            assert_eq!(
                error.to_string(),
                if cancelled {
                    "cancelled"
                } else {
                    "build failure"
                }
            );
        }
    }

    #[test]
    fn invalid_success_output_is_not_accepted_or_retried() {
        for output in [
            String::new(),
            "/tmp/system".to_owned(),
            format!("{SYSTEM}\n{SYSTEM}"),
        ] {
            let result = build_with_retry(
                || Ok(()),
                || Ok(output.clone()),
                || panic!("invalid output must not prompt for a retry"),
            );
            assert!(
                result
                    .unwrap_err()
                    .to_string()
                    .contains("one immutable NixOS system")
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Disposable public fixtures; no corresponding private keys are retained.
    const ADMIN: &str = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0rTdA8CAqpAJnL7hXFaKhMCqfeJQ7ODLrjU+Y5Vkoi assbox-test-admin";
    const AGENT: &str = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ4/WMI73Pf/077tLNv52VqJs/KH+scPNdll11LPumZ6 assbox-test-agent";

    #[test]
    fn ssh_preflight_accepts_optional_distinct_role_keys() {
        for (admin, agent) in [
            (None, None),
            (Some(ADMIN), None),
            (None, Some(AGENT)),
            (Some(ADMIN), Some(AGENT)),
        ] {
            validate_ssh_keys(&Commands, admin, agent).unwrap();
        }
    }

    #[test]
    fn ssh_preflight_rejects_malformed_keys_for_either_role() {
        let bad = "ssh-ed25519 truncated-key";
        for (admin, agent, role) in [
            (Some(bad), Some(AGENT), "admin"),
            (Some(ADMIN), Some(bad), "agent"),
            (None, Some(bad), "agent"),
        ] {
            let error = validate_ssh_keys(&Commands, admin, agent)
                .unwrap_err()
                .to_string();
            assert!(
                error.starts_with(&format!("{role} SSH public key validation failed:")),
                "{error}"
            );
            assert!(!error.contains(bad));
        }
    }
}
