# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
# Add a foreground entry point before the package's normal wrapGAppsHook runs.
# Both entry points receive the upstream GTK/loader/PATH/Ozone environment;
# the ordinary `code` CLI keeps its normal handoff behavior.
pkgs.vscode.overrideAttrs (old: {
  postInstall = (old.postInstall or "") + ''
    ln -s "$out/lib/vscode/code" "$out/bin/assbox-vscode-gui"
  '';
})
