// SPDX-License-Identifier: GPL-3.0-or-later
use crate::{commands::Commands, files::io};
use assbox_domain::*;
use std::{
    fs::{self, File},
    io::Read,
    path::Path,
};

fn number(s: &str) -> Result<u64> {
    s.parse()
        .map_err(|_| Error::new("invalid numeric block-device field"))
}
fn boolean(s: &str) -> Result<bool> {
    match s {
        "1" | "true" => Ok(true),
        "0" | "false" => Ok(false),
        _ => Err(Error::new("invalid boolean block-device field")),
    }
}
fn safe_device(s: &str) -> bool {
    s.starts_with("/dev/")
        && !s.contains("..")
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"/_-.".contains(&b))
}
fn has_holders(device: &str) -> Result<bool> {
    let base = Path::new(device)
        .file_name()
        .ok_or_else(|| Error::new("device basename missing"))?;
    let directory = Path::new("/sys/class/block").join(base).join("holders");
    Ok(io(fs::read_dir(directory))?.next().is_some())
}
fn persistent_disk(device: &str) -> Result<String> {
    let mut choices = Vec::new();
    if let Ok(entries) = fs::read_dir("/dev/disk/by-id") {
        for entry in entries {
            let entry = io(entry)?;
            if fs::canonicalize(entry.path()).is_ok_and(|p| p == Path::new(device)) {
                let path = entry.path().to_string_lossy().into_owned();
                if path.chars().all(|c| !c.is_control()) {
                    choices.push(path);
                }
            }
        }
    }
    choices.sort();
    Ok(choices.into_iter().next().unwrap_or_default())
}
fn hybrid(path: &str, table: Table) -> Result<bool> {
    if table == Table::Unknown {
        return Ok(false);
    }
    let mut sector = [0; 512];
    io(io(File::open(path))?.read_exact(&mut sector))?;
    if sector[510..512] != [0x55, 0xaa] {
        return Err(Error::new("invalid MBR signature"));
    }
    let types = [sector[450], sector[466], sector[482], sector[498]];
    let protective = types.iter().filter(|t| **t == 0xee).count();
    Ok(match table {
        Table::Gpt => protective != 1 || types.iter().any(|t| *t != 0 && *t != 0xee),
        Table::Mbr => protective != 0,
        Table::Unknown => false,
    })
}

pub fn inventory(c: &Commands) -> Result<Inventory> {
    c.run("mountpoint", &["-q", "/iso"])?;
    let json=c.capture("lsblk", &["--json","--bytes","--paths","--output",
        "NAME,TYPE,PKNAME,MAJ:MIN,SIZE,RO,FSTYPE,UUID,PARTUUID,PARTTYPE,PTTYPE,SERIAL,MOUNTPOINTS,MODEL"])?;
    let fields=c.jq_fields(&json,r#".blockdevices[] | recurse(.children[]?) |
      select(.type == "disk" or .type == "part" or .type == "rom") |
      [.type,.name,(.pkname // ""),.["maj:min"],(.size|tostring),(.ro|tostring),
       (.fstype // ""),(.uuid // ""),(.partuuid // ""),(.parttype // ""),(.pttype // ""),
       (.serial // ""),((.mountpoints // [])|map(select(. != null))|join("\u001f")),(.model // "")] |
      .[] | . + "\u0000""#)?;
    if fields.len() % 14 != 0 {
        return Err(Error::new("incomplete block-device record"));
    }
    let mut disks = Vec::new();
    let mut partitions = Vec::new();
    let mut optical = Vec::new();
    for f in fields.chunks_exact(14) {
        if !safe_device(&f[1]) {
            return Err(Error::new("unexpected device path"));
        }
        if f[0] == "disk" {
            let table = match f[10].as_str() {
                "gpt" => Table::Gpt,
                "dos" => Table::Mbr,
                _ => Table::Unknown,
            };
            disks.push(Disk {
                path: f[1].clone(),
                major_minor: f[3].clone(),
                bytes: number(&f[4])?,
                serial: f[11].clone(),
                model: f[13].clone(),
                persistent_path: persistent_disk(&f[1])?,
                table,
                read_only: boolean(&f[5])?,
                hybrid_mbr: hybrid(&f[1], table)?,
                mounts: if f[12].is_empty() {
                    Vec::new()
                } else {
                    f[12].split('\u{1f}').map(str::to_owned).collect()
                },
                has_holders: has_holders(&f[1])?,
            });
        } else if f[0] == "rom" {
            optical.push((
                f[1].clone(),
                f[3].clone(),
                number(&f[4])?,
                boolean(&f[5])?,
                f[6].clone(),
                f[7].clone(),
            ));
        } else {
            if !safe_device(&f[2]) {
                return Err(Error::new("unsupported partition parent"));
            }
            for id in [&f[7], &f[8]] {
                if !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
                    return Err(Error::new("invalid filesystem identity"));
                }
            }
            let base = Path::new(&f[1])
                .file_name()
                .ok_or_else(|| Error::new("device basename missing"))?
                .to_string_lossy();
            // Linux sysfs defines partition start in 512-byte sectors, even on 4Kn disks.
            let sectors =
                number(io(fs::read_to_string(format!("/sys/class/block/{base}/start")))?.trim())?;
            partitions.push(Partition {
                path: f[1].clone(),
                parent: f[2].clone(),
                major_minor: f[3].clone(),
                bytes: number(&f[4])?,
                start_bytes: sectors
                    .checked_mul(512)
                    .ok_or_else(|| Error::new("partition offset overflow"))?,
                fs: match f[6].as_str() {
                    "ext4" => FileSystem::Ext4,
                    "vfat" => FileSystem::Fat,
                    "exfat" => FileSystem::Exfat,
                    "" => FileSystem::None,
                    _ => FileSystem::Other,
                },
                uuid: f[7].clone(),
                partuuid: f[8].clone(),
                part_type: f[9].to_lowercase(),
                mounts: if f[12].is_empty() {
                    Vec::new()
                } else {
                    f[12].split('\u{1f}').map(str::to_owned).collect()
                },
                read_only: boolean(&f[5])?,
                has_holders: has_holders(&f[1])?,
            });
        }
    }
    let live_source = c.text(
        "findmnt",
        &[
            "--noheadings",
            "--raw",
            "--output",
            "SOURCE",
            "--mountpoint",
            "/iso",
        ],
    )?;
    let canonical = io(fs::canonicalize(live_source.trim()))?
        .to_string_lossy()
        .into_owned();
    let live_media = if let Some(disk) = disks.iter().find(|d| d.path == canonical) {
        LiveMedia::Disk {
            disk: disk.path.clone(),
            source: canonical,
            major_minor: disk.major_minor.clone(),
        }
    } else if let Some(partition) = partitions.iter().find(|p| p.path == canonical) {
        LiveMedia::Disk {
            disk: partition.parent.clone(),
            source: canonical,
            major_minor: partition.major_minor.clone(),
        }
    } else if let Some((device, major_minor, bytes, read_only, filesystem, uuid)) =
        optical.iter().find(|p| p.0 == canonical)
    {
        let options = c.text(
            "findmnt",
            &[
                "--noheadings",
                "--raw",
                "--output",
                "OPTIONS",
                "--mountpoint",
                "/iso",
            ],
        )?;
        LiveMedia::Optical {
            device: device.clone(),
            major_minor: major_minor.clone(),
            bytes: *bytes,
            filesystem: filesystem.clone(),
            uuid: uuid.clone(),
            read_only: *read_only,
            mounted_read_only: options.trim().split(',').any(|option| option == "ro"),
        }
    } else {
        return Err(Error::new(
            "cannot identify local installer media; loop, network and mapped roots are unsupported",
        ));
    };
    Ok(Inventory {
        architecture: architecture(c)?,
        hardware: crate::hardware::observe()?,
        firmware: if Path::new("/sys/firmware/efi").is_dir() {
            Firmware::Uefi
        } else {
            Firmware::Bios
        },
        disks,
        partitions,
        live_media,
    })
}

pub fn architecture(c: &Commands) -> Result<Architecture> {
    let kernel: Architecture = c.text("uname", &["-m"])?.trim().parse()?;
    let executable: Architecture = std::env::consts::ARCH.parse()?;
    if kernel != executable {
        return Err(Error::new(
            "use an Assbox executable native to the live kernel; cross-installation is unsupported",
        ));
    }
    Ok(kernel)
}

pub fn default_network(c: &Commands) -> Result<Vec<bool>> {
    let mut kinds = Vec::new();
    for family in ["-4", "-6"] {
        let json = c.capture("ip", &[family, "-json", "route", "show", "default"])?;
        let fields = c.jq_fields(&json, r#"[.[].dev // empty] | unique | .[] | . + "\u0000""#)?;
        for dev in fields {
            if !dev
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
            {
                return Ok(Vec::new());
            }
            let p = Path::new("/sys/class/net").join(&dev);
            if p.join("wireless").is_dir() {
                kinds.push(true);
            } else if p.join("device").exists() {
                kinds.push(false);
            } else {
                return Ok(Vec::new());
            } // VPN, bridge or unknown underlay: ask.
        }
    }
    Ok(kinds)
}
pub fn display_edids() -> Result<Vec<Vec<u8>>> {
    let mut internal = Vec::new();
    let mut external = Vec::new();
    for entry in io(fs::read_dir("/sys/class/drm"))? {
        let e = io(entry)?;
        let p = e.path();
        let name = e.file_name().to_string_lossy().into_owned();
        if fs::read_to_string(p.join("status"))
            .unwrap_or_default()
            .trim()
            != "connected"
        {
            continue;
        }
        if let Ok(bytes) = fs::read(p.join("edid")) {
            if name.contains("eDP") || name.contains("LVDS") {
                internal.push(bytes);
            } else {
                external.push(bytes);
            }
        }
    }
    Ok(if internal.is_empty() {
        external
    } else {
        internal
    })
}
/// Unknown battery presence and unreadable capacities must not masquerade as a desktop.
pub fn power() -> (BatteryPresence, Option<bool>, Option<u8>) {
    let Ok(entries) = fs::read_dir("/sys/class/power_supply") else {
        return (BatteryPresence::Unknown, None, None);
    };
    let mut presence = BatteryPresence::Absent;
    let mut ac = None;
    let mut capacity: Option<u8> = None;
    let mut incomplete = false;
    for entry in entries {
        let Ok(entry) = entry else {
            incomplete = true;
            continue;
        };
        let p = entry.path();
        let Ok(kind) = fs::read_to_string(p.join("type")) else {
            incomplete = true;
            continue;
        };
        if kind.trim() == "Battery" {
            if fs::read_to_string(p.join("present")).is_ok_and(|s| s.trim() == "0") {
                continue;
            }
            presence = BatteryPresence::Present;
            let percent = fs::read_to_string(p.join("capacity"))
                .ok()
                .and_then(|s| s.trim().parse::<u8>().ok())
                .filter(|n| *n <= 100);
            if let Some(n) = percent {
                capacity = Some(capacity.map_or(n, |old| old.min(n)));
            } else {
                incomplete = true;
            }
        } else if let Ok(s) = fs::read_to_string(p.join("online")) {
            match s.trim() {
                "1" => ac = Some(true),
                "0" => ac = Some(ac.unwrap_or(false)),
                _ => incomplete = true,
            }
        }
    }
    if incomplete {
        if presence == BatteryPresence::Absent {
            presence = BatteryPresence::Unknown;
        }
        capacity = None;
    }
    (presence, ac, capacity)
}
pub fn current_system() -> Result<String> {
    Ok(io(fs::canonicalize("/run/current-system"))?
        .to_string_lossy()
        .into_owned())
}
pub fn profile_system() -> Result<String> {
    Ok(io(fs::canonicalize("/nix/var/nix/profiles/system"))?
        .to_string_lossy()
        .into_owned())
}
pub fn runtime_json() -> Result<Vec<u8>> {
    let path = io(fs::canonicalize("/etc/assbox/runtime.json"))?;
    if !path.starts_with("/nix/store") {
        return Err(Error::new("runtime policy is not an immutable NixOS file"));
    }
    io(fs::read(path))
}
pub fn runtime(c: &Commands) -> Result<Vec<String>> {
    let bytes = runtime_json()?;
    c.jq_fields(&bytes,r#"[(.selectedComponents|join(",")),.presentation,.updates.calendar,(.updates.rebootGraceSeconds|tostring),
        (.updates.minimumBatteryPercent|tostring),(.updates.enable|tostring)] | .[] | . + "\u0000""#)
}
