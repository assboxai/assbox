// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_policy::*;

fn disk(name: &str, table: Table) -> Disk {
    Disk {
        path: name.into(),
        major_minor: format!("8:{}", name.as_bytes().last().unwrap()),
        bytes: 64 * 1024 * 1024 * 1024,
        serial: format!("test-{name}"),
        model: "Fixture disk".into(),
        persistent_path: format!("/dev/disk/by-id/test-{}", name.rsplit('/').next().unwrap()),
        table,
        read_only: false,
        hybrid_mbr: false,
        mounts: vec![],
        has_holders: false,
    }
}
fn partition(name: &str, parent: &str, fs: FileSystem, kind: &str) -> Partition {
    Partition {
        path: name.into(),
        parent: parent.into(),
        major_minor: format!("8:{}", name.as_bytes().last().unwrap()),
        bytes: 1024 * 1024 * 1024,
        start_bytes: 1024 * 1024,
        fs,
        uuid: format!("uuid-{name}"),
        partuuid: format!("partuuid-{name}"),
        part_type: kind.into(),
        mounts: vec![],
        read_only: false,
        has_holders: false,
    }
}
fn base(firmware: Firmware, table: Table) -> (Inventory, InstallRequest) {
    let mut parts = vec![
        partition("/dev/sda1", "/dev/sda", FileSystem::Ext4, "83"),
        partition("/dev/sdb1", "/dev/sdb", FileSystem::Exfat, "7"),
        partition("/dev/sdc1", "/dev/sdc", FileSystem::Fat, ESP_TYPE),
    ];
    let esp = if firmware == Firmware::Uefi {
        parts.push(partition(
            "/dev/sda2",
            "/dev/sda",
            FileSystem::Fat,
            ESP_TYPE,
        ));
        Some("/dev/sda2".into())
    } else if table == Table::Gpt {
        let mut boot = partition("/dev/sda2", "/dev/sda", FileSystem::None, BIOS_BOOT_TYPE);
        boot.uuid.clear();
        parts.push(boot);
        None
    } else {
        None
    };
    (
        Inventory {
            architecture: Architecture::X86_64,
            hardware: Hardware::default(),
            firmware,
            disks: vec![
                disk("/dev/sda", table),
                disk("/dev/sdb", Table::Gpt),
                disk("/dev/sdc", Table::Gpt),
            ],
            partitions: parts,
            live_media: LiveMedia::Disk {
                disk: "/dev/sdc".into(),
                source: "/dev/sdc1".into(),
                major_minor: "8:49".into(),
            },
        },
        InstallRequest {
            root: "/dev/sda1".into(),
            backup: "/dev/sdb1".into(),
            esp,
            choices: Choices {
                instance: Default::default(),
                hostname: Hostname::parse("assbox-test").unwrap(),
                timezone: "UTC".into(),
                components: Components::default(),
                presentation: Presentation::Headless,
                platform: Platform::Generic,
                devices: DevicePolicy::default(),
                scale: 1,
                allow_unfree: false,
                allow_mutable_code: false,
                autostart: Vec::new(),
                admin_ssh_key: None,
                agent_ssh_key: None,
                ssh_access: Default::default(),
                additional_packages: Default::default(),
                worker: None,
            },
        },
    )
}
#[test]
fn supported_firmware_and_table_matrix() {
    for (firmware, table, expected) in [
        (Firmware::Uefi, Table::Gpt, BootKind::Uefi),
        (Firmware::Bios, Table::Gpt, BootKind::BiosGpt),
        (Firmware::Bios, Table::Mbr, BootKind::BiosMbr),
    ] {
        let (inv, req) = base(firmware, table);
        assert_eq!(plan_install(inv, req).unwrap().boot(), expected);
    }
    for (fw, table) in [
        (Firmware::Uefi, Table::Mbr),
        (Firmware::Uefi, Table::Unknown),
        (Firmware::Bios, Table::Unknown),
    ] {
        let (inv, req) = base(fw, table);
        assert!(plan_install(inv, req).is_err());
    }
}
#[test]
fn only_apple_path_preserves_additional_partitions() {
    let (mut inv, mut req) = base(Firmware::Uefi, Table::Gpt);
    inv.partitions.push(partition(
        "/dev/sda3",
        "/dev/sda",
        FileSystem::Other,
        "7c3457ef-0000-11aa-aa11-00306543ecac",
    ));
    assert!(plan_install(inv.clone(), req.clone()).is_err());
    inv.hardware.model = "MacBookPro12,1".into();
    req.choices.platform = Platform::Macbookpro12_1;
    let plan = plan_install(inv, req).unwrap();
    assert_eq!(plan.boot(), BootKind::AppleRefind);
    assert_eq!(
        plan.inventory()
            .partitions
            .iter()
            .filter(|p| p.parent == "/dev/sda")
            .count(),
        3
    );
}

#[test]
fn hardware_refusals_apply_to_planning_and_revalidation() {
    let (mut inv, mut req) = base(Firmware::Uefi, Table::Gpt);
    inv.hardware.model = "MacBookPro11,1".into();
    req.choices.platform = Platform::Macbookpro11_1;
    req.choices.devices.wifi = true;
    req.choices.allow_unfree = true; // Application consent is not a driver exception.
    assert!(plan_install(inv.clone(), req.clone()).is_err());
    inv.hardware.wireless.push(WirelessInterface {
        name: "wlan0".into(),
        device_path: "devices/usb1/1-1".into(),
        driver: Some("ath9k_htc".into()),
        out_of_tree: false,
    });
    let plan = plan_install(inv.clone(), req).unwrap();
    assert!(plan.revalidate(&inv, &[]).is_ok());
    let mut disappeared = inv.clone();
    disappeared.hardware.wireless.clear();
    assert!(plan.revalidate(&disappeared, &[]).is_err());
    let mut replaced = inv.clone();
    replaced.hardware.wireless[0].device_path = "devices/usb1/1-2".into();
    assert!(plan.revalidate(&replaced, &[]).is_err());
    let mut driver_changed = inv.clone();
    driver_changed.hardware.wireless[0].out_of_tree = true;
    assert!(plan.revalidate(&driver_changed, &[]).is_err());
    inv.hardware.model = "MacBookPro15,1".into();
    assert!(plan.revalidate(&inv, &[]).is_err());
}
#[test]
fn backup_may_never_be_a_live_media_sibling() {
    let (inv, mut req) = base(Firmware::Uefi, Table::Gpt);
    req.backup = "/dev/sdc1".into();
    assert!(plan_install(inv, req).is_err());
}
#[test]
fn selected_media_must_be_on_three_different_disks() {
    let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
    inv.partitions[1].parent = "/dev/sda".into();
    assert!(plan_install(inv, req).is_err());
    let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
    inv.live_media = LiveMedia::Disk {
        disk: "/dev/sda".into(),
        source: "/dev/sda1".into(),
        major_minor: "8:49".into(),
    };
    assert!(plan_install(inv, req).is_err());
}

#[test]
fn different_names_do_not_make_a_second_backup_disk() {
    let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
    // Device aliases can differ in spelling while naming the same kernel disk.
    inv.disks[1].major_minor = inv.disks[0].major_minor.clone();
    assert!(plan_install(inv, req).is_err());
}
#[test]
fn all_selected_filesystems_require_offline_checks() {
    for fs in [FileSystem::Ext4, FileSystem::Fat, FileSystem::Exfat] {
        let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
        inv.partitions[1].fs = fs;
        assert!(plan_install(inv, req).is_ok());
        let (_, args) = filesystem_check(fs).unwrap();
        assert!(args.contains(&"-n"));
        assert!(!args.contains(&"-y"));
        assert!(!args.contains(&"-p"));
    }
    for fs in [FileSystem::None, FileSystem::Other] {
        assert!(filesystem_check(fs).is_err());
        let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
        inv.partitions[1].fs = fs;
        assert!(plan_install(inv, req).is_err());
    }
    assert_eq!(
        filesystem_check(FileSystem::Ext4).unwrap(),
        ("e2fsck", ["-f", "-n"].as_slice())
    );
    assert_eq!(
        filesystem_check(FileSystem::Fat).unwrap(),
        ("fsck.fat", ["-n"].as_slice())
    );
    assert_eq!(
        filesystem_check(FileSystem::Exfat).unwrap(),
        ("fsck.exfat", ["-n"].as_slice())
    );
}
#[test]
fn mounted_readonly_or_mapped_filesystems_are_rejected() {
    for index in [0, 1, 3] {
        for issue in 0..5 {
            let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
            let p = &mut inv.partitions[index];
            match issue {
                0 => p.read_only = true,
                1 => p.mounts.push("/elsewhere".into()),
                2 => p.has_holders = true,
                3 => p.uuid.clear(),
                _ => p.partuuid.clear(),
            }
            assert!(
                plan_install(inv, req).is_err(),
                "partition={index} issue={issue}"
            );
        }
    }
}
#[test]
fn whole_disk_mounts_holders_readonly_and_hybrid_tables_are_rejected() {
    for index in [0, 1] {
        for issue in 0..4 {
            let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
            match issue {
                0 => inv.disks[index].read_only = true,
                1 => inv.disks[index].hybrid_mbr = true,
                2 => inv.disks[index].mounts.push("/mounted".into()),
                _ => inv.disks[index].has_holders = true,
            }
            assert!(plan_install(inv, req).is_err());
        }
    }
}
#[test]
fn uuid_aliases_are_rejected_even_on_unselected_media() {
    for selected in [0, 1, 3] {
        for field in ["uuid", "partuuid"] {
            let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
            if field == "uuid" {
                inv.partitions[2].uuid = inv.partitions[selected].uuid.clone();
            } else {
                inv.partitions[2].partuuid = inv.partitions[selected].partuuid.clone();
            }
            assert!(plan_install(inv, req).is_err());
        }
    }
}
#[test]
fn newly_attached_media_cannot_alias_selected_filesystems() {
    let (inv, req) = base(Firmware::Uefi, Table::Gpt);
    let plan = plan_install(inv.clone(), req.clone()).unwrap();
    let mut attached = inv.clone();
    attached.disks.push(disk("/dev/sdd", Table::Gpt));
    attached
        .partitions
        .push(partition("/dev/sdd1", "/dev/sdd", FileSystem::Ext4, "83"));
    assert!(plan.revalidate(&attached, &[]).is_ok());

    for selected in [0, 1, 3] {
        for field in ["uuid", "partuuid"] {
            let mut aliased = attached.clone();
            let other = aliased.partitions.last_mut().unwrap();
            if field == "uuid" {
                other.uuid = inv.partitions[selected].uuid.clone();
            } else {
                other.partuuid = inv.partitions[selected].partuuid.clone();
            }
            assert!(plan_install(aliased.clone(), req.clone()).is_err());
            assert!(
                plan.revalidate(&aliased, &[]).is_err(),
                "{selected}: {field}"
            );
            // Owned mounts do not waive global identifier uniqueness.
            aliased.partitions[0].mounts.push("/target".into());
            assert!(
                plan.revalidate(&aliased, &[("/dev/sda1", "/target")])
                    .is_err()
            );
        }
    }
    attached.partitions[0].mounts.push("/target".into());
    assert!(
        plan.revalidate(&attached, &[("/dev/sda1", "/target")])
            .is_ok()
    );
}

#[test]
fn bios_has_a_deliberately_narrow_preservation_contract() {
    let (mut inv, req) = base(Firmware::Bios, Table::Gpt);
    inv.partitions.last_mut().unwrap().bytes = 1024 * 1024 - 1;
    assert!(plan_install(inv, req).is_err());
    let (mut inv, req) = base(Firmware::Bios, Table::Gpt);
    inv.partitions.last_mut().unwrap().fs = FileSystem::Ext4;
    assert!(plan_install(inv, req).is_err());
    for fw in [Firmware::Bios, Firmware::Uefi] {
        let (mut inv, mut req) = base(fw, Table::Gpt);
        inv.hardware.model = "MacBookPro12,1".into();
        req.choices.platform = Platform::Macbookpro12_1;
        inv.disks[0].persistent_path.clear();
        assert!(plan_install(inv, req).is_err());
    }
    let (mut inv, req) = base(Firmware::Bios, Table::Mbr);
    inv.partitions[0].start_bytes = 1024 * 1024 - 1;
    assert!(plan_install(inv, req).is_err());
    let (mut inv, req) = base(Firmware::Bios, Table::Mbr);
    inv.partitions[0].part_type = "5".into();
    assert!(plan_install(inv, req).is_err());
    let (mut inv, req) = base(Firmware::Bios, Table::Mbr);
    inv.partitions
        .push(partition("/dev/sda2", "/dev/sda", FileSystem::Other, "7"));
    assert!(plan_install(inv, req).is_err());
}
#[test]
fn stale_identity_geometry_and_mount_ownership_are_rechecked() {
    let (inv, req) = base(Firmware::Uefi, Table::Gpt);
    let plan = plan_install(inv.clone(), req).unwrap();
    assert!(plan.revalidate(&inv, &[]).is_ok());
    for change in 0..8 {
        let mut now = inv.clone();
        match change {
            0 => now.firmware = Firmware::Bios,
            1 => {
                now.live_media = LiveMedia::Disk {
                    disk: "/dev/sdb".into(),
                    source: "/dev/sdb1".into(),
                    major_minor: "8:49".into(),
                }
            }
            2 => now.disks[0].serial.push('x'),
            3 => now.partitions[0].start_bytes += 512,
            4 => now.partitions[0].bytes += 512,
            5 => now.partitions[0].has_holders = true,
            6 => now.partitions[0].mounts.push("/foreign".into()),
            _ => {
                now.partitions.pop();
            }
        }
        assert!(plan.revalidate(&now, &[]).is_err(), "change={change}");
    }
    let mut mounted = inv.clone();
    mounted.partitions[0].mounts.push("/target".into());
    assert!(
        plan.revalidate(&mounted, &[("/dev/sda1", "/target")])
            .is_ok()
    );
    assert!(
        plan.revalidate(&mounted, &[("/dev/sdb1", "/target")])
            .is_err()
    );
    assert!(
        plan.revalidate(&mounted, &[("/dev/sda1", "/wrong")])
            .is_err()
    );
}
#[test]
fn invalid_selection_and_esp_never_construct_a_plan() {
    for role in ["root", "backup", "esp"] {
        let (inv, mut req) = base(Firmware::Uefi, Table::Gpt);
        match role {
            "root" => req.root = "/dev/missing".into(),
            "backup" => req.backup = "/dev/missing".into(),
            _ => req.esp = None,
        }
        assert!(plan_install(inv, req).is_err());
    }
    for bad in 0..4 {
        let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
        match bad {
            0 => inv.partitions[0].fs = FileSystem::Fat,
            1 => inv.partitions[3].fs = FileSystem::Ext4,
            2 => inv.partitions[3].parent = "/dev/sdb".into(),
            _ => inv.partitions[3].part_type = "bad".into(),
        }
        assert!(plan_install(inv, req).is_err());
    }
}

fn optical() -> LiveMedia {
    LiveMedia::Optical {
        device: "/dev/sr0".into(),
        major_minor: "11:0".into(),
        bytes: 1024 * 1024,
        filesystem: "iso9660".into(),
        uuid: "test-iso".into(),
        read_only: true,
        mounted_read_only: true,
    }
}
#[test]
fn arm_is_generic_uefi_not_an_intel_mac_or_legacy_bios_machine() {
    for architecture in [Architecture::X86_64, Architecture::Aarch64] {
        for firmware in [Firmware::Uefi, Firmware::Bios] {
            for platform in [
                Platform::Generic,
                Platform::AppleIntel,
                Platform::Macbookpro11_1,
                Platform::Macbookpro12_1,
            ] {
                let (mut inv, mut req) = base(firmware, Table::Gpt);
                inv.architecture = architecture;
                req.choices.platform = platform;
                inv.hardware.model = match platform {
                    Platform::Macbookpro11_1 => "MacBookPro11,1",
                    Platform::Macbookpro12_1 => "MacBookPro12,1",
                    _ => "",
                }
                .into();
                let expected = if architecture == Architecture::Aarch64 {
                    firmware == Firmware::Uefi && platform == Platform::Generic
                } else {
                    (firmware == Firmware::Uefi || platform == Platform::Generic)
                        && platform != Platform::AppleIntel
                };
                assert_eq!(
                    plan_install(inv, req).is_ok(),
                    expected,
                    "{architecture:?} {firmware:?} {platform:?}"
                );
            }
        }
    }
    let (mut inv, req) = base(Firmware::Uefi, Table::Mbr);
    inv.architecture = Architecture::Aarch64;
    assert!(plan_install(inv, req).is_err());
}
#[test]
fn optical_media_do_not_require_a_third_disk() {
    for architecture in [Architecture::X86_64, Architecture::Aarch64] {
        let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
        inv.architecture = architecture;
        inv.disks.retain(|d| d.path != "/dev/sdc");
        inv.partitions.retain(|p| p.parent != "/dev/sdc");
        inv.live_media = optical();
        let plan = plan_install(inv.clone(), req.clone()).unwrap();
        assert!(plan.revalidate(&inv, &[]).is_ok());
        for change in 0..7 {
            let mut changed = inv.clone();
            if let LiveMedia::Optical {
                ref mut device,
                ref mut major_minor,
                ref mut bytes,
                ref mut filesystem,
                ref mut uuid,
                ref mut read_only,
                ref mut mounted_read_only,
            } = changed.live_media
            {
                match change {
                    0 => *read_only = false,
                    1 => *mounted_read_only = false,
                    2 => *bytes = 0,
                    3 => *filesystem = "ext4".into(),
                    4 => *device = "/dev/sda".into(),
                    5 => *major_minor = inv.disks[0].major_minor.clone(),
                    _ => uuid.push('x'),
                }
            }
            if change < 6 {
                assert!(plan_install(changed.clone(), req.clone()).is_err());
            }
            assert!(plan.revalidate(&changed, &[]).is_err());
        }
        let mut changed = inv.clone();
        changed.architecture = if architecture == Architecture::X86_64 {
            Architecture::Aarch64
        } else {
            Architecture::X86_64
        };
        assert!(plan.revalidate(&changed, &[]).is_err());
    }
}
#[test]
fn forged_disk_media_source_is_not_accepted() {
    let (mut inv, req) = base(Firmware::Uefi, Table::Gpt);
    inv.live_media = LiveMedia::Disk {
        disk: "/dev/sdc".into(),
        source: "/dev/sda1".into(),
        major_minor: "8:49".into(),
    };
    assert!(plan_install(inv, req).is_err());
}

#[test]
fn bios_boot_partition_requires_raw_write_permission() {
    let (mut inv, req) = base(Firmware::Bios, Table::Gpt);
    inv.partitions.last_mut().unwrap().read_only = true;
    assert!(plan_install(inv, req).is_err());
}
