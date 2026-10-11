# SPDX-License-Identifier: GPL-3.0-or-later
# Hybrid x86 live media for physical development qualification.
# It deliberately has no local-source installation bypass and is not a stable
# release trust root. The production installer remains release-authenticated.
{
  assboxCodex,
  assboxCheckpointSystemd,
  assboxHappier,
  assboxPackage,
  config,
  lib,
  modulesPath,
  pkgs,
  sourceRevision,
  ...
}:
let
  revision = if sourceRevision == "" then "uncommitted" else sourceRevision;
  checkpointDbus = pkgs.dbus.override { x11Support = false; };
  checkpointHwdb = pkgs.runCommand "assbox-checkpoint-hwdb.bin" { } ''
    mkdir -p root/etc/udev/hwdb.d
    cp ${assboxCheckpointSystemd}/lib/udev/hwdb.d/* root/etc/udev/hwdb.d/
    ${assboxCheckpointSystemd}/bin/systemd-hwdb --root="$PWD/root" update
    cp root/etc/udev/hwdb.bin "$out"
  '';
  readiness = pkgs.writeShellScript "assbox-physical-checkpoint-readiness" ''
    set -eu
    fail() {
      echo "Assbox physical checkpoint failed: $*" >&2
      exit 1
    }

    test "${revision}" != uncommitted || fail "source revision is not embedded"
    ${assboxCheckpointSystemd}/bin/systemctl is-active --quiet assbox-device-policy-check.service \
      || fail "disabled-device boot gate is not active"
    ${pkgs.gnugrep}/bin/grep -q 'module_blacklist=.*cfg80211.*snd' /proc/cmdline \
      || fail "early radio/sound module denial is absent"
    ${pkgs.gnugrep}/bin/grep -qw 'rfkill.default_state=0' /proc/cmdline \
      || fail "default radio block is absent"

    wired=0
    wired_carrier=0
    for interface in /sys/class/net/*; do
      test -e "$interface" || continue
      name=''${interface##*/}
      test "$name" != lo || continue
      test ! -d "$interface/wireless" \
        || fail "wireless interface initialized: $name"
      test "$(cat "$interface/type")" != 801 \
        || fail "wireless interface initialized: $name"
      if test "$(cat "$interface/type")" = 1; then
        wired=1
        if test -r "$interface/carrier" \
          && test "$(cat "$interface/carrier")" = 1; then
          wired_carrier=1
        fi
      fi
    done
    test "$wired" = 1 || fail "no wired Ethernet interface initialized"
    test "$wired_carrier" = 1 || fail "no wired Ethernet link has carrier"

    for radio in /sys/class/rfkill/rfkill*; do
      test -e "$radio" || continue
      if test "$(cat "$radio/soft")" != 1 \
        && test "$(cat "$radio/hard")" != 1; then
        fail "radio is not blocked: $radio"
      fi
    done
    for device in \
      /sys/class/bluetooth/* \
      /sys/class/ieee802154/* \
      /sys/class/nfc/* \
      /sys/class/uwb/* \
      /sys/class/wwan/* \
      /sys/class/sound/* \
      /dev/snd/* \
      /sys/class/video4linux/*; do
      test ! -e "$device" || fail "disabled device initialized: $device"
    done

    test -x ${assboxPackage}/bin/assbox || fail "Assbox CLI is absent"
    test -x ${assboxCodex}/bin/codex || fail "Codex is absent"
    test -x ${assboxHappier}/bin/happier || fail "Happier is absent"

    ${pkgs.coreutils}/bin/install -d -m 0755 /run/assbox-checkpoint
    ${pkgs.jq}/bin/jq -cn \
      --arg sourceRevision ${lib.escapeShellArg revision} \
      --arg system ${lib.escapeShellArg pkgs.stdenv.hostPlatform.system} \
      '{schema:1,kind:"assbox-physical-checkpoint-readiness",sourceRevision:$sourceRevision,system:$system,devices:{wifi:false,bluetooth:false,audio:false,camera:false},wiredInterfacePresent:true,wiredCarrierPresent:true,passed:true}' \
      > /run/assbox-checkpoint/readiness.json
    chmod 0444 /run/assbox-checkpoint/readiness.json
    message="ASSBOX_PHYSICAL_CHECKPOINT_READY ${revision}"
    echo "$message"
    if test -c /dev/ttyS0; then
      printf '%s\n' "$message" \
        | ${pkgs.coreutils}/bin/timeout 2 ${pkgs.coreutils}/bin/tee /dev/ttyS0 \
          > /dev/null \
        || true
    fi
  '';
in
{
  _module.args.assboxDevicePolicyNetworkUnit = "systemd-networkd.service";

  imports = [
    (modulesPath + "/installer/cd-dvd/iso-image.nix")
    (modulesPath + "/profiles/minimal.nix")
    ../modules/options.nix
    ../modules/security-overrides.nix
    ../modules/devices.nix
  ];

  assertions = [
    {
      assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
      message = "The physical checkpoint image currently supports x86-64 only.";
    }
    {
      assertion = sourceRevision != "";
      message = "The physical checkpoint image requires a committed source revision.";
    }
  ];

  assbox = {
    enable = true;
    presentation = "headless";
    updates.enable = false;
    devices = {
      wifi.enable = false;
      bluetooth.enable = false;
      audio.enable = false;
      camera.enable = false;
    };
    power.suspend.enable = false;
  };

  networking.hostName = "assbox-checkpoint";
  # This read-only image cannot install, rebuild or update a system. Omitting
  # the Nix daemon keeps the production package manager and its build/test
  # toolchain out of the checkpoint closure.
  nix.enable = false;
  system.switch.enable = false;
  systemd.package = assboxCheckpointSystemd;
  # Keep the NixOS coredump module aligned with the reduced systemd package.
  # Otherwise it tries to install an example sysctl file that is absent when
  # systemd-coredump is compiled out. A live auth session must not retain
  # process memory after a crash in any case.
  systemd.coredump.enable = false;
  # The upstream installer ISO populates a temporary Nix database so its
  # nixos-install tooling can run. This checkpoint carries no package manager
  # or installer, so the registration service would retain Nix for no use.
  systemd.services.register-nix-paths.enable = lib.mkForce false;
  networking.modemmanager.enable = false;
  networking.networkmanager.enable = false;
  networking.useDHCP = false;
  networking.useNetworkd = true;
  networking.wireless.enable = lib.mkForce false;
  systemd.network = {
    enable = true;
    networks."20-wired-dhcp" = {
      matchConfig.Type = "ether";
      networkConfig.DHCP = "yes";
      linkConfig.RequiredForOnline = "routable";
    };
    wait-online = {
      enable = true;
      anyInterface = true;
      timeout = 60;
    };
  };
  services.openssh.enable = lib.mkForce false;
  services.dbus.implementation = "dbus";
  services.dbus.dbusPackage = checkpointDbus;
  fonts.fontconfig.enable = false;
  # NixOS's generic hwdb builder uses the full build-platform systemd even
  # when the running system selects a narrower package. Build the same base
  # hardware database with the checkpoint systemd so its disabled BPF/TPM
  # toolchains do not return through a native build-only edge.
  environment.etc."udev/hwdb.bin".source = lib.mkForce checkpointHwdb;

  # Load the generic input, storage and wired-network driver set so one image
  # can qualify both old BIOS hardware and the Intel Mac EFI path. Device
  # policy still denies radio, sound and camera modules before udev can bind
  # them.
  hardware.enableAllHardware = true;

  # The upstream minimal installation image is intentionally a broad recovery
  # and installation environment. This checkpoint is neither: keep only the
  # filesystems required to boot the read-only hybrid image. In particular,
  # avoid compiling or loading the out-of-tree ZFS module and do not carry
  # drivers for mounting internal installation targets.
  boot.supportedFilesystems = lib.mkForce [
    "iso9660"
    "overlay"
    "squashfs"
    "tmpfs"
    "vfat"
  ];
  services.lvm.enable = false;
  boot.initrd.services.lvm.enable = false;
  boot.bcache.enable = false;
  boot.initrd.services.bcache.enable = false;
  boot.swraid.enable = false;
  # The generic ISO module enables an initrd rescue shell for installation
  # media. This checkpoint has no privileged recovery role; fail the boot
  # instead of exposing authority before the locked root account takes effect.
  boot.initrd.systemd.enable = lib.mkForce true;
  boot.initrd.systemd.emergencyAccess = lib.mkForce false;

  # Expose only an unprivileged local console identity and make the root
  # account unusable. Wired DHCP requires no interactive NetworkManager
  # privilege.
  users.mutableUsers = false;
  users.allowNoPasswordLogin = true;
  users.groups.agent = { };
  users.users = {
    agent = {
      isNormalUser = true;
      group = "agent";
      hashedPassword = "";
    };
    root.hashedPassword = lib.mkForce "!";
  };
  services.getty.autologinUser = lib.mkForce "agent";
  security.sudo.enable = lib.mkForce false;
  security.polkit.enable = lib.mkForce false;
  security.pam.services.su.forwardXAuth = lib.mkForce false;

  # Keep both firmware paths in one byte-identical image. The USB hybrid MBR is
  # what the legacy PC uses; the EFI image is what the Intel Mac uses.
  isoImage = {
    edition = lib.mkForce "assbox-checkpoint";
    volumeID = "ASSBOX_CHECKPOINT";
    makeBiosBootable = true;
    makeEfiBootable = true;
    makeUsbBootable = true;
    squashfsCompression = "zstd -Xcompression-level 6";
  };
  image.baseName = lib.mkForce "assbox-checkpoint-${lib.substring 0 12 revision}-x86_64-linux";

  # Replace the installer ISO's partitioning, recovery, server and installation
  # payload with the bounded console tools needed by this live coding image.
  environment.systemPackages = lib.mkForce [
    assboxPackage
    assboxCodex
    assboxHappier
    pkgs.bashInteractive
    pkgs.coreutils
    pkgs.curl
    pkgs.file
    pkgs.findutils
    pkgs.gawk
    pkgs.git
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gnutar
    pkgs.gzip
    pkgs.iproute2
    pkgs.jq
    pkgs.kmod
    pkgs.less
    pkgs.openssh
    pkgs.assboxPatchedPatch
    pkgs.pciutils
    pkgs.procps
    pkgs.ripgrep
    pkgs.tmux
    pkgs.unzip
    pkgs.util-linux
    pkgs.usbutils
    pkgs.which
    pkgs.xz
    pkgs.zip
    pkgs.zstd
  ];
  environment.etc."assbox/checkpoint.json".text = builtins.toJSON {
    schema = 1;
    kind = "assbox-physical-checkpoint";
    sourceRevision = revision;
    system = pkgs.stdenv.hostPlatform.system;
    assboxMode = "diagnostic-only";
    installationQualified = false;
    updatesQualified = false;
    devices = {
      wifi = false;
      bluetooth = false;
      audio = false;
      camera = false;
    };
  };
  environment.etc."motd".text = lib.mkForce ''
    Assbox physical development checkpoint ${revision}

    Wired Ethernet only. Wireless, Bluetooth, sound/microphones and cameras are
    denied before networking. Inspect /run/assbox-checkpoint/readiness.json.
    The console agent has no sudo or administrative device authority. This live
    image is not an installation-qualified stable release.
  '';
  services.getty.helpLine = lib.mkAfter ''

    Assbox includes Codex and Happier for ephemeral live testing. Its CLI has
    diagnostic tools only; install and update commands are not qualified. Run
    `systemctl status assbox-physical-checkpoint-readiness` before authentication.
  '';

  # Preserve a serial evidence channel for the automated BIOS/UEFI boot smoke
  # test while keeping the local display as the primary physical console.
  boot.kernelParams = [
    "console=ttyS0,115200n8"
    "console=tty0"
  ];
  # The live root is tmpfs over the read-only ISO store. Never force-import an
  # internal ZFS pool while this no-disk-write checkpoint is booting.
  boot.zfs.forceImportRoot = false;
  systemd.services.assbox-physical-checkpoint-readiness = {
    description = "Verify the Assbox physical checkpoint boundary";
    requiredBy = [ "multi-user.target" ];
    before = [ "multi-user.target" ];
    after = [
      "assbox-device-policy-check.service"
      "network-online.target"
      "systemd-networkd.service"
    ];
    wants = [ "network-online.target" ];
    requires = [ "assbox-device-policy-check.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = readiness;
    };
  };

  system.stateVersion = "26.05";
}
