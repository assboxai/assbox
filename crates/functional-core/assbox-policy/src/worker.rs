// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{
    Error, Result,
    worker::{WorkerHardware, WorkerNetwork, WorkerSpec},
};

use assbox_domain::worker::{GIB, storage_reserve};

/// Change only egress on an existing topology; never guess newly required uplinks.
pub fn with_egress(
    mut spec: WorkerSpec,
    network: WorkerNetwork,
    unfree: bool,
) -> Result<WorkerSpec> {
    spec.network = network;
    if network == WorkerNetwork::Offline {
        spec.uplinks.clear();
        spec.nameservers.clear();
    } else if spec.uplinks.is_empty() {
        return Err(Error::new(
            "enabling worker egress requires explicit uplinks and DNS; use assbox worker configure first",
        ));
    }
    spec.validate(unfree)?;
    Ok(spec)
}

/// Resolve once after building the provisional controller/image closure. Leave
/// another GiB for the final configuration derivations. No disk is resized here.
pub fn automatic_state_gib(total: u64, free: u64, root_virtual: u64) -> Result<u32> {
    let capacity = free
        .saturating_sub(root_virtual)
        .saturating_sub(storage_reserve(total))
        .saturating_sub(GIB)
        / GIB;
    if capacity < 8 {
        return Err(Error::new(
            "insufficient worker capacity after reserving the system overlay and controller build/recovery space",
        ));
    }
    Ok(capacity.min(2048) as u32)
}

/// Budget for a trusted desktop, a bounded VMM and a single headless worker.
/// These are planning defaults, not predictions of application performance.
pub fn recommended_memory(host: &WorkerHardware) -> Result<u32> {
    if !host.kvm_available {
        return Err(Error::new(
            "usable KVM is required; enable virtualization/nested KVM or keep VM mode disabled; no execution fallback",
        ));
    }
    if host.memory_mib < 5120 {
        return Err(Error::new(
            "at least 5 GiB of physical RAM is required for the minimum worker budget",
        ));
    }
    Ok(if host.memory_mib >= 14336 {
        8192
    } else if host.memory_mib >= 10240 {
        4096
    } else if host.memory_mib >= 6144 {
        3072
    } else {
        2048
    })
}

pub fn recommended_cpus(host: &WorkerHardware) -> u32 {
    host.cpus.saturating_sub(1).clamp(1, 4)
}

pub fn validate_host_budget(spec: &WorkerSpec, host: &WorkerHardware) -> Result<()> {
    recommended_memory(host)?;
    if u64::from(spec.memory_mib) + 2048 + 1024 > host.memory_mib {
        return Err(Error::new(
            "guest RAM plus host reserve and VMM overhead exceeds physical RAM",
        ));
    }
    if spec.vcpus > host.cpus {
        return Err(Error::new(
            "requested worker CPUs exceed the observed host CPU count",
        ));
    }
    // A conservative floor, not proof that a build will fit. Artifact-specific
    // checks reserve the entire writable root once its virtual size is known.
    if host
        .existing_state_gib
        .is_some_and(|size| size != spec.state_gib)
    {
        return Err(Error::new(
            "existing worker state size differs; automatic resize/reformat is forbidden",
        ));
    }
    let new_state = if host.existing_state_gib.is_some() {
        0
    } else {
        u64::from(spec.state_gib)
    };
    if new_state + 32 > host.free_gib {
        return Err(Error::new(
            "insufficient free space for worker state and initial build headroom; also budget retained artifacts",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn automatic_capacity_keeps_recovery_headroom() {
        assert_eq!(
            automatic_state_gib(256 * GIB, 220 * GIB, 20 * GIB).unwrap(),
            147
        );
        assert_eq!(
            automatic_state_gib(100 * GIB, 90 * GIB, 10 * GIB).unwrap(),
            47
        );
        assert!(automatic_state_gib(64 * GIB, 50 * GIB, 10 * GIB).is_err());
        assert_eq!(
            automatic_state_gib(64 * GIB, 51 * GIB, 10 * GIB).unwrap(),
            8
        );
        assert_eq!(
            automatic_state_gib(5000 * GIB, 4900 * GIB, 10 * GIB).unwrap(),
            2048
        );
        assert!(automatic_state_gib(256 * GIB, 0, u64::MAX).is_err());
    }
    #[test]
    fn automatic_capacity_allows_controller_growth_before_admission_floor() {
        use assbox_domain::worker::STORAGE_ADMISSION_RESERVE;
        for (total, free, root) in [(256, 220, 20), (100, 90, 10), (64, 51, 10)] {
            let capacity = automatic_state_gib(total * GIB, free * GIB, root * GIB).unwrap();
            let required = u64::from(capacity) * GIB + root * GIB + STORAGE_ADMISSION_RESERVE;
            // New controller generations may consume 24 GiB without resizing
            // the worker or spending the separate 8 GiB admission floor.
            assert!(free * GIB - 24 * GIB >= required);
        }
    }
    use assbox_domain::Components;
    fn host() -> WorkerHardware {
        WorkerHardware {
            memory_mib: 8192,
            cpus: 4,
            free_gib: 80,
            existing_state_gib: None,
            kvm_available: true,
            uplinks: vec!["eth0".into()],
        }
    }
    fn spec() -> WorkerSpec {
        WorkerSpec {
            components: "vim".parse().unwrap(),
            mutable_components: Components::default(),

            memory_mib: 3072,
            vcpus: 2,
            state_gib: 32,
            auto_state: false,
            uplinks: vec![],
            network: assbox_domain::worker::WorkerNetwork::Offline,
            nameservers: vec![],
            guest_sudo: false,
        }
    }
    #[test]
    fn egress_changes_preserve_resources_and_never_invent_authority() {
        let mut original = spec();
        original.network = WorkerNetwork::Normal;
        original.uplinks = vec!["eth0".into()];
        original.nameservers = vec!["1.1.1.1".into()];
        let internet = with_egress(original.clone(), WorkerNetwork::Internet, false).unwrap();
        let mut expected = original.clone();
        expected.network = WorkerNetwork::Internet;
        assert_eq!(internet, expected);
        let offline = with_egress(original, WorkerNetwork::Offline, false).unwrap();
        assert!(offline.uplinks.is_empty());
        assert!(offline.nameservers.is_empty());
        assert_eq!(offline.memory_mib, expected.memory_mib);
        assert_eq!(offline.state_gib, expected.state_gib);
        assert!(with_egress(offline, WorkerNetwork::Internet, false).is_err());
        expected.nameservers = vec!["192.168.1.1".into()];
        assert!(with_egress(expected, WorkerNetwork::Internet, false).is_err());
    }
    #[test]
    fn automatic_budgets_have_boundaries() {
        let mut h = host();
        for (ram, expected) in [
            (5120, 2048),
            (6143, 2048),
            (6144, 3072),
            (8192, 3072),
            (10240, 4096),
            (14336, 8192),
        ] {
            h.memory_mib = ram;
            assert_eq!(recommended_memory(&h).unwrap(), expected);
        }
        h.memory_mib = 5119;
        assert!(recommended_memory(&h).is_err());
        h = host();
        h.kvm_available = false;
        assert!(recommended_memory(&h).is_err());
        for (cpus, expected) in [(1, 1), (2, 1), (4, 3), (16, 4)] {
            h.cpus = cpus;
            assert_eq!(recommended_cpus(&h), expected);
        }
    }
    #[test]
    fn resources_and_existing_disk_are_not_silently_changed() {
        let mut h = host();
        let mut s = spec();
        assert!(validate_host_budget(&s, &h).is_ok());
        s.memory_mib = 8192;
        assert!(validate_host_budget(&s, &h).is_err());
        s = spec();
        s.vcpus = 5;
        assert!(validate_host_budget(&s, &h).is_err());
        s = spec();
        h.free_gib = 63;
        assert!(validate_host_budget(&s, &h).is_err());
        h.free_gib = 64;
        assert!(validate_host_budget(&s, &h).is_ok());
        h.existing_state_gib = Some(32);
        h.free_gib = 32;
        assert!(validate_host_budget(&s, &h).is_ok());
        h.free_gib = 31;
        assert!(validate_host_budget(&s, &h).is_err());
        h.free_gib = 80;
        h.existing_state_gib = Some(16);
        assert!(validate_host_budget(&s, &h).is_err());
        h = host();
        h.kvm_available = false;
        assert!(validate_host_budget(&s, &h).is_err());
    }
}
