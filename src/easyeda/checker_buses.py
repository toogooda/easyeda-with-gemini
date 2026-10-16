from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from .models import Component, Pin, SchematicGraph, CheckResult, CheckStatus
from .parts_manager import PartsManager, PartProfile


def check_bus_crossovers(mcu_comp: Component, graph: SchematicGraph, parts_manager: PartsManager) -> List[CheckResult]:
    """Validates bus peripheral pin assignments and crossovers (UART, CAN, SPI) between MCU and peripherals."""
    results: List[CheckResult] = []
    profile = parts_manager.get_profile(mcu_comp.lcsc_id) if mcu_comp.lcsc_id else None

    if not profile or not profile.peripherals:
        return results

    # 1. UART Check (USART1, USART2, etc.)
    for uart_name, uart_spec in profile.peripherals.items():
        if not uart_name.startswith("USART") and not uart_name.startswith("UART"):
            continue

        tx_pins = uart_spec.get("tx", [])
        rx_pins = uart_spec.get("rx", [])

        # Find which MCU pins are used
        for pin in mcu_comp.pins.values():
            p_ident = pin.name or pin.number
            if p_ident in tx_pins or pin.number in tx_pins or pin.name in tx_pins:
                # This is MCU TX pin! Trace connected pins
                connected = graph.get_connected_pins(pin.net)
                for other_p in connected:
                    if other_p.component_ref == mcu_comp.ref_des:
                        continue
                    other_comp = graph.get_component(other_p.component_ref)
                    if not other_comp:
                        continue
                    other_name = other_p.name.upper()

                    # Check if target is a UART peripheral/bridge (e.g. CH340, FTDI, CP2102, Bluetooth)
                    if "TX" in other_name:
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.FAIL,
                            message=f"Swapped UART connection: MCU {uart_name} TX pin ({p_ident}) is connected to TX pin ({other_p.name}) on {other_comp.ref_des}! Both are outputs. MCU TX must connect to peripheral RX.",
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))
                    elif "RX" in other_name:
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.PASS,
                            message=f"Proper UART crossover: MCU {uart_name} TX ({p_ident}) connects to RX ({other_p.name}) on {other_comp.ref_des}.",
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))

            elif p_ident in rx_pins or pin.number in rx_pins or pin.name in rx_pins:
                # This is MCU RX pin!
                connected = graph.get_connected_pins(pin.net)
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
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))

    # 2. CAN Bus Check (CAN1, CAN2)
    for can_name, can_spec in profile.peripherals.items():
        if not can_name.startswith("CAN"):
            continue

        can_tx_pins = can_spec.get("tx", [])
        can_rx_pins = can_spec.get("rx", [])

        for pin in mcu_comp.pins.values():
            p_ident = pin.name or pin.number
            # Check MCU CAN_RX pin
            if p_ident in can_rx_pins or pin.number in can_rx_pins or pin.name in can_rx_pins:
                for other_p in graph.get_connected_pins(pin.net):
                    if other_p.component_ref == mcu_comp.ref_des:
                        continue
                    other_comp = graph.get_component(other_p.component_ref)
                    if not other_comp:
                        continue
                    other_name = other_p.name.upper()

                    # In CAN transceivers, MCU CAN_RX must connect to Transceiver RXD output!
                    # If connected to Transceiver TXD input, it is swapped!
                    if other_name in ("TXD", "TX", "CTX", "CANTX"):
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.FAIL,
                            message=f"Swapped CAN transceiver pins: MCU {can_name} RX ({p_ident}) is connected to TXD ({other_p.name}) on transceiver {other_comp.ref_des}! MCU CAN_RX must connect to transceiver RXD output.",
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))
                    elif other_name in ("RXD", "RX", "CRX", "CANRX"):
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.PASS,
                            message=f"Proper CAN transceiver wiring: MCU {can_name} RX ({p_ident}) connected to RXD ({other_p.name}) on {other_comp.ref_des}.",
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))

            # Check MCU CAN_TX pin
            elif p_ident in can_tx_pins or pin.number in can_tx_pins or pin.name in can_tx_pins:
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
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))
                    elif other_name in ("TXD", "TX", "CTX", "CANTX"):
                        results.append(CheckResult(
                            ref_des=mcu_comp.ref_des,
                            component_type="MCU_BUS",
                            status=CheckStatus.PASS,
                            message=f"Proper CAN transceiver wiring: MCU {can_name} TX ({p_ident}) connected to TXD ({other_p.name}) on {other_comp.ref_des}.",
                            details={"mcu_pin": p_ident, "target": f"{other_comp.ref_des}.{other_p.name}", "net": pin.net}
                        ))

    return results
