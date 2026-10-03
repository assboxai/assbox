// SPDX-License-Identifier: GPL-3.0-or-later
//! Structural boot preconditions, not signature or firmware-boot verification.
use assbox_domain::{Error, Result};

pub fn validate_refind_image(path: &str, bytes: &[u8]) -> Result<()> {
    if !path.eq_ignore_ascii_case("efi/refind/refind_x64.efi") {
        return Err(Error::new(
            "Apple preservation requires EFI/refind/refind_x64.efi; other layouts require expert preparation",
        ));
    }
    let u16_at = |n: usize| {
        bytes
            .get(n..n + 2)
            .map(|b| u16::from_le_bytes([b[0], b[1]]))
    };
    let bad = || Error::new("rEFInd path is not an x86-64 PE32+ EFI application");
    if bytes.get(..2) != Some(b"MZ") || bytes.len() > 32 * 1024 * 1024 {
        return Err(bad());
    }
    let pointer = bytes.get(0x3c..0x40).ok_or_else(bad)?;
    let pe = u32::from_le_bytes([pointer[0], pointer[1], pointer[2], pointer[3]]) as usize;
    if pe > bytes.len().saturating_sub(96)
        || bytes.get(pe..pe + 4) != Some(b"PE\0\0")
        || u16_at(pe + 4) != Some(0x8664)
        || u16_at(pe + 6).is_none_or(|n| n == 0)
        || u16_at(pe + 20).is_none_or(|n| n < 70)
        || u16_at(pe + 22).is_none_or(|n| n & 2 == 0)
        || u16_at(pe + 24) != Some(0x20b)
        || u16_at(pe + 24 + 68) != Some(10)
    {
        return Err(bad());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn image() -> Vec<u8> {
        let mut b = vec![0; 512];
        b[..2].copy_from_slice(b"MZ");
        b[0x3c] = 128;
        b[128..132].copy_from_slice(b"PE\0\0");
        b[132..134].copy_from_slice(&0x8664u16.to_le_bytes());
        b[134] = 1;
        b[148] = 240;
        b[150] = 2;
        b[152..154].copy_from_slice(&0x20bu16.to_le_bytes());
        b[220] = 10;
        b
    }
    #[test]
    fn accepted_layout_requires_a_real_efi_header() {
        assert!(validate_refind_image("EFI/refind/refind_x64.efi", &image()).is_ok());
        for path in [
            "refind-backup.txt",
            "EFI/BOOT/BOOTX64.EFI",
            "EFI/refind/refind_x64.efi.bak",
        ] {
            assert!(validate_refind_image(path, &image()).is_err());
        }
        for n in [0, 128, 132, 152, 220] {
            let mut b = image();
            b[n] = 0;
            assert!(validate_refind_image("EFI/refind/refind_x64.efi", &b).is_err());
        }
        for n in [0, 2, 64, 128, 221] {
            assert!(validate_refind_image("EFI/refind/refind_x64.efi", &image()[..n]).is_err());
        }
    }
}
