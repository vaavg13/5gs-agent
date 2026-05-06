#!/bin/bash
# apply-impairment.sh - Apply tc/netem network impairments to ogstun interface
#
# This script reads a flattened YAML config file and applies traffic control
# rules to simulate network degradation for testing purposes.
#
# Usage: /scripts/apply-impairment.sh /etc/open5gs/impairment.yaml

set -e

CONFIG_FILE="${1:-/etc/open5gs/impairment.yaml}"
INTERFACE="ogstun"
LOG_PREFIX="[impairment]"

log() {
    echo "$LOG_PREFIX $*"
}

# Parse a value from the flattened YAML config
# Usage: get_config "key_name" "default_value"
get_config() {
    local key="$1"
    local default="$2"
    local value

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "$default"
        return
    fi

    # Extract value: match "key: value" or "key:value", strip quotes
    value=$(grep -E "^${key}:" "$CONFIG_FILE" 2>/dev/null | sed 's/^[^:]*:[[:space:]]*//' | sed "s/['\"]//g" | head -1)

    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Check if a boolean config is enabled (true/yes/1)
is_enabled() {
    local value
    value=$(get_config "$1" "false")
    case "$value" in
        true|True|TRUE|yes|Yes|YES|1) return 0 ;;
        *) return 1 ;;
    esac
}

# Wait for interface to exist
wait_for_interface() {
    local max_wait=30
    local waited=0

    log "Waiting for $INTERFACE interface..."
    while ! ip link show "$INTERFACE" &>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [ $waited -ge $max_wait ]; then
            log "ERROR: $INTERFACE interface not found after ${max_wait}s"
            return 1
        fi
    done
    log "$INTERFACE interface is ready"
}

# Main impairment application logic
apply_impairments() {
    # Check if any impairment is enabled
    local netem_enabled tbf_enabled
    netem_enabled=$(is_enabled "netem_enabled" && echo "true" || echo "false")
    tbf_enabled=$(is_enabled "tbf_enabled" && echo "true" || echo "false")

    if [ "$netem_enabled" = "false" ] && [ "$tbf_enabled" = "false" ]; then
        log "No impairments configured, skipping"
        return 0
    fi

    local name
    name=$(get_config "name" "unnamed")
    log "Applying impairment profile: $name"

    # Clear any existing qdiscs
    tc qdisc del dev "$INTERFACE" root 2>/dev/null || true

    # Track parent for chaining
    local netem_parent="root"
    local netem_handle=""

    # Apply TBF (Token Bucket Filter) for bandwidth limiting
    if is_enabled "tbf_enabled"; then
        local rate burst limit
        rate=$(get_config "tbf_rate" "1gbit")
        burst=$(get_config "tbf_burst" "128kbit")
        limit=$(get_config "tbf_limit" "100000")

        log "Applying TBF: rate=$rate burst=$burst limit=$limit"
        tc qdisc add dev "$INTERFACE" root handle 1: tbf \
            rate "$rate" \
            burst "$burst" \
            limit "$limit"

        # Netem will be chained under TBF (TBF is classless, so parent is 1: not 1:1)
        netem_parent="parent 1:"
        netem_handle="handle 10:"
    fi

    # Apply netem for delay/loss/corruption
    if is_enabled "netem_enabled"; then
        # Build netem command incrementally
        local netem_cmd="tc qdisc add dev $INTERFACE $netem_parent $netem_handle netem"

        # Delay, jitter, and delay correlation
        local delay_ms jitter_ms delay_dist delay_corr
        delay_ms=$(get_config "delay_ms" "0")
        jitter_ms=$(get_config "jitter_ms" "0")
        delay_dist=$(get_config "delay_distribution" "")
        delay_corr=$(get_config "delay_correlation" "0")

        if [ "$delay_ms" != "0" ]; then
            netem_cmd="$netem_cmd delay ${delay_ms}ms"
            if [ "$jitter_ms" != "0" ]; then
                netem_cmd="$netem_cmd ${jitter_ms}ms"
                # Add correlation before distribution (tc syntax requirement)
                if [ "$delay_corr" != "0" ]; then
                    netem_cmd="$netem_cmd ${delay_corr}%"
                fi
                if [ -n "$delay_dist" ]; then
                    netem_cmd="$netem_cmd distribution $delay_dist"
                fi
            fi
        fi

        # Packet loss
        local loss_pct loss_corr
        loss_pct=$(get_config "loss_percent" "0")
        loss_corr=$(get_config "loss_correlation" "0")

        if [ "$loss_pct" != "0" ]; then
            netem_cmd="$netem_cmd loss ${loss_pct}%"
            if [ "$loss_corr" != "0" ]; then
                netem_cmd="$netem_cmd ${loss_corr}%"
            fi
        fi

        # Packet corruption
        local corrupt_pct
        corrupt_pct=$(get_config "corrupt_percent" "0")
        if [ "$corrupt_pct" != "0" ]; then
            netem_cmd="$netem_cmd corrupt ${corrupt_pct}%"
        fi

        # Packet reordering
        local reorder_pct reorder_corr
        reorder_pct=$(get_config "reorder_percent" "0")
        reorder_corr=$(get_config "reorder_correlation" "0")

        if [ "$reorder_pct" != "0" ]; then
            netem_cmd="$netem_cmd reorder ${reorder_pct}%"
            if [ "$reorder_corr" != "0" ]; then
                netem_cmd="$netem_cmd ${reorder_corr}%"
            fi
        fi

        # Packet duplication
        local duplicate_pct
        duplicate_pct=$(get_config "duplicate_percent" "0")
        if [ "$duplicate_pct" != "0" ]; then
            netem_cmd="$netem_cmd duplicate ${duplicate_pct}%"
        fi

        log "Applying netem: $netem_cmd"
        eval "$netem_cmd"
    fi

    # Log final configuration
    log "Final tc configuration:"
    tc -s qdisc show dev "$INTERFACE" 2>&1 | while read -r line; do
        log "  $line"
    done

    log "Impairment profile '$name' applied successfully"
}

# Main execution
main() {
    log "Starting impairment application"
    log "Config file: $CONFIG_FILE"

    if [ ! -f "$CONFIG_FILE" ]; then
        log "Config file not found, no impairments to apply"
        exit 0
    fi

    wait_for_interface || exit 1
    apply_impairments

    log "Impairment setup complete"
}

main "$@"
