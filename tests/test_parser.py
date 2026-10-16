from pathlib import Path
import pytest
from src.easyeda.parser import parse_schematic_json, infer_component_type

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_schematic.json"


def test_infer_component_type():
    assert infer_component_type("D1", "SS34") == "DIODE"
    assert infer_component_type("LED1", "Red") == "LED"
    assert infer_component_type("D3", "0805 Red LED") == "LED"
    assert infer_component_type("R1", "10k") == "RESISTOR"
    assert infer_component_type("C1", "100nF") == "CAPACITOR"
    assert infer_component_type("Q1", "2N7002") == "MOSFET_N"
    assert infer_component_type("Q2", "S8050") == "BJT_NPN"
    assert infer_component_type("U1", "STM32F103C8T6") == "MCU"
    assert infer_component_type("U2", "TMP102") == "IC_I2C"
    assert infer_component_type("Y1", "8MHz") == "CRYSTAL"


def test_parse_fixture_loads_graph():
    graph = parse_schematic_json(FIXTURE_PATH)
    assert graph.project_name == "TestBench_Board"
    assert len(graph.components) >= 15
    assert len(graph.nets) >= 15


def test_component_and_pin_retrieval():
    graph = parse_schematic_json(FIXTURE_PATH)
    u1 = graph.get_component("U1")
    assert u1 is not None
    assert u1.value == "STM32F103C8T6"
    assert u1.lcsc_id == "C8734"
    assert u1.comp_type == "MCU"

    pa9 = u1.get_pin_by_name("PA9")
    assert pa9 is not None
    assert pa9.net == "UART1_TX"


def test_net_connections():
    graph = parse_schematic_json(FIXTURE_PATH)
    v33 = graph.get_net("+3V3")
    assert v33 is not None
    assert v33.is_power is True
    assert v33.is_ground is False

    gnd = graph.get_net("GND")
    assert gnd is not None
    assert gnd.is_ground is True
    assert gnd.is_power is False

    # Check connected pins on I2C_SDA
    sda_pins = graph.get_connected_pins("I2C_SDA")
    comp_refs = {p.component_ref for p in sda_pins}
    assert "U1" in comp_refs
    assert "U2" in comp_refs
    assert "R7" in comp_refs


def test_graph_helpers():
    graph = parse_schematic_json(FIXTURE_PATH)

    # Find series resistor for LED1
    r_led = graph.find_resistor_between("NET_LED1_K", "MCU_LED1")
    assert r_led is not None
    assert r_led.ref_des == "R1"
    assert r_led.value == "1k"

    # Find decoupling capacitors between +3V3 and GND
    caps = graph.find_capacitors_between("+3V3", "GND")
    cap_refs = {c.ref_des for c in caps}
    assert "C1" in cap_refs
    assert "C2" in cap_refs
    assert "C3" in cap_refs
    assert "C11" in cap_refs


def test_parse_real_protel_netlist():
    tel_path = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"
    if not tel_path.exists():
        pytest.skip("Protel netlist file not found")

    from src.easyeda.parser import parse_protel_netlist
    graph = parse_protel_netlist(tel_path)

    # Validate components
    assert "U1" in graph.components
    assert "X1" in graph.components
    assert "X2" in graph.components
    assert "R5" in graph.components
    assert "R6" in graph.components

    # Verify U1 has pins
    u1 = graph.get_component("U1")
    assert u1 is not None
    assert len(u1.pins) > 0

    # Verify nets
    assert "GND" in graph.nets
    assert "3V3" in graph.nets
    assert "SCL" in graph.nets
    assert "SDA" in graph.nets

    # Verify SCL connects to U1 pin 42, R6 pin 1
    scl_pins = graph.get_connected_pins("SCL")
    scl_refs = {p.component_ref for p in scl_pins}
    assert "U1" in scl_refs
    assert "R6" in scl_refs

