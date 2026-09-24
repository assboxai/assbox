// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{
    Error, Result,
    worker::{WorkerHardware, WorkerSpec},
};

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
    if new_state + 16 > host.free_gib {
        return Err(Error::new(
            "insufficient free space for worker state and initial build headroom; also budget retained artifacts",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
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
            uplinks: vec![],
            network: assbox_domain::worker::WorkerNetwork::Offline,
            nameservers: vec![],
            guest_sudo: false,
        }
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
        h.free_gib = 47;
        assert!(validate_host_budget(&s, &h).is_err());
        h.free_gib = 48;
        assert!(validate_host_budget(&s, &h).is_ok());
        h.existing_state_gib = Some(32);
        h.free_gib = 16;
        assert!(validate_host_budget(&s, &h).is_ok());
        h.free_gib = 15;
        assert!(validate_host_budget(&s, &h).is_err());
        h.free_gib = 80;
        h.existing_state_gib = Some(16);
        assert!(validate_host_budget(&s, &h).is_err());
        h = host();
        h.kvm_available = false;
        assert!(validate_host_budget(&s, &h).is_err());
    }
}
