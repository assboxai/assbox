// SPDX-License-Identifier: GPL-3.0-or-later
//! Profile provenance and policy requests; provider observations enter as values.
use crate::{Component, Components, Error, Presentation, Result, worker::WorkerNetwork};
use std::{fmt, str::FromStr};
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum Purpose {
    Assistant,
    Coder,
    Kiosk,
    #[default]
    Custom,
}
impl Purpose {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Assistant => "assistant",
            Self::Coder => "coder",
            Self::Kiosk => "kiosk",
            Self::Custom => "custom",
        }
    }
}
impl fmt::Display for Purpose {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}
impl FromStr for Purpose {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "assistant" => Ok(Self::Assistant),
            "coder" => Ok(Self::Coder),
            "kiosk" => Ok(Self::Kiosk),
            "custom" => Ok(Self::Custom),
            _ => Err(Error::new("choose assistant, coder, kiosk, or custom")),
        }
    }
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ComputerUse {
    #[default]
    None,
    Browser,
    VirtualDesktop,
}
impl ComputerUse {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Browser => "browser",
            Self::VirtualDesktop => "virtual-desktop",
        }
    }
}
impl FromStr for ComputerUse {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "none" => Ok(Self::None),
            "browser" => Ok(Self::Browser),
            "virtual-desktop" => Ok(Self::VirtualDesktop),
            _ => Err(Error::new("choose none, browser, or virtual-desktop")),
        }
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstanceConfig {
    pub purpose: Purpose,
    pub preset: String,
    pub revision: u32,
    pub exclusions: Components,
    pub tailscale: bool,
    pub egress: WorkerNetwork,
    pub computer_use: ComputerUse,
    pub protected_code: bool,
    pub execution_in_worker: bool,
    pub web_apps: Vec<String>,
    pub hermes_public_url: String,
    pub hermes_tunnel_only: bool,
    pub dashboard_serve: bool,
}
impl Default for InstanceConfig {
    fn default() -> Self {
        Self {
            purpose: Purpose::Custom,
            preset: "custom".into(),
            revision: 1,
            exclusions: Components::default(),
            tailscale: false,
            egress: WorkerNetwork::Internet,
            computer_use: ComputerUse::None,
            protected_code: false,
            execution_in_worker: false,
            web_apps: vec![],
            hermes_public_url: String::new(),
            hermes_tunnel_only: false,
            dashboard_serve: false,
        }
    }
}
impl InstanceConfig {
    pub fn validate(&self) -> Result<()> {
        if !PRESETS
            .iter()
            .any(|p| p.id == self.preset && p.purpose == self.purpose)
            || self.revision == 0
        {
            return Err(Error::new("unknown preset provenance"));
        }
        if self
            .web_apps
            .iter()
            .any(|a| !matches!(a.as_str(), "chatgpt" | "claude"))
            || self
                .web_apps
                .iter()
                .enumerate()
                .any(|(i, a)| self.web_apps[..i].contains(a))
        {
            return Err(Error::new("invalid web kiosk applications"));
        }
        if !self.hermes_public_url.is_empty()
            && (!self.hermes_public_url.starts_with("https://")
                || !self
                    .hermes_public_url
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b":/._-".contains(&b))
                || self.hermes_public_url.contains("localhost")
                || self.hermes_public_url.contains("127.0.0.1"))
        {
            return Err(Error::new(
                "Hermes requires an exact non-loopback HTTPS public URL",
            ));
        }
        if self.dashboard_serve
            && (!self.tailscale || self.hermes_tunnel_only || self.hermes_public_url.is_empty())
        {
            return Err(Error::new(
                "managed dashboard HTTPS requires Tailscale and an authenticated public URL",
            ));
        }
        Ok(())
    }
}
#[derive(Debug)]
pub struct Preset {
    pub id: &'static str,
    pub purpose: Purpose,
    pub revision: u32,
    pub components: &'static [Component],
    pub presentation: Presentation,
    pub tailscale: bool,
    pub workload_ssh: bool,
    pub web_apps: &'static [&'static str],
}

pub use crate::preset_ids::PRESETS;
impl Preset {
    pub fn find(id: &str) -> Result<&'static Self> {
        PRESETS
            .iter()
            .find(|p| p.id == id)
            .ok_or_else(|| Error::new("unknown instance preset"))
    }
    pub fn config(&self) -> InstanceConfig {
        InstanceConfig {
            purpose: self.purpose,
            preset: self.id.into(),
            revision: self.revision,
            tailscale: self.tailscale,
            web_apps: self.web_apps.iter().map(|s| (*s).into()).collect(),
            ..Default::default()
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativePolicyState {
    Verified,
    Pending,
    Unsupported,
    Ineffective,
    Stale,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NativePolicyObservation {
    pub app: Component,
    pub state: NativePolicyState,
    pub complete_inventory: bool,
    pub matching_scope: bool,
}
impl NativePolicyObservation {
    pub fn permits_activation(&self) -> bool {
        self.state == NativePolicyState::Verified && self.complete_inventory && self.matching_scope
    }
}
