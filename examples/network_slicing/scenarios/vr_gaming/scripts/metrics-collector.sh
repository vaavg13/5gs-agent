#!/bin/bash
# Continuous metrics collector for UE containers.
# Runs iperf3 (throughput) + ping (latency) in parallel, writes CSV.
# Resilient to tunnel disruptions — waits for interface recovery.
#
# Usage: metrics-collector.sh [TARGET] [CSV_PATH] [INTERFACE]

TARGET="${1:-iperf3-server}"
CSV="${2:-/tmp/metrics.csv}"
IFACE="${3:-uesimtun0}"

PING_STATE="/tmp/.ping_state"

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

echo "0 0 0" > "$PING_STATE"
(
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
                echo "$rtt $jitter 0" > "$PING_STATE"
            fi
        done
        sleep 1
    done
) &
PING_PID=$!

while true; do
    wait_for_interface
    iperf3 -c "$TARGET" -t 86400 -i 1 --forceflush -R --bind-dev "$IFACE" 2>/dev/null | \
    while IFS= read -r line; do
        case "$line" in
            *[Bb]its/sec*)
                case "$line" in
                    *SUM*|*sender*|*receiver*|*"- -"*) continue ;;
                esac
                tp_match=$(echo "$line" | grep -oE '[0-9.]+ [KMG]?bits/sec' | head -1)
                [ -z "$tp_match" ] && continue
                num=$(echo "$tp_match" | awk '{print $1}')
                unit=$(echo "$tp_match" | awk '{print $2}')
                case "$unit" in
                    Gbits/sec) mbps=$(awk "BEGIN {printf \"%.2f\", $num * 1000}") ;;
                    Mbits/sec) mbps=$(awk "BEGIN {printf \"%.2f\", $num}") ;;
                    Kbits/sec) mbps=$(awk "BEGIN {printf \"%.2f\", $num / 1000}") ;;
                    *)         mbps=$(awk "BEGIN {printf \"%.6f\", $num / 1000000}") ;;
                esac
                read -r lat jit loss < "$PING_STATE" 2>/dev/null || { lat=0; jit=0; loss=0; }
                ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
                echo "$ts,$mbps,$lat,$jit,$loss" >> "$CSV"
                ;;
        esac
    done
    sleep 2
done
