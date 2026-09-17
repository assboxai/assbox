// SPDX-License-Identifier: GPL-3.0-or-later
//! The shell delegates cryptography to the Nix-pinned GitHub CLI. A successful
//! download or a parsed attestation is never an authorization decision.
use assbox_domain::release::*;
use assbox_domain::{Error, Result, Revision};
use assbox_system::{
    commands::Commands,
    files::{self, io},
};
use std::{
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub(crate) const FLOOR: &str = "/var/lib/assbox/release-state";
const REPOSITORY: &str = "assboxai/assbox";
const CERT_IDENTITY: &str =
    "https://github.com/assboxai/assbox/.github/workflows/release.yml@refs/heads/master";
const MANIFEST_FIELDS: &str = r#"
  if (keys | sort) != (["schema","protocol","channel","tag","coreCommit","coreVersion","issuedAt","expiresAt","sourceSha256","sourceNarHash","lockSha256","systems","heldInputs","previousTag","previousManifestSha256"] | sort)
    or .schema != 3 or .protocol != 3
    or (.heldInputs | type) != "array" or (.systems | sort) != ["aarch64-linux","x86_64-linux"]
    or (.heldInputs | sort | unique) != .heldInputs
    or any(.heldInputs[]; @HELD_CHECK@)
    or any([.channel,.tag,.coreCommit,.coreVersion,.sourceSha256,.sourceNarHash,.lockSha256][]; type != "string")
    or any([.previousTag,.previousManifestSha256][]; type != "string" and type != "null")
    or ((.previousTag == null) != (.previousManifestSha256 == null))
    or any([.issuedAt,.expiresAt][]; type != "number" or . <= 0 or . > 9007199254740991 or floor != .)
  then error("unknown release manifest schema") else
    [.schema,.protocol,.channel,.tag,.coreCommit,.coreVersion,.issuedAt,.expiresAt,
     .sourceSha256,.sourceNarHash,.lockSha256,(.systems|sort|join(",")),(.previousTag // ""),(.previousManifestSha256 // "")]
    | .[] | if type == "string" or type == "number" then tostring + "\u0000" else error("invalid manifest field") end
  end
"#;
// Read only *verified* certificate extensions, not claims inside statement.predicate.
const PROVENANCE_FIELDS: &str = r#"
  if length != 1 then error("one provenance result is required") else
    .[0].verificationResult.signature.certificate |
    [.sourceRepositoryIdentifier,.sourceRepositoryOwnerIdentifier,.sourceRepositoryDigest,.buildTrigger]
    | .[] | if type == "string" then . + "\u0000" else error("missing certificate extension") end
  end
"#;

pub(crate) struct AuthenticatedRelease {
    pub manifest: ReleaseManifest,
    pub manifest_bytes: Vec<u8>,
    pub floor: ReleaseFloor,
    pub source_path: PathBuf,
}
fn trust() -> Result<ReleaseTrust> {
    let parse = |s: &str| {
        s.parse::<u64>()
            .map_err(|_| Error::new("invalid compiled release trust ID"))
    };
    Ok(ReleaseTrust {
        repository_id: parse(option_env!("ASSBOX_REPOSITORY_ID").unwrap_or("0"))?,
        owner_id: parse(option_env!("ASSBOX_OWNER_ID").unwrap_or("0"))?,
    })
}
fn now(c: &Commands) -> Result<u64> {
    if c.text(
        "timedatectl",
        &["show", "--property=NTPSynchronized", "--value"],
    )?
    .trim()
        != "yes"
    {
        return Err(Error::new(
            "release freshness requires synchronized system time; repair time synchronization rather than bypass expiry",
        ));
    }
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .map_err(|_| Error::new("system clock precedes Unix epoch"))
}
pub(crate) fn check_freshness(c: &Commands, manifest: &ReleaseManifest) -> Result<()> {
    let time = now(c)?;
    if manifest.expires_at <= time || manifest.issued_at > time.saturating_add(300) {
        return Err(Error::new(
            "release expired or clock changed; installation cannot continue with this release",
        ));
    }
    Ok(())
}
pub(crate) fn sha256(c: &Commands, path: &Path) -> Result<Digest> {
    let output = c.text("sha256sum", &["--", files::path_text(path)?])?;
    Digest::parse(output.split_whitespace().next().unwrap_or(""))
}
fn download(c: &Commands, url: &str, path: &Path, limit: u64) -> Result<()> {
    if !url.starts_with("https://github.com/assboxai/assbox/releases/download/")
        && !url.starts_with("https://api.github.com/repos/assboxai/assbox/")
    {
        return Err(Error::new("release download escaped the fixed repository"));
    }
    c.run(
        "curl",
        &[
            "--disable",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "5",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--connect-timeout",
            "20",
            "--max-time",
            "300",
            "--max-filesize",
            &limit.to_string(),
            "--output",
            files::path_text(path)?,
            url,
        ],
    )?;
    files::regular(path)?;
    if io(fs::metadata(path))?.len() > limit {
        return Err(Error::new("release asset exceeds size limit"));
    }
    Ok(())
}
pub(crate) fn read_floor() -> Result<Option<ReleaseFloor>> {
    let path = Path::new(FLOOR);
    files::trusted_dir(
        path.parent()
            .ok_or_else(|| Error::new("release-state parent missing"))?,
    )?;
    if !files::entry_exists(path)? {
        return Ok(None);
    }
    ReleaseFloor::parse(&files::text(path)?).map(Some)
}
pub(crate) fn record_floor(value: &ReleaseFloor) -> Result<()> {
    files::create_private(Path::new("/var/lib/assbox"))?;
    files::atomic_write(Path::new(FLOOR), value.encode().as_bytes(), 0o600)
}

fn manifest_from_bytes(c: &Commands, path: &Path) -> Result<(ReleaseManifest, Vec<u8>)> {
    let bytes = io(fs::read(path))?;
    // The canonical byte check rejects duplicate JSON keys and alternate encodings
    // before their decoded values can acquire two different lineage identities.
    let canonical = c.capture("jq", &["-cS", ".", files::path_text(path)?])?;
    if canonical != bytes {
        return Err(Error::new(
            "release manifest must be canonical sorted JSON with one final newline",
        ));
    }
    let manifest = ReleaseManifest::from_fields(&c.jq_fields(
        &bytes,
        &MANIFEST_FIELDS.replace("@HELD_CHECK@", assbox_domain::RELEASE_HELD_INPUT_CHECK),
    )?)?;
    assbox_policy::release::validate_parent_shape(&manifest)?;
    Ok((manifest, bytes))
}

fn verify_lineage(
    c: &Commands,
    manifest: &ReleaseManifest,
    digest: &Digest,
    floor: &ReleaseFloor,
    directory: &Path,
) -> Result<()> {
    let mut child = manifest.clone();
    let mut child_digest = digest.clone();
    for depth in 0..16384 {
        if assbox_policy::release::lineage_reaches_floor(&child, &child_digest, floor)? {
            return Ok(());
        }
        let previous = child
            .previous
            .as_ref()
            .ok_or_else(|| Error::new("missing release predecessor"))?;
        let path = directory.join(format!("ancestor-{depth}.json"));
        download(
            c,
            &previous.tag.asset_url("release.json")?,
            &path,
            64 * 1024,
        )?;
        let parent_digest = sha256(c, &path)?;
        // Do not parse an unauthenticated ancestor. Its exact bytes are committed
        // by the already authenticated child; no fresh expiry is needed for history.
        if parent_digest != previous.manifest_sha256 {
            return Err(Error::new("release ancestry digest mismatch"));
        }
        let (parent, _) = manifest_from_bytes(c, &path)?;
        assbox_policy::release::validate_parent(&child, &parent, &parent_digest)?;
        child = parent;
        child_digest = parent_digest;
    }
    Err(Error::new(
        "release lineage exceeds the traversal bound; explicit administrator recovery is required",
    ))
}

pub(crate) fn fetch(
    c: &Commands,
    requested: Option<&str>,
    directory: &Path,
    floor: Option<&ReleaseFloor>,
    historical: bool,
) -> Result<AuthenticatedRelease> {
    assbox_policy::release::require_release_selection(requested.is_some(), floor.is_some())?;
    let policy = trust()?;
    if policy.repository_id == 0 || policy.owner_id == 0 {
        return Err(Error::new(
            "release trust is unprovisioned; set actual GitHub repository/owner IDs in release/policy.json during bootstrap",
        ));
    }
    if files::entry_exists(directory)? {
        return Err(Error::new(
            "release download directory already exists; inspect it rather than overwrite it",
        ));
    }
    files::create_private(directory)?;
    let tag = match requested {
        Some(text) => ReleaseTag::parse(text)?,
        None => {
            // Only an installed machine with a durable floor may use this hint.
            // A backward/missing pointer fails closed; CI never uses latest as its baseline.
            let path = directory.join("hint.json");
            download(
                c,
                "https://api.github.com/repos/assboxai/assbox/releases/latest",
                &path,
                1024 * 1024,
            )?;
            let fields = c.jq_fields(&io(fs::read(path))?, r#".tag_name | if type == "string" then . + "\u0000" else error("missing tag") end"#)?;
            if fields.len() != 1 {
                return Err(Error::new("invalid release discovery"));
            }
            ReleaseTag::parse(&fields[0])?
        }
    };
    let manifest_path = directory.join("release.json");
    let bundle = directory.join("release.sigstore.json");
    download(
        c,
        &tag.asset_url("release.json")?,
        &manifest_path,
        64 * 1024,
    )?;
    download(
        c,
        &tag.asset_url("release.sigstore.json")?,
        &bundle,
        4 * 1024 * 1024,
    )?;
    // GitHub's immutable-release signature must name these exact manifest bytes.
    c.run(
        "gh",
        &[
            "release",
            "verify-asset",
            tag.as_str(),
            files::path_text(&manifest_path)?,
            "--repo",
            REPOSITORY,
        ],
    )?;
    let (manifest, manifest_bytes) = manifest_from_bytes(c, &manifest_path)?;
    if manifest.tag != tag {
        return Err(Error::new(
            "release tag and authenticated manifest disagree",
        ));
    }
    // Exact SAN (not a prefix regex) and both source/signer commits are enforced.
    let proof = c.capture(
        "gh",
        &[
            "attestation",
            "verify",
            files::path_text(&manifest_path)?,
            "--bundle",
            files::path_text(&bundle)?,
            "--repo",
            REPOSITORY,
            "--cert-identity",
            CERT_IDENTITY,
            "--source-ref",
            "refs/heads/master",
            "--source-digest",
            manifest.core_commit.as_str(),
            "--signer-digest",
            manifest.core_commit.as_str(),
            "--cert-oidc-issuer",
            "https://token.actions.githubusercontent.com",
            "--deny-self-hosted-runners",
            "--predicate-type",
            "https://slsa.dev/provenance/v1",
            "--format",
            "json",
        ],
    )?;
    let f = c.jq_fields(&proof, PROVENANCE_FIELDS)?;
    if f.len() != 4 {
        return Err(Error::new("provenance lacks required certificate facts"));
    }
    let facts = ProvenanceFacts {
        repository_id: f[0]
            .parse()
            .map_err(|_| Error::new("invalid attested repository ID"))?,
        owner_id: f[1]
            .parse()
            .map_err(|_| Error::new("invalid attested owner ID"))?,
        source_commit: Revision::parse(&f[2])?,
        trigger: f[3].clone(),
    };
    let digest = sha256(c, &manifest_path)?;
    let accepted = if historical {
        if floor.is_some() {
            return Err(Error::new(
                "historical inspection cannot change installed replay state",
            ));
        }
        assbox_policy::release::validate_historical_release(
            &manifest,
            &digest,
            &facts,
            &policy,
            now(c)?,
        )?
    } else {
        assbox_policy::release::validate_release(
            &manifest,
            &digest,
            &facts,
            &policy,
            floor,
            now(c)?,
        )?
    };
    if let Some(old) = floor {
        verify_lineage(c, &manifest, &digest, old, directory)?;
    }
    let reference = directory.join("tag.json");
    download(
        c,
        &format!(
            "https://api.github.com/repos/{REPOSITORY}/git/ref/tags/{}",
            tag.as_str()
        ),
        &reference,
        64 * 1024,
    )?;
    let ref_fields = c.jq_fields(
        &io(fs::read(reference))?,
        r#"[.object.type,.object.sha] | .[] | . + "\u0000""#,
    )?;
    if ref_fields != ["commit", manifest.core_commit.as_str()] {
        return Err(Error::new(
            "immutable release tag is not the attested core commit",
        ));
    }
    let lock = directory.join("flake.lock");
    let archive = directory.join("assbox-source.tar.gz");
    download(c, &tag.asset_url("flake.lock")?, &lock, 8 * 1024 * 1024)?;
    download(
        c,
        &tag.asset_url("assbox-source.tar.gz")?,
        &archive,
        64 * 1024 * 1024,
    )?;
    if sha256(c, &lock)? != manifest.lock_sha256 || sha256(c, &archive)? != manifest.source_sha256 {
        return Err(Error::new(
            "release source or dependency lock digest differs from its authenticated manifest",
        ));
    }
    // The file fetcher unpacks the authenticated archive without evaluating Nix
    // or consulting flake registries. Verify its NAR and lock before evaluation.
    let fetched = c.capture(
        "nix",
        &[
            "store",
            "prefetch-file",
            "--unpack",
            "--json",
            &format!("file://{}", files::path_text(&archive)?),
        ],
    )?;
    let source = c.jq_fields(&fetched, r#"[.hash,.storePath] | .[] | . + "\u0000""#)?;
    if source.len() != 2 || source[0] != manifest.source_nar_hash {
        return Err(Error::new("unpacked release NAR mismatch"));
    }
    let source_path = io(fs::canonicalize(&source[1]))?;
    if !source_path.starts_with("/nix/store")
        || io(fs::read(source_path.join("flake.lock")))? != io(fs::read(lock))?
    {
        return Err(Error::new(
            "unpacked release dependency graph differs from authenticated lock asset",
        ));
    }
    Ok(AuthenticatedRelease {
        manifest,
        manifest_bytes,
        floor: accepted,
        source_path,
    })
}
