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
            raw_data=data
        )


class PartsManager:
    """Manages the local parts cache directory (./parts_cache)."""

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path("parts_cache")
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

    def save_profile(self, profile: PartProfile) -> Path:
        path = self._get_path(profile.lcsc_part)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2)
        return path

    def list_cached_parts(self) -> List[str]:
        return [p.stem for p in self.cache_dir.glob("*.json")]
