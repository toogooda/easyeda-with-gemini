from pathlib import Path
import json
import urllib.request
import pytest

from src.easyeda.server import (
    audit_schematic,
    get_part_profile,
    save_part_profile,
    get_datasheet,
    list_cached_parts,
    start_live_receiver,
    archive_stale_payload,
    _CACHE_PAYLOAD_FILE,
    _STALE_PAYLOAD_FILE,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_schematic.json"
REAL_TEL_PATH = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"
REAL_BOM_PATH = Path(__file__).parent / "BOM_RemoteNode_Schematic_2026-10-17.xlsx"


def test_audit_schematic_fixture():
    report = audit_schematic(str(FIXTURE_PATH))
    assert isinstance(report, str)
    assert "# Schematic Review Report: TestBench_Board" in report

    # Check provenance metadata
    assert "**Source:**" in report
    assert "**Components:**" in report
    assert "**Nets:**" in report

    # Check that Summary of Issues is upfront (before Section 1)
    summary_pos = report.index("## Summary of Issues")
    sec1_pos = report.index("## 1. Diodes & LEDs")
    assert summary_pos < sec1_pos, "Summary of Issues must appear before Section 1"

    # Check section headers
    assert "## 1. Diodes & LEDs" in report
    assert "## 2. Transistors & FETs" in report
    assert "## 3. ICs & Peripherals" in report
    assert "## 4. Microcontrollers & Bus Pin Mapping" in report
    assert "#### Bus Peripheral Pin Mapping" in report

    # Check critical findings caught
    assert "🔴 **CRITICAL" in report
    assert "D2" in report  # backwards flyback
    assert "LED2" in report  # missing resistor
    assert "CAN1" in report or "PA11" in report  # swapped CAN transceiver

    # Check warnings
    assert "🟡 **WARNING" in report
    assert "Q2" in report  # base resistor warning

    # Check I2C detection
    assert "0x48" in report
    assert "U2" in report


def test_audit_schematic_real_project():
    if not REAL_TEL_PATH.exists() or not REAL_BOM_PATH.exists():
        pytest.skip("Real project files not found")

    report = audit_schematic(str(REAL_TEL_PATH), str(REAL_BOM_PATH))
    assert isinstance(report, str)
    assert "**Source:**" in report
    assert "**BOM:**" in report
    assert "## Summary of Issues" in report
    assert report.index("## Summary of Issues") < report.index("## 1. Diodes & LEDs")
    assert "## 1. Diodes & LEDs" in report
    assert "## 2. Transistors & FETs" in report
    assert "## 4. Microcontrollers & Bus Pin Mapping" in report

    # Verify bus peripheral pin mapping on real project
    assert "#### Bus Peripheral Pin Mapping" in report
    assert "| SPI |" in report
    assert "| I2C |" in report
    assert "| UART |" in report
    assert "LORASCK" in report
    assert "U2 (Ra-01SCH-P)" in report

    # Verify real crystals detected
    assert "8MHz" in report
    assert "32.768kHz" in report
    assert "R2" in report or "R4" in report


def test_get_part_profile_and_list():
    parts = list_cached_parts()
    assert "C8734" in parts
    assert "C62973" in parts

    p = get_part_profile("C8734")
    assert p["part_number"] == "STM32F103C8T6"


def test_live_extension_http_receiver():
    # Start live server on port 8766 for testing
    server = start_live_receiver(port=8766)

    # Load fixture data and POST to /review
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        payload_bytes = f.read().encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8766/review",
        data=payload_bytes,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        res_data = json.loads(resp.read().decode("utf-8"))
        assert res_data["status"] == "success"
        assert res_data["components_count"] >= 15

    # Check that audit_schematic("live") now returns the report
    live_report = audit_schematic("live")
    assert "# Schematic Review Report: TestBench_Board" in live_report

    server.shutdown()


def test_live_extension_netlist_text_payload():
    if not REAL_TEL_PATH.exists():
        pytest.skip("Real tel file not found")

    server = start_live_receiver(port=8767)

    with open(REAL_TEL_PATH, "r", encoding="utf-8") as f:
        tel_text = f.read()

    payload_bytes = json.dumps({
        "project_name": "Live_RemoteNode",
        "netlist_text": tel_text
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8767/review",
        data=payload_bytes,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        res_data = json.loads(resp.read().decode("utf-8"))
        assert res_data["status"] == "success"
        assert res_data["components_count"] > 0

    live_report = audit_schematic("live")
    assert "# Schematic Review Report: Live_RemoteNode" in live_report

    server.shutdown()


def test_live_extension_chunked_encoding():
    import http.client
    if not REAL_TEL_PATH.exists():
        pytest.skip("Real tel file not found")

    server = start_live_receiver(port=8768)

    with open(REAL_TEL_PATH, "r", encoding="utf-8") as f:
        tel_text = f.read()

    raw_bytes = json.dumps({
        "project_name": "Chunked_RemoteNode",
        "netlist_text": tel_text
    }).encode("utf-8")

    # Encode as HTTP/1.1 chunked stream
    chunked_body = f"{len(raw_bytes):x}\r\n".encode("ascii") + raw_bytes + b"\r\n0\r\n\r\n"

    conn = http.client.HTTPConnection("127.0.0.1", 8768, timeout=5)
    conn.putrequest("POST", "/review?client=localhost")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    conn.send(chunked_body)

    resp = conn.getresponse()
    assert resp.status == 200
    res_data = json.loads(resp.read().decode("utf-8"))
    assert res_data["status"] == "success"
    assert res_data["components_count"] > 0
    conn.close()

    live_report = audit_schematic("live")
    assert "# Schematic Review Report: Chunked_RemoteNode" in live_report

    server.shutdown()


def test_antigravity_initiated_on_demand_pull():
    import threading
    import time
    from src.easyeda.server import request_live_pull

    if not REAL_TEL_PATH.exists():
        pytest.skip("Real tel file not found")

    server = start_live_receiver(port=8769)
    with open(REAL_TEL_PATH, "r", encoding="utf-8") as f:
        tel_text = f.read()

    stop_client = threading.Event()

    def simulated_easyeda_extension():
        while not stop_client.is_set():
            try:
                with urllib.request.urlopen("http://127.0.0.1:8769/poll?client=localhost", timeout=2) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    if data.get("command") == "pull_schematic":
                        payload = json.dumps({
                            "project_name": "OnDemand_Pulled_Board",
                            "netlist_text": tel_text
                        }).encode("utf-8")
                        req = urllib.request.Request(
                            "http://127.0.0.1:8769/review?client=localhost",
                            data=payload,
                            headers={"Content-Type": "application/json"}
                        )
                        urllib.request.urlopen(req, timeout=2).read()
            except Exception:
                pass
            time.sleep(0.1)

    t = threading.Thread(target=simulated_easyeda_extension, daemon=True)
    t.start()
    time.sleep(0.25)  # allow first poll heartbeat

    report = request_live_pull(timeout=3.0, port=8769)
    stop_client.set()
    server.shutdown()

    assert report is not None
    assert "# Schematic Review Report: OnDemand_Pulled_Board" in report


def test_save_part_profile_and_reload():
    test_data = {
        "lcsc_part": "C999999",
        "part_number": "TEST_LDO_3V3",
        "part_type": "REGULATOR",
        "voltage_limits": {"vout": 3.3},
        "power_pins": [{"pin": "2", "name": "VOUT", "decoupling": "10uF"}],
        "ground_pins": ["1"]
    }
    res = save_part_profile(test_data)
    assert res["status"] == "success"
    assert res["lcsc_id"] == "C999999"

    loaded = get_part_profile("C999999")
    assert loaded["part_number"] == "TEST_LDO_3V3"
    assert loaded["part_type"] == "REGULATOR"

    # Clean up test file from parts_cache
    p_file = Path("parts_cache/C999999.json")
    if p_file.exists():
        p_file.unlink()


def test_zero_suppression_includes_d1_u4_u6_and_pin_tables():
    if not REAL_TEL_PATH.exists() or not REAL_BOM_PATH.exists():
        pytest.skip("Real project files not found")

    report = audit_schematic(str(REAL_TEL_PATH), str(REAL_BOM_PATH))
    # D1 TVS Array included in Section 1
    assert "D1" in report
    assert "SP720ABTG" in report
    assert "TVS_ARRAY" in report

    # U4 and U6 included in Section 3 with pin tables and decoupling
    assert "### U4: HT7350-1" in report
    assert "### U6: HT7333" in report
    assert "Power pin VIN" in report
    assert "Power pin VOUT" in report
    assert "Connected Net" in report
    assert "Capacitance to GND" in report


def test_transistor_telemetry_table_exposes_physical_pins():
    if not REAL_TEL_PATH.exists() or not REAL_BOM_PATH.exists():
        pytest.skip("Real project files not found")

    report = audit_schematic(str(REAL_TEL_PATH), str(REAL_BOM_PATH))
    # Section 2 Transistor table header asserts
    assert "Base / Gate" in report
    assert "Collector / Drain" in report
    assert "Emitter / Source" in report

    # Verify Q1 (B772) physical pinout telemetry is explicitly visible
    assert "Q1" in report
    assert "2SB772" in report or "B772" in report
    assert "BJT_PNP" in report
    assert "Pin 1" in report  # Base
    assert "Pin 2" in report  # Collector
    assert "Pin 3" in report  # Emitter


def test_archive_stale_payload_lifecycle():
    # Write a dummy payload
    _CACHE_PAYLOAD_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PAYLOAD_FILE.write_text('{"test": "stale_data"}', encoding="utf-8")
    assert _CACHE_PAYLOAD_FILE.exists()

    # Call archive_stale_payload
    archive_stale_payload()

    # Verify original is moved to stale
    assert not _CACHE_PAYLOAD_FILE.exists()
    assert _STALE_PAYLOAD_FILE.exists()

    # Clean up test stale file
    if _STALE_PAYLOAD_FILE.exists():
        _STALE_PAYLOAD_FILE.unlink()
