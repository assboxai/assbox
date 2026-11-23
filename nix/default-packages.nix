# SPDX-License-Identifier: GPL-3.0-or-later
{
  lib,
  options,
  pkgs,
}:
map (
  package:
  if package.drvPath == pkgs.rsync.drvPath then
    lib.setPrio (package.meta.priority or lib.meta.defaultPriority) pkgs.assboxReviewedRsync
  else
    package
) options.environment.defaultPackages.default
