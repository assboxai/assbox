// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
//! Ordinary Nix source rendering; this is not a second configuration database.
use assbox_domain::*;
use assbox_policy::InstallPlan;
use std::collections::BTreeSet;
pub mod storage_summary;

pub fn nix_string(s: &str) -> String {
    let escaped = s
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace("${", "\\${")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t");
    format!("\"{escaped}\"")
}

pub fn flake(
    source: &assbox_domain::release::ReleaseManifest,
    architecture: Architecture,
) -> String {
    format!(
        r#"# Machine-local configuration. No fork or public hardware profile is needed.
{{
  inputs.assbox.url = {};
  inputs.nixpkgs.follows = "assbox/nixpkgs";
  outputs = {{ assbox, nixpkgs, ... }}:
    let
      machine = nixpkgs.lib.nixosSystem {{
        system = "{system}";
        modules = [
          assbox.nixosModules.default
          ./hardware-configuration.nix
          ./storage.nix
          ./assbox-settings.nix
          ./assbox-packages.nix
          ./local.nix
        ];
      }};
    in {{
      nixosConfigurations.assbox = machine;
      legacyPackages.{system} = machine.pkgs;
    }};
}}
"#,
        nix_string(&source.pinned_url()),
        system = architecture.nix_system()
    )
}

/// Change only the generated literal input line. Arbitrary user Nix is never rewritten.
pub fn retarget_flake(
    text: &str,
    source: &assbox_domain::release::ReleaseManifest,
) -> Result<String> {
    let mut seen = 0;
    let mut output = String::new();
    for line in text.lines() {
        if line.starts_with("  inputs.assbox.url = ") {
            seen += 1;
            let value = line
                .strip_prefix("  inputs.assbox.url = \"")
                .and_then(|s| s.strip_suffix("\";"))
                .ok_or_else(|| {
                    Error::new("custom Assbox input; use ordinary NixOS administration instead")
                })?;
            if !value.starts_with("https://github.com/assboxai/assbox/releases/download/r-")
                || value.contains(['\\', '$', '\"'])
            {
                return Err(Error::new(
                    "Assbox CLI will not rewrite a custom source input",
                ));
            }
            output.push_str(&format!(
                "  inputs.assbox.url = {};\n",
                nix_string(&source.pinned_url())
            ));
        } else {
            output.push_str(line);
            output.push('\n');
        }
    }
    if seen != 1 {
        return Err(Error::new("missing or duplicate managed Assbox input"));
    }
    Ok(output)
}

pub fn settings(c: &Choices) -> Result<String> {
    c.validate()?;
    let ssh = c.admin_ssh_key.as_ref().map_or("  assbox.network.ssh.enable = lib.mkDefault false;\n".to_owned(), |k|
        format!("  assbox.network.ssh.enable = lib.mkDefault true;\n  users.users.admin.openssh.authorizedKeys.keys = [ {} ];\n", nix_string(k)));
    Ok(format!(
        r#"# Assbox installer choices. Override in local.nix using `assbox config edit`.
{{ lib, ... }}:
{{
  assbox.enable = true;
  networking.hostName = lib.mkDefault {};
  time.timeZone = lib.mkDefault {};
  assbox.application = lib.mkDefault {};
  assbox.presentation = lib.mkDefault {};
  assbox.platform = lib.mkDefault {};
  assbox.display.scale = lib.mkDefault {};
  assbox.devices.wifi.enable = lib.mkDefault {};
  assbox.devices.audio.enable = lib.mkDefault {};
  assbox.devices.camera.enable = lib.mkDefault {};
  assbox.devices.bluetooth.enable = lib.mkDefault {};
  assbox.power.suspend.enable = lib.mkDefault {};
  assbox.acceptUnfree = lib.mkDefault {};
{}  # Keep this at the installed state version; it is not an update channel.
  system.stateVersion = "26.05";
}}
"#,
        nix_string(c.hostname.as_str()),
        nix_string(&c.timezone),
        nix_string(c.application.as_str()),
        nix_string(c.presentation.as_str()),
        nix_string(c.platform.as_str()),
        c.scale,
        c.devices.wifi,
        c.devices.audio,
        c.devices.camera,
        c.devices.bluetooth,
        c.devices.suspend,
        c.allow_unfree,
        ssh
    ))
}

pub fn storage(plan: &InstallPlan) -> String {
    let root = plan.root();
    let esp = plan.esp().map_or(String::new(), |p| {
        format!(
            r#"
  fileSystems."/boot/efi" = {{
    device = {};
    fsType = "vfat";
    options = [ "fmask=0077" "dmask=0077" ];
  }};
"#,
            nix_string(&format!("/dev/disk/by-uuid/{}", p.uuid))
        )
    });
    format!(
        r#"# Generated storage binding. Never regenerate this by guessing device names.
{{ ... }}:
{{
  assbox.boot.mode = {};
  assbox.boot.disk = {};
  fileSystems."/" = {{ device = {}; fsType = "ext4"; }};
{}  swapDevices = [ ];
}}
"#,
        nix_string(plan.boot().as_str()),
        nix_string(
            &plan
                .inventory()
                .disk(&root.parent)
                .expect("validated disk")
                .persistent_path
        ),
        nix_string(&format!("/dev/disk/by-uuid/{}", root.uuid)),
        esp
    )
}

const PACKAGES_HEAD: &str = "# Managed by assbox package. Put hand-written Nix in local.nix.\n{ lib, pkgs, ... }:\n{\n  environment.systemPackages = map\n    (name: lib.attrByPath (lib.splitString \".\" name) (throw (\"Unknown nixpkgs package: \" + name)) pkgs)\n    [\n";
const PACKAGES_TAIL: &str = "    ];\n}\n";
pub fn packages(names: &BTreeSet<PackageName>) -> String {
    let mut s = PACKAGES_HEAD.to_owned();
    for name in names {
        s.push_str(&format!("      {}\n", nix_string(name.as_str())));
    }
    s.push_str(PACKAGES_TAIL);
    s
}
/// Parse only the exact managed representation. Never attempt to edit arbitrary Nix.
pub fn read_packages(text: &str) -> Result<BTreeSet<PackageName>> {
    let body = text.strip_prefix(PACKAGES_HEAD).and_then(|s| s.strip_suffix(PACKAGES_TAIL))
        .ok_or_else(|| Error::new("managed package file was edited; move custom Nix to local.nix before using package add/remove"))?;
    let mut out = BTreeSet::new();
    for line in body.lines() {
        let name = line
            .strip_prefix("      \"")
            .and_then(|s| s.strip_suffix('"'))
            .ok_or_else(|| Error::new("unrecognized managed package line"))?;
        if !out.insert(PackageName::parse(name)?) {
            return Err(Error::new("duplicate entry in managed package file"));
        }
    }
    if packages(&out) != text {
        return Err(Error::new(
            "managed package representation is not canonical",
        ));
    }
    Ok(out)
}

pub const LOCAL: &str = r#"# Yours to edit. Assbox never rewrites this file during an update.
{ pkgs, ... }:
{
  # environment.systemPackages = with pkgs; [ htop tmux ];
  # assbox.updates.calendar = "*-*-* 18:00:00";
  # assbox.updates.rebootGraceSeconds = 600;
}
"#;

pub fn selection(
    text: &str,
    application: Application,
    presentation: Presentation,
    accept_unfree: bool,
) -> Result<String> {
    if application == Application::Chatgpt && presentation != Presentation::X11 {
        return Err(Error::new(
            "ChatGPT requires X11; choose an explicitly compatible presentation",
        ));
    }
    let mut app_count = 0;
    let mut presentation_count = 0;
    let mut consent_count = 0;
    let mut result = String::new();
    for line in text.lines() {
        if line.starts_with("  assbox.application = ") {
            app_count += 1;
            result.push_str(&format!(
                "  assbox.application = lib.mkDefault {};\n",
                nix_string(application.as_str())
            ));
        } else if line.starts_with("  assbox.presentation = ") {
            presentation_count += 1;
            result.push_str(&format!(
                "  assbox.presentation = lib.mkDefault {};\n",
                nix_string(presentation.as_str())
            ));
        } else if accept_unfree && line.starts_with("  assbox.acceptUnfree = ") {
            if !matches!(
                line,
                "  assbox.acceptUnfree = lib.mkDefault true;"
                    | "  assbox.acceptUnfree = lib.mkDefault false;"
            ) {
                return Err(Error::new(
                    "custom proprietary-package policy; edit local.nix instead",
                ));
            }
            consent_count += 1;
            result.push_str("  assbox.acceptUnfree = lib.mkDefault true;\n");
        } else {
            result.push_str(line);
            result.push('\n');
        }
    }
    if app_count != 1 || presentation_count != 1 || (accept_unfree && consent_count != 1) {
        return Err(Error::new(
            "installer settings have custom structure; edit local.nix instead",
        ));
    }
    Ok(result)
}

/// A normal NetworkManager keyfile, written only to root-owned local state.
/// Supports personal WPA networks; enterprise/open network setup stays explicit.
pub fn wifi_keyfile(ssid: &str, password: &str) -> Result<String> {
    if ssid.is_empty() || ssid.len() > 32 || ssid.chars().any(char::is_control) {
        return Err(Error::new(
            "SSID must contain 1–32 bytes without control characters",
        ));
    }
    let personal = (8..=63).contains(&password.len())
        && password
            .bytes()
            .all(|b| b.is_ascii() && !b.is_ascii_control());
    let hexadecimal = password.len() == 64 && password.bytes().all(|b| b.is_ascii_hexdigit());
    if !personal && !hexadecimal {
        return Err(Error::new(
            "use an 8–63 character personal Wi-Fi passphrase or 64 hexadecimal digits",
        ));
    }
    let escape = |text: &str| text.replace('\\', "\\\\").replace(' ', "\\s");
    Ok(format!(
        "[connection]\nid=Assbox Wi-Fi\ntype=wifi\nautoconnect=true\n\n[wifi]\nmode=infrastructure\nssid={}\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n",
        escape(ssid),
        escape(password)
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interpolation_is_never_executable_input() {
        assert_eq!(
            nix_string("${builtins.abort \"oops\"}"),
            "\"\\${builtins.abort \\\"oops\\\"}\""
        );
    }
    #[test]
    fn packages_roundtrip_and_do_not_erase_custom_code() {
        let set: BTreeSet<_> = ["htop", "python3Packages.requests"]
            .map(|s| PackageName::parse(s).unwrap())
            .into();
        assert_eq!(read_packages(&packages(&set)).unwrap(), set);
        assert!(
            read_packages("{ pkgs, ... }: { environment.systemPackages = [ pkgs.htop ]; }")
                .is_err()
        );
        assert!(read_packages(&(packages(&set) + "# an edit\n")).is_err());
    }
}
