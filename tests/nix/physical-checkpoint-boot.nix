# SPDX-License-Identifier: GPL-3.0-or-later
{
  isoImage,
  kernelConfig,
  pkgs,
  sourceRevision,
}:
let
  ovmf = pkgs.OVMF;
  marker = "ASSBOX_PHYSICAL_CHECKPOINT_READY ${sourceRevision}";
in
pkgs.runCommand "assbox-physical-checkpoint-boot"
  {
    nativeBuildInputs = [
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.qemu_kvm
      pkgs.xorriso
    ];
    requiredSystemFeatures = [ "kvm" ];
  }
  ''
    set -eu

    set -- ${isoImage}/iso/*.iso
    test "$#" -eq 1
    iso="$1"

    mkdir -p "$out"
    xorriso -indev "$iso" -report_el_torito plain \
      > "$out/el-torito.txt" 2>&1
    grep -Fq 'BIOS' "$out/el-torito.txt"
    grep -Fq 'UEFI' "$out/el-torito.txt"

    # Module blacklisting happens before userspace only when the device cores
    # remain modular. Refuse an image whose kernel compiled one of them in.
    : > "$out/kernel-device-config.txt"
    for setting in \
      CONFIG_CFG80211=m \
      CONFIG_MAC80211=m \
      CONFIG_BT=m \
      CONFIG_SND=m \
      CONFIG_SND_HDA_INTEL=m \
      CONFIG_SND_USB_AUDIO=m \
      CONFIG_USB_VIDEO_CLASS=m; do
      grep -Fx "$setting" ${kernelConfig} >> "$out/kernel-device-config.txt"
    done
    grep -Fx '# CONFIG_RFKILL_INPUT is not set' ${kernelConfig} \
      >> "$out/kernel-device-config.txt"
    for setting in \
      CONFIG_CFG80211 \
      CONFIG_MAC80211 \
      CONFIG_BT \
      CONFIG_BT_BNEP \
      CONFIG_BT_HCIBTUSB \
      CONFIG_BT_RFCOMM \
      CONFIG_USB_NET_CDC_MBIM \
      CONFIG_IEEE802154 \
      CONFIG_MAC802154 \
      CONFIG_NFC \
      CONFIG_USB_NET_QMI_WWAN \
      CONFIG_UWB \
      CONFIG_WWAN \
      CONFIG_SND \
      CONFIG_SND_HDA_INTEL \
      CONFIG_SND_USB_AUDIO \
      CONFIG_USB_VIDEO_CLASS; do
      if grep -Fx "$setting=y" ${kernelConfig}; then
        echo "$setting is built into the checkpoint kernel" >&2
        exit 1
      fi
    done

    qemu_pid=
    stop_qemu() {
      if test -n "$qemu_pid" && kill -0 "$qemu_pid" 2>/dev/null; then
        kill "$qemu_pid" 2>/dev/null || true
        for ignored in $(seq 1 10); do
          kill -0 "$qemu_pid" 2>/dev/null || break
          sleep 1
        done
        kill -KILL "$qemu_pid" 2>/dev/null || true
        wait "$qemu_pid" 2>/dev/null || true
      fi
      qemu_pid=
    }
    trap stop_qemu EXIT INT TERM

    wait_for_ready() {
      log="$1"
      ready=0
      for ignored in $(seq 1 420); do
        if grep -Fq ${pkgs.lib.escapeShellArg marker} "$log"; then
          ready=1
          break
        fi
        if ! kill -0 "$qemu_pid" 2>/dev/null; then
          cat "$log" >&2
          echo "checkpoint VM exited before its readiness marker" >&2
          exit 1
        fi
        sleep 1
      done
      if test "$ready" != 1; then
        cat "$log" >&2
        echo "checkpoint VM did not reach its readiness marker" >&2
        exit 1
      fi
      stop_qemu
    }

    # Exercise the boot path used by a legacy PC after the hybrid image is
    # written directly to a USB drive.
    bios_log="$out/bios-serial.log"
    qemu-system-x86_64 \
      -enable-kvm \
      -machine pc,accel=kvm \
      -cpu host \
      -smp 2 \
      -m 3072 \
      -display none \
      -no-reboot \
      -serial "file:$bios_log" \
      -netdev user,id=network \
      -device virtio-net-pci,netdev=network \
      -drive "if=ide,format=raw,readonly=on,file=$iso" \
      -boot order=c \
      > "$out/bios-qemu.log" 2>&1 &
    qemu_pid=$!
    wait_for_ready "$bios_log"

    # Exercise the Intel Mac path with UEFI firmware and the same image exposed
    # as USB mass storage. The copied variables image is private to this boot.
    cp ${ovmf.variables} ovmf-vars.fd
    chmod u+w ovmf-vars.fd
    uefi_log="$out/uefi-serial.log"
    qemu-system-x86_64 \
      -enable-kvm \
      -machine q35,accel=kvm \
      -cpu host \
      -smp 2 \
      -m 3072 \
      -display none \
      -no-reboot \
      -serial "file:$uefi_log" \
      -drive "if=pflash,format=raw,unit=0,readonly=on,file=${ovmf.firmware}" \
      -drive "if=pflash,format=raw,unit=1,file=$PWD/ovmf-vars.fd" \
      -netdev user,id=network \
      -device virtio-net-pci,netdev=network \
      -device qemu-xhci,id=xhci \
      -drive "if=none,format=raw,readonly=on,file=$iso,id=checkpoint" \
      -device usb-storage,drive=checkpoint,bootindex=1 \
      > "$out/uefi-qemu.log" 2>&1 &
    qemu_pid=$!
    wait_for_ready "$uefi_log"

    printf '%s\n' ${pkgs.lib.escapeShellArg marker} > "$out/passed"
  ''
