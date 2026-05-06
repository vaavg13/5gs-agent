#!/bin/bash
# gNB entrypoint - resolves AMF hostname and sets own IP before starting

CONFIG_SRC="/etc/ueransim/gnb.yaml"
CONFIG_FILE="/tmp/gnb.yaml"

# Copy config to writable location
cp "$CONFIG_SRC" "$CONFIG_FILE"

# Wait for AMF to be resolvable
echo "Waiting for AMF hostname to be resolvable..."
until getent hosts amf > /dev/null 2>&1; do
    sleep 1
done

# Get AMF IP
AMF_IP=$(getent hosts amf | awk '{print $1}')
echo "Resolved AMF hostname to: $AMF_IP"

# Get own container IP using ip addr (more reliable in Alpine/BusyBox)
MY_IP=$(ip addr show eth0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
if [ -z "$MY_IP" ]; then
    # Fallback: try to get any non-loopback IP
    MY_IP=$(ip addr | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1)
fi
echo "Container IP: $MY_IP"

# Replace hostnames/placeholders with IPs in config
sed -i "s/linkIp: 0.0.0.0/linkIp: $MY_IP/" "$CONFIG_FILE"
sed -i "s/ngapIp: 0.0.0.0/ngapIp: $MY_IP/" "$CONFIG_FILE"
sed -i "s/gtpIp: 0.0.0.0/gtpIp: $MY_IP/" "$CONFIG_FILE"
sed -i "s/address: amf/address: $AMF_IP/" "$CONFIG_FILE"

echo "=== Pre-flight diagnostics ==="
[ -c /dev/net/tun ] && echo "  /dev/net/tun: OK" || echo "  /dev/net/tun: NOT accessible"
[ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ] && echo "  IP forwarding: enabled" || echo "  IP forwarding: disabled"

echo "Config updated:"
cat "$CONFIG_FILE"

mkdir -p /var/log/ueransim

# Start gNB with modified config
# Use full path for free5gc/ueransim image
exec sh -c '/ueransim/nr-gnb -c "$1" 2>&1 | tee -a /var/log/ueransim/gnb.log' sh "$CONFIG_FILE"
