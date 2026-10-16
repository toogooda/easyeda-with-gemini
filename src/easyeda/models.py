from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import re

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
