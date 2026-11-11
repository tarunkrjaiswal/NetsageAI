"""
checker/vlan_checker.py
Deterministic rules for VLAN configuration.
"""
import re
from .parsers import parse_show_vlan_brief, parse_show_interfaces_trunk


def _result(rule: str, status: str, detail: str) -> dict:
    return {"rule": rule, "status": status, "detail": detail}


def _extract_active_vlans(show_vlan_brief: str) -> set[str]:
    """
    Parse 'show vlan brief' output.
    Returns a set of active VLAN IDs (as strings).
    """
    return {
        str(vlan["id"]) for vlan in parse_show_vlan_brief(show_vlan_brief)
        if vlan["status"] == "active"
    }


def _extract_trunk_vlans(show_interfaces_trunk: str) -> list[str]:
    """
    Parse 'VLANs allowed on trunk' line and return a flat list of VLAN ID strings.
    Handles ranges like 1-29,31-4094.
    """
    allowed = []
    in_allowed = False
    for line in show_interfaces_trunk.splitlines():
        if "vlans allowed on trunk" in line.lower():
            in_allowed = True
            # Sometimes the list is on the same line
            parts = line.split(":", 1)
            if len(parts) > 1:
                _expand_vlan_list(parts[1].strip(), allowed)
            continue
        if in_allowed:
            if re.match(r'^\s*[\d,\-]+\s*$', line):
                _expand_vlan_list(line.strip(), allowed)
            else:
                in_allowed = False
    return allowed


def _expand_vlan_list(vlan_str: str, target: list) -> None:
    """Expand '1-10,20,30-35' into individual VLAN IDs."""
    for part in vlan_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-")
                target.extend(str(v) for v in range(int(start), int(end) + 1))
            except ValueError:
                pass
        elif part.isdigit():
            target.append(part)


def _extract_native_vlans(show_interfaces_trunk: str) -> list[str]:
    """Return all native VLAN values mentioned in 'show interfaces trunk' output."""
    return re.findall(r'native vlan\s+(\d+)', show_interfaces_trunk, re.IGNORECASE)


# ─── Rules ───────────────────────────────────────────────────────────────────

def check_vlan_present(show_output: str) -> dict:
    """
    Detect references to a VLAN in text (e.g., 'VLAN 30') that does not
    appear as active in 'show vlan brief' output.
    """
    active = _extract_active_vlans(show_output)
    if not active:
        return _result("vlan_present", "warn",
                       "No 'show vlan brief' output found — cannot verify VLAN existence.")

    # Look for VLAN IDs mentioned in symptom/other lines but not in vlan brief
    mentioned = set(re.findall(r'(?:vlan|vl)\s*(\d+)', show_output, re.IGNORECASE))
    missing = mentioned - active - {"1"}  # VLAN 1 always exists

    if missing:
        return _result("vlan_present", "fail",
                       f"VLAN(s) referenced but not active in 'show vlan brief': "
                       f"{', '.join(sorted(missing, key=int))}. "
                       "Create the VLAN on the switch with 'vlan <id>'.")
    return _result("vlan_present", "pass",
                   f"All referenced VLANs are present. Active: {sorted(active, key=int)}")


def check_trunk_allowed(show_output: str) -> dict:
    """Warn if 'VLANs allowed on trunk' is found and cross-check against active VLANs."""
    trunk_vlans = _extract_trunk_vlans(show_output)
    active_vlans = _extract_active_vlans(show_output)

    if not trunk_vlans:
        # May not be a trunk issue
        if "trunk" in show_output.lower():
            return _result("trunk_allowed", "warn",
                           "Trunk output detected but VLAN allowed-list could not be parsed.")
        return _result("trunk_allowed", "pass",
                       "No trunk output found — trunk check not applicable.")

    missing_on_trunk = active_vlans - set(trunk_vlans) - {"1"}
    if missing_on_trunk:
        return _result("trunk_allowed", "fail",
                       f"VLAN(s) active on switch but NOT allowed on trunk: "
                       f"{', '.join(sorted(missing_on_trunk, key=int))}. "
                       "Use 'switchport trunk allowed vlan add <id>' to permit them.")
    return _result("trunk_allowed", "pass",
                   "All active VLANs are allowed on the trunk link.")


def check_native_vlan_mismatch(show_output: str) -> dict:
    """Detect native VLAN mismatch when two sides are shown in output."""
    natives = _extract_native_vlans(show_output)
    if len(natives) < 2:
        return _result("native_vlan_mismatch", "pass",
                       "Only one native VLAN value found — no mismatch detectable from this output.")
    unique = set(natives)
    if len(unique) > 1:
        return _result(
            "native_vlan_mismatch",
            "fail",
            f"Native VLAN mismatch detected: values {unique} seen on different ports. "
            "This causes STP topology changes and possible traffic black-holing. "
            "Set both ends to the same native VLAN with 'switchport trunk native vlan <id>'."
        )
    return _result("native_vlan_mismatch", "pass",
                   f"Native VLAN is consistent: VLAN {list(unique)[0]}.")


def check_trunk_mode(show_output: str) -> dict:
    """Detect if both trunk sides are set to 'auto' (trunk will not form)."""
    parsed_trunks = parse_show_interfaces_trunk(show_output)
    if any(trunk["status"] == "not-trunking" for trunk in parsed_trunks):
        return _result(
            "trunk_mode", "fail",
            "Parsed trunk status shows 'not-trunking' — the trunk has not been established."
        )
    modes = re.findall(r'mode\s+(auto|desirable|on|access|trunk)',
                       show_output, re.IGNORECASE)
    if modes.count("auto") >= 2:
        return _result(
            "trunk_mode",
            "fail",
            "Both trunk ends appear to be set to 'auto' — DTP will not negotiate a trunk. "
            "Set at least one side to 'switchport mode trunk' or 'desirable'."
        )
    if "not-trunking" in show_output.lower():
        return _result("trunk_mode", "fail",
                       "Port shows 'not-trunking' — trunk has not been established.")
    return _result("trunk_mode", "pass", "Trunk mode configuration appears correct.")


# ─── Aggregate ───────────────────────────────────────────────────────────────

def check_all_vlan_rules(show_output: str, category: str) -> list[dict]:
    results = []
    if category.upper() in ("VLAN", "ROUTING", "WIRELESS"):
        results.append(check_vlan_present(show_output))
        results.append(check_trunk_allowed(show_output))
        results.append(check_native_vlan_mismatch(show_output))
        results.append(check_trunk_mode(show_output))
    return results
