# Track Plan: Fix Pinout Assumptions and Resolve Part Profiles via Datasheets

- [x] **Task 1: PartProfile Schema & Cache Updates**
  - Add `pin_map: Dict[str, str]` to `PartProfile` in `src/easyeda/parts_manager.py`.
  - Add cached part profiles for real design parts:
    - `parts_cache/C9900015672.json` (`1N5822`, DO-214AC: 1=CATHODE, 2=ANODE).
    - `parts_cache/C2903782.json` (`B772`, SOT-89: 1=BASE, 2=COLLECTOR, 3=EMITTER).
    - `parts_cache/C2844048.json` (`2SD965T-R`, SOT-89: 1=BASE, 2=COLLECTOR, 3=EMITTER).
    - `parts_cache/C2653870.json` (`INA226AIDGST`, VSSOP-10).

- [x] **Task 2: Component Classification by Part Number & Profile**
  - Update `infer_component_type()` in `src/easyeda/parser.py`:
    - Recognize diodes by part number pattern (`1N5822`, `SS*`, `1N4148`, `B5819*`, `MBR*`, `SK*`, `BAT*`, etc.) regardless of ref_des prefix.
    - Check `PartsManager` profile if LCSC ID or part number is available.
  - Update `parse_protel_netlist()` and JSON parser to re-evaluate component types when BOM metadata is merged.

- [x] **Task 3: Diode Checker Ground-Truth Pin Resolution**
  - Overhaul `get_diode_pins()` in `src/easyeda/checker_diodes.py`:
    - Check pin names (`A`/`ANODE` vs `K`/`CATHODE`).
    - Query `PartsManager` for `pin_map`.
    - Apply IPC-7351 package standard for verified packages (`DO-214*`, `SMA`, `SMB`, `SMC`, `SOD-123`, `SOD-323`: 1=K, 2=A).
    - Remove blind `1=Anode, 2=Cathode` fallback.
    - Return `WARN` with `VERIFY_PINOUT` if pin roles cannot be determined.
  - Pass `PartsManager` into `check_diodes_and_leds()` and `check_diode()`.

- [x] **Task 4: Transistor Checker Ground-Truth Pin Resolution**
  - Update `src/easyeda/checker_transistors.py` to support `PartProfile.pin_map` resolution for BJT and MOSFET pins.

- [x] **Task 5: Reporter Integration & Unit Tests**
  - Update `src/easyeda/reporter.py` to pass `PartsManager` to diode checkers.
  - Add comprehensive unit tests in `tests/test_discrete_checkers.py`:
    - Test `U5` (`1N5822`) correctly detected as backwards diode (🔴 CRITICAL FAIL).
    - Test DO-214AC package standard pin resolution.
    - Test unknown diode pinout warning (no silent assumption).
    - Regression test ensuring all 37 tests pass.
