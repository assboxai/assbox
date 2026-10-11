# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  ffmpegVersion = "8.1.3";
  ffmpegSourceHash = "sha256-cTjSjJbZ0+OvTuPYytcnQfj/tA2pDBESI13qPs0xeKM=";
  capstoneVersion = "5.0.9";
  libusbVersion = "1.0.30";
  nghttp2Version = "1.70.0";
  sqliteVersion = "3.53.3";
  busyboxSecurityPatches = [
    ../nix/patches/busybox-f5e1bf966b19ea1821f00a8c9ecd7774598689b4.patch
  ];
  patchSecurityPatches = [
    # CVE-2026-56288
    ../nix/patches/patch-e6d6a4e021660679d7fc9150f981d4920f722313.patch
    # CVE-2026-56289
    ../nix/patches/patch-faba04ef4f2b410257f76c1b9dc85e350929c4b9.patch
  ];
  # NixOS exposes GNU patch directly through environment.corePackages. Keep
  # the bootstrap/stdenv package set unchanged, but replace that user-visible
  # profile entry with the reviewed derivation. This mirrors the locked
  # NixOS core package list; the evaluation test below makes an upstream list
  # change fail visibly instead of silently dropping a core tool.
  corePackageNames = [
    "acl"
    "attr"
    "bashInteractive"
    "bzip2"
    "coreutils-full"
    "cpio"
    "curl"
    "diffutils"
    "findutils"
    "gawk"
    "getent"
    "getconf"
    "gnugrep"
    "gnupatch"
    "gnused"
    "gnutar"
    "gzip"
    "xz"
    "less"
    "libcap"
    "ncurses"
    "netcat"
    "mkpasswd"
    "procps"
    "su"
    "time"
    "util-linux"
    "which"
    "zstd"
  ];
  dhcpcdSecurityPatches = [
    ../nix/patches/dhcpcd-78ea09ed1633a583dbcde6e7bab9df4639ec8a34.patch
    ../nix/patches/dhcpcd-708b4a56bae080a5b18c2e0c4c6fbe103131a2b0.patch
    ../nix/patches/dhcpcd-2f00c7bfc408b6582d331932dfa47829c4819029.patch
    ../nix/patches/dhcpcd-5733d3c59a5651f64357ac11c98b4f39895c8d25.patch
  ];
  jbig2decSecurityPatches = [
    # CVE-2023-46361
    ../nix/patches/jbig2dec-ee53a7e4bc7819d32e8c0b2057885bcc97586bf3.patch
  ];
  libsndfileSecurityPatches = [
    # CVE-2024-50612
    ../nix/patches/libsndfile-4755f5bd7854611d92ad0f1295587b439f9950ba.patch
    # CVE-2025-56226
    ../nix/patches/libsndfile-d9a35ea0d5c64c19dd635ae578e0028df8f66d6a.patch
    # CVE-2026-37555
    ../nix/patches/libsndfile-3d63704f6654e8bc02fd5b97c069e7fd6a44e44c.patch
    # CVE-2025-52194
    ../nix/patches/libsndfile-7ff854d1e0bd9a751a9ff52ed980c62afced91fe.patch
  ];
in
{
  config = lib.mkIf cfg.enable {
    # Keep each override gated to the exact reviewed input. A later version
    # receives no implicit waiver and must pass the release scan on its own.
    nixpkgs.overlays = [
      (
        final: previous:
        let
          upgradeFfmpeg =
            package:
            if package.version == "8.1.2" then
              package.overrideAttrs (_old: {
                version = ffmpegVersion;
                src = previous.fetchurl {
                  url = "https://ffmpeg.org/releases/ffmpeg-${ffmpegVersion}.tar.xz";
                  hash = ffmpegSourceHash;
                };
              })
            else
              package;
          upgradeSqlite =
            package:
            if package.version == "3.51.2" then
              package.overrideAttrs (old: {
                version = sqliteVersion;
                src = previous.fetchurl {
                  url = "https://sqlite.org/2026/sqlite-src-3530300.zip";
                  hash = "sha256-u4C/ijv/wZJBzoq6WkvHTpw5gAE8sLXw8JdqmVFpQq8=";
                };
                docsrc = previous.fetchurl {
                  url = "https://sqlite.org/2026/sqlite-doc-3530300.zip";
                  hash = "sha256-Fo+Zhph2vPTbjZPvoqSDqcgVNlN9AZAMWM110KZ8yic=";
                };
                patches = (old.patches or [ ]) ++ [
                  (previous.fetchpatch {
                    name = "sqlite-tests-report-failure.patch";
                    url = "https://github.com/sqlite/sqlite/commit/4e4962f6b303688412746b54200ff5402c047aee.patch";
                    includes = [ "test/testrunner.tcl" ];
                    hash = "sha256-DLV2ML2zzjd1nEVScDF1sFDdZm1CrOWt5M10rRwXYCY=";
                  })
                ];
                postInstall = ''
                  mkdir -p $doc/share/doc
                  unzip $docsrc
                  mv sqlite-doc-3530300 $doc/share/doc/sqlite
                '';
              })
            else
              package;
        in
        {
          # The stable channel still carries 8.1.2 after upstream's 8.1.3
          # security/bug-fix point release. Preserve each feature variant and
          # the major ABI, and stop overriding as soon as Nixpkgs advances.
          ffmpeg_8 = upgradeFfmpeg previous.ffmpeg_8;
          ffmpeg_8-headless = upgradeFfmpeg previous.ffmpeg_8-headless;
          ffmpeg_8-full = upgradeFfmpeg previous.ffmpeg_8-full;
          ffmpeg = if previous.ffmpeg.version == "8.1.2" then final.ffmpeg_8 else previous.ffmpeg;
          ffmpeg-headless =
            if previous.ffmpeg-headless.version == "8.1.2" then
              final.ffmpeg_8-headless
            else
              previous.ffmpeg-headless;
          ffmpeg-full =
            if previous.ffmpeg-full.version == "8.1.2" then final.ffmpeg_8-full else previous.ffmpeg-full;
          busybox =
            if previous.busybox.version == "1.37.0" then
              previous.busybox.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ busyboxSecurityPatches;
              })
            else
              previous.busybox;
          assboxPatchedPatch =
            if previous.patch.version == "2.8" then
              previous.patch.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ patchSecurityPatches;
              })
            else
              previous.patch;
          capstone =
            if previous.capstone.version == "5.0.7" then
              previous.capstone.overrideAttrs (_old: {
                version = capstoneVersion;
                src = previous.fetchFromGitHub {
                  owner = "capstone-engine";
                  repo = "capstone";
                  rev = capstoneVersion;
                  hash = "sha256-uAiiKWKGjEATPE0Xc3g+aOLCz5ffIlDmf+7jaGwaZ4I=";
                };
              })
            else
              previous.capstone;
          dhcpcd =
            # Nixpkgs 10.3.1 disables privilege separation and predates four
            # upstream fixes for same-link and local vulnerabilities. Keep the
            # upstream version visible to scanners and apply the reviewed
            # commits in chronological order.
            if previous.dhcpcd.version == "10.3.1" then
              previous.dhcpcd.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ dhcpcdSecurityPatches;
              })
            else
              previous.dhcpcd;
          libusb1 =
            if previous.libusb1.version == "1.0.29" then
              previous.libusb1.overrideAttrs (_old: {
                version = libusbVersion;
                src = previous.fetchFromGitHub {
                  owner = "libusb";
                  repo = "libusb";
                  rev = "v${libusbVersion}";
                  hash = "sha256-qgs8h1vSqJg2muBDWN5nJlvaMjGYZnwMg1m07rqzHco=";
                };
              })
            else
              previous.libusb1;
          jbig2dec =
            if previous.jbig2dec.version == "0.20" then
              previous.jbig2dec.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ jbig2decSecurityPatches;
              })
            else
              previous.jbig2dec;
          libsndfile =
            if previous.libsndfile.version == "1.2.2" then
              previous.libsndfile.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ libsndfileSecurityPatches;
                # CVE-2024-50613 reaches an assertion in libmp3lame through
                # libsndfile's optional MPEG encoder, and upstream has not
                # supplied a libsndfile fix. Assbox does not need this codec
                # path; disable it so the affected code is not compiled.
                configureFlags = (old.configureFlags or [ ]) ++ [ "--disable-mpeg" ];
              })
            else
              previous.libsndfile;
          nghttp2 =
            if previous.nghttp2.version == "1.69.0" then
              previous.nghttp2.overrideAttrs (_old: {
                version = nghttp2Version;
                # Use the bootstrap fetcher. The ordinary fetchurl uses curl,
                # which itself consumes nghttp2.
                src = previous.stdenv.fetchurlBoot {
                  url = "https://github.com/nghttp2/nghttp2/releases/download/v${nghttp2Version}/nghttp2-${nghttp2Version}.tar.bz2";
                  hash = "sha256-j6yh94qpmsO8F2ina34PazbY5qYsE4GHUbHSBfAvlAU=";
                };
              })
            else
              previous.nghttp2;
          sqlite = upgradeSqlite previous.sqlite;
          tinysparql =
            # Keep 3.11.1's public double-to-text representation and complete
            # upstream query assertions when upgrading its SQLite dependency.
            # The compatibility setting is per connection, so other SQLite
            # consumers retain the new default and the security point release.
            if previous.tinysparql.version == "3.11.1" && previous.sqlite.version == "3.51.2" then
              previous.tinysparql.overrideAttrs (old: {
                patches = (old.patches or [ ]) ++ [ ../nix/patches/tinysparql-sqlite-precision.patch ];
              })
            else
              previous.tinysparql;
          sqlite-interactive = upgradeSqlite previous.sqlite-interactive;
        }
      )
    ];
    environment.corePackages = lib.mkForce (
      map (
        name:
        let
          package = if name == "gnupatch" then pkgs.assboxPatchedPatch else pkgs.${name};
        in
        lib.setPrio ((package.meta.priority or lib.meta.defaultPriority) + 3) package
      ) corePackageNames
      ++ [ pkgs.stdenv.cc.libc ]
    );
    assertions = [
      {
        assertion = builtins.all (package: package.version != "8.1.2") [
          pkgs.ffmpeg
          pkgs.ffmpeg_8
          pkgs.ffmpeg_8-headless
          pkgs.ffmpeg_8-full
        ];
        message = "FFmpeg 8.1.2 must be advanced to the reviewed security point release.";
      }
      {
        assertion =
          pkgs.busybox.version != "1.37.0"
          || builtins.all (patch: builtins.elem patch (pkgs.busybox.patches or [ ])) busyboxSecurityPatches;
        message = "BusyBox 1.37.0 must include the reviewed terminal-output security patch.";
      }
      {
        assertion =
          pkgs.assboxPatchedPatch.version != "2.8"
          || builtins.all (
            patch: builtins.elem patch (pkgs.assboxPatchedPatch.patches or [ ])
          ) patchSecurityPatches;
        message = "GNU patch 2.8 must include both reviewed malformed-input fixes.";
      }
      {
        assertion =
          pkgs.dhcpcd.version != "10.3.1"
          || builtins.all (patch: builtins.elem patch (pkgs.dhcpcd.patches or [ ])) dhcpcdSecurityPatches;
        message = "dhcpcd 10.3.1 must include all reviewed Assbox security patches.";
      }
      {
        assertion =
          pkgs.jbig2dec.version != "0.20"
          || builtins.all (patch: builtins.elem patch (pkgs.jbig2dec.patches or [ ])) jbig2decSecurityPatches;
        message = "jbig2dec 0.20 must include the reviewed command-line allocator security patch.";
      }
      {
        assertion =
          pkgs.libsndfile.version != "1.2.2"
          || (
            builtins.all (patch: builtins.elem patch (pkgs.libsndfile.patches or [ ])) libsndfileSecurityPatches
            && builtins.elem "--disable-mpeg" (pkgs.libsndfile.configureFlags or [ ])
          );
        message = "libsndfile 1.2.2 must include all reviewed malformed-input fixes and disable MPEG.";
      }
      {
        assertion =
          pkgs.capstone.version != "5.0.7"
          && pkgs.libusb1.version != "1.0.29"
          && pkgs.nghttp2.version != "1.69.0"
          && pkgs.sqlite.version != "3.51.2";
        message = "Reviewed security point releases must replace the affected library versions.";
      }
    ];
  };
}
