"""
ai/diagnosis.py — AI Diagnosis Engine

Calls either Google Gemini or OpenAI to produce a structured JSON diagnosis.
Falls back to mock_diagnosis if MOCK_AI=True or if no API key is configured.
"""
import json
import re
import sys
import os
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from ai.mock_diagnosis import mock_diagnose


# ── Prompt loading ───────────────────────────────────────────────────────────

def _load_prompt() -> str:
    base   = Path(__file__).resolve().parent.parent / "prompts"
    system = (base / "diagnose_prompt.md").read_text()
    examples = (base / "examples.md").read_text()
    return f"{system}\n\n---\n\n{examples}"


SYSTEM_PROMPT = _load_prompt()


# ── JSON extraction helper ───────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Extract the first valid JSON object from an LLM response that may
    contain surrounding prose or markdown fences.
    """
    # Strip markdown fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No valid JSON object found in AI response.")


def _validate(diag: dict) -> dict:
    """Ensure required keys exist with sensible defaults."""
    defaults = {
        "root_cause":   "Unable to determine — insufficient evidence",
        "osi_layer":    "Unknown",
        "confidence":   "Low",
        "evidence":     [],
        "next_command": "show ip interface brief",
        "fix_steps":    ["Gather more information before applying a fix."],
    }
    for k, v in defaults.items():
        diag.setdefault(k, v)
    # Normalise confidence capitalisation
    conf = diag["confidence"].strip().capitalize()
    if conf not in ("High", "Medium", "Low"):
        conf = "Low"
    diag["confidence"] = conf
    return diag


# ── Gemini client ────────────────────────────────────────────────────────────

def _call_gemini(user_message: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=30000),
    )
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return response.text


# ── OpenAI client ────────────────────────────────────────────────────────────

def _call_openai(user_message: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": user_message},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


# ── Public API ───────────────────────────────────────────────────────────────

def diagnose(symptom: str, topology: str, show_output: str,
             category: str = "General") -> dict:
    """
    Analyse a network case and return a structured diagnosis dict.

    Returns:
        {
          root_cause, osi_layer, confidence, evidence (list),
          next_command, fix_steps (list)
        }
    """
    # Offline / mock mode
    if config.MOCK_AI or not _api_key_available():
        return mock_diagnose(symptom, topology, show_output, category)

    user_message = (
        f"Category: {category}\n\n"
        f"Symptom:\n{symptom}\n\n"
        f"Topology:\n{topology}\n\n"
        f"Show Output:\n{show_output}"
    )

    try:
        if config.AI_PROVIDER == "openai":
            raw = _call_openai(user_message)
        else:
            raw = _call_gemini(user_message)

        diag = _extract_json(raw)
        return _validate(diag)

    except Exception as exc:
        print(f"[NetSage AI] LLM call failed: {exc}", flush=True)
        if config.MOCK_AI:
            return mock_diagnose(symptom, topology, show_output, category)
        raise RuntimeError("Gemini diagnosis failed. Check the API key and model configuration.") from exc


def _api_key_available() -> bool:
    if config.AI_PROVIDER == "openai":
        return bool(config.OPENAI_API_KEY and
                    config.OPENAI_API_KEY != "")
    return bool(config.GEMINI_API_KEY and
                config.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_HERE")
