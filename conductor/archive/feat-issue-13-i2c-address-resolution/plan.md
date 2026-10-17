# Track Plan: Universal I2C Device Address Resolution

- [x] **Task 1: Netlist Pin Enrichment via PartProfile.pin_map**
  - Update `merge_bom_into_graph()` in `src/easyeda/datasheet_extractor.py` to populate `pin.name` from `profile.pin_map` when pin names are numeric or missing.
  - Update `Component` or `PartsManager` helpers to allow fast role-based pin retrieval (e.g. `comp.get_pins_by_role("A*")`).

- [x] **Task 2: Universal Multi-Pin Address Strapping Engine**
  - Overhaul `check_i2c_peripheral()` in `src/easyeda/checker_ics.py`:
    - Collect all address pins (`A0`, `A1`, `A2`, `ADD0`, `ADDR`, etc.) using explicit pin names or `profile.pin_map`.
    - Evaluate pin connection state: `GND`, `VS`/`VCC`/`3V3`/`V+`, `SDA`, `SCL`, `FLOAT`.
    - Support composite multi-pin state key matching (e.g. `{A1}_{A0}` like `GND_VS` -> `0x41`).
    - Support binary bit strapping for EEPROMs (e.g. `24AA024`/`24LC024` with base `0x50` + `(A2<<2 | A1<<1 | A0)`).
    - Support single-pin strapping (TMP102 `ADD0=GND` -> `0x48`).
    - Return structured `CheckResult` with `i2c_address`, `address_pins`, and `pin_states` in `details`.

- [x] **Task 3: Part Profiles for INA226 and Microchip 24AA024 / 24LC024**
  - Complete all 16 states in `parts_cache/C2653870.json` for INA226 (`0x40`–`0x4F`).
  - Create profile `parts_cache/C284568.json` for Microchip `24LC024` / `24AA024` (SOIC-8/TSSOP-8 with `A0`, `A1`, `A2` strapping, `VCC`, `VSS`, `WP`, `SCL`, `SDA`).

- [x] **Task 4: Bus Conflict Detection & Reporter Presentation**
  - Update `src/easyeda/reporter.py`:
    - Display resolved 7-bit address in IC section headers: `### U7: SOLARADC (INA226AIDGST) [7-bit I2C: 0x41]`.
    - Cross-check all resolved I2C components connected to the same `SDA`/`SCL` net. If two components have identical addresses, flag `🔴 FAIL (I2C_ADDRESS_CONFLICT)`.
    - Summarize detected devices in `Summary of Issues`: `Detected I2C Devices: U7 @ 0x41, U8 @ 0x43, U9 @ 0x42`.

- [x] **Task 5: Unit Tests & Real Project Verification**
  - Add unit tests in `tests/test_mcu_checker.py`:
    - Test INA226 dual-pin address resolution (`U7` -> `0x41`, `U8` -> `0x43`, `U9` -> `0x42`) on the real project files.
    - Test Microchip `24AA024` / `24LC024` 3-pin strapping across various binary combinations (`0x50`, `0x51`, `0x57`).
    - Test I2C address conflict detection when two devices share the same address on the same bus.
    - Regression test ensuring all existing 40 tests pass.
