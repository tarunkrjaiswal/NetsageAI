"""
ai/mock_diagnosis.py
Pre-written structured diagnoses for offline / demo mode.
One mock per category; selected by keyword matching on symptom + show_output.
"""


_MOCKS: dict[str, dict] = {

    "VLAN": {
        "root_cause": "VLAN not allowed on trunk link or inter-VLAN routing not configured",
        "osi_layer": "Layer 2",
        "confidence": "Medium",
        "evidence": [
            "Symptom indicates cross-VLAN communication failure",
            "'show vlan brief' or 'show interfaces trunk' output suggests VLAN isolation",
            "Devices in the same VLAN can communicate but cross-VLAN traffic fails"
        ],
        "next_command": "show interfaces trunk",
        "fix_steps": [
            "Run 'show interfaces trunk' to verify VLAN is in allowed list",
            "If missing: switchport trunk allowed vlan add <vlan-id>",
            "Verify inter-VLAN routing interface (SVI or sub-interface) exists",
            "Check 'ip routing' is enabled on L3 switch or router-on-a-stick is configured",
            "Test connectivity after each change"
        ]
    },

    "ROUTING": {
        "root_cause": "Missing static or dynamic route to the destination network",
        "osi_layer": "Layer 3",
        "confidence": "Medium",
        "evidence": [
            "PC can reach its default gateway (Layer 2 and local routing OK)",
            "Traffic fails beyond the first hop — indicates a routing gap",
            "'show ip route' does not show the destination network"
        ],
        "next_command": "show ip route",
        "fix_steps": [
            "Run 'show ip route' on each router along the path",
            "Identify which router is missing the route to the destination subnet",
            "Add static route: ip route <dest-network> <mask> <next-hop>",
            "Verify symmetric routing — return path must also exist",
            "Test with ping and traceroute after adding routes"
        ]
    },

    "DHCP": {
        "root_cause": "DHCP pool misconfiguration or relay agent missing",
        "osi_layer": "Layer 3",
        "confidence": "Medium",
        "evidence": [
            "Client cannot obtain an IP address automatically",
            "DHCP pool may exist but network/gateway settings may be incorrect",
            "Remote subnet clients may be missing 'ip helper-address' on gateway interface"
        ],
        "next_command": "show ip dhcp pool",
        "fix_steps": [
            "Run 'show ip dhcp pool' to verify pool network and default-router",
            "Run 'show ip dhcp binding' to check for existing leases",
            "Verify excluded addresses do not consume the entire pool",
            "For remote subnets: add 'ip helper-address <server-ip>' on gateway interface",
            "Test: release and renew client IP, or use 'debug ip dhcp server events'"
        ]
    },

    "DNS": {
        "root_cause": "DNS server IP is unreachable or incorrectly configured on clients",
        "osi_layer": "Layer 7",
        "confidence": "Medium",
        "evidence": [
            "Hosts can communicate by IP address but not by hostname",
            "DNS server IP configured on clients may be incorrect or unreachable",
            "Ping to configured DNS server address may time out"
        ],
        "next_command": "ping <dns-server-ip>",
        "fix_steps": [
            "Verify the DNS server IP configured on the client is correct",
            "Ping the DNS server from the affected host",
            "If DNS server is unreachable, fix routing to it first",
            "Update DHCP pool: 'dns-server <correct-ip>'",
            "Test: nslookup <hostname> from affected client"
        ]
    },

    "GATEWAY": {
        "root_cause": "Default gateway is incorrect, unreachable, or on the wrong subnet",
        "osi_layer": "Layer 3",
        "confidence": "Medium",
        "evidence": [
            "PC can communicate within its subnet but not outside",
            "Default gateway IP may be on a different subnet than the PC",
            "Router interface may be administratively shut down"
        ],
        "next_command": "show ip interface brief",
        "fix_steps": [
            "Verify gateway IP is in the same subnet as the client: ip address <pc-ip> <mask>",
            "Confirm router interface is up: show ip interface brief",
            "If interface is down: no shutdown in interface config",
            "Update client gateway or DHCP pool default-router",
            "Test connectivity to gateway with ping"
        ]
    },

    "ACL": {
        "root_cause": "Access Control List is blocking traffic — check rule order and direction",
        "osi_layer": "Layer 3/4",
        "confidence": "Medium",
        "evidence": [
            "Traffic blocked selectively (e.g., ping works but HTTP fails, or one subnet blocked)",
            "'show access-lists' may show hit counts on deny rules",
            "ACL applied on wrong interface or wrong direction (in vs out)"
        ],
        "next_command": "show access-lists",
        "fix_steps": [
            "Run 'show access-lists' — look for deny entries with non-zero hit counts",
            "Run 'show run | include access-group' to find where ACLs are applied",
            "Verify ACL direction: 'in' filters arriving traffic, 'out' filters leaving traffic",
            "Remove or reorder deny rules as needed",
            "Ensure implicit deny at end does not block required management access"
        ]
    },

    "NAT": {
        "root_cause": "NAT misconfiguration — inside/outside interfaces or ACL may be wrong",
        "osi_layer": "Layer 3",
        "confidence": "Medium",
        "evidence": [
            "Internal hosts cannot reach external network despite NAT being configured",
            "'show ip nat translations' shows no entries — translation is not occurring",
            "NAT ACL may not match the inside source addresses"
        ],
        "next_command": "show ip nat translations",
        "fix_steps": [
            "Run 'show ip nat translations' — if empty, NAT is not triggering",
            "Verify 'ip nat inside' on LAN interface and 'ip nat outside' on WAN interface",
            "Check NAT ACL matches the LAN subnet: access-list 1 permit 192.168.x.0 0.0.0.255",
            "Verify 'ip nat inside source list <acl> interface <wan-if> overload'",
            "Test after changes: ping external IP from inside host"
        ]
    },

    "WIRELESS": {
        "root_cause": "Wireless authentication failure or VLAN/SSID misconfiguration",
        "osi_layer": "Layer 2",
        "confidence": "Medium",
        "evidence": [
            "Wireless clients cannot authenticate or receive wrong VLAN assignment",
            "PSK mismatch or SSID-to-VLAN mapping error is likely",
            "Guest isolation may not be enabled allowing cross-network access"
        ],
        "next_command": "show run | section dot11",
        "fix_steps": [
            "Verify WPA2 PSK matches on both AP and client",
            "Run 'show run | section dot11' to check SSID-VLAN mapping",
            "Ensure switchport connected to AP is a trunk allowing the mapped VLAN",
            "For guest isolation: enable 'client isolation' or 'bridge-group' separation",
            "Test: associate a wireless client and run 'show ip dhcp binding'"
        ]
    },
}

_DEFAULT_MOCK: dict = {
    "root_cause": "Unable to determine root cause from provided information",
    "osi_layer": "Unknown",
    "confidence": "Low",
    "evidence": [
        "Insufficient show-command output to identify the fault",
        "More diagnostic commands are needed"
    ],
    "next_command": "show ip interface brief",
    "fix_steps": [
        "Run 'show ip interface brief' to check interface status",
        "Run 'show ip route' to check routing table",
        "Run 'show vlan brief' if VLAN issues are suspected",
        "Provide the output to NetSage AI for further analysis"
    ]
}


def mock_diagnose(symptom: str, topology: str, show_output: str,
                  category: str = "General") -> dict:
    """
    Return a pre-written diagnosis appropriate for the given category.
    Tries to pick the best match; falls back to a generic response.
    """
    cat_upper = category.strip().upper()

    # Direct category match
    if cat_upper in _MOCKS:
        return dict(_MOCKS[cat_upper])

    # Keyword fallback — search symptom + show_output
    combined = (symptom + " " + show_output).lower()
    keyword_map = {
        "VLAN":     ["vlan", "trunk", "switchport", "native"],
        "ROUTING":  ["route", "routing", "ospf", "eigrp", "bgp", "nexthop", "next-hop"],
        "DHCP":     ["dhcp", "pool", "binding", "helper", "ip address"],
        "DNS":      ["dns", "name", "resolve", "nslookup", "domain"],
        "GATEWAY":  ["gateway", "default-router", "gw", "no route to host"],
        "ACL":      ["acl", "access-list", "permit", "deny", "access-group"],
        "NAT":      ["nat", "overload", "translation", "pat", "masquerade"],
        "WIRELESS": ["wireless", "ssid", "wpa", "psk", "dot11", "wifi", "ap"],
    }
    for cat, keywords in keyword_map.items():
        if any(kw in combined for kw in keywords):
            return dict(_MOCKS[cat])

    return dict(_DEFAULT_MOCK)
