# SPDX-License-Identifier: GPL-3.0-or-later
# Prune optional speech and local-model runtimes from the reviewed upstream
# closure. Browser/CUA tools are selected separately; missing extras stay off.
{
  lib,
  pkgs,
  raw,
}:
let
  excluded = [
    "edge-tts"
    "faster-whisper"
    "sounddevice"
    "numpy"
    "elevenlabs"
    "modal"
  ];
  dependencies = builtins.filter (
    p: !(builtins.elem (p.pname or (lib.getName p)) excluded)
  ) raw.dependencies;
  # Python applications need not expose pythonModule. Their declared Python
  # dependencies still identify the upstream interpreter; the consuming host's
  # Python can have a different native extension ABI.
  pythonDependency = lib.findFirst (
    p: p ? pythonModule && !(builtins.isBool p.pythonModule)
  ) null dependencies;
  pythonBase =
    if raw ? pythonModule && !(builtins.isBool raw.pythonModule) then
      raw.pythonModule
    else if pythonDependency != null then
      pythonDependency.pythonModule
    else
      throw "Hermes dependencies do not identify their Python interpreter";
  python = pythonBase.withPackages (_: dependencies);
in
assert lib.all (
  p: !(p ? pythonModule) || builtins.isBool p.pythonModule || p.pythonModule == pythonBase
) dependencies;
raw.overridePythonAttrs (old: {
  inherit dependencies;
  makeWrapperArgs = map (
    arg: if lib.hasSuffix "/bin/python3" arg then "${python}/bin/python3" else arg
  ) old.makeWrapperArgs;
  # Keep a core import gate for the resulting interpreter instead of requiring
  # the deliberately unselected voice/model extras in the upstream smoke test.
  installCheckPhase = ''
    runHook preInstallCheck
    ${python}/bin/python3 -c 'import openai, anthropic, dotenv, tenacity'
    test -x "$out/bin/hermes"
    grep -q HERMES_DISABLE_LAZY_INSTALLS "$out/bin/hermes"
    runHook postInstallCheck
  '';
  # The upstream hook closes over its full interpreter (including voice/model
  # extras). Check the retained assets against this pruned package instead.
  postInstallCheck = ''
    test -d "$out/share/hermes/skills"
    test -d "$out/share/hermes/optional-skills"
    test -d "$out/share/hermes/plugins"
    grep -q HERMES_WEB_DIST "$out/bin/hermes"
    PYTHONPATH="$out/${pythonBase.sitePackages}" \
      ${python}/bin/python3 -c 'import hermes_cli.dashboard_auth, tui_gateway.slash_worker, yaml'
  '';
})
