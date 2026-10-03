// SPDX-License-Identifier: GPL-3.0-or-later
//! Compare the compiled catalog API with its independently parsed source of truth.
//! Source regeneration alone cannot establish the runtime selection contract.
use assbox_domain::{Component, Components, Presentation};
use std::{collections::BTreeSet, path::Path, process::Command};

#[test]
fn compiled_catalog_and_selection_match_reviewed_metadata() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../catalog/components.json");
    // Python is already a native test input. Keep JSON parsing out of the
    // production domain crate, and do not invoke the Rust source generator here.
    let output = Command::new("python3")
        .args([
            "-c",
            r#"
import json, sys
for row in json.load(open(sys.argv[1])):
    fields = [row['id'], ','.join(row['dependencies']), ','.join(row['presentations']),
              str(row['unfree']).lower(), str(row['mutableCode']).lower(),
              row['blocked'], row['command'], row['codeNotes'],
              str(row['controllerAllowed']).lower(), str(row['workerAllowed']).lower(),
              str(row['requiresWorker']).lower()]
    for field in fields:
        assert '\0' not in field
        sys.stdout.write(field + '\0')
"#,
        ])
        .arg(path)
        .output()
        .expect("Python is required for the native catalog contract");
    assert!(output.status.success(), "{:?}", output.stderr);
    let text = String::from_utf8(output.stdout).unwrap();
    let fields: Vec<_> = text.split_terminator('\0').collect();
    assert_eq!(fields.len(), Component::ALL.len() * 11);
    let rows: Vec<_> = fields.chunks_exact(11).collect();
    let names = |items: &[Component]| {
        items
            .iter()
            .map(|item| item.as_str())
            .collect::<Vec<_>>()
            .join(",")
    };
    assert_eq!(
        Component::ALL
            .iter()
            .map(|item| item.as_str())
            .collect::<Vec<_>>(),
        rows.iter().map(|row| row[0]).collect::<Vec<_>>()
    );
    for row in &rows {
        let component: Component = row[0].parse().unwrap();
        assert_eq!(component.to_string(), row[0]);
        assert_eq!(
            names(component.dependencies()),
            row[1],
            "{} dependencies",
            row[0]
        );
        assert_eq!(
            component
                .presentations()
                .iter()
                .map(|mode| mode.as_str())
                .collect::<Vec<_>>()
                .join(","),
            row[2],
            "{} presentations",
            row[0]
        );
        assert_eq!(component.unfree().to_string(), row[3], "{} consent", row[0]);
        assert_eq!(
            component.mutable_code().to_string(),
            row[4],
            "{} mutable code",
            row[0]
        );
        assert_eq!(component.blocked(), row[5], "{} blocker", row[0]);
        assert_eq!(component.command(), row[6], "{} command", row[0]);
        assert_eq!(component.code_notes(), row[7], "{} disclosure", row[0]);

        assert_eq!(component.controller_allowed().to_string(), row[8]);
        assert_eq!(component.worker_allowed().to_string(), row[9]);
        assert_eq!(component.requires_worker().to_string(), row[10]);

        // Resolve dependencies from the JSON, independently of Component's API.
        let mut expected = BTreeSet::new();
        let mut pending = vec![row[0]];
        while let Some(id) = pending.pop() {
            if expected.insert(id) {
                let entry = rows.iter().find(|entry| entry[0] == id).unwrap();
                pending.extend(entry[1].split(',').filter(|id| !id.is_empty()));
            }
        }
        let expanded = Components::from(component).with_dependencies();
        assert_eq!(
            expanded
                .iter()
                .map(Component::as_str)
                .collect::<BTreeSet<_>>(),
            expected
        );
        for mode in [
            Presentation::Headless,
            Presentation::X11,
            Presentation::Wayland,
        ] {
            for consent in [false, true] {
                let allowed =
                    rows.iter()
                        .filter(|entry| expected.contains(entry[0]))
                        .all(|entry| {
                            entry[5].is_empty()
                                && entry[2]
                                    .split(',')
                                    .any(|supported| supported == mode.as_str())
                                && (consent || entry[3] == "false")
                        });
                assert_eq!(
                    expanded.validate(mode, consent).is_ok(),
                    allowed,
                    "{} in {mode}, unfree consent={consent}",
                    row[0]
                );
                if !row[1].is_empty() {
                    assert!(
                        Components::from(component).validate(mode, consent).is_err(),
                        "{} accepted without its explicit dependencies",
                        row[0]
                    );
                }
            }
        }
    }
}
