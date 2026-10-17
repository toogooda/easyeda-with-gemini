# Track Spec: Phase 5 MCP Server, Live Extension & Antigravity Skill

## Goal
Package the complete schematic review engine into an MCP server and Antigravity Skill that generates rendered Markdown reports (`review_report.md`), and provide an EasyEDA Pro extension for live, zero-export data streaming.

## Deliverables
1. `src/easyeda/reporter.py`:
   - Aggregates findings from all checkers.
   - Formats rendered Markdown tables for Diodes & LEDs, Transistors & FETs, ICs & I2C, and Microcontrollers.
   - Summarizes Critical, Warning, and Info findings.
2. `src/easyeda/server.py`:
   - Model Context Protocol (MCP) server over stdio.
   - Tools: `audit_schematic`, `get_part_profile`, `list_cached_parts`.
   - Local background HTTP receiver (`http://127.0.0.1:8765/review`) for live EasyEDA streaming.
3. `easyeda-extension/`:
   - `manifest.json`: EasyEDA Pro extension descriptor.
   - `index.js`: Extension script sending active document data to local endpoint.
4. `skills/easyeda-schematic-reviewer/SKILL.md`:
   - Antigravity Skill defining the hardware review procedure and report artifact generation.
5. `tests/test_mcp_server.py`:
   - Pytest suite verifying MCP tool execution and complete Markdown report formatting.
