#!/usr/bin/env bash
# Prints host hardware facts for the README (M0 amendment). Run on the target server.
set -eu
echo "CPU: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | xargs) ($(nproc) threads)"
echo "RAM: $(awk '/MemTotal/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
echo "Disk (/var/lib/docker or /): $(df -h --output=size,avail "$( [ -d /var/lib/docker ] && echo /var/lib/docker || echo / )" | tail -1)"
echo "Kernel: $(uname -sr)"
