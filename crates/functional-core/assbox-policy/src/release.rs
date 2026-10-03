// SPDX-License-Identifier: GPL-3.0-or-later
//! Authorization decisions over facts already observed by the crypto adapter.
use assbox_domain::release::*;
use assbox_domain::{Error, Result};

fn validate(
    manifest: &ReleaseManifest,
    digest: &Digest,
    facts: &ProvenanceFacts,
    trust: &ReleaseTrust,
    floor: Option<&ReleaseFloor>,
    now: u64,
    historical: bool,
) -> Result<ReleaseFloor> {
    if trust.repository_id == 0 || trust.owner_id == 0 {
        return Err(Error::new(
            "release trust IDs are not provisioned; complete cold-administrator bootstrap",
        ));
    }
    if facts.repository_id != trust.repository_id
        || facts.owner_id != trust.owner_id
        || facts.source_commit != manifest.core_commit
        || facts.trigger.parse::<ReleaseTrigger>().is_err()
    {
        return Err(Error::new(
            "release provenance does not match the provisioned repository and release policy",
        ));
    }
    validate_parent_shape(manifest)?;
    if manifest.issued_at > now.saturating_add(300)
        || (!historical && manifest.expires_at <= now)
        || manifest.expires_at <= manifest.issued_at
        || manifest.expires_at - manifest.issued_at != 604800
    {
        return Err(Error::new(
            "release expired or has invalid issue/expiry times; check clock and publisher health",
        ));
    }
    if let Some(old) = floor
        && (manifest.tag.sequence() < old.sequence
            || manifest.issued_at < old.issued_at
            || (manifest.tag.sequence() == old.sequence && *digest != old.manifest_sha256))
    {
        return Err(Error::new(
            "release replay, equivocation or downgrade refused",
        ));
    }
    Ok(ReleaseFloor {
        sequence: manifest.tag.sequence(),
        manifest_sha256: digest.clone(),
        issued_at: manifest.issued_at,
    })
}

/// Installed update policy always requires a fresh release.
pub fn validate_release(
    manifest: &ReleaseManifest,
    digest: &Digest,
    facts: &ProvenanceFacts,
    trust: &ReleaseTrust,
    floor: Option<&ReleaseFloor>,
    now: u64,
) -> Result<ReleaseFloor> {
    validate(manifest, digest, facts, trust, floor, now, false)
}
/// Historical inspection permits an expired *baseline*, not installation or
/// acceptance. Identity, valid lifetime, future-time checks and hashes still apply.
pub fn validate_historical_release(
    manifest: &ReleaseManifest,
    digest: &Digest,
    facts: &ProvenanceFacts,
    trust: &ReleaseTrust,
    now: u64,
) -> Result<ReleaseFloor> {
    validate(manifest, digest, facts, trust, None, now, true)
}

/// An uninitialized machine cannot authorize a source from mutable discovery.
pub fn require_release_selection(explicit_tag: bool, has_floor: bool) -> Result<()> {
    if !explicit_tag && !has_floor {
        return Err(Error::new(
            "first installation and historical inspection require an explicit authenticated release tag",
        ));
    }
    Ok(())
}

/// Shape validation also protects callers that construct domain observations directly.
pub fn validate_parent_shape(manifest: &ReleaseManifest) -> Result<()> {
    match &manifest.previous {
        None if manifest.tag.sequence() == 1 => Ok(()),
        Some(parent) if parent.tag.sequence() < manifest.tag.sequence() => Ok(()),
        _ => Err(Error::new(
            "invalid release lineage: only r-1 is genesis; parents must precede children",
        )),
    }
}

/// A predecessor fetched by its child hash need not be freshly installable. Its
/// bytes are authenticated by that hash, NOT by parsing it or trusting its URL.
pub fn validate_parent(
    child: &ReleaseManifest,
    parent: &ReleaseManifest,
    digest: &Digest,
) -> Result<()> {
    validate_parent_shape(child)?;
    validate_parent_shape(parent)?;
    let expected = child
        .previous
        .as_ref()
        .ok_or_else(|| Error::new("genesis has no predecessor"))?;
    if expected.tag != parent.tag
        || expected.manifest_sha256 != *digest
        || parent.issued_at > child.issued_at
        || parent.issued_at == 0
        || parent.expires_at <= parent.issued_at
        || parent.expires_at - parent.issued_at != 604800
    {
        return Err(Error::new(
            "release predecessor hash, tag or validity interval disagrees",
        ));
    }
    Ok(())
}

/// Decide whether traversal has reached the locally accepted release. A newer
/// sequence alone does not authorize a fork that omits the machine's own floor.
pub fn lineage_reaches_floor(
    manifest: &ReleaseManifest,
    digest: &Digest,
    floor: &ReleaseFloor,
) -> Result<bool> {
    if manifest.tag.sequence() == floor.sequence {
        if *digest != floor.manifest_sha256 || manifest.issued_at != floor.issued_at {
            return Err(Error::new(
                "release history equivocates at the local high-water mark",
            ));
        }
        return Ok(true);
    }
    let parent = manifest
        .previous
        .as_ref()
        .ok_or_else(|| Error::new("release lineage ended before the local high-water mark"))?;
    if manifest.tag.sequence() < floor.sequence || parent.tag.sequence() < floor.sequence {
        return Err(Error::new(
            "release lineage skips the local high-water mark",
        ));
    }
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use assbox_domain::Revision;
    fn sample() -> (ReleaseManifest, Digest, ProvenanceFacts, ReleaseTrust) {
        (
            ReleaseManifest {
                tag: ReleaseTag::parse("r-100").unwrap(),
                core_commit: Revision::parse(&"a".repeat(40)).unwrap(),
                core_version: "0.1.0".into(),
                issued_at: 1000,
                expires_at: 605800,
                source_sha256: Digest::parse(&"1".repeat(64)).unwrap(),
                source_nar_hash: format!("sha256-{}=", "A".repeat(43)),
                lock_sha256: Digest::parse(&"2".repeat(64)).unwrap(),
                previous: Some(ReleaseParent {
                    tag: ReleaseTag::parse("r-1").unwrap(),
                    manifest_sha256: Digest::parse(&"0".repeat(64)).unwrap(),
                }),
            },
            Digest::parse(&"3".repeat(64)).unwrap(),
            ProvenanceFacts {
                repository_id: 10,
                owner_id: 20,
                source_commit: Revision::parse(&"a".repeat(40)).unwrap(),
                trigger: "workflow_dispatch".into(),
            },
            ReleaseTrust {
                repository_id: 10,
                owner_id: 20,
            },
        )
    }
    #[test]
    fn exact_retry_is_allowed_but_rollback_and_equivocation_are_not() {
        let (mut m, d, p, t) = sample();
        let floor = validate_release(&m, &d, &p, &t, None, 1100).unwrap();
        assert!(validate_release(&m, &d, &p, &t, Some(&floor), 1200).is_ok());
        assert!(
            validate_release(
                &m,
                &Digest::parse(&"4".repeat(64)).unwrap(),
                &p,
                &t,
                Some(&floor),
                1200
            )
            .is_err()
        );
        m.tag = ReleaseTag::parse("r-99").unwrap();
        assert!(validate_release(&m, &d, &p, &t, Some(&floor), 1200).is_err());
        assert_eq!(ReleaseFloor::parse(&floor.encode()).unwrap(), floor);
    }
    #[test]
    fn expiry_future_times_identity_and_events_fail_closed() {
        let (m, d, p, t) = sample();
        for now in [0, 699, 605800, 999999] {
            assert!(validate_release(&m, &d, &p, &t, None, now).is_err());
        }
        for trigger in [
            "repository_dispatch",
            "pull_request",
            "pull_request_target",
            "workflow_run",
            "push",
            "",
            "unknown",
        ] {
            let mut wrong = p.clone();
            wrong.trigger = trigger.into();
            assert!(validate_release(&m, &d, &wrong, &t, None, 1100).is_err());
        }
        for trigger in ["schedule", "workflow_dispatch"] {
            let mut allowed = p.clone();
            allowed.trigger = trigger.into();
            assert!(validate_release(&m, &d, &allowed, &t, None, 1100).is_ok());
        }
        let mut wrong = p.clone();
        wrong.owner_id = 1;
        assert!(validate_release(&m, &d, &wrong, &t, None, 1100).is_err());
        let mut wrong = p.clone();
        wrong.repository_id = 1;
        assert!(validate_release(&m, &d, &wrong, &t, None, 1100).is_err());
        assert!(
            validate_release(
                &m,
                &d,
                &p,
                &ReleaseTrust {
                    owner_id: 0,
                    repository_id: 0
                },
                None,
                1100
            )
            .is_err()
        );
    }
    #[test]
    fn expired_history_is_inspectable_but_never_installable() {
        let (m, d, p, t) = sample();
        assert!(validate_historical_release(&m, &d, &p, &t, 900000).is_ok());
        assert!(validate_release(&m, &d, &p, &t, None, 900000).is_err());
        let mut wrong = p.clone();
        wrong.repository_id = 11;
        assert!(validate_historical_release(&m, &d, &wrong, &t, 900000).is_err());
    }
    #[test]
    fn tags_never_become_urls_or_options() {
        for s in [
            "latest", "stable", "r-", "r-01", "r-0", "r-../x", "r-1?x=y", "--help", "r-1\n",
        ] {
            assert!(ReleaseTag::parse(s).is_err());
        }
        assert!(
            ReleaseTag::parse("r-123")
                .unwrap()
                .asset_url("../../x")
                .is_err()
        );
    }
    #[test]
    fn bootstrap_requires_an_explicit_tag_but_installed_discovery_can_use_its_floor() {
        for explicit in [false, true] {
            for floor in [false, true] {
                assert_eq!(
                    require_release_selection(explicit, floor).is_ok(),
                    explicit || floor
                );
            }
        }
    }
    #[test]
    fn only_the_reserved_genesis_can_have_no_parent() {
        let (mut m, _, _, _) = sample();
        m.previous = None;
        assert!(validate_parent_shape(&m).is_err());
        m.tag = ReleaseTag::parse("r-1").unwrap();
        assert!(validate_parent_shape(&m).is_ok());
        m.previous = Some(ReleaseParent {
            tag: m.tag.clone(),
            manifest_sha256: Digest::parse(&"0".repeat(64)).unwrap(),
        });
        assert!(validate_parent_shape(&m).is_err());
    }
    #[test]
    fn ancestry_uses_exact_predecessor_hash_and_monotonic_issue_time() {
        let (child, _, _, _) = sample();
        let mut parent = child.clone();
        parent.tag = ReleaseTag::parse("r-1").unwrap();
        parent.previous = None;
        parent.issued_at = 900;
        parent.expires_at = 605700;
        let digest = Digest::parse(&"0".repeat(64)).unwrap();
        assert!(validate_parent(&child, &parent, &digest).is_ok());
        assert!(
            validate_parent(&child, &parent, &Digest::parse(&"9".repeat(64)).unwrap()).is_err()
        );
        parent.issued_at = 1001;
        assert!(validate_parent(&child, &parent, &digest).is_err());
        parent.issued_at = 900;
        parent.expires_at = 901;
        assert!(validate_parent(&child, &parent, &digest).is_err());
        parent.expires_at = 605700;
        parent.tag = ReleaseTag::parse("r-2").unwrap();
        assert!(validate_parent(&child, &parent, &digest).is_err());
    }
    #[test]
    fn a_higher_sequence_cannot_skip_or_equivocate_at_the_local_floor() {
        let (accepted, digest, facts, trust) = sample();
        let floor = validate_release(&accepted, &digest, &facts, &trust, None, 1100).unwrap();
        assert!(lineage_reaches_floor(&accepted, &digest, &floor).unwrap());
        let next_digest = Digest::parse(&"4".repeat(64)).unwrap();
        assert!(lineage_reaches_floor(&accepted, &next_digest, &floor).is_err());
        let mut next = accepted.clone();
        next.tag = ReleaseTag::parse("r-200").unwrap();
        // A fork that points straight back to genesis omits the locally seen r-100.
        assert!(lineage_reaches_floor(&next, &next_digest, &floor).is_err());
        next.previous = Some(ReleaseParent {
            tag: accepted.tag.clone(),
            manifest_sha256: digest.clone(),
        });
        assert!(!lineage_reaches_floor(&next, &next_digest, &floor).unwrap());
        assert!(validate_parent(&next, &accepted, &digest).is_ok());
        next.tag = ReleaseTag::parse("r-99").unwrap();
        assert!(lineage_reaches_floor(&next, &next_digest, &floor).is_err());
    }
}

/// Canonical transaction intent. Only these ordinary local files are CLI-managed.
pub fn managed_changes(names: &[&str]) -> Result<String> {
    let mut seen = std::collections::BTreeSet::new();
    for name in names {
        if !matches!(
            *name,
            "flake.nix"
                | "flake.lock"
                | "assbox-release.json"
                | "assbox-packages.nix"
                | "assbox-settings.nix"
        ) || !seen.insert(*name)
        {
            return Err(Error::new("invalid or duplicate managed recovery filename"));
        }
    }
    if names.is_empty() {
        return Err(Error::new("empty source transaction"));
    }
    Ok(names.iter().map(|s| format!("{s}\n")).collect())
}

#[cfg(test)]
mod transaction_tests {
    use super::*;
    #[test]
    fn release_state_is_never_a_recovery_source_file() {
        assert_eq!(
            managed_changes(&["flake.nix", "flake.lock", "assbox-release.json"]).unwrap(),
            "flake.nix\nflake.lock\nassbox-release.json\n"
        );
        for names in [
            vec![],
            vec!["release-state"],
            vec!["../release-state"],
            vec!["local.nix"],
            vec!["flake.lock", "flake.lock"],
        ] {
            assert!(managed_changes(&names).is_err());
        }
    }
}

/// Empty current intent explicitly means no source changes, except Published
/// requires changes. Absence and conflicting formats never mean "no changes".
pub fn recovery_source_intent(
    phase: crate::Phase,
    current: Option<&str>,
    legacy: Option<&str>,
) -> Result<Vec<String>> {
    if current.is_some() && legacy.is_some() {
        return Err(Error::new("conflicting recovery intent formats"));
    }
    if let Some(text) = current {
        if text.is_empty() {
            if phase == crate::Phase::Published {
                return Err(Error::new("published source intent is empty"));
            }
            return Ok(Vec::new());
        }
        let names: Vec<&str> = text.lines().collect();
        if managed_changes(&names)? != text {
            return Err(Error::new("noncanonical recovery change list"));
        }
        return Ok(names.into_iter().map(str::to_owned).collect());
    }
    if let Some(name) = legacy {
        managed_changes(&[name])?;
        return Ok(vec![name.to_owned()]);
    }
    Err(Error::new(
        "required recovery source intent is missing; journal retained",
    ))
}
#[cfg(test)]
mod recovery_intent_tests {
    use super::*;
    use crate::Phase;
    #[test]
    fn absence_and_conflicting_formats_fail_closed() {
        for phase in [Phase::Published, Phase::Activating, Phase::Committed] {
            assert!(recovery_source_intent(phase, None, None).is_err());
            assert!(recovery_source_intent(phase, Some(""), Some("flake.lock")).is_err());
        }
        assert!(recovery_source_intent(Phase::Published, Some(""), None).is_err());
        assert!(
            recovery_source_intent(Phase::Activating, Some(""), None)
                .unwrap()
                .is_empty()
        );
        assert!(
            recovery_source_intent(Phase::Committed, Some(""), None)
                .unwrap()
                .is_empty()
        );
    }
    #[test]
    fn canonical_current_and_unambiguous_legacy_intent() {
        for text in [
            "flake.lock",
            "flake.lock\r\n",
            "flake.lock\n\n",
            "flake.lock\nflake.lock\n",
            "../release-state\n",
            "release-state\n",
            "local.nix\n",
            "\n",
        ] {
            assert!(recovery_source_intent(Phase::Published, Some(text), None).is_err());
        }
        assert_eq!(
            recovery_source_intent(Phase::Published, Some("flake.lock\n"), None).unwrap(),
            ["flake.lock"]
        );
        assert_eq!(
            recovery_source_intent(Phase::Activating, None, Some("flake.lock")).unwrap(),
            ["flake.lock"]
        );
        assert!(recovery_source_intent(Phase::Activating, None, Some("flake.lock\n")).is_err());
    }
}
