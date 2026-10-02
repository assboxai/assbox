// SPDX-License-Identifier: GPL-3.0-or-later
use crate::{Component, Error, Presentation, Result};
use std::{fmt, str::FromStr};

/// Fixed, reviewed catalog selection. No runtime plugins or command interpretation.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Components(u64);
impl Components {
    pub fn contains(self, component: Component) -> bool {
        self.0 & (1 << component as u32) != 0
    }
    pub fn insert(&mut self, component: Component) {
        self.0 |= 1 << component as u32;
    }
    pub fn remove(&mut self, component: Component) {
        self.0 &= !(1 << component as u32);
    }
    pub fn iter(self) -> impl Iterator<Item = Component> {
        Component::ALL
            .iter()
            .copied()
            .filter(move |c| self.contains(*c))
    }
    pub fn with_dependencies(self) -> Self {
        let mut expanded = self;
        loop {
            let previous = expanded;
            for component in previous.iter() {
                for dependency in component.dependencies() {
                    expanded.insert(*dependency);
                }
            }
            if expanded == previous {
                return expanded;
            }
        }
    }
    pub fn validate(self, presentation: Presentation, unfree: bool) -> Result<()> {
        for component in self.iter() {
            if !component.blocked().is_empty() {
                return Err(Error::new(format!("{component}: {}", component.blocked())));
            }
            if !component.presentations().contains(&presentation) {
                return Err(Error::new(format!(
                    "{component} does not support {presentation}"
                )));
            }
            for dependency in component.dependencies() {
                if !self.contains(*dependency) {
                    return Err(Error::new(format!(
                        "{component} requires explicit selection of {dependency}"
                    )));
                }
            }
            if component.unfree() && !unfree {
                return Err(Error::new(format!(
                    "{component} requires explicit proprietary-package consent"
                )));
            }
        }
        Ok(())
    }
}
impl From<Component> for Components {
    fn from(value: Component) -> Self {
        let mut result = Self::default();
        result.insert(value);
        result
    }
}
impl FromStr for Components {
    type Err = Error;
    fn from_str(text: &str) -> Result<Self> {
        let mut result = Self::default();
        if text.is_empty() || text == "none" {
            return Ok(result);
        }
        for name in text.split(',') {
            let component = name.parse()?;
            if result.contains(component) {
                return Err(Error::new("duplicate component"));
            }
            result.insert(component);
        }
        Ok(result)
    }
}
impl fmt::Display for Components {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let names: Vec<_> = self.iter().map(Component::as_str).collect();
        f.write_str(&names.join(","))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dependencies_are_expanded_only_when_requested() {
        let chosen: Components = "cursor-worker,claude-code-remote".parse().unwrap();
        assert!(chosen.validate(Presentation::Headless, true).is_err());
        let expanded = chosen.with_dependencies();
        assert!(expanded.contains(Component::CursorAgent));
        assert!(expanded.contains(Component::ClaudeCode));
        assert!(!chosen.contains(Component::CursorAgent));
        assert!(expanded.validate(Presentation::Headless, true).is_ok());
        assert!(expanded.validate(Presentation::Headless, false).is_err());
    }
    #[test]
    fn canonical_roundtrip_and_invalid_inputs() {
        let selected: Components = "vim,codex,pi,omp".parse().unwrap();
        assert_eq!(selected.to_string(), "codex,omp,pi,vim");
        assert_eq!(
            selected.to_string().parse::<Components>().unwrap(),
            selected
        );
        for bad in ["codex,codex", "none,codex", "unknown", "${x}", "codex,"] {
            assert!(bad.parse::<Components>().is_err(), "{bad}");
        }
        assert_eq!(Component::ALL.len(), 33);
    }
    #[test]
    fn blocked_remotes_and_graphical_requirements_are_not_overridden_by_consent() {
        for id in ["happy", "happy-remote", "gemini-cli", "cowork-dispatch"] {
            assert!(id.parse::<Components>().is_err());
        }
        let chatgpt: Components = "codex,chatgpt-desktop".parse().unwrap();
        assert!(chatgpt.validate(Presentation::Headless, true).is_err());
        assert!(chatgpt.validate(Presentation::X11, true).is_ok());
    }
}
