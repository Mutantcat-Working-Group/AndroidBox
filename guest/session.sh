#!/bin/sh
set -eu
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=AndroidBox
export WLR_RENDERER=pixman
export WLR_NO_HARDWARE_CURSORS=1
exec dbus-run-session -- sh -c 'pulseaudio --start; exec cage -- androidbox show-full-ui'
