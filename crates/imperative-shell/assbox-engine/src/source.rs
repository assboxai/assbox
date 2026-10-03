// SPDX-License-Identifier: GPL-3.0-or-later
//! Authenticated immutable release graph, resolved only after provenance policy.
use crate::release::{self, AuthenticatedRelease};
use assbox_domain::release::ReleaseManifest;
use assbox_domain::*;
use assbox_system::{commands::Commands, files::io};
use std::{fs, path::Path};

const MACHINE_LOCK: &str = include_str!("../../../../nix/machine-lock.jq");
pub(crate) struct FetchedSource {
    pub release: AuthenticatedRelease,
    pub machine_lock: Vec<u8>,
}

pub(crate) fn machine_lock(
    c: &Commands,
    metadata: &[u8],
    source: &ReleaseManifest,
) -> Result<Vec<u8>> {
    c.input(
        "jq",
        &[
            "-e",
            "-S",
            "--arg",
            "url",
            &source.source_url(),
            "--arg",
            "hash",
            &source.source_nar_hash,
            MACHINE_LOCK,
        ],
        metadata,
    )
}
/// No candidate Nix is read/evaluated until release::fetch has verified the signed
/// manifest, immutable release, archive, NAR and exact embedded dependency lock.
pub(crate) fn bind(c: &Commands, release: AuthenticatedRelease) -> Result<FetchedSource> {
    let metadata = c.capture(
        "nix",
        &[
            "flake",
            "metadata",
            "--json",
            "--no-use-registries",
            "--no-update-lock-file",
            "--no-write-lock-file",
            &release.manifest.pinned_url(),
        ],
    )?;
    let upstream_lock = io(fs::read(release.source_path.join("flake.lock")))?;
    if c.input("jq", &["-c", "-S", "."], &upstream_lock)?
        != c.input("jq", &["-c", "-S", ".locks"], &metadata)?
    {
        return Err(Error::new(
            "resolved graph differs from the authenticated release lock",
        ));
    }
    let local_lock = machine_lock(c, &metadata, &release.manifest)?;
    Ok(FetchedSource {
        release,
        machine_lock: local_lock,
    })
}

pub(crate) fn resolve(
    c: &Commands,
    requested: Option<&str>,
    directory: &Path,
) -> Result<FetchedSource> {
    let release = release::fetch(c, requested, directory, None, false)?;
    let revision = option_env!("ASSBOX_SOURCE_REVISION").unwrap_or("");
    if revision.is_empty() || revision != release.manifest.core_commit.as_str() {
        return Err(Error::new(
            "installer core commit differs from this release; obtain its authenticated installer source first",
        ));
    }
    // The same frozen core can legitimately have a new, attested dependency graph.
    bind(c, release)
}

pub(crate) fn verify_local_lock(
    c: &Commands,
    directory: &Path,
    source: &ReleaseManifest,
) -> Result<()> {
    let bytes = io(fs::read(directory.join("flake.lock")))?;
    let fields = c.jq_fields(
        &bytes,
        r#". as $l | .nodes[.nodes[.root].inputs.assbox] |
      [.locked.type,.locked.url,.locked.narHash,.original.narHash] | .[] | . + "\u0000""#,
    )?;
    let url = source.source_url();
    let expected = [
        "tarball",
        url.as_str(),
        source.source_nar_hash.as_str(),
        source.source_nar_hash.as_str(),
    ];
    if !fields.iter().map(String::as_str).eq(expected) {
        return Err(Error::new(
            "machine lock no longer binds the authenticated immutable release",
        ));
    }
    Ok(())
}
