#!/bin/bash
set -e

# Load GTP kernel module if available (falls back to userspace GTP)
lsmod 2>/dev/null | grep -q gtp || modprobe gtp 2>/dev/null || true

# Pre-create ogstun interface
if ! ip link show ogstun &>/dev/null; then
    ip tuntap add name ogstun mode tun 2>/dev/null || true
    ip addr add 10.46.0.1/16 dev ogstun 2>/dev/null || true
    ip link set ogstun up 2>/dev/null || true
fi

# Start UPF in background
open5gs-upfd &
UPF_PID=$!

# Wait for ogstun interface
for i in {1..30}; do
    ip link show ogstun &>/dev/null && break
    sleep 1
done

# Configure ogstun interface
ip link set ogstun up
ip addr add 10.46.0.1/16 dev ogstun 2>/dev/null || true

# Configure NAT for UE subnet traffic
iptables -t nat -A POSTROUTING -s 10.46.0.0/16 -o eth0 -j MASQUERADE
iptables -A FORWARD -i ogstun -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o ogstun -m state --state RELATED,ESTABLISHED -j ACCEPT

# Apply network impairments if configured (for difficulty-based testing)
if [ -x /scripts/apply-impairment.sh ] && [ -f /etc/open5gs/impairment.yaml ]; then
    /scripts/apply-impairment.sh /etc/open5gs/impairment.yaml || true
fi

wait $UPF_PID
