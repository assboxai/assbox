# SPDX-License-Identifier: GPL-3.0-or-later
# Stream the complete offline closure into a real compressed SquashFS image.
# EROFS tar compression first stages all raw data; that peak exceeds hosted-runner
# storage. The pinned QEMU module still calls its mkfs.erofs interface, so the
# explicit fixture adapter accepts only that exact invocation. Guest mounts and
# the store drive below declare the actual filesystem and device identity.
# The pinned tar producer and formatter share the exact closure manifest so
# guest restarts can attach the same completed read-only image.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  serial = "assbox-offline-store";
  registration = pkgs.closureInfo { rootPaths = config.virtualisation.additionalPaths; };
  closure = pkgs.closureInfo {
    rootPaths = [
      config.system.build.toplevel
      registration
    ];
  };
  imageTools = pkgs.runCommand "assbox-fixture-squashfs-image-tools" { } ''
    mkdir -p "$out/bin"
    cat > "$out/bin/mkfs.erofs" <<'EOF'
    #!${pkgs.runtimeShell}
    exec ${pkgs.python3}/bin/python3 -I -B ${../fixtures/store_image.py} image ${closure}/store-paths ${pkgs.squashfsTools}/bin/mksquashfs "$@"
    EOF
    cat > "$out/bin/tar" <<'EOF'
    #!${pkgs.runtimeShell}
    exec ${pkgs.python3}/bin/python3 -I -B ${../fixtures/store_image.py} tar ${closure}/store-paths ${pkgs.gnutar}/bin/tar "$@"
    EOF
    chmod +x "$out/bin/mkfs.erofs" "$out/bin/tar"
  '';
in
{
  options.virtualisation.qemu.drives = lib.mkOption {
    apply = map (
      drive:
      if drive.name == "nix-store" then
        drive
        // {
          deviceExtraOpts = drive.deviceExtraOpts // {
            inherit serial;
          };
          driveExtraOpts = drive.driveExtraOpts // {
            readonly = "on";
          };
        }
      else
        drive
    );
  };
  config = {
    virtualisation.host.pkgs = lib.mkForce (
      pkgs
      // {
        erofs-utils = imageTools;
        gnutar = imageTools;
      }
    );
    virtualisation.fileSystems."/nix/.ro-store" = {
      device = lib.mkForce "/dev/disk/by-id/virtio-${serial}";
      fsType = lib.mkForce "squashfs";
    };
    boot.initrd.availableKernelModules = [ "squashfs" ];
  };
}
