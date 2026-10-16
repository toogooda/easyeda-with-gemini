# easyeda-with-gemini

Automated hardware schematic reviewer connecting **Antigravity / Gemini** to **EasyEDA Pro** via Model Context Protocol (MCP).

## Overview
`easyeda-with-gemini` inspects electronics schematics in EasyEDA Pro to identify design mistakes before PCB layout or manufacturing:
* **Diodes & LEDs:** Checks polarity, reverse-polarity protection, flyback diode orientation, and current-limiting resistor sizing.
* **Transistors & FETs:** Checks BJT base resistor sizing for saturation, emitter/collector orientation, and MOSFET gate pull-up/pull-down bias.
* **ICs & Peripherals:** Audits decoupling capacitors against exact datasheet requirements, traces $I^2C$ address strapping pins, and calculates 7-bit $I^2C$ addresses.
* **Microcontrollers:** Validates dual crystals (HSE & LSE 32.768kHz RTC), power rail filtering, and checks peripheral bus pin mappings (UART TX/RX crossover, CAN TX/RXD, SPI).
* **Just-In-Time (JIT) Part Library:** Downloads datasheets on first encounter via EasyEDA LCSC links, generates structured component profiles (`parts_cache/`), and caches them for fast, zero-token subsequent audits.

## Architecture
1. **EasyEDA Pro Data Source:** Reads schematic netlists/exports or connects via live local WebSocket extension.
2. **JIT Parts Cache:** Stores structured chip pinouts, decoupling requirements, and alternate functions in `./parts_cache/`.
3. **MCP Server:** Exposes standard verification tools to Antigravity/Gemini.
4. **Antigravity Skill:** Orchestrates the hardware engineering review and outputs interactive, rendered Markdown reports (`review_report.md`).
