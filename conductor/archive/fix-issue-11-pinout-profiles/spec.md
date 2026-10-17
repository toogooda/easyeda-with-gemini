# Specification: Eliminate Blind Pin Assumptions & Resolve Component Types via Part Profiles & Datasheets

## Context & Problem Statement
Generic DRC tools only check basic electrical connectivity without understanding physical part pinouts or polarities. In Phase 2, `checker_diodes.py` introduced a blind fallback `1=Anode, 2=Cathode`, which directly inverted the polarity check for standard SMD diodes (IPC-7351 DO-214AC / SMA, SOD-123 have Pin 1 as Cathode). Furthermore, `parser.py` classified components purely by their reference designator prefix (`U` -> `IC`), causing diode `U5` (`1N5822`) to bypass the diode checker completely.

This project was built to eliminate guessing by resolving ground truth from part numbers, datasheets, and JIT Part Profiles.

## Requirements

### 1. Component Type Inference
- `infer_component_type()` must evaluate:
  1. Component `PartProfile.part_type` (if cached or in PartsManager).
  2. Component part number / manufacturer part / comment string against known diode models (`1N5822`, `SS34`, `1N4148`, `B5819*`, `MBR*`, `SK*`, `BAT54*`, etc.) and transistor models.
  3. Reference designator prefix only as a final fallback.
- Components like `U5` with part number `1N5822` or `1N5822/SMD2.8*4.5` must be correctly identified as `DIODE`.

### 2. PartProfile Pinout Model
- Extend `PartProfile` in `models.py` / `parts_manager.py` to support explicit `pin_map: Dict[str, str]` (mapping pin numbers or pin names to functional roles, e.g. `{"1": "CATHODE", "2": "ANODE"}` or `{"1": "BASE", "2": "COLLECTOR", "3": "EMITTER"}`).
- Add profile files for parts in real designs:
  - `C9900015672.json` (`1N5822`, DO-214AC: Pin 1 = Cathode, Pin 2 = Anode).
  - `C2903782.json` (`B772`, SOT-89: Pin 1 = Base, Pin 2 = Collector, Pin 3 = Emitter).
  - `C2844048.json` (`2SD965T-R`, SOT-89: Pin 1 = Base, Pin 2 = Collector, Pin 3 = Emitter).
  - `C2653870.json` (`INA226AIDGST`, VSSOP-10: Pinout and address strapping).

### 3. Diode Checker Overhaul (`checker_diodes.py`)
- Remove the naive `1=Anode, 2=Cathode` fallback.
- `get_diode_pins(comp, parts_manager)` must resolve Anode and Cathode pins using:
  1. Explicit pin names on the component (`A`/`ANODE`/`+` and `K`/`C`/`CATHODE`/`-`).
  2. `PartProfile.pin_map` via `PartsManager`.
  3. IPC-7351 package standard rules when package is explicitly known (`DO-214*`, `SMA`, `SMB`, `SMC`, `SOD-123`, `SOD-323` -> Pin 1 = Cathode, Pin 2 = Anode).
  4. If pin mapping cannot be determined, return a `CheckResult` with status `WARN` and message requesting manual pinout verification (`VERIFY_PINOUT`), never blindly guessing.
- Correctly catch reverse-biased power diodes (such as `U5` with Cathode on `VIN` and Anode on LDO input).

### 4. Transistor Checker Overhaul (`checker_transistors.py`)
- Ensure BJT (`Base`, `Collector`, `Emitter`) and MOSFET (`Gate`, `Drain`, `Source`) pins are resolved from `PartProfile.pin_map` or pin names, warning if unresolved rather than making blind positional assumptions.

### 5. Verification & Tests
- Unit test for `U5` backwards diode detection using both netlist and BOM.
- Unit test for package standard fallback (`DO-214AC` -> 1=K, 2=A).
- Unit test for unknown diode pinout producing `WARN` instead of false `PASS`.
- Full regression test run (`pytest -v`) ensuring all 33 existing tests pass.
