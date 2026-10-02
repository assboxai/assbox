// SPDX-License-Identifier: GPL-3.0-or-later
//! One-time resolution; no account access, filesystem callbacks or live defaults.
use assbox_domain::{
    Component, Components, Error, Presentation, Result,
    instances::{InstanceConfig, NativePolicyObservation, Preset},
};
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedInstance {
    pub config: InstanceConfig,
    pub host: Components,
    pub worker: Components,
    pub presentation: Presentation,
    pub workload_ssh: bool,
}
pub fn resolve(
    id: &str,
    selected: Option<Components>,
    exclusions: Components,
    protected_code: bool,
) -> Result<ResolvedInstance> {
    let p = Preset::find(id)?;
    let mut cs = selected.unwrap_or_else(|| {
        let mut s = Components::default();
        for c in p.components {
            s.insert(*c);
        }
        s
    });
    for c in exclusions.iter() {
        cs.remove(c);
    }
    let expanded = cs.with_dependencies();
    if expanded.iter().any(|c| exclusions.contains(c)) {
        return Err(Error::new(
            "explicit exclusion conflicts with a required dependency",
        ));
    }
    cs = expanded;
    let mut host = Components::default();
    let mut worker = Components::default();
    let sensitive = cs.iter().any(|c| {
        matches!(
            c,
            Component::ChatgptDesktop | Component::ClaudeDesktop | Component::ChatgptRemote
        )
    }) || !p.web_apps.is_empty();
    if protected_code && !sensitive {
        return Err(Error::new(
            "protected local Code requires a selected kiosk application",
        ));
    }
    for c in cs.iter() {
        if sensitive && !c.controller_allowed() {
            return Err(Error::new(format!(
                "{c} is execution-side; choose standalone or place tools in a managed worker explicitly"
            )));
        }
        host.insert(c);
    }
    if protected_code {
        if host.contains(Component::ChatgptDesktop) {
            worker.insert(Component::Codex);
        }
        if host.contains(Component::ClaudeDesktop) {
            worker.insert(Component::ClaudeCode);
        }
        if worker == Components::default() {
            return Err(Error::new(
                "protected Code requires a selected native coding application",
            ));
        }
    }
    if id.starts_with("kiosk-") && !sensitive {
        return Err(Error::new("select at least one kiosk application"));
    }
    let mut config = p.config();
    config.exclusions = exclusions;
    config.protected_code = protected_code;
    config.execution_in_worker = protected_code;
    Ok(ResolvedInstance {
        config,
        host,
        worker,
        presentation: p.presentation,
        workload_ssh: p.workload_ssh,
    })
}
pub fn ready_native_apps(
    selected: Components,
    observations: &[NativePolicyObservation],
) -> Components {
    let mut ready = Components::default();
    for c in [Component::ChatgptDesktop, Component::ClaudeDesktop] {
        if selected.contains(c) {
            let rows: Vec<_> = observations.iter().filter(|o| o.app == c).collect();
            if rows.len() == 1 && rows[0].permits_activation() {
                ready.insert(c);
            }
        }
    }
    ready
}
#[cfg(test)]
mod tests {
    use super::*;
    use assbox_domain::instances::*;
    #[test]
    fn presets_resolve_without_implicit_expansion_after_install() {
        let r = resolve("coder-codex-ssh", None, Components::default(), false).unwrap();
        assert_eq!(r.host.to_string(), "codex");
        assert_eq!(r.worker, Components::default());
        assert!(r.workload_ssh);
        let r = resolve("assistant-hermes", None, Component::Pi.into(), false).unwrap();
        assert!(!r.host.contains(Component::Pi));
        assert_eq!(
            r.host
                .iter()
                .filter(|c| matches!(
                    c,
                    Component::Codex
                        | Component::ClaudeCode
                        | Component::AntigravityCli
                        | Component::CursorAgent
                        | Component::Grok
                        | Component::Opencode
                        | Component::Pi
                        | Component::Omp
                ))
                .count(),
            7
        );
        assert!(resolve("assistant-hermes", None, Component::Hermes.into(), false).is_err());
    }
    #[test]
    fn kiosk_staging_is_distinct_from_activation() {
        let r = resolve("kiosk-native", None, Components::default(), false).unwrap();
        assert_eq!(r.worker, Components::default());
        assert_eq!(ready_native_apps(r.host, &[]), Components::default());
        let o = NativePolicyObservation {
            app: Component::ChatgptDesktop,
            state: NativePolicyState::Verified,
            complete_inventory: true,
            matching_scope: true,
        };
        assert_eq!(
            ready_native_apps(r.host, std::slice::from_ref(&o)),
            Component::ChatgptDesktop.into()
        );
        let mut stale = o;
        stale.matching_scope = false;
        assert_eq!(ready_native_apps(r.host, &[stale]), Components::default());
        let r = resolve("kiosk-native", None, Components::default(), true).unwrap();
        assert_eq!(r.worker.to_string(), "claude-code,codex");
    }
}
