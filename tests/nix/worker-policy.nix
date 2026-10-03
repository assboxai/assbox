# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, module }:
let
  evaluate =
    extra:
    import (pkgs.path + "/nixos/lib/eval-config.nix") {
      system = pkgs.stdenv.hostPlatform.system;
      modules = [
        module
        ./fixture.nix
        {
          assbox.updates.enable = false;
          assbox.worker = {
            stateGiB = 8;
            enable = true;
            components = [ "vim" ];
            egress = "offline";
            nameservers = [ ];
          };
        }
        extra
      ];
    };
  good = evaluate { };
  missingCapacity = evaluate ({ lib, ... }: { assbox.worker.stateGiB = lib.mkForce null; });
  disabled = evaluate ({ lib, ... }: { assbox.worker.enable = lib.mkForce false; });
  noAssbox = evaluate (
    { lib, ... }: {
      assbox.enable = lib.mkForce false;
      assbox.worker.enable = lib.mkForce false;
    }
  );
  badHost = evaluate { assbox.components.codex.enable = true; };
  missingWorker = evaluate (
    { lib, ... }: {
      assbox.worker.enable = lib.mkForce false;
      assbox.acceptUnfree = true;
      assbox.presentation = "x11";
      assbox.components.chatgpt-desktop = {
        enable = true;
        allowMutableCode = true;
      };
    }
  );
  missingCodex = evaluate {
    assbox.kiosk.localExecution = "managed-worker";
    assbox.acceptUnfree = true;
    assbox.presentation = "x11";
    assbox.components.chatgpt-desktop = {
      enable = true;
      allowMutableCode = true;
    };
  };
  multiAgent = evaluate (
    { lib, ... }: {
      assbox.acceptUnfree = true;
      assbox.presentation = "x11";
      assbox.components.chatgpt-desktop = {
        enable = true;
        allowMutableCode = true;
      };
      assbox.worker.components = lib.mkForce [
        "codex"
        "claude-code"
        "grok"
        "antigravity-cli"
        "cursor-agent"
        "opencode"
        "pi"
        "omp"
      ];
    }
  );
  badNetwork = evaluate ({ lib, ... }: { assbox.worker.egress = lib.mkForce "internet"; });
  happier = evaluate (
    { lib, ... }: {
      assbox.worker.components = lib.mkForce [
        "happier"
        "happier-daemon"
        "codex"
      ];
      assbox.worker.allowMutableCodeFor = [
        "happier"
        "happier-daemon"
      ];
    }
  );
  failed = system: builtins.filter (item: !item.assertion) system.config.assertions;
  unit = good.config.systemd.services.assbox-worker;
  image = good.config.system.build.assboxWorkerImage;
  guestPolicy = image.guestPolicy;
  sshConfig =
    pkgs.writeText "worker-native-ssh-test.conf"
      good.config.environment.etc."assbox/worker-ssh-config".text;
  healthConfig =
    pkgs.writeText "worker-native-health-ssh-test.conf"
      good.config.environment.etc."assbox/worker-health-ssh-config".text;
in
assert failed good == [ ];
assert builtins.any (item: pkgs.lib.hasInfix "Set worker.stateGiB explicitly" item.message) (
  failed missingCapacity
);
assert failed disabled == [ ];
assert !(noAssbox.config.users.users ? assbox-vmm);
assert !(noAssbox.config.users.users ? assbox-health-probe);
assert !(disabled.config.system.build ? assboxWorkerImage);
assert !(disabled.config.system.build ? assboxWorkerAudit);
assert !(disabled.config.systemd.services ? assbox-worker);
assert !(disabled.config.systemd.services ? assbox-worker-provision);
assert !(disabled.config.systemd.services ? assbox-worker-network);
assert !(disabled.config.systemd.timers ? assbox-worker-health);
assert !(disabled.config.systemd.timers ? assbox-worker-boot-retry);
assert !(disabled.config.networking.nftables.tables ? assbox-worker);
assert !(disabled.config.environment.etc ? "assbox/worker-runtime.json");
assert !disabled.config.assbox.workerBootPolicy.enabled;
assert builtins.all
  (
    name:
    let
      u = disabled.config.users.users.${name};
    in
    u.isSystemUser
    && u.home == "/var/empty"
    && !u.createHome
    && u.hashedPassword == "!"
    && pkgs.lib.hasSuffix "/bin/nologin" u.shell
    && !(builtins.elem "kvm" u.extraGroups)
  )
  [
    "assbox-vmm"
    "assbox-health-probe"
  ];
assert builtins.elem "kvm" good.config.users.users.assbox-vmm.extraGroups;
assert
  !(builtins.any (
    rule: pkgs.lib.hasPrefix "d /var/lib/assbox-worker-data " rule
  ) good.config.systemd.tmpfiles.rules);
assert failed multiAgent == [ ];
assert failed happier == [ ];
assert builtins.all (
  item: item.assertion
) happier.config.system.build.assboxWorkerImage.guestPolicy.assertions;
assert builtins.all (
  item: item.assertion
) multiAgent.config.system.build.assboxWorkerImage.guestPolicy.assertions;
assert failed missingWorker == [ ];
assert failed missingCodex != [ ];
assert good.config.users.users.assbox-health-probe.isSystemUser;
assert good.config.users.users.assbox-health-probe.home == "/var/empty";
# Checking only the host assertions does not evaluate a separately built guest.
assert builtins.all (item: item.assertion) guestPolicy.assertions;
assert builtins.deepSeq image.auditClosure.drvPath true;
assert guestPolicy.allowNoPasswordLogin;
assert !guestPolicy.mutableUsers;
assert guestPolicy.rootPassword == "!";
assert guestPolicy.agentPassword == "!";
assert !guestPolicy.passwordAuthentication;
assert guestPolicy.permitRootLogin == "no";
assert pkgs.lib.hasSuffix "/bin/assbox-health-shell" guestPolicy.healthShell;
assert guestPolicy.healthHome == "/var/empty";
assert builtins.any (a: pkgs.lib.hasInfix "execution components" a.message) (failed badHost);
assert builtins.any (a: pkgs.lib.hasInfix "uplinkInterfaces" a.message) (failed badNetwork);
assert unit.serviceConfig.User == "assbox-vmm";
assert unit.serviceConfig.ProtectHome;
assert unit.serviceConfig.NoNewPrivileges;
assert unit.serviceConfig.CapabilityBoundingSet == "";
assert builtins.elem "nftables.service" unit.bindsTo;
assert good.config.networking.firewall.enable;
assert good.config.assbox.components.codex.enable == false;
assert good.config.assbox.worker.components == [ "vim" ];
assert !(good.config.system.build ? assboxWorkerGuest);
assert good.config.system.build.assboxWorkerImage.type == "derivation";
assert good.config.system.build.assboxWorkerAudit.type == "derivation";
assert good.config.assbox.workerBootPolicy.enabled;
assert
  !(builtins.elem "assbox-worker-health.service" good.config.systemd.services.assbox-boot-check.requires);
assert unit.serviceConfig.ProtectKernelLogs;
assert good.config.systemd.timers.assbox-worker-boot-retry.enable;
assert good.config.systemd.timers.assbox-worker-boot-retry.timerConfig.OnUnitInactiveSec == "5min";
pkgs.runCommand "assbox-worker-policy"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.openssh
    ];
  }
  ''
    export HOME="$TMPDIR/home"
    mkdir -p "$HOME" "$out"
    python3 ${../worker/native-ssh-policy.py} ${../../scripts/worker/worker.py} ${sshConfig} ${healthConfig}
    printf '%s\n' 'Worker Nix evaluation assertions passed.' > "$out/result"
  ''
