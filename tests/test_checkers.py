from checker import has_conflict, run_all_checks
from checker.parsers import (
    parse_show_interfaces_trunk,
    parse_show_ip_interface_brief,
    parse_show_ip_route,
    parse_show_vlan_brief,
)


TRUNK_FAILURE = """
SW1# show interfaces trunk
Gi0/1       Mode auto    not-trunking   1
SW2# show interfaces trunk
Gi0/1       Mode auto    not-trunking   1
"""


def test_vlan_checker_detects_unformed_trunk():
    results = run_all_checks("", TRUNK_FAILURE, "VLAN")

    trunk_mode = next(result for result in results if result["rule"] == "trunk_mode")
    assert trunk_mode["status"] == "fail"
    assert "auto" in trunk_mode["detail"]


def test_vlan_checker_detects_native_vlan_mismatch():
    output = """
    SW1 Gi0/1 native vlan 1
    SW2 Gi0/1 native vlan 99
    """

    results = run_all_checks("", output, "VLAN")

    native_vlan = next(
        result for result in results if result["rule"] == "native_vlan_mismatch"
    )
    assert native_vlan["status"] == "fail"


def test_conflict_detection_flags_unrelated_ai_diagnosis():
    results = [{"rule": "trunk_mode", "status": "fail", "detail": "trunk failed"}]

    assert has_conflict(results, "The DNS server is unreachable.") is True
    assert has_conflict(results, "The trunk mode is not forming.") is False


def test_structured_parsers_extract_cisco_tables():
    vlans = parse_show_vlan_brief("10 USERS active\n20 SERVERS active")
    assert vlans[1] == {"id": 20, "name": "SERVERS", "status": "active"}

    trunks = parse_show_interfaces_trunk(
        "Port        Mode         Encapsulation  Status        Native vlan\n"
        "Gi0/1       auto         802.1q         not-trunking  1"
    )
    assert trunks[0]["status"] == "not-trunking"
    assert trunks[0]["native_vlan"] == 1

    routes = parse_show_ip_route("C 192.168.10.0/24 is directly connected\n"
                                 "S 192.168.30.0/24 [1/0] via 192.168.20.1")
    assert routes[1]["via"] == "192.168.20.1"

    interfaces = parse_show_ip_interface_brief(
        "Interface              IP-Address      OK? Method Status                Protocol\n"
        "Gi0/1                  192.168.1.1     YES manual up                    up"
    )
    assert interfaces[0]["interface"] == "Gi0/1"
    assert interfaces[0]["status"] == "up"
