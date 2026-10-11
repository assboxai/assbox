// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{
    Choices, Component, Components, DevicePolicy, Hostname, Platform, Presentation,
};
use assbox_system::commands::Commands;

#[test]
fn rendered_selections_and_consent_parse_together_in_nix() {
    for (ids, presentation, downloads, expected) in [
        ("none", Presentation::Headless, false, "[]"),
        (
            "codex,vim",
            Presentation::Headless,
            false,
            "[\"codex\",\"vim\"]",
        ),
        (
            "chatgpt-desktop",
            Presentation::X11,
            true,
            "[\"chatgpt-desktop\"]",
        ),
        (
            "codex,happier,happier-daemon,zed-remote-host",
            Presentation::Headless,
            true,
            "[\"codex\",\"happier\",\"happier-daemon\",\"zed-remote-host\"]",
        ),
    ] {
        let components: Components = ids.parse().unwrap();
        let choices = Choices {
            instance: assbox_domain::instances::InstanceConfig {
                tailscale: true,
                ..Default::default()
            },
            hostname: Hostname::parse("assbox-fixture").unwrap(),
            timezone: "UTC".into(),
            components,
            presentation,
            platform: Platform::Generic,
            devices: DevicePolicy::default(),
            scale: 1,
            allow_unfree: true,
            allow_mutable_code: downloads,
            autostart: Vec::new(),
            admin_ssh_key: Some("ssh-ed25519 fixture".into()),
            agent_ssh_key: Some("ssh-ed25519 agent-fixture".into()),
            ssh_access: Default::default(),
            additional_packages: Default::default(),
            worker: components.contains(Component::ChatgptDesktop).then(|| {
                assbox_domain::worker::WorkerSpec {
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
                }
            }),
        };
        let original = assbox_config::settings(&choices).unwrap();
        // Exercise the real renderer and managed editor, without a NixOS
        // evaluation, store writes, network or package builds. Identity mkDefault
        // suffices here: Nix itself checks attribute syntax and composition.
        // The dummy store also keeps this runnable inside the package sandbox,
        // where no writable local store or daemon socket is available.
        let switched = assbox_config::selection(
            &original,
            Components::default(),
            Presentation::Headless,
            false,
        )
        .unwrap();
        for (text, selected) in [(&original, expected), (&switched, "[]")] {
            let expression = format!(
                r#"let cfg = ({text}) {{ lib.mkDefault = x: x; }};
                in assert cfg.assbox.network.ssh.admin.enable;
                   assert cfg.assbox.network.ssh.agent.enable;
                   assert cfg.assbox.network.tailscale.enable; {{
                  selected = builtins.filter (id: cfg.assbox.components.${{id}}.enable or false)
                    (builtins.attrNames cfg.assbox.components);
                  downloads = cfg.assbox.components.chatgpt-desktop.allowMutableCode or false;
                }}"#
            );
            let actual = Commands
                .text(
                    "nix-instantiate",
                    &[
                        "--store",
                        "dummy://",
                        "--eval",
                        "--strict",
                        "--json",
                        "--expr",
                        &expression,
                    ],
                )
                .unwrap();
            assert_eq!(
                actual.trim(),
                format!(
                    "{{\"downloads\":{},\"selected\":{selected}}}",
                    components.contains(Component::ChatgptDesktop)
                )
            );
        }
    }
}

#[test]
fn managed_launcher_transitions_satisfy_actual_component_assertions() {
    let ids = "vscode,zed,opencode,opencode-server,openclaw,openclaw-gateway";
    let choices = Choices {
        instance: Default::default(),
        hostname: Hostname::parse("assbox-fixture").unwrap(),
        timezone: "UTC".into(),
        components: ids.parse().unwrap(),
        presentation: Presentation::X11,
        platform: Platform::Generic,
        devices: DevicePolicy::default(),
        scale: 1,
        allow_unfree: true,
        allow_mutable_code: true,
        autostart: ["vscode", "zed", "opencode-attach", "openclaw-dashboard"]
            .map(str::to_owned)
            .to_vec(),
        admin_ssh_key: None,
        agent_ssh_key: None,
        ssh_access: Default::default(),
        additional_packages: Default::default(),
        worker: None,
    };
    let original = assbox_config::settings(&choices).unwrap();
    let lib_path = std::env::var("ASSBOX_NIX_LIB").expect("Nix module library is required");
    let evaluator = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../tests/nix/component-eval.nix"
    );
    for (selected, presentation, launchers) in [
        (ids, Presentation::X11, choices.autostart.as_slice()),
        (
            "vscode,opencode,opencode-server",
            Presentation::Wayland,
            &["vscode".into(), "opencode-attach".into()],
        ),
        (
            "openclaw,openclaw-gateway",
            Presentation::X11,
            &["openclaw-dashboard".into()],
        ),
        (
            "opencode,opencode-server,openclaw,openclaw-gateway",
            Presentation::Headless,
            &[],
        ),
        ("none", Presentation::Headless, &[]),
        ("none", Presentation::Wayland, &[]),
    ] {
        let changed =
            assbox_config::selection(&original, selected.parse().unwrap(), presentation, false)
                .unwrap();
        let expected = launchers
            .iter()
            .map(|id| assbox_config::nix_string(id))
            .collect::<Vec<_>>()
            .join(" ");
        let expression = format!(
            r#"
            let
              cfg = ({changed}) {{ lib.mkDefault = x: x; }};
              evaluate = autostart: import {evaluator} {{
                libPath = {lib_path};
                selection = cfg.assbox.components;
                inherit (cfg.assbox) presentation acceptUnfree;
                inherit autostart;
              }};
            in assert cfg.assbox.session.autostart == [ {expected} ];
               assert (evaluate cfg.assbox.session.autostart).failures == [];
               # An explicit incompatible launcher remains an error, even after
               # the generated defaults have been cleaned up.
               assert cfg.assbox.presentation != "headless"
                 || (evaluate [ "vscode" ]).failures != [];
               true
        "#,
            evaluator = assbox_config::nix_string(evaluator),
            lib_path = assbox_config::nix_string(&lib_path)
        );
        assert_eq!(
            Commands
                .text(
                    "nix-instantiate",
                    &[
                        "--store",
                        "dummy://",
                        "--eval",
                        "--strict",
                        "--json",
                        "--expr",
                        &expression
                    ]
                )
                .unwrap()
                .trim(),
            "true"
        );
    }
}
