// SPDX-License-Identifier: GPL-3.0-or-later
//! Authenticated immutable release graph, resolved only after provenance policy.
use crate::release::{self, AuthenticatedRelease};
use assbox_domain::release::ReleaseManifest;
use assbox_domain::*;
use assbox_system::{
    commands::Commands,
    files::{self, io},
};
use std::{
    fs,
    path::{Path, PathBuf},
};

const MACHINE_LOCK: &str = include_str!("../../../../nix/machine-lock.jq");
pub(crate) struct FetchedSource {
    pub release: AuthenticatedRelease,
    pub machine_lock: Vec<u8>,
    pub source_path: PathBuf,
    pub evaluation_store: String,
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

fn exact_source_root(root: &Path, expected: &Path) -> Result<bool> {
    let metadata = io(fs::symlink_metadata(root))?;
    Ok(metadata.file_type().is_symlink() && io(fs::read_link(root))? == expected)
}

fn add_owned_source_root(c: &Commands, root: &Path, expected: &Path) -> Result<()> {
    let parent = root
        .parent()
        .ok_or_else(|| Error::new("authenticated source root has no parent"))?;
    files::trusted_dir(parent)?;
    if files::entry_exists(root)? && !exact_source_root(root, expected)? {
        return Err(Error::new(
            "authenticated source GC root changed unexpectedly",
        ));
    }
    c.run(
        "nix-store",
        &[
            "--add-root",
            files::path_text(root)?,
            "--indirect",
            "--realise",
            files::path_text(expected)?,
        ],
    )?;
    if !exact_source_root(root, expected)? {
        return Err(Error::new(
            "authenticated source GC root resolved unexpectedly",
        ));
    }
    io(io(fs::File::open(parent))?.sync_all())
}

/// Rebuild the authenticated object in a fresh isolated store, publish it to a
/// private local cache, then ask Nix's supported repair operation to replace the
/// corrupt live object. Deleting the object is not sound: already-built
/// derivations may legitimately refer to it, and Nix refuses such deletion even
/// when root liveness is ignored.
fn repair_flake_source(
    c: &Commands,
    source: &Path,
    source_root: &Path,
    expected: &Path,
) -> Result<()> {
    let parent = source_root
        .parent()
        .ok_or_else(|| Error::new("authenticated source root has no parent"))?;
    files::trusted_dir(parent)?;
    if files::entry_exists(source_root)? && !exact_source_root(source_root, expected)? {
        return Err(Error::new(
            "authenticated source GC root changed unexpectedly",
        ));
    }

    // A random fresh root prevents a power-cut residue from supplying the
    // isolated store or its cache on a retry. The transaction parent is
    // root-owned and private, and transaction cleanup removes these artifacts.
    let repair_root = parent.join(format!(
        "authenticated-flake-repair-{}",
        files::random_id()?
    ));
    files::create_private(&repair_root)?;
    let isolated_store = repair_root.join("store");
    let cache = repair_root.join("cache");
    let store_uri = format!("local?root={}", files::path_text(&isolated_store)?);
    let cache_uri = format!("file://{}", files::path_text(&cache)?);
    let imported = c.text(
        "nix",
        &[
            "--store",
            &store_uri,
            "store",
            "add-path",
            "--name",
            "source",
            files::path_text(source)?,
        ],
    )?;
    if imported.trim() != files::path_text(expected)? {
        return Err(Error::new(
            "isolated repair source differs from authenticated content",
        ));
    }
    c.run(
        "nix",
        &[
            "--store",
            &store_uri,
            "copy",
            "--to",
            &cache_uri,
            files::path_text(expected)?,
        ],
    )?;
    // This one command accepts an unsigned cache because that cache was just
    // created beneath the private transaction from authenticated bytes. Nix
    // still validates its content address, and the caller verifies the repaired
    // live object again before any candidate Nix is evaluated.
    c.run(
        "nix",
        &[
            "--option",
            "substituters",
            &cache_uri,
            "--option",
            "require-sigs",
            "false",
            "store",
            "repair",
            files::path_text(expected)?,
        ],
    )
}

/// Materialize the tarball fetcher's exact content-addressed source object from
/// the already authenticated unpacked NAR before asking Nix to evaluate it.
/// A sudden power loss can leave a registered store path with truncated bytes;
/// `add-path` then trusts the registration, while `store verify` detects the
/// damage. Repair is confined to the exact source-named path derived from the
/// authenticated content.
fn prepare_flake_source(
    c: &Commands,
    source: &Path,
    source_root: &Path,
) -> Result<std::path::PathBuf> {
    let source_text = files::path_text(source)?;
    let expected_output = c.text(
        "nix",
        &[
            "store",
            "add-path",
            "--dry-run",
            "--name",
            "source",
            source_text,
        ],
    )?;
    let expected = expected_output.trim();
    if !valid_flake_source_store_path(expected) {
        return Err(Error::new(
            "authenticated flake source has an invalid store path",
        ));
    }
    let add = |commands: &Commands| -> Result<()> {
        let imported = commands.text(
            "nix",
            &["store", "add-path", "--name", "source", source_text],
        )?;
        if imported.trim() != expected {
            return Err(Error::new(
                "imported flake source differs from authenticated content",
            ));
        }
        Ok(())
    };
    add(c)?;
    if !c.succeeds("nix", &["store", "verify", "--no-trust", expected]) {
        repair_flake_source(c, source, source_root, Path::new(expected))?;
        c.run("nix", &["store", "verify", "--no-trust", expected])?;
    }
    // Root the verified object before starting a separate metadata process so
    // automatic collection cannot reopen the authentication/evaluation gap.
    add_owned_source_root(c, source_root, Path::new(expected))?;
    // The transaction deliberately survives hard power cuts. Make the repaired
    // or newly imported source durable before its first evaluation and before a
    // later source-publication checkpoint can cut power again.
    c.run("sync", &["-f", expected])?;
    let canonical = io(fs::canonicalize(expected))?;
    if canonical != Path::new(expected) {
        return Err(Error::new(
            "authenticated flake source resolved through a filesystem alias",
        ));
    }
    Ok(canonical)
}

/// Import the authenticated source into a fresh transaction-private store. Nix's
/// global store optimizer may hardlink identical files from several fetcher
/// objects; repairing one registered object cannot make every such alias safe to
/// evaluate. Keeping the complete release evaluation in a new store avoids those
/// pre-existing aliases while ordinary build outputs can still use their target
/// store.
fn prepare_evaluation_store(
    c: &Commands,
    source: &Path,
    directory: &Path,
    expected: &Path,
) -> Result<String> {
    files::trusted_dir(directory)?;
    let root = directory.join(format!(
        "authenticated-evaluation-store-{}",
        files::random_id()?
    ));
    files::create_private(&root)?;
    let store = root.join("store");
    let store_uri = format!("local?root={}", files::path_text(&store)?);
    let imported = c.text(
        "nix",
        &[
            "--store",
            &store_uri,
            "store",
            "add-path",
            "--name",
            "source",
            files::path_text(source)?,
        ],
    )?;
    if imported.trim() != files::path_text(expected)? {
        return Err(Error::new(
            "private evaluation source differs from authenticated content",
        ));
    }
    c.run(
        "nix",
        &[
            "--store",
            &store_uri,
            "store",
            "verify",
            "--no-trust",
            files::path_text(expected)?,
        ],
    )?;
    // A retained transaction is discarded or recovered before another attempt,
    // but the store must remain stable for this attempt's later Nix processes.
    c.run("sync", &["-f", files::path_text(&root)?])?;
    Ok(store_uri)
}

/// Copy the complete preflight evaluator state onto target-backed storage before
/// the full system evaluation. Both stores keep normal Nix trust checks, and the
/// private destination is content-verified again before use.
pub(crate) fn copy_evaluation_store(
    c: &Commands,
    source_store: &str,
    directory: &Path,
    authenticated_source: &Path,
) -> Result<String> {
    files::trusted_dir(directory)?;
    let root = directory.join(format!(
        "authenticated-evaluation-store-{}",
        files::random_id()?
    ));
    files::create_private(&root)?;
    let store = root.join("store");
    let store_uri = format!("local?root={}", files::path_text(&store)?);
    c.run(
        "nix",
        &["copy", "--all", "--from", source_store, "--to", &store_uri],
    )?;
    c.run(
        "nix",
        &[
            "--store",
            &store_uri,
            "store",
            "verify",
            "--all",
            "--no-trust",
        ],
    )?;
    c.run(
        "nix",
        &[
            "--store",
            &store_uri,
            "store",
            "verify",
            "--no-trust",
            files::path_text(authenticated_source)?,
        ],
    )?;
    c.run("sync", &["-f", files::path_text(&root)?])?;
    Ok(store_uri)
}

pub(crate) fn machine_lock(
    c: &Commands,
    metadata: &[u8],
    source: &ReleaseManifest,
    source_path: &Path,
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
            "--arg",
            "path",
            files::path_text(source_path)?,
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
    let source_root = directory.join("authenticated-flake-source");
    let source_path = prepare_flake_source(c, &release.source_path, &source_root)?;
    let evaluation_store =
        prepare_evaluation_store(c, &release.source_path, directory, &source_path)?;
    let authenticated_reference = format!("path:{}", files::path_text(&source_path)?);
    // Evaluate the exact verified store object. Refetching the immutable URL
    // here would re-enter Nix's tarball/Git caches after authentication. Store
    // optimization can hardlink identical files across those cache objects, so
    // a damaged registered object can otherwise survive repair in an alias.
    let metadata = c.capture(
        "nix",
        &[
            "flake",
            "metadata",
            "--store",
            &evaluation_store,
            "--eval-store",
            &evaluation_store,
            "--json",
            "--no-use-registries",
            "--no-update-lock-file",
            "--no-write-lock-file",
            &authenticated_reference,
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
    let local_lock = machine_lock(c, &metadata, &release.manifest, &source_path)?;
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
    if source_path != Path::new(raw)
        || io(fs::read(source_path.join("flake.lock")))? != upstream_lock
    {
        return Err(Error::new(
            "resolved flake source differs from the authenticated release",
        ));
    }
    if !exact_source_root(&source_root, &source_path)? {
        return Err(Error::new(
            "authenticated flake source GC root resolved unexpectedly",
        ));
    }
    Ok(FetchedSource {
        release,
        machine_lock: local_lock,
        source_path,
        evaluation_store,
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
    use super::{exact_source_root, valid_flake_source_store_path};
    use std::{fs, os::unix::fs::symlink, path::Path};

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

    #[test]
    fn transaction_root_must_be_an_exact_symlink() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "assbox-source-root-test-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir(&directory).unwrap();
        let root = directory.join("authenticated-flake-source");
        let expected = Path::new("/nix/store/0123456789abcdfghijklmnpqrsvwxyz-source");

        symlink(expected, &root).unwrap();
        assert!(exact_source_root(&root, expected).unwrap());
        fs::remove_file(&root).unwrap();

        symlink("relative-source", &root).unwrap();
        assert!(!exact_source_root(&root, expected).unwrap());
        fs::remove_file(&root).unwrap();

        fs::write(&root, b"not a link").unwrap();
        assert!(!exact_source_root(&root, expected).unwrap());
        fs::remove_dir_all(&directory).unwrap();
    }
}
