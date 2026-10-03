# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  raw,
  command,
}:
# Public command wrappers keep vendor service installers and CLI self-updaters
# from becoming the normal managed lifecycle. They do not sandbox agent code.
pkgs.writeShellScriptBin command ''
  case "''${1-}" in
    update|upgrade|self-update|selfupdate)
      echo 'This executable is Nix-managed. Use Assbox release updates.' >&2; exit 78 ;;
  esac
  case ${pkgs.lib.escapeShellArg command}:"''${1-}":"''${2-}":"''${3-}" in
    happier:daemon:service:install)
      case " $* " in *" --dry-run "*) ;; *) echo 'Use the Nix-owned Happier supervisor.' >&2; exit 78 ;; esac ;;
    happier:daemon:service:uninstall|openclaw:daemon:install:*|openclaw:gateway:install:*|hermes:gateway:install:*|agy:remote-control:start:*)
      echo 'Assbox owns the supervisor. Use component setup and the declarative service contract.' >&2; exit 78 ;;
  esac
  exec ${raw}/bin/${command} "$@"
''
