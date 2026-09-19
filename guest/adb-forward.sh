#!/bin/sh
# This runs in the guest only. Keep Android ADB authentication enabled.
set -eu
lease=/var/lib/misc/dnsmasq.androidbox0.leases
while :; do
    ip=$(awk 'NR == 1 {print $3}' "$lease" 2>/dev/null || true)
    case "$ip" in
        192.168.240.*)
            exec socat TCP-LISTEN:5555,bind=0.0.0.0,reuseaddr,fork "TCP:$ip:5555"
            ;;
    esac
    sleep 2
done
