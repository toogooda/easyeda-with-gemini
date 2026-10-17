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


def generate_schematic_report(graph: SchematicGraph, parts_manager: Optional[PartsManager] = None) -> str:
    """Runs all schematic audit checks and formats a comprehensive, rendered Markdown report."""
    if parts_manager is None:
        parts_manager = PartsManager()

    diode_led_results = check_all_diodes_and_leds(graph)
    transistor_results = check_all_transistors(graph)

    # IC and MCU checks
    ic_results: Dict[str, List[CheckResult]] = {}
    mcu_results: Dict[str, List[CheckResult]] = {}
    bus_results: Dict[str, List[CheckResult]] = {}

    for comp in graph.components.values():
        c_type = comp.comp_type.upper()
        val = comp.value.upper()
        profile = parts_manager.get_profile(comp.lcsc_id) if (parts_manager and comp.lcsc_id) else None

        is_mcu = (
            "MCU" in c_type
            or any(m in val for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"])
            or (profile is not None and (profile.part_type == "MCU" or any(m in profile.part_number.upper() for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"])))
            or (comp.datasheet and any(m in comp.datasheet.upper() for m in ["STM32", "ESP32", "RP2040", "ATMEGA", "PIC"]))
        )

        if is_mcu:
            mcu_results[comp.ref_des] = check_microcontroller(comp, graph, parts_manager)
            bus_results[comp.ref_des] = check_bus_crossovers(comp, graph, parts_manager)
        elif comp.ref_des.startswith("U") or "IC" in c_type:
            checks: List[CheckResult] = []
            checks.extend(check_ic_decoupling(comp, graph, parts_manager))
            is_i2c = (
                "I2C" in c_type
                or any(s in val for s in ["TMP", "BMP", "BME", "AHT", "SHT", "MPU"])
                or (profile is not None and (profile.part_type == "I2C_SENSOR" or profile.i2c_bus is not None))
                or (comp.datasheet and any(s in comp.datasheet.upper() for s in ["TMP", "BMP", "BME", "AHT", "SHT", "MPU"]))
            )
            if is_i2c:
                checks.extend(check_i2c_peripheral(comp, graph, parts_manager))
            if checks:
                ic_results[comp.ref_des] = checks

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
    md.append(f"# Schematic Review Report: {graph.project_name or 'Untitled Board'}")
    md.append("")

    # 1. Diodes & LEDs
    md.append("## 1. Diodes & LEDs")
    md.append("| Designator | Part Number | Type | Anode Net | Cathode Net | Resistor | Status | Notes |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in diode_led_results:
        comp = graph.get_component(r.ref_des)
        part_num = comp.value if comp else ""
        c_type = comp.comp_type if comp else "DIODE"
        anode, cathode = get_diode_pins(comp) if comp else (None, None)
        a_net = anode.net if anode else "-"
        c_net = cathode.net if cathode else "-"
        res_info = r.details.get("resistor", "N/A")
        if res_info != "N/A" and "value" in r.details:
            res_info += f" ({r.details['value']})"
        md.append(f"| {r.ref_des} | {part_num} | {c_type} | {a_net} | {c_net} | {res_info} | {r.badge} | {r.message} |")
    md.append("")

    # 2. Transistors & FETs
    md.append("## 2. Transistors & FETs (Switching & Saturation)")
    md.append("| Designator | Part Number | Type | Control Pin | Base/Gate R | Pull-up/down | Status | Notes |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in transistor_results:
        comp = graph.get_component(r.ref_des)
        part_num = comp.value if comp else ""
        c_type = r.component_type
        ctrl_pin = r.details.get("base") or r.details.get("gate", "-")
        series_r = r.details.get("resistor", "None")
        if series_r != "None" and "value" in r.details:
            series_r += f" ({r.details['value']})"
        pull_r = r.details.get("pulldown") or r.details.get("pullup", "None")
        if pull_r != "None" and "value" in r.details:
            pull_r += f" ({r.details['value']})"
        md.append(f"| {r.ref_des} | {part_num} | {c_type} | {ctrl_pin} | {series_r} | {pull_r} | {r.badge} | {r.message} |")
    md.append("")

    # 3. ICs & Peripherals
    md.append("## 3. ICs & Peripherals")
    if not ic_results:
        md.append("*No discrete ICs or I2C sensors identified.*")
    else:
        for ref_des, checks in ic_results.items():
            comp = graph.get_component(ref_des)
            val = comp.value if comp else ""
            if not val and comp and comp.lcsc_id and parts_manager:
                prof = parts_manager.get_profile(comp.lcsc_id)
                if prof:
                    val = prof.part_number
            md.append(f"### {ref_des}: {val}")
            if comp and comp.datasheet:
                md.append(f"* **Datasheet:** [{comp.datasheet}]({comp.datasheet})")
            for c in checks:
                md.append(f"* {c.badge} {c.message}")
            md.append("")

    # 4. Microcontroller & Bus Pin Mapping
    md.append("## 4. Microcontrollers & Bus Pin Mapping")
    if not mcu_results:
        md.append("*No microcontrollers identified.*")
    else:
        for ref_des, checks in mcu_results.items():
            comp = graph.get_component(ref_des)
            val = comp.value if comp else ""
            if not val and comp and comp.lcsc_id and parts_manager:
                prof = parts_manager.get_profile(comp.lcsc_id)
                if prof:
                    val = prof.part_number
            md.append(f"### {ref_des}: {val}")
            if comp and comp.datasheet:
                md.append(f"* **Datasheet:** [{comp.datasheet}]({comp.datasheet})")

            # Group power & crystal checks
            for c in checks:
                md.append(f"* {c.badge} {c.message}")
            md.append("")

            # Bus crossovers table
            buses = bus_results.get(ref_des, [])
            if buses:
                md.append("#### Bus Pin Mapping & Crossovers")
                md.append("| MCU Pin | Connected Net | Target Connection | Status | Notes |")
                md.append("| :--- | :--- | :--- | :--- | :--- |")
                for b in buses:
                    mcu_p = b.details.get("mcu_pin", "-")
                    net = b.details.get("net", "-")
                    target = b.details.get("target", "-")
                    md.append(f"| {mcu_p} | {net} | {target} | {b.badge} | {b.message} |")
                md.append("")

    # 5. Summary of Issues
    md.append("---")
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

    i2c_addresses = [f"{r.ref_des} @ {r.details['i2c_address']}" for r in all_results if "i2c_address" in r.details]
    md.append(f"* 🟢 **INFO & PASS ({len(pass_items)} checks passed):**")
    if i2c_addresses:
        md.append(f"  * Detected I2C Devices: {', '.join(i2c_addresses)}")

    return "\n".join(md)
