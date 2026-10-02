// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
//! Values, validated names, and explicit observations. No environment access.

pub mod hardware;
pub mod instances;
pub mod maintenance;
mod preset_ids;
pub mod release;
pub use hardware::{Hardware, PciNetworkDevice, WirelessInterface};
pub use maintenance::{BootAcceptance, BootId, PendingReboot};
use std::{error::Error as StdError, fmt, str::FromStr};

pub mod source;
pub use source::Revision;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);
impl Error {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl StdError for Error {}
pub type Result<T> = std::result::Result<T, Error>;

macro_rules! named_enum {
    ($name:ident { $($variant:ident => $value:literal),+ $(,)? }) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
        pub enum $name { $($variant),+ }
        impl $name {
            pub const fn as_str(self) -> &'static str {
                match self { $(Self::$variant => $value),+ }
            }
        }
        impl FromStr for $name {
            type Err = Error;
            fn from_str(s: &str) -> Result<Self> {
                match s { $($value => Ok(Self::$variant)),+, _ => Err(Error::new(
                    format!("invalid {}: {s}", stringify!($name)))) }
            }
        }
        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(self.as_str())
            }
        }
    }
}
named_enum!(Architecture { X86_64 => "x86_64", Aarch64 => "aarch64" });
named_enum!(BatteryPresence { Present => "present", Absent => "absent", Unknown => "unknown" });

impl Architecture {
    pub const fn nix_system(self) -> &'static str {
        match self {
            Self::X86_64 => "x86_64-linux",
            Self::Aarch64 => "aarch64-linux",
        }
    }
}

mod component_ids;
pub use component_ids::{Component, RELEASE_HELD_INPUT_CHECK};
mod components;
pub use components::Components;
named_enum!(Presentation { Headless => "headless", X11 => "x11", Wayland => "wayland" });
named_enum!(Platform { Generic => "generic", AppleIntel => "apple-intel", Macbookpro11_1 => "macbookpro11-1", Macbookpro12_1 => "macbookpro12-1" });
named_enum!(Firmware { Uefi => "uefi", Bios => "bios" });
named_enum!(Table { Gpt => "gpt", Mbr => "dos", Unknown => "unknown" });
named_enum!(FileSystem { Ext4 => "ext4", Fat => "vfat", Exfat => "exfat", None => "none", Other => "other" });
named_enum!(BootKind { Uefi => "uefi", BiosGpt => "bios-gpt", BiosMbr => "bios-mbr", AppleRefind => "apple-refind" });

impl Platform {
    pub const fn is_apple(self) -> bool {
        !matches!(self, Self::Generic)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Hostname(String);
impl Hostname {
    pub fn parse(s: &str) -> Result<Self> {
        if s.is_empty()
            || s.len() > 63
            || s.starts_with('-')
            || s.ends_with('-')
            || !s
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        {
            return Err(Error::new(
                "hostname must be 1–63 lowercase letters, digits or interior hyphens",
            ));
        }
        Ok(Self(s.to_owned()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
    /// The shell supplies uniformly distributed bytes; no machine identifier is used.
    pub fn from_entropy(bytes: [u8; 6]) -> Self {
        const ALPHABET: &[u8; 32] = b"abcdefghjkmnpqrstuvwxyz234567890";
        let suffix: String = bytes
            .iter()
            .map(|b| char::from(ALPHABET[usize::from(b & 31)]))
            .collect();
        Self(format!("assbox-{suffix}"))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct PackageName(String);
impl PackageName {
    pub fn parse(s: &str) -> Result<Self> {
        if s.len() > 200
            || s.split('.').any(|part| {
                part.is_empty()
                    || !part.as_bytes()[0].is_ascii_alphabetic() && part.as_bytes()[0] != b'_'
                    || !part
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_+-".contains(&b))
            })
        {
            return Err(Error::new(
                "use a nixpkgs attribute such as htop or python3Packages.requests",
            ));
        }
        Ok(Self(s.to_owned()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DevicePolicy {
    pub wifi: bool,
    pub audio: bool,
    pub camera: bool,
    pub bluetooth: bool,
    pub suspend: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Choices {
    pub hostname: Hostname,
    pub timezone: String,
    pub components: Components,
    pub presentation: Presentation,
    pub platform: Platform,
    pub devices: DevicePolicy,
    pub scale: u8,
    pub allow_unfree: bool,
    pub allow_mutable_code: bool,
    pub autostart: Vec<String>,
    pub admin_ssh_key: Option<String>,
    pub agent_ssh_key: Option<String>,
    pub ssh_access: access::SshAccess,
    pub additional_packages: std::collections::BTreeSet<PackageName>,
    pub worker: Option<worker::WorkerSpec>,
    pub instance: instances::InstanceConfig,
}

/// Owners of the graphical launchers supported by the installer.
pub fn installer_launcher_owner(launcher: &str) -> Result<Component> {
    match launcher {
        "chatgpt-desktop" => Ok(Component::ChatgptDesktop),
        "claude-desktop" => Ok(Component::ClaudeDesktop),
        "vscode" => Ok(Component::Vscode),
        "zed" => Ok(Component::Zed),
        "chromium" => Ok(Component::Chromium),
        "opencode-attach" => Ok(Component::OpencodeServer),
        "openclaw-dashboard" => Ok(Component::OpenclawGateway),
        _ => Err(Error::new(
            "unknown installer graphical launcher; configure GUI Emacs explicitly in local.nix",
        )),
    }
}

impl Choices {
    pub fn validate(&self) -> Result<()> {
        if !(1..=3).contains(&self.scale) {
            return Err(Error::new("display scale must be 1, 2 or 3"));
        }
        if self.timezone.is_empty()
            || self.timezone.starts_with('/')
            || self
                .timezone
                .split('/')
                .any(|s| s.is_empty() || s == "." || s == "..")
            || !self
                .timezone
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"/_+-".contains(&b))
        {
            return Err(Error::new("invalid timezone identifier"));
        }
        self.instance.validate()?;
        if self.instance.protected_code != self.worker.is_some()
            && self.instance.purpose == instances::Purpose::Kiosk
        {
            return Err(Error::new(
                "protected Code placement does not match the worker selection",
            ));
        }
        self.components
            .validate(self.presentation, self.allow_unfree)?;
        if let Some(worker) = &self.worker {
            worker.validate(self.allow_unfree)?;
        }
        worker::validate_host_selection(self.components, self.worker.as_ref())?;
        self.ssh_access
            .validate(self.admin_ssh_key.is_some() || self.agent_ssh_key.is_some())?;
        let sensitive = self.worker.is_some()
            || !self.instance.web_apps.is_empty()
            || self.components.contains(Component::ChatgptDesktop)
            || self.components.contains(Component::ClaudeDesktop);
        if sensitive && !self.additional_packages.is_empty() {
            return Err(Error::new(
                "additional controller packages are not allowed; configure tools inside the worker",
            ));
        }
        if !self.allow_mutable_code && self.components.iter().any(Component::mutable_code) {
            return Err(Error::new(
                "selected components require explicit consent to provider/client-managed executable downloads",
            ));
        }
        let mut launchers = std::collections::BTreeSet::new();
        for launcher in &self.autostart {
            let owner = installer_launcher_owner(launcher)?;
            if self.presentation == Presentation::Headless
                || !self.components.contains(owner)
                || !launchers.insert(launcher)
            {
                return Err(Error::new(
                    "graphical autostart requires a unique selected component and a headed presentation",
                ));
            }
        }
        if (self.components.contains(Component::VscodeRemoteHost)
            || self.components.contains(Component::ZedRemoteHost))
            && self.agent_ssh_key.is_none()
        {
            return Err(Error::new(
                "SSH editor hosts require an agent SSH public key",
            ));
        }
        for key in [&self.admin_ssh_key, &self.agent_ssh_key]
            .into_iter()
            .flatten()
        {
            let kind = key.split_whitespace().next().unwrap_or("");
            let known = matches!(
                kind,
                "ssh-ed25519"
                    | "ssh-rsa"
                    | "ecdsa-sha2-nistp256"
                    | "ecdsa-sha2-nistp384"
                    | "ecdsa-sha2-nistp521"
                    | "sk-ssh-ed25519@openssh.com"
                    | "sk-ecdsa-sha2-nistp256@openssh.com"
            );
            if key.contains(['\n', '\r', '\0']) || !known {
                return Err(Error::new(
                    "supply one OpenSSH public key, without authorized_keys options",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Disk {
    pub path: String,
    pub major_minor: String,
    pub bytes: u64,
    pub serial: String,
    pub model: String,
    pub persistent_path: String,
    pub table: Table,
    pub read_only: bool,
    pub hybrid_mbr: bool,
    pub mounts: Vec<String>,
    pub has_holders: bool,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Partition {
    pub path: String,
    pub parent: String,
    pub major_minor: String,
    pub bytes: u64,
    pub start_bytes: u64,
    pub fs: FileSystem,
    pub uuid: String,
    pub partuuid: String,
    pub part_type: String,
    pub mounts: Vec<String>,
    pub read_only: bool,
    pub has_holders: bool,
}
impl Partition {
    pub fn same_identity(&self, other: &Self) -> bool {
        self.path == other.path
            && self.parent == other.parent
            && self.major_minor == other.major_minor
            && self.bytes == other.bytes
            && self.start_bytes == other.start_bytes
            && self.fs == other.fs
            && self.uuid == other.uuid
            && self.partuuid == other.partuuid
            && self.part_type == other.part_type
            && self.read_only == other.read_only
            && self.has_holders == other.has_holders
    }
}
/// The boot medium is not necessarily a writable disk: VMs commonly attach an ISO
/// as a read-only optical device. Neither representation permits loop/network roots.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LiveMedia {
    Disk {
        disk: String,
        source: String,
        major_minor: String,
    },
    Optical {
        device: String,
        major_minor: String,
        bytes: u64,
        filesystem: String,
        uuid: String,
        read_only: bool,
        mounted_read_only: bool,
    },
}
impl LiveMedia {
    pub fn disk(&self) -> Option<&str> {
        match self {
            Self::Disk { disk, .. } => Some(disk),
            Self::Optical { .. } => None,
        }
    }
    pub fn source(&self) -> &str {
        match self {
            Self::Disk { source, .. } => source,
            Self::Optical { device, .. } => device,
        }
    }
    pub fn major_minor(&self) -> &str {
        match self {
            Self::Disk { major_minor, .. } | Self::Optical { major_minor, .. } => major_minor,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Inventory {
    pub architecture: Architecture,
    pub firmware: Firmware,
    pub hardware: Hardware,
    pub disks: Vec<Disk>,
    pub partitions: Vec<Partition>,
    pub live_media: LiveMedia,
}
impl Inventory {
    pub fn partition(&self, name: &str) -> Result<&Partition> {
        self.partitions
            .iter()
            .find(|p| p.path == name)
            .ok_or_else(|| Error::new(format!("not a supported physical partition: {name}")))
    }
    pub fn disk(&self, name: &str) -> Result<&Disk> {
        self.disks
            .iter()
            .find(|p| p.path == name)
            .ok_or_else(|| Error::new(format!("not a supported physical disk: {name}")))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstallRequest {
    pub root: String,
    pub esp: Option<String>,
    pub backup: String,
    pub choices: Choices,
}

/// Observations supplied by the shell, not a live timer or power interface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MaintenanceFacts {
    pub changed_generation: bool,
    pub stage_succeeded: bool,
    pub battery_presence: BatteryPresence,
    pub on_ac: Option<bool>,
    pub battery_percent: Option<u8>,
    pub minimum_battery: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootBinding {
    pub architecture: Architecture,
    pub mode: BootKind,
    pub platform: Platform,
    pub disk: String,
    pub root_device: String,
    pub esp_device: String,
    /// Canonical, evaluation-derived immutable loader/storage details.
    /// Generation limits are deliberately not part of this binding.
    pub loader: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootPolicy {
    pub generations: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootReceipt {
    pub binding: BootBinding,
    pub policy: BootPolicy,
}

/// Observed without following symlinks. Directory content is only inspected for
/// the permitted recovery directory; the shell never repairs or removes entries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedRootEntry {
    pub name: String,
    pub is_directory: bool,
    pub owner: u32,
    pub group: u32,
    pub mode: u32,
    pub same_filesystem: bool,
    pub empty: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Audit {
    pub enabled: bool,
    pub components: Components,
    pub presentation: Presentation,
    pub firewall: bool,
    pub root_locked: bool,
    pub agent_locked: bool,
    pub agent_groups: Vec<String>,
    pub trusted_users: Vec<String>,
    pub sandbox: bool,
    pub require_signatures: bool,
    pub accept_flake_config: bool,
    pub automount: bool,
    pub passwordless_sudo: bool,
    pub efi_writes: bool,
    pub boot: BootKind,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn hostname_constraints_and_privacy() {
        assert_eq!(Hostname::from_entropy([0; 6]).as_str(), "assbox-aaaaaa");
        for bad in ["", "A", "-box", "box-", "a.b", "a b", "a\n"] {
            assert!(Hostname::parse(bad).is_err(), "{bad:?}");
        }
        for b in 0..=255 {
            assert!(Hostname::parse(Hostname::from_entropy([b; 6]).as_str()).is_ok());
        }
    }
    #[test]
    fn package_inputs_cannot_be_expressions_or_options() {
        for bad in [
            "",
            "--impure",
            "a..b",
            "a; builtins.abort",
            "a${x}",
            "a/b",
            "a\n",
            "1foo",
        ] {
            assert!(PackageName::parse(bad).is_err(), "{bad:?}");
        }
        for good in ["htop", "python3Packages.requests", "git-lfs", "libstdcxx5"] {
            assert!(PackageName::parse(good).is_ok());
        }
    }
}
pub mod access;
pub mod worker;
