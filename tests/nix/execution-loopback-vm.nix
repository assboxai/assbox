# SPDX-License-Identifier: GPL-3.0-or-later
# Real receiving identities, complete TCP handshakes and UDP listener replacement.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  witness = pkgs.writeText "assbox-disposable-loopback-witness.py" (
    builtins.readFile ../fixtures/execution_loopback.py
  );
  serve = port: "${pkgs.python3}/bin/python3 ${witness} serve ${toString port}";
in
pkgs.testers.runNixOSTest {
  name = "assbox-execution-loopback";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = "headless";
      components = { };
      updates.enable = false;
    };
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    environment.systemPackages = [ pkgs.python3 ];
    systemd.user.services.disposable-loopback = {
      wantedBy = [ "default.target" ];
      serviceConfig.ExecStart = serve 18080;
    };
    systemd.user.services.disposable-replaceable-loopback = {
      wantedBy = [ "default.target" ];
      serviceConfig.ExecStart = serve 18082;
    };
    systemd.services.disposable-root-loopback = {
      wantedBy = [ "multi-user.target" ];
      serviceConfig.ExecStart = serve 18081;
    };
    systemd.services.disposable-root-replacement.serviceConfig.ExecStart = serve 18082;
    virtualisation.memorySize = 1024;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    system.stateVersion = "26.05";
  };
  testScript = ''
    import shlex

    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("nftables.service")
    machine.wait_for_unit("user@1000.service")
    prefix = "runuser -u agent -- env HOME=/home/agent XDG_RUNTIME_DIR=/run/user/1000 "

    def user(command):
        return prefix + "bash -c " + shlex.quote(command)

    witness = "${pkgs.python3}/bin/python3 ${witness}"

    def probe(protocol, address, port, uid, source_port=0):
        return (witness + " probe " + protocol + " " + address + " " + str(port)
                + " " + str(uid) + " --source-port " + str(source_port))

    for port in (18080, 18081, 18082):
        machine.wait_until_succeeds("ss -H -ltn 'sport = :" + str(port) + "' | grep -q 127.0.0.1", timeout=60)

    for protocol in ("tcp", "udp"):
        for address in ("127.0.0.1", "::1"):
            allowed = probe(protocol, address, 18080, 1000)
            denied = probe(protocol, address, 18081, 0)
            # Direct UID switches and real user-manager services exercise distinct
            # client cgroups. Admission depends on the receiving listener.
            machine.succeed(user(allowed))
            machine.fail(user(denied))
            managed = "systemd-run --user --wait --pipe --collect --service-type=exec "
            machine.succeed(user(managed + allowed))
            machine.fail(user(managed + denied))

    # UDP must recheck the receiver on each packet. Reuse the same tuple after
    # a privileged service takes over the formerly admitted workload port.
    for address in ("127.0.0.1", "::1"):
        machine.succeed(user(probe("udp", address, 18082, 1000, source_port=49200)))
    machine.succeed(user("systemctl --user stop disposable-replaceable-loopback.service"))
    machine.succeed("systemctl start disposable-root-replacement.service")
    machine.wait_until_succeeds("ss -H -ltn 'sport = :18082' | grep -q 127.0.0.1", timeout=60)
    for address in ("127.0.0.1", "::1"):
        machine.fail(user(probe("udp", address, 18082, 0, source_port=49200)))

    # An admitted established TCP connection must still obey later outbound
    # revocation. This guest-only rule deliberately represents a stricter policy.
    state = "/home/agent/.cache/disposable-loopback"
    machine.succeed("install -d -o agent -g users -m700 " + state)
    held = witness + " hold tcp 127.0.0.1 18080 1000 " + state
    machine.succeed(user("systemd-run --user --no-block --unit=disposable-held-loopback " + held))
    machine.wait_until_succeeds("test -e " + state + "/ready", timeout=60)
    machine.succeed("nft insert rule inet assbox-execution output meta skuid 1000 ip daddr 127.0.0.1 reject")
    machine.succeed("touch " + state + "/continue")
    machine.wait_until_succeeds("grep -Fx denied " + state + "/result", timeout=30)
  '';
}
