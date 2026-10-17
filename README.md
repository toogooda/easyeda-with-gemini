# easyeda-with-gemini

Automated hardware schematic reviewer connecting **Antigravity / Gemini** to **EasyEDA Pro** via Model Context Protocol (MCP).

## Overview
`easyeda-with-gemini` inspects electronics schematics in EasyEDA Pro to identify design mistakes before PCB layout or manufacturing:
* **Diodes & LEDs:** Checks polarity, reverse-polarity protection, flyback diode orientation, and current-limiting resistor sizing.
* **Transistors & FETs:** Checks BJT base resistor sizing for saturation, emitter/collector orientation, and MOSFET gate pull-up/pull-down bias.
* **ICs & Peripherals:** Audits decoupling capacitors against exact datasheet requirements, traces $I^2C$ address strapping pins, and calculates 7-bit $I^2C$ addresses.
* **Microcontrollers:** Validates dual crystals (HSE & LSE 32.768kHz RTC), power rail filtering, and checks peripheral bus pin mappings (UART TX/RX crossover, CAN TX/RXD, SPI).
* **Just-In-Time (JIT) Part Library:** Downloads datasheets on first encounter via EasyEDA LCSC links, generates structured component profiles (`parts_cache/`), and caches them for fast, zero-token subsequent audits.

## Architecture
1. **EasyEDA Pro Data Source:** Reads schematic netlists/exports or connects via live local WebSocket extension.
2. **JIT Parts Cache:** Stores structured chip pinouts, decoupling requirements, and alternate functions in `./parts_cache/`.
3. **MCP Server:** Exposes standard verification tools to Antigravity/Gemini.
4. **Antigravity Skill:** Orchestrates the hardware engineering review and outputs interactive, rendered Markdown reports (`review_report.md`).

---

## Installation

The system consists of two parts:
1. **EasyEDA Pro Extension:** Adds an "Audit with Antigravity" button to EasyEDA Pro.
2. **Antigravity MCP Server & Skill:** Teaches Antigravity how to run the audit engine and generate review reports.

### 1. Install the EasyEDA Pro Extension
1. Open **EasyEDA Pro** (Desktop client or Web version).
2. In the top menu, go to **Advanced** $\to$ **Extension Manager** (or **Settings** $\to$ **Extensions**).
3. Click the **Import** button.
4. Select the pre-packaged extension file from the repository:
   ```
   C:\Projects\easyeda-with-gemini\easyeda-extension\easyeda-with-gemini.eext
   ```
   *(Alternatively, `easyeda-with-gemini.zip` is also provided in the same folder).*
5. In the **Installed** tab of Extension Manager, ensure **Antigravity Reviewer** is toggled to **Enabled**.
6. Open any schematic: the new menu item is available in the top bar under:
   **Antigravity** $\to$ **Audit Schematic with Antigravity**.

### 2. Register the Antigravity Skill
Copy the skill folder to your personal Antigravity skills directory:
```powershell
Copy-Item -Recurse -Force "C:\Projects\easyeda-with-gemini\skills\easyeda-schematic-reviewer" "$HOME\.gemini\antigravity\skills\"
```

### 3. Register the MCP Server
Add the server configuration to your Antigravity MCP settings (e.g. `%USERPROFILE%\.gemini\antigravity\mcp_config.json`):
```json
{
  "mcpServers": {
    "easyeda-reviewer": {
      "command": "python",
      "args": ["-m", "src.easyeda.server"],
      "cwd": "C:\\Projects\\easyeda-with-gemini"
    }
  }
}
```

---

## Usage

### Mode A: Live Stream from EasyEDA Pro (Zero-Export)
1. In **EasyEDA Pro**, open your schematic.
2. Go to **Schematic** $\to$ **Tools** $\to$ **Audit with Antigravity**.
3. In **Antigravity Chat**, prompt:
   > *"Review my open EasyEDA schematic"*
4. Antigravity retrieves the live design from the local receiver, audits all components, and displays the complete rendered report.

### Mode B: File-Based Audit (Netlist + BOM)
1. Export a Netlist (`.tel`, `.net`, or `.json`) and BOM (`.xlsx` or `.csv`) from EasyEDA Pro.
2. In **Antigravity Chat**, prompt:
   > *"Please audit my schematic at `tests/Netlist_Schematic_2026-10-17.tel` using BOM `tests/BOM_RemoteNode_Schematic_2026-10-17.xlsx`"*

### Mode C: Command-Line / Terminal Test
Run an audit directly from PowerShell:
```powershell
python -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); from src.easyeda.server import audit_schematic; print(audit_schematic('tests/Netlist_Schematic_2026-10-17.tel', 'tests/BOM_RemoteNode_Schematic_2026-10-17.xlsx'))"
```
