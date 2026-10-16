from __future__ import annotations
from typing import List, Optional, Tuple
import re

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus, parse_resistance


def get_bjt_pins(comp: Component) -> Tuple[Optional[Pin], Optional[Pin], Optional[Pin]]:
    """Returns (base_pin, emitter_pin, collector_pin) for a BJT."""
    base: Optional[Pin] = None
    emitter: Optional[Pin] = None
    collector: Optional[Pin] = None

    for pin in comp.pins.values():
        name_up = pin.name.upper()
        if name_up in ("B", "BASE"):
            base = pin
        elif name_up in ("E", "EMITTER"):
            emitter = pin
        elif name_up in ("C", "COLLECTOR"):
            collector = pin

    # Fallback standard SOT-23 mapping (1=B, 2=E, 3=C)
    if not base:
        base = comp.get_pin("1")
    if not emitter:
        emitter = comp.get_pin("2")
    if not collector:
        collector = comp.get_pin("3")

    return base, emitter, collector


def get_mosfet_pins(comp: Component) -> Tuple[Optional[Pin], Optional[Pin], Optional[Pin]]:
    """Returns (gate_pin, source_pin, drain_pin) for a MOSFET."""
    gate: Optional[Pin] = None
    source: Optional[Pin] = None
    drain: Optional[Pin] = None

    for pin in comp.pins.values():
        name_up = pin.name.upper()
        if name_up in ("G", "GATE"):
            gate = pin
        elif name_up in ("S", "SOURCE"):
            source = pin
        elif name_up in ("D", "DRAIN"):
            drain = pin

    # Fallback standard SOT-23 mapping (1=G, 2=S, 3=D)
    if not gate:
        gate = comp.get_pin("1")
    if not source:
        source = comp.get_pin("2")
    if not drain:
        drain = comp.get_pin("3")

    return gate, source, drain


def _find_pull_resistor(net_name: str, target_rail: str, graph: SchematicGraph) -> Optional[Component]:
    """Checks if net_name has a resistor connected to target_rail ('GND' or power)."""
    net = graph.get_net(net_name)
    if not net:
        return None

    for pin in net.pins:
        comp = graph.get_component(pin.component_ref)
        if comp and (comp.ref_des.startswith("R") or comp.comp_type == "RESISTOR"):
            for other_pin in comp.pins.values():
                if other_pin.pin_net != net_name if hasattr(other_pin, "pin_net") else other_pin.net != net_name:
                    target_net = graph.get_net(other_pin.net)
                    if target_rail == "GND" and target_net and target_net.is_ground:
                        return comp
                    elif target_rail == "POWER" and target_net and target_net.is_power:
                        return comp
    return None


def _net_has_mcu_connection(net_name: str, graph: SchematicGraph) -> bool:
    """Checks if a net directly connects to a microcontroller or IC GPIO."""
    net = graph.get_net(net_name)
    if not net:
        return False
    for pin in net.pins:
        comp = graph.get_component(pin.component_ref)
        if comp and comp.comp_type in ("MCU", "IC") or (comp and comp.ref_des.startswith("U")):
            # Check if pin is a GPIO or signal pin, not a power/gnd pin
            p_name = pin.name.upper()
            if not any(pwr in p_name for pwr in ["VDD", "VCC", "GND", "VSS", "V+"]):
                return True
    return False


def check_bjt(comp: Component, graph: SchematicGraph) -> CheckResult:
    """Checks BJT base resistor for proper switching saturation and validates emitter orientation."""
    base, emitter, collector = get_bjt_pins(comp)
    if not base or not emitter or not collector:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type=comp.comp_type or "BJT",
            status=CheckStatus.WARN,
            message="Could not identify BJT Base, Emitter, and Collector pins.",
            details={"pins": str(list(comp.pins.keys()))}
        )

    b_net = base.net
    e_net = emitter.net
    c_net = collector.net

    is_npn = "PNP" not in comp.comp_type.upper()
    net_e = graph.get_net(e_net)
    is_e_gnd = net_e.is_ground if net_e else False
    is_e_power = net_e.is_power if net_e else False

    # 1. Emitter Polarity Check
    if is_npn and is_e_power:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="BJT_NPN",
            status=CheckStatus.FAIL,
            message=f"Incorrect NPN Emitter connection: Emitter is connected to positive power rail '{e_net}'. For standard low-side switching, NPN Emitter must connect to GND.",
            details={"base": b_net, "emitter": e_net, "collector": c_net}
        )
    elif not is_npn and is_e_gnd:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="BJT_PNP",
            status=CheckStatus.FAIL,
            message=f"Incorrect PNP Emitter connection: Emitter is connected to GND. For high-side switching, PNP Emitter must connect to positive power rail.",
            details={"base": b_net, "emitter": e_net, "collector": c_net}
        )

    # 2. Base Series Resistor / Saturation Check
    # Check if base connects through a series resistor
    net_b_obj = graph.get_net(b_net)
    series_resistor: Optional[Component] = None
    res_val: Optional[float] = None

    if net_b_obj:
        for pin in net_b_obj.pins:
            c = graph.get_component(pin.component_ref)
            if c and (c.ref_des.startswith("R") or c.comp_type == "RESISTOR"):
                val = parse_resistance(c.value)
                if val is not None:
                    series_resistor = c
                    res_val = val
                    break

    # If no resistor on base net, check if base connects directly to an MCU GPIO
    is_direct_mcu = _net_has_mcu_connection(b_net, graph) or "MCU" in b_net.upper() or "GPIO" in b_net.upper()

    if is_direct_mcu and not series_resistor:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="BJT_NPN" if is_npn else "BJT_PNP",
            status=CheckStatus.WARN,
            message=f"Direct connection to Base without series resistor: Net '{b_net}' connects directly to an MCU/logic output. A base resistor (typically 1kΩ - 4.7kΩ) is needed to limit GPIO current and ensure saturation.",
            details={"base": b_net, "emitter": e_net, "collector": c_net}
        )

    if series_resistor and res_val is not None:
        if res_val > 50000.0:
            return CheckResult(
                ref_des=comp.ref_des,
                component_type="BJT_NPN" if is_npn else "BJT_PNP",
                status=CheckStatus.WARN,
                message=f"Base resistor {series_resistor.ref_des} ({series_resistor.value} / {res_val}Ω) is high; verify it provides enough base current for collector load saturation.",
                details={"resistor": series_resistor.ref_des, "value": series_resistor.value}
            )
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="BJT_NPN" if is_npn else "BJT_PNP",
            status=CheckStatus.PASS,
            message=f"Base driven through saturation resistor {series_resistor.ref_des} ({series_resistor.value}). Emitter properly oriented on '{e_net}'.",
            details={"resistor": series_resistor.ref_des, "value": series_resistor.value, "emitter": e_net}
        )

    return CheckResult(
        ref_des=comp.ref_des,
        component_type="BJT_NPN" if is_npn else "BJT_PNP",
        status=CheckStatus.PASS,
        message=f"BJT connections verified: Base on '{b_net}', Emitter on '{e_net}', Collector on '{c_net}'.",
        details={"base": b_net, "emitter": e_net, "collector": c_net}
    )


def check_mosfet(comp: Component, graph: SchematicGraph) -> CheckResult:
    """Checks MOSFET gate biasing (pull-up/pull-down) to prevent floating gates during reset/boot."""
    gate, source, drain = get_mosfet_pins(comp)
    if not gate or not source or not drain:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type=comp.comp_type or "MOSFET",
            status=CheckStatus.WARN,
            message="Could not identify MOSFET Gate, Source, and Drain pins.",
            details={"pins": str(list(comp.pins.keys()))}
        )

    g_net = gate.net
    s_net = source.net
    d_net = drain.net

    is_n_ch = "P" not in comp.comp_type.upper()
    net_s = graph.get_net(s_net)
    is_s_gnd = net_s.is_ground if net_s else False

    # 1. Source Polarity Check
    if is_n_ch and not is_s_gnd and net_s and net_s.is_power:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="MOSFET_N",
            status=CheckStatus.FAIL,
            message=f"N-Channel MOSFET Source is connected to positive power rail '{s_net}'. For standard low-side switching, Source must connect to GND.",
            details={"gate": g_net, "source": s_net, "drain": d_net}
        )

    # 2. Gate Pull-down / Pull-up Check
    # Check if gate has a pull-down to GND (for N-ch) or pull-up to power (for P-ch)
    pulldown = _find_pull_resistor(g_net, "GND", graph)
    pullup = _find_pull_resistor(g_net, "POWER", graph)

    if is_n_ch:
        if pulldown:
            return CheckResult(
                ref_des=comp.ref_des,
                component_type="MOSFET_N",
                status=CheckStatus.PASS,
                message=f"Gate properly biased with pull-down resistor {pulldown.ref_des} ({pulldown.value}) to GND to prevent floating state during boot.",
                details={"pulldown": pulldown.ref_des, "value": pulldown.value, "gate": g_net, "source": s_net}
            )
        else:
            return CheckResult(
                ref_des=comp.ref_des,
                component_type="MOSFET_N",
                status=CheckStatus.WARN,
                message=f"Floating gate risk: No pull-down resistor to GND found on Gate net '{g_net}'. Adding a 10kΩ - 100kΩ pull-down is recommended to prevent unintended turn-on during MCU boot.",
                details={"gate": g_net, "source": s_net, "drain": d_net}
            )
    else: # P-channel
        if pullup:
            return CheckResult(
                ref_des=comp.ref_des,
                component_type="MOSFET_P",
                status=CheckStatus.PASS,
                message=f"Gate properly biased with pull-up resistor {pullup.ref_des} ({pullup.value}) to power rail to prevent floating state during boot.",
                details={"pullup": pullup.ref_des, "value": pullup.value, "gate": g_net, "source": s_net}
            )
        else:
            return CheckResult(
                ref_des=comp.ref_des,
                component_type="MOSFET_P",
                status=CheckStatus.WARN,
                message=f"Floating gate risk: No pull-up resistor to power rail found on Gate net '{g_net}'. Adding a 10kΩ - 100kΩ pull-up is recommended.",
                details={"gate": g_net, "source": s_net, "drain": d_net}
            )


def check_all_transistors(graph: SchematicGraph) -> List[CheckResult]:
    """Runs checks on all BJTs and MOSFETs in the schematic."""
    results: List[CheckResult] = []
    for comp in graph.components.values():
        c_type = comp.comp_type.upper()
        if "MOSFET" in c_type or "MOS" in c_type:
            results.append(check_mosfet(comp, graph))
        elif "BJT" in c_type or comp.ref_des.upper().startswith("Q"):
            # If Q ref_des and not classified as MOSFET, treat as BJT
            results.append(check_bjt(comp, graph))
    return results
