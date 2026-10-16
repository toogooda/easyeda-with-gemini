# Track Plan: Phase 3 JIT Part Cache & Datasheet Extractor

- [x] **Task 1: Part Profile Models & Cache Manager (`src/easyeda/parts_manager.py`)**
  - Implement dataclasses for `PartProfile`, `PowerPinSpec`, `CrystalSpec`, `I2CSpec`, `PeripheralSpec`.
  - Implement `PartsManager` with methods:
    - `get_profile(lcsc_id) -> Optional[PartProfile]`
    - `save_profile(profile) -> None`
    - `is_cached(lcsc_id) -> bool`
- [x] **Task 2: BOM Ingestion & Datasheet Fetcher (`src/easyeda/datasheet_extractor.py`)**
  - Read EasyEDA BOM files (CSV / Excel `.xlsx`) to extract component designators, LCSC IDs, and datasheet links.
  - Implement PDF downloader to save files into `datasheets/<LCSC_ID>.pdf`.
  - Merge BOM metadata into `SchematicGraph` so every component knows its LCSC ID and datasheet URL.
- [x] **Task 3: Seed Key Part Profiles in `parts_cache/`**
  - Create `parts_cache/C62973.json` (TMP102 I2C sensor: 100nF decoupling, ADD0 strapping table for 0x48-0x4B).
  - Create `parts_cache/C8734.json` (STM32F103C8T6 MCU: VDD/VSS/VDDA pins, HSE 8MHz / LSE 32.768kHz RTC crystals, NRST, BOOT0, UART/I2C/SPI/CAN pin maps).
- [x] **Task 4: Unit Test Suite (`tests/test_parts_manager.py`)**
  - Test BOM ingestion on `BOM_RemoteNode_Schematic_2026-10-17.xlsx`.
  - Test cache hit loading and profile validation.
  - Test merging BOM attributes into schematic graph.
