// SPDX-License-Identifier: GPL-3.0-or-later
//! Read-only sysfs observations. Hardware support decisions belong to policy.
use crate::files::io;
use assbox_domain::*;
use std::{fs, io::Read, path::Path};

fn field(path: &Path) -> Result<String> {
    let mut bytes = Vec::new();
    io(io(fs::File::open(path))?.take(257).read_to_end(&mut bytes))?;
    if bytes.len() > 256 {
        return Err(Error::new("hardware observation exceeds field limit"));
    }
    String::from_utf8(bytes)
        .map(|value| value.trim().to_owned())
        .map_err(|_| Error::new("hardware observation is not UTF-8"))
}

fn optional_field(path: &Path) -> Result<String> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        result => {
            io(result)?;
            field(path)
        }
    }
}

fn hex(path: &Path) -> Result<u32> {
    let value = field(path)?;
    u32::from_str_radix(value.strip_prefix("0x").unwrap_or(&value), 16)
        .map_err(|_| Error::new("invalid PCI hardware identifier"))
}

fn entries(path: &Path) -> Result<Vec<std::path::PathBuf>> {
    let directory = match fs::read_dir(path) {
        Ok(directory) => directory,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(Error::new(error.to_string())),
    };
    let mut paths = Vec::new();
    for entry in directory {
        paths.push(io(entry)?.path());
        if paths.len() > 4096 {
            return Err(Error::new("hardware inventory exceeds device limit"));
        }
    }
    paths.sort();
    Ok(paths)
}

fn name(path: &Path) -> Result<String> {
    path.file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty() && value.chars().all(|c| !c.is_control()))
        .map(str::to_owned)
        .ok_or_else(|| Error::new("invalid hardware device name"))
}

pub fn observe() -> Result<Hardware> {
    observe_at(Path::new("/sys"))
}

fn observe_at(sys: &Path) -> Result<Hardware> {
    let mut hardware = Hardware {
        vendor: optional_field(&sys.join("class/dmi/id/sys_vendor"))?,
        model: optional_field(&sys.join("class/dmi/id/product_name"))?,
        ..Hardware::default()
    };
    for path in entries(&sys.join("bus/pci/devices"))? {
        if hex(&path.join("class"))? >> 16 == 0x02 {
            hardware.pci_network.push(PciNetworkDevice {
                slot: name(&path)?,
                vendor: u16::try_from(hex(&path.join("vendor"))?)
                    .map_err(|_| Error::new("invalid PCI vendor"))?,
                device: u16::try_from(hex(&path.join("device"))?)
                    .map_err(|_| Error::new("invalid PCI device"))?,
            });
        }
    }
    for path in entries(&sys.join("class/net"))? {
        // Both expose a real wireless interface; do not infer Wi-Fi from its name.
        if !path
            .join("wireless")
            .try_exists()
            .map_err(|e| Error::new(e.to_string()))?
            && !path
                .join("phy80211")
                .try_exists()
                .map_err(|e| Error::new(e.to_string()))?
        {
            continue;
        }
        let device = io(fs::canonicalize(path.join("device")))?;
        let driver = match fs::canonicalize(device.join("driver")) {
            Ok(path) => Some(name(&path)?),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(Error::new(error.to_string())),
        };
        let taint = optional_field(&device.join("driver/module/taint"))?;
        hardware.wireless.push(WirelessInterface {
            name: name(&path)?,
            device_path: device
                .strip_prefix(sys)
                .map_err(|_| Error::new("network device resolves outside sysfs"))?
                .to_str()
                .ok_or_else(|| Error::new("invalid network device path"))?
                .to_owned(),
            driver,
            out_of_tree: taint.contains('O'),
        });
    }
    Ok(hardware)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::unix::fs::symlink, path::PathBuf};

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "assbox-hardware-{}-{}",
                std::process::id(),
                u64::from_le_bytes(crate::files::random_bytes().unwrap())
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn put(&self, path: &str, value: &str) {
            let path = self.0.join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, value).unwrap();
        }
        fn wifi(&self, interface: &str, driver: &str, taint: &str) {
            self.put(&format!("class/net/{interface}/wireless/present"), "");
            self.put(&format!("devices/{interface}/present"), "");
            self.put(&format!("bus/usb/drivers/{driver}/module/taint"), taint);
            symlink(
                self.0.join(format!("devices/{interface}")),
                self.0.join(format!("class/net/{interface}/device")),
            )
            .unwrap();
            symlink(
                self.0.join(format!("bus/usb/drivers/{driver}")),
                self.0.join(format!("devices/{interface}/driver")),
            )
            .unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn observes_unbound_pci_and_bound_usb_without_network_secrets() {
        let f = Fixture::new();
        f.put("class/dmi/id/sys_vendor", "Apple Inc.\n");
        f.put("class/dmi/id/product_name", "MacBookPro11,1\n");
        f.put("bus/pci/devices/0000:03:00.0/class", "0x028000\n");
        f.put("bus/pci/devices/0000:03:00.0/vendor", "0x14e4\n");
        f.put("bus/pci/devices/0000:03:00.0/device", "0x43a0\n");
        f.wifi("wlan1", "ath9k_htc", "");
        f.wifi("wlan0", "wl", "PO\n");
        let hardware = observe_at(&f.0).unwrap();
        assert_eq!(hardware.model, "MacBookPro11,1");
        assert_eq!(hardware.pci_network[0].device, 0x43a0);
        assert_eq!(hardware.wireless[0].name, "wlan0");
        assert!(hardware.wireless[0].out_of_tree);
        assert_eq!(hardware.wireless[1].driver.as_deref(), Some("ath9k_htc"));
        assert!(!hardware.wireless[1].out_of_tree);
        assert_eq!(hardware.wireless[1].device_path, "devices/wlan1");
        fs::remove_file(f.0.join("devices/wlan1/driver")).unwrap();
        assert_eq!(observe_at(&f.0).unwrap().wireless[1].driver, None);
    }

    #[test]
    fn missing_optional_buses_are_empty_but_invalid_observations_fail() {
        let f = Fixture::new();
        assert_eq!(observe_at(&f.0).unwrap(), Hardware::default());
        f.put("class/dmi/id/product_name", &"x".repeat(257));
        assert!(observe_at(&f.0).is_err());
        f.put("class/dmi/id/product_name", "Generic");
        f.put("bus/pci/devices/0000:00:00.0/class", "bogus");
        assert!(observe_at(&f.0).is_err());
        f.put("bus/pci/devices/0000:00:00.0/class", "0x028000");
        f.put("bus/pci/devices/0000:00:00.0/vendor", "0x10000");
        f.put("bus/pci/devices/0000:00:00.0/device", "0x43a0");
        assert!(observe_at(&f.0).is_err());
    }
}
