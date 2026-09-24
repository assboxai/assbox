// SPDX-License-Identifier: GPL-3.0-or-later
//! Render a bounded CLI-owned block in the existing installer settings file.
use crate::nix_string;
use assbox_domain::{Components, Error, Result, worker::WorkerSpec};
const BEGIN: &str = "  # BEGIN ASSBOX WORKER (managed)\n";
const END: &str = "  # END ASSBOX WORKER\n";
const DISABLED: &str = "  assbox.worker.enable = lib.mkDefault false;\n";

fn strings(items: impl IntoIterator<Item = String>) -> String {
    items
        .into_iter()
        .map(|s| nix_string(&s))
        .collect::<Vec<_>>()
        .join(" ")
}
fn body(spec: &WorkerSpec) -> String {
    format!(
        concat!(
            "  assbox.worker = {{\n",
            "    enable = lib.mkDefault true;\n",
            "    components = lib.mkDefault [ {} ];\n",
            "    allowMutableCodeFor = lib.mkDefault [ {} ];\n",
            "    memoryMiB = lib.mkDefault {};\n",
            "    vcpus = lib.mkDefault {};\n",
            "    stateGiB = lib.mkDefault {};\n",
            "    uplinkInterfaces = lib.mkDefault [ {} ];\n",
            "    egress = lib.mkDefault {};\n",
            "    nameservers = lib.mkDefault [ {} ];\n",
            "    allowGuestSudo = lib.mkDefault {};\n",
            "  }};\n"
        ),
        strings(spec.components.iter().map(|c| c.to_string())),
        strings(spec.mutable_components.iter().map(|c| c.to_string())),
        spec.memory_mib,
        spec.vcpus,
        spec.state_gib,
        strings(spec.uplinks.clone()),
        nix_string(if spec.offline { "offline" } else { "internet" }),
        if spec.offline {
            ""
        } else {
            "\"1.1.1.1\" \"9.9.9.9\""
        },
        spec.guest_sudo
    )
}
fn invalid() -> Error {
    Error::new(
        "custom worker settings; put hand-written Nix in local.nix instead of the CLI-managed block",
    )
}
fn parse_list(value: &str) -> Result<Vec<String>> {
    let list = value
        .strip_prefix("[ ")
        .and_then(|s| s.strip_suffix(" ]"))
        .ok_or_else(invalid)?;
    list.split_whitespace()
        .map(|v| {
            v.strip_prefix('"')
                .and_then(|s| s.strip_suffix('"'))
                .map(str::to_owned)
                .ok_or_else(invalid)
        })
        .collect()
}
fn validate_body(text: &str) -> Result<()> {
    if text == DISABLED {
        return Ok(());
    }
    let field = |key: &str| -> Result<String> {
        let prefix = format!("    {key} = lib.mkDefault ");
        let values: Vec<_> = text
            .lines()
            .filter_map(|l| l.strip_prefix(&prefix).and_then(|s| s.strip_suffix(';')))
            .collect();
        if values.len() != 1 {
            return Err(invalid());
        }
        Ok(values[0].to_owned())
    };
    let number = |key| field(key)?.parse::<u32>().map_err(|_| invalid());
    let boolean = |key| field(key)?.parse::<bool>().map_err(|_| invalid());
    let parse_components =
        |key| -> Result<Components> { parse_list(&field(key)?)?.join(",").parse() };
    let spec = WorkerSpec {
        components: parse_components("components")?,
        mutable_components: parse_components("allowMutableCodeFor")?,
        memory_mib: number("memoryMiB")?,
        vcpus: number("vcpus")?,
        state_gib: number("stateGiB")?,
        uplinks: parse_list(&field("uplinkInterfaces")?)?,
        offline: field("egress")? == "\"offline\"",
        guest_sudo: boolean("allowGuestSudo")?,
    };
    spec.validate(true)?;
    if body(&spec) != text {
        return Err(invalid());
    }
    Ok(())
}

pub fn selection(text: &str, spec: Option<&WorkerSpec>) -> Result<String> {
    if let Some(spec) = spec {
        spec.validate(true)?;
    }
    if !text.starts_with("# Assbox installer choices.") || !text.ends_with("}\n") {
        return Err(invalid());
    }
    let mut outer = text.to_owned();
    if text.matches(BEGIN).count() != text.matches(END).count() || text.matches(BEGIN).count() > 1 {
        return Err(invalid());
    }
    if let Some(start) = text.find(BEGIN) {
        let stop = text.find(END).ok_or_else(invalid)?;
        if stop < start {
            return Err(invalid());
        }
        validate_body(&text[start + BEGIN.len()..stop])?;
        outer.replace_range(start..stop + END.len(), "");
    }
    if outer.contains("assbox.worker") {
        return Err(invalid());
    }
    outer.truncate(outer.len() - 2);
    outer.push_str(BEGIN);
    outer.push_str(&spec.map(body).unwrap_or_else(|| DISABLED.to_owned()));
    outer.push_str(END);
    outer.push_str("}\n");
    Ok(outer)
}

/// Fixed JSON selector used only for post-evaluation comparison, not execution.
pub const EVALUATED_SELECTION: &str = "c: { inherit (c.worker) enable components allowMutableCodeFor memoryMiB vcpus stateGiB uplinkInterfaces egress nameservers allowGuestSudo; }";

pub fn expected_fields(spec: Option<&WorkerSpec>) -> Vec<String> {
    let Some(s) = spec else {
        return vec!["false".to_owned()];
    };
    vec![
        "true".to_owned(),
        s.components.to_string(),
        s.mutable_components.to_string(),
        s.memory_mib.to_string(),
        s.vcpus.to_string(),
        s.state_gib.to_string(),
        s.uplinks.join(","),
        if s.offline {
            "offline".to_owned()
        } else {
            "internet".to_owned()
        },
        s.guest_sudo.to_string(),
        if s.offline {
            String::new()
        } else {
            "1.1.1.1,9.9.9.9".to_owned()
        },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    const BASE: &str = "# Assbox installer choices.\n{ lib, ... }: {\n  # kept\n}\n";
    fn spec() -> WorkerSpec {
        WorkerSpec {
            components: "vim".parse().unwrap(),
            mutable_components: Components::default(),
            memory_mib: 3072,
            vcpus: 2,
            state_gib: 32,
            uplinks: vec![],
            offline: true,
            guest_sudo: false,
        }
    }
    #[test]
    fn managed_block_roundtrips_without_rewriting_other_settings() {
        let s = spec();
        let text = selection(BASE, Some(&s)).unwrap();
        assert_eq!(selection(&text, Some(&s)).unwrap(), text);
        assert!(text.contains("  # kept\n"));
        let disabled = selection(&text, None).unwrap();
        assert!(disabled.contains(DISABLED));
        assert!(!disabled.contains("memoryMiB"));
        assert_eq!(selection(&disabled, None).unwrap(), disabled);
        assert_eq!(selection(&disabled, Some(&s)).unwrap(), text);
        assert_eq!(expected_fields(None), ["false"]);
        assert_eq!(expected_fields(Some(&s)).last().unwrap(), "");
    }
    #[test]
    fn internet_mutable_and_sudo_options_roundtrip() {
        let mut s = spec();
        s.components = "vscode-remote-host".parse().unwrap();
        s.mutable_components = s.components;
        s.offline = false;
        s.uplinks = vec!["eth0".into(), "wlan0".into()];
        s.guest_sudo = true;
        let text = selection(BASE, Some(&s)).unwrap();
        assert_eq!(selection(&text, Some(&s)).unwrap(), text);
        assert!(text.contains("nameservers = lib.mkDefault [ \"1.1.1.1\" \"9.9.9.9\" ];"));
        assert_eq!(expected_fields(Some(&s)).last().unwrap(), "1.1.1.1,9.9.9.9");
        assert!(text.contains("allowGuestSudo = lib.mkDefault true"));
    }
    #[test]
    fn malformed_and_handwritten_settings_refuse_without_guessing() {
        let s = spec();
        let good = selection(BASE, Some(&s)).unwrap();
        for text in [
            String::new(),
            BASE.trim_end().to_owned(),
            BASE.replace("# Assbox installer choices.", "# custom"),
            BASE.replace("  # kept", "  assbox.worker.enable = true;"),
            good.replace(END, ""),
            good.replace(BEGIN, &format!("{BEGIN}{BEGIN}")),
            good.replace("3072", "-1"),
            good.replace("lib.mkDefault true;", "lib.mkDefault 1;"),
            good.replace("\"vim\"", "vim"),
            good.replace("\"offline\"", "\"mystery\""),
            good.replace("[  ]", "oops"),
            good.replace("    memoryMiB = lib.mkDefault 3072;\n", ""),
            good.replace(
                "    memoryMiB = lib.mkDefault 3072;",
                "    memoryMiB = lib.mkDefault 3072;\n    memoryMiB = lib.mkDefault 3072;",
            ),
            good.replace(
                "    nameservers = lib.mkDefault [  ];",
                "    nameservers = lib.mkDefault [ \"127.0.0.1\" ];",
            ),
            format!("{BASE}{END}{BEGIN}}}\n"),
        ] {
            assert!(selection(&text, Some(&s)).is_err(), "{text}");
        }
        let mut bad = s;
        bad.components = Components::default();
        assert!(selection(BASE, Some(&bad)).is_err());
    }
}
