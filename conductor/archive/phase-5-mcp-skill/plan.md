# Track Plan: Phase 5 MCP Server, Live Extension & Antigravity Skill

- [x] **Task 1: Full Report Generator (`src/easyeda/reporter.py`)**
  - Implement `generate_schematic_report(graph, parts_manager)`:
    - Runs all checkers: Diodes & LEDs, Transistors & FETs, ICs & I2C, Microcontrollers, and Bus crossovers.
    - Generates markdown formatted tables matching Section 6 of `docs/spec.md`.
    - Generates summary of Critical (🔴), Warning (🟡), and Info (🟢) issues.
- [x] **Task 2: MCP Server Implementation (`src/easyeda/server.py`)**
  - Implement MCP tools (`audit_schematic`, `get_part_profile`, `list_cached_parts`).
  - Implement local HTTP endpoint for receiving live schematic payloads from EasyEDA Pro without file export.
- [x] **Task 3: EasyEDA Pro Extension (`easyeda-extension/`)**
  - Create `manifest.json` registering the extension menu item.
  - Create `index.js` extracting components and nets from active editor document and POSTing to `http://127.0.0.1:8765/review`.
- [x] **Task 4: Antigravity Skill (`skills/easyeda-schematic-reviewer/SKILL.md`)**
  - Create skill document defining tool usage and review instructions.
- [x] **Task 5: Unit & End-to-End Test Suite (`tests/test_mcp_server.py`)**
  - Test report generation formatting and MCP tool functions.
