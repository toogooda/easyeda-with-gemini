# Track Spec: Phase 1 Test Bench Schematic & Graph Parser

## Goal
Build the fundamental in-memory electrical connectivity graph and parser to read EasyEDA schematic exports (BOM CSV and netlist/JSON).

## Deliverables
1. `tests/fixtures/test_schematic.json`: Realistic schematic fixture containing diodes, LEDs, transistors, I2C sensor, and STM32 microcontroller.
2. `src/easyeda/models.py`: Python dataclasses/models (`Pin`, `Component`, `Net`, `SchematicGraph`).
3. `src/easyeda/parser.py`: Parser converting EasyEDA export files into `SchematicGraph`.
4. `tests/test_parser.py`: Pytest suite verifying graph construction, pin counts, net traversal, and attribute loading.
