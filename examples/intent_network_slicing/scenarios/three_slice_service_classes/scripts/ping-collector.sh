#!/bin/bash
# Ping-only metrics collector for non-target UE containers.
# Writes the same CSV format as metrics-collector.sh but with throughput=0.
# Resilient to tunnel disruptions — waits for interface recovery.
#
# Usage: ping-collector.sh [TARGET] [CSV_PATH] [INTERFACE]

TARGET="${1:-iperf3-server}"
CSV="${2:-/tmp/metrics.csv}"
IFACE="${3:-uesimtun0}"

cleanup() {
    kill $(jobs -p) 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

wait_for_interface() {
    while ! ip addr show "$IFACE" 2>/dev/null | grep -q "inet "; do
        sleep 1
    done
}

wait_for_interface

echo "timestamp,throughput_mbps,latency_ms,jitter_ms,packet_loss_pct" > "$CSV"

while true; do
    wait_for_interface
    prev_rtt=-1
    ping -I "$IFACE" -i 1 "$TARGET" 2>/dev/null | while IFS= read -r line; do
        rtt=$(echo "$line" | sed -n 's/.*time=\([0-9.]*\).*/\1/p')
        if [ -n "$rtt" ]; then
            if [ "$prev_rtt" != "-1" ]; then
                jitter=$(awk "BEGIN {d=$rtt-$prev_rtt; print (d<0?-d:d)}")
            else
                jitter="0"
            fi
            prev_rtt="$rtt"
            ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            echo "$ts,0,$rtt,$jitter,0" >> "$CSV"
        fi
    done
    sleep 1
done
