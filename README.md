# NetSage AI 🌐⚡
**AI-Assisted Cisco Network Troubleshooting System**

> *AI recommends → Rules verify → Human decides → Network is fixed → Result is verified.*

---

## Overview

NetSage AI is a complete Applied AI + Networking project that helps junior network engineers diagnose faults in Cisco/Packet Tracer networks. It combines three "brains":

| Brain | Role |
|---|---|
| 🤖 **AI Engine** (Gemini / GPT-4o) | Understands the symptom and produces an evidence-based, structured diagnosis |
| 🐍 **Python Rule Checker** | Deterministically validates IPs, VLANs, routes, and interfaces |
| 👨‍💼 **Human Reviewer** | Makes the final Accept / Edit / Reject decision |

---

## Features

- **32 pre-loaded troubleshooting cases** across 8 fault categories (VLAN, Routing, DHCP, DNS, Gateway, ACL, NAT, Wireless)
- **Structured AI diagnosis**: root cause, OSI layer, confidence (High/Medium/Low), evidence list, next command, fix steps
- **Python Rule Checker**: duplicate IPs, gateway mismatch, missing VLANs, trunk errors, missing routes, interface status
- **AI ↔ Rule Checker conflict detection** with visual banner
- **Human review workflow**: Accept / Edit / Reject with correction notes and verification
- **Responsible AI Log**: 6 pre-seeded + live cases where human corrected the AI
- **Dashboard**: KPI cards + 4 Chart.js charts + Responsible AI table
- **Offline/Mock mode**: works without any API key

---

## Project Structure

```
netsage-ai/
├── app.py                   # Flask app — all routes
├── wsgi.py                  # Production WSGI entry point
├── Dockerfile
├── docker-compose.yml
├── config.py                # API keys, settings
├── requirements.txt
├── data/
│   └── cases.csv            # 32 troubleshooting cases
├── prompts/
│   ├── diagnose_prompt.md   # LLM system prompt
│   └── examples.md          # 3 few-shot examples
├── checker/                 # Python Rule Checker
│   ├── ip_checker.py
│   ├── parsers.py
│   ├── vlan_checker.py
│   ├── route_checker.py
│   └── interface_checker.py
├── ai/
│   ├── diagnosis.py         # Gemini / OpenAI client
│   └── mock_diagnosis.py    # Offline fallback
├── database/
│   ├── schema.sql
│   └── db.py
├── render.yaml             # Render Blueprint deployment configuration
├── supabase/
│   └── migrations/         # PostgreSQL schema for Supabase
├── templates/               # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── diagnosis.html
│   ├── review.html
│   ├── cases.html
│   └── dashboard.html
└── static/
    ├── css/style.css
    └── js/app.js
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements-dev.txt
```

### 2. Configure secrets
Never place API keys in source files. Copy `.env.example` to `.env`, or set
the variables in your shell/deployment platform:
```powershell
$env:GEMINI_API_KEY = "your-key-here"
$env:SECRET_KEY = "generate-a-long-random-secret"
$env:MOCK_AI = "false"
```
For local offline use, set `MOCK_AI=true` and omit the Gemini key.

### 3. Run tests
```bash
python -m pytest -q
```
The test suite covers VLAN rule detection, AI response parsing, conflict
detection, and the Flask analysis workflow without calling a live AI provider.

### 4. Run
```bash
python app.py
```
Open http://localhost:5000

### Production / Docker
For a local container deployment:
```bash
docker compose up --build
```
Open http://localhost:5000. Set `GEMINI_API_KEY`, `SECRET_KEY`, and
`MOCK_AI=false` in `.env` to enable live Gemini diagnosis. Without a key,
use `MOCK_AI=true` for a fully offline container.

### Render + Supabase PostgreSQL deployment

The database adapter supports both local SQLite and PostgreSQL. For hosted deployment,
create a Supabase project and use its **Session Pooler** connection string as `DATABASE_URL`
(recommended for a small Flask web service). The app creates its tables and seeds the
32-case dataset plus the six demonstration Responsible AI records at startup.

1. Create a Supabase project and copy the PostgreSQL Session Pooler URI.
2. Create a Render **Web Service** from this GitHub repository and select the Docker runtime.
3. Set these Render environment variables:
   - `FLASK_DEBUG=false`
   - `SECRET_KEY` = a newly generated random secret (at least 32 random bytes)
   - `DATABASE_URL` = Supabase Session Pooler connection URI
   - `AI_PROVIDER=gemini`
   - `GEMINI_API_KEY` = your own Gemini API key
   - `GEMINI_MODEL=gemini-2.5-flash`
   - `MOCK_AI=false` (use `true` if you want an offline mock demo)
4. Deploy and verify `/api/health` returns both `status: ok` and `database: ok`.

Never commit `.env`, database files, API keys, or Flask secrets. The `.env.example` file
contains placeholders only. If a real key was ever placed in a shared archive or repository,
revoke it and generate a replacement.

The demo uses a small in-process rate limiter and the Docker command runs one Gunicorn
worker to keep its counters consistent. Before scaling to multiple instances, replace the process-local limiter with a
shared Redis-backed rate limiter. The free
Render instance may sleep when idle; first requests after inactivity can be delayed. Supabase
Free projects have usage limits and may pause after prolonged inactivity; check the current
plan terms before relying on it for continuous availability.

On Linux, the production WSGI server can also be started directly:
```bash
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 60 wsgi:app
```

### API
The JSON API is available while the Flask app is running:

```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/cases?category=VLAN
```

Create a diagnosis:
```bash
curl -X POST http://localhost:5000/api/diagnose ^
  -H "Content-Type: application/json" ^
  -d "{\"category\":\"VLAN\",\"symptom\":\"VLAN 20 is unreachable\",\"show_output\":\"show interfaces trunk ...\"}"
```

The API also provides `GET /api/diagnoses/<id>` and
`POST /api/diagnoses/<id>/reviews`. Diagnosis requests require `symptom` and
`show_output`; review decisions must be `accept`, `edit`, or `reject`. The public
`/api/cases` endpoint deliberately omits `expected_fault` so the dataset ground truth
is not exposed to visitors before they attempt a diagnosis. Browser form submissions use session-bound CSRF tokens. Diagnosis and review writes
are rate-limited per client IP. The limiter is process-local; use shared Redis before scaling.

---

## Public demo and privacy

This repository is intended for a portfolio demonstration. Do not paste credentials,
production network configurations, customer information, or other sensitive command output
into a publicly hosted instance. The demo's diagnosis and review records are stored in the
configured shared database and may be visible through its history/dashboard pages. Add
user authentication and per-user data isolation before using it for private or production data.

## Usage

### Analyze a case
1. Go to **Analyze** — select an issue category
2. Paste your Cisco show-command output
3. Click **Analyze** — AI + Rule Checker run in parallel
4. Review the diagnosis panel

### Load a dataset case
- Click **Cases** in the nav to browse all 32 cases
- Click **Load →** to pre-fill the analysis form

### Human Review
On the diagnosis page:
- **Accept** — AI diagnosis is correct
- **Edit** — Correct the root cause and explain what AI missed
- **Reject** — AI was wrong; provide the correct diagnosis

### Dashboard
- View agreement rate, decision distribution, category/severity breakdown
- Scroll to the **Responsible AI Log** to see all human corrections

---

## Dataset Summary

| Category | Cases | Key Faults |
|---|---|---|
| VLAN | 5 | Missing VLAN, trunk not formed, native VLAN mismatch, VLAN not allowed on trunk |
| Routing | 5 | Missing route, return route, default route, OSPF area, routing loop |
| DHCP | 4 | Pool misconfigured, excluded range, relay missing, stale binding |
| DNS | 4 | Wrong DNS IP, no internet on DNS server, static misconfiguration, primary down |
| Gateway | 4 | Subnet mismatch, interface shutdown, no onward route, stale client config |
| ACL | 4 | Port blocked, all traffic denied, wrong direction, management locked out |
| NAT | 3 | ACL mismatch, wrong outside interface, target host unreachable |
| Wireless | 3 | PSK mismatch, VLAN mapping wrong, guest isolation disabled |

---

## Responsible AI Principle

> **The AI never auto-approves a fix.** Every diagnosis must be reviewed by a human engineer before being accepted.

The system tracks every case where the human overrode the AI. This is the Responsible AI Log — visible on the Dashboard — demonstrating that AI is a tool to assist, not replace, human judgment.

---

## Architecture

```
User Input (Symptom + Show Output)
         │
         ├──→ Python Rule Checker (deterministic)
         │
         └──→ AI Diagnosis Engine (Gemini/GPT-4o)
                    │
              Conflict Detection
                    │
              Human Review Panel
             /       │        \
          Accept    Edit     Reject
             │       │        │
             └───────┼────────┘
                     │
               SQLite (local) / PostgreSQL (hosted)
                     │
                 Dashboard
```

---

## Evaluation Checklist

- ✅ ≥ 30 cases across multiple fault types (`data/cases.csv`)
- ✅ AI uses actual show-command evidence in diagnosis
- ✅ Structured JSON output (root_cause, confidence, evidence, next_command, fix_steps)
- ✅ Python deterministic rule checker (4 modules, structured Cisco parsers, 14 rules)
- ✅ Human review: Accept / Edit / Reject
- ✅ ≥ 5 Responsible AI cases (6 pre-seeded in DB)
- ✅ Dashboard with agreement rate and category charts
- ✅ AI ↔ Rule Checker conflict detection

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.12 + Flask |
| AI | Google Gemini 2.5 Flash (or OpenAI GPT-4o) |
| Rule Checker | Pure Python (stdlib only) |
| Database | SQLite locally; PostgreSQL on hosted deployments |
| Frontend | HTML + CSS + JavaScript |
| Charts | Chart.js v4 |
| Fonts | Google Fonts (Inter + JetBrains Mono) |
