import pytest

from ai.diagnosis import _extract_json, _validate


def test_extract_json_handles_markdown_fences():
    diagnosis = _extract_json(
        '```json\n{"root_cause": "Missing VLAN", "confidence": "high"}\n```'
    )

    assert diagnosis["root_cause"] == "Missing VLAN"


def test_extract_json_rejects_non_json_response():
    with pytest.raises(ValueError, match="No valid JSON"):
        _extract_json("No structured diagnosis was returned.")


def test_validate_adds_defaults_and_normalizes_confidence():
    diagnosis = _validate({"root_cause": "Trunk failure", "confidence": "HIGH"})

    assert diagnosis["confidence"] == "High"
    assert diagnosis["osi_layer"] == "Unknown"
    assert diagnosis["evidence"] == []
    assert diagnosis["fix_steps"]
