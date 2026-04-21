#!/bin/bash
# Generic NF entrypoint - resolves container hostname to IP and updates config
# Usage: entrypoint-nf.sh <config_path> <nf_name> <daemon_command>

CONFIG_FILE="$1"
NF_NAME="$2"
DAEMON_CMD="$3"

# Create writable config copy
CONFIG_TMP="/tmp/${NF_NAME}.yaml"
cp "$CONFIG_FILE" "$CONFIG_TMP"

# Get own container IP
MY_IP=$(ip addr show eth0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
if [ -z "$MY_IP" ]; then
    MY_IP=$(ip addr | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1)
fi
echo "[$NF_NAME] Container IP: $MY_IP"

# Replace hostname with actual IP in the NF's SBI config
# The pattern matches "addr: <hostname>" where hostname is the NF name
sed -i "s/addr: ${NF_NAME}$/addr: ${MY_IP}/" "$CONFIG_TMP"

echo "[$NF_NAME] Config updated:"
grep -A2 "${NF_NAME}:" "$CONFIG_TMP" | head -10

# Start the daemon
exec $DAEMON_CMD -c "$CONFIG_TMP"
