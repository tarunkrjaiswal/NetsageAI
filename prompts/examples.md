# NetSage AI — Few-Shot Examples

These three examples are embedded in the prompt to anchor the AI's output format.

---

## Example 1 — VLAN Not Allowed on Trunk (High Confidence)

**Input**

```
Category: VLAN
Symptom: PC1 in VLAN 30 cannot reach the server; VLAN 10 and VLAN 20 work fine.
Topology: PC1(VLAN30) -> SW1 -> [trunk] -> SW2 -> Server
Show Output:
show vlan brief
VLAN Name      Status    Ports
30   FINANCE    active    Fa0/4
show interfaces trunk
Port  Mode  Encapsulation  Status     Native vlan
Gi0/1 on    802.1q         trunking   1
VLANs allowed on trunk: 1-29,31-4094
```

**Expected JSON Output**

```json
{
  "root_cause": "VLAN 30 is not allowed on the trunk link between SW1 and SW2",
  "osi_layer": "Layer 2",
  "confidence": "High",
  "evidence": [
    "'VLANs allowed on trunk: 1-29,31-4094' explicitly excludes VLAN 30",
    "VLAN 30 (FINANCE) is active on the local switch (Fa0/4) but traffic cannot cross the trunk",
    "VLAN 10 and 20 are within the allowed range 1-29, explaining why they work"
  ],
  "next_command": "show interfaces trunk",
  "fix_steps": [
    "On SW1: switchport trunk allowed vlan add 30",
    "On SW2: switchport trunk allowed vlan add 30",
    "Verify: show interfaces trunk — VLAN 30 should appear in allowed list",
    "Test connectivity from PC1 (VLAN 30) to the server"
  ]
}
```

---

## Example 2 — Missing Return Route (Medium Confidence)

**Input**

```
Category: Routing
Symptom: PC1 can reach the server but the server cannot reply to PC1.
Topology: PC1(192.168.10.10) -> R1 -> R2 -> Server(192.168.30.10)
Show Output:
show ip route (R1)
C 192.168.10.0/24 is directly connected, Gi0/0
C 192.168.20.0/24 is directly connected, Gi0/1
S 192.168.30.0/24 [1/0] via 192.168.20.2
```

**Expected JSON Output**

```json
{
  "root_cause": "R2 likely has no return route to PC1's subnet (192.168.10.0/24), causing one-way connectivity",
  "osi_layer": "Layer 3",
  "confidence": "Medium",
  "evidence": [
    "R1 has a route to 192.168.30.0/24 via 192.168.20.2 — traffic from PC1 to server can reach R2",
    "Only R1's routing table is shown; R2's routing table is not available to confirm the return path",
    "One-way connectivity (PC1 can reach server but not vice versa) is a classic asymmetric routing symptom"
  ],
  "next_command": "show ip route (on R2)",
  "fix_steps": [
    "Log into R2 and run: show ip route",
    "If 192.168.10.0/24 is absent from R2's table, add: ip route 192.168.10.0 255.255.255.0 192.168.20.1",
    "Verify R2 can ping 192.168.10.10",
    "Test bidirectional connectivity from PC1 to server"
  ]
}
```

---

## Example 3 — ACL Blocking Traffic (High Confidence)

**Input**

```
Category: ACL
Symptom: PC1 can ping the server but cannot connect to the web server on port 80.
Topology: PC1(192.168.10.10) -> R1 -> Server(192.168.30.10)
Show Output:
show access-lists
Extended IP access list 110
 10 permit icmp 192.168.10.0 0.0.0.255 any
 20 deny tcp 192.168.10.0 0.0.0.255 any eq 80 (34 matches)
 30 permit ip any any
show run | section interface Gi0/1
 ip access-group 110 in
```

**Expected JSON Output**

```json
{
  "root_cause": "ACL 110 rule 20 explicitly denies TCP port 80 (HTTP) from the PC subnet",
  "osi_layer": "Layer 3/4",
  "confidence": "High",
  "evidence": [
    "ACL entry: 'deny tcp 192.168.10.0 0.0.0.255 any eq 80 (34 matches)' — 34 packets already dropped",
    "ACL 110 is applied inbound on Gi0/1 — the interface facing the PC network",
    "ICMP is permitted (rule 10) which explains why ping works but HTTP does not"
  ],
  "next_command": "show access-lists 110",
  "fix_steps": [
    "Remove the deny rule: no access-list 110 20  (or use named ACL equivalent)",
    "If HTTP blocking is intentional, add a specific permit before it: access-list 110 15 permit tcp 192.168.10.0 0.0.0.255 host 192.168.30.10 eq 80",
    "Verify: show access-lists 110 — hit count on deny should stop increasing",
    "Test HTTP access from PC1 to the server"
  ]
}
```
