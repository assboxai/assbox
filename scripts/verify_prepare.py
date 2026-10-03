#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit finite verification that never dispatches Nix or VM builds."""
import argparse
import subprocess


def commands(lite=False):
    result = [['scripts/verify', 'static'], ['scripts/verify', 'rust']]
    if not lite:
        result += [['scripts/verify', 'mutations'], ['python3', 'scripts/development_check.py', 'runtime']]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lite', action='store_true')
    args = parser.parse_args()
    for command in commands(args.lite):
        subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
