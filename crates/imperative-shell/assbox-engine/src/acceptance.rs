// SPDX-License-Identifier: GPL-3.0-or-later
//! Noninstalled test harness. No test transport or fixture entrypoint is compiled
//! into the appliance binary. Invoked explicitly inside disposable NixOS VMs.
use assbox_domain::release::ReleaseFloor;
use assbox_system::{commands::Commands, files};
use std::path::Path;

fn require_vm() {
    files::require_root().unwrap();
    assert_eq!(
        files::text(Path::new("/etc/assbox-acceptance-vm")).unwrap(),
        "disposable\n"
    );
}

#[test]
#[ignore = "requires the disposable authenticated-release VM and its test-only tool closure"]
fn release_fetch() {
    require_vm();
    let directory = Path::new("/var/lib/assbox-acceptance");
    let floor = if files::entry_exists(&directory.join("floor")).unwrap() {
        Some(ReleaseFloor::parse(&files::text(&directory.join("floor")).unwrap()).unwrap())
    } else {
        None
    };
    let tag = std::env::var("ASSBOX_TEST_TAG").unwrap();
    let expected = std::env::var("ASSBOX_TEST_ERROR").unwrap();
    let result = crate::release::fetch(
        &Commands,
        (tag != "latest").then_some(tag.as_str()),
        &directory.join("download"),
        floor.as_ref(),
        false,
    );
    if expected.is_empty() {
        let verified = result.unwrap();
        assert!(verified.source_path.starts_with("/nix/store"));
        assert!(verified.source_path.join("flake.lock").is_file());
        files::atomic_write(
            &directory.join("accepted-floor"),
            verified.floor.encode().as_bytes(),
            0o600,
        )
        .unwrap();
    } else {
        let error = result
            .err()
            .expect("untrusted release was accepted")
            .to_string();
        assert!(
            error.contains(&expected),
            "expected {expected:?}, got {error:?}"
        );
        assert!(!files::entry_exists(&directory.join("accepted-floor")).unwrap());
    }
}

/// Deliberate cut points exist only in this noninstalled test executable.
pub(crate) fn checkpoint(name: &str) -> assbox_domain::Result<()> {
    let control = Path::new("/var/lib/assbox-acceptance/cut");
    if !control.exists() {
        return Ok(());
    }
    require_vm();
    let value = files::text(control)?;
    if value.trim() == format!("fail:{name}") {
        return Err(assbox_domain::Error::new(format!(
            "injected failure: {name}"
        )));
    }
    if value.trim() == format!("pause:{name}") {
        files::atomic_write(
            Path::new("/var/lib/assbox-acceptance/reached"),
            name.as_bytes(),
            0o600,
        )?;
        while control.exists() {
            assbox_system::cancellation::check()?;
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
    }
    Ok(())
}

pub(crate) fn install_configuration(directory: &Path) -> assbox_domain::Result<()> {
    require_vm();
    let local = files::read(Path::new("/etc/assbox-acceptance-local.nix"))?;
    files::atomic_write(&directory.join("local.nix"), &local, 0o644)
}

#[test]
#[ignore = "requires disposable prepared disks and fixture release transport"]
fn install_apply() {
    use assbox_domain::*;
    require_vm();
    let values = Commands
        .jq_fields(
            &files::read(Path::new("/var/lib/assbox-acceptance/install.json")).unwrap(),
            r#"[.root,.esp,.backup,.platform,.key] | .[] | . + "\u0000""#,
        )
        .unwrap();
    assert_eq!(values.len(), 5);
    let request = InstallRequest {
        root: values[0].clone(),
        esp: (!values[1].is_empty()).then(|| values[1].clone()),
        backup: values[2].clone(),
        choices: Choices {
            instance: Default::default(),
            hostname: Hostname::parse("assbox-vm").unwrap(),
            timezone: "UTC".into(),
            components: Components::default(),
            presentation: Presentation::Headless,
            platform: values[3].parse().unwrap(),
            devices: DevicePolicy::default(),
            scale: 1,
            allow_unfree: false,
            allow_mutable_code: false,
            autostart: Vec::new(),
            admin_ssh_key: Some(values[4].clone()),
            agent_ssh_key: None,
            ssh_access: Default::default(),
            additional_packages: Default::default(),
            worker: None,
        },
    };
    let plan =
        assbox_policy::plan_install(assbox_system::probe::inventory(&Commands).unwrap(), request)
            .unwrap();
    crate::install::apply(plan, Some("r-1")).unwrap();
}

#[test]
#[ignore = "requires an installed disposable Assbox system"]
fn management() {
    use assbox_domain::PackageName;
    require_vm();
    match std::env::var("ASSBOX_TEST_OPERATION").unwrap().as_str() {
        "add" => crate::manage::package_change(PackageName::parse("hello").unwrap(), true),
        "remove" => crate::manage::package_change(PackageName::parse("hello").unwrap(), false),
        "stage" => crate::manage::rebuild(true),
        "switch" => crate::manage::rebuild(false),
        "update" => crate::manage::update(false),
        "maintenance" => crate::manage::maintenance(false),
        "retry" => crate::manage::maintenance(true),
        "recover" => crate::manage::recover(false),
        "recover-rollback" => crate::manage::recover(true),
        "cleanup" => crate::manage::cleanup(),
        operation => panic!("unknown operation {operation}"),
    }
    .unwrap();
}
