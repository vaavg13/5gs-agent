"""Helpers for forcing traffic through the UE tunnel interface."""

from __future__ import annotations

import ipaddress
import re

from inspect_ai.tool import ToolError


_IPV4_RE = re.compile(r"inet (\d+\.\d+\.\d+\.\d+)/")


async def prepare_tunnel_path(ue, target: str) -> tuple[str, str]:
    """Resolve a target and pin its route to the UE tunnel.

    Returns:
        Tuple of (target_ip, ue_tunnel_ip).
    """
    addr_result = await ue.exec(["ip", "addr", "show", "uesimtun0"], timeout=10)
    if not addr_result.success:
        raise ToolError("PDU session is not active: uesimtun0 is unavailable.")

    match = _IPV4_RE.search(addr_result.stdout)
    if not match:
        raise ToolError("Unable to determine UE tunnel IP from uesimtun0.")
    tunnel_ip = match.group(1)

    try:
        ipaddress.ip_address(target)
        target_ip = target
    except ValueError:
        resolve = await ue.exec(
            ["sh", "-lc", f"getent hosts '{target}' | awk 'NR==1 {{print $1}}'"],
            timeout=10,
        )
        target_ip = resolve.stdout.strip()
        if not resolve.success or not target_ip:
            raise ToolError(f"Unable to resolve target '{target}'.")

    route = await ue.exec(
        ["ip", "route", "replace", f"{target_ip}/32", "dev", "uesimtun0"],
        timeout=10,
    )
    if not route.success:
        raise ToolError(f"Unable to route {target_ip} through uesimtun0: {route.stderr or route.stdout}")

    return target_ip, tunnel_ip
