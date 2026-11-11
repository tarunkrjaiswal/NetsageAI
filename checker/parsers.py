"""Structured parsers for common Cisco IOS show-command output."""
import ipaddress
import re


def parse_show_vlan_brief(output: str) -> list[dict]:
    """Parse VLAN IDs, names, and status from ``show vlan brief``."""
    vlans = []
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\S+)\s+(active|suspend|act/unsup)\b",
                         line, re.IGNORECASE)
        if match:
            vlans.append({
                "id": int(match.group(1)),
                "name": match.group(2),
                "status": match.group(3).lower(),
            })
    return vlans


def parse_show_interfaces_trunk(output: str) -> list[dict]:
    """Parse trunk status rows from ``show interfaces trunk``."""
    trunks = []
    in_status_table = False
    for line in output.splitlines():
        if re.search(r"Port\s+Mode\s+Encapsulation\s+Status\s+Native vlan", line,
                     re.IGNORECASE):
            in_status_table = True
            continue
        if not in_status_table:
            continue
        parts = line.split()
        if len(parts) >= 5 and re.match(r"^(trunking|not-trunking|trunk)", parts[3],
                                        re.IGNORECASE):
            trunks.append({
                "interface": parts[0],
                "mode": parts[1].lower(),
                "status": parts[3].lower(),
                "native_vlan": int(parts[4]) if parts[4].isdigit() else None,
            })
    return trunks


def parse_show_ip_route(output: str) -> list[dict]:
    """Parse route type, prefix, and next-hop from ``show ip route``."""
    routes = []
    pattern = re.compile(
        r"^\s*([CSRBODEILX\*]+)\s+"
        r"(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})"
        r"(?:.*?via\s+(\d{1,3}(?:\.\d{1,3}){3}))?",
        re.MULTILINE,
    )
    for match in pattern.finditer(output):
        prefix = match.group(2)
        try:
            ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        routes.append({
            "type": match.group(1).replace("*", "").strip(),
            "prefix": prefix,
            "via": match.group(3) or "directly connected",
        })
    return routes


def parse_show_ip_interface_brief(output: str) -> list[dict]:
    """Parse interface, IP, status, and protocol columns."""
    interfaces = []
    in_table = False
    for line in output.splitlines():
        if re.match(r"\s*Interface\s+IP-Address", line, re.IGNORECASE):
            in_table = True
            continue
        if not in_table:
            continue
        parts = line.split()
        if len(parts) >= 6:
            interfaces.append({
                "interface": parts[0],
                "ip": parts[1],
                "status": parts[-2].lower(),
                "protocol": parts[-1].lower(),
            })
    return interfaces
