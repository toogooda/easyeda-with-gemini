from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus, parse_resistance, parse_capacitance
from .parts_manager import PartsManager, PartProfile
from .checker_ics import check_ic_decoupling, _find_power_pullup


def _find_ground_pulldown(net_name: str, graph: SchematicGraph) -> Optional[Component]:
    """Finds a pull-down resistor between net_name and Ground."""
    net = graph.get_net(net_name)
    if not net:
        return None
    for pin in net.pins:
        comp = graph.get_component(pin.component_ref)
        if comp and (comp.ref_des.startswith("R") or comp.comp_type == "RESISTOR"):
            for other_pin in comp.pins.values():
                if other_pin.net != net_name:
                    target_net = graph.get_net(other_pin.net)
                    if target_net and target_net.is_ground:
                        return comp
    return None


def check_mcu_power_and_filtering(comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Validates VDD, VSS, and VDDA power rails and decoupling for the microcontroller."""
    results: List[CheckResult] = []

    # Check decoupling via cached profile
    results.extend(check_ic_decoupling(comp, graph, parts_manager))


    # Verify all VSS ground pins are tied to GND
    for pin in comp.pins.values():
        p_name = pin.name.upper()
        if p_name.startswith("VSS") or p_name == "GND":
            net_obj = graph.get_net(pin.net)
            if not net_obj or not net_obj.is_ground:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="MCU",
                    status=CheckStatus.FAIL,
                    message=f"Ground pin {pin.name} ({pin.number}) is not connected to GND! Connected to '{pin.net}'.",
                    details={"pin": pin.name, "net": pin.net}
                ))

    return results


def check_mcu_crystals(comp: Component, graph: SchematicGraph, profile: Optional[PartProfile]) -> List[CheckResult]:
    """Validates HSE (High-Speed) and optional LSE (32.768kHz RTC) crystal circuits and load capacitors."""
    results: List[CheckResult] = []

    # 1. HSE Crystal (OSC_IN / OSC_OUT)
    hse_spec = profile.crystals.get("hse") if profile else None
    hse_in = comp.find_pin_matching(r"(OSC_IN|OSCIN|XTAL_IN|XTAL1)")
    hse_out = comp.find_pin_matching(r"(OSC_OUT|OSCOUT|XTAL_OUT|XTAL2)")
    if not hse_in:
        spec_in = str(hse_spec.get("in", "5")) if hse_spec else "5"
        hse_in = comp.get_pin(spec_in)
    if not hse_out:
        spec_out = str(hse_spec.get("out", "6")) if hse_spec else "6"
        hse_out = comp.get_pin(spec_out)

    if hse_in and hse_out:
        net_in = hse_in.net
        net_out = hse_out.net

        # Check if connected to a crystal
        crystal_comp: Optional[Component] = None
        for p in graph.get_connected_pins(net_in):
            c = graph.get_component(p.component_ref)
            if c and (c.comp_type == "CRYSTAL" or c.ref_des.startswith("Y") or c.ref_des.startswith("X")):
                crystal_comp = c
                break

        if crystal_comp:
            # Check load capacitors to GND on both pins
            caps_in = graph.find_capacitors_between(net_in, "GND")
            caps_out = graph.find_capacitors_between(net_out, "GND")

            if caps_in and caps_out:
                c1_str = f"{caps_in[0].ref_des} ({caps_in[0].value})"
                c2_str = f"{caps_out[0].ref_des} ({caps_out[0].value})"
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="MCU",
                    status=CheckStatus.PASS,
                    message=f"HSE Crystal {crystal_comp.ref_des} ({crystal_comp.value}) properly wired on {hse_in.name}/{hse_out.name} with load capacitors {c1_str} and {c2_str}.",
                    details={"crystal": crystal_comp.ref_des, "caps": f"{c1_str}, {c2_str}"}
                ))
            else:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="MCU",
                    status=CheckStatus.WARN,
                    message=f"HSE Crystal {crystal_comp.ref_des} connected on {hse_in.name}/{hse_out.name}, but missing load capacitors to GND!",
                    details={"crystal": crystal_comp.ref_des}
                ))

    # 2. LSE / RTC Crystal (PC14-OSC32_IN / PC15-OSC32_OUT)
    lse_spec = profile.crystals.get("lse_rtc") if profile else None
    lse_in = comp.find_pin_matching(r"(OSC32_IN|RTC_IN|OSC32IN)")
    lse_out = comp.find_pin_matching(r"(OSC32_OUT|RTC_OUT|OSC32OUT)")
    if not lse_in:
        spec_lse_in = str(lse_spec.get("in", "3")) if lse_spec else "3"
        lse_in = comp.get_pin(spec_lse_in)
    if not lse_out:
        spec_lse_out = str(lse_spec.get("out", "4")) if lse_spec else "4"
        lse_out = comp.get_pin(spec_lse_out)

    if lse_in and lse_out:
        net_in = lse_in.net
        net_out = lse_out.net

        # Check if connected to an RTC crystal
        rtc_crystal: Optional[Component] = None
        for p in graph.get_connected_pins(net_in):
            c = graph.get_component(p.component_ref)
            if c and (c.comp_type == "CRYSTAL" or c.ref_des.startswith("Y") or c.ref_des.startswith("X")):
                if c != crystal_comp:
                    rtc_crystal = c
                    break

        if rtc_crystal:
            caps_in = graph.find_capacitors_between(net_in, "GND")
            caps_out = graph.find_capacitors_between(net_out, "GND")

            if caps_in and caps_out:
                c1_str = f"{caps_in[0].ref_des} ({caps_in[0].value})"
                c2_str = f"{caps_out[0].ref_des} ({caps_out[0].value})"
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="MCU",
                    status=CheckStatus.PASS,
                    message=f"LSE 32.768kHz RTC Crystal {rtc_crystal.ref_des} ({rtc_crystal.value}) properly wired on {lse_in.name}/{lse_out.name} with load capacitors {c1_str} and {c2_str}.",
                    details={"crystal": rtc_crystal.ref_des, "caps": f"{c1_str}, {c2_str}"}
                ))
            else:
                results.append(CheckResult(
                    ref_des=comp.ref_des,
                    component_type="MCU",
                    status=CheckStatus.WARN,
                    message=f"LSE RTC Crystal {rtc_crystal.ref_des} connected on {lse_in.name}/{lse_out.name}, but missing load capacitors to GND!",
                    details={"crystal": rtc_crystal.ref_des}
                ))
        else:
            # RTC crystal is optional
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="MCU",
                status=CheckStatus.PASS,
                message=f"LSE RTC crystal is excluded (pins {lse_in.name}/{lse_out.name} available as GPIO or internal oscillator).",
                details={"status": "EXCLUDED"}
            ))

    return results


def check_mcu_reset_and_boot(comp: Component, graph: SchematicGraph, profile: Optional[PartProfile] = None) -> List[CheckResult]:
    """Validates NRST pull-up and BOOT0 pull-down circuitry."""
    results: List[CheckResult] = []

    # Reset pin (NRST)
    reset_spec = profile.reset_pin if profile else None
    nrst_pin = comp.find_pin_matching(r"^(NRST|RESET|RESET_N|nRST)$")
    if not nrst_pin:
        spec_rst = str(reset_spec.get("pin", "7")) if reset_spec else "7"
        nrst_pin = comp.get_pin(spec_rst)

    if nrst_pin:
        pullup = _find_power_pullup(nrst_pin.net, graph)
        caps = graph.find_capacitors_between(nrst_pin.net, "GND")

        cap_str = f" with filter cap {caps[0].ref_des} ({caps[0].value})" if caps else ""
        if pullup:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="MCU",
                status=CheckStatus.PASS,
                message=f"Reset pin '{nrst_pin.name}' properly pulled up with {pullup.ref_des} ({pullup.value}){cap_str}.",
                details={"pin": nrst_pin.name, "net": nrst_pin.net, "pullup": pullup.ref_des}
            ))
        else:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="MCU",
                status=CheckStatus.WARN,
                message=f"No external pull-up resistor detected on Reset pin '{nrst_pin.name}'. An external 10kΩ pull-up + 100nF filter cap is recommended for noise immunity.",
                details={"pin": nrst_pin.name, "net": nrst_pin.net}
            ))

    # Boot0 pin
    boot0_pin = comp.find_pin_matching(r"^(BOOT0|BOOT_0)$")
    if not boot0_pin:
        spec_boot = str(profile.boot_strapping[0].get("pin", "44")) if profile and profile.boot_strapping else "44"
        boot0_pin = comp.get_pin(spec_boot)

    if boot0_pin:
        net_obj = graph.get_net(boot0_pin.net)
        is_direct_gnd = net_obj.is_ground if net_obj else False
        pulldown = _find_ground_pulldown(boot0_pin.net, graph)

        if is_direct_gnd or pulldown:
            pd_str = f" via {pulldown.ref_des} ({pulldown.value})" if pulldown else " directly"
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="MCU",
                status=CheckStatus.PASS,
                message=f"BOOT0 pin properly tied to GND{pd_str} for standard Flash boot mode.",
                details={"pin": boot0_pin.name, "net": boot0_pin.net}
            ))
        else:
            results.append(CheckResult(
                ref_des=comp.ref_des,
                component_type="MCU",
                status=CheckStatus.WARN,
                message=f"BOOT0 pin '{boot0_pin.name}' is not tied to GND (net: '{boot0_pin.net}'). Ensure it is not floating during boot.",
                details={"pin": boot0_pin.name, "net": boot0_pin.net}
            ))

    return results


def check_microcontroller(comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Runs all microcontroller checks: power, decoupling, dual crystals, reset, and boot."""
    profile = parts_manager.get_profile(comp.lcsc_id) if comp.lcsc_id else None
    results: List[CheckResult] = []
    results.extend(check_mcu_power_and_filtering(comp, graph, parts_manager))
    results.extend(check_mcu_crystals(comp, graph, profile))
    results.extend(check_mcu_reset_and_boot(comp, graph, profile))
    return results


