# Track Spec: Phase 3 JIT Part Cache & Datasheet Extractor

## Goal
Implement the Just-In-Time (JIT) chip profile cache and datasheet downloader/parser, utilizing the datasheet URLs provided by EasyEDA BOM and schematic attributes.

## Deliverables
1. `src/easyeda/parts_manager.py`:
   - Data models for `PartProfile`, `PowerPinSpec`, `CrystalSpec`, `I2CSpec`, `PeripheralSpec`.
   - Local directory cache management (`parts_cache/<LCSC_ID>.json`).
   - Profile serialization, loading, and schema validation.
2. `src/easyeda/datasheet_extractor.py`:
   - Ingesting BOM files (CSV / Excel) to extract LCSC part numbers and datasheet URLs.
   - Downloading datasheet PDFs to `datasheets/<LCSC_ID>.pdf`.
   - Text parsing / targeted extraction helpers for Pinouts, Decoupling, and I2C address tables.
3. `parts_cache/`:
   - `C62973.json` (TMP102AIDRLR I2C temperature sensor).
   - `C8734.json` (STM32F103C8T6 MCU).
4. `tests/test_parts_manager.py`:
   - Pytest suite verifying BOM reading, cache lookup, profile serialization, and fallback downloading.
