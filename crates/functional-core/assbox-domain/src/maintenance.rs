// SPDX-License-Identifier: GPL-3.0-or-later
//! Durable reboot intent and acceptance. Boot identity distinguishes a reboot from live switches.
use crate::{Error, Result, source::valid_store_system};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootId(String);
impl BootId {
    pub fn parse(value: &str) -> Result<Self> {
        if value.len() != 36
            || !value.bytes().enumerate().all(|(i, c)| {
                if [8, 13, 18, 23].contains(&i) {
                    c == b'-'
                } else {
                    c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
                }
            })
        {
            return Err(Error::new("invalid kernel boot identity"));
        }
        Ok(Self(value.to_owned()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PendingReboot {
    system: String,
    origin_boot_id: Option<BootId>,
}
impl PendingReboot {
    pub fn new(system: &str, boot_id: BootId) -> Result<Self> {
        if !valid_store_system(system) {
            return Err(Error::new("invalid pending reboot generation"));
        }
        Ok(Self {
            system: system.to_owned(),
            origin_boot_id: Some(boot_id),
        })
    }
    pub fn parse(text: &str) -> Result<Self> {
        // Older installations stored only the generation. Require the booted
        // generation when consuming these; all subsequent writes use v1.
        if valid_store_system(text) {
            return Ok(Self {
                system: text.to_owned(),
                origin_boot_id: None,
            });
        }
        let fields: Vec<_> = text.split('\n').collect();
        match fields.as_slice() {
            ["assbox-pending-reboot-v1", system, boot_id, ""] => {
                Self::new(system, BootId::parse(boot_id)?)
            }
            _ => Err(Error::new("invalid pending reboot record")),
        }
    }
    pub fn encode(&self) -> String {
        match &self.origin_boot_id {
            Some(id) => format!(
                "assbox-pending-reboot-v1\n{}\n{}\n",
                self.system,
                id.as_str()
            ),
            None => self.system.clone(),
        }
    }
    pub fn system(&self) -> &str {
        &self.system
    }
    pub fn origin_boot_id(&self) -> Option<&BootId> {
        self.origin_boot_id.as_ref()
    }
}

/// Records completed boot acceptance, not provider authentication or attestation.
/// A retry may reuse it only without pending intent and for the same system/boot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BootAcceptance {
    system: String,
    boot_id: BootId,
}
impl BootAcceptance {
    pub fn new(system: &str, boot_id: BootId) -> Result<Self> {
        if !valid_store_system(system) {
            return Err(Error::new("invalid accepted boot generation"));
        }
        Ok(Self {
            system: system.to_owned(),
            boot_id,
        })
    }
    pub fn parse(text: &str) -> Result<Self> {
        let fields: Vec<_> = text.split('\n').collect();
        match fields.as_slice() {
            ["assbox-boot-acceptance-v1", system, boot_id, ""] => {
                Self::new(system, BootId::parse(boot_id)?)
            }
            _ => Err(Error::new("invalid boot acceptance record")),
        }
    }
    pub fn encode(&self) -> String {
        format!(
            "assbox-boot-acceptance-v1\n{}\n{}\n",
            self.system,
            self.boot_id.as_str()
        )
    }
    pub fn matches(&self, system: &str, boot_id: &BootId) -> bool {
        self.system == system && self.boot_id == *boot_id
    }
}
