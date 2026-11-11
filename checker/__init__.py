"""checker/__init__.py — Aggregate rule-checker entry point."""
from .ip_checker        import check_all_ip_rules
from .vlan_checker      import check_all_vlan_rules
from .route_checker     import check_all_route_rules
from .interface_checker import check_all_interface_rules


def run_all_checks(symptom: str, show_output: str, category: str,
                   extra: dict | None = None) -> list[dict]:
    """
    Run every applicable deterministic rule against the supplied show-output.

    Returns a list of result dicts:
        {
          "rule":    str,          # short rule name
          "status":  "pass"|"warn"|"fail",
          "detail":  str           # human-readable finding
        }
    """
    extra = extra or {}
    results: list[dict] = []

    results.extend(check_all_ip_rules(show_output, extra))
    results.extend(check_all_vlan_rules(show_output, category))
    results.extend(check_all_route_rules(show_output, category))
    results.extend(check_all_interface_rules(show_output))

    return results


def has_conflict(rule_results: list[dict], ai_diagnosis: str) -> bool:
    """
    Simple heuristic: if any rule says 'fail' and the AI diagnosis
    doesn't mention the affected concept, flag a potential conflict.
    """
    failed_concepts = {r["rule"] for r in rule_results if r["status"] == "fail"}
    if not failed_concepts:
        return False
    ai_lower = ai_diagnosis.lower()
    for concept in failed_concepts:
        # If the AI doesn't reference the failing concept at all, flag it
        key = concept.lower().replace("_", " ").split()[0]
        if key not in ai_lower:
            return True
    return False
