// SPDX-License-Identifier: GPL-3.0-or-later
//! Authenticated immutable release graph, resolved only after provenance policy.
use crate::release::{self, AuthenticatedRelease};
use assbox_domain::release::ReleaseManifest;
use assbox_domain::*;
use assbox_system::{
    commands::Commands,
    files::{self, io},
};
use std::{fs, io::ErrorKind, path::Path};

const MACHINE_LOCK: &str = include_str!("../../../../nix/machine-lock.jq");
pub(crate) struct FetchedSource {
    pub release: AuthenticatedRelease,
    pub machine_lock: Vec<u8>,
}

fn valid_flake_source_store_path(path: &str) -> bool {
    let Some(name) = path.strip_prefix("/nix/store/") else {
        return false;
    };
    let Some(hash) = name.strip_suffix("-source") else {
        return false;
    };
    hash.len() == 32
        && hash
            .bytes()
            .all(|b| b"0123456789abcdfghijklmnpqrsvwxyz".contains(&b))
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
pub(crate) fn bind(
    c: &Commands,
    release: AuthenticatedRelease,
    directory: &Path,
) -> Result<FetchedSource> {
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
    let paths = c.jq_fields(
        &metadata,
        r#".path | if type == "string" then . + "\u0000" else error("missing flake source path") end"#,
    )?;
    if paths.len() != 1 || !valid_flake_source_store_path(&paths[0]) {
        return Err(Error::new(
            "resolved flake source has an invalid store path",
        ));
    }
    let raw = &paths[0];
    let source_path = match fs::canonicalize(raw) {
        Ok(path) => path,
        Err(error) if error.kind() == ErrorKind::NotFound => {
            match fs::symlink_metadata(raw) {
                Err(missing) if missing.kind() == ErrorKind::NotFound => {}
                Ok(_) => {
                    return Err(Error::new(
                        "resolved flake source is an unresolved store entry",
                    ));
                }
                Err(observation) => return io(Err(observation)),
            }
            // The tarball fetcher uses a separate `source`-named store object
            // from prefetch-file's authenticated filename-named import. A live
            // store image can preserve the fetcher cache and validity record
            // while losing that object across power loss. Remove only this
            // absent hash-shaped registration, then recreate its exact
            // content-addressed name from the already authenticated NAR.
            c.run("nix", &["store", "delete", "--ignore-liveness", raw])?;
            let restored = c.text(
                "nix",
                &[
                    "store",
                    "add-path",
                    "--name",
                    "source",
                    files::path_text(&release.source_path)?,
                ],
            )?;
            if restored.trim() != raw {
                return Err(Error::new(
                    "restored flake source differs from authenticated metadata",
                ));
            }
            io(fs::canonicalize(raw))?
        }
        Err(error) => return io(Err(error)),
    };
    if source_path != Path::new(raw)
        || io(fs::read(source_path.join("flake.lock")))? != upstream_lock
    {
        return Err(Error::new(
            "resolved flake source differs from the authenticated release",
        ));
    }
    let source_root = directory.join("authenticated-flake-source");
    c.run(
        "nix-store",
        &[
            "--add-root",
            files::path_text(&source_root)?,
            "--indirect",
            "--realise",
            files::path_text(&source_path)?,
        ],
    )?;
    if io(fs::canonicalize(&source_root))? != source_path {
        return Err(Error::new(
            "authenticated flake source GC root resolved unexpectedly",
        ));
    }
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
    bind(c, release, directory)
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

#[cfg(test)]
mod tests {
    use super::valid_flake_source_store_path;

    #[test]
    fn flake_store_repair_is_limited_to_the_fetcher_source_shape() {
        assert!(valid_flake_source_store_path(
            "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-source"
        ));
        for path in [
            "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-assbox-source.tar.gz",
            "/nix/store/0123456789abcdfghijklmnpqrsvwxy-source",
            "/nix/store/0123456789abcdfghijklmnpqrsvwxyE-source",
            "/nix/store/0123456789abcdfghijklmnpqrsvwxyz-source/child",
            "/tmp/0123456789abcdfghijklmnpqrsvwxyz-source",
        ] {
            assert!(!valid_flake_source_store_path(path), "{path}");
        }
    }
}
