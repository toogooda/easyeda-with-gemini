from __future__ import annotations
import itertools
import re
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
    profile = parts_manager.find_profile(lcsc_id=comp.lcsc_id or "", part_number=comp.value or "") if parts_manager else None

    # Fallback pin names from profile.pin_map if component pins are numeric
    if profile and profile.pin_map:
        for pin_num, pin_name in profile.pin_map.items():
            p = comp.get_pin(str(pin_num))
            if p and (not p.name or p.name == p.number or p.name.isdigit()):
                p.name = str(pin_name)

    # 1. Universal Address Strapping Resolution
    if profile and (profile.i2c_addresses or profile.address_base):
        def _get_pin_state(pin: Optional[Pin]) -> str:
            if not pin or not pin.net:
                return "FLOAT"
            net = graph.get_net(pin.net)
            if not net:
                return "FLOAT"
            net_up = net.name.upper()
            if net.is_ground or any(g in net_up for g in ["GND", "VSS", "GROUND"]):
                return "GND"
            if net.is_power or any(pwr in net_up for pwr in ["3V3", "5V", "VCC", "VDD", "VS", "V+", "POWER", "VIN"]):
                return "VS" if any(x in net_up for x in ["VS", "3V3", "5V"]) else "VCC"
            if "SDA" in net_up:
                return "SDA"
            if "SCL" in net_up:
                return "SCL"
            return "FLOAT"

        # Determine target strapping pins
        target_pins: List[Pin] = []
        if profile.address_pins:
            for p_name in profile.address_pins:
                p = comp.get_pin_by_name(p_name)
                if not p and profile.pin_map:
                    for num, name in profile.pin_map.items():
                        if name.upper() == p_name.upper():
                            p = comp.get_pin(str(num))
                            break
                if p:
                    target_pins.append(p)
        else:
            # Auto-detect address strapping pins (A0, A1, A2, ADD0, etc.)
            matched = [p for p in comp.pins.values() if re.match(r"^(ADD\d*|A\d+|ADDR\d*)$", p.name.upper())]
            target_pins = sorted(matched, key=lambda x: x.name.upper(), reverse=True)

        addr: Optional[str] = None
        state_summary = ""

        # Case 0: Fixed address (0 strapping pins)
        if not target_pins:
            if "fixed" in profile.i2c_addresses:
                addr = profile.i2c_addresses["fixed"]
                state_summary = "Fixed internal address"
            elif "default" in profile.i2c_addresses:
                addr = profile.i2c_addresses["default"]
                state_summary = "Default internal address"
            elif len(profile.i2c_addresses) == 1:
                addr = list(profile.i2c_addresses.values())[0]
                state_summary = "Fixed internal address"

        # Case 1: Single strapping pin (e.g. TMP102)
        elif len(target_pins) == 1:
            p = target_pins[0]
            st = _get_pin_state(p)
            power_aliases = ["VS", "VCC", "V+"] if st in ("VS", "VCC", "V+") else [st]
            for candidate_st in power_aliases:
                addr = (
                    profile.i2c_addresses.get(f"{p.name}={candidate_st}")
                    or profile.i2c_addresses.get(candidate_st)
                    or profile.i2c_addresses.get(f"ADD0={candidate_st}")
                    or profile.i2c_addresses.get(f"A0={candidate_st}")
                )
                if addr:
                    st = candidate_st
                    break
            state_summary = f"{p.name}={p.net} ({st})"

        # Case 2: Multi-pin strapping (e.g. INA226, 24AA024/24LC024)
        else:
            pin_states = [(p.name, _get_pin_state(p)) for p in target_pins]
            state_summary = ", ".join([f"{name}={comp.get_pin_by_name(name).net if comp.get_pin_by_name(name) else ''} ({st})" for name, st in pin_states])

            # Try composite key: e.g. GND_VS, GND_SCL, GND_GND_VCC
            state_lists = []
            for _, st in pin_states:
                if st in ("VS", "VCC", "V+"):
                    state_lists.append(["VS", "VCC", "V+"])
                else:
                    state_lists.append([st])

            for combo in itertools.product(*state_lists):
                key = "_".join(combo)
                if key in profile.i2c_addresses:
                    addr = profile.i2c_addresses[key]
                    break

            # If not matched in table, evaluate binary bit-strapping formula
            if not addr and profile.address_base:
                try:
                    base_int = int(str(profile.address_base), 16) if str(profile.address_base).startswith("0x") else int(profile.address_base)
                    offset = 0
                    for p_name, st in pin_states:
                        m_bit = re.search(r"(\d+)$", p_name)
                        if m_bit:
                            bit_idx = int(m_bit.group(1))
                            if st in ("VS", "VCC", "V+"):
                                offset |= (1 << bit_idx)
                    addr = f"0x{(base_int | offset):02X}"
                except Exception:
                    pass

        if addr:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="IC_I2C",
                status=CheckStatus.PASS,
                message=f"I2C Address configured: {state_summary} -> 7-bit Address is {addr}.",
                details={"i2c_address": addr, "configuration": state_summary}
            ))
        elif target_pins:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="IC_I2C",
                status=CheckStatus.WARN,
                message=f"I2C address pins detected ({state_summary}), but address could not be resolved from profile.",
                details={"configuration": state_summary}
            ))

    # 2. Bus Pull-Up Checks (SDA, SCL)
    sda_pin = comp.find_pin_matching(r"^SDA") or comp.get_pin_by_name("SDA")
    scl_pin = comp.find_pin_matching(r"^SCL") or comp.get_pin_by_name("SCL")
    if not sda_pin and profile and profile.pin_map:
        for num, role in profile.pin_map.items():
            if str(role).upper() == "SDA":
                sda_pin = comp.get_pin(str(num))
            elif str(role).upper() == "SCL":
                scl_pin = comp.get_pin(str(num))

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
