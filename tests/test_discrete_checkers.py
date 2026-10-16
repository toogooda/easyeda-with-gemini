from pathlib import Path
import pytest

from src.easyeda.parser import parse_schematic_json, parse_protel_netlist
from src.easyeda.models import CheckStatus, parse_resistance, parse_capacitance
from src.easyeda.checker_diodes import check_diode, check_led, check_all_diodes_and_leds
from src.easyeda.checker_transistors import check_bjt, check_mosfet, check_all_transistors

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_schematic.json"
REAL_TEL_PATH = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"


def test_parse_resistance():
    assert parse_resistance("10k") == 10000.0
    assert parse_resistance("10kΩ") == 10000.0
    assert parse_resistance("4k7") == 4700.0
    assert parse_resistance("4.7k") == 4700.0
    assert parse_resistance("100R") == 100.0
    assert parse_resistance("220Ω") == 220.0
    assert parse_resistance("1M") == 1000000.0
    assert parse_resistance("0R") == 0.0


def test_parse_capacitance():
    assert parse_capacitance("100nF") == pytest.approx(100e-9)
    assert parse_capacitance("1uF") == pytest.approx(1e-6)
    assert parse_capacitance("22pF") == pytest.approx(22e-12)
    assert parse_capacitance("10pF") == pytest.approx(10e-12)
    assert parse_capacitance("4.7uF") == pytest.approx(4.7e-6)


def test_d1_reverse_polarity_protection_passes():
    graph = parse_schematic_json(FIXTURE_PATH)
    d1 = graph.get_component("D1")
    assert d1 is not None

    res = check_diode(d1, graph)
    assert res.status == CheckStatus.PASS
    assert "Reverse polarity" in res.message


def test_d2_backwards_flyback_fails():
    graph = parse_schematic_json(FIXTURE_PATH)
    d2 = graph.get_component("D2")
    assert d2 is not None

    res = check_diode(d2, graph)
    assert res.status == CheckStatus.FAIL
    assert "Backwards" in res.message


def test_led1_proper_ballast_passes():
    graph = parse_schematic_json(FIXTURE_PATH)
    led1 = graph.get_component("LED1")
    assert led1 is not None

    res = check_led(led1, graph)
    assert res.status == CheckStatus.PASS
    assert "R1" in res.details.get("resistor", "")


def test_led2_missing_resistor_fails():
    graph = parse_schematic_json(FIXTURE_PATH)
    led2 = graph.get_component("LED2")
    assert led2 is not None

    res = check_led(led2, graph)
    assert res.status == CheckStatus.FAIL
    assert "Missing current-limiting resistor" in res.message


def test_q1_mosfet_gate_pulldown_passes():
    graph = parse_schematic_json(FIXTURE_PATH)
    q1 = graph.get_component("Q1")
    assert q1 is not None

    res = check_mosfet(q1, graph)
    assert res.status == CheckStatus.PASS
    assert "R2" in res.details.get("pulldown", "")


def test_q2_bjt_missing_base_resistor_warns():
    graph = parse_schematic_json(FIXTURE_PATH)
    q2 = graph.get_component("Q2")
    assert q2 is not None

    res = check_bjt(q2, graph)
    assert res.status == CheckStatus.WARN
    assert "Direct connection to Base without series resistor" in res.message


def test_check_all_aggregates():
    graph = parse_schematic_json(FIXTURE_PATH)
    diode_results = check_all_diodes_and_leds(graph)
    assert len(diode_results) == 4  # D1, D2, LED1, LED2

    transistor_results = check_all_transistors(graph)
    assert len(transistor_results) == 2  # Q1, Q2


def test_discrete_checkers_on_real_netlist():
    if not REAL_TEL_PATH.exists():
        pytest.skip("Real netlist not found")
    graph = parse_protel_netlist(REAL_TEL_PATH)

    diode_res = check_all_diodes_and_leds(graph)
    trans_res = check_all_transistors(graph)

    # Asserts that checkers run cleanly without exceptions on real project data
    assert isinstance(diode_res, list)
    assert isinstance(trans_res, list)
