from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional

from .models import Component, SchematicGraph, CheckResult, CheckStatus
from .parts_manager import PartsManager
from .checker_diodes import check_all_diodes_and_leds, get_diode_pins, _find_led_series_resistor
from .checker_transistors import check_all_transistors, get_bjt_pins, get_mosfet_pins, _find_pull_resistor
from .checker_ics import check_ic_decoupling, check_i2c_peripheral
from .checker_mcu import check_microcontroller
from .checker_buses import check_bus_crossovers


def is_connector_or_mechanical(comp: Component) -> bool:
    """Returns True if component is a connector, header, testpoint, or mechanical fixture."""
    if comp.comp_type in ("MCU", "IC_I2C", "I2C_SENSOR", "REGULATOR", "TRANSCEIVER", "TVS_ARRAY"):
        return False
    ref_up = comp.ref_des.upper()
    if ref_up.startswith(("J", "H", "TP", "FID", "MH", "PAD")):
        return True
    pkg_up = (comp.package or "").upper()
    val_up = (comp.value or "").upper()
    type_up = (comp.comp_type or "").upper()
    keywords = [
        "CONN", "HEADER", "SOCKET", "TERMINAL", "PLUG", "JACK", "JST",
        "PH-SM", "SIP2P", "POGO", "REED", "TESTPOINT", "FIDUCIAL", "MOUNTING"
    ]
    if any(kw in pkg_up for kw in keywords) or any(kw in val_up for kw in keywords) or any(kw in type_up for kw in keywords):
        return True
    if any(pad in pkg_up for pad in ["_PAD", "POGO_PAD", "SOLDERPAD", "REEDSWITCH"]):
        return True
    return False


def get_component_functional_description(comp: Component, profile: Optional[Any] = None) -> str:
    """Resolves a human-readable functional title for an IC header."""
    if profile:
        if getattr(profile, "description", None):
            return profile.description
        if profile.part_type == "REGULATOR":
            vout = profile.voltage_limits.get("vout")
            return f"{vout}V LDO Voltage Regulator" if vout else "Linear Voltage Regulator"
        elif profile.part_type == "I2C_SENSOR":
            return "I2C Sensor / Peripheral"
        elif profile.part_type == "TRANSCEIVER":
            return "Wireless Transceiver Module"
        elif profile.part_type == "TVS_ARRAY":
            return "Multi-Channel TVS ESD Protection Array"
    val_up = (comp.value or "").upper()
    if "HT7333" in val_up:
        return "3.3V LDO Voltage Regulator"
    elif "HT7350" in val_up:
        return "5.0V LDO Voltage Regulator"
    elif "INA226" in val_up:
        return "Bidirectional Current/Power Monitor"
    elif any(r in val_up for r in ["RA-01", "SX1262", "SX1278", "LORA"]):
        return "SX1262 LoRa Wireless Transceiver Module"
    elif "SP720" in val_up:
        return "14-Channel TVS ESD Protection Array"
    elif any(ldo in val_up for ldo in ["AMS1117", "LM1117", "ME6211", "LP2985"]):
        return "Low-Dropout Voltage Regulator"
    return ""


def generate_schematic_report(graph: SchematicGraph, parts_manager: Optional[PartsManager] = None) -> str:
    """Runs all schematic audit checks and formats a comprehensive, rendered Markdown report."""
    if parts_manager is None:
        parts_manager = PartsManager()

    diode_led_results = check_all_diodes_and_leds(graph, parts_manager)
    transistor_results = check_all_transistors(graph, parts_manager)

    # Track components already audited in specialized sections to prevent duplicates
    audited_components = set()
    for r in diode_led_results:
        audited_components.add(r.ref_des)
    for r in transistor_results:
        audited_components.add(r.ref_des)

    # IC and MCU checks
    ic_results: Dict[str, List[CheckResult]] = {}
    mcu_results: Dict[str, List[CheckResult]] = {}
    bus_results: Dict[str, List[CheckResult]] = {}

    for comp in graph.components.values():
        if comp.ref_des in audited_components:
            continue

        if is_connector_or_mechanical(comp):
            continue

        c_type = comp.comp_type.upper()
        val = comp.value.upper()
        profile = parts_manager.find_profile(comp.lcsc_id or "", comp.value or "") if parts_manager else None

        is_mcu = (
            "MCU" in c_type
            or any(m in val for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"])
            or (profile is not None and (profile.part_type == "MCU" or any(m in profile.part_number.upper() for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"])))
            or (comp.datasheet and any(m in comp.datasheet.upper() for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"]))
        )

        if is_mcu:
            audited_components.add(comp.ref_des)
            mcu_results[comp.ref_des] = check_microcontroller(comp, graph, parts_manager)
            bus_results[comp.ref_des] = check_bus_crossovers(comp, graph, parts_manager)
        elif comp.ref_des.startswith("U") or "IC" in c_type:
            audited_components.add(comp.ref_des)
            checks: List[CheckResult] = []
            checks.extend(check_ic_decoupling(comp, graph, parts_manager))
            is_i2c = (
                "I2C" in c_type
                or any(s in val for s in ["TMP", "BMP", "BME", "AHT", "SHT", "MPU", "INA226", "24AA", "24LC"])
                or (profile is not None and (profile.part_type in ("I2C_SENSOR", "IC_I2C") or bool(profile.i2c_addresses) or bool(profile.address_base)))
                or (comp.datasheet and any(s in comp.datasheet.upper() for s in ["TMP", "BMP", "BME", "AHT", "SHT", "MPU", "INA226", "24AA", "24LC"]))
            )
            if is_i2c:
                checks.extend(check_i2c_peripheral(comp, graph, parts_manager))
            # Zero-suppression: always record all ICs even if no automated checks triggered
            ic_results[comp.ref_des] = checks

    # Check for I2C Address Collisions across devices on the same bus
    i2c_devices_by_bus: Dict[str, Dict[str, List[str]]] = {}
    for ref_des, checks in ic_results.items():
        comp = graph.get_component(ref_des)
        sda_pin = comp.find_pin_matching(r"^SDA") or (comp.get_pin_by_name("SDA") if comp else None)
        bus_name = sda_pin.net if sda_pin else "I2C"
        for c in checks:
            if "i2c_address" in c.details:
                addr = c.details["i2c_address"]
                i2c_devices_by_bus.setdefault(bus_name, {}).setdefault(addr, []).append(ref_des)

    for bus_name, addrs in i2c_devices_by_bus.items():
        for addr, ref_list in addrs.items():
            if len(ref_list) > 1:
                collision_result = CheckResult(
                    ref_des=ref_list[0],
                    component_type="IC_I2C",
                    status=CheckStatus.FAIL,
                    message=f"I2C Address Collision: Devices {', '.join(ref_list)} on bus '{bus_name}' share identical 7-bit address {addr}!",
                    details={"i2c_address": addr, "conflicting_devices": ", ".join(ref_list), "bus": bus_name}
                )
                ic_results[ref_list[0]].append(collision_result)

    # Count issues
    all_results: List[CheckResult] = []
    all_results.extend(diode_led_results)
    all_results.extend(transistor_results)
    for res_list in ic_results.values():
        all_results.extend(res_list)
    for res_list in mcu_results.values():
        all_results.extend(res_list)
    for res_list in bus_results.values():
        all_results.extend(res_list)

    critical_items = [r for r in all_results if r.status == CheckStatus.FAIL]
    warning_items = [r for r in all_results if r.status == CheckStatus.WARN]
    pass_items = [r for r in all_results if r.status == CheckStatus.PASS]

    # Build Markdown Document
    md: List[str] = []
    title = graph.project_name or "Untitled Board"
    md.append(f"# Schematic Review Report: {title}")
    
    meta_info = []
    if getattr(graph, "source_path", None):
        meta_info.append(f"**Source:** `{graph.source_path}`")
    elif graph.project_name:
        meta_info.append(f"**Project:** `{graph.project_name}`")
    if getattr(graph, "bom_path", None):
        meta_info.append(f"**BOM:** `{graph.bom_path}`")
    meta_info.append(f"**Components:** {len(graph.components)}")
    meta_info.append(f"**Nets:** {len(graph.nets)}")
    if meta_info:
        md.append(" | ".join(meta_info))
    md.append("")

    # Executive Summary of Issues (Upfront)
    md.append("## Summary of Issues")
    md.append(f"* 🔴 **CRITICAL ({len(critical_items)}):**")
    if not critical_items:
        md.append("  * None detected!")
    else:
        for it in critical_items:
            md.append(f"  * **{it.ref_des}:** {it.message}")

    md.append(f"* 🟡 **WARNING ({len(warning_items)}):**")
    if not warning_items:
        md.append("  * None detected.")
    else:
        for it in warning_items:
            md.append(f"  * **{it.ref_des}:** {it.message}")

    i2c_entries = []
    seen_i2c_refs = set()
    for r in all_results:
        if "i2c_address" in r.details and r.ref_des not in seen_i2c_refs:
            seen_i2c_refs.add(r.ref_des)
            comp = graph.get_component(r.ref_des)
            val = comp.value if (comp and comp.value and comp.value != "{Value}") else ""
            if val:
                i2c_entries.append(f"{r.ref_des} ({val}) @ {r.details['i2c_address']}")
            else:
                i2c_entries.append(f"{r.ref_des} @ {r.details['i2c_address']}")

    md.append(f"* 🟢 **INFO & PASS ({len(pass_items)} checks passed):**")
    if i2c_entries:
        md.append(f"  * Detected I2C Devices: {', '.join(i2c_entries)}")

    md.append("")
    md.append("> [!IMPORTANT]")
    md.append("> **Senior Engineering Review Required:** The tables below present raw pinout and netlist telemetry extracted from the schematic. Reviewing AI agents must cross-reference physical pin assignments against the Zero-Trust Engineering Review Checklist in `SKILL.md` (verifying BJT/FET power and load orientations, diode polarities, ballast resistors, and MCU pin alternate functions) to author the final engineering critique.")
    md.append("")
    md.append("---")
    md.append("")

    # 1. Diodes & LEDs (Polarity & Ballast Telemetry)
    md.append("## 1. Diodes & LEDs (Polarity & Ballast Telemetry)")
    md.append("| Designator | Part Number | Package | Type | Anode (Pin & Net) | Cathode (Pin & Net) | Series Resistor | Status | Notes |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in diode_led_results:
        comp = graph.get_component(r.ref_des)
        part_num = comp.value if comp else ""
        pkg = comp.package if (comp and comp.package) else "-"
        c_type = r.component_type or (comp.comp_type if comp else "DIODE")
        if c_type == "TVS_ARRAY":
            a_net = f"GND (`{r.details.get('gnd_net', 'GND')}`)"
            c_net = f"V+ (`{r.details.get('v_plus_net', '-')}`)"
            res_info = "N/A"
        else:
            anode, cathode = get_diode_pins(comp, parts_manager) if comp else (None, None)
            a_net = f"Pin {anode.number} (`{anode.net}`)" if anode else "-"
            c_net = f"Pin {cathode.number} (`{cathode.net}`)" if cathode else "-"
            res_info = r.details.get("resistor", "None")
            if res_info != "None" and "value" in r.details:
                res_info += f" ({r.details['value']})"
        md.append(f"| {r.ref_des} | {part_num} | {pkg} | {c_type} | {a_net} | {c_net} | {res_info} | {r.badge} | {r.message} |")
    md.append("")

    # 2. Transistors & FETs (Switching & Pinout Telemetry)
    md.append("## 2. Transistors & FETs (Switching & Pinout Telemetry)")
    md.append("| Designator | Part Number | Package | Type | Base / Gate | Collector / Drain | Emitter / Source | Series R | Bias / Pull R | Status | Notes |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in transistor_results:
        comp = graph.get_component(r.ref_des)
        part_num = comp.value if comp else ""
        pkg = comp.package if (comp and comp.package) else "-"
        c_type = r.component_type
        if "MOSFET" in c_type:
            gate, source, drain = get_mosfet_pins(comp, parts_manager) if comp else (None, None, None)
            g_str = f"Pin {gate.number} (`{gate.net}`)" if gate else "-"
            d_str = f"Pin {drain.number} (`{drain.net}`)" if drain else "-"
            s_str = f"Pin {source.number} (`{source.net}`)" if source else "-"
            series_r = r.details.get("resistor", "None")
            pull_r = r.details.get("pulldown") or r.details.get("pullup", "None")
            if pull_r != "None" and "value" in r.details:
                pull_r += f" ({r.details['value']})"
        else:
            base, emitter, collector = get_bjt_pins(comp, parts_manager) if comp else (None, None, None)
            g_str = f"Pin {base.number} (`{base.net}`)" if base else "-"
            d_str = f"Pin {collector.number} (`{collector.net}`)" if collector else "-"
            s_str = f"Pin {emitter.number} (`{emitter.net}`)" if emitter else "-"
            series_r = r.details.get("resistor", "None")
            if series_r != "None" and "value" in r.details:
                series_r += f" ({r.details['value']})"
            pull_r = "None"
            if base:
                net_b = graph.get_net(base.net)
                if net_b:
                    for pin in net_b.pins:
                        if pin.component_ref != r.ref_des:
                            c = graph.get_component(pin.component_ref)
                            if c and (c.ref_des.startswith("R") or c.comp_type == "RESISTOR"):
                                if series_r == "None" or c.ref_des not in series_r:
                                    pull_r = f"{c.ref_des} ({c.value})"
                                    break
        md.append(f"| {r.ref_des} | {part_num} | {pkg} | {c_type} | {g_str} | {d_str} | {s_str} | {series_r} | {pull_r} | {r.badge} | {r.message} |")
    md.append("")

    # 3. ICs & Peripherals
    md.append("## 3. ICs & Peripherals")
    if not ic_results:
        md.append("*No discrete ICs or I2C sensors identified.*")
    else:
        for ref_des, checks in ic_results.items():
            comp = graph.get_component(ref_des)
            val = comp.value if comp else ""
            prof = parts_manager.find_profile(comp.lcsc_id or "", comp.value or "") if (parts_manager and comp) else None
            if not val and prof:
                val = prof.part_number
            desc = get_component_functional_description(comp, prof)
            desc_str = f" - {desc}" if desc else ""
            i2c_addr = next((c.details.get("i2c_address") for c in checks if "i2c_address" in c.details), None)
            addr_header = f" [7-bit I2C: {i2c_addr}]" if i2c_addr else ""
            md.append(f"### {ref_des}: {val}{desc_str}{addr_header}")
            
            meta_items = []
            if comp and comp.package:
                meta_items.append(f"**Package:** `{comp.package}`")
            if comp and comp.lcsc_id:
                meta_items.append(f"**LCSC ID:** `{comp.lcsc_id}`")
            if comp and comp.datasheet:
                meta_items.append(f"**Datasheet:** [{comp.datasheet}]({comp.datasheet})")
            if meta_items:
                md.append(f"* {' | '.join(meta_items)}")

            # Render automated check results
            for c in checks:
                md.append(f"* {c.badge} {c.message}")

            # Generate structured Pin Connection & Net Analysis Table
            if comp and comp.pins:
                md.append("")
                md.append("| Pin | Name | Connected Net | Electrical Role | Capacitance to GND |")
                md.append("| :--- | :--- | :--- | :--- | :--- |")
                sorted_pins = sorted(comp.pins.values(), key=lambda p: (int(p.number) if p.number.isdigit() else 999, p.number))
                for pin in sorted_pins:
                    p_name = pin.name if (pin.name and pin.name != pin.number) else ""
                    if not p_name and prof and prof.pin_map and str(pin.number) in prof.pin_map:
                        p_name = str(prof.pin_map[str(pin.number)])
                    if not p_name:
                        p_name = "-"

                    net_name = pin.net or "NC"
                    net_obj = graph.get_net(net_name) if pin.net else None
                    p_name_up = p_name.upper()
                    net_up = net_name.upper()

                    if (net_obj and net_obj.is_ground) or p_name_up in ("GND", "VSS", "V-", "GROUND") or "GND" in net_up:
                        role = "Ground"
                    elif (net_obj and net_obj.is_power) or p_name_up in ("VCC", "VDD", "VIN", "VOUT", "V+", "VBAT", "VS") or any(p in net_up for p in ["3V3", "5V", "VCC", "VDD", "VS", "PWR", "LORAON", "PWRON", "PERVOLTAGE", "VIN"]):
                        role = "Power"
                    else:
                        role = "Signal"

                    caps = graph.find_capacitors_between(net_name, "GND") if pin.net else []
                    cap_str = ", ".join([f"{c.ref_des} ({c.value})" for c in caps[:3]]) if caps else "-"
                    if len(caps) > 3:
                        cap_str += f", +{len(caps)-3} more"
                    md.append(f"| {pin.number} | {p_name} | {net_name} | {role} | {cap_str} |")
            md.append("")


    # 4. Microcontroller & Bus Pin Mapping
    md.append("## 4. Microcontrollers & Bus Pin Mapping")
    if not mcu_results:
        md.append("*No microcontrollers identified.*")
    else:
        for ref_des, checks in mcu_results.items():
            comp = graph.get_component(ref_des)
            val = comp.value if comp else ""
            prof = parts_manager.find_profile(comp.lcsc_id or "", comp.value or "") if (parts_manager and comp) else None
            if not val and prof:
                val = prof.part_number
            desc = get_component_functional_description(comp, prof)
            desc_str = f" - {desc}" if desc else ""
            md.append(f"### {ref_des}: {val}{desc_str}")
            
            meta_items = []
            if comp and comp.package:
                meta_items.append(f"**Package:** `{comp.package}`")
            if comp and comp.lcsc_id:
                meta_items.append(f"**LCSC ID:** `{comp.lcsc_id}`")
            if comp and comp.datasheet:
                meta_items.append(f"**Datasheet:** [{comp.datasheet}]({comp.datasheet})")
            if meta_items:
                md.append(f"* {' | '.join(meta_items)}")

            # Group power & crystal checks
            for c in checks:
                md.append(f"* {c.badge} {c.message}")
            md.append("")

            # Bus crossovers table
            buses = bus_results.get(ref_des, [])
            if buses:
                md.append("#### Bus Peripheral Pin Mapping")
                md.append("| Bus | MCU Pin | Connected Net | Target Connection(s) | Pull-up / Protection | Status | Notes |")
                md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for b in buses:
                    b_type = b.details.get("bus_type", "BUS")
                    mcu_p = b.details.get("mcu_pin", "-")
                    net = b.details.get("net", "-")
                    target = b.details.get("target", "-")
                    prot = b.details.get("pullup_protection", "-")
                    notes = b.message
                    md.append(f"| {b_type} | {mcu_p} | {net} | {target} | {prot} | {b.badge} | {notes} |")
                md.append("")

    return "\n".join(md)
