// SPDX-License-Identifier: GPL-3.0-or-later
//! Exercise the actual selection flow without inventory, accounts or filesystem writes.
use super::*;
use std::collections::VecDeque;

struct Scripted {
    answers: VecDeque<String>,
    transcript: String,
    gates: VecDeque<&'static str>,
    gate_calls: Vec<(Component, String)>,
}
impl Scripted {
    fn new(answers: &[&str]) -> Self {
        Self {
            answers: answers.iter().map(|s| (*s).to_owned()).collect(),
            transcript: String::new(),
            gates: VecDeque::new(),
            gate_calls: vec![],
        }
    }
}
impl SelectionUi for Scripted {
    fn ask(&mut self, label: &str, default: Option<&str>) -> Result<String> {
        self.transcript.push_str(label);
        if let Some(value) = default {
            self.transcript.push_str(&format!(" [{value}]"));
        }
        self.transcript.push_str(": ");
        let Some(answer) = self.answers.pop_front() else {
            self.transcript.push_str("<EOF>\n");
            return Err(Error::new("input closed; installation cancelled"));
        };
        self.transcript.push_str(if answer.is_empty() {
            "<enter>"
        } else {
            &answer
        });
        self.transcript.push('\n');
        answer_value(&answer, default)
    }
    fn show(&mut self, text: &str) {
        self.transcript.push_str(text);
        self.transcript.push('\n');
    }
    fn native_status(&mut self, app: Component, requested: &str) -> Result<(String, String)> {
        self.gate_calls.push((app, requested.to_owned()));
        Ok((
            self.gates.pop_front().expect("unplanned gate read").into(),
            "fixture installed observations".into(),
        ))
    }
}

fn scenario(
    name: &str,
    answers: &[&str],
    gates: &[&'static str],
    installed: bool,
    expected_preset: Option<&str>,
    combined: &mut String,
) {
    let mut ui = Scripted::new(answers);
    ui.gates = gates.iter().copied().collect();
    let result = selection_with_ui(&mut ui, installed);
    combined.push_str(&format!("=== {name} ===\n"));
    combined.push_str(&ui.transcript);
    match (result, expected_preset) {
        (Ok(selection), Some(expected)) => {
            assert_eq!(selection.config.preset, expected);
            assert_eq!(
                selection.config.execution_in_worker,
                selection.worker != Components::default()
            );
            // Gate observations never silently choose a web or worker alternative.
            if !gates.is_empty() && expected == "kiosk-native" {
                assert!(!selection.config.protected_code);
                assert_eq!(selection.worker, Components::default());
                assert!(selection.config.web_apps.is_empty());
            }
            if expected == "kiosk-web" {
                assert!(
                    answers.contains(&"web"),
                    "web fallback requires an explicit choice"
                );
            }
            combined.push_str(&format!(
                "RESULT: {} | host {} | worker {} | exclusions {} | workload SSH {}\n\n",
                selection.config.preset,
                selection.host,
                selection.worker,
                selection.config.exclusions,
                selection.workload_ssh
            ));
        }
        (Err(error), None) => combined.push_str(&format!("CANCELLED/REFUSED: {error}\n\n")),
        (other, expected) => panic!(
            "{name}: unexpected {other:?} for {expected:?}\n{}",
            ui.transcript
        ),
    }
    assert!(
        ui.answers.is_empty(),
        "unused answers in {name}: {:?}",
        ui.answers
    );
    assert!(ui.gates.is_empty(), "unused gate observations in {name}");
    assert_eq!(ui.gate_calls.len(), gates.len());
}

#[test]
fn purpose_flow_matches_reviewed_transcripts_without_side_effects() {
    let mut transcript = String::new();
    let routes: &[(&str, &[&str])] = &[
        (
            "assistant-openclaw",
            &["assistant", "openclaw", "", "", "", "", "", ""],
        ),
        (
            "assistant-hermes",
            &["assistant", "hermes", "", "", "", "", "", ""],
        ),
        (
            "coder-happier",
            &["coder", "happier", "", "", "", "", "", ""],
        ),
        (
            "coder-codex-ssh",
            &["coder", "codex", "", "", "", "", "", "", ""],
        ),
        (
            "coder-claude-native",
            &["coder", "claude", "relay", "", "", "", "", "", "", ""],
        ),
        (
            "coder-claude-ssh",
            &["coder", "claude", "ssh", "", "", "", "", "", "", ""],
        ),
        (
            "coder-cursor",
            &["coder", "more", "cursor", "", "", "", "", "", "", ""],
        ),
        (
            "coder-antigravity",
            &["coder", "more", "antigravity", "", "", "", "", "", "", ""],
        ),
        (
            "coder-opencode",
            &["coder", "more", "opencode", "", "", "", "", "", "", ""],
        ),
        ("coder-ssh", &["coder", "ssh", "", "", "", "", "", "", ""]),
        (
            "kiosk-native",
            &["kiosk", "native", "", "", "", "", "", "", "", ""],
        ),
        ("kiosk-web", &["kiosk", "web", "", "", "", "", "", "", ""]),
        ("custom", &["custom", "codex", "", "", "", "", "", "", ""]),
    ];
    for (id, answers) in routes {
        scenario(id, answers, &[], false, Some(id), &mut transcript);
    }
    scenario(
        "coder-desktop-protected",
        &["coder", "desktop", "", "", "", "", "", "", "", ""],
        &[],
        false,
        Some("kiosk-native"),
        &mut transcript,
    );
    scenario(
        "custom-worker",
        &["custom", "chromium,codex", "n", "y", "", "", "", "", ""],
        &[],
        false,
        Some("custom"),
        &mut transcript,
    );
    scenario(
        "nested-back-and-selection-back",
        &[
            "coder",
            "claude",
            "back",
            "coder",
            "more",
            "back",
            "assistant",
            "hermes",
            "back",
            "coder",
            "codex",
            "",
            "n",
            "",
            "",
            "",
            "",
            "",
        ],
        &[],
        false,
        Some("coder-codex-ssh"),
        &mut transcript,
    );
    scenario(
        "independent-agent-deselection",
        &[
            "assistant",
            "hermes",
            "codex,hermes,hermes-gateway",
            "",
            "",
            "",
            "",
            "",
        ],
        &[],
        false,
        Some("assistant-hermes"),
        &mut transcript,
    );
    scenario(
        "dependency-consent-refusal",
        &["custom", "cursor-worker", "n", "n"],
        &[],
        false,
        None,
        &mut transcript,
    );
    scenario(
        "cancel-before-selection",
        &[],
        &[],
        false,
        None,
        &mut transcript,
    );
    scenario(
        "cancel-before-confirmation",
        &["coder", "codex", "", "n", "", "", "", ""],
        &[],
        false,
        None,
        &mut transcript,
    );
    for state in ["verified", "pending", "unavailable", "ineffective", "stale"] {
        scenario(
            &format!("native-{state}"),
            &[
                "kiosk",
                "native",
                "chatgpt-desktop",
                "n",
                "",
                "",
                "",
                "",
                "y",
                "y",
            ],
            &[state],
            true,
            Some("kiosk-native"),
            &mut transcript,
        );
    }
    scenario(
        "mixed-native-outcomes",
        &["kiosk", "native", "", "n", "", "", "", "", "y", "y"],
        &["verified", "ineffective"],
        true,
        Some("kiosk-native"),
        &mut transcript,
    );
    scenario(
        "declined-native-staging-and-explicit-web",
        &[
            "kiosk", "native", "", "n", "", "", "", "", "n", "kiosk", "web", "", "", "", "", "",
            "", "",
        ],
        &["unavailable", "stale"],
        true,
        Some("kiosk-web"),
        &mut transcript,
    );
    scenario(
        "native-back-and-deselection",
        &[
            "kiosk",
            "native",
            "",
            "n",
            "",
            "",
            "",
            "",
            "back",
            "kiosk",
            "native",
            "claude-desktop",
            "n",
            "",
            "",
            "",
            "",
            "stage",
            "y",
        ],
        &["unavailable", "ineffective", "verified"],
        true,
        Some("kiosk-native"),
        &mut transcript,
    );
    scenario(
        "protected-worker-does-not-bypass-unavailable-native-policy",
        &["coder", "desktop", "", "y", "", "", "", "", "back"],
        &["unavailable", "unavailable"],
        true,
        None,
        &mut transcript,
    );
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/selection_transcripts.txt");
    if std::env::var_os("ASSBOX_UPDATE_SELECTION_GOLDENS").is_some() {
        std::fs::write(&path, &transcript).unwrap();
    }
    assert_eq!(
        std::fs::read_to_string(path).unwrap(),
        transcript,
        "review the selection changes; regenerate with ASSBOX_UPDATE_SELECTION_GOLDENS=1 only when intended"
    );
}
