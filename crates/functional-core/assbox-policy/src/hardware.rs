// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;

/// An in-tree driver observed on live media is a prerequisite, not proof that
/// the target kernel, firmware and access point work together.
pub fn usable_wifi(interface: &WirelessInterface) -> bool {
    !interface.out_of_tree
        && interface
            .driver
            .as_deref()
            .is_some_and(|driver| !driver.is_empty() && driver != "wl")
}

pub fn has_bcm4360(hardware: &Hardware) -> bool {
    hardware
        .pci_network
        .iter()
        .any(|device| device.vendor == 0x14e4 && matches!(device.device, 0x43a0 | 0x4360))
}

pub fn validate_install_hardware(
    architecture: Architecture,
    hardware: &Hardware,
    platform: Platform,
    wifi: bool,
) -> Result<()> {
    let apple = hardware.vendor.starts_with("Apple") || hardware.model.starts_with("Mac");
    if architecture == Architecture::X86_64 && (apple || platform.is_apple()) {
        let expected = match hardware.model.as_str() {
            "MacBookPro11,1" => Platform::Macbookpro11_1,
            "MacBookPro12,1" => Platform::Macbookpro12_1,
            _ => {
                return Err(Error::new(
                    "the guided Apple installer supports MacBookPro11,1 and MacBookPro12,1 only; other models, including T2 Macs, require separately reviewed NixOS hardware support",
                ));
            }
        };
        if platform != expected {
            return Err(Error::new(format!(
                "detected Mac model requires the {expected} profile; a different profile cannot bypass hardware checks"
            )));
        }
    }
    if wifi && !hardware.wireless.iter().any(usable_wifi) {
        return Err(Error::new(if has_bcm4360(hardware) {
            "BCM4360 built-in Wi-Fi requires the unsupported insecure wl driver; use Ethernet with Wi-Fi disabled, or attach a supported USB Wi-Fi adapter and restart the installer"
        } else {
            "Wi-Fi was requested but no wireless interface has a bound in-tree driver; establish supported Wi-Fi on the live medium and restart, or use Ethernet with Wi-Fi disabled (wl and out-of-tree drivers are unsupported)"
        }));
    }
    Ok(())
}
