# Track Specification: Universal I2C Device Address Resolution

## Context & Motivation
In automated schematic reviews, identifying the exact 7-bit I2C device address for all I2C peripherals is a core requirement to verify bus topologies, detect address collisions, and generate software configuration headers.

Currently:
1. **Netlist Pin Number vs Name:** In Protel netlists (exported from EasyEDA), pins only carry numbers (`1`, `2`, `3`...). `PartProfile.pin_map` defines the pin roles, but `Component.pins` were not enriched with these names during parsing or checking, preventing address strapping pins (`A0`, `A1`, `A2`) from being identified.
2. **Multi-Pin Strapping:** The strapping resolver only handled single-pin devices (e.g. TMP102 `ADD0`). Devices with 2 address pins (e.g., TI INA226 with `A1` and `A0` strapped to GND, VS, SDA, or SCL) or 3 address pins (e.g., Microchip 24AA024 / 24LC024 / 24AA025 / 24LC025 2-Kbit I2C Serial EEPROM with `A2`, `A1`, `A0` strapped to GND or VCC) were not resolved.
3. **Report Visibility:** Resolved I2C addresses must be clearly displayed in the IC component headings, verification checklists, and summary table.

## Requirements & Scope
1. **Netlist Pin Enrichment:**
   - In `merge_bom_into_graph()` or `PartsManager`, enrich component pins with signal names from `PartProfile.pin_map` whenever pin names are numeric or missing.
2. **Universal Strapping Engine:**
   - Support arbitrary number of address pins (0, 1, 2, 3+ pins).
   - Evaluate the electrical connection state of each strapping pin:
     - `GND` (ground net)
     - `V+` / `VS` / `VCC` / `VDD` / `POWER` (positive power rail)
     - `SDA` (connected to I2C SDA bus net)
     - `SCL` (connected to I2C SCL bus net)
     - `FLOAT` (no connection)
   - Match against profile strapping definitions:
     - Single-pin: `{pin}={state}` or `ADD0={state}` (e.g. `ADD0=GND` -> `0x48`)
     - Multi-pin explicit state table: `{state_A1}_{state_A0}` (e.g. INA226 `GND_VS` -> `0x41`, `GND_SCL` -> `0x43`, `GND_SDA` -> `0x42`)
     - Binary bit strapping formula: `base_address | (A2 << 2) | (A1 << 1) | (A0 << 0)` for EEPROMs and GPIO expanders (e.g. 24AA024 / 24LC024 with base `0x50`).
3. **Verified Part Profiles:**
   - TI INA226 (`C2653870`): Complete 16-state address lookup table (`0x40`–`0x4F`).
   - Microchip 24AA024 / 24LC024 (`C284568` or generic EEPROM profile): 3-pin strapping (`A0`, `A1`, `A2` -> `0x50`–`0x57`).
4. **Report & Summary Presentation:**
   - IC component section header: `### U7: SOLARADC (INA226AIDGST) [7-bit I2C: 0x41]`
   - Checklist item: `* 🟢 PASS I2C Address resolved: A1=GND, A0=3V3 (VS) -> 7-bit Address is 0x41.`
   - Summary of issues: `* Detected I2C Devices: U7 @ 0x41, U8 @ 0x43, U9 @ 0x42`
5. **Bus Address Conflict Detection:**
   - Compare all resolved I2C addresses on the same bus net (`SDA`/`SCL`).
   - Emit `🔴 FAIL (I2C_ADDRESS_CONFLICT)` if two components share the same address on the same bus.
