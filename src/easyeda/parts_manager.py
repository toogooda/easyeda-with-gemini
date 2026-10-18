from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass
class PartProfile:
    lcsc_part: str
    part_number: str
    part_type: str = "IC"  # MCU, I2C_SENSOR, REGULATOR, TRANSCEIVER, etc.
    voltage_limits: Dict[str, float] = field(default_factory=dict)
    power_pins: List[Dict[str, str]] = field(default_factory=list)
    ground_pins: List[str] = field(default_factory=list)
    crystals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reset_pin: Dict[str, Any] = field(default_factory=dict)
    boot_strapping: List[Dict[str, str]] = field(default_factory=list)
    i2c_addresses: Dict[str, str] = field(default_factory=dict)
    peripherals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pin_map: Dict[str, str] = field(default_factory=dict)  # e.g. {"1": "CATHODE", "2": "ANODE"} or {"1": "BASE", "2": "COLLECTOR", "3": "EMITTER"}
    package: str = ""
    address_pins: List[str] = field(default_factory=list)  # e.g. ["A1", "A0"] or ["A2", "A1", "A0"]
    address_base: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Avoid duplicating raw_data if empty
        if not self.raw_data:
            data.pop("raw_data", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PartProfile:
        return cls(
            lcsc_part=data.get("lcsc_part", ""),
            part_number=data.get("part_number", ""),
            part_type=data.get("part_type") or data.get("type", "IC"),
            voltage_limits=data.get("voltage_limits", {}),
            power_pins=data.get("power_pins", []),
            ground_pins=data.get("ground_pins", []),
            crystals=data.get("crystals", {}),
            reset_pin=data.get("reset_pin", {}),
            boot_strapping=data.get("boot_strapping", []),
            i2c_addresses=data.get("i2c_addresses") or data.get("address_strapping", {}),
            peripherals=data.get("peripherals", {}),
            pin_map=data.get("pin_map") or data.get("pins", {}),
            package=data.get("package", ""),
            address_pins=data.get("address_pins", []),
            address_base=data.get("address_base", ""),
            raw_data=data
        )


class PartsManager:
    """Manages the local parts cache directory (./parts_cache)."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        elif Path("parts_cache").exists():
            self.cache_dir = Path("parts_cache")
        else:
            self.cache_dir = Path(__file__).resolve().parents[2] / "parts_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, lcsc_id: str) -> Path:
        clean_id = lcsc_id.strip().upper()
        return self.cache_dir / f"{clean_id}.json"

    def is_cached(self, lcsc_id: str) -> bool:
        return self._get_path(lcsc_id).exists()

    def get_profile(self, lcsc_id: str) -> Optional[PartProfile]:
        path = self._get_path(lcsc_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PartProfile.from_dict(data)
        except Exception:
            return None

    def find_profile(self, lcsc_id: str = "", part_number: str = "") -> Optional[PartProfile]:
        """Finds a profile by LCSC ID first, or by part_number substring/exact match."""
        if lcsc_id:
            p = self.get_profile(lcsc_id)
            if p:
                return p
        if not part_number:
            return None
        pn_clean = part_number.strip().upper()
        # Scan cached profiles
        for f in self.cache_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                stored_pn = (data.get("part_number") or "").upper()
                if stored_pn and (stored_pn == pn_clean or pn_clean in stored_pn or stored_pn in pn_clean):
                    return PartProfile.from_dict(data)
            except Exception:
                continue
        return None

    def save_profile(self, profile: Union[PartProfile, Dict[str, Any]]) -> Path:
        if isinstance(profile, dict):
            profile = PartProfile.from_dict(profile)
        path = self._get_path(profile.lcsc_part)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2)
        return path

    def list_cached_parts(self) -> List[str]:
        return [p.stem for p in self.cache_dir.glob("*.json")]
