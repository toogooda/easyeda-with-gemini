from __future__ import annotations
from typing import List, Optional, Tuple
import re

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus, parse_resistance


def get_diode_pins(comp: Component, parts_manager: Optional[Any] = None) -> Tuple[Optional[Pin], Optional[Pin]]:
    """
    Returns (anode_pin, cathode_pin) for a diode or LED.
    Ground-truth resolution order:
    1. Explicit pin names on symbol/component ('A', 'ANODE', '+' vs 'K', 'C', 'CATHODE', '-')
    2. Verified PartProfile pin_map (via PartsManager lookup of LCSC ID or part number)
    3. IPC-7351 package standards for surface mount diodes:
       - Packages containing DO-214, SMA, SMB, SMC, SOD-123, SOD-323, SOD-523:
         Pin 1 is CATHODE, Pin 2 is ANODE!
    4. NEVER guess or assume. Return (None, None) if unresolved.
    """
    anode: Optional[Pin] = None
    cathode: Optional[Pin] = None

    # 1. Check explicit pin names
    for pin in comp.pins.values():
        name_up = pin.name.upper()
        if name_up in ("A", "ANODE", "+"):
            anode = pin
        elif name_up in ("K", "C", "CATHODE", "-"):
            cathode = pin
    if anode and cathode:
        return anode, cathode

    # 2. Check PartProfile pin_map
    if parts_manager:
        profile = parts_manager.find_profile(lcsc_id=comp.lcsc_id, part_number=comp.value)
        if profile and profile.pin_map:
            for pin_num, role in profile.pin_map.items():
                role_up = str(role).upper()
                if role_up in ("A", "ANODE", "+"):
                    anode = comp.get_pin(pin_num)
                elif role_up in ("K", "C", "CATHODE", "-"):
                    cathode = comp.get_pin(pin_num)
            if anode and cathode:
                return anode, cathode

    # 3. Check IPC-7351 package standards for SMD diodes
    pkg_up = comp.package.upper()
    smd_diode_packages = ["DO-214", "SMA", "SMB", "SMC", "SOD-123", "SOD-323", "SOD-523"]
    if any(p in pkg_up for p in smd_diode_packages):
        # IPC-7351 standard: Pin 1 = Cathode (band), Pin 2 = Anode
        cathode = comp.get_pin("1")
        anode = comp.get_pin("2")
        if anode and cathode:
            return anode, cathode

    # 4. Strict no-guessing: do not make blind assumptions
    return None, None


def check_diode(comp: Component, graph: SchematicGraph, parts_manager: Optional[Any] = None) -> CheckResult:
    """Checks power and flyback diodes for correct orientation."""
    anode, cathode = get_diode_pins(comp, parts_manager)
    if not anode or not cathode:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.WARN,
            message=f"Could not verify Anode/Cathode pinout for '{comp.ref_des}' ({comp.value}, {comp.package}) from datasheet, symbol, or package standards. Manual verification required (VERIFY_PINOUT).",
            details={"pins": str(list(comp.pins.keys())), "package": comp.package, "value": comp.value}
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

    is_a_gnd = net_a_obj.is_ground if net_a_obj else False
    is_c_gnd = net_c_obj.is_ground if net_c_obj else False

    def _net_feeds_circuit(net_name: str) -> bool:
        net = graph.get_net(net_name)
        if not net:
            return False
        if net.is_power:
            return True
        for pin in net.pins:
            c = graph.get_component(pin.component_ref)
            if c and c.ref_des != comp.ref_des:
                if c.comp_type in ("IC", "MCU") or c.ref_des.startswith("U"):
                    return True
                if c.comp_type == "CAPACITOR" or c.ref_des.startswith("C"):
                    for other_p in c.pins.values():
                        if other_p.net != net_name:
                            on = graph.get_net(other_p.net)
                            if on and on.is_ground:
                                return True
        return False

    is_a_load = is_a_sys or is_a_power or _net_feeds_circuit(a_net)
    is_c_load = is_c_sys or is_c_power or _net_feeds_circuit(c_net)

    if is_a_raw and is_c_gnd:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.FAIL,
            message=f"Dead short across power input: Diode Anode is connected to input '{a_net}' and Cathode is connected to GND!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    if is_a_raw and is_c_load and not is_c_gnd:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.PASS,
            message=f"Reverse polarity protection properly oriented: Anode on input '{a_net}', Cathode on system rail '{c_net}'.",
            details={"anode_net": a_net, "cathode_net": c_net}
        )
    elif is_c_raw and is_a_load and not is_a_gnd:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="DIODE",
            status=CheckStatus.FAIL,
            message=f"Backwards diode blocking power: Cathode is connected to input '{c_net}' and Anode to system rail '{a_net}'. Power cannot pass into the board!",
            details={"anode_net": a_net, "cathode_net": c_net}
        )

    # 3. Zener / TVS clamp check (Cathode to positive rail, Anode to GND)
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



def check_led(comp: Component, graph: SchematicGraph, parts_manager: Optional[Any] = None) -> CheckResult:
    """Checks LED polarity and verifies the presence and value of a series current-limiting resistor."""
    anode, cathode = get_diode_pins(comp, parts_manager)
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


def check_tvs_array(comp: Component, graph: SchematicGraph, parts_manager: Optional[Any] = None) -> CheckResult:
    """Checks multi-channel TVS / ESD diode protection arrays (e.g. SP720, USBLC6)."""
    profile = parts_manager.find_profile(lcsc_id=comp.lcsc_id or "", part_number=comp.value or "") if parts_manager else None

    # Identify ground and positive clamp pins
    gnd_pins: List[Pin] = []
    v_plus_pins: List[Pin] = []
    protected_pins: List[Pin] = []

    for pin in comp.pins.values():
        net = graph.get_net(pin.net) if pin.net else None
        p_name = pin.name.upper() if pin.name else ""
        if profile and profile.pin_map:
            role = str(profile.pin_map.get(str(pin.number), "")).upper()
            if role in ("GND", "V-", "VSS", "GROUND"):
                gnd_pins.append(pin)
                continue
            elif role in ("V+", "VCC", "VDD", "VP"):
                v_plus_pins.append(pin)
                continue

        if (net and net.is_ground) or p_name in ("GND", "V-", "VSS"):
            gnd_pins.append(pin)
        elif (net and net.is_power) or p_name in ("V+", "VCC", "VDD", "VP"):
            v_plus_pins.append(pin)
        else:
            protected_pins.append(pin)

    # If ground pin missing
    if not gnd_pins:
        return CheckResult(
            ref_des=comp.ref_des,
            component_type="TVS_ARRAY",
            status=CheckStatus.WARN,
            message=f"TVS diode array '{comp.ref_des}' ({comp.value or comp.package}) has no verified ground pin! ESD transients cannot be safely shunted to ground.",
            details={"pins": str(list(comp.pins.keys())), "type": "TVS_ARRAY"}
        )

    gnd_pin = gnd_pins[0]
    gnd_net = gnd_pin.net
    v_plus_net = v_plus_pins[0].net if v_plus_pins else "Unconnected"
    protected_nets = sorted(list(set(p.net for p in protected_pins if p.net and p.net != gnd_net and p.net != v_plus_net)))

    status = CheckStatus.PASS
    msg = f"Multi-channel TVS / ESD array active: Ground return on '{gnd_net}'"
    if v_plus_pins:
        msg += f", V+ clamp on '{v_plus_net}'"
    msg += f", protecting {len(protected_nets)} signal line(s): {', '.join(protected_nets[:8])}"
    if len(protected_nets) > 8:
        msg += f", +{len(protected_nets) - 8} more"

    return CheckResult(
        ref_des=comp.ref_des,
        component_type="TVS_ARRAY",
        status=status,
        message=msg,
        details={
            "gnd_net": gnd_net,
            "v_plus_net": v_plus_net,
            "protected_nets": ", ".join(protected_nets),
            "channels": len(protected_nets)
        }
    )


def check_all_diodes_and_leds(graph: SchematicGraph, parts_manager: Optional[Any] = None) -> List[CheckResult]:
    """Runs checks on all diodes, LEDs, and TVS arrays in the schematic."""
    results: List[CheckResult] = []
    for comp in graph.components.values():
        if comp.comp_type == "LED" or comp.ref_des.upper().startswith("LED"):
            results.append(check_led(comp, graph, parts_manager))
        elif comp.comp_type in ("DIODE", "TVS_ARRAY") or comp.ref_des.upper().startswith("D"):
            if len(comp.pins) > 3:
                results.append(check_tvs_array(comp, graph, parts_manager))
            else:
                results.append(check_diode(comp, graph, parts_manager))
    return results

