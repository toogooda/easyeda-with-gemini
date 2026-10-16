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
