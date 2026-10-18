from pathlib import Path
import pytest

from src.easyeda.parser import parse_schematic_json, parse_protel_netlist
from src.easyeda.models import CheckStatus, Component, Pin, SchematicGraph
from src.easyeda.parts_manager import PartsManager
from src.easyeda.datasheet_extractor import parse_bom, merge_bom_into_graph
from src.easyeda.checker_ics import check_ic_decoupling, check_i2c_peripheral
from src.easyeda.checker_mcu import check_microcontroller
from src.easyeda.checker_buses import check_bus_crossovers
from src.easyeda.reporter import generate_schematic_report

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_schematic.json"
CACHE_DIR = Path(__file__).parent.parent / "parts_cache"
REAL_TEL_PATH = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"
REAL_BOM_PATH = Path(__file__).parent / "BOM_RemoteNode_Schematic_2026-10-17.xlsx"


def test_tmp102_decoupling_and_i2c_address():
    graph = parse_schematic_json(FIXTURE_PATH)
    pm = PartsManager(CACHE_DIR)
    u2 = graph.get_component("U2")
    assert u2 is not None

    # Check decoupling
    decoupling_results = check_ic_decoupling(u2, graph, pm)
    assert len(decoupling_results) >= 1
    assert decoupling_results[0].status == CheckStatus.PASS
    assert "100nF" in decoupling_results[0].message

    # Check I2C address resolution and bus pull-ups
    i2c_results = check_i2c_peripheral(u2, graph, pm)
    assert len(i2c_results) >= 3

    # Check strapping address resolved to 0x48
    addr_res = [r for r in i2c_results if "0x48" in r.message]
    assert len(addr_res) == 1
    assert addr_res[0].status == CheckStatus.PASS

    # Check SDA and SCL pull-ups
    sda_res = [r for r in i2c_results if "SDA" in r.message]
    assert len(sda_res) == 1
    assert sda_res[0].status == CheckStatus.PASS

    scl_res = [r for r in i2c_results if "SCL" in r.message]
    assert len(scl_res) == 1
    assert scl_res[0].status == CheckStatus.PASS


def test_stm32_mcu_power_crystals_and_boot():
    graph = parse_schematic_json(FIXTURE_PATH)
    pm = PartsManager(CACHE_DIR)
    u1 = graph.get_component("U1")
    assert u1 is not None

    results = check_microcontroller(u1, graph, pm)
    statuses = [r.status for r in results]
    assert CheckStatus.FAIL not in statuses

    # Verify HSE 8MHz crystal passed
    hse_res = [r for r in results if "HSE" in r.message]
    assert len(hse_res) == 1
    assert hse_res[0].status == CheckStatus.PASS
    assert "22pF" in hse_res[0].message

    # Verify LSE 32.768kHz RTC crystal passed
    lse_res = [r for r in results if "LSE" in r.message]
    assert len(lse_res) == 1
    assert lse_res[0].status == CheckStatus.PASS
    assert "10pF" in lse_res[0].message


def test_bus_crossovers_detects_swapped_can_and_valid_uart():
    graph = parse_schematic_json(FIXTURE_PATH)
    pm = PartsManager(CACHE_DIR)
    u1 = graph.get_component("U1")
    assert u1 is not None

    bus_results = check_bus_crossovers(u1, graph, pm)
    assert len(bus_results) >= 3

    # UART1 to CH340G should pass
    uart_pass = [r for r in bus_results if "UART" in r.message and r.status == CheckStatus.PASS]
    assert len(uart_pass) >= 1

    # CAN bus to TJA1050 (U5) was intentionally swapped in fixture: CAN_RX connected to TXD!
    can_fails = [r for r in bus_results if "CAN" in r.message and r.status == CheckStatus.FAIL]
    assert len(can_fails) >= 1
    assert "Swapped CAN transceiver pins" in can_fails[0].message


def test_mcu_checks_on_real_project():
    if not REAL_TEL_PATH.exists() or not REAL_BOM_PATH.exists():
        pytest.skip("Real project files not found")

    graph = parse_protel_netlist(REAL_TEL_PATH)
    bom_data = parse_bom(REAL_BOM_PATH)
    merge_bom_into_graph(graph, bom_data)

    pm = PartsManager(CACHE_DIR)
    u1 = graph.get_component("U1")
    assert u1 is not None

    results = check_microcontroller(u1, graph, pm)
    assert len(results) > 0

    # Ensure crystals on real board are validated
    crystal_results = [r for r in results if "Crystal" in r.message]
    assert len(crystal_results) >= 1


def test_ina226_real_board_i2c_address_resolution():
    """Validates that U7, U8, U9 on the real board resolve to 0x41, 0x43, 0x42 respectively."""
    if not REAL_TEL_PATH.exists() or not REAL_BOM_PATH.exists():
        pytest.skip("Real project files not found")

    graph = parse_protel_netlist(REAL_TEL_PATH)
    bom_data = parse_bom(REAL_BOM_PATH)
    merge_bom_into_graph(graph, bom_data)

    pm = PartsManager(CACHE_DIR)

    # U7 (SOLARADC): A1=GND, A0=3V3 -> 0x41
    u7 = graph.get_component("U7")
    u7_res = check_i2c_peripheral(u7, graph, pm)
    u7_addr = next((r.details.get("i2c_address") for r in u7_res if "i2c_address" in r.details), None)
    assert u7_addr == "0x41"

    # U8 (P1ADC): A1=GND, A0=SCL -> 0x43
    u8 = graph.get_component("U8")
    u8_res = check_i2c_peripheral(u8, graph, pm)
    u8_addr = next((r.details.get("i2c_address") for r in u8_res if "i2c_address" in r.details), None)
    assert u8_addr == "0x43"

    # U9 (CAPADC): A1=GND, A0=SDA -> 0x42
    u9 = graph.get_component("U9")
    u9_res = check_i2c_peripheral(u9, graph, pm)
    u9_addr = next((r.details.get("i2c_address") for r in u9_res if "i2c_address" in r.details), None)
    assert u9_addr == "0x42"

    # Verify report formatting
    report = generate_schematic_report(graph, pm)
    assert "U7: SOLARADC [7-bit I2C: 0x41]" in report
    assert "U8: P1ADC [7-bit I2C: 0x43]" in report
    assert "U9: CAPADC [7-bit I2C: 0x42]" in report
    assert "Detected I2C Devices: U7 (SOLARADC) @ 0x41, U8 (P1ADC) @ 0x43, U9 (CAPADC) @ 0x42" in report


def test_microchip_24lc024_eeprom_3pin_strapping():
    """Validates Microchip 24AA024 / 24LC024 EEPROM 3-pin strapping (A2, A1, A0 -> 0x50 to 0x57)."""
    pm = PartsManager(CACHE_DIR)

    test_cases = [
        ({"A2": "GND", "A1": "GND", "A0": "GND"}, "0x50"),
        ({"A2": "GND", "A1": "GND", "A0": "3V3"}, "0x51"),
        ({"A2": "3V3", "A1": "GND", "A0": "3V3"}, "0x55"),
        ({"A2": "3V3", "A1": "3V3", "A0": "3V3"}, "0x57"),
    ]

    for pin_connections, expected_addr in test_cases:
        graph = SchematicGraph()
        eeprom = Component(ref_des="U10", value="24LC024T-I/SN", package="SOIC-8", lcsc_id="C284568", comp_type="IC_I2C")

        # Add pins: 1=A0, 2=A1, 3=A2, 4=VSS, 5=SDA, 6=SCL, 7=WP, 8=VCC
        eeprom.add_pin(Pin("1", "A0", pin_connections["A0"]))
        eeprom.add_pin(Pin("2", "A1", pin_connections["A1"]))
        eeprom.add_pin(Pin("3", "A2", pin_connections["A2"]))
        eeprom.add_pin(Pin("4", "VSS", "GND"))
        eeprom.add_pin(Pin("5", "SDA", "SDA"))
        eeprom.add_pin(Pin("6", "SCL", "SCL"))
        eeprom.add_pin(Pin("7", "WP", "GND"))
        eeprom.add_pin(Pin("8", "VCC", "3V3"))
        graph.add_component(eeprom)

        # Add pull-ups so pull-up check passes
        r_sda = Component(ref_des="R10", value="4.7k", comp_type="RESISTOR")
        r_sda.add_pin(Pin("1", "1", "3V3"))
        r_sda.add_pin(Pin("2", "2", "SDA"))
        graph.add_component(r_sda)

        r_scl = Component(ref_des="R11", value="4.7k", comp_type="RESISTOR")
        r_scl.add_pin(Pin("1", "1", "3V3"))
        r_scl.add_pin(Pin("2", "2", "SCL"))
        graph.add_component(r_scl)

        res_list = check_i2c_peripheral(eeprom, graph, pm)
        addr = next((r.details.get("i2c_address") for r in res_list if "i2c_address" in r.details), None)
        assert addr == expected_addr, f"Expected {expected_addr} for {pin_connections}, got {addr}"


def test_i2c_address_conflict_detection():
    """Validates that address collision on the same I2C bus produces a CRITICAL FAIL."""
    pm = PartsManager(CACHE_DIR)
    graph = SchematicGraph()

    # Create two devices on the same bus both strapped to 0x48
    d1 = Component(ref_des="U1", value="TMP102", comp_type="IC_I2C", lcsc_id="C435555")
    d1.add_pin(Pin("1", "SCL", "SCL"))
    d1.add_pin(Pin("2", "GND", "GND"))
    d1.add_pin(Pin("3", "ALERT", "ALERT1"))
    d1.add_pin(Pin("4", "ADD0", "GND"))  # ADD0=GND -> 0x48
    d1.add_pin(Pin("5", "V+", "3V3"))
    d1.add_pin(Pin("6", "SDA", "SDA"))
    graph.add_component(d1)

    d2 = Component(ref_des="U2", value="TMP102", comp_type="IC_I2C", lcsc_id="C435555")
    d2.add_pin(Pin("1", "SCL", "SCL"))
    d2.add_pin(Pin("2", "GND", "GND"))
    d2.add_pin(Pin("3", "ALERT", "ALERT2"))
    d2.add_pin(Pin("4", "ADD0", "GND"))  # ADD0=GND -> 0x48 (Collision!)
    d2.add_pin(Pin("5", "V+", "3V3"))
    d2.add_pin(Pin("6", "SDA", "SDA"))
    graph.add_component(d2)

    # Add pull-ups so pullup check passes and only the collision is CRITICAL
    r_sda = Component(ref_des="R1", value="4.7k", comp_type="RESISTOR")
    r_sda.add_pin(Pin("1", "1", "3V3"))
    r_sda.add_pin(Pin("2", "2", "SDA"))
    graph.add_component(r_sda)

    r_scl = Component(ref_des="R2", value="4.7k", comp_type="RESISTOR")
    r_scl.add_pin(Pin("1", "1", "3V3"))
    r_scl.add_pin(Pin("2", "2", "SCL"))
    graph.add_component(r_scl)

    c1 = Component(ref_des="C1", value="100nF", comp_type="CAPACITOR")
    c1.add_pin(Pin("1", "1", "3V3"))
    c1.add_pin(Pin("2", "2", "GND"))
    graph.add_component(c1)

    report = generate_schematic_report(graph, pm)
    assert "I2C Address Collision" in report
    assert "CRITICAL (1)" in report

