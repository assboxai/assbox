{
  source,
  revision,
  system,
  useKvm ? system == "x86_64-linux",
  recoveryPath ? null,
  recoveryHash ? null,
}:
let
  product = builtins.getFlake "git+file://${source}?rev=${revision}";
  efi = system == "aarch64-linux";
  profileName = system + (if efi then "-uefi-none-headless" else "-bios-gpt-none");
  base = product.nixosConfigurations.${profileName};
  pkgs = product.inputs.nixpkgs.legacyPackages.${system};
  inherit (pkgs) lib;
  ids = [
    "antigravity-cli"
    "claude-code"
    "codex"
    "cursor-agent"
    "grok"
    "omp"
    "opencode"
    "pi"
  ];
  catalog = builtins.fromJSON (builtins.readFile (product.outPath + "/catalog/components.json"));
  serial = "assbox-cli-target";
  disk = "/dev/disk/by-id/virtio-${serial}";
  profile = base.extendModules {
    modules = [
      ({ lib, modulesPath, ... }: {
        imports = [ (modulesPath + "/testing/test-instrumentation.nix") ];
        # The isolated test console and unprivileged test account provide instrumentation.
        users.users.root.hashedPasswordFile = lib.mkForce null;
        users.users.headless-probe = {
          isNormalUser = true;
          uid = 1234;
        };
        networking.useDHCP = lib.mkForce false;
        assbox = {
          acceptUnfree = true;
          components = lib.genAttrs ids (_: {
            enable = true;
          });
          computerUse.mode = "none";
          boot.disk = lib.mkForce disk;
        };
      })
    ];
  };
  config = profile.config;
  expected = lib.genAttrs ids (id: {
    inherit (lib.findFirst (row: row.id == id) (throw "Missing CLI catalog entry") catalog) command;
    output = builtins.head config.assbox.componentPackagePaths.${id};
  });
  actual = config.system.build.toplevel;
  recoveryDisk = if recoveryPath == null then null else builtins.path {
    path = builtins.toPath recoveryPath;
    name = "curated-headless-verified-prior-target.qcow2";
    recursive = false;
    sha256 = recoveryHash;
  };
  expectedProfile = {
    source = product.rev;
    inherit system;
    mode = config.assbox.computerUse.mode;
    presentation = config.assbox.presentation;
    workerEnabled = config.assbox.worker.enable;
    displayServerEnabled = config.services.xserver.enable;
    displayManagerEnabled = config.services.displayManager.enable;
    boot = config.assbox.boot.mode;
    configuredDefaultUnit = config.systemd.defaultUnit;
    inherit expected;
  };
  test = pkgs.testers.runNixOSTest {
    name = "assbox-current-installed-curated-headless";
    globalTimeout = if efi && !useKvm then 5400 else 3600;
    requiredFeatures.kvm = useKvm;
    nodes.installer = {
      imports = [ (product.outPath + "/tests/nix/fixture-store-image.nix") ];
      virtualisation = {
        useNixStoreImage = true;
        writableStore = true;
        memorySize = 3072;
        cores = 2;
        qemu.forceAccel = lib.mkForce useKvm;
        additionalPaths = [ actual ];
        useEFIBoot = efi;
        useBootLoader = false;
        efi.keepVariables = false;
        qemu.options = [
          "-drive file=\"$SHARED_DIR/curated-target.qcow2\",if=none,id=curated-target,format=qcow2"
          "-device virtio-blk-pci,drive=curated-target,serial=${serial}"
        ];
      };
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      boot.kernelModules = lib.optionals efi [ "vfat" "nls_cp437" "nls_iso8859-1" ];
      environment.systemPackages = [
        pkgs.e2fsprogs
        pkgs.gptfdisk
        pkgs.dosfstools
      ];
      nix.settings.substituters = lib.mkForce [ ];
      system.stateVersion = "26.05";
    };
    nodes.target = {
      virtualisation = {
        memorySize = 8192;
        cores = 2;
        qemu.forceAccel = lib.mkForce useKvm;
        diskImage = "$SHARED_DIR/curated-target.qcow2";
        useBootLoader = true;
        useEFIBoot = efi;
        efi.keepVariables = false;
        useDefaultFilesystems = false;
        fileSystems."/" = {
          device = "/dev/vda";
          fsType = "ext4";
        };
        qemu.drives = lib.mkForce [
          {
            name = "root";
            file = "\"$NIX_DISK_IMAGE\"";
            deviceExtraOpts = {
              inherit serial;
              bootindex = "1";
            };
          }
        ];
      };
      boot.loader.grub.enable = lib.mkForce false;
      system.stateVersion = "26.05";
    };
    testScript = ''
      import json
      from pathlib import Path

      installed = "${actual}"
      disk = "${disk}"
      qemu_img = "${pkgs.qemu}/bin/qemu-img"
      expected = json.loads(${builtins.toJSON (builtins.toJSON expectedProfile)})
      recovery = ${if recoveryDisk == null then "None" else builtins.toJSON (toString recoveryDisk)}
      scenario = "${./run-current-installed-cli.py}"
      install_timeout = ${if efi && !useKvm then "3600" else "1500"}
      exec(compile(Path(scenario).read_text(), scenario, "exec"))
    '';
  };
in
assert builtins.elem system [ "x86_64-linux" "aarch64-linux" ];
assert (recoveryPath == null) == (recoveryHash == null);
assert !efi || recoveryPath == null;
assert builtins.stringLength serial <= 20;
assert expectedProfile.mode == "none";
assert expectedProfile.presentation == "headless";
assert !expectedProfile.workerEnabled;
assert !expectedProfile.displayServerEnabled;
assert !expectedProfile.displayManagerEnabled;
assert expectedProfile.configuredDefaultUnit == "multi-user.target";
{
  inherit actual expectedProfile recoveryDisk test;
}
