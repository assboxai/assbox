# SPDX-License-Identifier: GPL-3.0-or-later
{ lib, gh }:
# Upstream's two read-only release commands require a login at the CLI front
# door even though public release/attestation APIs support anonymous reads.
# Change only that front-door check. Signature, TUF, identity, digest and network
# verification remain upstream. A changed upstream layout fails the build.
assert lib.assertMsg (lib.versionAtLeast gh.version "2.97.0")
  "Assbox release verification requires GitHub CLI >= 2.97.0";
gh.overrideAttrs (old: {
  postPatch = (old.postPatch or "") + ''
    for source in pkg/cmd/release/verify/verify.go pkg/cmd/release/verify-asset/verify_asset.go; do
      substituteInPlace "$source" --replace-fail \
        'cmdutil.AddFormatFlags(cmd, &opts.Exporter)' \
        'cmdutil.DisableAuthCheck(cmd); cmdutil.AddFormatFlags(cmd, &opts.Exporter)'
    done
  '';
})
