# Track Spec: Zero-Trust Engineering Review Skill, Pure Circuit Telemetry, and Stale Session Payload Lifecycle

## Overview
Automated schematic auditing suffered from two fundamental flaws:
1. **Premature Pass/Fail Judgments & Concealed Telemetry:** Hardcoded Python checkers attempted to make engineering decisions using brittle heuristics, emitting premature `🟢 PASS` judgments (e.g. declaring Q1's swapped Collector/Emitter as `PASS: Emitter properly oriented on 'LORAON'`) while concealing the actual Collector and Emitter nets from the report tables. The reviewing AI treated these premature verdicts as truth and hallucinated justifications instead of reasoning.
2. **Silent Stale Payload Ingestion:** Audit runs silently fell back to cached payloads from previous sessions, causing the AI to review stale state (e.g. reporting fixed diodes as still reversed) without notifying the user that no live data had been pushed.

This track establishes a **Pure Telemetry Architecture**:
- **Python's Role:** Pure circuit parsing and factual telemetry extraction. Python outputs complete pin-to-net connectivity tables (exposing Base, Collector, and Emitter nets, series resistors, and bias resistors) without declaring premature pass/fail verdicts.
- **AI Agent's Role:** Senior Hardware Review Engineer with full reasoning capability. Guided by the zero-trust engineering checklist in `SKILL.md`, the AI inspects the raw pin telemetry tables to detect design errors (such as swapped Collector/Emitter on high-side PNP switches) and generates the Executive Summary and findings.
- **Session Lifecycle:** Formalized to rename stale payloads on session startup, preventing silent reuse of old caches.

## Requirements

### 1. Zero-Trust Engineering Review Checklist (`SKILL.md`)
- Mandate that AI agents treat Python outputs as **raw telemetry only**, never accepting premature passes.
- Provide the comprehensive hardware engineering review checklist:
  - Transistors & Switching FETs (PNP Emitter on power, Collector on load; NPN Emitter on GND; MOSFET Source/Drain orientation; Base/Gate resistors).
  - Diodes & LEDs (polarities, series ballast resistors).
  - I2C Bus & Strapping (slave address resolution, bus conflicts, pull-ups).
  - MCU Clocks, Reset & Boot (crystals, NRST 100nF, BOOT0 pull-down).
  - Silicon Alternate Function verification.

### 2. Pure Telemetry Reporting (`reporter.py`, `checker_transistors.py`, `checker_diodes.py`)
- In Section 2 (Transistors & FETs):
  - Expand table columns to expose complete pinout telemetry:
    `| Designator | Value | Package | Type | Base/Gate (Pin & Net) | Collector/Drain (Pin & Net) | Emitter/Source (Pin & Net) | Series Resistor | Pull-up / Pull-down | Telemetry Details |`
  - Remove hardcoded `🟢 PASS` / `🔴 FAIL` verdicts from the Python checker output for transistors and diodes; report factual findings (e.g. "PNP BJT. Base on pin 1 ($1N3719) via R2 (1kΩ). Pin 2 on '3V3', Pin 3 on 'LORAON'.").
- Ensure Python report invites the reviewing AI to evaluate the circuit against design rules rather than asserting artificial pass counts.

### 3. Session Lifecycle & Stale Payload Management (`server.py`)
- On server startup or session start:
  - Rename pre-existing `parts_cache/.last_raw_payload.json` to `parts_cache/.stale_raw_payload.json` (and `.last_live_report.md` to `.stale_live_report.md`).
- When `audit_schematic('live')` is called:
  - Wait for live schematic push over port 8765.
  - If timeout occurs without a live push during the current session: return a clear notice that no live schematic push was received in the current session (noting that previous session data is archived to `.stale_raw_payload.json`).
  - Keep active live payloads in memory and `.last_raw_payload.json` for subsequent queries in the same session.

### 4. Verification & Testing
- Unit tests verifying:
  - Transistor and diode reporting outputs complete pinout telemetry.
  - Stale payload archiving and live pull timeout handling.
- Regression testing: all existing tests pass or are updated to match telemetry models.
- End-to-end verification against the active EasyEDA Pro session confirming the AI reviewer catches Q1's swapped Collector/Emitter as a 🔴 **CRITICAL DEFECT**.
