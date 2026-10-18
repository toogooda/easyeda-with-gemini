# Track Plan: Zero-Suppression Component Reporting, JIT Profile Caching Tool, and Standalone Skill Context

- [x] **Task 1: Zero-Suppression Reporting & Pin Analysis Table**
  - Update `src/easyeda/checker_diodes.py`: remove `len(comp.pins) <= 3` gate so multi-pin protection arrays (like `D1`) are retained.
  - Update `src/easyeda/reporter.py`:
    - Guarantee 100% component inclusion: every component in the netlist/BOM appears in the report.
    - Generate structured **Pin Connection & Net Analysis Table** for every IC, LDO, and multi-pin device (Pin, Name, Net, Type, Caps to GND).
    - Display component details (Value, Package, LCSC ID, Datasheet).

- [x] **Task 2: JIT Profile Caching & Datasheet Tools in MCP Server**
  - Update `src/easyeda/parts_manager.py`: enhance `save_profile()` with dict/JSON validation.
  - Update `src/easyeda/server.py`:
    - Add `save_part_profile(profile_data: dict)` tool.
    - Add `get_datasheet(lcsc_id: str, url: str)` tool.
  - Add initial cached profiles in `parts_cache/`:
    - `C434726.json` (SP720ABTG TVS Array).
    - `C22466409.json` (HT7350-1 5V LDO).
    - `C259241.json` (HT7333 3.3V LDO).

- [x] **Task 3: Self-Contained Skill Instructions**
  - Overhaul `skills/easyeda-schematic-reviewer/SKILL.md` and global `C:\Users\USER\.gemini\config\skills\easyeda-schematic-reviewer\SKILL.md`.
  - Provide comprehensive instructions on MCP tools, on-demand live pull over port 8765 without addon clicks, CLI fallbacks, and AI-driven datasheet review + JIT profile caching.

- [x] **Task 4: Unit Testing & Verification**
  - Add tests in `tests/test_mcp_server.py` and `tests/test_mcu_checker.py`:
    - Verify `D1`, `U4`, and `U6` are included with full pin tables and decoupling caps.
    - Test `save_part_profile` and `get_datasheet` MCP tools.
    - Verify 100% pass rate across test suite.
