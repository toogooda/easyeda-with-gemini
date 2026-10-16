from pathlib import Path
import pytest

from src.easyeda.parts_manager import PartsManager, PartProfile
from src.easyeda.datasheet_extractor import parse_bom, merge_bom_into_graph
from src.easyeda.parser import parse_protel_netlist

CACHE_DIR = Path(__file__).parent.parent / "parts_cache"
BOM_XLSX = Path(__file__).parent / "BOM_RemoteNode_Schematic_2026-10-17.xlsx"
NETLIST_TEL = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"


def test_parts_manager_cache_hits():
    pm = PartsManager(CACHE_DIR)

    assert pm.is_cached("C62973") is True
    assert pm.is_cached("c62973") is True  # case insensitive
    assert pm.is_cached("C8734") is True
    assert pm.is_cached("NONEXISTENT_PART") is False

    parts = pm.list_cached_parts()
    assert "C62973" in parts
    assert "C8734" in parts


def test_tmp102_profile_schema():
    pm = PartsManager(CACHE_DIR)
    p = pm.get_profile("C62973")
    assert p is not None
    assert p.part_number == "TMP102AIDRLR"
    assert p.part_type == "I2C_SENSOR"
    assert p.i2c_addresses.get("ADD0=GND") == "0x48"
    assert p.i2c_addresses.get("ADD0=V+") == "0x49"
    assert len(p.power_pins) == 1
    assert p.power_pins[0]["decoupling"] == "100nF"


def test_stm32_profile_schema():
    pm = PartsManager(CACHE_DIR)
    p = pm.get_profile("C8734")
    assert p is not None
    assert p.part_number == "STM32F103C8T6"
    assert p.part_type == "MCU"

    # Crystals
    assert "hse" in p.crystals
    assert p.crystals["hse"]["in_name"] == "OSC_IN"
    assert "lse_rtc" in p.crystals
    assert p.crystals["lse_rtc"]["in_name"] == "PC14-OSC32_IN"

    # Peripherals
    assert "USART1" in p.peripherals
    assert "PA9" in p.peripherals["USART1"]["tx"]
    assert "PA10" in p.peripherals["USART1"]["rx"]
    assert "CAN1" in p.peripherals
    assert "PA12" in p.peripherals["CAN1"]["tx"]


def test_parts_manager_save_and_reload(tmp_path):
    pm = PartsManager(tmp_path)
    new_profile = PartProfile(
        lcsc_part="C12345",
        part_number="TEST_IC",
        part_type="REGULATOR",
        voltage_limits={"min": 3.0, "max": 5.5}
    )
    saved_path = pm.save_profile(new_profile)
    assert saved_path.exists()

    loaded = pm.get_profile("C12345")
    assert loaded is not None
    assert loaded.part_number == "TEST_IC"
    assert loaded.voltage_limits["max"] == 5.5


def test_parse_real_bom_xlsx():
    if not BOM_XLSX.exists():
        pytest.skip("BOM xlsx file not found")

    bom_data = parse_bom(BOM_XLSX)
    assert len(bom_data) > 0

    # Test individual components expanded from lists (e.g. C1,C2,C3)
    assert "C1" in bom_data
    assert "C2" in bom_data
    assert bom_data["C1"]["lcsc_id"] == "C24497"
    assert bom_data["C1"]["datasheet"].startswith("http")

    assert "U1" in bom_data


def test_merge_bom_into_netlist_graph():
    if not BOM_XLSX.exists() or not NETLIST_TEL.exists():
        pytest.skip("Files not found")

    graph = parse_protel_netlist(NETLIST_TEL)
    bom_data = parse_bom(BOM_XLSX)

    # Before merge, C1 has no lcsc_id or datasheet
    c1 = graph.get_component("C1")
    assert c1 is not None

    merge_bom_into_graph(graph, bom_data)

    # After merge, C1 must have LCSC ID and datasheet URL
    assert c1.lcsc_id == "C24497"
    assert c1.datasheet.startswith("http")
