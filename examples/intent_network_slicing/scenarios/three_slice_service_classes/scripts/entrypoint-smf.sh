#!/bin/bash
# SMF entrypoint - resolves UPF hostname and own hostname to IP before starting

CONFIG_SRC="/opt/open5gs/etc/open5gs/smf.yaml"
CONFIG_FILE="/tmp/smf.yaml"

# Copy config to writable location
cp "$CONFIG_SRC" "$CONFIG_FILE"

# Get own container IP
MY_IP=$(ip addr show eth0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
if [ -z "$MY_IP" ]; then
    MY_IP=$(ip addr | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1)
fi
echo "[SMF] Container IP: $MY_IP"

# Replace SMF's own SBI hostname with actual IP
sed -i "s/addr: smf$/addr: $MY_IP/" "$CONFIG_FILE"

# Wait for UPF to be resolvable
echo "[SMF] Waiting for UPF hostname to be resolvable..."
until getent hosts upf > /dev/null 2>&1; do
    sleep 1
done

# Get UPF IP
UPF_IP=$(getent hosts upf | awk '{print $1}')
echo "[SMF] Resolved UPF hostname to: $UPF_IP"

# Replace UPF hostname with IP in config
sed -i "s/addr: upf$/addr: $UPF_IP/" "$CONFIG_FILE"

echo "[SMF] Config updated"

# Start SMF with modified config
exec open5gs-smfd -c "$CONFIG_FILE"
