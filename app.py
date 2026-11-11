"""
app.py — NetSage AI Flask Application
"""
import csv
import json
import os
import sys
import secrets
import hmac
from pathlib import Path
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify, abort, session)
from collections import defaultdict, deque
from functools import wraps
from threading import Lock
from time import monotonic

# ── Bootstrap path ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
from database import db
from checker  import run_all_checks, has_conflict
from ai.diagnosis import diagnose

# ── App init ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not config.DEBUG,
    TRUSTED_HOSTS=os.getenv("TRUSTED_HOSTS", "").split(",") if os.getenv("TRUSTED_HOSTS") else None,
)
_rate_buckets = defaultdict(deque)
_rate_lock = Lock()

def _rate_limit(rule: str):
    """Small per-process limiter; run one Gunicorn worker for this demo deployment."""
    parts = rule.split()
    limit = int(parts[0])
    period = 60 if parts[-1].startswith("minute") else 3600
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            now = monotonic()
            key = (request.remote_addr or "unknown", request.endpoint or view.__name__)
            with _rate_lock:
                bucket = _rate_buckets[key]
                while bucket and now - bucket[0] >= period:
                    bucket.popleft()
                if len(bucket) >= limit:
                    return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429
                bucket.append(now)
            return view(*args, **kwargs)
        return wrapped
    return decorate

# Flask-Limiter is intentionally not required: this lightweight demo limiter is
# process-local. Use a shared Redis-backed limiter before scaling to multiple workers/instances.


CASES_CSV = BASE_DIR / "data" / "cases.csv"


@app.context_processor
def inject_csrf_token():
    def csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token
    return {"csrf_token": csrf_token}


@app.before_request
def protect_browser_posts():
    # Browser form submissions use a session-bound CSRF token. JSON API routes
    # are intentionally separate and do not rely on cookie-based authentication.
    if request.method == "POST" and request.endpoint in {"analyze", "submit_review"}:
        expected = session.get("_csrf_token", "")
        supplied = request.form.get("csrf_token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self' https: data:; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https:; connect-src 'self' https:")
    return response


# ── Database initialisation ───────────────────────────────────────────────────
def init_app():
    db.init_db()
    _seed_cases()
    _seed_responsible_ai()


def _seed_cases():
    """Load cases.csv into DB on first run (idempotent via INSERT OR IGNORE)."""
    if not CASES_CSV.exists():
        return
    with open(CASES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace from keys/values
            clean = {k.strip(): v.strip() for k, v in row.items()}
            db.insert_case(clean)


def _seed_responsible_ai():
    """
    Pre-seed 6 Responsible AI cases (AI was wrong, human corrected).
    Idempotent — checks if records already exist.
    """
    with db.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE decision IN ('edit','reject')"
        ).fetchone()[0]
    if count >= 6:
        return  # Already seeded

    seeds = [
        {
            "case_ref": "004", "category": "ACL",
            "symptom": "PC1 in VLAN 30 cannot reach the server even though VLAN 10 and VLAN 20 work fine",
            "topology": "PC1(VLAN30) -> SW1 -> Router -> Server",
            "show_output": "show vlan brief\nVLAN 30 active Fa0/4\nshow interfaces trunk\nVLANs allowed: 1-29,31-4094",
            "root_cause": "ACL may be blocking VLAN 30 traffic on the router",
            "osi_layer": "Layer 3/4", "confidence": "Medium",
            "evidence": json.dumps(["ACL mismatch suspected", "Other VLANs work"]),
            "next_command": "show access-lists",
            "fix_steps": json.dumps(["Review ACL rules", "Remove deny entry for VLAN 30"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "edit",
                "human_root_cause": "VLAN 30 is not allowed on the trunk link",
                "human_correction": "ACL was not the issue. 'show interfaces trunk' shows VLAN 30 excluded from allowed list.",
                "reason": "Rule checker flagged VLAN 30 missing from trunk — AI missed this and incorrectly blamed ACL."
            }
        },
        {
            "case_ref": "008", "category": "DNS",
            "symptom": "All PCs lose connectivity to the server after a new trunk was configured",
            "topology": "PC1 -> SW1 ==(trunk)== SW2 -> Server",
            "show_output": "show interfaces trunk\nSW1 native: 1\nSW2 native: 99",
            "root_cause": "DNS server is unreachable after trunk reconfiguration",
            "osi_layer": "Layer 7", "confidence": "Low",
            "evidence": json.dumps(["Connectivity lost after trunk change", "DNS service suspected"]),
            "next_command": "ping dns-server",
            "fix_steps": json.dumps(["Verify DNS server connectivity", "Check DNS configuration"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "reject",
                "human_root_cause": "Native VLAN mismatch between SW1 (VLAN 1) and SW2 (VLAN 99)",
                "human_correction": "Native VLAN mismatch causes STP issues and traffic black-holing. Not a DNS issue.",
                "reason": "AI incorrectly blamed DNS. The trunk show output clearly shows different native VLANs."
            }
        },
        {
            "case_ref": "013", "category": "Routing",
            "symptom": "PC1 can ping its default gateway but cannot reach the 192.168.30.0/24 server network",
            "topology": "PC1 -> R1 -> R2 -> Server(192.168.30.0/24)",
            "show_output": "show ip route (R1)\nC 192.168.10.0/24 directly connected\nS 192.168.30.0/24 via 192.168.20.99",
            "root_cause": "ACL on R2 may be blocking traffic to 192.168.30.0/24",
            "osi_layer": "Layer 3/4", "confidence": "Medium",
            "evidence": json.dumps(["Traffic fails at R2", "ACL could block transit traffic"]),
            "next_command": "show access-lists",
            "fix_steps": json.dumps(["Check ACLs on R2", "Remove blocking rules"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "edit",
                "human_root_cause": "Incorrect next-hop in static route — 192.168.20.99 does not exist",
                "human_correction": "Static route next-hop 192.168.20.99 is incorrect; R2 is at 192.168.20.2. Route is broken before reaching R2.",
                "reason": "AI blamed ACL without verifying the static route next-hop. Rule checker caught unreachable next-hop."
            }
        },
        {
            "case_ref": "019", "category": "DHCP",
            "symptom": "New PC cannot get an IP address — all DHCP requests are dropped",
            "topology": "PC1 -> SW1 -> R1(DHCP Server)",
            "show_output": "show ip dhcp pool\nPool LAN\nNetwork: 192.168.10.0/24\nExcluded: 192.168.10.1 to 192.168.10.254",
            "root_cause": "DHCP server pool is not configured or server is unreachable",
            "osi_layer": "Layer 3", "confidence": "Medium",
            "evidence": json.dumps(["DHCP requests dropped", "No binding created"]),
            "next_command": "show ip dhcp pool",
            "fix_steps": json.dumps(["Configure DHCP pool", "Verify server reachability"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "edit",
                "human_root_cause": "Entire address range excluded — no addresses available in DHCP pool",
                "human_correction": "Pool exists but 'ip dhcp excluded-address 192.168.10.1 192.168.10.254' excludes all usable addresses. AI missed the excluded range.",
                "reason": "AI suggested pool doesn't exist — it does exist but all addresses are excluded."
            }
        },
        {
            "case_ref": "026", "category": "VLAN",
            "symptom": "Intermittent connectivity between devices in different VLANs after SW2 was added",
            "topology": "PC1(VLAN10) -> SW1 -> SW2 -> PC2(VLAN20)",
            "show_output": "show interfaces trunk\nSW1 Gi0/1 mode: auto not-trunking\nSW2 Gi0/1 mode: auto not-trunking",
            "root_cause": "VLAN 20 may be missing from the switch configuration",
            "osi_layer": "Layer 2", "confidence": "Low",
            "evidence": json.dumps(["VLANs work intermittently", "SW2 recently added"]),
            "next_command": "show vlan brief",
            "fix_steps": json.dumps(["Check VLAN 20 exists on SW2", "Add missing VLAN"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "reject",
                "human_root_cause": "Trunk link not established — both sides set to DTP auto mode",
                "human_correction": "Output clearly shows 'not-trunking' on both sides with mode 'auto'. DTP auto+auto never forms a trunk. VLAN 20 exists on both switches.",
                "reason": "AI missed the obvious 'not-trunking' status. Trunk must be set to 'on' or 'desirable' on at least one side."
            }
        },
        {
            "case_ref": "031", "category": "NAT",
            "symptom": "Internal PCs can reach each other but cannot access the internet despite NAT being configured",
            "topology": "PC1(192.168.10.10) -> R1(NAT) -> ISP",
            "show_output": "show ip nat translations\n(no entries)\nip nat inside source list 1 interface Gi0/1 overload\naccess-list 1 permit 10.0.0.0 0.0.0.255",
            "root_cause": "R1 WAN interface Gi0/1 may be down causing NAT failures",
            "osi_layer": "Layer 1/3", "confidence": "Medium",
            "evidence": json.dumps(["NAT translation table empty", "No entries showing"]),
            "next_command": "show ip interface brief",
            "fix_steps": json.dumps(["Check WAN interface status", "Apply no shutdown if down"]),
            "rule_results": json.dumps([]),
            "ai_conflict": 0,
            "review": {
                "decision": "edit",
                "human_root_cause": "NAT ACL matches wrong subnet (10.0.0.0/24 instead of 192.168.10.0/24)",
                "human_correction": "ACL 1 permits 10.0.0.0/24 which is the WAN subnet. LAN hosts (192.168.10.x) never match, so no translations occur. Interface is up.",
                "reason": "AI focused on interface status. The ACL mismatch is the actual fault — clearly visible in the show run output."
            }
        },
    ]

    for s in seeds:
        review = s.pop("review")
        diag_id = db.insert_diagnosis(s)
        review["diagnosis_id"] = diag_id
        db.insert_review(review)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    cases = db.get_all_cases()
    categories = sorted({c["category"] for c in cases})
    return render_template("index.html", categories=categories, cases=cases)


@app.route("/analyze", methods=["POST"])
@_rate_limit("8 per minute")
def analyze():
    symptom     = request.form.get("symptom", "").strip()
    topology    = request.form.get("topology", "").strip()
    show_output = request.form.get("show_output", "").strip()
    category    = request.form.get("category", "General").strip()
    case_ref    = request.form.get("case_ref", "").strip() or None

    if not symptom:
        flash("Please enter a symptom description.", "error")
        return redirect(url_for("index"))

    # ── Python Rule Checker ──────────────────────────────────────────────
    extra = {
        "pc_ip":   request.form.get("pc_ip", "").strip(),
        "pc_mask": request.form.get("pc_mask", "").strip(),
        "gateway": request.form.get("gateway", "").strip(),
    }
    rule_results = run_all_checks(symptom, show_output, category, extra)

    # ── AI Diagnosis Engine ──────────────────────────────────────────────
    diag = diagnose(symptom, topology, show_output, category)

    # ── Conflict Detection ───────────────────────────────────────────────
    conflict = has_conflict(rule_results, diag.get("root_cause", ""))

    # ── Persist ──────────────────────────────────────────────────────────
    record = {
        "case_ref":     case_ref,
        "category":     category,
        "symptom":      symptom,
        "topology":     topology,
        "show_output":  show_output,
        **diag,
        "rule_results": rule_results,
        "ai_conflict":  conflict,
    }
    diag_id = db.insert_diagnosis(record)

    return redirect(url_for("diagnosis_page", diag_id=diag_id))


@app.route("/diagnosis/<int:diag_id>")
def diagnosis_page(diag_id: int):
    diag = db.get_diagnosis(diag_id)
    if not diag:
        abort(404)
    review = db.get_review_for_diagnosis(diag_id)
    return render_template("diagnosis.html", diag=diag, review=review)


@app.route("/review/<int:diag_id>", methods=["POST"])
@_rate_limit("12 per minute")
def submit_review(diag_id: int):
    diag = db.get_diagnosis(diag_id)
    if not diag:
        abort(404)

    existing = db.get_review_for_diagnosis(diag_id)
    if existing:
        flash("This diagnosis has already been reviewed.", "warning")
        return redirect(url_for("diagnosis_page", diag_id=diag_id))

    decision         = request.form.get("decision", "").strip().lower()
    human_root_cause = request.form.get("human_root_cause", "").strip()
    human_correction = request.form.get("human_correction", "").strip()
    reason           = request.form.get("reason", "").strip()
    fix_applied      = request.form.get("fix_applied", "").strip()
    verified_before  = request.form.get("verified_before", "").strip() or None
    verified_after   = request.form.get("verified_after", "").strip() or None

    if decision not in ("accept", "edit", "reject"):
        flash("Invalid decision — must be accept, edit, or reject.", "error")
        return redirect(url_for("diagnosis_page", diag_id=diag_id))

    review = {
        "diagnosis_id":    diag_id,
        "decision":        decision,
        "human_root_cause": human_root_cause or diag.get("root_cause"),
        "human_correction": human_correction,
        "reason":          reason,
        "verified_before": verified_before,
        "fix_applied":     fix_applied,
        "verified_after":  verified_after,
    }
    db.insert_review(review)
    flash(f"Review submitted — {decision.upper()}.", "success")
    return redirect(url_for("diagnosis_page", diag_id=diag_id))


@app.route("/cases")
def cases_page():
    cases = db.get_all_cases()
    category_filter = request.args.get("category", "")
    if category_filter:
        cases = [c for c in cases if c["category"] == category_filter]
    categories = sorted({c["category"] for c in db.get_all_cases()})
    return render_template("cases.html", cases=cases,
                           categories=categories,
                           selected=category_filter)


@app.route("/load-case/<case_id>")
def load_case(case_id: str):
    case = db.get_case(case_id)
    if not case:
        abort(404)
    all_cases = db.get_all_cases()
    categories = sorted({c["category"] for c in all_cases})
    return render_template("index.html", prefill=case,
                           categories=categories, cases=all_cases)


@app.route("/history")
def history():
    reviews = db.get_all_reviews()
    return render_template("review.html", reviews=reviews)


@app.route("/dashboard")
def dashboard():
    stats = db.get_dashboard_stats()
    rai_log = db.get_responsible_ai_log()
    return render_template("dashboard.html", stats=stats, rai_log=rai_log)


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_dashboard_stats())


def _api_error(message: str, status: int):
    return jsonify({"error": message}), status


def _api_text(payload: dict, field: str, required: bool = False) -> str:
    value = payload.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required.")
    if len(value) > 100_000:
        raise ValueError(f"{field} exceeds the 100000 character limit.")
    return value


@app.route("/api/health")
def api_health():
    try:
        db.check_database()
    except Exception:
        app.logger.exception("Database health check failed")
        return jsonify({"status": "error", "service": "netsage-ai", "database": "unavailable"}), 503
    return jsonify({"status": "ok", "service": "netsage-ai", "database": "ok"})


@app.route("/api/cases")
def api_cases():
    cases = db.get_all_cases()
    category = request.args.get("category", "").strip()
    if category:
        cases = [case for case in cases if case["category"] == category]
    # Never expose ground-truth answers through the public API.
    public_fields = ("case_id", "category", "symptom", "topology", "show_output", "osi_layer", "concept", "severity")
    safe_cases = [{key: case.get(key) for key in public_fields} for case in cases]
    return jsonify({"cases": safe_cases, "count": len(safe_cases)})


@app.route("/api/diagnose", methods=["POST"])
@_rate_limit("8 per minute")
def api_diagnose():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("Request body must be a JSON object.", 400)
    try:
        symptom = _api_text(payload, "symptom", required=True)
        show_output = _api_text(payload, "show_output", required=True)
        topology = _api_text(payload, "topology")
        category = _api_text(payload, "category") or "General"
        case_ref = _api_text(payload, "case_ref") or None
        extra = {
            "pc_ip": _api_text(payload, "pc_ip"),
            "pc_mask": _api_text(payload, "pc_mask"),
            "gateway": _api_text(payload, "gateway"),
        }
    except ValueError as exc:
        return _api_error(str(exc), 400)

    rule_results = run_all_checks(symptom, show_output, category, extra)
    diag = diagnose(symptom, topology, show_output, category)
    record = {
        "case_ref": case_ref,
        "category": category,
        "symptom": symptom,
        "topology": topology,
        "show_output": show_output,
        **diag,
        "rule_results": rule_results,
        "ai_conflict": has_conflict(rule_results, diag.get("root_cause", "")),
    }
    diag_id = db.insert_diagnosis(record)
    return jsonify({"id": diag_id, "diagnosis": diag,
                    "rule_results": rule_results,
                    "ai_conflict": record["ai_conflict"]}), 201


@app.route("/api/diagnoses/<int:diag_id>")
def api_diagnosis(diag_id: int):
    diagnosis = db.get_diagnosis(diag_id)
    if not diagnosis:
        return _api_error("Diagnosis not found.", 404)
    review = db.get_review_for_diagnosis(diag_id)
    # Keep raw CLI output and topology private; the public API returns the result only.
    public_diagnosis = {key: diagnosis.get(key) for key in (
        "id", "case_ref", "category", "root_cause", "osi_layer", "confidence",
        "evidence", "next_command", "fix_steps", "rule_results", "ai_conflict", "created_at"
    )}
    public_diagnosis["review"] = review
    return jsonify(public_diagnosis)


@app.route("/api/diagnoses/<int:diag_id>/reviews", methods=["POST"])
@_rate_limit("12 per minute")
def api_review(diag_id: int):
    if not db.get_diagnosis(diag_id):
        return _api_error("Diagnosis not found.", 404)
    if db.get_review_for_diagnosis(diag_id):
        return _api_error("This diagnosis has already been reviewed.", 409)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _api_error("Request body must be a JSON object.", 400)
    decision = payload.get("decision")
    if decision not in ("accept", "edit", "reject"):
        return _api_error("decision must be accept, edit, or reject.", 400)

    try:
        review = {
            "diagnosis_id": diag_id,
            "decision": decision,
            "human_root_cause": _api_text(payload, "human_root_cause"),
            "human_correction": _api_text(payload, "human_correction"),
            "reason": _api_text(payload, "reason"),
            "verified_before": _api_text(payload, "verified_before") or None,
            "fix_applied": _api_text(payload, "fix_applied"),
            "verified_after": _api_text(payload, "verified_after") or None,
        }
    except ValueError as exc:
        return _api_error(str(exc), 400)
    if review["verified_before"] not in (None, "pass", "fail") or review["verified_after"] not in (None, "pass", "fail"):
        return _api_error("verification values must be 'pass' or 'fail'.", 400)
    review_id = db.insert_review(review)
    return jsonify({"id": review_id, "review": review}), 201


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_app()
    app.run(debug=config.DEBUG, port=config.PORT)
