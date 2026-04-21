#!/bin/bash
# Apply per-service-class bandwidth and delay policies on ogstun.

set -e

CONFIG_FILE="${1:-/etc/open5gs/service-classes.yaml}"
INTERFACE="ogstun"
LOG_PREFIX="[service-class]"

log() {
    echo "$LOG_PREFIX $*"
}

get_config() {
    local key="$1"
    local default="$2"
    local value

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "$default"
        return
    fi

    value=$(grep -E "^${key}:" "$CONFIG_FILE" 2>/dev/null | sed 's/^[^:]*:[[:space:]]*//' | sed "s/['\"]//g" | head -1)
    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

is_enabled() {
    local value
    value=$(get_config "$1" "false")
    case "$value" in
        true|True|TRUE|yes|Yes|YES|1) return 0 ;;
        *) return 1 ;;
    esac
}

wait_for_interface() {
    local max_wait=30
    local waited=0

    while ! ip link show "$INTERFACE" >/dev/null 2>&1; do
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge "$max_wait" ]; then
            log "ERROR: $INTERFACE interface not found after ${max_wait}s"
            return 1
        fi
    done
}

add_class_profile() {
    local classid="$1"
    local handle="$2"
    local subnet="$3"
    local rate="$4"
    local ceil="$5"
    local delay_ms="$6"
    local loss_pct="$7"
    local netem_args="delay ${delay_ms}ms"

    if [ -n "$loss_pct" ] && [ "$loss_pct" != "0" ] && [ "$loss_pct" != "0.0" ]; then
        netem_args="$netem_args loss ${loss_pct}%"
    fi

    tc class add dev "$INTERFACE" parent 1:1 classid "$classid" htb rate "$rate" ceil "$ceil"
    tc qdisc add dev "$INTERFACE" parent "$classid" handle "$handle" netem $netem_args
    tc filter add dev "$INTERFACE" protocol ip parent 1: prio 10 u32 match ip src "$subnet" flowid "$classid"
    tc filter add dev "$INTERFACE" protocol ip parent 1: prio 10 u32 match ip dst "$subnet" flowid "$classid"
}

main() {
    log "Starting service-class QoS setup"
    log "Config file: $CONFIG_FILE"

    if [ ! -f "$CONFIG_FILE" ]; then
        log "Config file not found, skipping"
        exit 0
    fi

    if ! is_enabled "enabled"; then
        log "Service-class shaping disabled, skipping"
        exit 0
    fi

    wait_for_interface

    local root_rate default_rate default_ceil
    root_rate=$(get_config "root_rate" "1000mbit")
    default_rate=$(get_config "default_rate" "20mbit")
    default_ceil=$(get_config "default_ceil" "50mbit")

    tc qdisc del dev "$INTERFACE" root 2>/dev/null || true
    tc qdisc add dev "$INTERFACE" root handle 1: htb default 40
    tc class add dev "$INTERFACE" parent 1: classid 1:1 htb rate "$root_rate"
    tc class add dev "$INTERFACE" parent 1:1 classid 1:40 htb rate "$default_rate" ceil "$default_ceil"

    add_class_profile "1:10" "10:" \
        "$(get_config "background_subnet" "10.46.10.0/24")" \
        "$(get_config "background_rate" "70mbit")" \
        "$(get_config "background_ceil" "100mbit")" \
        "$(get_config "background_delay_ms" "35")" \
        "$(get_config "background_loss_pct" "0")"

    add_class_profile "1:20" "20:" \
        "$(get_config "premium_subnet" "10.46.20.0/24")" \
        "$(get_config "premium_rate" "900mbit")" \
        "$(get_config "premium_ceil" "950mbit")" \
        "$(get_config "premium_delay_ms" "2")" \
        "$(get_config "premium_loss_pct" "0")"

    add_class_profile "1:30" "30:" \
        "$(get_config "control_subnet" "10.46.30.0/24")" \
        "$(get_config "control_rate" "300mbit")" \
        "$(get_config "control_ceil" "400mbit")" \
        "$(get_config "control_delay_ms" "8")" \
        "$(get_config "control_loss_pct" "0")"

    log "Final tc configuration:"
    tc -s qdisc show dev "$INTERFACE" 2>&1 | while read -r line; do
        log "  $line"
    done
    tc -s class show dev "$INTERFACE" 2>&1 | while read -r line; do
        log "  $line"
    done
}

main "$@"
