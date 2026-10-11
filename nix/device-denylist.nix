# SPDX-License-Identifier: GPL-3.0-or-later
{
  lib,
  wifi,
  bluetooth,
  audio,
  camera,
}:
lib.unique (
  lib.optionals (!wifi) [
    "cfg80211"
    "mac80211"
    # Keep the unsupported Broadcom STA driver denied if it is ever added by a
    # local override. MacBookPro11,1 commonly contains the BCM4360 it targets.
    "wl"
  ]
  ++ lib.optionals (!bluetooth) [
    "bluetooth"
    "bnep"
    "btusb"
    "rfcomm"
  ]
  ++ lib.optionals (!wifi && !bluetooth) [
    "cdc_mbim"
    "ieee802154"
    "mac802154"
    "nfc"
    "qmi_wwan"
    "uwb"
    "wwan"
  ]
  ++ lib.optionals (!audio) [
    "snd"
    "snd_hda_intel"
    "snd_usb_audio"
  ]
  ++ lib.optionals (!camera) [
    # MacBookPro11,1 uses the out-of-tree FaceTime HD driver when an operator
    # adds it; keep that path denied as well as standard USB cameras.
    "facetimehd"
    "uvcvideo"
  ]
)
