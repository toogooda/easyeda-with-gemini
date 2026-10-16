# High-Level Specification: EasyEDA Pro Schematic Checker

## 1. Project Goal
Enable **Antigravity** to inspect electronics schematics in **EasyEDA Pro**, identify hardware design mistakes (reversed diodes/LEDs, incorrect transistor saturation/pinouts, missing decoupling matched to datasheets, bus crossover mistakes, and invalid I2C addressing), and generate a fully rendered Markdown review report.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      1. EasyEDA Pro Data                        │
│  - Schematic Netlist (.net / JSON)                              │
│  - Bill of Materials (.csv)                                     │
│  - Attributes: Designator, Value, LCSC Part #, Datasheet Link   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                 2. JIT Datasheet & Parts Cache                  │
│  - Folder: ./parts_cache/<LCSC_ID>.json                         │
│  - Cache Miss: Download PDF -> Extract key sections -> Save     │
│  - Cache Hit: Instant load, zero token cost                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     3. Python MCP Server                        │
│  - Tools: get_schematic_summary(), inspect_component(),         │
│           check_diodes(), check_transistors(), check_buses(),   │
│           check_mcu_pinout(), verify_i2c_addresses()            │
└────────────────────────────────┬────────────────────────────────┘
                                 │ JSON-RPC (MCP)
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     4. Antigravity Skill                        │
│  - Hardware engineering review playbook & heuristics            │
│  - Outputs rendered Markdown artifact (`review_report.md`)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Net Naming & Recognition (Flexible & Natural)

No artificial or strict naming prefixes required. The tool naturally recognizes your schematic conventions:

### 3.1 Power Rails
* Recognizes standard rail names: `VIN`, `VBUS`, `VBAT`, `+5V`, `+3V3`, `+1V8`, `GND`, `AGND`.
* If a protected rail is used after a diode/fuse, names like `VIN_SYS` or `VCC` are recognized.

### 3.2 Flexible Bus & Signal Names
* Standard shorthand names are automatically parsed:
  * **I2C:** `SDA`, `SCL` (or `I2C1_SDA`, `I2C1_SCL`)
  * **UART:** `TX`, `RX`, `TX1`, `RX1`, `TX2`, `RX2`, etc.
  * **SPI:** `MOSI`, `MISO`, `SCK`, `CS` / `SS`
* Pull-up requirements for reset or control lines are determined **from the component datasheets and pin types**, not from net name suffixes.

---

## 4. Component Verification Rules

### 4.1 Diodes & LEDs
* **Power & Flyback Diodes:**
  * Reverse Polarity Protection: Verify Anode connects towards input power, Cathode towards system rail. Flag if backwards (blocking power).
  * Flyback / Snubber Diodes: Verify Cathode connects to positive rail and Anode to switched side of inductive load.
* **LEDs:**
  * **Polarity Check:** Verify Anode is oriented towards the positive driving rail/pin and Cathode towards ground or low-side driver.
  * **Current-Limiting Resistor:** Ensure a series resistor is present. Flag if missing (would burn out the LED or GPIO). Verify reasonable resistor value for normal LED brightness.

### 4.2 Transistors & MOSFETs (Switching & Saturation Focus)
Assuming transistors are primarily used as switches/drivers:
* **BJT (NPN / PNP):**
  * **Base Resistor Sizing for Saturation:** Check base resistor to ensure adequate base current ($I_B \approx I_C / 10$ or standard $1\text{k}\Omega - 4.7\text{k}\Omega$ for MCU 3.3V logic driving typical small loads like relays, LEDs, or buzzers).
  * **Pinout / Polarity:** Ensure NPN Emitter is at Ground, or PNP Emitter is at positive rail.
* **MOSFET (N-Channel / P-Channel):**
  * **Gate Drive & Floating Protection:** Ensure Gate has a pull-down resistor (N-ch) or pull-up (P-ch) to prevent floating gate states during MCU reset/boot.
  * **Gate Voltage ($V_{GS(th)}$) Check:** Flag if a MOSFET requires 5V/10V gate drive when operated from a 3.3V MCU pin.

### 4.3 ICs & Peripherals (Strictly from Cached Datasheet)
* **Decoupling Capacitors (No Generalizations):**
  * Values, quantities, and placement are **extracted strictly from the cached datasheet profile** for that specific IC (e.g., $10\mu\text{F} + 100\text{nF}$, or $1\mu\text{F}$ only). No generic 100nF assumptions.
* **I2C Strapping & Address Calculation:**
  * Detect connection of address strapping pins (`ADDR`, `A0`, `A1`, etc.) to `GND`, `VCC`, `SDA`, or `SCL`.
  * Compute and display the resulting 7-bit $I^2C$ address.
  * Verify presence of bus pull-up resistors on `SDA` and `SCL`.

### 4.4 Microcontrollers (MCUs)
* **Dual Crystal Support (HSE & LSE / RTC):**
  * **HSE (High-Speed External):** `OSC_IN` / `OSC_OUT` (e.g. 8MHz–16MHz) checked for load capacitors tied to GND based on datasheet values.
  * **LSE (Low-Speed External / RTC):** `PC14-OSC32_IN` / `PC15-OSC32_OUT` (32.768kHz). If present on the schematic, verify correct pin mapping and recommended low-pF load capacitors (typically $6\text{pF} - 12\text{pF}$). If not used, verify pins are left or tied per datasheet guidelines.
* **Power Pins & Analog Filtering:** Verify all power pins (`VDD_1`, `VDD_2`, `VDDA`, `VSS`) are connected and have the exact decoupling capacitors specified by the datasheet/reference design.
* **Bus Alternate Function & Crossover Checks:**
  * **UART:** MCU `TX` $\to$ Peripheral `RX`, MCU `RX` $\leftarrow$ Peripheral `TX` (and per-channel: `TX1` to `RX1`, `TX2` to `RX2`).
  * **CAN:** MCU `CAN_TX` $\to$ PHY `TXD`, MCU `CAN_RX` $\leftarrow$ PHY `RXD`.
  * **SPI:** MCU `MOSI` $\to$ Device `MOSI`/`SDI`, MCU `MISO` $\leftarrow$ Device `MISO`/`SDO`.
  * **Pin Function Validity:** Verify assigned pin actually supports the required hardware peripheral.

---

## 5. JIT Part Profile Schema (`parts_cache/<LCSC_ID>.json`)

```json
{
  "lcsc_part": "C8734",
  "part_number": "STM32F103C8T6",
  "type": "MCU",
  "voltage_limits": { "min": 2.0, "max": 3.6, "typical": 3.3 },
  "power_pins": [
    { "pin": "VDD_1", "rail": "3.3V", "decoupling": "100nF" },
    { "pin": "VDD_2", "rail": "3.3V", "decoupling": "100nF" },
    { "pin": "VDD_3", "rail": "3.3V", "decoupling": "100nF" },
    { "pin": "VDDA",  "rail": "3.3V", "decoupling": "10nF + 1uF", "notes": "Analog filter" }
  ],
  "ground_pins": ["VSS_1", "VSS_2", "VSS_3", "VSSA"],
  "crystals": {
    "hse": { "in": "OSC_IN", "out": "OSC_OUT", "recommended_caps": "15pF-25pF", "required": false },
    "lse_rtc": { "in": "PC14-OSC32_IN", "out": "PC15-OSC32_OUT", "recommended_caps": "6pF-10pF", "required": false }
  },
  "reset_pin": { "pin": "NRST", "active": "LOW", "recommended": "10k pull-up + 100nF" },
  "boot_strapping": [
    { "pin": "BOOT0", "normal_run_state": "GND", "recommendation": "10k pull-down" }
  ],
  "peripherals": {
    "USART1": { "tx": ["PA9", "PB6"], "rx": ["PA10", "PB7"] },
    "USART2": { "tx": ["PA2"], "rx": ["PA3"] },
    "I2C1":   { "scl": ["PB6", "PB8"], "sda": ["PB7", "PB9"] },
    "SPI1":   { "sck": ["PA5", "PB3"], "mosi": ["PA7", "PB5"], "miso": ["PA6", "PB4"] },
    "CAN1":   { "tx": ["PA12", "PB9"], "rx": ["PA11", "PB8"] }
  }
}
```

---

## 6. Review Report Delivery (Visual Markdown Artifact)

The review report is written directly to an Antigravity Markdown Artifact (`review_report.md`). This renders cleanly in the IDE side-by-side with your project, showing formatted tables, status badges, and expandable details.

### Example Rendered View:

# Schematic Review Report

## 1. Diodes & LEDs
| Designator | Part Number | Type | Anode Net | Cathode Net | Resistor | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| D1 | SS34 | Schottky | VIN | VIN_SYS | N/A | 🟢 PASS | Reverse polarity protection correctly oriented |
| D2 | 1N4148 | Switching | GND | RELAY_COIL | N/A | 🔴 FAIL | Backwards: Cathode should connect to +12V rail |
| LED1 | 0805 Red | LED | +3V3 | MCU_LED | R3 (1k) | 🟢 PASS | Polarity correct, 1k limits current to ~1.5mA |
| LED2 | 0805 Green | LED | MCU_STATUS | GND | None | 🔴 FAIL | Missing current-limiting resistor! Will burn GPIO |

## 2. Transistors & FETs (Switching & Saturation)
| Designator | Part Number | Type | Control Pin | Base/Gate R | Pull-up/down | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Q1 | 2N7002 | N-Ch MOSFET | MCU_GPIO4 | 100R | 10k to GND | 🟢 PASS | Gate pulled low during boot, logic level compatible |
| Q2 | S8050 | NPN BJT | MCU_GPIO5 | None | None | 🟡 WARN | Direct connection to Base; add 1k–2.2k resistor for saturation |

## 3. ICs & Peripherals
### U2: TMP102 (Temperature Sensor)
* **Datasheet:** [Cached: parts_cache/C62973.json]
* **I2C Address:** Pin `ADD0` tied to `GND` $\to$ **7-bit Address: 0x48**
* **Decoupling:** `V+` (Pin 2) has C3 (100nF) to GND per datasheet spec $\to$ 🟢 **PASS**
* **Buses:** `SDA` has R4 (4.7k) pull-up, `SCL` has R5 (4.7k) pull-up $\to$ 🟢 **PASS**

## 4. Microcontroller (U1: STM32F103C8T6)
### Power & Decoupling (Datasheet Spec)
* `VDD_1`, `VDD_2`, `VDD_3`: Decoupled with individual 100nF ceramic capacitors to GND $\to$ 🟢 **PASS**
* `VDDA`: Filtered with 10nF + 1uF ceramic capacitors $\to$ 🟢 **PASS**

### Oscillator Circuits
* **HSE (8MHz Crystal):** `OSC_IN` / `OSC_OUT` with 22pF load caps $\to$ 🟢 **PASS**
* **LSE / RTC (32.768kHz):** `PC14` / `PC15` with 10pF load caps $\to$ 🟢 **PASS**

### Bus Pin Mapping
| Pin # | Pin Name | Connected Net | Target Device & Pin | Function Validated | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 30 | PA9 | TX1 | U4 (CH340G) Pin 2 (RXD) | USART1_TX (Output) | 🟢 PASS | Proper TX -> RX crossover |
| 31 | PA10 | RX1 | U4 (CH340G) Pin 3 (TXD) | USART1_RX (Input) | 🟢 PASS | Proper RX <- TX crossover |
| 32 | PA11 | CAN_RX | U5 (TJA1050) Pin 1 (TXD)| CAN1_RX (Input) | 🔴 FAIL | Swapped: Connect to RXD (Pin 4), not TXD! |

---
## Summary of Issues
* 🔴 **CRITICAL (3):** 
  * D2 is oriented backwards across RELAY_COIL.
  * LED2 has no series resistor on MCU_STATUS.
  * PA11 (CAN_RX) is connected to TXD on U5.
* 🟡 **WARNING (1):** 
  * Q2 base needs a series resistor (1k–2.2k) for saturation.
* 🟢 **INFO:** 
  * I2C Devices: TMP102 @ 0x48.
