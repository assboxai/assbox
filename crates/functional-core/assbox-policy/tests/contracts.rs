// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_policy::*;
fn choices() -> Choices {
    Choices {
        instance: Default::default(),
        hostname: Hostname::parse("assbox-example").unwrap(),
        timezone: "America/New_York".into(),
        components: Components::default(),
        presentation: Presentation::Headless,
        platform: Platform::Generic,
        devices: DevicePolicy::default(),
        scale: 1,
        allow_unfree: true,
        allow_mutable_code: true,
        autostart: Vec::new(),
        admin_ssh_key: None,
        agent_ssh_key: None,
        ssh_access: Default::default(),
        additional_packages: Default::default(),
        worker: None,
    }
}
#[test]
fn exactly_ten_application_presentation_combinations_are_valid() {
    let mut valid = 0;
    for app in [
        Components::default(),
        Components::from(Component::ChatgptDesktop),
        Components::from(Component::Opencode),
        Components::from(Component::Openclaw),
    ] {
        for presentation in [
            Presentation::Headless,
            Presentation::X11,
            Presentation::Wayland,
        ] {
            let mut c = choices();
            c.components = app;
            if app.contains(Component::ChatgptDesktop) {
                c.worker = Some(assbox_domain::worker::WorkerSpec {
                    components: Component::Codex.into(),
                    mutable_components: Components::default(),

                    memory_mib: 3072,
                    vcpus: 2,
                    state_gib: 32,
                    auto_state: false,
                    uplinks: vec![],
                    network: assbox_domain::worker::WorkerNetwork::Offline,
                    nameservers: vec![],
                    guest_sudo: false,
                });
            }
            c.presentation = presentation;
            let expected = app != Components::from(Component::ChatgptDesktop)
                || presentation == Presentation::X11;
            assert_eq!(c.validate().is_ok(), expected);
            if expected {
                valid += 1;
            }
        }
    }
    assert_eq!(valid, 10);
}
#[test]
fn input_contract_rejects_injection_and_unfree_without_consent() {
    let mut c = choices();
    c.components = Components::from(Component::ChatgptDesktop);
    c.presentation = Presentation::X11;
    c.allow_unfree = false;
    assert!(c.validate().is_err());
    for timezone in [
        "",
        "/etc/passwd",
        "../passwd",
        "America/../etc",
        "a\nb",
        "UTC;foo",
        "A//B",
    ] {
        let mut c = choices();
        c.timezone = timezone.into();
        assert!(c.validate().is_err());
    }
    for scale in [0, 4, 255] {
        let mut c = choices();
        c.scale = scale;
        assert!(c.validate().is_err());
    }
    let mut c = choices();
    c.admin_ssh_key = Some("command=evil ssh-ed25519 AAAA".into());
    assert!(c.validate().is_err());
    let mut c = choices();
    c.admin_ssh_key = Some("ssh-ed25519 AAAA\ncommand=evil".into());
    assert!(c.validate().is_err());
}
#[test]
fn happier_needs_no_backend_list_and_editor_access_is_separate() {
    let mut c = choices();
    c.components = "happier,happier-daemon,codex,pi,omp".parse().unwrap();
    assert!(c.validate().is_ok());
    c.components.insert(Component::ZedRemoteHost);
    c.admin_ssh_key = Some("ssh-ed25519 admin-fixture".into());
    assert!(c.validate().is_err());
    c.agent_ssh_key = Some("ssh-ed25519 agent-fixture".into());
    assert!(c.validate().is_ok());
    c.agent_ssh_key = Some("command=evil ssh-ed25519 fixture".into());
    assert!(c.validate().is_err());
}
fn edid(px: u16, mm: u16) -> [u8; 128] {
    let mut e = [0; 128];
    e[..8].copy_from_slice(&[0, 255, 255, 255, 255, 255, 255, 0]);
    e[54] = 1;
    e[56] = px as u8;
    e[58] = ((px >> 8) as u8) << 4;
    e[66] = mm as u8;
    e[68] = ((mm >> 8) as u8) << 4;
    e[127] = 0u8.wrapping_sub(e[..127].iter().fold(0u8, |a, b| a.wrapping_add(*b)));
    e
}
#[test]
fn edid_is_a_validated_suggestion_not_a_headless_setting() {
    assert_eq!(suggested_scale(&edid(1920, 510)), Some(1));
    assert_eq!(suggested_scale(&edid(2560, 290)), Some(2));
    assert_eq!(suggested_scale(&edid(2560, 0)), None);
    assert_eq!(suggested_scale(&edid(100, 400)), None);
    let mut corrupt = edid(1920, 510);
    corrupt[20] ^= 1;
    assert_eq!(suggested_scale(&corrupt), None);
    assert_eq!(suggested_scale(&[]), None);
    assert_eq!(
        recommended_platform("MacBookPro11,1\n"),
        Platform::Macbookpro11_1
    );
    assert_eq!(
        recommended_platform("MacBookPro12,1"),
        Platform::Macbookpro12_1
    );
    assert_eq!(recommended_platform("MacPro5,1"), Platform::AppleIntel);
    assert_eq!(recommended_platform("ThinkPad"), Platform::Generic);
}
fn audit() -> Audit {
    Audit {
        enabled: true,
        components: Components::default(),
        presentation: Presentation::Headless,
        firewall: true,
        root_locked: true,
        agent_locked: true,
        agent_groups: vec!["users".into()],
        trusted_users: vec!["root".into()],
        sandbox: true,
        require_signatures: true,
        accept_flake_config: false,
        automount: false,
        passwordless_sudo: false,
        efi_writes: false,
        boot: BootKind::AppleRefind,
    }
}
#[test]
fn evaluated_policy_guards_are_independent_of_module_defaults() {
    assert!(validate_audit(&audit()).is_ok());
    for issue in 0..14 {
        let mut a = audit();
        match issue {
            0 => a.enabled = false,
            1 => a.firewall = false,
            2 => a.root_locked = false,
            3 => a.agent_locked = false,
            4 => a.sandbox = false,
            5 => a.require_signatures = false,
            6 => a.accept_flake_config = true,
            7 => a.automount = true,
            8 => a.passwordless_sudo = true,
            9 => a.agent_groups.push("wheel".into()),
            10 => a.trusted_users.push("agent".into()),
            11 => a.efi_writes = true,
            12 => a.components = Components::from(Component::ChatgptDesktop),
            _ => a.agent_groups.push("disk".into()),
        }
        assert!(validate_audit(&a).is_err(), "issue={issue}");
    }
}
#[test]
fn restart_recovery_contract_is_exhaustive_and_typed() {
    for (phase, expected) in [
        (Phase::Prepared, Recovery::DiscardCandidate),
        (Phase::Built, Recovery::DiscardCandidate),
        (Phase::Published, Recovery::RestoreSources),
        (Phase::Activating, Recovery::InspectActivation),
        (Phase::Committed, Recovery::Nothing),
    ] {
        assert_eq!(phase.as_str().parse::<Phase>().unwrap(), phase);
        assert_eq!(recovery_after_interruption(phase), expected);
    }
    assert!("pretend-complete".parse::<Phase>().is_err());
}

#[test]
fn application_architecture_matrix_is_explicit() {
    for architecture in [Architecture::X86_64, Architecture::Aarch64] {
        for app in [
            Components::default(),
            Components::from(Component::ChatgptDesktop),
            Components::from(Component::Opencode),
            Components::from(Component::Openclaw),
        ] {
            for presentation in [
                Presentation::Headless,
                Presentation::X11,
                Presentation::Wayland,
            ] {
                assert_eq!(
                    components_supported(architecture, app, presentation),
                    app != Components::from(Component::ChatgptDesktop)
                        || presentation == Presentation::X11
                );
            }
        }
    }
}
#[test]
fn unknown_power_never_masquerades_as_confirmed_ac_or_no_battery() {
    let f = MaintenanceFacts {
        changed_generation: true,
        stage_succeeded: true,
        battery_presence: BatteryPresence::Present,
        on_ac: None,
        battery_percent: Some(5),
        minimum_battery: 20,
    };
    assert_eq!(reboot_decision(f), RebootDecision::RetryForPower);
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            on_ac: Some(false),
            battery_percent: None,
            ..f
        }),
        RebootDecision::RetryForPower
    );
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            battery_presence: BatteryPresence::Unknown,
            battery_percent: None,
            ..f
        }),
        RebootDecision::RetryForPower
    );
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            battery_presence: BatteryPresence::Absent,
            battery_percent: None,
            ..f
        }),
        RebootDecision::Reboot
    );
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            on_ac: Some(true),
            ..f
        }),
        RebootDecision::Reboot
    );
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            battery_percent: Some(20),
            ..f
        }),
        RebootDecision::Reboot
    );
    assert_eq!(
        reboot_decision(MaintenanceFacts {
            battery_percent: Some(101),
            ..f
        }),
        RebootDecision::RetryForPower
    );
}
#[test]
fn rollback_validates_the_target_generation_not_only_current_settings() {
    let current = BootReceipt {
        binding: BootBinding {
            architecture: Architecture::Aarch64,
            mode: BootKind::Uefi,
            platform: Platform::Generic,
            disk: "/dev/disk/by-id/disk".into(),
            root_device: "/dev/disk/by-uuid/root".into(),
            esp_device: "/dev/disk/by-uuid/esp".into(),
            loader: "evaluated-loader-binding".into(),
        },
        policy: BootPolicy { generations: 8 },
    };
    assert!(validate_boot_target(&current, &current).is_ok());
    for difference in 0..7 {
        let mut target = current.clone();
        match difference {
            0 => target.binding.architecture = Architecture::X86_64,
            1 => target.binding.mode = BootKind::BiosGpt,
            2 => target.binding.platform = Platform::AppleIntel,
            3 => target.binding.disk.push('x'),
            4 => target.binding.root_device.push('x'),
            5 => target.binding.esp_device.clear(),
            _ => target.binding.loader.push('x'),
        }
        assert!(validate_boot_target(&current, &target).is_err());
    }
    for count in [2, 8, 16, 32] {
        let mut target = current.clone();
        target.policy.generations = count;
        assert!(validate_boot_target(&current, &target).is_ok());
    }
    for count in [0, 1, 33, u32::MAX] {
        let mut target = current.clone();
        target.policy.generations = count;
        assert!(validate_boot_target(&current, &target).is_err());
    }
    let mut invalid = current;
    invalid.binding.mode = BootKind::BiosGpt;
    assert!(validate_boot_target(&invalid, &invalid).is_err());
}

#[test]
fn prepared_root_rejects_recovered_files_and_disguised_entries() {
    let empty = PreparedRootEntry {
        name: "lost+found".into(),
        is_directory: true,
        owner: 0,
        group: 0,
        mode: 0o40700,
        same_filesystem: true,
        empty: true,
    };
    assert!(validate_prepared_root(&[]).is_ok());
    assert!(validate_prepared_root(std::slice::from_ref(&empty)).is_ok());
    for change in 0..9 {
        let mut entry = empty.clone();
        match change {
            0 => entry.empty = false,        // Recovered files belong to the operator.
            1 => entry.is_directory = false, // Includes symlinks, FIFOs and files.
            2 => entry.owner = 1000,
            3 => entry.group = 1000,
            4 => entry.mode |= 0o002,
            5 => entry.mode |= 0o020,
            6 => entry.mode |= 0o2000,
            7 => entry.same_filesystem = false,
            _ => entry.name = "important-data".into(),
        }
        assert!(validate_prepared_root(&[entry]).is_err(), "change={change}");
    }
    assert!(validate_prepared_root(&[empty.clone(), empty]).is_err());
}

#[test]
fn application_selection_never_implies_proprietary_package_consent() {
    for presentation in [
        Presentation::Headless,
        Presentation::Wayland,
        Presentation::X11,
    ] {
        for app in [
            Components::default(),
            Components::from(Component::Openclaw),
            Components::from(Component::Opencode),
        ] {
            assert!(validate_component_selection(app, presentation, false).is_ok());
        }
        for consent in [false, true] {
            assert_eq!(
                validate_component_selection(
                    Components::from(Component::ChatgptDesktop),
                    presentation,
                    consent
                )
                .is_ok(),
                presentation == Presentation::X11 && consent
            );
        }
    }
}
