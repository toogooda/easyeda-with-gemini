---
name: easyeda-schematic-reviewer
description: Hardware engineering review playbook to audit EasyEDA Pro electronics schematics for errors (reversed diodes, TVS arrays, LDO regulators, IC decoupling, dual crystals, I2C addressing, and bus crossovers) and produce rendered Markdown reports.
---

# EasyEDA Pro Schematic Reviewer Skill

This skill teaches the agent how to systematically audit an electronics schematic created in EasyEDA Pro, verify hardware design rules, examine component pinouts against datasheets, cache new part profiles dynamically, and generate an interactive Markdown report artifact (`review_report.md`).

---

## Architecture: Zero Suppression & JIT Part Caching

The reviewer operates on a **Zero-Suppression Architecture**:
* **100% Component Visibility:** Every active silicon, power device, protection array, and sensor in the design appears in the report with a structured **Pin Connection & Net Analysis Table**. Non-electrical connectors and mechanical items are filtered out to focus strictly on electronics.
* **Automated Rules + Autonomous AI Review:** Deterministic checkers run fast-path math (I2C address strapping, reversed diodes, crystal load caps). For all discrete ICs and modules, the reviewing AI reads the net connectivity and datasheet to audit power requirements, decoupling, and pin connections.
* **JIT (Just-In-Time) Profile Caching:** No human or developer manually hardcodes JSON profiles. When the AI encounters an unprofiled part, it reads the datasheet, extracts the pinout and electrical constraints, and saves the profile into `parts_cache/<LCSC_ID>.json` using `save_part_profile`. That part is now permanently cached for all future audits!

---

## Strict Guardrails for the Reviewing Agent

* 🚫 **DO NOT run git commands:** Under NO circumstances should you run `git status`, `git log`, `git checkout`, or `git restore`. You are acting strictly as a senior hardware design engineer auditing a circuit design, not managing software repository state.
* 🚫 **DO NOT inspect internal repository tracking:** Do NOT inspect `conductor/` tracks, previous commits, or PR notes to deduce component behavior.
* 🚫 **DO NOT inspect or read Python source files (`src/easyeda/*.py`, `tests/`):** You are acting strictly as an EE hardware review engineer. `audit_schematic` handles all parsing and report generation. Do NOT inspect, read, or reverse-engineer the Python source files.
* 🚫 **DO NOT print raw report text containing emojis to PowerShell stdout:** The Windows terminal encoding (`cp1252`) will throw `UnicodeEncodeError: 'charmap'` on status emojis (`🔴`, `🟡`, `🟢`). Always write the report output directly to `review_report.md` using UTF-8 encoding.
* 🚫 **NEVER restore cache files from git:** If a component in `review_report.md` lacks a profile or has unmapped pin names (`-`), you MUST read its datasheet directly from the component's `Datasheet:` URL and create its profile. Attempting to retrieve old cache files via git is strictly prohibited.
* ⚠️ **Handling Inactive Live Sessions:** If `audit_schematic('live')` returns `"No live schematic received yet..."`:
  - Do NOT start exploring the filesystem or running diagnostics.
  - Simply ask the user to either open their schematic in EasyEDA Pro with the live extension running, or provide the file paths to their exported netlist (`.tel`, `.net`, `.json`) and optional BOM (`.xlsx`, `.csv`), for example: `tests/Netlist_Schematic_2026-10-17.tel` and `tests/BOM_RemoteNode_Schematic_2026-10-17.xlsx`.

---

## Available Tools

### 1. MCP Tools (`easyeda-reviewer`)
When running with MCP tools enabled, use:
* **`audit_schematic(schematic_path, bom_path)`**
  * `schematic_path="live"` (or omit argument): Initiates an on-demand pull from the active EasyEDA Pro session via the background bridge on `http://127.0.0.1:8765`. **No user clicks or manual exports needed in EasyEDA!**
  * `schematic_path="<path-to-netlist>"`: Audits an exported `.tel`, `.net`, or `.json` schematic file.
  * `bom_path="<path-to-bom>"`: Optional `.xlsx` or `.csv` BOM file to enrich components with LCSC part numbers and datasheet links.
* **`save_part_profile(profile_data)`**
  * Caches a newly analyzed component profile into `parts_cache/<LCSC_ID>.json` for permanent reuse.
* **`get_datasheet(lcsc_id, url)`**
  * Downloads and caches a component datasheet PDF locally into `datasheets/<LCSC_ID>.pdf`.
* **`get_part_profile(lcsc_id)`**
  * Retrieves the cached pinout, decoupling, and alternate function profile for a component.
* **`list_cached_parts()`**
  * Lists all component IDs currently cached in the JIT part library.

### 2. Fallback Execution (If Direct MCP Tools Are Not Declared)
If running in an environment or subagent where MCP tools are not directly exposed, execute the audit via command:
```powershell
python -c "import sys, pathlib; sys.path.insert(0, r'C:\Projects\easyeda-with-gemini'); from src.easyeda.server import audit_schematic; r = audit_schematic('live'); pathlib.Path('review_report.md').write_text(r, encoding='utf-8'); print('Audit written. Length:', len(r))"
```
*(Or pass the netlist and BOM paths if auditing exported files).*

---

## Audit Workflow for the AI Agent

### Step 1: Run the Audit Tool
Call `audit_schematic(schematic_path="live")` (or the Python fallback command above) to pull the active EasyEDA Pro schematic and write `review_report.md`.

### Step 2: Autonomous Datasheet Lookup & JIT Caching
Inspect Section 3 ("ICs & Peripherals") in `review_report.md`:
* If any active IC (e.g. voltage regulators, transceivers, ADCs/sensors) has unmapped pin names (names showing as `-` or numeric numbers) or lacks automated checks:
  1. Open/read the `Datasheet:` URL provided in the component's metadata (or search the web for the MPN datasheet pinout).
  2. Extract the device's functional description, pin map (`VCC`, `GND`, `RESET`, `SPI`), operating voltage range, and decoupling capacitor requirements.
  3. **I2C Address Strapping (for I2C sensors / peripherals):**
     Look up the device's Slave Address selection table in the datasheet and include the strapping configuration:
     * **Fixed address:** `"i2c_addresses": {"fixed": "0x68"}`
     * **1 strapping pin (2-state or 4-state, e.g. TMP102 ADD0):**
       `"address_pins": ["ADD0"], "i2c_addresses": {"GND": "0x48", "VS": "0x49", "SDA": "0x4A", "SCL": "0x4B"}`
     * **Binary strapping (any number of pins A0, A1, A2... tied to GND or VCC):**
       `"address_pins": ["A2", "A1", "A0"], "address_base": "0x20"`
       *(The engine automatically calculates the bit offset for any combination of pins tied high or low!)*
     * **Multi-pin 4-state matrix (e.g. INA226 A1 & A0 tied to GND, VS, SDA, SCL):**
       `"address_pins": ["A1", "A0"], "i2c_addresses": {"GND_GND": "0x40", "GND_VS": "0x41", "GND_SDA": "0x42", "GND_SCL": "0x43", "VS_GND": "0x44", ...}`
  4. **Save the profile:** Simply use the `write_to_file` tool to save the JSON profile into `parts_cache/<LCSC_ID>.json` (or call `save_part_profile` if MCP is enabled):
     ```json
     {
       "lcsc_part": "<LCSC_ID>",
       "part_number": "<MPN>",
       "part_type": "REGULATOR | TRANSCEIVER | IC | SENSOR | MCU",
       "description": "<Human-readable functional title>",
       "voltage_limits": {"vin_max": 30.0, "vout": 3.3},
       "power_pins": [{"pin": "6", "name": "VS", "decoupling": "100nF"}],
       "ground_pins": ["7"],
       "pin_map": {"1": "A1", "2": "A0", "4": "SDA", "5": "SCL", "6": "VS", "7": "GND"},
       "address_pins": ["A1", "A0"],
       "i2c_addresses": {
         "GND_GND": "0x40", "GND_VS": "0x41", "GND_SDA": "0x42", "GND_SCL": "0x43",
         "VS_GND": "0x44", "VS_VS": "0x45", "VS_SDA": "0x46", "VS_SCL": "0x47",
         "SDA_GND": "0x48", "SDA_VS": "0x49", "SDA_SDA": "0x4A", "SDA_SCL": "0x4B",
         "SCL_GND": "0x4C", "SCL_VS": "0x4D", "SCL_SDA": "0x4E", "SCL_SCL": "0x4F"
       }
     }
     ```
  5. **Rerun `audit_schematic()`:** After creating the profile file(s), rerun the audit command. The live engine will immediately re-evaluate the schematic graph against the newly saved profiles, automatically populating all pin names, decoupling capacitor checks, and I2C address checks!

### Step 3: Conduct a True Hardware Engineering Critique
**Never leave boilerplate placeholders like "INFO Pin connections mapped".** Conduct a genuine senior-level engineering critique:

1. **Executive Summary Upfront:**
   * Review the `## Summary of Issues` positioned right at the top of the report. Verify all 🔴 **CRITICAL** failures (e.g. backwards diodes, unballasted LEDs, swapped RX/TX lines, I2C address conflicts) and 🟡 **WARNING** items (e.g. missing reset pull-ups, floating boot pins).

2. **Microcontroller & Bus Peripheral Pin Mapping (Section 4):**
   * Inspect the `#### Bus Peripheral Pin Mapping` table.
   * The schematic netlist traces what nets are wired to which MCU pins (e.g. Pin 42 to `SCL`, Pin 43 to `SDA`, Pins 14–17 to `LORA` SPI, Pins 30–31 to `PTX`/`PRX`).
   * **Crucial Rule:** The schematic netlist graph alone cannot verify silicon capabilities. You as the reviewing AI must cross-reference the MCU physical pin numbers against the MCU datasheet Alternate Functions (AF) table (e.g. STM32 LQFP-48 pinout):
     * Verify that Pin 42 actually has `I2C_SCL` hardware alternate function.
     * Verify that Pin 15 actually has `SPI_SCK` hardware alternate function.
     * Verify that Pins 30/31 actually have `USART_TX`/`USART_RX` hardware alternate functions.
     * Confirm pull-up resistors on I2C lines (`SCL`, `SDA`) and ESD protection on external lines.
     * If a pin is routed to a function not supported by the MCU silicon alternate function matrix, flag it as a 🔴 **CRITICAL** design error!

3. **Power Tree & Switching:**
   * Trace power origins. If an IC is powered from a switched rail (e.g. `LORAON` driven by high-side PNP switch `Q1` from an MCU GPIO), verify base resistor saturation, pull-up/down resistors, and orientation.

4. **Decoupling for Peak Currents:**
   * Verify decoupling capacitor adequacy. For RF transceivers, motors, or switching regulators, verify whether bulk capacitance (e.g. $10\,\mu\text{F}$) is present in parallel with high-frequency bypass ($100\,\text{nF}$) to prevent brownouts during transmit bursts or load steps.

5. **Diodes, Regulators & Protection:**
   * Catch reversed diodes blocking power rails.
   * Verify LDO ground returns, input voltage ratings, and input/output stability capacitance.
   * Verify TVS protection array clamping rails ($V+$ to power, $V-$ to GND).

### Step 4: Deliver the Visual Report Artifact
Write the complete output into a dedicated user-facing Markdown artifact:
* **Target File:** `review_report.md`
* Set `UserFacing: true` and `RequestFeedback: false`.
* Ensure every section uses descriptive functional titles (e.g. `### U6: HT7333 - 3.3V LDO Voltage Regulator`, `### U2: Ra-01SCH-P - Wireless Transceiver Module`).

### Step 5: Highlight Critical Findings in Chat
In your chat response:
* Provide a clickable link to `review_report.md` using the `file://` scheme.
* Call out any **🔴 CRITICAL** items (e.g. reversed power diodes, unballasted LEDs, or swapped TX/RX pins) and **🟡 WARNING** items that require design changes before PCB layout.
