// SPDX-License-Identifier: GPL-3.0-or-later
//! Live hardware observations; no claim of firmware or application acceptance.

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Hardware {
    pub vendor: String,
    pub model: String,
    pub pci_network: Vec<PciNetworkDevice>,
    pub wireless: Vec<WirelessInterface>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PciNetworkDevice {
    pub slot: String,
    pub vendor: u16,
    pub device: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WirelessInterface {
    pub name: String,
    pub device_path: String,
    pub driver: Option<String>,
    pub out_of_tree: bool,
}
