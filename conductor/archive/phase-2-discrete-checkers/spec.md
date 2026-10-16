# Track Spec: Phase 2 Discrete Component Checkers

## Goal
Implement rules and automated checks for discrete diodes, LEDs, BJTs, and MOSFETs, outputting structured check findings (`CheckResult`) with severity (`PASS`, `WARN`, `FAIL`).

## Deliverables
1. `src/easyeda/checker_diodes.py`:
   - Diodes: Reverse polarity orientation, flyback orientation.
   - LEDs: Polarity orientation, series resistor presence, and resistance value range check.
2. `src/easyeda/checker_transistors.py`:
   - BJTs: Base saturation resistor presence/range ($1\text{k}\Omega - 4.7\text{k}\Omega$), emitter rail check.
   - MOSFETs: Gate bias pull-up/pull-down resistor check to avoid floating gates during boot.
3. `tests/test_discrete_checkers.py`:
   - Pytest test cases verifying PASS/WARN/FAIL statuses on test fixture components.
