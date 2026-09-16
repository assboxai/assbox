// SPDX-License-Identifier: GPL-3.0-or-later
//! A core revision is an immutable commit, never an update channel.
use crate::{Error, Result};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Revision(String);
impl Revision {
    pub fn parse(text: &str) -> Result<Self> {
        if text.len() != 40 || !text.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()) {
            return Err(Error::new("expected a full lowercase Git commit revision"));
        }
        Ok(Self(text.to_owned()))
    }
    pub fn as_str(&self) -> &str { &self.0 }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn revisions_cannot_be_tracks_or_expressions() {
        for bad in ["stable", "master", "0123456", "", "../x"] { assert!(Revision::parse(bad).is_err()); }
        assert!(Revision::parse(&"a".repeat(40)).is_ok());
        assert!(Revision::parse(&"A".repeat(40)).is_err());
    }
}
