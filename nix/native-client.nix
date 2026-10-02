# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  raw,
  id,
  command,
  runtime,
}:
pkgs.runCommand "assbox-guarded-${command}"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta = raw.meta;
  }
  ''
    mkdir -p "$out/bin" "$out/share"
    makeWrapper ${runtime}/bin/assbox-native-policy "$out/bin/${command}" --add-flags "launch ${id}"
    if test -d ${raw}/share; then cp -rL ${raw}/share/. "$out/share/"; chmod -R u+w "$out/share"; fi
    if test -d "$out/share/applications"; then
      for desktop in "$out/share/applications/"*.desktop; do
        sed -i -E "s|^Exec=.*|Exec=$out/bin/${command} %U|" "$desktop"
      done
    fi
  ''
