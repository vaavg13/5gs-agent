#!/bin/bash
# UE entrypoint - resolves gNB hostname before starting

CONFIG_SRC="/etc/ueransim/ue.yaml"
CONFIG_FILE="/tmp/ue.yaml"

# Install iperf3 and ping for network measurements (required by scorer)
echo "Installing network measurement tools..."
apt-get update -qq && apt-get install -y -qq iperf3 iputils-ping > /dev/null 2>&1 || true
echo "Network measurement tools ready"

# Copy config to writable location
cp "$CONFIG_SRC" "$CONFIG_FILE"

# Wait for gNB to be resolvable
echo "Waiting for gNB hostname to be resolvable..."
until getent hosts gnb > /dev/null 2>&1; do
    sleep 1
done

# Get gNB IP
GNB_IP=$(getent hosts gnb | awk '{print $1}')
echo "Resolved gNB hostname to: $GNB_IP"

# Replace hostname with IP in config
sed -i "s/- gnb/- $GNB_IP/" "$CONFIG_FILE"

# Start UE with modified config
# Use full path for free5gc/ueransim image
exec /ueransim/nr-ue -c "$CONFIG_FILE"
