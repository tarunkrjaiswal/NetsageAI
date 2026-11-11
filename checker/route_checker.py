"""
checker/route_checker.py
Deterministic rules for routing table and default route validation.
"""
import re
import ipaddress
from .parsers import parse_show_ip_route


def _result(rule: str, status: str, detail: str) -> dict:
    return {"rule": rule, "status": status, "detail": detail}


def _extract_routes(show_ip_route: str) -> list[dict]:
    """
    Parse 'show ip route' output into a list of route dicts.
    Returns: [{"prefix": "192.168.10.0/24", "type": "C", "via": "192.168.20.1"}, ...]
    """
    return parse_show_ip_route(show_ip_route)


def check_default_route(show_output: str) -> dict:
    """Flag if no default route exists and traffic likely needs one."""
    has_default = (
        "0.0.0.0/0" in show_output or
        "Gateway of last resort is" in show_output and
        "not set" not in show_output.lower()
    )
    if not has_default and "show ip route" in show_output.lower():
        return _result(
            "default_route",
            "warn",
            "No default route (0.0.0.0/0) found in routing table. "
            "Hosts requiring internet or cross-domain access will have no path. "
            "Add: 'ip route 0.0.0.0 0.0.0.0 <next-hop>'."
        )
    if has_default:
        return _result("default_route", "pass", "Default route is present in routing table.")
    return _result("default_route", "pass", "Route check not applicable to this output.")


def check_route_to_destination(show_output: str) -> dict:
    """
    Look for the destination network mentioned in the symptom text but absent
    from the routing table.  Works by finding all /24 networks in context then
    checking them against parsed routes.
    """
    routes  = _extract_routes(show_output)
    if not routes:
        return _result("route_to_dest", "warn",
                       "No routing table entries parsed — paste 'show ip route' output.")

    routed_prefixes = {r["prefix"] for r in routes}

    # Find all /24 networks mentioned anywhere in the output
    all_networks = set(re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}',
                                  show_output))
    unrouted = all_networks - routed_prefixes

    if unrouted:
        return _result(
            "route_to_dest",
            "fail",
            f"Network(s) mentioned but absent from routing table: "
            f"{', '.join(sorted(unrouted))}. "
            "Traffic to these destinations will be dropped. "
            "Add a static route or verify routing protocol advertisement."
        )
    return _result("route_to_dest", "pass",
                   "All referenced networks appear in the routing table.")


def check_next_hop_reachability(show_output: str) -> dict:
    """
    For each static route via a next-hop, verify the next-hop is itself
    reachable (i.e., in a directly connected subnet shown in the table).
    """
    routes = _extract_routes(show_output)
    connected = [r["prefix"] for r in routes if r["type"] == "C"]
    static    = [r for r in routes if r["type"] == "S" and r["via"] != "directly connected"]

    unreachable = []
    for s in static:
        via = s["via"]
        try:
            via_addr = ipaddress.IPv4Address(via)
        except ValueError:
            continue
        reachable = any(
            via_addr in ipaddress.IPv4Network(c, strict=False)
            for c in connected
        )
        if not reachable:
            unreachable.append(f"{s['prefix']} via {via}")

    if unreachable:
        return _result(
            "next_hop_reachable",
            "fail",
            f"Static route next-hop(s) not in any directly connected subnet: "
            f"{'; '.join(unreachable)}. "
            "The next-hop must be reachable from this router."
        )
    if static:
        return _result("next_hop_reachable", "pass",
                       "All static route next-hops appear reachable.")
    return _result("next_hop_reachable", "pass",
                   "No static routes found — next-hop check not applicable.")


def check_routing_loop(show_output: str) -> dict:
    """
    Basic routing loop detection: if two routers both point default routes
    at each other's addresses, flag it.
    """
    # Find 'S* 0.0.0.0/0 via X.X.X.X' entries
    defaults = re.findall(r'S\*?\s+0\.0\.0\.0/0.*?via\s+(\d+\.\d+\.\d+\.\d+)',
                          show_output, re.IGNORECASE)
    # Find all directly connected addresses
    connected_ips = re.findall(
        r'C\s+\d+\.\d+\.\d+\.\d+/\d+.*?(\d+\.\d+\.\d+\.\d+)',
        show_output
    )
    loop_candidates = [d for d in defaults if d in connected_ips]
    if loop_candidates:
        return _result(
            "routing_loop",
            "fail",
            f"Possible routing loop: default route(s) point back to a directly-connected "
            f"address ({', '.join(loop_candidates)}). Verify the next-hop is on the correct upstream router."
        )
    return _result("routing_loop", "pass", "No obvious routing loops detected.")


# ─── Aggregate ───────────────────────────────────────────────────────────────

def check_all_route_rules(show_output: str, category: str) -> list[dict]:
    results = []
    if category.upper() in ("ROUTING", "GATEWAY", "NAT", "DHCP", "DNS", "VLAN"):
        results.append(check_default_route(show_output))
        results.append(check_route_to_destination(show_output))
        results.append(check_next_hop_reachability(show_output))
        results.append(check_routing_loop(show_output))
    return results
