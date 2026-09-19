# Copyright 2022 Alessandro Astone
# SPDX-License-Identifier: GPL-3.0-or-later

# Currently implemented as FIFO
import os
import dbus

def DBusContainerService(object_path="/ContainerManager", intf="org.mutantcat.androidbox.ContainerManager"):
    return dbus.Interface(dbus.SystemBus().get_object("org.mutantcat.androidbox.Container", object_path), intf)

def DBusSessionService(object_path="/SessionManager", intf="org.mutantcat.androidbox.SessionManager"):
    return dbus.Interface(dbus.SessionBus().get_object("org.mutantcat.androidbox.Session", object_path), intf)
