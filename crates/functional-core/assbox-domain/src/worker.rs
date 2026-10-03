// SPDX-License-Identifier: GPL-3.0-or-later
//! Explicit worker choices and controller hardware observations. No probing or activation here.
use crate::{Component, Components, Error, Presentation, Result};
use core::net::Ipv4Addr;
use std::{fmt, str::FromStr};

pub const GIB: u64 = 1024 * 1024 * 1024;
/// Minimum free space after budgeting the worker's full writable capacity.
/// Automatic sizing leaves a larger, consumable controller growth budget.
pub const STORAGE_ADMISSION_RESERVE: u64 = 8 * GIB;
/// Initial sizing budget, including the admission floor. The remainder can be
/// consumed by later controller generations without shrinking the worker.
pub fn storage_reserve(total_bytes: u64) -> u64 {
    (32 * GIB).max(total_bytes / 5)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerNetwork {
    Normal,
    Internet,
    Offline,
}

impl WorkerNetwork {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Normal => "normal",
            Self::Internet => "internet",
            Self::Offline => "offline",
        }
    }
    pub fn default_dns(self) -> Vec<String> {
        if self == Self::Offline {
            vec![]
        } else {
            vec!["1.1.1.1".into(), "9.9.9.9".into()]
        }
    }
    pub fn allows_dns(self, text: &str) -> bool {
        let Ok(ip) = text.parse::<Ipv4Addr>() else {
            return false;
        };
        let [a, b, c, _] = ip.octets();
        if self == Self::Offline
            || a == 0
            || a == 127
            || a >= 224
            || (a == 169 && b == 254)
            || (a == 192 && b == 0 && (c == 0 || c == 2))
            || (a == 198 && (b == 18 || b == 19 || (b == 51 && c == 100)))
            || (a == 203 && b == 0 && c == 113)
            || (u32::from(ip) & !3 == u32::from(Ipv4Addr::new(10, 77, 0, 0)))
        {
            return false;
        }
        self == Self::Normal || !(ip.is_private() || (a == 100 && (64..=127).contains(&b)))
    }
}
impl fmt::Display for WorkerNetwork {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}
impl FromStr for WorkerNetwork {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "normal" => Ok(Self::Normal),
            "internet" => Ok(Self::Internet),
            "offline" => Ok(Self::Offline),
            _ => Err(Error::new("choose normal, internet, or offline networking")),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSpec {
    pub components: Components,
    pub mutable_components: Components,

    pub memory_mib: u32,
    pub vcpus: u32,
    pub state_gib: u32,
    /// Transient construction request. Resolved to concrete state_gib before publication.
    pub auto_state: bool,
    pub uplinks: Vec<String>,
    pub network: WorkerNetwork,
    pub nameservers: Vec<String>,
    pub guest_sudo: bool,
}

pub fn valid_interface(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 15
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
}

impl WorkerSpec {
    pub fn validate(&self, accept_unfree: bool) -> Result<()> {
        if self.components == Components::default() {
            return Err(Error::new(
                "select at least one worker component explicitly",
            ));
        }
        self.components
            .validate(Presentation::Headless, accept_unfree)?;
        if self
            .components
            .iter()
            .any(|component| !component.worker_allowed())
        {
            return Err(Error::new(
                "selected component is not an execution-worker component",
            ));
        }
        if self
            .mutable_components
            .iter()
            .any(|c| !self.components.contains(c))
        {
            return Err(Error::new(
                "mutable-code consent must name selected worker components",
            ));
        }
        for component in self.components.iter() {
            if component.mutable_code() && !self.mutable_components.contains(component) {
                return Err(Error::new(format!(
                    "{component} requires explicit mutable-code consent"
                )));
            }
        }
        if !(2048..=65536).contains(&self.memory_mib)
            || !(1..=32).contains(&self.vcpus)
            || !(8..=2048).contains(&self.state_gib)
        {
            return Err(Error::new("worker resources exceed supported bounds"));
        }
        if (self.network == WorkerNetwork::Offline) != self.uplinks.is_empty()
            || self
                .uplinks
                .iter()
                .any(|s| !valid_interface(s) || s == "ab-worker0")
            || self
                .uplinks
                .iter()
                .enumerate()
                .any(|(i, s)| self.uplinks[..i].contains(s))
        {
            return Err(Error::new(
                "choose --offline or distinct explicit --uplink interfaces",
            ));
        }
        if (self.network == WorkerNetwork::Offline) != self.nameservers.is_empty()
            || self.nameservers.iter().any(|s| !self.network.allows_dns(s))
        {
            return Err(Error::new(
                "DNS resolvers must be IPv4 addresses permitted by the worker network policy",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerHardware {
    pub memory_mib: u64,
    pub cpus: u32,
    pub free_gib: u64,
    pub existing_state_gib: Option<u32>,
    pub kvm_available: bool,
    pub uplinks: Vec<String>,
}

/// Curated controller UI packages only. This does not disable bundled Desktop tools.
pub fn controller_components(selected: Components) -> Components {
    let mut result = Components::default();
    for c in selected.iter() {
        if c.controller_allowed() {
            result.insert(c);
        }
    }
    result
}

/// Product placement is separate from provider permissions or Desktop tooling.
/// A privileged administrator can change Nix; no supported controller-execution bypass.
pub fn validate_host_selection(host: Components, worker: Option<&WorkerSpec>) -> Result<()> {
    let sensitive =
        host.contains(Component::ChatgptDesktop) || host.contains(Component::ClaudeDesktop);
    if (sensitive || worker.is_some()) && host.iter().any(|c| !c.controller_allowed()) {
        return Err(Error::new(
            "execution components cannot share the native controller; select them in the worker or use standalone",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn network_dns_authority_is_explicit() {
        for ip in ["10.1.2.3", "192.168.1.1", "172.16.0.1", "100.100.100.100"] {
            assert!(WorkerNetwork::Normal.allows_dns(ip));
            assert!(!WorkerNetwork::Internet.allows_dns(ip));
        }
        for ip in [
            "10.77.0.1",
            "10.77.0.2",
            "127.0.0.1",
            "169.254.169.254",
            "224.0.0.1",
            "::1",
            "1.2.3.999",
        ] {
            assert!(!WorkerNetwork::Normal.allows_dns(ip));
        }
        assert!(WorkerNetwork::Internet.allows_dns("1.1.1.1"));
        assert!(!WorkerNetwork::Offline.allows_dns("1.1.1.1"));
    }
    fn spec() -> WorkerSpec {
        WorkerSpec {
            components: "vim".parse().unwrap(),
            mutable_components: Components::default(),

            memory_mib: 3072,
            vcpus: 2,
            state_gib: 32,
            auto_state: false,
            uplinks: vec![],
            network: WorkerNetwork::Offline,
            nameservers: vec![],
            guest_sudo: false,
        }
    }
    #[test]
    fn explicit_selection_and_role_separation() {
        let s = spec();
        assert!(s.validate(false).is_ok());
        assert_eq!(
            controller_components("codex,chatgpt-desktop,vim".parse().unwrap()).to_string(),
            "chatgpt-desktop"
        );
        let mut s = s;
        s.components = Components::default();
        assert!(s.validate(true).is_err());
        s.components = "chatgpt-desktop".parse().unwrap();
        assert!(s.validate(true).is_err());
        s.components = "claude-code-remote".parse().unwrap();
        assert!(s.validate(true).is_err());
    }
    #[test]
    fn controller_placement_is_mandatory() {
        let host: Components = "chatgpt-desktop,chatgpt-remote".parse().unwrap();
        assert!(validate_host_selection(host, None).is_ok());
        assert!(validate_host_selection(host, Some(&spec())).is_ok());
        let mut worker = spec();
        worker.components = "codex,claude-code,grok,antigravity-cli,cursor-agent,opencode,pi,omp"
            .parse()
            .unwrap();
        assert!(worker.validate(true).is_ok());
        assert!(validate_host_selection(host, Some(&worker)).is_ok());
        assert!(
            validate_host_selection(
                "chatgpt-desktop,claude-code".parse().unwrap(),
                Some(&worker)
            )
            .is_err()
        );
        assert!(validate_host_selection("claude-desktop".parse().unwrap(), Some(&worker)).is_ok());
        assert!(validate_host_selection("opencode".parse().unwrap(), None).is_ok());
    }
    #[test]
    fn mutable_consent_is_per_selected_component() {
        let mut s = spec();
        s.mutable_components = "codex".parse().unwrap();
        assert!(s.validate(true).is_err());
        s.components = "vscode-remote-host".parse().unwrap();
        s.mutable_components = Components::default();
        assert!(s.validate(true).is_err());
        s.mutable_components = s.components;
        assert!(s.validate(true).is_ok());
    }
    #[test]
    fn resources_are_bounded() {
        for (memory, cpus, disk) in [
            (2047, 2, 32),
            (65537, 2, 32),
            (3072, 0, 32),
            (3072, 33, 32),
            (3072, 2, 7),
            (3072, 2, 2049),
        ] {
            let mut s = spec();
            s.memory_mib = memory;
            s.vcpus = cpus;
            s.state_gib = disk;
            assert!(s.validate(false).is_err());
        }
        for (memory, cpus, disk) in [(2048, 1, 8), (65536, 32, 2048)] {
            let mut s = spec();
            s.memory_mib = memory;
            s.vcpus = cpus;
            s.state_gib = disk;
            assert!(s.validate(false).is_ok());
        }
    }
    #[test]
    fn network_selection_is_explicit_and_bounded() {
        for name in ["", "0123456789012345", "eth0;id", "en0.1", "a b", "é"] {
            assert!(!valid_interface(name));
        }
        assert!(valid_interface("enp0s1"));
        assert!(valid_interface("veth_a-b"));
        let mut s = spec();
        s.network = "internet".parse().unwrap();
        s.nameservers = s.network.default_dns();
        assert!(s.validate(false).is_err());
        s.uplinks = vec!["eth0".into()];
        assert!(s.validate(false).is_ok());
        s.network = "offline".parse().unwrap();
        s.nameservers.clear();
        assert!(s.validate(false).is_err());
        s.network = "internet".parse().unwrap();
        s.nameservers = s.network.default_dns();
        for uplinks in [
            vec!["ab-worker0".into()],
            vec!["bad;".into()],
            vec!["eth0".into(), "eth0".into()],
        ] {
            s.uplinks = uplinks;
            assert!(s.validate(false).is_err());
        }
    }
}
