# Implementation & Testing Plan: EasyEDA Pro Schematic Checker

## Overview
This plan breaks down the development of the EasyEDA Pro schematic checker into 5 testable, progressive phases. Each phase has clear deliverables, test cases, and completion criteria.

---

## Phase 1: Test Bench Schematic & Graph Parser
*Goal: Convert schematic export data into a queryable in-memory electrical graph.*

- [ ] **1.1 Test Bench Schematic Fixture**
  - Create a realistic fixture (`tests/fixtures/test_schematic.json` / netlist + BOM) containing:
    - 1 correctly oriented diode & 1 backwards diode
    - 1 properly limited LED & 1 LED without series resistor
    - 1 properly biased NPN switch & 1 direct-driven BJT base
    - 1 I2C sensor (e.g. TMP102) with address pin to GND
    - 1 Microcontroller (STM32F103) with power, crystal, and bus pins
- [ ] **1.2 Schematic Data Models (`models.py`)**
  - Define data structures: `Component`, `Pin`, `Net`, and `SchematicGraph`.
- [ ] **1.3 Netlist & BOM Parser (`parser.py`)**
  - Implement parsing for EasyEDA netlist/JSON export and BOM CSV.
  - Extract designator, pin numbers/names, connected net, LCSC part ID, and datasheet URL.
- [ ] **1.4 Phase 1 Verification / Unit Tests**
  - Write `tests/test_parser.py`.
  - Assert all components, nets, and pins are loaded into the graph accurately.

---

## Phase 2: Discrete Component Checkers (Diodes, LEDs, Transistors)
*Goal: Implement deterministic electrical rules for two-terminal and three-terminal devices.*

- [ ] **2.1 Diode & LED Checker (`checker_diodes.py`)**
  - Reverse polarity protection check: verify Anode towards `VIN`, Cathode towards system rail.
  - Flyback diode check: verify Cathode towards positive rail across inductive load.
  - LED polarity check: Anode towards drive, Cathode towards ground/low-side.
  - LED current-limiting check: verify series resistor presence and reasonable resistance value.
- [ ] **2.2 Transistor & MOSFET Checker (`checker_transistors.py`)**
  - BJT Saturation check: ensure base has a series resistor ($1\text{k}\Omega - 4.7\text{k}\Omega$) from MCU GPIO.
  - BJT Emitter polarity check: NPN Emitter to GND; PNP Emitter to positive rail.
  - MOSFET Gate pull-down (N-ch) / pull-up (P-ch) check.
  - MOSFET gate drive logic level check ($V_{GS(th)}$ compatible with 3.3V).
- [ ] **2.3 Phase 2 Verification / Unit Tests**
  - Write `tests/test_discrete_checkers.py`.
  - Run checks against Phase 1 fixture.
  - Assert that all intentional bugs are caught with correct severities (🔴 CRITICAL, 🟡 WARN, 🟢 PASS).

---

## Phase 3: JIT Part Cache & Datasheet Extractor
*Goal: Automate downloading datasheets and generating structured part profiles on first encounter.*

- [ ] **3.1 Parts Cache Manager (`parts_manager.py`)**
  - Check local cache: `parts_cache/<LCSC_ID>.json`.
  - Provide fast load for cache hits.
- [ ] **3.2 PDF Fetcher & Targeted Extractor (`datasheet_extractor.py`)**
  - Download PDF from component's EasyEDA `datasheet` URL into `datasheets/<LCSC_ID>.pdf`.
  - Scan PDF text for target pages: Pinout, Typical Application, Decoupling, I2C Address tables.
- [ ] **3.3 LLM Profile Generator**
  - Prompt template to extract structured JSON matching our schema:
    - Power pins & exact required decoupling capacitor values/types
    - Crystal pins (HSE and LSE 32.768kHz RTC)
    - Reset pin requirements
    - I2C address strapping mapping
    - Peripheral alternate functions (UART, SPI, I2C, CAN)
- [ ] **3.4 Phase 3 Verification**
  - Test on 2 sample parts: 1 I2C sensor (`TMP102`) and 1 MCU (`STM32F103C8T6`).
  - Verify generated JSON matches schema and contains required fields.

---

## Phase 4: IC, I2C & Microcontroller Checker Engine
*Goal: Cross-reference schematic netlist against cached part profiles for ICs and MCUs.*

- [ ] **4.1 IC & I2C Peripheral Checker (`checker_ics.py`)**
  - Match decoupling capacitors on IC power pins to the exact cached datasheet requirements.
  - Read strapping pin connections (`ADDR`, `A0`, `A1`) and compute the resulting 7-bit $I^2C$ address.
  - Verify bus pull-ups on `SDA` and `SCL`.
- [ ] **4.2 Microcontroller Validator (`checker_mcu.py`)**
  - Verify all power pins (`VDD`, `VDDA`, `VSS`) connected and decoupled per datasheet.
  - Verify HSE crystal load capacitors.
  - Verify LSE (32.768kHz RTC) crystal and load capacitors if RTC pins are connected.
  - Verify reset and boot pin circuitry.
- [ ] **4.3 Bus Alternate Function & Crossover Checker (`checker_buses.py`)**
  - UART crossover check: MCU `TX` $\to$ Device `RX`, MCU `RX` $\leftarrow$ Device `TX` (including `TX1`/`RX1`, `TX2`/`RX2`).
  - CAN transceiver check: MCU `CAN_TX` $\to$ PHY `TXD`, MCU `CAN_RX` $\leftarrow$ PHY `RXD`.
  - SPI check: `MOSI` $\to$ `MOSI`/`SDI`, `MISO` $\leftarrow$ `MISO`/`SDO`.
  - Validate that assigned pins actually support the specified hardware peripheral.
- [ ] **4.4 Phase 4 Verification**
  - Write `tests/test_mcu_checker.py`.
  - Assert that decoupling errors, reversed UART, and swapped CAN pins are flagged correctly.

---

## Phase 5: MCP Server, Live Extension & Antigravity Skill
*Goal: Provide zero-export live integration and deliver rendered Markdown review reports in the IDE.*

- [ ] **5.1 MCP Server (`server.py`)**
  - Wrap review engine into standard MCP tools:
    - `audit_schematic(source)`: Runs full review.
    - `get_part_profile(lcsc_id)`: Inspects cached profile.
    - `list_cached_parts()`: Lists all known parts.
- [ ] **5.2 Live EasyEDA Pro Extension (Zero-Export Bridge)**
  - Simple TypeScript extension running in EasyEDA Pro.
  - Exposes local endpoint on `localhost` streaming active schematic document to the MCP server.
- [ ] **5.3 Antigravity Skill (`skills/easyeda-schematic-reviewer/SKILL.md`)**
  - Hardware review playbook instructing the agent to run the MCP audit tool.
  - Generates the rendered visual artifact: `review_report.md` with tables and badges.
- [ ] **5.4 End-to-End System Test**
  - Open a project in EasyEDA Pro.
  - Ask Antigravity: *"Review my schematic"*.
  - Verify that the report is generated cleanly and rendered in the IDE.
