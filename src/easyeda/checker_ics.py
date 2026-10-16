from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus, parse_resistance, parse_capacitance
from .parts_manager import PartsManager, PartProfile


def _find_power_pullup(net_name: str, graph: SchematicGraph) -> Optional[Component]:
    """Finds a pull-up resistor between net_name and any positive power rail."""
    net = graph.get_net(net_name)
    if not net:
        return None
    for pin in net.pins:
        comp = graph.get_component(pin.component_ref)
        if comp and (comp.ref_des.startswith("R") or comp.comp_type == "RESISTOR"):
            for other_pin in comp.pins.values():
                if other_pin.net != net_name:
                    target_net = graph.get_net(other_pin.net)
                    if target_net and target_net.is_power:
                        return comp
    return None


def check_ic_decoupling(comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Checks that IC power pins have matching decoupling capacitors per cached datasheet profile."""
    results: List[CheckResult] = []
    profile = parts_manager.get_profile(comp.lcsc_id) if comp.lcsc_id else None

    if not profile or not profile.power_pins:
        # Fallback heuristic: check any pin with VDD/VCC in name
        for pin in comp.pins.values():
            p_name = pin.name.upper()
            if any(pwr in p_name for pwr in ["VDD", "VCC", "V+", "VIN"]):
                net_obj = graph.get_net(pin.net)
                if net_obj and net_obj.is_power:
                    caps = graph.find_capacitors_between(pin.net, "GND")
                    if caps:
                        cap_names = ", ".join([f"{c.ref_des} ({c.value})" for c in caps[:3]])
                        results.append(CheckResult(
                            ref_des=comp.ref_des,
                            component_type=comp.comp_type or "IC",
                            status=CheckStatus.PASS,
                            message=f"Power pin {pin.name} ({pin.net}) has decoupling: {cap_names}.",
                            details={"pin": pin.name, "net": pin.net, "capacitors": cap_names}
                        ))
                    else:
                        results.append(CheckResult(
                            ref_des=comp.ref_des,
                            component_type=comp.comp_type or "IC",
                            status=CheckStatus.WARN,
                            message=f"No decoupling capacitors detected on power pin {pin.name} ({pin.net}).",
                            details={"pin": pin.name, "net": pin.net}
                        ))
        return results

    # Datasheet-specific decoupling check
    for p_spec in profile.power_pins:
        spec_pin_num = str(p_spec.get("pin", ""))
        spec_pin_name = str(p_spec.get("name", "")).upper()
        req_decoupling = p_spec.get("decoupling", "100nF")

        # Find matching pin on component
        target_pin: Optional[Pin] = comp.get_pin(spec_pin_num)
        if not target_pin and spec_pin_name:
            target_pin = comp.get_pin_by_name(spec_pin_name)

        if not target_pin:
            continue

        net_name = target_pin.net
        caps = graph.find_capacitors_between(net_name, "GND")

        if caps:
            cap_strs = [f"{c.ref_des} ({c.value})" for c in caps]
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type=profile.part_type,
                status=CheckStatus.PASS,
                message=f"Power pin {target_pin.name or target_pin.number} ({net_name}) decoupled with {', '.join(cap_strs)} (Datasheet spec: {req_decoupling}).",
                details={"pin": target_pin.name or target_pin.number, "net": net_name, "required": req_decoupling, "found": ", ".join(cap_strs)}
            ))
        else:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type=profile.part_type,
                status=CheckStatus.FAIL,
                message=f"Missing decoupling on power pin {target_pin.name or target_pin.number} ({net_name})! Datasheet requires: {req_decoupling}.",
                details={"pin": target_pin.name or target_pin.number, "net": net_name, "required": req_decoupling}
            ))

    return results


def check_i2c_peripheral(comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Resolves I2C device address from strapping pins and validates bus pull-up resistors."""
    results: List[CheckResult] = []
    profile = parts_manager.get_profile(comp.lcsc_id) if comp.lcsc_id else None

    # 1. Address Strapping Resolution
    if profile and profile.i2c_addresses:
        # Identify strapping pin on component (e.g. ADD0, ADD, A0, A1, ADDR)
        strap_pin = comp.find_pin_matching(r"^(ADD\d*|A\d+|ADDR\d*)$")
        if strap_pin:
            strap_net = graph.get_net(strap_pin.net)

            state = "FLOAT"
            if strap_net:
                if strap_net.is_ground:
                    state = "GND"
                elif strap_net.is_power:
                    state = "V+"
                elif "SDA" in strap_net.name.upper():
                    state = "SDA"
                elif "SCL" in strap_net.name.upper():
                    state = "SCL"

            # Match against profile strapping table
            strap_key = f"{strap_pin.name}={state}"
            alt_key = f"ADD0={state}"
            addr = profile.i2c_addresses.get(strap_key) or profile.i2c_addresses.get(alt_key)

            if addr:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="IC_I2C",
                    status=CheckStatus.PASS,
                    message=f"I2C Address configured: Pin {strap_pin.name} connected to {state} -> 7-bit Address is {addr}.",
                    details={"pin": strap_pin.name, "state": state, "i2c_address": addr}
                ))
            else:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="IC_I2C",
                    status=CheckStatus.WARN,
                    message=f"I2C strapping pin {strap_pin.name} connected to '{strap_pin.net}' (State: {state}), but address could not be matched in profile.",
                    details={"pin": strap_pin.name, "net": strap_pin.net, "state": state}
                ))

    # 2. Bus Pull-Up Checks (SDA, SCL)
    sda_pin = comp.find_pin_matching(r"^SDA")
    scl_pin = comp.find_pin_matching(r"^SCL")

    for bus_pin, bus_name in [(sda_pin, "SDA"), (scl_pin, "SCL")]:
        if not bus_pin:
            continue
        pullup = _find_power_pullup(bus_pin.net, graph)
        if pullup:
            r_val = parse_resistance(pullup.value)
            if r_val is not None and (r_val < 1000.0 or r_val > 15000.0):
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="IC_I2C",
                    status=CheckStatus.WARN,
                    message=f"I2C {bus_name} line '{bus_pin.net}' has pull-up {pullup.ref_des} ({pullup.value}), which is outside recommended 2.2kΩ - 10kΩ range.",
                    details={"bus": bus_name, "net": bus_pin.net, "pullup": pullup.ref_des, "value": pullup.value}
                ))
            else:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="IC_I2C",
                    status=CheckStatus.PASS,
                    message=f"I2C {bus_name} line '{bus_pin.net}' properly pulled up with {pullup.ref_des} ({pullup.value}).",
                    details={"bus": bus_name, "net": bus_pin.net, "pullup": pullup.ref_des, "value": pullup.value}
                ))
        else:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="IC_I2C",
                status=CheckStatus.FAIL,
                message=f"Missing pull-up resistor on I2C {bus_name} line '{bus_pin.net}'! I2C bus lines are open-drain and require a pull-up to VDD.",
                details={"bus": bus_name, "net": bus_pin.net}
            ))

    return results
