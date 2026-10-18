from __future__ import annotations
import json
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import SchematicGraph
from .parser import parse_schematic_json, parse_protel_netlist
from .datasheet_extractor import parse_bom, merge_bom_into_graph
from .parts_manager import PartsManager
from .reporter import generate_schematic_report

# Global live state & on-demand pull synchronization
_LAST_LIVE_GRAPH: Optional[SchematicGraph] = None
_LAST_LIVE_REPORT: Optional[str] = None
_CACHE_REPORT_FILE = Path(__file__).resolve().parents[2] / "parts_cache" / ".last_live_report.md"
_CACHE_PAYLOAD_FILE = Path(__file__).resolve().parents[2] / "parts_cache" / ".last_raw_payload.json"

_PULL_LOCK = threading.Lock()
_PULL_REQUESTED: bool = False
_PULL_COMPLETED_EVENT = threading.Event()
_LAST_POLL_TIME: float = 0.0
_ACTIVE_SERVER_PORT: Optional[int] = None


def _build_graph_from_payload(raw_text: str) -> SchematicGraph:
    """Parses raw payload text (JSON or Protel) into a SchematicGraph with BOM enrichment."""
    stripped = raw_text.strip()
    if stripped.startswith("{") or stripped.startswith("[{"):
        data = json.loads(stripped)
        if isinstance(data, dict) and "netlist_text" in data:
            graph = parse_protel_netlist(data["netlist_text"])
            if "project_name" in data:
                graph.project_name = data["project_name"]
            graph.source_path = f"EasyEDA Pro Live Bridge ({data.get('project_name', 'Active Session')})"
            if "bom_data" in data and isinstance(data["bom_data"], dict):
                merge_bom_into_graph(graph, data["bom_data"])
                graph.bom_path = "Live Session BOM"
            if "bom_csv" in data and isinstance(data["bom_csv"], str) and data["bom_csv"].strip():
                try:
                    merge_bom_into_graph(graph, parse_bom(data["bom_csv"]))
                    graph.bom_path = "Live Session BOM"
                except Exception:
                    pass
        else:
            graph = parse_schematic_json(data)
            graph.source_path = "EasyEDA Pro Live Bridge (JSON Payload)"
    else:
        graph = parse_protel_netlist(stripped)
        graph.source_path = "EasyEDA Pro Live Bridge (Protel Wirelist)"
    return graph


def reevaluate_live_report(pm: Optional[PartsManager] = None) -> Optional[str]:
    """Re-evaluates and returns the schematic report using the active live graph or cached payload and current PartsManager."""
    global _LAST_LIVE_GRAPH, _LAST_LIVE_REPORT
    if pm is None:
        pm = PartsManager()

    if _LAST_LIVE_GRAPH is None and _CACHE_PAYLOAD_FILE.exists():
        try:
            raw_text = _CACHE_PAYLOAD_FILE.read_text(encoding="utf-8")
            if raw_text.strip():
                _LAST_LIVE_GRAPH = _build_graph_from_payload(raw_text)
        except Exception:
            pass

    if _LAST_LIVE_GRAPH is not None:
        report = generate_schematic_report(_LAST_LIVE_GRAPH, pm)
        _LAST_LIVE_REPORT = report
        try:
            _CACHE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_REPORT_FILE.write_text(report, encoding="utf-8")
        except Exception:
            pass
        return report

    if _LAST_LIVE_REPORT:
        return _LAST_LIVE_REPORT
    if _CACHE_REPORT_FILE.exists():
        return _CACHE_REPORT_FILE.read_text(encoding="utf-8")
    return None



def _wait_for_in_process_pull(timeout: float = 4.0) -> bool:
    """Flags a pull request for the polling EasyEDA Pro extension and waits for /review."""
    global _PULL_REQUESTED
    with _PULL_LOCK:
        _PULL_COMPLETED_EVENT.clear()
        _PULL_REQUESTED = True
    completed = _PULL_COMPLETED_EVENT.wait(timeout=timeout)
    with _PULL_LOCK:
        _PULL_REQUESTED = False
    return completed


def ensure_live_receiver_daemon(port: int = 8765) -> bool:
    """Ensures the EasyEDA live receiver is listening on port 8765. If not, spawns it as a background daemon."""
    import socket
    import subprocess
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            return True

    root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, "-m", "src.easyeda.server", "--live"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        subprocess.Popen(cmd, cwd=str(root), creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
    except Exception:
        pass
    return True


def request_live_pull(timeout: float = 4.0, port: int = 8765) -> Optional[str]:
    """
    Initiates an on-demand schematic pull from EasyEDA Pro.
    Works both in-process (when this process owns the live receiver) and cross-process (via /trigger_pull).
    """
    global _LAST_LIVE_REPORT
    target_port = _ACTIVE_SERVER_PORT if _ACTIVE_SERVER_PORT is not None else port
    ensure_live_receiver_daemon(port=target_port)
    if _ACTIVE_SERVER_PORT == target_port:
        if _LAST_POLL_TIME > 0 and (time.time() - _LAST_POLL_TIME) < 15.0:
            _wait_for_in_process_pull(timeout=timeout)
        return _LAST_LIVE_REPORT

    # Cross-process: ask the running live receiver daemon on `target_port` to trigger a pull
    try:
        url = f"http://127.0.0.1:{target_port}/trigger_pull?timeout={timeout}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout + 2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if data.get("report"):
                    _LAST_LIVE_REPORT = data["report"]
                    return _LAST_LIVE_REPORT
    except Exception:
        pass
    return None


class EasyEDALiveHandler(BaseHTTPRequestHandler):
    """Bidirectional HTTP bridge for the EasyEDA Pro extension over localhost:8765."""

    def _read_body(self) -> str:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer_encoding:
            chunks: List[bytes] = []
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                line_str = line.strip().split(b";")[0]
                if not line_str:
                    continue
                chunk_len = int(line_str, 16)
                if chunk_len == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(chunk_len))
                self.rfile.readline()
            return b"".join(chunks).decode("utf-8", errors="replace")

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            return self.rfile.read(content_length).decode("utf-8", errors="replace")
        return ""

    def do_GET(self):
        global _PULL_REQUESTED, _LAST_POLL_TIME
        if self.path.startswith("/poll"):
            _LAST_POLL_TIME = time.time()
            with _PULL_LOCK:
                should_pull = _PULL_REQUESTED
                _PULL_REQUESTED = False
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            cmd = "pull_schematic" if should_pull else "idle"
            self.wfile.write(json.dumps({"command": cmd}).encode("utf-8"))
        elif self.path.startswith("/trigger_pull"):
            wait_sec = 4.0 if (_LAST_POLL_TIME > 0 and (time.time() - _LAST_POLL_TIME) < 15.0) else 1.5
            pulled = _wait_for_in_process_pull(timeout=wait_sec)
            report = reevaluate_live_report()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "success" if pulled else "cached",
                "pulled_live": pulled,
                "report": report or ""
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global _LAST_LIVE_GRAPH, _LAST_LIVE_REPORT
        if self.path.startswith("/review"):
            post_data = self._read_body()
            try:
                try:
                    _CACHE_PAYLOAD_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _CACHE_PAYLOAD_FILE.write_text(post_data, encoding="utf-8")
                except Exception:
                    pass
                stripped = post_data.strip()
                if not stripped:
                    raise ValueError("Received empty schematic payload from client")
                graph = _build_graph_from_payload(stripped)
                _LAST_LIVE_GRAPH = graph
                pm = PartsManager()
                report = reevaluate_live_report(pm)
                _PULL_COMPLETED_EVENT.set()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                response = {
                    "status": "success",
                    "components_count": len(graph.components),
                    "nets_count": len(graph.nets),
                    "report_preview": (report or "")[:500]
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging to stderr
        pass


def start_live_receiver(port: int = 8765) -> HTTPServer:
    """Starts the background threaded HTTP receiver for EasyEDA Pro live extensions."""
    global _ACTIVE_SERVER_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), EasyEDALiveHandler)
    _ACTIVE_SERVER_PORT = port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ==========================================
# MCP Tool Functions (Callable by Antigravity)
# ==========================================

def audit_schematic(schematic_path: Optional[str] = None, bom_path: Optional[str] = None) -> str:
    """
    Audits an EasyEDA schematic and returns a rendered Markdown report.
    If schematic_path is omitted or 'live', initiates an on-demand live pull from EasyEDA Pro.
    """
    global _LAST_LIVE_REPORT
    pm = PartsManager()

    if not schematic_path or schematic_path.lower() == "live":
        pulled_report = request_live_pull(timeout=4.0)
        report = reevaluate_live_report(pm)
        if report:
            return report
        return "No live schematic received yet from EasyEDA Pro. Make sure EasyEDA Pro is open with the Antigravity extension enabled, or specify a file path."

    path = Path(schematic_path)
    if not path.exists():
        return f"Error: Schematic file not found: {schematic_path}"

    if path.suffix.lower() in (".tel", ".net"):
        graph = parse_protel_netlist(path)
    else:
        graph = parse_schematic_json(path)

    graph.source_path = str(path)
    if bom_path and Path(bom_path).exists():
        bom_data = parse_bom(bom_path)
        merge_bom_into_graph(graph, bom_data)
        graph.bom_path = str(bom_path)

    report = generate_schematic_report(graph, pm)
    return report


def get_part_profile(lcsc_id: str) -> Dict[str, Any]:
    """Retrieves the cached electrical profile for a part by LCSC ID."""
    pm = PartsManager()
    profile = pm.get_profile(lcsc_id)
    if profile:
        return profile.to_dict()
    return {"status": "not_found", "lcsc_id": lcsc_id}


def list_cached_parts() -> List[str]:
    """Returns a list of all part IDs currently cached in the JIT part library."""
    pm = PartsManager()
    return pm.list_cached_parts()


def save_part_profile(profile_data: Union[Dict[str, Any], str]) -> Dict[str, Any]:
    """Saves or updates a component profile in the local parts cache."""
    pm = PartsManager()
    if isinstance(profile_data, str):
        try:
            profile_data = json.loads(profile_data)
        except Exception as e:
            return {"status": "error", "message": f"Invalid JSON profile data: {e}"}
    if not isinstance(profile_data, dict):
        return {"status": "error", "message": "profile_data must be a dictionary or JSON object"}
    lcsc = profile_data.get("lcsc_part") or profile_data.get("lcsc_id")
    if not lcsc:
        return {"status": "error", "message": "Missing required field 'lcsc_part' (or 'lcsc_id')"}
    profile_data["lcsc_part"] = str(lcsc).strip().upper()
    from .parts_manager import PartProfile
    prof = PartProfile.from_dict(profile_data)
    path = pm.save_profile(prof)
    return {"status": "success", "lcsc_id": prof.lcsc_part, "path": str(path)}


def get_datasheet(lcsc_id: str, url: Optional[str] = None) -> Dict[str, Any]:
    """Downloads and caches a datasheet PDF locally if URL provided, returning cached path."""
    dest = Path(__file__).resolve().parents[2] / "datasheets"
    clean_id = lcsc_id.strip().upper()
    if url:
        from .datasheet_extractor import download_datasheet
        cached = download_datasheet(url, clean_id, dest_dir=dest)
        if cached and cached.exists():
            return {"status": "success", "lcsc_id": clean_id, "file_path": str(cached)}
    local_pdf = dest / f"{clean_id}.pdf"
    if local_pdf.exists():
        return {"status": "success", "lcsc_id": clean_id, "file_path": str(local_pdf)}
    return {"status": "not_found", "lcsc_id": clean_id, "message": "Datasheet not cached and no valid download URL supplied"}


# ==========================================
# Standard MCP JSON-RPC Stdio Server Loop
# ==========================================

TOOLS = [
    {
        "name": "audit_schematic",
        "description": "Performs a hardware audit on an EasyEDA schematic and returns a detailed Markdown review report with tables and issue summaries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schematic_path": {
                    "type": "string",
                    "description": "Path to the schematic export (.json, .tel, or .net) or 'live' for the active EasyEDA editor document."
                },
                "bom_path": {
                    "type": "string",
                    "description": "Optional path to the exported BOM (.xlsx or .csv) for datasheet links and LCSC part numbers."
                }
            }
        }
    },
    {
        "name": "get_part_profile",
        "description": "Returns the cached pinout, decoupling, crystal, and alternate function profile for a component by LCSC part ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lcsc_id": {
                    "type": "string",
                    "description": "The LCSC part number (e.g. C8734, C62973)."
                }
            },
            "required": ["lcsc_id"]
        }
    },
    {
        "name": "save_part_profile",
        "description": "Caches or updates a structured electrical part profile (pinout, power rails, decoupling, I2C addresses) into parts_cache/<LCSC_ID>.json for permanent reuse across future schematic reviews.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_data": {
                    "type": "object",
                    "description": "Structured component profile containing lcsc_part, part_number, part_type, power_pins, pin_map, voltage_limits, etc."
                }
            },
            "required": ["profile_data"]
        }
    },
    {
        "name": "get_datasheet",
        "description": "Downloads and caches a component datasheet PDF locally in datasheets/<LCSC_ID>.pdf or returns the path to an already cached datasheet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lcsc_id": {
                    "type": "string",
                    "description": "The LCSC part number (e.g. C22466409, C434726)."
                },
                "url": {
                    "type": "string",
                    "description": "Optional datasheet download URL (from BOM or LCSC)."
                }
            },
            "required": ["lcsc_id"]
        }
    },
    {
        "name": "list_cached_parts",
        "description": "Lists all component part profiles currently cached in the local library.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def run_mcp_server():
    """Runs the MCP server over stdio, also launching the live extension receiver."""
    start_live_receiver(port=8765)

    for line in sys.stdin:
        line_clean = line.strip()
        if not line_clean:
            continue
        try:
            req = json.loads(line_clean)
            method = req.get("method")
            msg_id = req.get("id")

            if method == "initialize":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "easyeda-with-gemini", "version": "1.0.0"}
                    }
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

            elif method == "tools/list":
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": TOOLS}
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

            elif method == "tools/call":
                params = req.get("params", {})
                tool_name = params.get("name")
                args = params.get("arguments", {})

                if tool_name == "audit_schematic":
                    out = audit_schematic(args.get("schematic_path"), args.get("bom_path"))
                    content = [{"type": "text", "text": out}]
                elif tool_name == "get_part_profile":
                    out = get_part_profile(args.get("lcsc_id", ""))
                    content = [{"type": "text", "text": json.dumps(out, indent=2)}]
                elif tool_name == "save_part_profile":
                    out = save_part_profile(args.get("profile_data", {}))
                    content = [{"type": "text", "text": json.dumps(out, indent=2)}]
                elif tool_name == "get_datasheet":
                    out = get_datasheet(args.get("lcsc_id", ""), args.get("url"))
                    content = [{"type": "text", "text": json.dumps(out, indent=2)}]
                elif tool_name == "list_cached_parts":
                    out = list_cached_parts()
                    content = [{"type": "text", "text": json.dumps(out, indent=2)}]
                else:
                    content = [{"type": "text", "text": f"Unknown tool: {tool_name}"}]

                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content}
                }
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()

        except Exception as e:
            err_res = {
                "jsonrpc": "2.0",
                "id": req.get("id") if "req" in locals() else None,
                "error": {"code": -32603, "message": str(e)}
            }
            sys.stdout.write(json.dumps(err_res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    if "--live" in sys.argv:
        server = start_live_receiver(port=8765)
        print("EasyEDA Live Receiver listening on http://127.0.0.1:8765/review...")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            server.shutdown()
    else:
        run_mcp_server()
