from __future__ import annotations
import json
import csv
import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from .models import Component, Pin, SchematicGraph


def infer_component_type(ref_des: str, value: str = "") -> str:
    """Infers component category from ref_des and value string."""
    ref_upper = ref_des.upper()
    val_upper = value.upper()

    if ref_upper.startswith("LED") or "LED" in val_upper:
        return "LED"
    if ref_upper.startswith("D"):
        return "DIODE"
    if ref_upper.startswith("R"):
        return "RESISTOR"
    if ref_upper.startswith("C"):
        return "CAPACITOR"
    if ref_upper.startswith("Q"):
        if "MOS" in val_upper or "2N7002" in val_upper or "SI230" in val_upper or "AO340" in val_upper:
            return "MOSFET_N" if "P" not in val_upper else "MOSFET_P"
        return "BJT_NPN"
    if ref_upper.startswith("U"):
        if any(mcu in val_upper for mcu in ["STM32", "ESP32", "RP2040", "ATMEGA", "ATTINY", "PIC"]):
            return "MCU"
        if any(sensor in val_upper for sensor in ["TMP102", "BMP280", "BME280", "AHT20", "SHT30", "MPU6050"]):
            return "IC_I2C"
        return "IC"
    if ref_upper.startswith("Y") or ref_upper.startswith("X"):
        return "CRYSTAL"
    if ref_upper.startswith("L"):
        return "INDUCTOR"
    if ref_upper.startswith("FB"):
        return "FERRITE_BEAD"
    if ref_upper.startswith("J") or ref_upper.startswith("CN") or ref_upper.startswith("P"):
        return "CONNECTOR"
    return "UNKNOWN"


def parse_schematic_json(source: Union[str, Path, dict]) -> SchematicGraph:
    """Parses a schematic JSON document into a SchematicGraph object."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json.loads(str(source))
    else:
        data = source

    graph = SchematicGraph(
        project_name=data.get("project_name", "Untitled"),
        version=data.get("version", "1.0")
    )

    for comp_data in data.get("components", []):
        ref_des = comp_data.get("ref_des", "")
        value = comp_data.get("value", "")
        comp_type = comp_data.get("type") or infer_component_type(ref_des, value)

        comp = Component(
            ref_des=ref_des,
            value=value,
            package=comp_data.get("package", ""),
            lcsc_id=comp_data.get("lcsc_id"),
            datasheet=comp_data.get("datasheet"),
            comp_type=comp_type
        )

        for pin_data in comp_data.get("pins", []):
            pin = Pin(
                number=str(pin_data.get("number", "")),
                name=pin_data.get("name", ""),
                net=pin_data.get("net", ""),
                component_ref=ref_des
            )
            comp.add_pin(pin)

        graph.add_component(comp)

    return graph


def _join_protel_lines(text: str) -> List[str]:
    """Joins continuation lines in Protel format where lines end or start with commas."""
    records = []
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith(","):
            line = line[1:].strip()
        if current:
            current += " " + line
        else:
            current = line

        if current.endswith(","):
            current = current[:-1].rstrip()
        else:
            records.append(current)
            current = ""
    if current:
        records.append(current)
    return records


def parse_protel_netlist(source: Union[str, Path]) -> SchematicGraph:
    """Parses a Protel/EasyEDA (.tel / .net) wirelist into a SchematicGraph object."""
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    else:
        content = str(source)

    graph = SchematicGraph(project_name="Exported_Netlist", version="1.0")

    # Split into sections
    sections: Dict[str, str] = {}
    current_sec = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("$"):
            current_sec = stripped.upper()
            sections[current_sec] = ""
        elif current_sec:
            sections[current_sec] += line + "\n"

    # 1. Parse $PACKAGES
    # Each record: Footprint ! Package ! Value ; RefDes1 RefDes2 ...
    pkg_text = sections.get("$PACKAGES", "")
    for record in _join_protel_lines(pkg_text):
        if ";" not in record:
            continue
        meta_part, refs_part = record.split(";", 1)

        meta_tokens = [t.strip().strip("'\"") for t in meta_part.split("!") if t.strip()]
        footprint = meta_tokens[0] if len(meta_tokens) > 0 else ""
        raw_val = meta_tokens[2] if len(meta_tokens) > 2 else (meta_tokens[1] if len(meta_tokens) > 1 else "")
        val = "" if raw_val in ("{Value}", "") else raw_val

        clean_refs = re.findall(r"\b[A-Za-z0-9_]+\b", refs_part)
        for ref in clean_refs:
            comp = Component(
                ref_des=ref,
                value=val,
                package=footprint,
                comp_type=infer_component_type(ref, val)
            )
            graph.add_component(comp)

    # 2. Parse $NETS
    # Each record: NetName ; RefDes.PinNumber RefDes.PinNumber ...
    nets_text = sections.get("$NETS", "")
    for record in _join_protel_lines(nets_text):
        if ";" not in record:
            continue
        net_part, pins_part = record.split(";", 1)
        net_name = net_part.strip().strip("'\"").strip(",")
        if not net_name or net_name.startswith("$"):
            continue

        pin_tokens = re.findall(r"([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)", pins_part)
        for ref, pin_num in pin_tokens:
            comp = graph.get_component(ref)
            if not comp:
                comp = Component(
                    ref_des=ref,
                    value="",
                    comp_type=infer_component_type(ref, "")
                )
                graph.add_component(comp)

            pin = comp.get_pin(pin_num)
            if not pin:
                pin = Pin(
                    number=pin_num,
                    name=pin_num,
                    net=net_name,
                    component_ref=ref
                )
                comp.add_pin(pin)
            else:
                pin.net = net_name

            graph._register_pin_in_net(pin)

    return graph


