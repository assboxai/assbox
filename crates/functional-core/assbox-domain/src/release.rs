// SPDX-License-Identifier: GPL-3.0-or-later
//! Release data has no clock, networking, signature verification or filesystem access.
use crate::{Error, Result, Revision};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Digest(String);
impl Digest {
    pub fn parse(s: &str) -> Result<Self> {
        if s.len() != 64
            || !s
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(Error::new("expected a lowercase SHA-256 digest"));
        }
        Ok(Self(s.into()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseTag {
    text: String,
    sequence: u64,
}
impl ReleaseTag {
    pub fn parse(s: &str) -> Result<Self> {
        let digits = s
            .strip_prefix("r-")
            .ok_or_else(|| Error::new("release tag must be r-<sequence>"))?;
        if digits.is_empty()
            || digits.len() > 16
            || digits.starts_with('0')
            || !digits.bytes().all(|b| b.is_ascii_digit())
        {
            return Err(Error::new("invalid immutable release tag"));
        }
        let sequence = digits
            .parse()
            .map_err(|_| Error::new("invalid release sequence"))?;
        Ok(Self {
            text: s.into(),
            sequence,
        })
    }
    pub fn as_str(&self) -> &str {
        &self.text
    }
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    pub fn asset_url(&self, name: &str) -> Result<String> {
        if !matches!(
            name,
            "release.json" | "release.sigstore.json" | "flake.lock" | "assbox-source.tar.gz"
        ) {
            return Err(Error::new("unknown release asset"));
        }
        Ok(format!(
            "https://github.com/assboxai/assbox/releases/download/{}/{name}",
            self.text
        ))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseParent {
    pub tag: ReleaseTag,
    pub manifest_sha256: Digest,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseManifest {
    pub tag: ReleaseTag,
    pub core_commit: Revision,
    pub core_version: String,
    pub issued_at: u64,
    pub expires_at: u64,
    pub source_sha256: Digest,
    pub source_nar_hash: String,
    pub lock_sha256: Digest,
    pub previous: Option<ReleaseParent>,
}
impl ReleaseManifest {
    /// Decode a fixed, schema-checked field sequence emitted by the JSON adapter.
    /// This does NOT imply that a signature has been checked.
    pub fn from_fields(f: &[String]) -> Result<Self> {
        if f.len() != 14
            || f[0] != "3"
            || f[1] != "3"
            || f[2] != "stable"
            || f[11] != "aarch64-linux,x86_64-linux"
        {
            return Err(Error::new(
                "unsupported Assbox release schema, protocol, channel or architecture matrix",
            ));
        }
        let tag = ReleaseTag::parse(&f[3])?;
        let previous = match (f[12].as_str(), f[13].as_str()) {
            ("", "") if tag.sequence() == 1 => None,
            ("", _) | (_, "") => {
                return Err(Error::new("only r-1 genesis may omit both parent fields"));
            }
            (name, hash) => {
                let parent = ReleaseTag::parse(name)?;
                if parent.sequence() >= tag.sequence() {
                    return Err(Error::new("release parent must precede child"));
                }
                Some(ReleaseParent {
                    tag: parent,
                    manifest_sha256: Digest::parse(hash)?,
                })
            }
        };
        let issued_at = f[6]
            .parse::<u64>()
            .map_err(|_| Error::new("invalid release issue time"))?;
        let expires_at = f[7]
            .parse::<u64>()
            .map_err(|_| Error::new("invalid release expiry"))?;
        let hash = f[9].strip_prefix("sha256-").unwrap_or("");
        if hash.len() != 44
            || !hash.ends_with('=')
            || !hash.as_bytes()[..43]
                .iter()
                .all(|b| b.is_ascii_alphanumeric() || b"+/".contains(b))
        {
            return Err(Error::new("invalid release NAR hash"));
        }
        if f[5].is_empty()
            || f[5].len() > 40
            || !f[5]
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b".-".contains(&b))
        {
            return Err(Error::new("invalid core version"));
        }
        Ok(Self {
            tag,
            core_commit: Revision::parse(&f[4])?,
            core_version: f[5].clone(),
            issued_at,
            expires_at,
            source_sha256: Digest::parse(&f[8])?,
            source_nar_hash: f[9].clone(),
            lock_sha256: Digest::parse(&f[10])?,
            previous,
        })
    }
    pub fn source_url(&self) -> String {
        format!(
            "https://github.com/assboxai/assbox/releases/download/{}/assbox-source.tar.gz",
            self.tag.as_str()
        )
    }
    pub fn pinned_url(&self) -> String {
        // Only three base64 characters need percent-encoding in this query value.
        let hash = self
            .source_nar_hash
            .replace('+', "%2B")
            .replace('/', "%2F")
            .replace('=', "%3D");
        format!("{}?narHash={hash}", self.source_url())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseFloor {
    pub sequence: u64,
    pub manifest_sha256: Digest,
    pub issued_at: u64,
}
impl ReleaseFloor {
    pub fn encode(&self) -> String {
        format!(
            "ASSBOX-RELEASE-1\n{}\n{}\n{}\n",
            self.sequence,
            self.manifest_sha256.as_str(),
            self.issued_at
        )
    }
    pub fn parse(s: &str) -> Result<Self> {
        let f: Vec<_> = s.lines().collect();
        if f.len() != 4 || f[0] != "ASSBOX-RELEASE-1" {
            return Err(Error::new("invalid authenticated-release high-water mark"));
        }
        let value = Self {
            sequence: f[1]
                .parse()
                .map_err(|_| Error::new("invalid release sequence"))?,
            manifest_sha256: Digest::parse(f[2])?,
            issued_at: f[3]
                .parse()
                .map_err(|_| Error::new("invalid release time"))?,
        };
        if value.sequence == 0 || value.encode() != s {
            return Err(Error::new("noncanonical release state"));
        }
        Ok(value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProvenanceFacts {
    pub repository_id: u64,
    pub owner_id: u64,
    pub source_commit: Revision,
    pub trigger: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReleaseTrust {
    pub repository_id: u64,
    pub owner_id: u64,
}

/// Unknown or future Actions events are not implicitly trusted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReleaseTrigger {
    Schedule,
    WorkflowDispatch,
}
impl std::str::FromStr for ReleaseTrigger {
    type Err = Error;
    fn from_str(value: &str) -> Result<Self> {
        match value {
            "schedule" => Ok(Self::Schedule),
            "workflow_dispatch" => Ok(Self::WorkflowDispatch),
            _ => Err(Error::new("unreviewed release provenance trigger")),
        }
    }
}
