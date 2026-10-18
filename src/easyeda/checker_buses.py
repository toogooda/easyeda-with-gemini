from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus
from .parts_manager import PartsManager, PartProfile
from .checker_ics import _find_power_pullup


def check_bus_crossovers(mcu_comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Validates bus peripheral pin assignments and crossovers (I2C, SPI, UART, CAN, SWD) between MCU and peripherals."""
    results: List[CheckResult] = []
    profile = parts_manager.get_profile(mcu_comp.lcsc_id) if mcu_comp.lcsc_id else None

    # Track pins already audited to avoid duplicate reports
    audited_pins = set()

    # Helper to find TVS / ESD protection and pull-ups on a net
    def get_net_pull_and_protection(net_name: str) -> str:
        items = []
        pullup = _find_power_pullup(net_name, graph)
        if pullup:
            items.append(f"Pull-up {pullup.ref_des} ({pullup.value})")
        # Check TVS array or ESD diode
        for p in graph.get_connected_pins(net_name):
            c = graph.get_component(p.component_ref)
            if c and c.ref_des != mcu_comp.ref_des:
                val_up = (c.value or "").upper()
                if c.comp_type == "TVS_ARRAY" or "SP720" in val_up or "TVS" in val_up:
                    items.append(f"TVS protected ({c.ref_des}.{p.number})")
                    break
        return ", ".join(items) if items else "None"

    # Helper to summarize target connections
    def get_target_summary(net_name: str) -> str:
        targets = []
        for p in graph.get_connected_pins(net_name):
            if p.component_ref == mcu_comp.ref_des:
                continue
            c = graph.get_component(p.component_ref)
            if not c:
                continue
            val_up = (c.value or "").upper()
            # Skip passive pull-ups, capacitors, and TVS protection in target summary
            if c.comp_type in ("RESISTOR", "CAPACITOR") or c.ref_des.startswith(("R", "C")):
                continue
            if c.comp_type == "TVS_ARRAY" or "SP720" in val_up or "TVS" in val_up:
                continue
            val_info = f" ({c.value})" if c.value and c.value != "{Value}" else ""
            targets.append(f"{c.ref_des}{val_info}.{p.number}")
        return ", ".join(targets) if targets else "Header / Test Point"

    # -------------------------------------------------------------
    # 1. Profile-driven UART & CAN checks (with crossover verification)
    # -------------------------------------------------------------
    if profile and profile.peripherals:
        # UART Checks
        for uart_name, uart_spec in profile.peripherals.items():
            if not uart_name.startswith("USART") and not uart_name.startswith("UART"):
                continue

            tx_pins = [str(p) for p in uart_spec.get("tx", [])]
            rx_pins = [str(p) for p in uart_spec.get("rx", [])]

            for pin in mcu_comp.pins.values():
                p_ident = pin.name if (pin.name and pin.name != pin.number) else f"Pin {pin.number}"
                if not pin.net:
                    continue
                net_up = pin.net.upper()
                is_uart_net = any(k in net_up for k in ["TX", "RX", "UART", "USART"])

                if p_ident in tx_pins or pin.number in tx_pins or pin.name in tx_pins:
                    connected = graph.get_connected_pins(pin.net)
                    has_transceiver = any(
                        other_p.component_ref != mcu_comp.ref_des and
                        graph.get_component(other_p.component_ref) and
                        any(t in other_p.name.upper() for t in ["TX", "RX"])
                        for other_p in connected
                    )

                    if not is_uart_net and not has_transceiver:
                        # Pin is repurposed for alternate peripheral (e.g. I2C or GPIO)
                        continue

                    audited_pins.add(pin.number)
                    for other_p in connected:
                        if other_p.component_ref == mcu_comp.ref_des:
                            continue
                        other_comp = graph.get_component(other_p.component_ref)
                        if not other_comp:
                            continue
                        other_name = other_p.name.upper()

                        if "TX" in other_name:
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.FAIL,
                                message=f"Swapped UART connection: MCU {uart_name} TX pin ({p_ident}) is connected to TX pin ({other_p.name}) on {other_comp.ref_des}! Both are outputs. MCU TX must connect to peripheral RX.",
                                details={"bus_type": "UART", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                            break
                        elif "RX" in other_name:
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.PASS,
                                message=f"Proper UART crossover: MCU {uart_name} TX ({p_ident}) connects to RX ({other_p.name}) on {other_comp.ref_des}.",
                                details={"bus_type": "UART", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                            break
                    else:
                        # Connected to external connector or header
                        target = get_target_summary(pin.net)
                        pull_prot = get_net_pull_and_protection(pin.net)
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.PASS,
                            message=f"MCU {uart_name} TX ({p_ident}) [Net: {pin.net}] routed to external header/connector {target}.",
                            details={"bus_type": "UART", "mcu_pin": p_ident, "target": target, "net": pin.net, "pullup_protection": pull_prot}
                        ))

                elif p_ident in rx_pins or pin.number in rx_pins or pin.name in rx_pins:
                    connected = graph.get_connected_pins(pin.net)
                    has_transceiver = any(
                        other_p.component_ref != mcu_comp.ref_des and
                        graph.get_component(other_p.component_ref) and
                        any(t in other_p.name.upper() for t in ["TX", "RX"])
                        for other_p in connected
                    )

                    if not is_uart_net and not has_transceiver:
                        # Pin is repurposed for alternate peripheral (e.g. I2C or GPIO)
                        continue

                    audited_pins.add(pin.number)
                    for other_p in connected:
                        if other_p.component_ref == mcu_comp.ref_des:
                            continue
                        other_comp = graph.get_component(other_p.component_ref)
                        if not other_comp:
                            continue
                        other_name = other_p.name.upper()

                        if "TX" in other_name:
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.PASS,
                                message=f"Proper UART crossover: MCU {uart_name} RX ({p_ident}) receives from TX ({other_p.name}) on {other_comp.ref_des}.",
                                details={"bus_type": "UART", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                            break
                        elif "RX" in other_name:
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.FAIL,
                                message=f"Swapped UART connection: MCU {uart_name} RX pin ({p_ident}) is connected to RX pin ({other_p.name}) on {other_comp.ref_des}! Both are inputs.",
                                details={"bus_type": "UART", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                            break
                    else:
                        # Connected to external connector or header
                        target = get_target_summary(pin.net)
                        pull_prot = get_net_pull_and_protection(pin.net)
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.PASS,
                            message=f"MCU {uart_name} RX ({p_ident}) [Net: {pin.net}] routed to external header/connector {target}.",
                            details={"bus_type": "UART", "mcu_pin": p_ident, "target": target, "net": pin.net, "pullup_protection": pull_prot}
                        ))

        # CAN Checks
        for can_name, can_spec in profile.peripherals.items():
            if not can_name.startswith("CAN"):
                continue

            can_tx_pins = [str(p) for p in can_spec.get("tx", [])]
            can_rx_pins = [str(p) for p in can_spec.get("rx", [])]

            for pin in mcu_comp.pins.values():
                p_ident = pin.name if (pin.name and pin.name != pin.number) else f"Pin {pin.number}"
                if not pin.net:
                    continue

                if p_ident in can_rx_pins or pin.number in can_rx_pins or pin.name in can_rx_pins:
                    audited_pins.add(pin.number)
                    for other_p in graph.get_connected_pins(pin.net):
                        if other_p.component_ref == mcu_comp.ref_des:
                            continue
                        other_comp = graph.get_component(other_p.component_ref)
                        if not other_comp:
                            continue
                        other_name = other_p.name.upper()

                        if other_name in ("TXD", "TX", "CTX", "CANTX"):
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.FAIL,
                                message=f"Swapped CAN transceiver pins: MCU {can_name} RX ({p_ident}) is connected to TXD ({other_p.name}) on transceiver {other_comp.ref_des}! MCU CAN_RX must connect to transceiver RXD output.",
                                details={"bus_type": "CAN", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                        elif other_name in ("RXD", "RX", "CRX", "CANRX"):
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.PASS,
                                message=f"Proper CAN transceiver wiring: MCU {can_name} RX ({p_ident}) connected to RXD ({other_p.name}) on {other_comp.ref_des}.",
                                details={"bus_type": "CAN", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))

                elif p_ident in can_tx_pins or pin.number in can_tx_pins or pin.name in can_tx_pins:
                    audited_pins.add(pin.number)
                    for other_p in graph.get_connected_pins(pin.net):
                        if other_p.component_ref == mcu_comp.ref_des:
                            continue
                        other_comp = graph.get_component(other_p.component_ref)
                        if not other_comp:
                            continue
                        other_name = other_p.name.upper()

                        if other_name in ("RXD", "RX", "CRX", "CANRX"):
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.FAIL,
                                message=f"Swapped CAN transceiver pins: MCU {can_name} TX ({p_ident}) is connected to RXD ({other_p.name}) on transceiver {other_comp.ref_des}! MCU CAN_TX must connect to transceiver TXD input.",
                                details={"bus_type": "CAN", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))
                        elif other_name in ("TXD", "TX", "CTX", "CANTX"):
                            results.append(CheckResult(
                                ref_des=mcu_comp.ref_des,
                                component_type="MCU_BUS",
                                status=CheckStatus.PASS,
                                message=f"Proper CAN transceiver wiring: MCU {can_name} TX ({p_ident}) connected to TXD ({other_p.name}) on {other_comp.ref_des}.",
                                details={"bus_type": "CAN", "mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net, "pullup_protection": get_net_pull_and_protection(pin.net)}
                            ))

    # -------------------------------------------------------------
    # 2. Dynamic Bus Detection (SWD, I2C, SPI, UART)
    # -------------------------------------------------------------
    for pin in mcu_comp.pins.values():
        if pin.number in audited_pins:
            continue

        net_name = pin.net
        if not net_name:
            continue
        net_upper = net_name.upper()

        # Skip power, ground, and crystal nets
        if net_upper in ("GND", "AGND", "VSS", "VSSA", "3V3", "5V", "+3V3", "+5V", "VCC", "VDD", "VDDA", "VBAT", "NRST", "RESET"):
            continue
        if any(x in net_upper for x in ["OSC_IN", "OSC_OUT", "OSC32", "XTAL"]):
            continue

        p_ident = pin.name if (pin.name and pin.name != pin.number) else f"Pin {pin.number}"

        # 2a. SWD / Debug Interface (SWDIO / SWCLK)
        if any(k in net_upper for k in ["SWDIO", "SWCLK", "SWD", "TMS", "TCK", "PSWDIO", "PSWCLK"]):
            role = "SWD Data (SWDIO)" if any(d in net_upper for d in ["DIO", "TMS"]) else "SWD Clock (SWCLK)"
            pull_prot = get_net_pull_and_protection(net_name)
            target = get_target_summary(net_name)

            results.append(CheckResult(
                ref_des=mcu_comp.ref_des,
                component_type="MCU_BUS",
                status=CheckStatus.PASS,
                message=f"{role} on {p_ident} [Net: {net_name}] -> {target}.",
                details={
                    "bus_type": "SWD",
                    "mcu_pin": p_ident,
                    "net": net_name,
                    "target": target,
                    "pullup_protection": pull_prot
                }
            ))
            audited_pins.add(pin.number)

        # 2b. I2C Bus Detection (SCL / SDA)
        elif "SCL" in net_upper or "SDA" in net_upper or "I2C" in net_upper:
            is_scl = "SCL" in net_upper
            is_sda = "SDA" in net_upper
            bus_role = "I2C Clock (SCL)" if is_scl else ("I2C Data (SDA)" if is_sda else "I2C Bus")
            pull_prot = get_net_pull_and_protection(net_name)
            target = get_target_summary(net_name)

            has_pullup = "Pull-up" in pull_prot
            status = CheckStatus.PASS if has_pullup else CheckStatus.WARN
            note = "Pull-up present and routed to slave devices." if has_pullup else "Warning: No external pull-up detected!"

            results.append(CheckResult(
                ref_des=mcu_comp.ref_des,
                component_type="MCU_BUS",
                status=status,
                message=f"{bus_role} on {p_ident} [Net: {net_name}] -> {target}. {note}",
                details={
                    "bus_type": "I2C",
                    "mcu_pin": p_ident,
                    "net": net_name,
                    "target": target,
                    "pullup_protection": pull_prot
                }
            ))
            audited_pins.add(pin.number)

        # 2c. SPI Bus Detection (SCK / MISO / MOSI / NSS / CS)
        elif any(k in net_upper for k in ["SCK", "CLK", "MISO", "MOSI", "NSS", "CS", "SPI"]):
            if "SCK" in net_upper or "CLK" in net_upper:
                role = "SPI Clock (SCK)"
            elif "MISO" in net_upper:
                role = "SPI MISO"
            elif "MOSI" in net_upper:
                role = "SPI MOSI"
            elif "NSS" in net_upper or "CS" in net_upper:
                role = "SPI Chip Select (NSS/CS)"
            else:
                role = "SPI Control Line"

            pull_prot = get_net_pull_and_protection(net_name)
            target = get_target_summary(net_name)

            results.append(CheckResult(
                ref_des=mcu_comp.ref_des,
                component_type="MCU_BUS",
                status=CheckStatus.PASS,
                message=f"{role} on {p_ident} [Net: {net_name}] -> {target}.",
                details={
                    "bus_type": "SPI",
                    "mcu_pin": p_ident,
                    "net": net_name,
                    "target": target,
                    "pullup_protection": pull_prot
                }
            ))
            audited_pins.add(pin.number)

        # 2d. UART / Serial Detection (TX / RX / PTX / PRX)
        elif any(k in net_upper for k in ["TX", "RX", "UART", "USART"]):
            is_tx = "TX" in net_upper
            role = "UART Transmit (TX)" if is_tx else "UART Receive (RX)"
            pull_prot = get_net_pull_and_protection(net_name)
            target = get_target_summary(net_name)

            results.append(CheckResult(
                ref_des=mcu_comp.ref_des,
                component_type="MCU_BUS",
                status=CheckStatus.PASS,
                message=f"{role} on {p_ident} [Net: {net_name}] -> {target}.",
                details={
                    "bus_type": "UART",
                    "mcu_pin": p_ident,
                    "net": net_name,
                    "target": target,
                    "pullup_protection": pull_prot
                }
            ))
            audited_pins.add(pin.number)

    return results
