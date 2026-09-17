# SPDX-License-Identifier: GPL-3.0-or-later
"""Consume the real Rust renderer's keyfile with libnm, without a running daemon."""
import signal
import sys
import gi

signal.alarm(20)
gi.require_version('NM', '1.0')
from gi.repository import GLib, NM

ssid, password = sys.argv[1:]
raw = sys.stdin.buffer.read()
keyfile = GLib.KeyFile.new()
assert keyfile.load_from_data(raw.decode('utf-8'), len(raw), GLib.KeyFileFlags.NONE)
connection = NM.keyfile_read(keyfile, '/', NM.KeyfileHandlerFlags.NONE, None, None)
assert connection is not None
assert bytes(connection.get_setting_wireless().get_ssid().get_data()) == ssid.encode('utf-8')
assert connection.get_setting_wireless_security().get_psk() == password
# The keyfile plugin fills defaults such as a missing UUID when importing files.
# Normalize in memory, then check the complete profile with the same library.
assert connection.normalize()[0]
assert connection.verify()
