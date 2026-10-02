// SPDX-License-Identifier: GPL-3.0-or-later
use crate::nix_string;
use assbox_domain::{Error, Result, instances::InstanceConfig};
const BEGIN: &str = "  # BEGIN ASSBOX INSTANCE (managed)\n";
const END: &str = "  # END ASSBOX INSTANCE\n";
pub fn body(c: &InstanceConfig) -> Result<String> {
    c.validate()?;
    let mut output = format!(
        concat!(
            "  assbox.instance = {{ purpose = lib.mkDefault {}; preset = lib.mkDefault {}; revision = lib.mkDefault {}; exclusions = lib.mkDefault [ {} ]; }};\n",
            "  assbox.network.tailscale.enable = lib.mkDefault {};\n",
            "  assbox.network.execution.egress = lib.mkDefault {};\n",
            "  assbox.computerUse.mode = lib.mkDefault {};\n",
            "  assbox.worker.computerUseMode = lib.mkDefault {};\n",
            "  assbox.kiosk.localExecution = lib.mkDefault {};\n",
            "  assbox.kiosk.webApps = lib.mkDefault [ {} ];\n"
        ),
        nix_string(c.purpose.as_str()),
        nix_string(&c.preset),
        c.revision,
        c.exclusions
            .iter()
            .map(|i| nix_string(i.as_str()))
            .collect::<Vec<_>>()
            .join(" "),
        c.tailscale,
        nix_string(c.egress.as_str()),
        nix_string(if c.execution_in_worker {
            "none"
        } else {
            c.computer_use.as_str()
        }),
        nix_string(if c.execution_in_worker {
            c.computer_use.as_str()
        } else {
            "none"
        }),
        nix_string(if c.protected_code {
            "managed-worker"
        } else {
            "none"
        }),
        c.web_apps
            .iter()
            .map(|s| nix_string(s))
            .collect::<Vec<_>>()
            .join(" ")
    );
    output.push_str(&format!("  assbox.components.hermes-dashboard.publicUrl = lib.mkDefault {};\n  assbox.components.hermes-dashboard.accessProfile = lib.mkDefault {};\n  assbox.components.hermes-dashboard.consentTunnelOnly = lib.mkDefault {};\n",nix_string(&c.hermes_public_url),nix_string(if c.hermes_tunnel_only {"tunnel-only"}else{"authenticated"}),c.hermes_tunnel_only));
    output.push_str(&format!(
        "  assbox.network.tailscale.serveMappings = lib.mkDefault [ {} ];\n",
        if c.dashboard_serve {
            format!(
                "{{ component = \"hermes-dashboard\"; publicUrl = {}; port = 9119; }}",
                nix_string(&c.hermes_public_url)
            )
        } else {
            String::new()
        }
    ));
    Ok(output)
}
pub fn selection(text: &str, c: &InstanceConfig) -> Result<String> {
    if !text.starts_with("# Assbox installer choices.") || !text.ends_with("}\n") {
        return Err(Error::new(
            "custom settings; retain handwritten configuration in local.nix",
        ));
    }
    let mut out = text.to_owned();
    if out.matches(BEGIN).count() != out.matches(END).count() || out.matches(BEGIN).count() > 1 {
        return Err(Error::new("damaged managed instance block"));
    }
    if let Some(start) = out.find(BEGIN) {
        let stop = out
            .find(END)
            .ok_or_else(|| Error::new("missing instance block end"))?;
        if stop < start {
            return Err(Error::new("damaged instance block"));
        }
        out.replace_range(start..stop + END.len(), "");
    }
    if out.contains("assbox.instance")
        || out.contains("assbox.kiosk")
        || out.contains("assbox.computerUse")
    {
        return Err(Error::new(
            "handwritten instance settings outside managed block; edit local.nix",
        ));
    }
    // Remove the legacy generated Tailscale line when replacing the instance block.
    out = out
        .lines()
        .filter(|l| !l.starts_with("  assbox.network.tailscale.enable = lib.mkDefault "))
        .collect::<Vec<_>>()
        .join("\n")
        + "\n";
    out.truncate(out.len() - 2);
    out.push_str(BEGIN);
    out.push_str(&body(c)?);
    out.push_str(END);
    out.push_str("}\n");
    Ok(out)
}
