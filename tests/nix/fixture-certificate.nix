# SPDX-License-Identifier: GPL-3.0-or-later
# Generated local modules must remain self-contained under pure flake evaluation.
{ certificate }:
"security.pki.certificates = [ ${builtins.toJSON (builtins.readFile certificate)} ];"
