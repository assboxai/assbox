// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_config::*;
use assbox_domain::*;
use std::collections::BTreeSet;
fn choices() -> Choices {
    Choices {
        instance: Default::default(),
        hostname: Hostname::parse("assbox-local").unwrap(),
        timezone: "UTC".into(),
        components: Components::default(),
        presentation: Presentation::Headless,
        platform: Platform::Generic,
        devices: DevicePolicy::default(),
        scale: 1,
        allow_unfree: false,
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
fn standalone_workload_ssh_and_manual_browser_do_not_require_a_nested_worker() {
    let mut c = choices();
    c.components = "chromium,codex".parse().unwrap();
    c.agent_ssh_key = Some("ssh-ed25519 workload-fixture".into());
    c.ssh_access = access::SshAccess {
        exposure: access::SshExposure::Lan,
        interfaces: vec!["enp0s5".into()],
        source_cidrs: vec!["192.168.64.1/32".into()],
    };
    c.additional_packages
        .insert(PackageName::parse("htop").unwrap());
    for presentation in [Presentation::X11, Presentation::Wayland] {
        c.presentation = presentation;
        c.autostart = vec!["chromium".into()];
        let text = settings(&c).unwrap();
        assert!(text.contains("assbox.network.ssh.agent.enable = lib.mkDefault true;"));
        assert!(text.contains("assbox.network.ssh.admin.enable = lib.mkDefault false;"));
        assert!(text.contains("lanInterfaces = lib.mkDefault [ \"enp0s5\" ];"));
        assert!(text.contains("lanSourceCidrs = lib.mkDefault [ \"192.168.64.1/32\" ];"));
        assert!(text.contains("tailscale.enable = lib.mkDefault false"));
        assert!(!text.contains("assbox.worker ="));
        assert!(!text.contains("vscode-remote-host"));
        let guide = connection_guide(&c);
        assert!(guide.contains("User agent\n"));
        assert!(guide.contains("ForwardAgent no\n"));
        assert!(guide.contains("compare its fingerprint"));
        assert!(guide.contains("command -v codex"));
        assert_eq!(
            read_packages(&packages(&c.additional_packages)).unwrap(),
            c.additional_packages
        );
    }
    c.presentation = Presentation::Headless;
    assert!(settings(&c).is_err());
    c.components = "codex".parse().unwrap();
    c.autostart.clear();
    assert!(settings(&c).is_ok());
    c.ssh_access = Default::default();
    c.instance.tailscale = true;
    let text = settings(&c).unwrap();
    assert!(text.contains("tailscale.enable = lib.mkDefault true;"));
    assert!(connection_guide(&c).contains("sudo tailscale up"));
    c.components = "chatgpt-desktop".parse().unwrap();
    c.presentation = Presentation::X11;
    c.allow_unfree = true;
    assert!(settings(&c).is_err());
}
fn release() -> assbox_domain::release::ReleaseManifest {
    let fields = [
        "3",
        "3",
        "stable",
        "r-42",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "0.1.0",
        "100",
        "604900",
        &"b".repeat(64),
        "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        &"c".repeat(64),
        "aarch64-linux,x86_64-linux",
        "r-1",
        &"d".repeat(64),
    ]
    .map(str::to_owned);
    assbox_domain::release::ReleaseManifest::from_fields(&fields).unwrap()
}
// All config rendering tests use this schema-3 fixture, including the local-flake
// regression. It is test-only data, not a release/cryptographic authorization.
#[test]
fn local_flake_imports_machine_state_not_upstream_hosts() {
    let text = flake(&release(), Architecture::X86_64);
    assert!(text.contains("/releases/download/r-42/assbox-source.tar.gz?narHash="));
    assert!(text.contains("./hardware-configuration.nix"));
    assert!(text.contains("./local.nix"));
    assert!(!text.contains("hosts/"));
}
#[test]
fn rendering_cannot_change_the_upstream_repository_or_publish_hardware() {
    let source = release();
    let text = flake(&source, Architecture::X86_64);
    for local in [
        "hardware-configuration.nix",
        "storage.nix",
        "local.nix",
        "assbox-packages.nix",
    ] {
        assert!(text.contains(local));
    }
    assert!(text.contains("assbox/nixpkgs"));
    assert!(text.contains("nixosConfigurations.assbox"));
    assert!(!text.contains("git push"));
    assert!(!text.contains("hosts/"));
    for bad in [
        "",
        "github:a/b",
        "github:a/b/c/d",
        "github:a/b/--bad?",
        "github:/b/c",
        "https://example.com/a",
    ] {
        assert!(assbox_domain::release::ReleaseTag::parse(bad).is_err());
    }
}
#[test]
fn safe_package_names_roundtrip_across_all_subsets() {
    let names = ["htop", "tmux", "python3Packages.requests", "git-lfs"];
    for bits in 0..16 {
        let set: BTreeSet<_> = names
            .iter()
            .enumerate()
            .filter(|(i, _)| bits & (1 << i) != 0)
            .map(|(_, s)| PackageName::parse(s).unwrap())
            .collect();
        assert_eq!(read_packages(&packages(&set)).unwrap(), set);
    }
}
#[test]
fn managed_package_parser_never_rewrites_an_expression() {
    let mut names = BTreeSet::new();
    names.insert(PackageName::parse("htop").unwrap());
    let text = packages(&names);
    for bad in [
        text.replace("htop", "${builtins.abort}"),
        text.replace("      \"htop\"\n", "      \"htop\"\n      \"htop\"\n"),
        text.replace("      \"htop\"", "    pkgs.htop"),
        format!("{text}\n"),
    ] {
        assert!(read_packages(&bad).is_err());
    }
}
#[test]
fn application_selection_has_no_implicit_presentation_change() {
    let original = settings(&choices()).unwrap();
    assert!(
        selection(
            &original,
            Components::from(Component::ChatgptDesktop),
            Presentation::Wayland,
            false
        )
        .is_err()
    );
    let next = selection(
        &original,
        Components::from(Component::Openclaw),
        Presentation::Wayland,
        false,
    )
    .unwrap();
    assert!(next.contains("assbox.components = { openclaw.enable = lib.mkDefault true; }"));
    assert!(next.contains("assbox.presentation = lib.mkDefault \"wayland\""));
    assert!(next.contains("networking.hostName = lib.mkDefault \"assbox-local\""));
    assert!(
        selection(
            "{ ... }: {}",
            Components::default(),
            Presentation::Headless,
            false
        )
        .is_err()
    );
    assert!(
        selection(
            &(original.clone() + "  assbox.components = {  };\n"),
            Components::default(),
            Presentation::Headless,
            false
        )
        .is_err()
    );
}

#[test]
fn selection_never_rewrites_custom_or_ambiguous_autostart() {
    let original = settings(&choices()).unwrap();
    let line = "  assbox.session.autostart = lib.mkDefault [  ];";
    for replacement in [
        "  assbox.session.autostart = myLaunchers;",
        "  assbox.session.autostart = lib.mkDefault [ \"${custom}\" ];",
        "  assbox.session.autostart = lib.mkDefault [ \"vscode\" \"vscode\" ];",
        "  assbox.session.autostart = lib.mkDefault [ \"emacs\" ];",
        "  assbox.session.autostart = lib.mkDefault [  \"vscode\" ];",
    ] {
        assert!(
            selection(
                &original.replace(line, replacement),
                Components::default(),
                Presentation::Headless,
                false
            )
            .is_err()
        );
    }
    assert!(
        selection(
            &(original.clone() + line),
            Components::default(),
            Presentation::Headless,
            false
        )
        .is_err()
    );
    // Older installer settings without a launcher line keep the module default.
    assert!(
        selection(
            &original.replace(line, ""),
            Components::default(),
            Presentation::Headless,
            false
        )
        .is_ok()
    );
}
#[test]
fn source_text_escape_is_literal_for_sensitive_metacharacters() {
    assert_eq!(nix_string("a\nb\tc\rd\\e\""), "\"a\\nb\\tc\\rd\\\\e\\\"\"");
    assert!(nix_string("${x}").contains("\\${x}"));
    assert!(LOCAL.contains("local") || LOCAL.contains("Yours to edit"));
}

#[test]
fn wifi_credentials_are_plain_local_keyfiles_not_nix_source() {
    let keyfile = wifi_keyfile("my network", "pass word123").unwrap();
    assert!(keyfile.contains("ssid=my\\snetwork"));
    assert!(keyfile.contains("psk=pass\\sword123"));
    assert!(!keyfile.contains("/nix/store"));
    let ambiguous = wifi_keyfile("65;66;", "pass;word123").unwrap();
    assert!(ambiguous.contains("ssid=65\\\\;66\\\\;\n"));
    assert!(ambiguous.contains("psk=pass;word123\n"));
    for (ssid, password) in [
        ("", "password123"),
        ("a\nb", "password123"),
        ("network", "short"),
        ("network", "password\n123"),
    ] {
        assert!(wifi_keyfile(ssid, password).is_err());
    }
    assert!(wifi_keyfile("network", &"a".repeat(64)).is_ok());
    assert!(wifi_keyfile("network", &"g".repeat(64)).is_err());
}

#[test]
fn local_flake_system_and_package_search_follow_observed_architecture() {
    let source = release();
    for architecture in [Architecture::X86_64, Architecture::Aarch64] {
        let text = flake(&source, architecture);
        assert!(text.contains(&format!("system = \"{}\"", architecture.nix_system())));
        assert!(text.contains(&format!("legacyPackages.{}", architecture.nix_system())));
        assert!(text.contains("assbox/nixpkgs"));
        assert!(!text.contains("hosts/"));
    }
}

#[test]
fn selection_changes_consent_only_after_an_explicit_grant() {
    let original = settings(&choices()).unwrap();
    let no_grant = selection(
        &original,
        Components::from(Component::ChatgptDesktop),
        Presentation::X11,
        false,
    )
    .unwrap();
    assert!(no_grant.contains("assbox.acceptUnfree = lib.mkDefault false;"));
    let granted = selection(
        &original,
        Components::from(Component::ChatgptDesktop),
        Presentation::X11,
        true,
    )
    .unwrap();
    assert!(granted.contains("assbox.acceptUnfree = lib.mkDefault true;"));
    assert!(!granted.contains("assbox.acceptUnfree = lib.mkDefault false;"));
    let switched = selection(
        &granted,
        Components::default(),
        Presentation::Headless,
        false,
    )
    .unwrap();
    assert!(switched.contains("assbox.acceptUnfree = lib.mkDefault true;"));
    for bad in [
        original.replace("  assbox.acceptUnfree = lib.mkDefault false;\n", ""),
        original.replace(
            "  assbox.acceptUnfree = lib.mkDefault false;",
            "  assbox.acceptUnfree = customPolicy;",
        ),
        original.clone() + "  assbox.acceptUnfree = lib.mkDefault false;\n",
    ] {
        assert!(
            selection(
                &bad,
                Components::from(Component::ChatgptDesktop),
                Presentation::X11,
                true
            )
            .is_err()
        );
    }
}

#[test]
fn human_disk_identification_escapes_terminal_controls_and_shows_unknowns() {
    use assbox_config::storage_summary::{disk_summary, terminal_text};
    let disk = Disk {
        path: "/dev/sda".into(),
        major_minor: "8:0".into(),
        bytes: 64 * 1024 * 1024 * 1024,
        serial: "serial-1".into(),
        model: "Example SSD".into(),
        persistent_path: "/dev/disk/by-id/test-ssd".into(),
        table: Table::Gpt,
        read_only: false,
        hybrid_mbr: false,
        mounts: vec![],
        has_holders: false,
    };
    let summary = disk_summary("TARGET", &disk);
    for value in [
        "Example SSD",
        "serial-1",
        "/dev/disk/by-id/test-ssd",
        "68719476736 bytes",
        "8:0",
    ] {
        assert!(summary.contains(value));
    }
    assert_eq!(terminal_text(""), "(unavailable)");
    let untrusted = terminal_text("disk\n\x1b[2J\u{202e}evil");
    assert!(!untrusted.contains(['\n', '\x1b', '\u{202e}']));
    assert!(untrusted.contains("evil"));
}

#[test]
fn confirmation_names_the_whole_disk_and_repeats_root_esp_and_backup() {
    use assbox_config::storage_summary::{confirmation_phrase, plan_storage_summary};
    let disk = |name: &str, id: &str| Disk {
        path: format!("/dev/{name}"),
        major_minor: id.into(),
        bytes: 64 * 1024 * 1024 * 1024,
        serial: format!("serial-{name}"),
        model: "Test model".into(),
        persistent_path: format!("/dev/disk/by-id/test-{name}"),
        table: Table::Gpt,
        read_only: false,
        hybrid_mbr: false,
        mounts: vec![],
        has_holders: false,
    };
    let partition = |name: &str, parent: &str, fs: FileSystem, kind: &str| Partition {
        path: format!("/dev/{name}"),
        parent: format!("/dev/{parent}"),
        major_minor: format!("id-{name}"),
        bytes: 1024 * 1024 * 1024,
        start_bytes: 1024 * 1024,
        fs,
        uuid: format!("uuid-{name}"),
        partuuid: format!("partuuid-{name}"),
        part_type: kind.into(),
        mounts: vec![],
        read_only: false,
        has_holders: false,
    };
    let inventory = Inventory {
        architecture: Architecture::Aarch64,
        hardware: Hardware::default(),
        firmware: Firmware::Uefi,
        disks: vec![disk("sda", "8:0"), disk("sdb", "8:16")],
        partitions: vec![
            partition("sda1", "sda", FileSystem::Ext4, "83"),
            partition("sda2", "sda", FileSystem::Fat, assbox_policy::ESP_TYPE),
            partition("sdb1", "sdb", FileSystem::Ext4, "83"),
        ],
        live_media: LiveMedia::Optical {
            device: "/dev/sr0".into(),
            major_minor: "11:0".into(),
            bytes: 4096,
            filesystem: "iso9660".into(),
            uuid: "iso".into(),
            read_only: true,
            mounted_read_only: true,
        },
    };
    let request = InstallRequest {
        root: "/dev/sda1".into(),
        esp: Some("/dev/sda2".into()),
        backup: "/dev/sdb1".into(),
        choices: choices(),
    };
    let plan = assbox_policy::plan_install(inventory.clone(), request.clone()).unwrap();
    assert_eq!(
        confirmation_phrase(&plan).unwrap(),
        "INSTALL DISK /dev/disk/by-id/test-sda AS assbox-local"
    );
    let summary = plan_storage_summary(&plan).unwrap();
    for identity in [
        "serial-sda",
        "serial-sdb",
        "/dev/sda1",
        "/dev/sda2",
        "/dev/sdb1",
        "/dev/sr0",
    ] {
        assert!(summary.contains(identity));
    }
    let mut unnamed = inventory;
    unnamed.disks[0].persistent_path.clear();
    let plan = assbox_policy::plan_install(unnamed, request).unwrap();
    let phrase = confirmation_phrase(&plan).unwrap();
    assert!(phrase.contains("DISK /dev/sda [8:0; 68719476736 bytes]"));
    assert!(!phrase.contains("/dev/sda1"));
}

#[test]
fn retargeting_preserves_other_local_text_and_refuses_custom_or_duplicate_inputs() {
    let mut candidate = release();
    let original = flake(&candidate, Architecture::Aarch64);
    candidate.tag = assbox_domain::release::ReleaseTag::parse("r-43").unwrap();
    let updated = retarget_flake(&original, &candidate).unwrap();
    assert!(updated.contains("/r-43/assbox-source.tar.gz"));
    assert!(updated.contains("./local.nix"));
    for custom in [
        original.replace(
            "https://github.com/assboxai/assbox/releases/download/r-42/assbox-source.tar.gz",
            "github:other/custom/master",
        ),
        original.clone() + "  inputs.assbox.url = \"github:other/custom/master\";\n",
        String::new(),
    ] {
        assert!(retarget_flake(&custom, &candidate).is_err());
    }
}
#[test]
fn console_only_does_not_enable_ssh_but_an_explicit_key_does() {
    let mut c = choices();
    assert!(
        settings(&c)
            .unwrap()
            .contains("assbox.network.ssh.admin.enable = lib.mkDefault false;")
    );
    c.admin_ssh_key =
        Some("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKTestFixtureOnlyNotARealKeyExample test".into());
    assert!(
        settings(&c)
            .unwrap()
            .contains("assbox.network.ssh.admin.enable = lib.mkDefault true;")
    );
}
