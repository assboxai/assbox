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
            "chatgpt-desktop,codex",
            Presentation::X11,
            true,
            "[\"chatgpt-desktop\",\"codex\"]",
        ),
        (
            "codex,happy,happy-remote,zed-remote-host",
            Presentation::Headless,
            true,
            "[\"codex\",\"happy\",\"happy-remote\",\"zed-remote-host\"]",
        ),
    ] {
        let components: Components = ids.parse().unwrap();
        let choices = Choices {
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
            happy_backends: if components.contains(Component::HappyRemote) {
                Component::Codex.into()
            } else {
                Components::default()
            },
        };
        let original = assbox_config::settings(&choices).unwrap();
        // Exercise the real renderer and managed editor, without a NixOS
        // evaluation, store writes, network or package builds. Identity mkDefault
        // suffices here: Nix itself checks attribute syntax and composition.
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
                    &["--eval", "--strict", "--json", "--expr", &expression],
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
