# Intel Mac prerequisites and acceptance

This is a procedure for qualifying one machine and application. The model profiles
are implementation targets, not a record of successful physical-hardware testing.
Keep results, serials and machine-specific configurations outside the repository.

## Hardware boundary

In macOS, obtain the model identifier with `sysctl -n hw.model`. In the live NixOS
environment, compare it with `/sys/class/dmi/id/product_name` and inspect `lspci -nnk`.
The installer displays the DMI model, PCI network identifiers and wireless drivers.

| Model | Guided installer profile | Networking prerequisite |
| --- | --- | --- |
| MacBookPro11,1 | `macbookpro11-1` | BCM4360 (`14e4:43a0` or `14e4:4360`) built-in Wi-Fi is unsupported; use Ethernet or a supported external adapter |
| MacBookPro12,1 | `macbookpro12-1` | Establish a live wireless interface with its in-tree driver, normally `brcmfmac`, or use Ethernet |
| Other Apple models, including T2 | Refused | Requires a separately reviewed hardware configuration and support decision |

Actual PCI observations take precedence over assumptions about a model's original
parts. Both models may use Ethernet with Wi-Fi disabled. Requested Wi-Fi requires
at least one live interface with a bound in-tree driver. An unsupported built-in
adapter does not disqualify a working external adapter. That external adapter must
remain attached during installation and be tested after boot. The check does not
certify every in-tree driver or validate an Internet connection.

The [upstream MacBookPro11,1 notes](https://github.com/NixOS/nixos-hardware/blob/master/apple/macbook-pro/11-1/README.md)
identify the BCM4360's dependency on `wl`. The
[pinned Nixpkgs driver](https://github.com/NixOS/nixpkgs/blob/c3eea5b2156db11c7eeeada3dc737711255b253e/pkgs/os-specific/linux/broadcom-sta/default.nix)
lists known vulnerabilities and an unmaintained implementation. Application consent
to proprietary packages does not override this driver decision. Assbox adds no
`permittedInsecurePackages` exception or hardware-check bypass.

The generic `apple-intel` NixOS module remains an expert configuration building
block. Selecting it in the guided installer cannot substitute for model support.
Other features, such as camera access or suspend, need their own real-hardware
acceptance if enabled. Start with the default disabled camera, Bluetooth and suspend.

## Release commissioning prerequisite

Follow [repository provisioning](governance.md#one-time-repository-provisioning) and
[release authentication](release-authentication.md) before applying installation.
The source's zero trust IDs intentionally prevent deployment until real repository
and owner IDs are independently verified and committed. A 404 or inaccessible
repository is not evidence of an ID and must never be replaced with a development
fork's identity merely to get past this gate.

Record the reviewed source commit, locked inputs, provisioned numeric IDs and exact
authenticated release tag. Complete native release gates before enabling publication;
then exercise the real bootstrap client, installation and an authenticated successor
release. Confirm independent release-monitor failure and recovery notifications.
The disposable signed fixtures do not establish any of these remote properties.

## Acceptance on the actual machine

Use independent data backups, the required external boot-backup disk and working
rescue media. Follow [installation](installation.md) and keep the
[recovery procedure](install-recovery.md) available off the machine.

1. **Live environment:** boot through the installed rEFInd, confirm the observed
   model and physical storage identities, exercise keyboard/trackpad and the chosen
   network connection, and check the retained macOS partition layout. Use the same
   network adapter intended for the installed system.
2. **Initial installation:** begin with `none`/headless. Save the exact source/release
   identities and installer outcome. Boot Assbox from rEFInd, log in as administrator
   and verify networking. Reboot into the actual macOS installation, then Assbox
   again. Check that rescue media still boot and the external backup can be read.
3. **Application:** select the intended profile, complete real provider onboarding,
   and run a representative authenticated task. Reboot and verify that the GUI or
   service and its credentials work again. Test any requested USB, audio, camera,
   display-off or suspend behavior separately. For ChatGPT, verify usable `/dev/kvm`
   in the installed Linux system and complete [worker acceptance](worker/acceptance.md)
   and [client-routing acceptance](worker/client-routing.md). Run the authenticated
   task in the worker SSH project. Confirm adequate RAM and disk headroom with the
   controller and worker both active; the installer's budget is an admission floor,
   not a measurement of acceptable performance on this MacBook.
4. **Maintenance and resources:** run a representative workload alongside an update.
   Observe responsiveness, memory/swap, free disk space, fan behavior and temperature.
   Exercise the notification grace and reboot with real work active. Confirm the
   application becomes usable afterward; service activity alone is insufficient.
5. **Recovery:** stage and boot a retained generation, verify a real authenticated
   successor update, and confirm macOS still boots after bootloader updates. Exercise
   low/unknown battery and unavailable-network behavior. Perform deliberate power
   cuts and disk exhaustion in disposable VMs, not first on valuable dual-boot data.

Record a pass/fail and evidence for each step, including model, PCI IDs, RAM, storage,
application version, source commit and release tag. A failure blocks acceptance of
that configuration. Changes to kernel, firmware or application versions require
appropriate regression checks; one successful installation is not perpetual approval.

`assbox doctor`, journal output and the boot-check service are diagnostic aids.
Boot-check does not establish Internet access or application authentication, and
there is no automatic boot-count rollback. Production operation assumes an
administrator can reach the console or rescue media when a boot needs repair.
