# Track Plan: Zero-Trust Engineering Review Skill, Pure Circuit Telemetry, and Stale Session Payload Lifecycle

- [x] **Task 1: Zero-Trust Engineering Review Checklist in `SKILL.md`**
  - Update `skills/easyeda-schematic-reviewer/SKILL.md` (repository skill).
  - Update `C:\Users\USER\.gemini\config\skills\easyeda-schematic-reviewer\SKILL.md` (global skill).
  - Mandate zero-trust protocol: treat Python outputs as raw telemetry; never accept `PASS` badges as authoritative.
  - Insert detailed engineering checklist:
    - BJT/MOSFET physical pinout & orientation (High-Side PNP Emitter on power rail, Collector on load; Low-Side NPN Emitter on GND; Gate/Base resistors).
    - Diode/LED polarities & ballast resistors.
    - I2C strapping resolution, 7-bit slave address collisions, and bus pull-ups.
    - MCU dual crystals (HSE 8MHz / LSE 32.768kHz) + load caps, NRST 100nF filter, BOOT0 pull-down.
    - MCU silicon Alternate Function mappings.

- [x] **Task 2: Pure Telemetry Tables in Transistor & Diode Reporting**
  - Update `src/easyeda/reporter.py` and `checker_transistors.py`:
    - Strip misleading pass/fail judgment messages from transistor checks.
    - Expose full pin-to-net connectivity columns:
      `Designator | Value | Package | Type | Base / Gate | Collector / Drain | Emitter / Source | Series R | Bias / Pull R | Status | Notes`
    - Expose full pinout telemetry for diodes and LEDs.

- [x] **Task 3: Stale Session Payload Lifecycle & Cache Isolation**
  - Update `src/easyeda/server.py`:
    - Implement `archive_stale_payload()`: rename existing `.last_raw_payload.json` to `.stale_raw_payload.json`.
    - In `audit_schematic('live')`, require fresh push during the active session; do not silently audit stale files on timeout.
    - Preserve active session payload in memory and `.last_raw_payload.json` for subsequent in-session queries.

- [x] **Task 4: Testing & Verification**
  - Update/add unit tests in `tests/test_discrete_checkers.py` and `tests/test_mcp_server.py`.
  - Run full test suite (`python -m pytest`) ensuring 100% pass rate (44/44 passing).
  - Verified live audit timeout behavior: reports that no live schematic push was received in the current session and archives stale payload.
