// SPDX-License-Identifier: GPL-3.0-or-later
//! Observations and bounded calls into a generation-bound worker helper.
use crate::{
    commands::{Commands, valid_store_system},
    files::{self, io},
};
use assbox_domain::{
    Error, Result,
    worker::{WorkerHardware, valid_interface},
};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

fn immutable(path: &Path) -> Result<PathBuf> {
    let target = io(fs::canonicalize(path))?;
    if !target.starts_with("/nix/store") || !io(fs::metadata(&target))?.is_file() {
        return Err(Error::new(
            "worker authority must be an immutable store file",
        ));
    }
    Ok(target)
}

pub fn hardware(c: &Commands) -> Result<WorkerHardware> {
    let memory = io(fs::read_to_string("/proc/meminfo"))?;
    let memory_mib = memory
        .lines()
        .find(|l| l.starts_with("MemTotal:"))
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|v| v.parse::<u64>().ok())
        .ok_or_else(|| Error::new("cannot determine host physical RAM"))?
        / 1024;
    let cpus = std::thread::available_parallelism()
        .map_err(|e| Error::new(e.to_string()))?
        .get()
        .min(u32::MAX as usize) as u32;
    let kvm = c.text(
        "python3",
        &[
            "-c",
            r#"
import fcntl, os
try:
    fd = os.open('/dev/kvm', os.O_RDWR | os.O_CLOEXEC)
    try:
        ready = fcntl.ioctl(fd, 0xAE00, 0) == 12
    finally:
        os.close(fd)
except OSError:
    ready = False
print('ready' if ready else 'unavailable')
"#,
        ],
    )?;
    let disk_path = if Path::new("/var/lib/assbox-worker-data").exists() {
        "/var/lib/assbox-worker-data"
    } else {
        "/var/lib"
    };
    let df = c.text("df", &["--block-size=1", "--output=avail", disk_path])?;
    let free_gib = df
        .lines()
        .nth(1)
        .and_then(|s| s.trim().parse::<u64>().ok())
        .ok_or_else(|| Error::new("cannot determine worker filesystem free space"))?
        / (1024 * 1024 * 1024);
    let routes = c.capture("ip", &["-j", "-4", "route", "show", "default"])?;
    let uplinks = c.jq_fields(
        &routes,
        r#"[.[] | .dev // empty] | unique | .[] | . + "\u0000""#,
    )?;
    if uplinks.iter().any(|name| !valid_interface(name)) {
        return Err(Error::new("invalid interface in host route observation"));
    }
    let state = Path::new("/var/lib/assbox-worker-data/home.raw");
    let existing_state_gib = match fs::symlink_metadata(state) {
        Ok(meta) => {
            let gib = 1024_u64 * 1024 * 1024;
            if !meta.file_type().is_file()
                || meta.len() % gib != 0
                || !(8..=2048).contains(&(meta.len() / gib))
            {
                return Err(Error::new(
                    "existing worker disk is not a supported regular GiB-sized image",
                ));
            }
            Some((meta.len() / gib) as u32)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(e) => return Err(Error::new(e.to_string())),
    };
    Ok(WorkerHardware {
        memory_mib,
        cpus,
        free_gib,
        existing_state_gib,
        kvm_available: kvm.trim() == "ready",
        uplinks,
    })
}

/// Measurements only; sizing decisions belong to the pure policy layer.
pub fn filesystem_capacity(c: &Commands, path: &Path) -> Result<(u64, u64)> {
    let output = c.text(
        "df",
        &[
            "--block-size=1",
            "--output=size,avail",
            files::path_text(path)?,
        ],
    )?;
    let numbers: Vec<u64> = output
        .lines()
        .nth(1)
        .unwrap_or("")
        .split_whitespace()
        .map(|s| {
            s.parse()
                .map_err(|_| Error::new("invalid filesystem capacity"))
        })
        .collect::<Result<_>>()?;
    if numbers.len() != 2 || numbers[0] == 0 || numbers[1] > numbers[0] {
        return Err(Error::new("cannot measure target filesystem capacity"));
    }
    Ok((numbers[0], numbers[1]))
}

pub fn artifact_root_bytes(c: &Commands, store_root: &Path, artifact: &str) -> Result<u64> {
    let suffix = artifact
        .strip_prefix("/nix/store/")
        .ok_or_else(|| Error::new("invalid artifact store path"))?;
    if suffix.len() < 34
        || suffix.as_bytes()[32] != b'-'
        || suffix.contains('/')
        || !suffix
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"+._?=-".contains(&b))
    {
        return Err(Error::new("invalid artifact store path"));
    }
    let manifest = store_root
        .join("nix/store")
        .join(suffix)
        .join("manifest.json");
    let meta = io(fs::symlink_metadata(&manifest))?;
    if !meta.is_file() || meta.len() > 16384 {
        return Err(Error::new("invalid worker artifact manifest"));
    }
    let fields = c.jq_fields(&io(fs::read(manifest))?,
        r#"if .schema != 1 or (.rootVirtualBytes|type) != "number" then error("invalid manifest") else (.rootVirtualBytes|tostring) + "\u0000" end"#)?;
    let bytes = fields
        .first()
        .and_then(|s| s.parse::<u64>().ok())
        .ok_or_else(|| Error::new("invalid worker root size"))?;
    if fields.len() != 1 || !(4 * 1024 * 1024 * 1024..=2048 * 1024 * 1024 * 1024).contains(&bytes) {
        return Err(Error::new("worker root size exceeds supported bounds"));
    }
    Ok(bytes)
}

/// The running generation, not mutable /etc settings or service ordering,
/// decides whether a worker must be healthy before pending state can be cleared.
pub fn boot_health(c: &Commands, system: &str) -> Result<()> {
    if !valid_store_system(system) {
        return Err(Error::new("invalid running generation"));
    }
    let path = Path::new(system).join("assbox-worker-policy.json");
    let missing = match fs::symlink_metadata(&path) {
        Ok(_) => false,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => true,
        Err(e) => return Err(Error::new(e.to_string())),
    };
    if missing {
        // Compatibility for pre-worker generations is permitted only when no
        // worker runtime is present. Unknown worker authority always refuses.
        match fs::symlink_metadata("/etc/assbox/worker-runtime.json") {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(Error::new(e.to_string())),
            Ok(_) => {
                return Err(Error::new(
                    "worker runtime exists without a generation-bound boot policy",
                ));
            }
        }
        return Ok(());
    }
    let receipt = io(fs::read(immutable(&path)?))?;
    let fields = c.jq_fields(
        &receipt,
        r#"
        if .schema != 1 or (.enabled|type) != "boolean" then error("invalid worker receipt")
        elif .enabled then
          if (.checker|type) != "string" or (.configuration|type) != "string"
              or (.buildId|type) != "string" then error("incomplete worker receipt")
          else ["true", .checker, .configuration, .buildId] | .[] | . + "\u0000" end
        else "false\u0000" end"#,
    )?;
    if fields == ["false"] {
        return Ok(());
    }
    if fields.len() != 4 || fields[0] != "true" {
        return Err(Error::new("invalid worker boot requirement"));
    }
    let checker = immutable(Path::new(&fields[1]))?;
    let expected_config = immutable(Path::new(&fields[2]))?;
    if immutable(Path::new("/etc/assbox/worker-runtime.json"))? != expected_config {
        return Err(Error::new(
            "active worker runtime differs from the booted generation",
        ));
    }
    let config = io(fs::read(&expected_config))?;
    let configured_id = c.jq_fields(
        &config,
        r#"if .schema != 2 then error("unknown worker runtime") else .buildId + "\u0000" end"#,
    )?;
    if configured_id != [fields[3].clone()] {
        return Err(Error::new(
            "worker build identity differs from the boot receipt",
        ));
    }
    let checker = checker
        .to_str()
        .ok_or_else(|| Error::new("invalid worker helper path"))?;
    // The helper bounds hostile replies and its SSH retries. This independent
    // deadline also bounds helper failure before any transport has been opened.
    c.run(
        "timeout",
        &["--signal=TERM", "--kill-after=5s", "110s", checker, "check"],
    )
    .map_err(|_| {
        Error::new(
            "required worker health failed; pending reboot and recovery generations are retained",
        )
    })
}

/// Recheck storage using the BUILT candidate's artifact before publication or
/// activation, including ordinary updates and rollback commits. No guest runs.
pub fn admit_candidate(c: &Commands, system: &str) -> Result<()> {
    if !valid_store_system(system) {
        return Err(Error::new("invalid candidate generation"));
    }
    let policy = Path::new(system).join("assbox-worker-policy.json");
    if !files::entry_exists(&policy)? {
        if files::entry_exists(Path::new("/etc/assbox/worker-runtime.json"))? {
            return Err(Error::new(
                "worker deployment cannot stage a generation without worker policy",
            ));
        }
        return Ok(());
    }
    let receipt = io(fs::read(immutable(&policy)?))?;
    let fields = c.jq_fields(
        &receipt,
        r#"
        if .schema != 1 or (.enabled|type) != "boolean" then error("invalid worker policy")
        elif .enabled then [.checker, .configuration, .buildId] | .[] | . + "\u0000"
        else "false\u0000" end"#,
    )?;
    if fields == ["false"] {
        return Ok(());
    }
    if fields.len() != 3 {
        return Err(Error::new("invalid candidate worker policy"));
    }
    let checker = immutable(Path::new(&fields[0]))?;
    let configuration = immutable(Path::new(&fields[1]))?;
    let config = io(fs::read(&configuration))?;
    let identity = c.jq_fields(
        &config,
        r#"if .schema != 2 then error("invalid runtime") else .buildId + "\u0000" end"#,
    )?;
    if identity != [fields[2].clone()] {
        return Err(Error::new(
            "candidate artifact identity differs from its policy",
        ));
    }
    c.run(
        "timeout",
        &[
            "--signal=TERM",
            "--kill-after=5s",
            "60s",
            files::path_text(&checker)?,
            "--configuration",
            files::path_text(&configuration)?,
            "admit",
        ],
    )
    .map_err(|_| {
        Error::new("candidate worker storage admission failed; deployment was not published")
    })
}

/// A fresh installation uses a target chroot store. Measure that filesystem,
/// not the live installer's /var/lib, before touching bootloader activation.
pub fn admit_install(c: &Commands, root: &Path, system: &str, state_gib: u32) -> Result<()> {
    if !valid_store_system(system) || !(8..=2048).contains(&state_gib) {
        return Err(Error::new("invalid install worker admission input"));
    }
    let link = root
        .join(system.trim_start_matches('/'))
        .join("assbox-worker-image");
    let target = io(fs::read_link(link))?;
    let virtual_bytes = artifact_root_bytes(c, root, files::path_text(&target)?)?;
    let (_, free) = filesystem_capacity(c, root)?;
    let required = virtual_bytes
        + u64::from(state_gib) * assbox_domain::worker::GIB
        + assbox_domain::worker::STORAGE_ADMISSION_RESERVE;
    if free < required {
        return Err(Error::new(
            "target lacks space for worker state and a fully dirtied root; bootloader not activated",
        ));
    }
    Ok(())
}

/// Boot retries are transient. Do not stop the service that currently owns the
/// management lock; only stop future timer wakeups after completed acceptance.
pub fn quiesce_boot_retry(c: &Commands, system: &str) -> Result<()> {
    if !valid_store_system(system) {
        return Err(Error::new("invalid accepted generation"));
    }
    let path = Path::new(system).join("assbox-worker-policy.json");
    if !files::entry_exists(&path)? {
        return Ok(());
    }
    let receipt = io(fs::read(immutable(&path)?))?;
    let enabled = c.jq_fields(&receipt,
        r#"if .schema != 1 or (.enabled|type) != "boolean" then error("invalid worker policy") else (.enabled|tostring) + "\u0000" end"#)?;
    if enabled == ["false"] {
        return Ok(());
    }
    if enabled != ["true"] {
        return Err(Error::new("invalid worker retry policy"));
    }
    c.run(
        "systemctl",
        &["stop", "--no-block", "assbox-worker-boot-retry.timer"],
    )
}

pub fn run(action: &str) -> Result<()> {
    if !matches!(
        action,
        "status" | "doctor" | "check" | "start" | "stop" | "setup-ssh" | "login" | "shell"
    ) {
        return Err(Error::new("unknown worker operation"));
    }
    let helper =
        immutable(Path::new("/run/current-system/sw/bin/assbox-worker")).map_err(|_| {
            Error::new(
                "worker tools are not installed; use sudo assbox worker configure or local.nix",
            )
        })?;
    if matches!(action, "check" | "start" | "stop") {
        files::require_root()?;
    }
    let mut command = Command::new(helper);
    command
        .arg(action)
        .env_clear()
        .env("PATH", Commands::path())
        .env("LC_ALL", "C.UTF-8");
    if let Ok(term) = std::env::var("TERM")
        && !term.is_empty()
        && term.len() <= 64
        && term
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-+.".contains(&b))
    {
        command.env("TERM", term);
    }
    let status = command
        .stdin(Stdio::inherit())
        .status()
        .map_err(|e| Error::new(e.to_string()))?;
    if status.success() {
        Ok(())
    } else {
        Err(Error::new("worker operation failed"))
    }
}
