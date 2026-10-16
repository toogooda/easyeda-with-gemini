from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
import re


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"



@dataclass
class CheckResult:
    ref_des: str
    component_type: str
    status: CheckStatus
    message: str
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def badge(self) -> str:
        if self.status == CheckStatus.PASS:
            return "🟢 PASS"
        elif self.status == CheckStatus.WARN:
            return "🟡 WARN"
        else:
            return "🔴 FAIL"


def parse_resistance(val_str: str) -> Optional[float]:
    """Parses standard resistance strings (e.g. 10k, 4k7, 100R, 220Ω, 1M) to ohms."""
    if not val_str:
        return None
    cleaned = val_str.strip().replace("Ω", "").replace("ohm", "").replace("Ohm", "").strip()

    # Match 4k7 style
    m_mid = re.match(r"^(\d+)[kK](\d+)$", cleaned)
    if m_mid:
        return float(f"{m_mid.group(1)}.{m_mid.group(2)}") * 1e3

    m_mid_r = re.match(r"^(\d+)[rR](\d+)$", cleaned)
    if m_mid_r:
        return float(f"{m_mid_r.group(1)}.{m_mid_r.group(2)}")

    m_mid_m = re.match(r"^(\d+)[mM](\d+)$", cleaned)
    if m_mid_m:
        return float(f"{m_mid_m.group(1)}.{m_mid_m.group(2)}") * 1e6

    # Match standard numbers with multiplier suffix
    m = re.match(r"^([0-9.]+)\s*([kKmM]?[rR]?)$", cleaned)
    if not m:
        return None

    try:
        val = float(m.group(1))
        unit = m.group(2).upper()
        if "K" in unit:
            return val * 1e3
        elif "M" in unit:
            return val * 1e6
        else:
            return val
    except ValueError:
        return None


def parse_capacitance(val_str: str) -> Optional[float]:
    """Parses standard capacitance strings (e.g. 100nF, 1uF, 22pF, 4.7uF) to Farads."""
    if not val_str:
        return None
    cleaned = val_str.strip().replace("F", "").replace("f", "").strip()
    m = re.match(r"^([0-9.]+)\s*([pnumµk]?)$", cleaned, re.IGNORECASE)
    if not m:
        return None
    try:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "p":
            return val * 1e-12
        elif unit == "n":
            return val * 1e-9
        elif unit in ("u", "µ"):
            return val * 1e-6
        elif unit == "m":
            return val * 1e-3
        else:
            return val
    except ValueError:
        return None


@dataclass
class Pin:
    number: str
    name: str
    net: str
    component_ref: str = ""

    def __repr__(self) -> str:
        return f"Pin({self.component_ref}.{self.number} [{self.name}] -> {self.net})"



@dataclass
class Component:
    ref_des: str
    value: str
    package: str = ""
    lcsc_id: Optional[str] = None
    datasheet: Optional[str] = None
    comp_type: str = ""
    pins: Dict[str, Pin] = field(default_factory=dict)

    def add_pin(self, pin: Pin) -> None:
        pin.component_ref = self.ref_des
        self.pins[pin.number] = pin

    def get_pin(self, number: str) -> Optional[Pin]:
        return self.pins.get(str(number))

    def get_pin_by_name(self, name: str) -> Optional[Pin]:
        target = name.upper()
        for p in self.pins.values():
            if p.name.upper() == target:
                return p
        return None

    def find_pin_matching(self, pattern: str) -> Optional[Pin]:
        regex = re.compile(pattern, re.IGNORECASE)
        for p in self.pins.values():
            if regex.search(p.name) or regex.search(p.number):
                return p
        return None


@dataclass
class Net:
    name: str
    pins: List[Pin] = field(default_factory=list)

    @property
    def is_ground(self) -> bool:
        norm = self.name.upper()
        return norm in ("GND", "AGND", "PGND", "DGND", "VSS", "VSSA", "0V") or "GND" in norm

    @property
    def is_power(self) -> bool:
        norm = self.name.upper()
        if self.is_ground:
            return False
        return (
            norm.startswith("+")
            or norm.startswith("VCC")
            or norm.startswith("VDD")
            or norm.startswith("VIN")
            or norm.startswith("VBUS")
            or norm.startswith("VBAT")
            or norm.endswith("V")
        )

    def add_pin(self, pin: Pin) -> None:
        if pin not in self.pins:
            self.pins.append(pin)


@dataclass
class SchematicGraph:
    project_name: str = ""
    version: str = "1.0"
    components: Dict[str, Component] = field(default_factory=dict)
    nets: Dict[str, Net] = field(default_factory=dict)

    def add_component(self, comp: Component) -> None:
        self.components[comp.ref_des] = comp
        for pin in comp.pins.values():
            self._register_pin_in_net(pin)

    def _register_pin_in_net(self, pin: Pin) -> None:
        if not pin.net:
            return
        if pin.net not in self.nets:
            self.nets[pin.net] = Net(name=pin.net)
        self.nets[pin.net].add_pin(pin)

    def get_component(self, ref_des: str) -> Optional[Component]:
        return self.components.get(ref_des)

    def get_net(self, net_name: str) -> Optional[Net]:
        return self.nets.get(net_name)

    def get_connected_pins(self, net_name: str) -> List[Pin]:
        net = self.get_net(net_name)
        return net.pins if net else []

    def get_components_by_type(self, type_keyword: str) -> List[Component]:
        keyword = type_keyword.upper()
        results = []
        for c in self.components.values():
            if keyword in c.comp_type.upper() or c.ref_des.upper().startswith(keyword):
                results.append(c)
        return results

    def get_components_by_prefix(self, prefix: str) -> List[Component]:
        prefix_up = prefix.upper()
        return [c for c in self.components.values() if re.match(f"^{prefix_up}\\d+", c.ref_des, re.IGNORECASE)]

    def get_single_pin_nets(self) -> List[str]:
        return [net.name for net in self.nets.values() if len(net.pins) == 1]

    def find_resistor_between(self, net_a: str, net_b: str) -> Optional[Component]:
        resistors = self.get_components_by_prefix("R")
        for r in resistors:
            pin_nets = {p.net for p in r.pins.values()}
            if net_a in pin_nets and net_b in pin_nets:
                return r
        return None

    def find_capacitors_between(self, net_a: str, net_b: str) -> List[Component]:
        caps = self.get_components_by_prefix("C")
        matched = []
        for c in caps:
            pin_nets = {p.net for p in c.pins.values()}
            if net_a in pin_nets and net_b in pin_nets:
                matched.append(c)
        return matched
