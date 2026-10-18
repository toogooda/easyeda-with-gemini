# Track Spec: Zero-Suppression Component Reporting, JIT Profile Caching Tool, and Standalone Skill Context

## Overview
Schematic review previously suffered from a component exclusion blindspot: any component lacking automated rule passes was filtered out and omitted from reports (e.g. `D1` TVS diode array, `U4` and `U6` LDO voltage regulators). This track implements a Zero-Suppression architecture ensuring 100% component visibility, provides an MCP tool for the AI to cache JIT part profiles directly, and enriches the schematic reviewer skill to be fully self-contained for external AI assistants.

## Requirements

### 1. Zero-Suppression Component Reporting (`reporter.py`, `checker_diodes.py`)
- Remove all exclusion gates (`len(comp.pins) <= 3` on diodes, `if checks:` on ICs).
- Ensure 100% of components from the netlist/BOM (including `D1`, `U4`, `U6`, connectors, regulators, and unknown ICs) appear in the review report.
- For all ICs, regulators, and protection devices, provide:
  - Header with Designator, Part Number / Value, Package, LCSC ID, and Datasheet link.
  - Formatted **Pin Connection & Net Analysis Table**: Pin number, Pin name, Connected Net, Electrical Type (`Power`, `Ground`, `Signal`), and detected Capacitance to GND on that net.
  - Rule-based check results if available, or status `ℹ️ IC / Peripheral (Datasheet Review Needed)` with prompt for the reviewing AI.

### 2. JIT Profile Caching & Datasheet Tools in MCP (`server.py`, `parts_manager.py`)
- Expose `save_part_profile` tool on the MCP server allowing AI agents to persist extracted profiles (pinout, power pins, voltage limits, decoupling requirements) into `parts_cache/<LCSC_ID>.json`.
- Expose `get_datasheet` tool to download and cache datasheet PDFs locally into `datasheets/<LCSC_ID>.pdf`.
- Pre-populate cached profiles for:
  - `C434726` (`SP720ABTG` Littelfuse 14-Channel TVS Array in SOIC-16).
  - `C22466409` (`HT7350-1` Holtek 5.0V LDO in SOT-89-3).
  - `C259241` (`HT7333` Holtek 3.3V LDO in SOT-89-3).

### 3. Self-Contained Skill Context (`SKILL.md`)
- Overhaul both `skills/easyeda-schematic-reviewer/SKILL.md` and global `C:\Users\USER\.gemini\config\skills\easyeda-schematic-reviewer\SKILL.md`.
- Document all MCP tools (`audit_schematic`, `save_part_profile`, `get_part_profile`, `list_cached_parts`, `get_datasheet`).
- Explain the on-demand live pull mechanism over port 8765 (`schematic_path="live"`) requiring no manual addon clicks.
- Instruct external AI agents on how to read the pin table and datasheet link for unprofiled ICs, audit electrical constraints, and cache profiles to `parts_cache/`.

### 4. Verification
- Pytest suite verifying:
  - `D1`, `U4`, and `U6` appear in `generate_schematic_report()` with full pin tables and decoupling capacitor detection.
  - `save_part_profile` and `get_datasheet` MCP tools work as expected.
  - Regression testing: all existing tests continue to pass.
