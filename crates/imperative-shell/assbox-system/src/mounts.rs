// SPDX-License-Identifier: GPL-3.0-or-later
//! Owned Linux mounts. A provisional lease exists immediately after mount succeeds.
use crate::{
    commands::Commands,
    files::{self, io},
};
use assbox_domain::{Error, Result};
use std::{
    fs,
    os::unix::fs::{FileTypeExt, MetadataExt},
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, PartialEq, Eq)]
struct Identity {
    id: u64,
    major_minor: String,
    root: String,
}

// Effect injection belongs only in the shell; it permits real fault tests of the
// acquisition/cleanup algorithm without mounting devices in a Cargo unit test.
trait Backend {
    fn observe(&self, point: &Path) -> Result<Vec<Identity>>;
    fn mount(&self, device: &str, point: &Path, options: &str) -> Result<()>;
    fn unmount(&self, point: &Path) -> Result<()>;
}
struct LinuxBackend;
impl Backend for LinuxBackend {
    fn observe(&self, point: &Path) -> Result<Vec<Identity>> {
        parse_mountinfo(&io(fs::read_to_string("/proc/self/mountinfo"))?, point)
    }
    fn mount(&self, device: &str, point: &Path, options: &str) -> Result<()> {
        Commands.run(
            "mount",
            &["-o", options, "--", device, files::path_text(point)?],
        )
    }
    fn unmount(&self, point: &Path) -> Result<()> {
        Commands.run("umount", &["--", files::path_text(point)?])
    }
}
fn unescape(text: &str) -> Result<String> {
    let bytes = text.as_bytes();
    let mut output = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'\\' {
            let chunk = bytes
                .get(i + 1..i + 4)
                .ok_or_else(|| Error::new("short mountinfo escape"))?;
            if !chunk.iter().all(|b| (b'0'..=b'7').contains(b)) {
                return Err(Error::new("invalid mountinfo escape"));
            }
            let value = (u16::from(chunk[0] - b'0') * 64)
                + (u16::from(chunk[1] - b'0') * 8)
                + u16::from(chunk[2] - b'0');
            output.push(u8::try_from(value).map_err(|_| Error::new("invalid mountinfo byte"))?);
            i += 4;
        } else {
            output.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(output).map_err(|_| Error::new("mount path is not UTF-8"))
}
fn parse_mountinfo(text: &str, point: &Path) -> Result<Vec<Identity>> {
    let mut result = Vec::new();
    for line in text.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.len() < 10 || !fields.contains(&"-") {
            return Err(Error::new("invalid kernel mountinfo record"));
        }
        if Path::new(&unescape(fields[4])?) == point {
            result.push(Identity {
                id: fields[0]
                    .parse()
                    .map_err(|_| Error::new("invalid mount ID"))?,
                major_minor: fields[2].into(),
                root: unescape(fields[3])?,
            });
        }
    }
    Ok(result)
}
struct Lease<B: Backend> {
    backend: B,
    device: String,
    major_minor: String,
    point: PathBuf,
    mount_id: Option<u64>,
    mounted: bool,
}
impl<B: Backend> Lease<B> {
    fn acquire(
        backend: B,
        device: &str,
        major_minor: String,
        point: &Path,
        options: &str,
    ) -> Result<Self> {
        if !backend.observe(point)?.is_empty() {
            return Err(Error::new("mount destination is already mounted"));
        }
        backend.mount(device, point, options)?;
        // No fallible operation between successful mount and owning its cleanup.
        let mut lease = Self {
            backend,
            device: device.into(),
            major_minor,
            point: point.into(),
            mount_id: None,
            mounted: true,
        };
        let identity = lease.owned_identity()?;
        lease.mount_id = Some(identity.id);
        Ok(lease)
    }
    fn owned_identity(&self) -> Result<Identity> {
        let observations = self.backend.observe(&self.point)?;
        let [identity] = observations.as_slice() else {
            return Err(Error::new(
                "mount is missing or overmounted; inspect manually",
            ));
        };
        if identity.major_minor != self.major_minor
            || identity.root != "/"
            || self.mount_id.is_some_and(|id| id != identity.id)
        {
            return Err(Error::new(
                "mount ownership changed; refusing to unmount a replacement",
            ));
        }
        Ok(identity.clone())
    }
    fn release(&mut self) -> Result<()> {
        if self.mounted {
            self.owned_identity()?;
            self.backend.unmount(&self.point)?;
            self.mounted = false;
        }
        Ok(())
    }
}
impl<B: Backend> Drop for Lease<B> {
    fn drop(&mut self) {
        if self.mounted
            && let Err(error) = self.release()
        {
            eprintln!(
                "Assbox cleanup: {error}; inspect {} manually",
                self.point.display()
            );
        }
    }
}

pub struct Mount {
    lease: Lease<LinuxBackend>,
    pub point: PathBuf,
}
impl Mount {
    pub fn new(_commands: &Commands, device: &str, point: &Path, options: &str) -> Result<Self> {
        files::create_private(point)?;
        let metadata = io(fs::metadata(device))?;
        if !metadata.file_type().is_block_device() {
            return Err(Error::new("selected mount source is not a block device"));
        }
        let rdev = metadata.rdev();
        // Linux dev_t layout, common to x86-64 and AArch64; no libc/unsafe required.
        let major = ((rdev >> 8) & 0xfff) | ((rdev >> 32) & 0xfffff000);
        let minor = (rdev & 0xff) | ((rdev >> 12) & 0xffffff00);
        let lease = Lease::acquire(
            LinuxBackend,
            device,
            format!("{major}:{minor}"),
            point,
            options,
        )?;
        Ok(Self {
            lease,
            point: point.into(),
        })
    }
    pub fn device(&self) -> &str {
        &self.lease.device
    }
    pub fn unmount(&mut self, _commands: &Commands) -> Result<()> {
        self.lease.release()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::RefCell, rc::Rc};
    #[derive(Default)]
    struct State {
        mounted: bool,
        reads: usize,
        mounts: usize,
        unmounts: usize,
        fail_read: Option<usize>,
        replacement: bool,
        fail_unmount: bool,
    }
    struct Fake(Rc<RefCell<State>>);
    impl Backend for Fake {
        fn observe(&self, _: &Path) -> Result<Vec<Identity>> {
            let mut s = self.0.borrow_mut();
            s.reads += 1;
            if s.fail_read == Some(s.reads) {
                return Err(Error::new("injected observation failure"));
            }
            Ok(if s.mounted {
                vec![Identity {
                    id: 10,
                    major_minor: if s.replacement { "8:99" } else { "8:1" }.into(),
                    root: "/".into(),
                }]
            } else {
                vec![]
            })
        }
        fn mount(&self, _: &str, _: &Path, _: &str) -> Result<()> {
            let mut s = self.0.borrow_mut();
            s.mounted = true;
            s.mounts += 1;
            Ok(())
        }
        fn unmount(&self, _: &Path) -> Result<()> {
            let mut s = self.0.borrow_mut();
            s.unmounts += 1;
            if s.fail_unmount {
                return Err(Error::new("injected unmount failure"));
            }
            s.mounted = false;
            Ok(())
        }
    }
    #[test]
    fn failure_immediately_after_mount_still_owns_cleanup() {
        let state = Rc::new(RefCell::new(State {
            fail_read: Some(2),
            ..State::default()
        }));
        assert!(
            Lease::acquire(
                Fake(state.clone()),
                "/dev/test",
                "8:1".into(),
                Path::new("/owned"),
                "ro"
            )
            .is_err()
        );
        let s = state.borrow();
        assert_eq!(s.mounts, 1);
        assert_eq!(s.unmounts, 1);
        assert!(!s.mounted);
    }
    #[test]
    fn failed_preflight_never_mounts() {
        let state = Rc::new(RefCell::new(State {
            fail_read: Some(1),
            ..State::default()
        }));
        assert!(
            Lease::acquire(
                Fake(state.clone()),
                "/dev/test",
                "8:1".into(),
                Path::new("/owned"),
                "ro"
            )
            .is_err()
        );
        assert_eq!(state.borrow().mounts, 0);
    }
    #[test]
    fn successful_mount_releases_once_and_never_unmounts_a_replacement() {
        let state = Rc::new(RefCell::new(State::default()));
        let mut lease = Lease::acquire(
            Fake(state.clone()),
            "/dev/test",
            "8:1".into(),
            Path::new("/owned"),
            "ro",
        )
        .unwrap();
        lease.release().unwrap();
        drop(lease);
        assert_eq!(state.borrow().unmounts, 1);
        let mut lease = Lease::acquire(
            Fake(state.clone()),
            "/dev/test",
            "8:1".into(),
            Path::new("/owned"),
            "ro",
        )
        .unwrap();
        state.borrow_mut().replacement = true;
        assert!(lease.release().is_err());
        drop(lease);
        assert_eq!(state.borrow().unmounts, 1);
    }
    #[test]
    fn failed_cleanup_is_not_reported_as_unmounted() {
        let state = Rc::new(RefCell::new(State {
            fail_unmount: true,
            ..State::default()
        }));
        let mut lease = Lease::acquire(
            Fake(state.clone()),
            "/dev/test",
            "8:1".into(),
            Path::new("/owned"),
            "ro",
        )
        .unwrap();
        assert!(lease.release().is_err());
        assert!(state.borrow().mounted);
    }
    #[test]
    fn mountinfo_preserves_escaped_paths_and_rejects_broken_records() {
        let text = "10 1 8:1 / /run/a\\040b ro - ext4 /dev/test ro\n";
        assert_eq!(
            parse_mountinfo(text, Path::new("/run/a b")).unwrap()[0].id,
            10
        );
        assert!(parse_mountinfo("bad", Path::new("/run/a b")).is_err());
        assert!(unescape("\\777").is_err());
    }
}
