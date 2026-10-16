from __future__ import annotations
from typing import List, Optional, Tuple
import re

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus, parse_resistance


def get_diode_pins(comp: Component) -> Tuple[Optional[Pin], Optional[Pin]]:
    """Returns (anode_pin, cathode_pin) for a diode or LED."""
    anode: Optional[Pin] = None
    cathode: Optional[Pin] = None

    # Check pin names first
    for pin in comp.pins.values():
        name_up = pin.name.upper()
        if name_up in ("A", "ANODE", "+"):
            anode = pin
        elif name_up in ("K", "C", "CATHODE", "-"):
            cathode = pin

    # Fallback to pin numbers: 1 is Anode, 2 is Cathode
    if not anode:
        anode = comp.get_pin("1")
    if not cathode:
        cathode = comp.get_pin("2")

    return anode, cathode


def check_diode(comp: Component, graph: SchematicGraph) -> CheckResult:
    """Checks power and flyback diodes for correct orientation."""
    anode, cathode = get_diode_pins(comp)
    if not anode or not cathode:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.WARN,
            message="Could not identify Anode and Cathode pins.",
            details={"pins": str(list(comp.pins.keys()))}
        )

    a_net = anode.net
    c_net = cathode.net

    # 1. Flyback / Relay coil protection check
    # Inductive / coil net indicators
    coil_indicators = ["RELAY", "COIL", "MOTOR", "SOLENOID", "SW", "DRAIN", "COLLECTOR"]
    is_a_coil = any(ind in a_net.upper() for ind in coil_indicators)
    is_c_coil = any(ind in c_net.upper() for ind in coil_indicators)

    net_a_obj = graph.get_net(a_net)
    net_c_obj = graph.get_net(c_net)
    is_a_power = net_a_obj.is_power if net_a_obj else False
    is_c_power = net_c_obj.is_power if net_c_obj else False

    if is_a_power and is_c_coil:
        # Anode on positive power rail with cathode on switched coil -> Backwards!
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.FAIL,
            message=f"Backwards flyback diode: Anode is on positive rail '{a_net}' and Cathode on '{c_net}'. This will short-circuit power when the load is switched!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )
    elif is_c_power and is_a_coil:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.PASS,
            message=f"Flyback diode correctly oriented: Cathode on positive rail '{c_net}', Anode on switched coil net '{a_net}'.",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    # 2. Reverse polarity power input protection
    is_a_sys = any(sys_tag in a_net.upper() for sys_tag in ["SYS", "PROT", "OUT", "INT"])
    is_c_sys = any(sys_tag in c_net.upper() for sys_tag in ["SYS", "PROT", "OUT", "INT"])

    raw_keywords = ["VIN", "VBUS", "VBAT", "RAW", "INPUT", "DC", "BARREL", "JACK"]
    is_a_raw = any(kw in a_net.upper() for kw in raw_keywords) and not is_a_sys
    is_c_raw = any(kw in c_net.upper() for kw in raw_keywords) and not is_c_sys

    if is_a_raw and (is_c_sys or is_c_power):
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.PASS,
            message=f"Reverse polarity protection properly oriented: Anode on input '{a_net}', Cathode on system rail '{c_net}'.",
            details={"anode_net": a_net, "cathode_net": c_net}
        )
    elif is_c_raw and (is_a_sys or is_a_power):
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.FAIL,
            message=f"Backwards diode blocking power: Cathode is connected to input '{c_net}' and Anode to system rail '{a_net}'. Power cannot pass into the board!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    # 3. Zener / TVS clamp check (Cathode to positive rail, Anode to GND)
    is_a_gnd = net_a_obj.is_ground if net_a_obj else False
    is_c_gnd = net_c_obj.is_ground if net_c_obj else False
    if is_a_gnd and is_c_power:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.PASS,
            message=f"Reverse clamp / TVS diode oriented correctly: Cathode on '{c_net}', Anode on GND.",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    return CheckResult(
        ref_des=comp.ref_des,
        component_type="DIODE",
        status=CheckStatus.PASS,
        message=f"Diode connection verified: Anode on '{a_net}', Cathode on '{c_net}'.",
        details={"anode_net": a_net, "cathode_net": c_net}
    )


def _find_led_series_resistor(anode_net: str, cathode_net: str, graph: SchematicGraph) -> Optional[Tuple[Component, float]]:
    """Finds a dedicated series resistor connected to LED Anode or Cathode (excluding global power/ground rails)."""
    for net_name in (anode_net, cathode_net):
        net = graph.get_net(net_name)
        if not net or net.is_power or net.is_ground:
            continue
        for pin in net.pins:
            comp = graph.get_component(pin.component_ref)
            if comp and (comp.ref_des.startswith("R") or comp.comp_type == "RESISTOR"):
                r_val = parse_resistance(comp.value)
                if r_val is not None:
                    return comp, r_val
    return None



def check_led(comp: Component, graph: SchematicGraph) -> CheckResult:
    """Checks LED polarity and verifies the presence and value of a series current-limiting resistor."""
    anode, cathode = get_diode_pins(comp)
    if not anode or not cathode:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="LED",
            status=CheckStatus.WARN,
            message="Could not identify LED Anode and Cathode pins.",
            details={"pins": str(list(comp.pins.keys()))}
        )

    a_net = anode.net
    c_net = cathode.net
    net_a_obj = graph.get_net(a_net)
    net_c_obj = graph.get_net(c_net)

    is_a_gnd = net_a_obj.is_ground if net_a_obj else False
    is_c_power = net_c_obj.is_power if net_c_obj else False

    # 1. Reverse polarity check
    if is_a_gnd and is_c_power:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="LED",
            status=CheckStatus.FAIL,
            message=f"Backwards LED: Anode is tied to GND and Cathode to power rail '{c_net}'. The LED is permanently reverse-biased and will not light!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    # 2. Check for current limiting resistor on either Anode or Cathode side
    r_series = _find_led_series_resistor(a_net, c_net, graph)

    resistor_comp = None
    res_val = None

    if r_series:
        resistor_comp, res_val = r_series


    if not resistor_comp:
        # Check if connected directly between power and ground/GPIO
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="LED",
            status=CheckStatus.FAIL,
            message=f"Missing current-limiting resistor! LED is wired directly between '{a_net}' and '{c_net}'. This will exceed current ratings and damage the LED or driving GPIO!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    # Check resistor value range (typical 100R to 10k)
    if res_val < 50.0:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="LED",
            status=CheckStatus.WARN,
            message=f"Series resistor {resistor_comp.ref_des} value ({resistor_comp.value} / {res_val}Ω) is very low. Verify it does not exceed maximum LED/GPIO current.",
            details={"resistor": resistor_comp.ref_des, "value": resistor_comp.value, "anode_net": a_net, "cathode_net": c_net}
        )
    elif res_val > 15000.0:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="LED",
            status=CheckStatus.WARN,
            message=f"Series resistor {resistor_comp.ref_des} value ({resistor_comp.value} / {res_val}Ω) is unusually high. The LED may be very dim.",
            details={"resistor": resistor_comp.ref_des, "value": resistor_comp.value, "anode_net": a_net, "cathode_net": c_net}
        )

    return CheckResult(
        ref_des=comp.ref_des,
        component_type="LED",
        status=CheckStatus.PASS,
        message=f"Polarity and current limiting verified with {resistor_comp.ref_des} ({resistor_comp.value}).",
        details={"resistor": resistor_comp.ref_des, "value": resistor_comp.value, "anode_net": a_net, "cathode_net": c_net}
    )


def check_all_diodes_and_leds(graph: SchematicGraph) -> List[CheckResult]:
    """Runs checks on all diodes and LEDs in the schematic."""
    results: List[CheckResult] = []
    for comp in graph.components.values():
        if comp.comp_type == "LED" or comp.ref_des.upper().startswith("LED"):
            results.append(check_led(comp, graph))
        elif comp.comp_type == "DIODE" or comp.ref_des.upper().startswith("D"):
            # Exclude ESD array packs named D if they have many pins (>3)
            if len(comp.pins) <= 3:
                results.append(check_diode(comp, graph))
    return results
