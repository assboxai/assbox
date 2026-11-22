// SPDX-License-Identifier: GPL-3.0-or-later
use super::SelectionUi;
use assbox_domain::{Component, Components};
use assbox_policy::instances::ResolvedInstance;

pub(super) const CURATED: [Component; 8] = [
    Component::AntigravityCli,
    Component::ClaudeCode,
    Component::Codex,
    Component::CursorAgent,
    Component::Grok,
    Component::Omp,
    Component::Opencode,
    Component::Pi,
];

const HAPPIER_REVIEWED_VERSION: &str = "0.2.14";
const HAPPIER_REVIEW_DATE: &str = "2026-11-22";

fn frontend(agent: Component, selected: Components, workload_ssh: bool) -> String {
    use Component::*;
    let happier = if selected.contains(HappierDaemon) {
        match agent {
            AntigravityCli => Some("Happier CLI binding, experimental remote ACP helper"),
            Grok => Some("Happier binding, experimental upstream resume"),
            Pi => Some("Named upstream Happier adapter"),
            ClaudeCode | Codex | CursorAgent | Opencode => Some("Happier binding"),
            _ => None,
        }
    } else {
        None
    };
    let native = match agent {
        AntigravityCli if selected.contains(AntigravityRemote) => {
            Some("Antigravity Remote selected")
        }
        ClaudeCode if selected.contains(ClaudeCodeRemote) => Some("Claude Remote Control selected"),
        Codex if selected.contains(CodexRelay) => Some("Experimental direct Codex relay selected"),
        CursorAgent if selected.contains(CursorWorker) => Some("Cursor worker selected"),
        Opencode if selected.contains(OpencodeServer) => Some("OpenCode server selected"),
        _ => None,
    };
    let ssh =
        (workload_ssh && matches!(agent, Codex | ClaudeCode)).then_some("Workload SSH requested");
    let routes: Vec<_> = [happier, native, ssh].into_iter().flatten().collect();
    if routes.is_empty() {
        "CLI only".into()
    } else {
        routes.join(" + ")
    }
}

pub(super) fn show(ui: &mut impl SelectionUi, selection: &ResolvedInstance, reconfiguration: bool) {
    let mut agents = CURATED
        .into_iter()
        .filter(|agent| selection.host.contains(*agent) || selection.worker.contains(*agent))
        .peekable();
    if agents.peek().is_none() {
        return;
    }

    let installed_host = if reconfiguration {
        ui.installed_host_components()
    } else {
        Some(Components::default())
    };
    if selection.host.contains(Component::HappierDaemon)
        || selection.worker.contains(Component::HappierDaemon)
    {
        ui.show(&format!(
            "Happier adapter review for {HAPPIER_REVIEWED_VERSION} ({HAPPIER_REVIEW_DATE})"
        ));
    }
    ui.show("Agent | Requested placement | Installation | Authentication | Frontend integration | Assbox qualification");
    for agent in agents {
        let (placement, selected, installation) = if selection.worker.contains(agent) {
            (
                "managed worker",
                selection.worker,
                if reconfiguration {
                    "unobserved"
                } else {
                    "requested"
                },
            )
        } else {
            (
                "host",
                selection.host,
                match installed_host {
                    Some(installed) if installed.contains(agent) => "installed",
                    Some(_) => "requested",
                    None => "unobserved",
                },
            )
        };
        let integration = frontend(agent, selected, selection.workload_ssh);
        ui.show(&format!(
            "{agent} | {placement} | {installation} | unobserved | {integration} | unobserved"
        ));
    }
}
