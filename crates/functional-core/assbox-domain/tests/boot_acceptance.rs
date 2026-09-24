// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{BootAcceptance, BootId};

const SYSTEM: &str = "/nix/store/00000000000000000000000000000000-nixos-system-assbox-1";
const OTHER: &str = "/nix/store/11111111111111111111111111111111-nixos-system-assbox-2";

fn boot(value: u8) -> BootId {
    BootId::parse(&format!("00000000-0000-0000-0000-{value:012}")).unwrap()
}

#[test]
fn receipt_roundtrips_and_binds_generation_and_kernel_boot() {
    let receipt = BootAcceptance::new(SYSTEM, boot(1)).unwrap();
    assert_eq!(BootAcceptance::parse(&receipt.encode()).unwrap(), receipt);
    assert!(receipt.matches(SYSTEM, &boot(1)));
    assert!(!receipt.matches(OTHER, &boot(1)));
    assert!(!receipt.matches(SYSTEM, &boot(2)));
}

#[test]
fn receipt_is_strict_and_does_not_accept_legacy_pending_state() {
    let encoded = BootAcceptance::new(SYSTEM, boot(1)).unwrap().encode();
    for malformed in [
        String::new(),
        SYSTEM.to_owned(),
        encoded.trim_end().to_owned(),
        format!("{encoded}extra\n"),
        encoded.replace("acceptance-v1", "acceptance-v2"),
        encoded.replace("acceptance", "pending-reboot"),
        encoded.replace("nixos-system", "not-system"),
        encoded.replace("00000000-0000-0000-0000-000000000001", "invalid"),
    ] {
        assert!(BootAcceptance::parse(&malformed).is_err(), "{malformed}");
    }
    assert!(BootAcceptance::new("/tmp/system", boot(1)).is_err());
}
