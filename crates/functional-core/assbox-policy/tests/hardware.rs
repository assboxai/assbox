// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_policy::hardware::*;

fn mac(model: &str) -> Hardware {
    Hardware {
        vendor: "Apple Inc.".into(),
        model: model.into(),
        ..Hardware::default()
    }
}

fn wifi(driver: Option<&str>, out_of_tree: bool) -> WirelessInterface {
    WirelessInterface {
        name: "wlan0".into(),
        device_path: "devices/usb1/1-1/1-1:1.0".into(),
        driver: driver.map(str::to_owned),
        out_of_tree,
    }
}

#[test]
fn model_specific_profiles_cannot_be_selected_for_other_machines() {
    for (model, expected) in [
        ("MacBookPro11,1", Platform::Macbookpro11_1),
        ("MacBookPro12,1", Platform::Macbookpro12_1),
    ] {
        for platform in [
            Platform::Generic,
            Platform::AppleIntel,
            Platform::Macbookpro11_1,
            Platform::Macbookpro12_1,
        ] {
            assert_eq!(
                validate_install_hardware(Architecture::X86_64, &mac(model), platform, false)
                    .is_ok(),
                platform == expected
            );
        }
    }
    for model in [
        "MacBookPro15,1",
        "MacBookAir9,1",
        "Macmini8,1",
        "MacBookPro13,3",
        "MacPro5,1",
        "",
        "Unknown",
    ] {
        for platform in [
            Platform::Generic,
            Platform::AppleIntel,
            Platform::Macbookpro11_1,
            Platform::Macbookpro12_1,
        ] {
            assert!(
                validate_install_hardware(Architecture::X86_64, &mac(model), platform, false)
                    .is_err()
            );
        }
    }
    assert!(
        validate_install_hardware(
            Architecture::X86_64,
            &Hardware::default(),
            Platform::Macbookpro12_1,
            false
        )
        .is_err()
    );
    for architecture in [Architecture::X86_64, Architecture::Aarch64] {
        assert!(
            validate_install_hardware(architecture, &Hardware::default(), Platform::Generic, false)
                .is_ok()
        );
    }
}

#[test]
fn insecure_or_unbound_wifi_never_satisfies_requested_wifi() {
    let mut hardware = mac("MacBookPro11,1");
    hardware.pci_network.push(PciNetworkDevice {
        slot: "0000:03:00.0".into(),
        vendor: 0x14e4,
        device: 0x43a0,
    });
    let check = |hardware: &Hardware, enabled| {
        validate_install_hardware(
            Architecture::X86_64,
            hardware,
            Platform::Macbookpro11_1,
            enabled,
        )
    };
    assert!(has_bcm4360(&hardware));
    assert!(check(&hardware, false).is_ok()); // Ethernet requires no wl exception.
    assert!(
        check(&hardware, true)
            .unwrap_err()
            .to_string()
            .contains("BCM4360")
    );
    for interface in [
        wifi(None, false),
        wifi(Some(""), false),
        wifi(Some("wl"), true),
        wifi(Some("wl"), false),
        wifi(Some("vendor_usb"), true),
    ] {
        hardware.wireless = vec![interface];
        assert!(check(&hardware, true).is_err());
    }
    // An unsupported built-in adapter does not block a supported external one.
    hardware.wireless.push(wifi(Some("ath9k_htc"), false));
    assert!(check(&hardware, true).is_ok());
}

#[test]
fn other_broadcom_devices_are_not_mistaken_for_bcm4360() {
    let mut hardware = mac("MacBookPro12,1");
    hardware.pci_network.push(PciNetworkDevice {
        slot: "0000:03:00.0".into(),
        vendor: 0x14e4,
        device: 0x43ba,
    });
    assert!(!has_bcm4360(&hardware));
    assert!(
        validate_install_hardware(
            Architecture::X86_64,
            &hardware,
            Platform::Macbookpro12_1,
            true
        )
        .is_err()
    );
    hardware.wireless.push(wifi(Some("brcmfmac"), false));
    assert!(
        validate_install_hardware(
            Architecture::X86_64,
            &hardware,
            Platform::Macbookpro12_1,
            true
        )
        .is_ok()
    );
    hardware.pci_network[0].device = 0x4360;
    assert!(has_bcm4360(&hardware));
    hardware.pci_network[0].vendor = 0x8086;
    assert!(!has_bcm4360(&hardware));
}
