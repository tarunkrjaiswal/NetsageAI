"""
checker/ip_checker.py
Deterministic rules for IP addressing, subnet masks, and default gateway.
All functions operate purely on text (show-command output + optional extra fields).
"""
import ipaddress
import re


# ─── Internal helpers ────────────────────────────────────────────────────────

def _result(rule: str, status: str, detail: str) -> dict:
    return {"rule": rule, "status": status, "detail": detail}


def _extract_ipv4_addresses(text: str) -> list[str]:
    """Extract all IPv4 addresses (including prefix length) from text."""
    return re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b', text)


def _extract_ip_mask_pairs(text: str) -> list[tuple[str, str]]:
    """
    Find patterns like '192.168.1.1 255.255.255.0' in show ip interface brief
    or interface config blocks.
    """
    pattern = r'(\d{1,3}(?:\.\d{1,3}){3})\s+(255\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    return re.findall(pattern, text)


def _to_network(ip: str, mask: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    except ValueError:
        return None


# ─── Individual Rules ────────────────────────────────────────────────────────

def check_duplicate_ips(show_output: str) -> dict:
    """Detect duplicate IPv4 host addresses in the show output."""
    ips = _extract_ipv4_addresses(show_output)
    # Strip prefix lengths for comparison
    bare = [ip.split("/")[0] for ip in ips if not ip.endswith(".0") and not ip.endswith(".255")]
    seen, dupes = set(), set()
    for ip in bare:
        if ip in seen:
            dupes.add(ip)
        seen.add(ip)
    if dupes:
        return _result(
            "duplicate_ip",
            "fail",
            f"Duplicate IP address(es) detected: {', '.join(sorted(dupes))}. "
            "Duplicate IPs cause ARP conflicts and intermittent connectivity."
        )
    return _result("duplicate_ip", "pass", "No duplicate IP addresses detected.")


def check_subnet_masks(show_output: str) -> dict:
    """Verify every subnet mask in the output is a valid contiguous mask."""
    pairs = _extract_ip_mask_pairs(show_output)
    invalid = []
    for ip, mask in pairs:
        try:
            ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
        except ValueError:
            invalid.append(f"{ip}/{mask}")
    if invalid:
        return _result(
            "subnet_mask",
            "fail",
            f"Invalid subnet mask(s) found: {', '.join(invalid)}. "
            "Non-contiguous masks are not supported in IOS."
        )
    if not pairs:
        return _result("subnet_mask", "warn",
                       "No IP/mask pairs found in output — unable to validate subnet masks.")
    return _result("subnet_mask", "pass",
                   f"All {len(pairs)} subnet mask(s) are valid.")


def check_gateway_mismatch(show_output: str, extra: dict) -> dict:
    """
    Check that the client's default gateway belongs to the same subnet as the client IP.
    extra must supply 'pc_ip', 'pc_mask', 'gateway' (all as strings) for this check to run.
    """
    pc_ip  = extra.get("pc_ip",  "").strip()
    pc_mask = extra.get("pc_mask", "").strip()
    gw      = extra.get("gateway",  "").strip()

    if not (pc_ip and pc_mask and gw):
        # Try to auto-extract from ipconfig-style output
        ip_match  = re.search(r'IPv4 Address[.\s:]+(\d+\.\d+\.\d+\.\d+)', show_output)
        mask_match = re.search(r'Subnet Mask[.\s:]+(\d+\.\d+\.\d+\.\d+)', show_output)
        gw_match   = re.search(r'Default Gateway[.\s:]+(\d+\.\d+\.\d+\.\d+)', show_output)
        if ip_match:  pc_ip  = ip_match.group(1)
        if mask_match: pc_mask = mask_match.group(1)
        if gw_match:   gw      = gw_match.group(1)

    if not (pc_ip and pc_mask and gw):
        return _result("gateway_mismatch", "warn",
                       "Gateway mismatch check skipped — pc_ip, pc_mask, gateway not provided.")

    net = _to_network(pc_ip, pc_mask)
    if net is None:
        return _result("gateway_mismatch", "warn",
                       f"Cannot parse network from {pc_ip}/{pc_mask}.")
    try:
        gw_addr = ipaddress.IPv4Address(gw)
    except ValueError:
        return _result("gateway_mismatch", "warn", f"Invalid gateway address: {gw}.")

    if gw_addr not in net:
        return _result(
            "gateway_mismatch",
            "fail",
            f"⚠ Gateway mismatch: PC {pc_ip}/{pc_mask} is on network {net.network_address}/{net.prefixlen} "
            f"but gateway {gw} is NOT in that subnet. PC cannot reach its gateway."
        )
    return _result("gateway_mismatch", "pass",
                   f"Gateway {gw} is valid for subnet {net.network_address}/{net.prefixlen}.")


def check_private_address_on_wan(show_output: str) -> dict:
    """Warn if a private RFC1918 address appears on a WAN/outside interface."""
    # Look for lines that mention WAN / outside / Serial alongside private IPs
    wan_lines = [l for l in show_output.splitlines()
                 if any(kw in l.lower() for kw in ("serial", "wan", "outside", "gi0/1"))]
    private_ranges = [
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    ]
    found = []
    for line in wan_lines:
        for ip_str in _extract_ipv4_addresses(line):
            try:
                addr = ipaddress.IPv4Address(ip_str.split("/")[0])
                if any(addr in r for r in private_ranges):
                    found.append(f"{ip_str} (line: {line.strip()})")
            except ValueError:
                pass
    if found:
        return _result("private_on_wan", "warn",
                       f"Private address on potential WAN interface: {'; '.join(found)}. "
                       "Verify NAT/PAT is configured if internet access is required.")
    return _result("private_on_wan", "pass",
                   "No private addresses detected on WAN-tagged interfaces.")


# ─── Aggregate ───────────────────────────────────────────────────────────────

def check_all_ip_rules(show_output: str, extra: dict) -> list[dict]:
    return [
        check_duplicate_ips(show_output),
        check_subnet_masks(show_output),
        check_gateway_mismatch(show_output, extra),
        check_private_address_on_wan(show_output),
    ]
