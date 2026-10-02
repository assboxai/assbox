// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
//! Deterministic decisions. Effects, including effectful callback interfaces, live elsewhere.

pub mod efi;
pub mod hardware;
pub mod instances;
pub mod release;
use assbox_domain::*;

pub const ESP_TYPE: &str = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b";
pub const BIOS_BOOT_TYPE: &str = "21686148-6449-6e6f-744e-656564454649";

#[derive(Debug, Clone)]
pub struct InstallPlan {
    request: InstallRequest,
    inventory: Inventory,
    boot: BootKind,
}
impl InstallPlan {
    pub fn request(&self) -> &InstallRequest {
        &self.request
    }
    pub fn inventory(&self) -> &Inventory {
        &self.inventory
    }
    pub fn boot(&self) -> BootKind {
        self.boot
    }
    pub fn root(&self) -> &Partition {
        // Construction checked existence; no public field mutation or deserialization.
        self.inventory
            .partitions
            .iter()
            .find(|p| p.path == self.request.root)
            .expect("validated root")
    }
    pub fn backup(&self) -> &Partition {
        self.inventory
            .partitions
            .iter()
            .find(|p| p.path == self.request.backup)
            .expect("validated backup")
    }
    pub fn esp(&self) -> Option<&Partition> {
        self.request
            .esp
            .as_ref()
            .and_then(|s| self.inventory.partitions.iter().find(|p| &p.path == s))
    }
    /// Re-observe before each consequential phase. Mounts are allowed only where
    /// this operation explicitly mounted the corresponding selected partition.
    pub fn revalidate(&self, now: &Inventory, allowed: &[(&str, &str)]) -> Result<()> {
        hardware::validate_install_hardware(
            now.architecture,
            &now.hardware,
            self.request.choices.platform,
            self.request.choices.devices.wifi,
        )?;
        if now.hardware != self.inventory.hardware {
            return Err(Error::new(
                "hardware identity or network drivers changed; refusing a stale plan",
            ));
        }
        if now.architecture != self.inventory.architecture
            || now.firmware != self.inventory.firmware
            || now.live_media != self.inventory.live_media
        {
            return Err(Error::new("firmware or live-media identity changed"));
        }
        for disk in [self.root().parent.as_str(), self.backup().parent.as_str()]
            .into_iter()
            .chain(self.inventory.live_media.disk())
        {
            if now.disk(disk)? != self.inventory.disk(disk)? {
                return Err(Error::new("disk identity changed; refusing a stale plan"));
            }
            let old: Vec<_> = self
                .inventory
                .partitions
                .iter()
                .filter(|p| p.parent == disk)
                .collect();
            let new: Vec<_> = now.partitions.iter().filter(|p| p.parent == disk).collect();
            if old.len() != new.len() || old.iter().any(|a| !new.iter().any(|b| a.same_identity(b)))
            {
                return Err(Error::new("partition geometry or identity changed"));
            }
        }
        // Newly attached disks are outside the geometry comparison, but their
        // identifiers can still make the installed UUID bindings ambiguous.
        for partition in [self.root(), self.backup()].into_iter().chain(self.esp()) {
            unique_partition_identity(now, partition)?;
        }
        for p in now
            .partitions
            .iter()
            .filter(|p| p.parent == self.root().parent || p.parent == self.backup().parent)
        {
            for mount in &p.mounts {
                if !allowed
                    .iter()
                    .any(|(device, point)| p.path == *device && mount == point)
                {
                    return Err(Error::new(format!(
                        "unexpected mount on {}: {mount}",
                        p.path
                    )));
                }
            }
        }
        Ok(())
    }
}

/// Architecture is observed from the running kernel; there is no cross-install override.
pub fn validate_machine(
    architecture: Architecture,
    firmware: Firmware,
    platform: Platform,
) -> Result<()> {
    if architecture == Architecture::Aarch64
        && (firmware != Firmware::Uefi || platform != Platform::Generic)
    {
        return Err(Error::new(
            "AArch64 requires generic UEFI; BIOS and Intel Apple profiles are x86-64 only",
        ));
    }
    Ok(())
}

pub fn components_supported(
    architecture: Architecture,
    components: Components,
    presentation: Presentation,
) -> bool {
    matches!(architecture, Architecture::X86_64 | Architecture::Aarch64)
        && components.validate(presentation, true).is_ok()
}

fn validate_live_media(inv: &Inventory) -> Result<()> {
    match &inv.live_media {
        LiveMedia::Disk {
            disk,
            source,
            major_minor,
        } => {
            let physical = inv.disk(disk)?;
            let bound = if source == disk {
                physical.major_minor == *major_minor
            } else {
                inv.partitions.iter().any(|p| {
                    p.path == *source && p.parent == *disk && p.major_minor == *major_minor
                })
            };
            if !bound {
                return Err(Error::new(
                    "live-media source does not match its physical disk",
                ));
            }
        }
        LiveMedia::Optical {
            device,
            major_minor,
            bytes,
            filesystem,
            read_only,
            mounted_read_only,
            ..
        } => {
            if !*read_only
                || !*mounted_read_only
                || *bytes == 0
                || !matches!(filesystem.as_str(), "iso9660" | "udf")
                || !device.starts_with("/dev/")
                || major_minor.is_empty()
                || inv
                    .disks
                    .iter()
                    .any(|d| d.path == *device || d.major_minor == *major_minor)
            {
                return Err(Error::new(
                    "live optical media must be a distinct read-only ISO/UDF block device",
                ));
            }
        }
    }
    Ok(())
}

fn live_uses_disk(inv: &Inventory, disk: &Disk) -> bool {
    inv.live_media.disk().is_some_and(|name| name == disk.path)
        || inv.live_media.source() == disk.path
        || inv.live_media.major_minor() == disk.major_minor
}

pub fn validate_boot_target(current: &BootReceipt, target: &BootReceipt) -> Result<()> {
    if current.binding != target.binding {
        return Err(Error::new(
            "target generation has a different boot/storage binding; use expert NixOS recovery instead",
        ));
    }
    if !(2..=32).contains(&target.policy.generations) {
        return Err(Error::new("boot menu generations must be between 2 and 32"));
    }
    let target = &target.binding;
    let firmware = if matches!(target.mode, BootKind::BiosGpt | BootKind::BiosMbr) {
        Firmware::Bios
    } else {
        Firmware::Uefi
    };
    validate_machine(target.architecture, firmware, target.platform)?;
    if target.root_device.is_empty() || (firmware == Firmware::Uefi && target.esp_device.is_empty())
    {
        return Err(Error::new(
            "target generation has incomplete filesystem bindings",
        ));
    }
    Ok(())
}

fn unique_partition_identity(inv: &Inventory, partition: &Partition) -> Result<()> {
    if inv
        .partitions
        .iter()
        .filter(|p| p.uuid == partition.uuid)
        .count()
        != 1
        || inv
            .partitions
            .iter()
            .filter(|p| p.partuuid == partition.partuuid)
            .count()
            != 1
    {
        return Err(Error::new("duplicate filesystem UUID or PARTUUID"));
    }
    Ok(())
}

fn writable_unmounted(p: &Partition) -> Result<()> {
    if p.read_only
        || p.has_holders
        || !p.mounts.is_empty()
        || p.uuid.is_empty()
        || p.partuuid.is_empty()
    {
        return Err(Error::new(format!(
            "{} must be unmounted, writable and have UUID/PARTUUID",
            p.path
        )));
    }
    Ok(())
}

pub fn plan_install(inv: Inventory, req: InstallRequest) -> Result<InstallPlan> {
    req.choices.validate()?;
    validate_machine(inv.architecture, inv.firmware, req.choices.platform)?;
    hardware::validate_install_hardware(
        inv.architecture,
        &inv.hardware,
        req.choices.platform,
        req.choices.devices.wifi,
    )?;
    if !components_supported(
        inv.architecture,
        req.choices.components,
        req.choices.presentation,
    ) {
        return Err(Error::new(
            "application/presentation is unsupported on this architecture",
        ));
    }
    let root = inv.partition(&req.root)?;
    let backup = inv.partition(&req.backup)?;
    let target = inv.disk(&root.parent)?;
    validate_live_media(&inv)?;
    let backup_disk = inv.disk(&backup.parent)?;
    writable_unmounted(root)?;
    writable_unmounted(backup)?;
    if root.fs != FileSystem::Ext4 {
        return Err(Error::new("the prepared root filesystem must be ext4"));
    }
    if !matches!(
        backup.fs,
        FileSystem::Ext4 | FileSystem::Fat | FileSystem::Exfat
    ) {
        return Err(Error::new("backup must be ext4, FAT or exFAT"));
    }
    if live_uses_disk(&inv, target)
        || backup_disk.path == target.path
        || backup_disk.major_minor == target.major_minor
        || live_uses_disk(&inv, backup_disk)
    {
        return Err(Error::new(
            "target and backup must be separate disks, neither containing the live installer",
        ));
    }
    if target.read_only
        || backup_disk.read_only
        || target.hybrid_mbr
        || backup_disk.hybrid_mbr
        || target.has_holders
        || backup_disk.has_holders
        || !target.mounts.is_empty()
        || !backup_disk.mounts.is_empty()
    {
        return Err(Error::new(
            "read-only disks and hybrid partition tables are unsupported",
        ));
    }
    for p in &inv.partitions {
        if (p.parent == root.parent || p.parent == backup.parent)
            && (!p.mounts.is_empty() || p.has_holders)
        {
            return Err(Error::new(
                "all partitions of target and backup disks must be unmounted",
            ));
        }
    }
    // UUID aliases on another disk can select the wrong filesystem after reboot.
    for p in [root, backup] {
        unique_partition_identity(&inv, p)?;
    }
    if (inv.firmware == Firmware::Bios || req.choices.platform.is_apple())
        && !target.persistent_path.starts_with("/dev/disk/by-id/")
    {
        return Err(Error::new(
            "BIOS and Apple boot installation require an unambiguous whole-disk by-id path",
        ));
    }
    let boot = match (inv.firmware, target.table, req.choices.platform.is_apple()) {
        (Firmware::Uefi, Table::Gpt, apple) => {
            let name = req
                .esp
                .as_ref()
                .ok_or_else(|| Error::new("UEFI requires an existing ESP"))?;
            let esp = inv.partition(name)?;
            writable_unmounted(esp)?;
            if esp.parent != root.parent
                || esp.fs != FileSystem::Fat
                || !esp.part_type.eq_ignore_ascii_case(ESP_TYPE)
                || esp.path == root.path
            {
                return Err(Error::new(
                    "ESP must be a distinct FAT EFI System Partition on the target",
                ));
            }
            unique_partition_identity(&inv, esp)?;
            if !apple
                && inv
                    .partitions
                    .iter()
                    .any(|p| p.parent == root.parent && p.path != root.path && p.path != esp.path)
            {
                return Err(Error::new(
                    "generic UEFI installation requires a dedicated target disk",
                ));
            }
            if apple {
                BootKind::AppleRefind
            } else {
                BootKind::Uefi
            }
        }
        (Firmware::Bios, Table::Gpt, false) => {
            if req.esp.is_some() {
                return Err(Error::new("BIOS installation does not use an ESP"));
            }
            let extra: Vec<_> = inv
                .partitions
                .iter()
                .filter(|p| p.parent == root.parent && p.path != root.path)
                .collect();
            if extra.len() != 1
                || !extra[0].part_type.eq_ignore_ascii_case(BIOS_BOOT_TYPE)
                || extra[0].bytes < 1024 * 1024
                || extra[0].fs != FileSystem::None
                || extra[0].read_only
            {
                return Err(Error::new(
                    "BIOS/GPT requires one writable, unformatted BIOS Boot Partition of at least 1 MiB",
                ));
            }
            BootKind::BiosGpt
        }
        (Firmware::Bios, Table::Mbr, false) => {
            if req.esp.is_some()
                || root.start_bytes < 1024 * 1024
                || inv
                    .partitions
                    .iter()
                    .filter(|p| p.parent == root.parent)
                    .count()
                    != 1
                || !matches!(root.part_type.to_lowercase().as_str(), "0x83" | "83")
            {
                return Err(Error::new(
                    "BIOS/MBR requires a dedicated disk, one primary Linux partition, and a 1 MiB embedding gap",
                ));
            }
            BootKind::BiosMbr
        }
        _ => {
            return Err(Error::new(
                "unsupported firmware/table/platform combination",
            ));
        }
    };
    Ok(InstallPlan {
        request: req,
        inventory: inv,
        boot,
    })
}

pub fn filesystem_check(fs: FileSystem) -> Result<(&'static str, &'static [&'static str])> {
    match fs {
        FileSystem::Ext4 => Ok(("e2fsck", &["-f", "-n"])),
        FileSystem::Fat => Ok(("fsck.fat", &["-n"])),
        FileSystem::Exfat => Ok(("fsck.exfat", &["-n"])),
        _ => Err(Error::new(
            "no approved non-repairing checker for this filesystem",
        )),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RebootDecision {
    NoChange,
    StageFailed,
    RetryForPower,
    Reboot,
}
pub fn reboot_decision(f: MaintenanceFacts) -> RebootDecision {
    if !f.stage_succeeded {
        return RebootDecision::StageFailed;
    }
    if !f.changed_generation {
        return RebootDecision::NoChange;
    }
    if f.on_ac == Some(true) {
        return RebootDecision::Reboot;
    }
    if f.battery_presence == BatteryPresence::Absent
        && f.on_ac != Some(false)
        && f.battery_percent.is_none()
    {
        return RebootDecision::Reboot;
    }
    if f.battery_presence != BatteryPresence::Absent
        && f.battery_percent
            .is_some_and(|p| p <= 100 && p >= f.minimum_battery)
    {
        return RebootDecision::Reboot;
    }
    RebootDecision::RetryForPower
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Prepared,
    Built,
    Published,
    Activating,
    Committed,
}
impl Phase {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Built => "built",
            Self::Published => "published",
            Self::Activating => "activating",
            Self::Committed => "committed",
        }
    }
}
impl std::str::FromStr for Phase {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self> {
        match s {
            "prepared" => Ok(Self::Prepared),
            "built" => Ok(Self::Built),
            "published" => Ok(Self::Published),
            "activating" => Ok(Self::Activating),
            "committed" => Ok(Self::Committed),
            _ => Err(Error::new("unrecognized operation journal phase")),
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Recovery {
    DiscardCandidate,
    RestoreSources,
    InspectActivation,
    Nothing,
}
pub fn recovery_after_interruption(phase: Phase) -> Recovery {
    match phase {
        Phase::Prepared | Phase::Built => Recovery::DiscardCandidate,
        Phase::Published => Recovery::RestoreSources,
        Phase::Activating => Recovery::InspectActivation,
        Phase::Committed => Recovery::Nothing,
    }
}

/// Only a subsequent boot of the selected generation satisfies a recorded reboot.
/// Legacy records lack a boot ID, but still need a matching booted generation.
pub fn reboot_completed(
    pending: &PendingReboot,
    booted: &str,
    activated: &str,
    boot_id: &BootId,
) -> bool {
    pending.system() == booted
        && booted == activated
        && pending
            .origin_boot_id()
            .is_none_or(|origin| origin != boot_id)
}

/// Live changes may retarget an outstanding reboot, but cannot discharge it.
pub fn pending_after_activation(
    target: &str,
    booted: &str,
    activated: &str,
    boot_id: &BootId,
    pending: Option<&PendingReboot>,
    stage: bool,
) -> Result<Option<PendingReboot>> {
    if (stage && (target != booted || target != activated))
        || pending.is_some_and(|p| !reboot_completed(p, booted, activated, boot_id))
    {
        PendingReboot::new(target, boot_id.clone()).map(Some)
    } else {
        Ok(None)
    }
}

/// Recovery may undo only this transaction's profile and pending-boot changes.
/// Always require a reboot: matching links cannot prove a partial live activation
/// left services untouched, even when the old kernel is still running.
pub fn recovery_target<'a>(
    old: &'a str,
    new: &str,
    profile: &str,
    running: &str,
    pending: Option<&str>,
) -> Result<&'a str> {
    if ![old, new, profile, running]
        .into_iter()
        .all(assbox_domain::source::valid_store_system)
        || (profile != old && profile != new)
        || pending.is_some_and(|value| value != old && value != new)
    {
        return Err(Error::new(
            "generation state changed outside this operation or is invalid; refusing recovery",
        ));
    }
    Ok(old)
}

/// A suggestion, never a persisted automatic setting. None means ask the operator.
pub fn suggested_wifi(default_interfaces: &[bool]) -> Option<bool> {
    let first = *default_interfaces.first()?;
    default_interfaces
        .iter()
        .all(|b| *b == first)
        .then_some(first)
}

/// Validate a base EDID block and use its first detailed timing's physical size.
/// No display I/O; uncertain/missing metadata has no inferred scale.
pub fn suggested_scale(edid: &[u8]) -> Option<u8> {
    if edid.len() < 128
        || edid[..8] != [0, 255, 255, 255, 255, 255, 255, 0]
        || edid[..128].iter().fold(0u8, |a, b| a.wrapping_add(*b)) != 0
    {
        return None;
    }
    let d = &edid[54..72];
    if d[0] == 0 && d[1] == 0 {
        return None;
    }
    let px = u32::from(d[2]) | (u32::from(d[4] & 0xf0) << 4);
    let mm = u32::from(d[12]) | (u32::from(d[14] & 0xf0) << 4);
    if !(640..=16384).contains(&px) || !(100..=2000).contains(&mm) {
        return None;
    }
    let dpi = px * 254 / (mm * 10);
    if !(60..=400).contains(&dpi) {
        return None;
    }
    Some(if dpi >= 170 { 2 } else { 1 })
}

pub fn validate_audit(a: &Audit) -> Result<()> {
    if !a.enabled
        || !a.firewall
        || !a.root_locked
        || !a.agent_locked
        || !a.sandbox
        || !a.require_signatures
        || a.accept_flake_config
        || a.automount
        || a.passwordless_sudo
    {
        return Err(Error::new(
            "evaluated NixOS configuration violates the Assbox security contract",
        ));
    }
    if a.components.contains(Component::ChatgptDesktop) && a.presentation != Presentation::X11 {
        return Err(Error::new("ChatGPT requires X11"));
    }
    if a.agent_groups.iter().any(|g| {
        matches!(
            g.as_str(),
            "wheel" | "disk" | "input" | "docker" | "lxd" | "libvirtd" | "networkmanager"
        )
    }) || a.trusted_users.iter().any(|u| u != "root")
    {
        return Err(Error::new("workload or Nix trust privileges are too broad"));
    }
    if a.boot == BootKind::AppleRefind && a.efi_writes {
        return Err(Error::new("Apple rEFInd mode may not write EFI variables"));
    }
    Ok(())
}

pub fn recommended_platform(model: &str) -> Platform {
    match model.trim() {
        "MacBookPro11,1" => Platform::Macbookpro11_1,
        "MacBookPro12,1" => Platform::Macbookpro12_1,
        s if s.starts_with("Mac") => Platform::AppleIntel,
        _ => Platform::Generic,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn failure_and_power_never_become_a_reboot() {
        for changed in [false, true] {
            for staged in [false, true] {
                for ac in [None, Some(false), Some(true)] {
                    for battery in [None, Some(0), Some(19), Some(20), Some(100)] {
                        let f = MaintenanceFacts {
                            changed_generation: changed,
                            stage_succeeded: staged,
                            battery_presence: BatteryPresence::Present,
                            on_ac: ac,
                            battery_percent: battery,
                            minimum_battery: 20,
                        };
                        let r = reboot_decision(f);
                        if r == RebootDecision::Reboot {
                            assert!(staged && changed);
                            assert!(!(ac == Some(false) && battery.is_some_and(|n| n < 20)));
                        }
                    }
                }
            }
        }
    }
    #[test]
    fn no_session_activity_veto_in_maintenance_contract() {
        assert_eq!(
            reboot_decision(MaintenanceFacts {
                changed_generation: true,
                stage_succeeded: true,
                battery_presence: BatteryPresence::Present,
                on_ac: Some(true),
                battery_percent: Some(0),
                minimum_battery: 20
            }),
            RebootDecision::Reboot
        );
    }
    #[test]
    fn uncertain_network_does_not_disable_wifi() {
        assert_eq!(suggested_wifi(&[]), None);
        assert_eq!(suggested_wifi(&[false, true]), None);
        assert_eq!(suggested_wifi(&[true, true]), Some(true));
        assert_eq!(suggested_wifi(&[false]), Some(false));
    }
    #[test]
    fn unknown_display_falls_back_to_operator() {
        assert_eq!(suggested_scale(&[0; 128]), None);
    }
    #[test]
    fn activation_failure_is_not_a_claimed_rollback() {
        assert_eq!(
            recovery_after_interruption(Phase::Activating),
            Recovery::InspectActivation
        );
        assert_eq!(
            recovery_after_interruption(Phase::Published),
            Recovery::RestoreSources
        );
    }
}

/// Retention never selects a protected generation or one of the newest `keep`.
/// The shell provides actual profile links and separately verifies they did not change.
pub fn obsolete_generations(
    generations: &[(u64, String)],
    protected: &[String],
    keep: usize,
) -> Result<Vec<u64>> {
    if keep < 2 {
        return Err(Error::new("retain at least two generations"));
    }
    let mut sorted = generations.to_vec();
    sorted.sort_by_key(|(number, _)| std::cmp::Reverse(*number));
    if sorted.windows(2).any(|pair| pair[0].0 == pair[1].0) {
        return Err(Error::new("duplicate generation identity"));
    }
    Ok(sorted
        .into_iter()
        .skip(keep)
        .filter(|(_, system)| !protected.contains(system))
        .map(|(number, _)| number)
        .collect())
}

/// Select work before any network lookup or staging-budget read. A completed
/// staged update must not wait on a new release; an unresolved journal must not
/// be mistaken for permission to reboot into potentially partial activation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MaintenanceAction {
    Disabled,
    InspectRecovery,
    RebootPending,
    ConsiderStage,
}

pub fn maintenance_action(
    enabled: bool,
    transaction_pending: bool,
    reboot_pending: bool,
) -> MaintenanceAction {
    if !enabled {
        MaintenanceAction::Disabled
    } else if transaction_pending {
        MaintenanceAction::InspectRecovery
    } else if reboot_pending {
        MaintenanceAction::RebootPending
    } else {
        MaintenanceAction::ConsiderStage
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StageAttempt {
    Skip,
    Scheduled,
    Retry { used: u32 },
}
/// Retry counts are persisted before each retry; a crash cannot create an infinite
/// retry loop. A scheduled daily attempt starts a new bounded retry budget.
pub fn stage_attempt(retry_only: bool, retries_used: Option<u32>, limit: u32) -> StageAttempt {
    if !retry_only {
        return StageAttempt::Scheduled;
    }
    match retries_used {
        Some(used) if used < limit => StageAttempt::Retry { used: used + 1 },
        _ => StageAttempt::Skip,
    }
}

#[cfg(test)]
mod retention_tests {
    use super::*;
    #[test]
    fn retention_preserves_recent_running_and_pending_generations() {
        let generations: Vec<_> = (1..=12).map(|n| (n, format!("system-{n}"))).collect();
        assert_eq!(
            obsolete_generations(&generations, &["system-1".into(), "system-3".into()], 8).unwrap(),
            vec![4, 2]
        );
        assert!(
            obsolete_generations(&generations, &[], 20)
                .unwrap()
                .is_empty()
        );
        assert!(obsolete_generations(&generations, &[], 1).is_err());
        assert!(obsolete_generations(&[(1, "a".into()), (1, "b".into())], &[], 2).is_err());
    }
    #[test]
    fn maintenance_priority_covers_every_observed_state() {
        use MaintenanceAction::*;
        let cases = [
            ((false, false, false), Disabled),
            ((false, false, true), Disabled),
            ((false, true, false), Disabled),
            ((false, true, true), Disabled),
            ((true, false, false), ConsiderStage),
            ((true, false, true), RebootPending),
            ((true, true, false), InspectRecovery),
            ((true, true, true), InspectRecovery),
        ];
        for ((enabled, transaction, pending), expected) in cases {
            assert_eq!(maintenance_action(enabled, transaction, pending), expected);
        }
    }
    #[test]
    fn pending_reboot_does_not_consume_or_depend_on_stage_retry_budget() {
        for retry in [false, true] {
            for budget in [None, Some(0), Some(3), Some(u32::MAX)] {
                let staging = stage_attempt(retry, budget, 3);
                assert_eq!(
                    maintenance_action(true, false, true),
                    MaintenanceAction::RebootPending,
                    "pending boot must precede staging decision {staging:?}"
                );
                assert_eq!(
                    maintenance_action(true, true, true),
                    MaintenanceAction::InspectRecovery
                );
            }
        }
    }
    #[test]
    fn stage_retry_budget_is_bounded_and_daily_attempt_resets_it() {
        assert_eq!(stage_attempt(false, Some(99), 3), StageAttempt::Scheduled);
        assert_eq!(stage_attempt(true, None, 3), StageAttempt::Skip);
        assert_eq!(
            stage_attempt(true, Some(0), 3),
            StageAttempt::Retry { used: 1 }
        );
        assert_eq!(
            stage_attempt(true, Some(2), 3),
            StageAttempt::Retry { used: 3 }
        );
        assert_eq!(stage_attempt(true, Some(3), 3), StageAttempt::Skip);
        assert_eq!(stage_attempt(true, Some(u32::MAX), 3), StageAttempt::Skip);
    }
}

/// A freshly prepared ext4 root is empty, or contains only its empty, ordinary
/// root-owned recovery directory. Recovered user files never count as empty.
pub fn validate_prepared_root(entries: &[PreparedRootEntry]) -> Result<()> {
    let valid = match entries {
        [] => true,
        [entry] => {
            entry.name == "lost+found"
                && entry.is_directory
                && entry.empty
                && entry.owner == 0
                && entry.group == 0
                && entry.mode & 0o7022 == 0
                && entry.same_filesystem
        }
        _ => false,
    };
    if !valid {
        return Err(Error::new(
            "root filesystem is not empty or has an unsafe lost+found; preserve its data and prepare a different empty root",
        ));
    }
    Ok(())
}

pub fn validate_component_selection(
    components: Components,
    presentation: Presentation,
    accepted_unfree: bool,
) -> Result<()> {
    components.validate(presentation, accepted_unfree)
}
pub mod worker;
