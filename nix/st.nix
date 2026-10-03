# SPDX-License-Identifier: GPL-3.0-or-later
{ st }:
st.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ./st-window-close.patch ];
})
