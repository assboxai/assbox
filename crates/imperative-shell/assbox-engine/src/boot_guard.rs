// SPDX-License-Identifier: GPL-3.0-or-later
//! Observe boot state around activation; never silently repair changed firmware.
use assbox_domain::*;
use assbox_system::{
    commands::Commands,
    files::{self, io},
};
use std::{collections::BTreeMap, fs, path::Path};

pub(crate) struct BootGuard {
    disk: String,
    table: Vec<u8>,
    firmware: Option<Vec<u8>>,
    unrelated_esp: Option<BTreeMap<String, String>>,
    esp_source: Option<String>,
}
pub(crate) fn read_binding(c: &Commands, system: &str) -> Result<BootReceipt> {
    if !assbox_system::commands::valid_store_system(system) {
        return Err(Error::new("invalid target generation"));
    }
    let path = io(fs::canonicalize(
        Path::new(system).join("assbox-boot-policy.json"),
    ))
    .map_err(|_| {
        Error::new(
            "target generation has no Assbox boot receipt; use expert NixOS recovery instead",
        )
    })?;
    if !path.starts_with("/nix/store") {
        return Err(Error::new(
            "generation receipt is not immutable store content",
        ));
    }
    decode_binding(c, &io(fs::read(path))?)
}

fn decode_binding(c: &Commands, bytes: &[u8]) -> Result<BootReceipt> {
    let fields = c.jq_fields(bytes, r#"if .schema != 2 then error("unknown boot receipt schema")
        elif (.binding.loader|type) != "object" then error("missing immutable loader binding")
        elif (.policy.generations|type) != "number" then error("missing generation policy")
        else [.binding.architecture,.binding.mode,.binding.platform,.binding.disk,
          .binding.rootDevice,.binding.espDevice,(.binding.loader|tojson),(.policy.generations|tostring)]
          | .[] | . + "\u0000" end"#)?;
    if fields.len() != 8 {
        return Err(Error::new("incomplete generation boot receipt"));
    }
    Ok(BootReceipt {
        binding: BootBinding {
            architecture: fields[0].parse()?,
            mode: fields[1].parse()?,
            platform: fields[2].parse()?,
            disk: fields[3].clone(),
            root_device: fields[4].clone(),
            esp_device: fields[5].clone(),
            loader: fields[6].clone(),
        },
        policy: BootPolicy {
            generations: fields[7]
                .parse()
                .map_err(|_| Error::new("invalid generation limit"))?,
        },
    })
}

pub(crate) fn verify_install_target_in_store(
    c: &Commands,
    root: &Path,
    system: &str,
    plan: &assbox_policy::InstallPlan,
) -> Result<()> {
    let bytes = assbox_system::files::target_store_receipt(root, system)?;
    let binding = decode_binding(c, &bytes)?;
    assbox_policy::validate_boot_target(&binding, &binding)?;
    let binding = binding.binding;
    let esp = plan
        .esp()
        .map_or(String::new(), |p| format!("/dev/disk/by-uuid/{}", p.uuid));
    if binding.architecture != plan.inventory().architecture
        || binding.mode != plan.boot()
        || binding.platform != plan.request().choices.platform
        || binding.disk != plan.inventory().disk(&plan.root().parent)?.persistent_path
        || binding.root_device != format!("/dev/disk/by-uuid/{}", plan.root().uuid)
        || binding.esp_device != esp
    {
        return Err(Error::new(
            "built generation does not match the validated installation plan",
        ));
    }
    Ok(())
}

impl BootGuard {
    pub(crate) fn capture(c: &Commands, destination: &Path, target_system: &str) -> Result<Self> {
        let current = assbox_system::probe::current_system()?;
        let binding = read_binding(c, &current)?;
        let target = read_binding(c, target_system)?;
        assbox_policy::validate_boot_target(&binding, &target)?;
        let boot = [
            binding.binding.mode.as_str().to_owned(),
            binding.binding.disk,
        ];
        files::create_private(destination)?;
        let disk = if boot[1].is_empty() {
            let source = c.text(
                "findmnt",
                &[
                    "--noheadings",
                    "--raw",
                    "--output",
                    "SOURCE",
                    "--mountpoint",
                    "/",
                ],
            )?;
            let source = io(fs::canonicalize(source.trim()))?;
            c.text(
                "lsblk",
                &[
                    "--noheadings",
                    "--paths",
                    "--nodeps",
                    "--output",
                    "PKNAME",
                    files::path_text(&source)?,
                ],
            )?
            .trim()
            .to_owned()
        } else {
            io(fs::canonicalize(&boot[1]))?
                .to_string_lossy()
                .into_owned()
        };
        if !disk.starts_with("/dev/")
            || disk.chars().any(char::is_whitespace)
            || disk.contains("..")
        {
            return Err(Error::new(
                "cannot bind boot preservation to one physical disk",
            ));
        }
        let table = c.capture("sfdisk", &["--json", &disk])?;
        files::atomic_write(&destination.join("partition-table.json"), &table, 0o600)?;
        let apple = boot[0] == "apple-refind";
        let (firmware, unrelated_esp, esp_source) = if apple {
            c.run("mountpoint", &["-q", "/boot/efi"])?;
            let source = c.text(
                "findmnt",
                &[
                    "--noheadings",
                    "--raw",
                    "--output",
                    "SOURCE",
                    "--mountpoint",
                    "/boot/efi",
                ],
            )?;
            let vars = c.capture("efibootmgr", &["-v"])?;
            files::atomic_write(&destination.join("firmware.txt"), &vars, 0o600)?;
            let manifest = crate::install::esp_manifest(c, Path::new("/boot/efi"), true)?;
            let text = manifest
                .iter()
                .map(|(name, hash)| format!("{hash}  {name}\n"))
                .collect::<String>();
            files::atomic_write(
                &destination.join("unrelated-esp.sha256"),
                text.as_bytes(),
                0o600,
            )?;
            c.run(
                "tar",
                &[
                    "--create",
                    "--file",
                    files::path_text(&destination.join("esp.tar"))?,
                    "--one-file-system",
                    "--directory",
                    "/boot/efi",
                    ".",
                ],
            )?;
            (Some(vars), Some(manifest), Some(source))
        } else {
            (None, None, None)
        };
        Ok(Self {
            disk,
            table,
            firmware,
            unrelated_esp,
            esp_source,
        })
    }
    pub(crate) fn verify(&self, c: &Commands) -> Result<()> {
        if c.capture("sfdisk", &["--json", &self.disk])? != self.table {
            return Err(Error::new(
                "boot activation changed partition geometry; inspect the retained journal",
            ));
        }
        if let Some(expected) = &self.firmware
            && c.capture("efibootmgr", &["-v"])? != *expected
        {
            return Err(Error::new("Apple EFI variables changed unexpectedly"));
        }
        if let Some(expected) = &self.unrelated_esp {
            let source = c.text(
                "findmnt",
                &[
                    "--noheadings",
                    "--raw",
                    "--output",
                    "SOURCE",
                    "--mountpoint",
                    "/boot/efi",
                ],
            )?;
            if self.esp_source.as_ref() != Some(&source)
                || crate::install::esp_manifest(c, Path::new("/boot/efi"), true)? != *expected
            {
                return Err(Error::new(
                    "Apple activation altered unrelated ESP files or mount ownership",
                ));
            }
        }
        Ok(())
    }
}
