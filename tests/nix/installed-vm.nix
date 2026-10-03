# SPDX-License-Identifier: GPL-3.0-or-later
# Installs real source onto a separate disk, then boots that disk. No fake Nix,
# filesystem or bootloader commands. Network evidence remains test-only.
{
  pkgs,
  module,
  assbox,
  inputs,
  mode,
  scenario,
  sectorSize ? 512,
}:
let
  lib = pkgs.lib;
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  efi = builtins.elem mode [
    "uefi"
    "apple-refind"
  ];
  apple = mode == "apple-refind";
  ca = ../fixtures/mirror-cert.crt;
  harness = import ./acceptance-harness.nix {
    inherit pkgs assbox;
    testCa = ca;
  };
  mirror = import ./source-mirror.nix { inherit pkgs inputs; };
  keys = pkgs.runCommand "assbox-disposable-ssh-key" { nativeBuildInputs = [ pkgs.openssh ]; } ''
    mkdir "$out"
    ssh-keygen -q -t ed25519 -N "" -C disposable-vm -f "$out/key"
  '';
  local = pkgs.writeText "assbox-acceptance-local.nix" ''
    { lib, pkgs, modulesPath, ... }: {
      imports = [ (modulesPath + "/testing/test-instrumentation.nix") ];
      # Test instrumentation normally unlocks root; preserve Assbox's locked root.
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
      assbox.network.tailscale.enable = lib.mkForce false;
      assbox.network.ssh.exposure = "lan";
      assbox.network.ssh.lanInterfaces = [ "eth1" ];
      assbox.updates = { enable = false; rebootGraceSeconds = 0; keepGenerations = 2; };
      # Tests invoke maintenance deliberately; calendar firing would race cuts.
      systemd.timers.assbox-maintenance.enable = lib.mkForce false;
      systemd.timers.assbox-reboot-retry.enable = lib.mkForce false;
      environment.etc."assbox-acceptance-vm" = { text = "disposable\n"; mode = "0600"; };
      # Test instrumentation is isolated in the disposable machine-local module.
      # Actual appliance accounts, SSH policy and bootloader are not replaced.
    }
  '';
  seed = inputs.nixpkgs.lib.nixosSystem {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      module
      ./fixture.nix
      {
        assbox = {
          enable = true;
          components = { };
          presentation = "headless";
          boot.mode = mode;
          platform = if apple then "macbookpro12-1" else "generic";
        };
        environment.systemPackages = [ pkgs.hello ];
      }
    ];
  };
  # Runtime builds may need build inputs absent from the output closure. Include
  # the derivation closure too, using Nix's own dependency graph.
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
      hello
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
  iso = pkgs.runCommand "assbox-live-observation.iso" { nativeBuildInputs = [ pkgs.xorriso ]; } ''
    mkdir contents
    echo disposable > contents/fixture
    xorriso -as mkisofs -quiet -o "$out" contents
  '';
  common = { lib, ... }: {
    virtualisation.memorySize = 3072;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    virtualisation.qemu.options = lib.optionals arm [ "-cpu max,lpa2=off" ];
    system.stateVersion = "26.05";
  };
in
pkgs.testers.runNixOSTest {
  name = "assbox-${scenario}-${mode}-${toString sectorSize}";
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
      systemd.services.source-mirror = {
        serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 ${../fixtures/source_server.py} ${mirror} ${ca} ${../fixtures/mirror-test.key}";
      };
      virtualisation.additionalPaths = [
        assbox.src
        keys
      ];
    };
    installer = { lib, ... }: {
      imports = [
        common
        (import ./fixture-cache-signing.nix {
          inherit pkgs;
          roots = [
            harness
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
      # Trusted-file reads in the harness reject the default /etc symlinks.
      environment.etc."assbox-acceptance-vm" = {
        text = "disposable\n";
        mode = "0600";
      };
      environment.etc."assbox-acceptance-local.nix" = {
        source = local;
        mode = "0600";
      };
      environment.systemPackages =
        with pkgs;
        [
          nix
          python3
          jq
          openssh
          e2fsprogs
          dosfstools
          exfatprogs
          gptfdisk
          util-linux
        ]
        ++ lib.optionals apple [ pkgs.refind ];
      nix.settings = {
        experimental-features = [
          "nix-command"
          "flakes"
        ];
        substituters = lib.mkForce [ ];
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
      virtualisation.emptyDiskImages = [ 2048 ]; # Independent backup disk.
      virtualisation.useEFIBoot = efi;
      # Direct kernel boot through the EFI firmware keeps real firmware
      # observation without baking the complete offline build closure into an
      # installer image. The produced target still boots its real bootloader.
      virtualisation.useBootLoader = false;
      virtualisation.efi.keepVariables = false;
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      virtualisation.qemu.options =
        lib.optionals apple [
          # Exercise the production DMI observation, not a test-only bypass. QEMU
          # escapes a comma within a key=value argument by doubling it.
          "-smbios type=1,manufacturer=Apple,product=MacBookPro12,,1"
        ]
        ++ [
          "-drive file=\"$SHARED_DIR/assbox-target.qcow2\",if=none,id=assbox-target,format=qcow2"
          "-device virtio-blk-pci,drive=assbox-target,serial=assbox-target,logical_block_size=${toString sectorSize},physical_block_size=${toString sectorSize}"
          "-device virtio-scsi-pci,id=assbox-scsi"
          "-drive if=none,id=assbox-iso,media=cdrom,readonly=on,format=raw,file=${iso}"
          "-device scsi-cd,bus=assbox-scsi.0,drive=assbox-iso"
        ];
      virtualisation.additionalPaths = [
        harness
        keys
        dependencies
        pkgs.path
        local
        ca
      ];
    };
    target = { lib, ... }: {
      imports = [ common ];
      # QEMU boots the produced disk; this node's skeleton is never installed.
      virtualisation.diskImage = "$SHARED_DIR/assbox-target.qcow2";
      virtualisation.useBootLoader = true;
      virtualisation.useEFIBoot = efi;
      virtualisation.useDefaultFilesystems = false;
      virtualisation.efi.keepVariables = false;
      virtualisation.qemu.drives = lib.mkForce [
        {
          name = "root";
          file = "\"$NIX_DISK_IMAGE\"";
          deviceExtraOpts = {
            serial = "assbox-target";
            bootindex = "1";
            logical_block_size = toString sectorSize;
            physical_block_size = toString sectorSize;
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
    import subprocess
    from pathlib import Path
    mode = ${builtins.toJSON mode}
    sector_size = ${toString sectorSize}
    scenario = ${builtins.toJSON scenario}
    harness = "${harness}/libexec/assbox-acceptance"
    dependencies = "${dependencies}"
    key = "${keys}/key.pub"
    private_key = "${keys}/key"
    source = "${assbox.src}"
    activation_script = "${../fixtures/activation_cases.py}"
    release_script = "${../fixtures/install_release.py}"
    terminal_script = "${../fixtures/installer_terminal.py}"
    test_ca = "${ca}"
    refind = "${if apple then "${pkgs.refind}/share/refind/refind_x64.efi" else ""}"
    qemu_img = "${pkgs.qemu}/bin/qemu-img"
    target_image = str(installer.shared_dir / "assbox-target.qcow2")
    subprocess.run([qemu_img, "create", "-f", "qcow2", target_image, "64G"], check=True)
    case_script = "${../fixtures/installed_cases.py}"
    exec(compile(Path(case_script).read_text(), case_script, "exec"))
  '';
}
