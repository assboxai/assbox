# SPDX-License-Identifier: GPL-3.0-or-later
# Prune optional speech and local-model runtimes from the reviewed upstream
# closure. Browser/CUA tools are selected separately; missing extras stay off.
{
  lib,
  appPkgs,
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
  ffmpeg = appPkgs.ffmpeg;
  ffmpegVersion = "9.1";
  reviewedFfmpeg = ffmpeg.overrideAttrs (old: {
    version = ffmpegVersion;
    src = appPkgs.fetchurl {
      url = "https://ffmpeg.org/releases/ffmpeg-${ffmpegVersion}.tar.xz";
      hash = "sha256-Gk05SuY9GQpSbNBS60QVwVa1xeLfN++rQafeC4/eJDM=";
    };
    # FFmpeg 9.1 includes this backport.
    patches = builtins.filter (
      patch:
      !lib.hasSuffix "0001-swscale-loongarch-fix-buffer-underflow-in-yuv2plane1.patch" (toString patch)
    ) (old.patches or [ ]);
  });
  retainedDependencies = map (
    package:
    if (package.pname or null) == "discord.py" && ffmpeg.version == "9.0.1" then
      package.override { ffmpeg = reviewedFfmpeg; }
    else
      package
  ) (builtins.filter (p: !(builtins.elem (p.pname or (lib.getName p)) excluded)) raw.dependencies);
  # Python applications need not expose pythonModule. Their declared Python
  # dependencies still identify the upstream interpreter; the consuming host's
  # Python can have a different native extension ABI.
  pythonDependency = lib.findFirst (
    p: p ? pythonModule && !(builtins.isBool p.pythonModule)
  ) null retainedDependencies;
  pythonBase =
    if raw ? pythonModule && !(builtins.isBool raw.pythonModule) then
      raw.pythonModule
    else if pythonDependency != null then
      pythonDependency.pythonModule
    else
      throw "Hermes dependencies do not identify their Python interpreter";
  # The pinned Hermes wheel requires watchfiles. The package recipe omits it.
  dependencies =
    retainedDependencies
    ++ lib.optional (
      !(lib.any (p: (p.pname or (lib.getName p)) == "watchfiles") retainedDependencies)
    ) pythonBase.pkgs.watchfiles;
  python = pythonBase.withPackages (_: dependencies);
in
assert lib.all (
  p: !(p ? pythonModule) || builtins.isBool p.pythonModule || p.pythonModule == pythonBase
) dependencies;
raw.overridePythonAttrs (old: {
  inherit dependencies;
  makeWrapperArgs =
    map (
      arg: if lib.hasSuffix "/bin/python3" arg then "${python}/bin/python3" else arg
    ) old.makeWrapperArgs
    ++ [
      "--set"
      "HERMES_BUNDLED_LOCALES"
      "${placeholder "out"}/share/hermes/locales"
    ];
  # Hermes looks up message catalogs outside the Python wheel.
  postInstall =
    (old.postInstall or "")
    + "\n"
    + ''
      mkdir -p "$out/share/hermes/locales"
      cp ${old.src}/locales/*.yaml "$out/share/hermes/locales/"
    '';
  # Keep a core import gate for the resulting interpreter instead of requiring
  # the deliberately unselected voice/model extras in the upstream smoke test.
  installCheckPhase = ''
    runHook preInstallCheck
    ${python}/bin/python3 -c 'import openai, anthropic, dotenv, tenacity, watchfiles'
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
    grep -q HERMES_BUNDLED_LOCALES "$out/bin/hermes"
    HERMES_BUNDLED_LOCALES="$out/share/hermes/locales" \
    PYTHONPATH="$out/${pythonBase.sitePackages}" \
      ${python}/bin/python3 -c '
    import hermes_cli.dashboard_auth, tui_gateway.slash_worker, yaml
    from agent.i18n import SUPPORTED_LANGUAGES, _load_catalog, t

    assert all(_load_catalog(language) for language in SUPPORTED_LANGUAGES)
    assert "fixture-session" in t("gateway.status.session_id", lang="en", session_id="fixture-session")
    '
  '';
})
