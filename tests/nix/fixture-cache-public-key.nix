# SPDX-License-Identifier: GPL-3.0-or-later
# Public disposable test key. Never import this trust into an appliance module.
builtins.replaceStrings [ "\n" ] [ "" ] (builtins.readFile ../fixtures/nix-cache-test.pub)
