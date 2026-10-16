from pathlib import Path
import pytest

from src.easyeda.parser import parse_schematic_json, parse_protel_netlist
from src.easyeda.models import CheckStatus
from src.easyeda.parts_manager import PartsManager
from src.easyeda.datasheet_extractor import parse_bom, merge_bom_into_graph
from src.easyeda.checker_ics import check_ic_decoupling, check_i2c_peripheral
from src.easyeda.checker_mcu import check_microcontroller
from src.easyeda.checker_buses import check_bus_crossovers

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
