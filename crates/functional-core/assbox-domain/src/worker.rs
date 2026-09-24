// SPDX-License-Identifier: GPL-3.0-or-later
//! Explicit worker choices and controller hardware observations. No probing or activation here.
use crate::{Component, Components, Error, Presentation, Result};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSpec {
    pub components: Components,
    pub mutable_components: Components,
    pub memory_mib: u32,
    pub vcpus: u32,
    pub state_gib: u32,
    pub uplinks: Vec<String>,
    pub offline: bool,
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
        if self.offline != self.uplinks.is_empty()
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
    let sensitive = host.iter().any(Component::requires_worker);
    if sensitive && worker.is_none() {
        return Err(Error::new(
            "sensitive controller components require a managed worker; no local-execution fallback",
        ));
    }
    if (sensitive || worker.is_some()) && host.iter().any(|c| !c.controller_allowed()) {
        return Err(Error::new(
            "component is not approved for the thin controller; select it in the worker or use a separate standalone deployment",
        ));
    }
    if host.contains(Component::ChatgptDesktop)
        && !worker.is_some_and(|w| w.components.contains(Component::Codex))
    {
        return Err(Error::new(
            "the ChatGPT controller requires explicitly selected Codex inside the worker",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn spec() -> WorkerSpec {
        WorkerSpec {
            components: "vim".parse().unwrap(),
            mutable_components: Components::default(),
            memory_mib: 3072,
            vcpus: 2,
            state_gib: 32,
            uplinks: vec![],
            offline: true,
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
        assert!(validate_host_selection(host, None).is_err());
        assert!(validate_host_selection(host, Some(&spec())).is_err());
        let mut worker = spec();
        worker.components =
            "codex,claude-code,grok,antigravity-cli,cursor-agent,opencode,gemini-cli"
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
        assert!(validate_host_selection("claude-desktop".parse().unwrap(), Some(&worker)).is_err());
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
        s.offline = false;
        assert!(s.validate(false).is_err());
        s.uplinks = vec!["eth0".into()];
        assert!(s.validate(false).is_ok());
        s.offline = true;
        assert!(s.validate(false).is_err());
        s.offline = false;
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
