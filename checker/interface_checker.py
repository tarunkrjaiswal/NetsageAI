"""
checker/interface_checker.py
Deterministic rules for interface status (up/down, admin-down).
"""
import re
from .parsers import parse_show_ip_interface_brief


def _result(rule: str, status: str, detail: str) -> dict:
    return {"rule": rule, "status": status, "detail": detail}


def _parse_interface_brief(show_output: str) -> list[dict]:
    """
    Parse 'show ip interface brief' lines.
    Returns: [{"interface": str, "ip": str, "status": str, "protocol": str}]
    """
    return parse_show_ip_interface_brief(show_output)


def check_interfaces_up(show_output: str) -> dict:
    """Flag any interface that is down or admin-down."""
    ifaces = _parse_interface_brief(show_output)
    if not ifaces:
        # Try looser match
        down_lines = [l.strip() for l in show_output.splitlines()
                      if re.search(r'(admin.?down|line protocol is down)', l, re.IGNORECASE)]
        if down_lines:
            return _result(
                "interface_up",
                "fail",
                f"Interface(s) detected as down: {'; '.join(down_lines[:3])}. "
                "Use 'no shutdown' to bring up the interface."
            )
        return _result("interface_up", "warn",
                       "No 'show ip interface brief' table found — interface status unknown.")

    down = [i for i in ifaces if "down" in i["status"] or "down" in i["protocol"]]
    admin_down = [i for i in ifaces if "admin" in i["status"]]

    findings = []
    if admin_down:
        names = ", ".join(i["interface"] for i in admin_down)
        findings.append(
            f"Administratively shut down: {names}. "
            "Apply 'no shutdown' in interface config mode."
        )
    if down and not admin_down:
        names = ", ".join(i["interface"] for i in down)
        findings.append(
            f"Interface(s) down (physical/protocol): {names}. "
            "Check cable, speed/duplex, or remote side."
        )

    if findings:
        return _result("interface_up", "fail", " | ".join(findings))
    return _result("interface_up", "pass",
                   f"All {len(ifaces)} parsed interface(s) are up/up.")


def check_ip_assigned(show_output: str) -> dict:
    """Flag interfaces with 'unassigned' IP in show ip interface brief."""
    ifaces = _parse_interface_brief(show_output)
    unassigned = [i for i in ifaces if i["ip"] in ("unassigned", "")]
    up_unassigned = [i for i in unassigned if "up" in i["status"]]

    if up_unassigned:
        names = ", ".join(i["interface"] for i in up_unassigned)
        return _result(
            "ip_assigned",
            "fail",
            f"Active interface(s) with no IP address assigned: {names}. "
            "Configure an IP address with 'ip address <addr> <mask>'."
        )
    return _result("ip_assigned", "pass",
                   "All active interfaces have IP addresses assigned.")


def check_duplex_mismatch(show_output: str) -> dict:
    """Detect duplex mismatch indicators in show interfaces output."""
    if "duplex mismatch" in show_output.lower() or \
       ("half-duplex" in show_output.lower() and "full-duplex" in show_output.lower()):
        return _result(
            "duplex_mismatch",
            "warn",
            "Possible duplex mismatch detected in interface output. "
            "Set both sides to the same duplex with 'duplex full' or use 'duplex auto'."
        )
    return _result("duplex_mismatch", "pass", "No duplex mismatch indicators found.")


def check_error_counters(show_output: str) -> dict:
    """Flag high input/output error counters that indicate physical layer problems."""
    error_pattern = re.compile(
        r'(\d+)\s+input errors|(\d+)\s+output errors|(\d+)\s+CRC', re.IGNORECASE
    )
    high_errors = []
    for m in error_pattern.finditer(show_output):
        count = int(next(g for g in m.groups() if g is not None))
        if count > 100:
            high_errors.append(f"{count} {m.group(0).strip()}")

    if high_errors:
        return _result(
            "error_counters",
            "warn",
            f"High error counters detected: {', '.join(high_errors)}. "
            "This may indicate Layer 1 issues (bad cable, SFP, or speed mismatch)."
        )
    return _result("error_counters", "pass", "No significant interface error counters found.")


# ─── Aggregate ───────────────────────────────────────────────────────────────

def check_all_interface_rules(show_output: str) -> list[dict]:
    return [
        check_interfaces_up(show_output),
        check_ip_assigned(show_output),
        check_duplex_mismatch(show_output),
        check_error_counters(show_output),
    ]
