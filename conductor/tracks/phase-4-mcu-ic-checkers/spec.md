# Track Spec: Phase 4 IC, I2C & Microcontroller Checker Engine

## Goal
Connect the schematic electrical graph to cached chip profiles (`parts_cache/<LCSC_ID>.json`) to validate exact decoupling capacitor values, compute I2C device addresses, check dual crystal circuits (HSE & LSE 32.768kHz RTC), and verify bus crossovers (UART, CAN, SPI).

## Deliverables
1. `src/easyeda/checker_ics.py`:
   - Exact decoupling verification per cached profile.
   - I2C address strapping resolution (calculates 7-bit addresses like `0x48`).
   - I2C pull-up resistor verification on SDA/SCL.
2. `src/easyeda/checker_mcu.py`:
   - Power pins (VDD, VDDA, VSS) and decoupling caps per pin.
   - Dual crystal check (HSE 8MHz and LSE 32.768kHz RTC with load caps).
   - Reset (NRST) and Boot (BOOT0) pin circuitry.
3. `src/easyeda/checker_buses.py`:
   - UART TX/RX crossover validation.
   - CAN bus transceiver connection check (flags swapped RX/TX).
   - SPI bus direction verification.
4. `tests/test_mcu_checker.py`:
   - Pytest suite asserting correct detection on test fixtures and real-world project files.
