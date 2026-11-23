{
  pkgs,
  package ? pkgs.libsoup_3,
}:
let
  version = "3.8.1";
  # GNOME's release contains these exact Nixpkgs backports. Retain any
  # later patches introduced by the locked recipe.
  inheritedPatchHashes = [
    "sha256-gEqCeGx49/egPlMcvmOTslszJb/FlVlw+BhQznr5sv0="
    "sha256-k7inbIk0HyijAtTWXFxJYfDTDBif/izWrsYQmdg7z4A="
    "sha256-83teXanQTc6MC5/KBtfz0zgDjatSeiomIbmTFelc3d0="
    "sha256-Y4MzqjroDnUFgDd9NRW/bHRRjWaSphB5dU5DnMdIG6I="
    "sha256-v5xvd7XLHCROeec2bid/5V7Livd1uMHki39Oi+OokLg="
    "sha256-fLTmSp+Z8ZEVbqiaSOjG1iNhg16FS5ul8fP9y0uBeqY="
    "sha256-XuFJMHtAiQiJ26KQ51JDQdJ/NdVkuccZCHQMOyzzdF0="
    "sha256-r30VFpkOqJRiEhl63uavmKecbk8tpTuCvL9YbIozyZg="
    "sha256-13fU7zuzkb7wIH3BxylBaVyw6s/X6f4/ji9yYqYIcVg="
    "sha256-eDsYtL6NHyouaVEHptZy2Gy/34guZJA7LUtj+YgWWQE="
    "sha256-Dpd1qyJlIqNp6MzqyCKQ6anQr887e4J3CAGXEyzQOYU="
    "sha256-TdWCOo2QnCnTbV0dPk4iGnNuwZO+LKSH1YFp2XAenwY="
    "sha256-IPYr77720+LOi3fp+x2M4MTKOm62As0dh8lZ5hKsuTU="
    "sha256-p5J1QlfU+/be5YVahVTKt2QsxlRttrf62AYOa1QrwEo="
    "sha256-DD5HO+ZCn9Q/lVWWG9WnTBSeOe37Y3GD4dvsP4YuCLI="
  ];
in
if package.version == "3.6.6" then
  package.overrideAttrs (old: {
    inherit version;
    src = pkgs.fetchurl {
      url = "https://download.gnome.org/sources/libsoup/3.8/libsoup-${version}.tar.xz";
      hash = "sha256-UBPc75E29vhh5lKfyleK9QwfUqOSGQJ/ta/2UtE3GgQ=";
    };
    patches = builtins.filter (
      patch: !(builtins.elem (patch.outputHash or null) inheritedPatchHashes)
    ) (old.patches or [ ]);
    mesonFlags = (old.mesonFlags or [ ]) ++ [ "-Dzstd=disabled" ];
  })
else
  package
