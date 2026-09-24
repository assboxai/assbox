// SPDX-License-Identifier: GPL-3.0-or-later
use crate::{Error, Result};
use core::net::IpAddr;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum SshExposure {
    #[default]
    Tailscale,
    Lan,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SshAccess {
    pub exposure: SshExposure,
    pub interfaces: Vec<String>,
    pub source_cidrs: Vec<String>,
}

pub fn valid_cidr(s: &str) -> bool {
    let Some((ip, prefix)) = s.split_once('/') else {
        return false;
    };
    // Match the declarative firewall grammar, including canonical decimal
    // prefixes and IPv6 without embedded dotted IPv4 notation.
    if prefix.is_empty()
        || !prefix.bytes().all(|b| b.is_ascii_digit())
        || (prefix.len() > 1 && prefix.starts_with('0'))
        || (ip.contains(':') && ip.contains('.'))
    {
        return false;
    }
    let (Ok(ip), Ok(prefix)) = (ip.parse::<IpAddr>(), prefix.parse::<u8>()) else {
        return false;
    };
    prefix <= if ip.is_ipv4() { 32 } else { 128 }
}

fn valid_interface(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 15
        && name != "lo"
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.:-".contains(&b))
}

impl SshAccess {
    pub fn validate(&self, enabled: bool) -> Result<()> {
        if self.exposure == SshExposure::Lan && (!enabled || self.interfaces.is_empty()) {
            return Err(Error::new(
                "local-network SSH requires an enabled account and explicit interfaces",
            ));
        }
        if self.exposure == SshExposure::Tailscale
            && (!self.interfaces.is_empty() || !self.source_cidrs.is_empty())
        {
            return Err(Error::new(
                "LAN settings cannot accompany Tailscale-only SSH",
            ));
        }
        if self.interfaces.iter().any(|s| !valid_interface(s))
            || self.source_cidrs.iter().any(|s| !valid_cidr(s))
        {
            return Err(Error::new("invalid SSH interface or source CIDR"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn access_requires_explicit_interfaces_and_valid_sources() {
        assert!(SshAccess::default().validate(false).is_ok());
        let mut lan = SshAccess {
            exposure: SshExposure::Lan,
            ..Default::default()
        };
        assert!(lan.validate(true).is_err());
        lan.interfaces = vec!["enp0s5".into(), "vlan.10".into()];
        assert!(lan.validate(true).is_ok());
        assert!(lan.validate(false).is_err());
        for cidr in ["192.168.64.1/32", "0.0.0.0/0", "2001:db8::/32", "::1/128"] {
            lan.source_cidrs = vec![cidr.into()];
            assert!(lan.validate(true).is_ok(), "{cidr}");
        }
        for cidr in [
            "127.0.0.1",
            "192.0.2.0/033",
            "192.0.2.1/+1",
            "1.2.3.4/33",
            "::/129",
            "::ffff:192.0.2.1/128",
            "::1:/64",
        ] {
            assert!(!valid_cidr(cidr), "{cidr}");
        }
        for iface in ["lo", "", "en*", "a\neth0", "0123456789012345"] {
            assert!(!valid_interface(iface), "{iface}");
        }
        lan.exposure = SshExposure::Tailscale;
        assert!(lan.validate(true).is_err());
    }
}
