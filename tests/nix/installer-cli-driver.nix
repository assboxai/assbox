# SPDX-License-Identifier: GPL-3.0-or-later
# Authoritative callers load this expression from a frozen oracle, with candidate
# product source as data. Building .driver does not execute its testScript.
{
  candidateSource,
  candidateRevision,
  candidateContent,
  system ? builtins.currentSystem,
}:
let
  candidate = builtins.getFlake ("git+file://${candidateSource}?rev=${candidateRevision}");
  pkgs = candidate.inputs.nixpkgs.legacyPackages.${system};
  lib = pkgs.lib;
  arm = system == "aarch64-linux";
  assbox = candidate.packages.${system}.assbox;
  module = candidate.nixosModules.default;
  tools = import ../../nix/tool-environment.nix { inherit pkgs; };
  ca = ../fixtures/mirror-cert.crt;
  mirror = import ./source-mirror.nix {
    inherit pkgs;
    inputs = candidate.inputs;
  };
  adapters = pkgs.runCommand "assbox-canonical-external-fixtures" { } ''
    mkdir -p "$out/bin"
    for tool in curl gh timedatectl systemd-ask-password; do
      cat > "$out/bin/$tool" <<EOF
    #!${pkgs.runtimeShell}
    exec ${pkgs.python3}/bin/python3 ${../fixtures/installer_cli_transport.py} $tool "\$@"
    EOF
      chmod +x "$out/bin/$tool"
    done
  '';
  cli = pkgs.rustPlatform.buildRustPackage {
    pname = "assbox-canonical-installer-cli";
    inherit (assbox) version src;
    cargoLock.lockFile = "${candidate.outPath}/Cargo.lock";
    cargoBuildFlags = [
      "-p"
      "assbox-cli"
    ];
    # Ordinary CLI compilation, with only these external boundary substitutions.
    ASSBOX_TOOL_PATH = "${adapters}/bin:${tools.path}";
    ASSBOX_NIX_LIB = "${pkgs.path}/lib";
    ASSBOX_SOURCE_REVISION = candidateRevision;
    ASSBOX_REPOSITORY_ID = "123";
    ASSBOX_OWNER_ID = "456";
    ASSBOX_CA_BUNDLE = ca;
    doCheck = false;
  };
  seed = candidate.inputs.nixpkgs.lib.nixosSystem {
    inherit system;
    modules = [
      module
      ./fixture.nix
      {
        assbox.components = { };
        assbox.network.tailscale.enable = false;
        assbox.presentation = "headless";
        networking.hostName = lib.mkForce "assbox-repair-vm";
        time.timeZone = lib.mkForce "UTC";
      }
    ];
  };
  buildTools =
    with pkgs;
    [
      stdenv
      stdenvNoCC
      bintools
      brotli.dev
      brotli.lib
      desktop-file-utils
      docbook5
      docbook_xsl_ns
      kbd.dev
      kmod.dev
      libarchive.dev
      libxml2.bin
      libxslt.bin
      perlPackages.ConfigIniFiles
      perlPackages.FileSlurp
      perlPackages.JSON
      perlPackages.ListCompare
      perlPackages.XMLLibXML
      (python3.withPackages (p: [ p.mistune ]))
      shared-mime-info
      sudo
      switch-to-configuration-ng
      texinfo
      unionfs-fuse
      lndir
      shellcheck-minimal
      systemdMinimal.out
      cargo
      rustc
      rustPlatform.cargoSetupHook
      nixos-rebuild-ng
    ]
    ++ lib.optionals (!arm) [
      pkgs.grub2
      pkgs.grub2_efi
    ];
  dependencies = pkgs.closureInfo {
    rootPaths = [
      seed.config.system.build.toplevel
      seed.config.system.build.toplevel.drvPath
      assbox
      assbox.drvPath
      assbox.cargoDeps
      seed.config.boot.kernelPackages.kernel.out
      seed.config.boot.kernelPackages.kernel.modules
      seed.config.boot.kernelPackages.kernel.dev
    ]
    ++ buildTools;
  };
  iso =
    pkgs.runCommand "assbox-canonical-optical.iso"
      {
        nativeBuildInputs = [ pkgs.xorriso ];
      }
      ''
        mkdir contents
        echo disposable > contents/fixture
        xorriso -as mkisofs -quiet -o "$out" contents
      '';
  instrumentation = pkgs.writeText "assbox-canonical-local.nix" ''
    { lib, modulesPath, ... }: {
      imports = [ (modulesPath + "/testing/test-instrumentation.nix") ];
      users.users.root.hashedPasswordFile = lib.mkForce null;
      networking.useDHCP = lib.mkForce false;
      networking.interfaces.eth1.ipv4.addresses = lib.mkForce [{ address = "192.168.1.3"; prefixLength = 24; }];
      networking.hosts."192.168.1.1" = [ "github.com" "api.github.com" ];
      # This module is copied into a new flake. Embed the same public test CA
      # instead of introducing an absolute path outside that flake's inputs.
      ${import ./fixture-certificate.nix { certificate = ca; }}
      nix.settings.trusted-public-keys = lib.mkAfter [ ${builtins.toJSON (import ./fixture-cache-public-key.nix)} ];
      nix.settings.substituters = lib.mkForce [];
      nix.settings.builders = lib.mkForce "";
      systemd.timers.assbox-maintenance.enable = lib.mkForce false;
      systemd.timers.assbox-reboot-retry.enable = lib.mkForce false;
      environment.etc."assbox-canonical-vm".text = "disposable\n";
    }
  '';
  common = { lib, ... }: {
    virtualisation.memorySize = 3072;
    virtualisation.restrictNetwork = true;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    virtualisation.qemu.options = lib.optionals arm [ "-cpu max,lpa2=off" ];
    # No default route to the host LAN, metadata or public network. eth1 is the
    # driver's private virtual switch; source acquisition uses the exact mirror.
    networking.useDHCP = lib.mkForce false;
    networking.defaultGateway = lib.mkForce null;
    networking.defaultGateway6 = lib.mkForce null;
    system.stateVersion = "26.05";
  };
  test = pkgs.testers.runNixOSTest {
    name = "assbox-canonical-interactive-install";
    globalTimeout = 10800;
    node.pkgsReadOnly = false;
    requiredFeatures.kvm = !arm;
    nodes = {
      server = { ... }: {
        imports = [ common ];
        networking.interfaces.eth1.ipv4.addresses = lib.mkForce [
          {
            address = "192.168.1.1";
            prefixLength = 24;
          }
        ];
        networking.firewall.allowedTCPPorts = [ 443 ];
        environment.systemPackages = [
          pkgs.python3
          pkgs.nix
          pkgs.openssh
        ];
        nix.settings.experimental-features = [
          "nix-command"
          "flakes"
        ];
        systemd.services.source-mirror.serviceConfig.ExecStart =
          "${pkgs.python3}/bin/python3 ${../fixtures/source_server.py} ${mirror} ${ca} ${../fixtures/mirror-test.key}";
        virtualisation.additionalPaths = [ assbox.src ];
      };
      installer = { lib, ... }: {
        imports = [
          common
          ./fixture-store-compression.nix
          (import ./fixture-cache-signing.nix {
            inherit pkgs;
            roots = [
              cli
              dependencies
            ];
          })
        ];
        networking.interfaces.eth1.ipv4.addresses = lib.mkForce [
          {
            address = "192.168.1.2";
            prefixLength = 24;
          }
        ];
        networking.hosts."192.168.1.1" = [
          "github.com"
          "api.github.com"
        ];
        security.pki.certificateFiles = [ ca ];
        environment.systemPackages = [
          cli
          pkgs.python3
          pkgs.jq
          pkgs.nix
          pkgs.openssh
          pkgs.util-linux
          pkgs.e2fsprogs
          pkgs.dosfstools
          pkgs.nixos-install-tools
        ];
        nix.settings = {
          experimental-features = [
            "nix-command"
            "flakes"
          ];
          substituters = lib.mkForce [ ];
          builders = lib.mkForce "";
        };
        # Read the offline closure from a block-backed image instead of 9p.
        virtualisation.useNixStoreImage = true;
        virtualisation.writableStore = true;
        # The optical fixture is attached through a modular virtio SCSI driver.
        boot.kernelModules = [
          "virtio_scsi"
          "sr_mod"
        ];
        virtualisation.diskSize = 65536;
        virtualisation.useEFIBoot = true;
        # QEMU's EFI firmware boots the supplied kernel/initrd; constructing a
        # bootloader image with make-disk-image would itself launch a build VM.
        virtualisation.useBootLoader = false;
        virtualisation.efi.keepVariables = false;
        boot.loader.systemd-boot.enable = lib.mkForce false;
        boot.loader.grub.enable = lib.mkForce false;
        virtualisation.qemu.options = [
          "-drive file=\"$SHARED_DIR/assbox-target.qcow2\",if=none,id=assbox-target,format=qcow2"
          "-device virtio-blk-pci,drive=assbox-target,serial=assbox-repair-target,logical_block_size=512,physical_block_size=512"
          "-drive file=\"$SHARED_DIR/assbox-backup.qcow2\",if=none,id=assbox-backup,format=qcow2"
          "-device virtio-blk-pci,drive=assbox-backup,serial=assbox-repair-backup"
          "-device virtio-scsi-pci,id=assbox-scsi"
          "-drive if=none,id=assbox-iso,media=cdrom,readonly=on,format=raw,file=${iso}"
          "-device scsi-cd,bus=assbox-scsi.0,drive=assbox-iso"
        ];
        virtualisation.additionalPaths = [
          cli
          dependencies
          pkgs.path
          instrumentation
          ca
        ];
      };
      target = { lib, ... }: {
        imports = [ common ];
        virtualisation.diskImage = "$SHARED_DIR/assbox-target.qcow2";
        virtualisation.useBootLoader = true;
        virtualisation.useEFIBoot = true;
        virtualisation.useDefaultFilesystems = false;
        virtualisation.efi.keepVariables = false;
        virtualisation.qemu.drives = lib.mkForce [
          {
            name = "root";
            file = "\"$NIX_DISK_IMAGE\"";
            deviceExtraOpts = {
              serial = "assbox-repair-target";
              bootindex = "1";
            };
          }
        ];
        virtualisation.fileSystems."/" = {
          device = "/dev/vda";
          fsType = "ext4";
        };
        boot.loader.grub.enable = lib.mkForce false;
      };
    };
    testScript = ''
      from pathlib import Path
      cli = "${cli}/bin/assbox"
      production_cli = "${assbox}/bin/assbox"
      source = "${assbox.src}"
      dependencies = "${dependencies}"
      instrumentation = "${instrumentation}"
      revision = ${builtins.toJSON candidateRevision}
      content_digest = ${builtins.toJSON candidateContent}
      release_script = "${../fixtures/installer_cli_release.py}"
      terminal_script = "${../fixtures/installer_cli_terminal.py}"
      qemu_img = "${pkgs.qemu}/bin/qemu-img"
      case_script = "${../fixtures/installer_cli_cases.py}"
      exec(compile(Path(case_script).read_text(), case_script, "exec"))
    '';
  };
in
test.driver
