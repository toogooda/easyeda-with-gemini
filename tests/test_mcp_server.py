from pathlib import Path
import json
import urllib.request
import pytest

from src.easyeda.server import (
    audit_schematic,
    get_part_profile,
    list_cached_parts,
    start_live_receiver
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_schematic.json"
REAL_TEL_PATH = Path(__file__).parent / "Netlist_Schematic_2026-10-17.tel"
REAL_BOM_PATH = Path(__file__).parent / "BOM_RemoteNode_Schematic_2026-10-17.xlsx"


def test_audit_schematic_fixture():
    report = audit_schematic(str(FIXTURE_PATH))
    assert isinstance(report, str)
    assert "# Schematic Review Report: TestBench_Board" in report

    # Check section headers
    assert "## 1. Diodes & LEDs" in report
    assert "## 2. Transistors & FETs" in report
    assert "## 3. ICs & Peripherals" in report
    assert "## 4. Microcontrollers & Bus Pin Mapping" in report
    assert "## Summary of Issues" in report

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
    assert "## 1. Diodes & LEDs" in report
    assert "## 2. Transistors & FETs" in report
    assert "## 4. Microcontrollers & Bus Pin Mapping" in report

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


