# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the real FileChooser portal; the VM driver operates its visible UI."""
import json
from pathlib import Path
import sys

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

mode, output = sys.argv[1:]
output = Path(output)
DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
loop = GLib.MainLoop()
result = None


def response(code, values):
    global result
    result = {"code": int(code), "uris": [str(uri) for uri in values.get("uris", [])]}
    loop.quit()


def expired():
    loop.quit()
    return False


# Subscribe before making the request; a fast response must not get lost.
bus.add_signal_receiver(response, signal_name="Response",
                        dbus_interface="org.freedesktop.portal.Request",
                        bus_name="org.freedesktop.portal.Desktop")
chooser = dbus.Interface(bus.get_object("org.freedesktop.portal.Desktop",
                                       "/org/freedesktop/portal/desktop"),
                         "org.freedesktop.portal.FileChooser")
options = dbus.Dictionary({"handle_token": "assbox_test", "modal": False}, signature="sv")
if mode == "folder":
    options["directory"] = True
if mode == "save":
    options["current_name"] = "saved.txt"
    method = chooser.SaveFile
else:
    method = chooser.OpenFile
method("", "Assbox " + mode, options, timeout=30)
GLib.timeout_add_seconds(90, expired)
loop.run()
if result is None:
    raise SystemExit("portal did not respond")
output.write_text(json.dumps(result))
