from __future__ import annotations
import csv
from pathlib import Path
from typing import Dict, List, Optional, Union
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from .models import SchematicGraph, Component


def _parse_xlsx_bom(file_path: Path) -> List[List[str]]:
    """Reads all rows from an Excel .xlsx sheet without third-party dependencies."""
    with zipfile.ZipFile(file_path, "r") as z:
        # Read shared strings
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared_strings = [t.text or "" for t in tree.findall(".//{*}t")]

        # Read sheet 1
        sheet_data = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row_elem in sheet_data.findall(".//{*}row"):
            row = []
            for c in row_elem.findall("{*}c"):
                v = c.find("{*}v")
                if v is not None and v.text:
                    if c.attrib.get("t") == "s":
                        idx = int(v.text)
                        row.append(shared_strings[idx] if idx < len(shared_strings) else "")
                    else:
                        row.append(v.text)
                else:
                    # Inline string fallback
                    t = c.find(".//{*}t")
                    row.append(t.text if t is not None and t.text else "")
            rows.append(row)
        return rows


def parse_bom(file_path: Union[str, Path]) -> Dict[str, Dict[str, str]]:
    """Parses an EasyEDA BOM (Excel .xlsx, CSV file, or raw CSV/TSV text) into a per-designator metadata dictionary."""
    rows: List[List[str]] = []
    is_file = False
    path = Path()
    try:
        if isinstance(file_path, Path) or (isinstance(file_path, str) and "\n" not in file_path and len(file_path) < 260):
            path = Path(file_path)
            is_file = path.is_file()
    except Exception:
        is_file = False

    if is_file:
        if path.suffix.lower() == ".xlsx":
            rows = _parse_xlsx_bom(path)
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = [ln for ln in content.splitlines() if ln.strip()]
                if lines:
                    delim = "\t" if "\t" in lines[0] else ","
                    rows = list(csv.reader(lines, delimiter=delim))
    elif isinstance(file_path, str) and ("\n" in file_path or "\t" in file_path):
        lines = [ln for ln in file_path.splitlines() if ln.strip()]
        if lines:
            delim = "\t" if "\t" in lines[0] else ","
            rows = list(csv.reader(lines, delimiter=delim))
    else:
        raise FileNotFoundError(f"BOM file not found: {file_path}")

    if not rows:
        return {}

    # Identify header indices
    header = [h.strip() for h in rows[0]]
    header_lower = [h.lower() for h in header]

    def find_col(*candidates: str) -> Optional[int]:
        for cand in candidates:
            for idx, col in enumerate(header_lower):
                if cand in col:
                    return idx
        return None

    des_col = find_col("designator")
    lcsc_col = find_col("supplier part", "lcsc", "part number", "supplier")
    sheet_col = find_col("datasheet", "link", "url")
    val_col = find_col("value")
    comment_col = find_col("comment")
    mpn_col = find_col("manufacturer part", "device", "name")
    fp_col = find_col("footprint", "package")

    results: Dict[str, Dict[str, str]] = {}

    for row in rows[1:]:
        if not row or (des_col is not None and des_col >= len(row)):
            continue

        raw_des = row[des_col].strip() if des_col is not None and des_col < len(row) else ""
        if not raw_des:
            continue

        lcsc_id = row[lcsc_col].strip() if lcsc_col is not None and lcsc_col < len(row) else ""
        datasheet_url = row[sheet_col].strip() if sheet_col is not None and sheet_col < len(row) else ""
        value = row[val_col].strip() if val_col is not None and val_col < len(row) else ""
        if not value and comment_col is not None and comment_col < len(row):
            value = row[comment_col].strip()
        if not value and mpn_col is not None and mpn_col < len(row):
            value = row[mpn_col].strip()
        footprint = row[fp_col].strip() if fp_col is not None and fp_col < len(row) else ""

        # Handle multiple comma/space-separated designators in one row (e.g. C1,C2,C3)
        clean_designators = [d.strip() for d in raw_des.replace(" ", ",").split(",") if d.strip()]
        for des in clean_designators:
            results[des] = {
                "ref_des": des,
                "lcsc_id": lcsc_id,
                "datasheet": datasheet_url,
                "value": value,
                "footprint": footprint
            }

    return results


def merge_bom_into_graph(graph: SchematicGraph, bom_data: Dict[str, Dict[str, str]]) -> None:
    """Enriches all components in a SchematicGraph with BOM metadata (LCSC ID, datasheet link)."""
    from .parser import infer_component_type

    for ref_des, meta in bom_data.items():
        comp = graph.get_component(ref_des)
        if comp:
            if meta.get("lcsc_id"):
                comp.lcsc_id = meta["lcsc_id"]
            if meta.get("datasheet"):
                comp.datasheet = meta["datasheet"]
            if (not comp.value or comp.value == "{Value}") and meta.get("value"):
                comp.value = meta["value"]
            fp = meta.get("footprint", "")
            if not comp.package and fp and fp != "[object Object]":
                comp.package = fp
            # Re-evaluate component type with newly acquired value and package
            new_type = infer_component_type(comp.ref_des, comp.value, comp.lcsc_id, comp.package)
            if new_type != "UNKNOWN" and (comp.comp_type in ("UNKNOWN", "IC") or new_type != "IC"):
                comp.comp_type = new_type


def download_datasheet(url: str, lcsc_id: str, dest_dir: Union[str, Path] = "datasheets") -> Optional[Path]:
    """Downloads a datasheet PDF via URL into datasheets/<lcsc_id>.pdf."""
    if not url or not url.startswith("http"):
        return None

    target_dir = Path(dest_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{lcsc_id.upper()}.pdf"

    if target_file.exists():
        return target_file

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=15) as response, open(target_file, "wb") as out:
            out.write(response.read())
        return target_file
    except Exception:
        return None
