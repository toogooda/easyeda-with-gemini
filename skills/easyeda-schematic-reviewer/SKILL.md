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
* **Automated Telemetry + Autonomous AI Review:** Deterministic checkers parse net connectivity, component types, and fast-path pinout math. The reviewing AI treats Python output as raw telemetry, applying senior hardware design principles to audit circuit operation, pin orientation, and electrical constraints.
* **JIT (Just-In-Time) Profile Caching:** No human or developer manually hardcodes JSON profiles. When the AI encounters an unprofiled part, it reads the datasheet, extracts the pinout and electrical constraints, and saves the profile into `parts_cache/<LCSC_ID>.json` using `save_part_profile`. That part is now permanently cached for all future audits!

---

## Strict Guardrails for the Reviewing Agent

* 🚫 **NEVER blindly trust Python checker `PASS` badges (Zero-Trust Mandate):** Python checkers perform preliminary heuristics, but may fail to detect inverted pinouts, swapped collector/emitter pins, or logic race conditions. You are an autonomous Senior Hardware Design Engineer: treat Python checker outputs as **raw telemetry only** (pin net connections, component values, part profiles). You MUST personally verify physical pin connections against hardware engineering rules. Never invent justifications or assume a circuit is correct simply because an automated check returned `🟢 PASS`.
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

### Step 3: Conduct a True Hardware Engineering Critique (Zero-Trust Review Checklist)
**Never leave boilerplate placeholders or accept automated PASS badges without verification.** As a Senior Electrical Engineer, you must actively audit the raw pin-to-net connectivity against the following zero-trust hardware checklist:

#### 1. Transistors & Switching FETs (Section 1 & Raw Netlist)
* **High-Side PNP BJTs (e.g. Q1 / B772):**
  - **Physical Pin Orientation:** Pin assigned to **Emitter** MUST connect to the positive DC power rail (`3V3`, `5V`, `VIN`, etc.). Pin assigned to **Collector** MUST connect to the switched load net (e.g. `LORAON`).
  - 🔴 **CRITICAL DEFECT:** If Collector connects to a power rail or Emitter connects to the load, the BJT is **swapped/reversed**. In this inverted state, the base-collector junction acts as a forward diode to the base, breaking high-side gating, causing parasitic back-powering, and preventing cutoff. Flag this immediately as a Critical Design Error!
  - **Base Drive & Resistors:** Verify a series base resistor ($1\,\text{k}\Omega - 4.7\,\text{k}\Omega$) is present to limit GPIO sink current. Verify a pull-up resistor ($10\,\text{k}\Omega - 100\,\text{k}\Omega$) exists between Base and Emitter (Power rail) to guarantee clean cutoff during MCU reset/boot.
* **Low-Side NPN BJTs (e.g. Q2 / 2SD965):**
  - **Physical Pin Orientation:** Pin assigned to **Emitter** MUST connect to ground (`GND`). Pin assigned to **Collector** MUST connect to the low side of the switched load.
  - 🔴 **CRITICAL DEFECT:** If Emitter connects to a positive rail or Collector connects to GND, flag as a reversed BJT.
  - **Base Drive & Resistors:** Verify a series base resistor ($220\,\Omega - 2.2\,\text{k}\Omega$) and a pull-down resistor to GND to keep the switch off during MCU boot.
* **P-Channel MOSFETs (High-Side Switch):**
  - Source MUST connect to the positive power rail; Drain MUST connect to the load. (Reversing Source and Drain leaves the internal body diode forward-biased, permanently conducting power!).
  - Gate MUST have a pull-up resistor to the source power rail.
* **N-Channel MOSFETs (Low-Side Switch):**
  - Source MUST connect to `GND`; Drain MUST connect to the load.
  - Gate MUST have a pull-down resistor to `GND`.

#### 2. Diodes & Protection Devices (Section 2 & Raw Netlist)
* **Power & Rectifier Diodes (e.g. U5, D2):**
  - Anode MUST connect to the power input / driving source; Cathode MUST connect to the protected / downstream net.
  - 🔴 **CRITICAL DEFECT:** A reversed diode in series with power will block all current and completely deaden the circuit.
* **Indicator LEDs:**
  - Verify every LED has a dedicated series ballast current-limiting resistor ($100\,\Omega - 2.2\,\text{k}\Omega$).
  - 🔴 **CRITICAL DEFECT:** Direct connection of an LED between a logic pin/rail and GND without a ballast resistor will cause overcurrent damage to the diode or MCU GPIO!
* **TVS Protection Arrays (e.g. D1 / SP720):**
  - Ground/Anode pins MUST connect to solid `GND`.
  - Clamp/Cathode pins MUST tap the protected signal/bus lines.
  - Verify clamp voltage exceeds nominal bus operating voltage.

#### 3. I2C Bus & Address Resolution (Section 3 & Raw Netlist)
* **Physical Address Strapping:**
  - Inspect the physical net connections on all address pins ($A_0, A_1, A_2, \text{ADD0}$) for every I2C device (e.g. INA226, EEPROM, TMP102).
  - Verify exact 7-bit slave addresses calculated from the strapping table in the device datasheet.
* **Address Collisions:**
  - 🔴 **CRITICAL DEFECT:** If two devices on the same I2C bus share the same 7-bit address, flag an immediate bus conflict.
* **Bus Pull-Up Resistors:**
  - Verify dedicated pull-up resistors ($2.2\,\text{k}\Omega - 4.7\,\text{k}\Omega$) are present on both `SCL` and `SDA` nets to the I2C $V_{\text{CC}}$ rail.

#### 4. Microcontroller Clocks, Reset & Boot Strapping (Section 4)
* **Dual Oscillator Crystals:**
  - HSE (e.g. 8MHz) crystal pins wired to `OSC_IN` / `OSC_OUT` with matching load capacitors ($10\,\text{pF} - 22\,\text{pF}$) to GND.
  - LSE (e.g. 32.768kHz) crystal pins wired to `OSC32_IN` / `OSC32_OUT` with load capacitors ($6\,\text{pF} - 12\,\text{pF}$) to GND.
* **NRST Pin:**
  - MUST have a $100\,\text{nF}$ filter/decoupling capacitor directly to `GND` to suppress transient resets.
* **BOOT0 Pin:**
  - MUST have a pull-down resistor ($10\,\text{k}\Omega$) to `GND` for normal Flash memory execution.

#### 5. Silicon Peripheral Alternate Functions (AF)
* Cross-reference MCU pin assignments against the silicon alternate function table:
  - Verify MCU pins assigned to `I2C_SCL` / `I2C_SDA` support hardware I2C AF.
  - Verify MCU pins assigned to `SPI_SCK`, `SPI_MOSI`, `SPI_MISO`, `SPI_NSS` support hardware SPI AF.
  - Verify MCU pins assigned to `USART_TX` / `USART_RX` support hardware UART AF.
  - 🔴 **CRITICAL DEFECT:** If a peripheral signal is routed to an MCU pin lacking that alternate function in silicon, flag as an unroutable peripheral!

#### 6. Power Distribution & Decoupling
* For every IC, LDO, and RF module:
  - Verify bulk capacitor (e.g. $10\,\mu\text{F}$) on power entry.
  - Verify high-frequency bypass capacitor ($100\,\text{nF}$) close to each $V_{\text{DD}}$ / $V_{\text{CC}}$ pin with low-impedance ground return to `GND`.
  - For RF transceivers (e.g. LoRa SX1262 / Ra-01), verify adequate peak current capability ($>120\,\text{mA}$) and transient bypass to avoid transmit reset.

### Step 4: Deliver the Visual Report Artifact
Write the complete output into a dedicated user-facing Markdown artifact:
* **Target File:** `review_report.md`
* Set `UserFacing: true` and `RequestFeedback: false`.
* Ensure every section uses descriptive functional titles (e.g. `### U6: HT7333 - 3.3V LDO Voltage Regulator`, `### U2: Ra-01SCH-P - Wireless Transceiver Module`).

### Step 5: Highlight Critical Findings in Chat
In your chat response:
* Provide a clickable link to `review_report.md` using the `file://` scheme.
* Call out any **🔴 CRITICAL** items (e.g. reversed power diodes, unballasted LEDs, or swapped TX/RX pins) and **🟡 WARNING** items that require design changes before PCB layout.
