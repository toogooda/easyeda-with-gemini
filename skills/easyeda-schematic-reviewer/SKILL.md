---
name: easyeda-schematic-reviewer
description: Hardware engineering review playbook to audit EasyEDA Pro electronics schematics for errors (reversed diodes, transistor saturation, IC decoupling, dual crystals, I2C addressing, and bus crossovers) and produce rendered Markdown reports.
---

# EasyEDA Pro Schematic Reviewer Skill

This skill teaches the agent how to systematically audit an electronics schematic created in EasyEDA Pro, verify hardware design rules, and generate an interactive Markdown report artifact (`review_report.md`).

---

## When to Use This Skill
Activate this skill whenever the user asks to:
* Review or check an EasyEDA Pro schematic for errors or mistakes.
* Verify power rails, decoupling capacitors, or oscillator/crystal circuits.
* Validate I2C strapping addresses, pull-up resistors, or bus pin crossovers (UART TX/RX, CAN, SPI).
* Audit an exported netlist (`.tel`, `.net`), JSON export, or active live design from EasyEDA Pro.

---

## Audit Workflow

### Step 1: Identify Input Source
Determine whether the user is reviewing:
1. **A live open schematic in EasyEDA Pro:** Use `schematic_path="live"`. The EasyEDA Pro extension will have streamed the active canvas across `http://127.0.0.1:8765/review`.
2. **An exported netlist or JSON file:** Identify the path to the `.tel`, `.net`, or `.json` file.
3. **An exported BOM file:** Check if an associated `.xlsx` or `.csv` BOM exists in the project folder to enrich components with LCSC part numbers and datasheet links.

### Step 2: Invoke MCP Audit Tool
Invoke the `audit_schematic` MCP tool:
```python
audit_schematic(schematic_path="tests/Netlist_Schematic_2026-10-17.tel", bom_path="tests/BOM_RemoteNode_Schematic_2026-10-17.xlsx")
```

### Step 3: Deliver the Visual Report Artifact
Write the complete output into a dedicated user-facing Markdown artifact:
* **Target File:** `review_report.md`
* Set `UserFacing: true` and `RequestFeedback: false`.

### Step 4: Highlight Critical Findings
In your chat response:
* Point the user to the generated `review_report.md` artifact.
* Call out any **🔴 CRITICAL** items (e.g. reversed power diodes, unballasted LEDs, or swapped TX/RX pins) and **🟡 WARNING** items that require design changes before PCB layout.
