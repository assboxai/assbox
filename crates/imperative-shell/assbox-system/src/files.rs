// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{Error, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

pub fn io<T>(result: std::io::Result<T>) -> Result<T> {
    result.map_err(|e| Error::new(e.to_string()))
}
pub fn require_root() -> Result<()> {
    let text = io(fs::read_to_string("/proc/self/status"))?;
    let uid = text
        .lines()
        .find(|s| s.starts_with("Uid:"))
        .and_then(|s| s.split_whitespace().nth(2));
    if uid != Some("0") {
        return Err(Error::new(
            "this operation requires root; use sudo as an administrator",
        ));
    }
    Ok(())
}
pub fn random_bytes<const N: usize>() -> Result<[u8; N]> {
    let mut out = [0; N];
    io(io(File::open("/dev/urandom"))?.read_exact(&mut out))?;
    Ok(out)
}
pub fn random_id() -> Result<String> {
    Ok(random_bytes::<12>()?
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
pub fn path_text(path: &Path) -> Result<&str> {
    path.to_str().ok_or_else(|| Error::new("path is not UTF-8"))
}

/// All ancestors must be root-owned, non-symlink directories and not writable by
/// other users. This is not protection against an administrator racing themselves.
pub fn trusted_dir(path: &Path) -> Result<()> {
    if !path.is_absolute() {
        return Err(Error::new("expected an absolute directory"));
    }
    for p in path.ancestors() {
        let m = io(fs::symlink_metadata(p))?;
        if !m.is_dir() || m.uid() != 0 || m.mode() & 0o022 != 0 {
            return Err(Error::new(format!("untrusted directory: {}", p.display())));
        }
    }
    Ok(())
}
pub fn create_private(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        trusted_dir(parent)?;
    }
    match fs::create_dir(path) {
        Ok(()) => io(fs::set_permissions(path, fs::Permissions::from_mode(0o700)))?,
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(Error::new(e.to_string())),
    }
    trusted_dir(path)
}
pub fn regular(path: &Path) -> Result<()> {
    let m = io(fs::symlink_metadata(path))?;
    if !m.is_file() || m.uid() != 0 || m.mode() & 0o022 != 0 || m.nlink() != 1 {
        return Err(Error::new(format!(
            "expected a root-owned regular file without writable aliases: {}",
            path.display()
        )));
    }
    Ok(())
}
pub fn read(path: &Path) -> Result<Vec<u8>> {
    regular(path)?;
    let m = io(fs::metadata(path))?;
    if m.len() > 16 * 1024 * 1024 {
        return Err(Error::new("configuration file is too large"));
    }
    io(fs::read(path))
}
pub fn text(path: &Path) -> Result<String> {
    String::from_utf8(read(path)?).map_err(|_| Error::new("configuration is not UTF-8"))
}

/// Only a missing directory entry is absent state. In particular, a dangling
/// symlink is present and observation failures must not authorize an effect.
pub fn entry_exists(path: &Path) -> Result<bool> {
    // ENOENT may describe a missing/dangling ancestor rather than this entry.
    if !path.is_absolute() {
        return Err(Error::new("state observation requires an absolute path"));
    }
    let parent = path
        .parent()
        .ok_or_else(|| Error::new("state path has no parent"))?;
    for ancestor in parent.ancestors() {
        let metadata = io(fs::symlink_metadata(ancestor))?;
        if !metadata.is_dir() {
            return Err(Error::new(format!(
                "invalid state ancestor: {}",
                ancestor.display()
            )));
        }
    }
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(Error::new(format!(
            "cannot inspect {}: {e}",
            path.display()
        ))),
    }
}
/// State deletion must validate the entry and durably publish its absence.
pub fn remove_regular(path: &Path) -> Result<()> {
    let parent = path.parent().ok_or_else(|| Error::new("missing parent"))?;
    trusted_dir(parent)?;
    regular(path)?;
    io(fs::remove_file(path))?;
    io(io(File::open(parent))?.sync_all())
}
pub fn atomic_write(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::new("file has no parent"))?;
    trusted_dir(parent)?;
    if entry_exists(path)? {
        regular(path)?;
    }
    let temp = parent.join(format!(".assbox-write-{}", random_id()?));
    let result = (|| {
        let mut f = io(OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(mode)
            .open(&temp))?;
        io(f.write_all(bytes))?;
        io(f.sync_all())?;
        io(fs::rename(&temp, path))?;
        io(File::open(parent))?
            .sync_all()
            .map_err(|e| Error::new(e.to_string()))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

pub struct Lock {
    _file: File,
}
impl Lock {
    pub fn acquire(path: &Path) -> Result<Self> {
        trusted_dir(
            path.parent()
                .ok_or_else(|| Error::new("lock parent missing"))?,
        )?;
        if entry_exists(path)? {
            regular(path)?;
        }
        let f = io(OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(path))?;
        regular(path)?;
        f.try_lock()
            .map_err(|e| Error::new(format!("another Assbox operation holds the lock: {e}")))?;
        Ok(Self { _file: f })
    }
}

pub fn copy_tree(source: &Path, destination: &Path) -> Result<()> {
    trusted_dir(source)?;
    create_private(destination)?;
    let mut count = 0;
    copy_entries(source, destination, &mut count)?;
    io(File::open(destination))?
        .sync_all()
        .map_err(|e| Error::new(e.to_string()))
}
fn copy_entries(source: &Path, dest: &Path, count: &mut usize) -> Result<()> {
    for entry in io(fs::read_dir(source))? {
        let entry = io(entry)?;
        if entry.file_name() == ".git" {
            continue;
        }
        *count += 1;
        if *count > 10000 {
            return Err(Error::new(
                "local configuration tree exceeds 10,000 entries",
            ));
        }
        let src = entry.path();
        let dst = dest.join(entry.file_name());
        let m = io(fs::symlink_metadata(&src))?;
        if m.is_dir() {
            trusted_dir(&src)?;
            create_private(&dst)?;
            copy_entries(&src, &dst, count)?;
            io(File::open(&dst))?
                .sync_all()
                .map_err(|e| Error::new(e.to_string()))?;
        } else {
            let bytes = read(&src)?;
            atomic_write(&dst, &bytes, m.mode() & 0o777)?;
        }
    }
    Ok(())
}

// Kept at this import path for orchestration; ownership is implemented separately.
pub use crate::mounts::Mount;

/// Publish an already-complete private tree. No partially initialized journal is live.
pub fn publish_directory(prepared: &Path, destination: &Path) -> Result<()> {
    let parent = destination
        .parent()
        .ok_or_else(|| Error::new("directory has no parent"))?;
    trusted_dir(parent)?;
    trusted_dir(prepared)?;
    if prepared.parent() != Some(parent) || entry_exists(destination)? {
        return Err(Error::new(
            "journal publication requires an absent sibling destination",
        ));
    }
    io(File::open(prepared))?
        .sync_all()
        .map_err(|e| Error::new(e.to_string()))?;
    io(fs::rename(prepared, destination))?;
    io(File::open(parent))?
        .sync_all()
        .map_err(|e| Error::new(e.to_string()))
}

/// Retire atomically before deletion: a crash during cleanup cannot leave a broken
/// active journal. Orphaned preparation/retirement trees contain no live operation.
pub fn retire_directory(path: &Path) -> Result<PathBuf> {
    let parent = path
        .parent()
        .ok_or_else(|| Error::new("directory has no parent"))?;
    trusted_dir(path)?;
    let retired = parent.join(format!("transaction-retired-{}", random_id()?));
    trusted_dir(parent)?;
    if entry_exists(&retired)? {
        return Err(Error::new("retirement name occupied"));
    }
    io(fs::rename(path, &retired))?;
    io(File::open(parent))?
        .sync_all()
        .map_err(|e| Error::new(e.to_string()))?;
    Ok(retired)
}

/// Complete cleanup only after the active journal name has been durably retired.
pub fn remove_retired_directory(retired: &Path) -> Result<()> {
    let parent = retired
        .parent()
        .ok_or_else(|| Error::new("directory has no parent"))?;
    trusted_dir(parent)?;
    trusted_dir(retired)?;
    io(fs::remove_dir_all(retired))?;
    io(File::open(parent))?
        .sync_all()
        .map_err(|e| Error::new(e.to_string()))
}

/// Read a bounded root-directory observation without following symlinks. More
/// than one entry already disqualifies an empty prepared filesystem in policy.
pub fn prepared_root_entries(root: &Path) -> Result<Vec<assbox_domain::PreparedRootEntry>> {
    let root_metadata = io(fs::symlink_metadata(root))?;
    if !root_metadata.is_dir() {
        return Err(Error::new("prepared root mount is not a directory"));
    }
    let mut observed = Vec::new();
    for entry in io(fs::read_dir(root))?.take(2) {
        let entry = io(entry)?;
        let metadata = io(fs::symlink_metadata(entry.path()))?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| Error::new("non-UTF8 entry in prepared root"))?;
        let empty =
            if name == "lost+found" && metadata.is_dir() && metadata.dev() == root_metadata.dev() {
                io(fs::read_dir(entry.path()))?
                    .next()
                    .transpose()
                    .map_err(|e| Error::new(e.to_string()))?
                    .is_none()
            } else {
                false
            };
        observed.push(assbox_domain::PreparedRootEntry {
            name,
            is_directory: metadata.is_dir(),
            owner: metadata.uid(),
            group: metadata.gid(),
            mode: metadata.mode(),
            same_filesystem: metadata.dev() == root_metadata.dev(),
            empty,
        });
    }
    Ok(observed)
}

/// The generated receipt is one absolute store symlink. Resolve that link in the
/// selected chroot store, never through the live machine's /nix/store.
pub fn target_store_receipt(root: &Path, system: &str) -> Result<Vec<u8>> {
    if !root.is_absolute() || !assbox_domain::source::valid_store_system(system) {
        return Err(Error::new("invalid target store or generation"));
    }
    let system_path = root.join(system.trim_start_matches('/'));
    if io(fs::canonicalize(&system_path))? != system_path {
        return Err(Error::new(
            "target store generation uses a filesystem alias",
        ));
    }
    let link = io(fs::read_link(system_path.join("assbox-boot-policy.json")))?;
    let name = link
        .strip_prefix("/nix/store")
        .map_err(|_| Error::new("receipt escapes target store"))?;
    if name.components().count() != 1
        || !matches!(
            name.components().next(),
            Some(std::path::Component::Normal(_))
        )
    {
        return Err(Error::new("receipt is not a store object"));
    }
    let path = root.join("nix/store").join(name);
    if io(fs::canonicalize(&path))? != path || !io(fs::symlink_metadata(&path))?.is_file() {
        return Err(Error::new("receipt uses a filesystem alias"));
    }
    if io(fs::metadata(&path))?.len() > 65536 {
        return Err(Error::new("oversized boot receipt"));
    }
    io(fs::read(path))
}
