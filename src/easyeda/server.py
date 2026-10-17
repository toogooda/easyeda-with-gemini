from __future__ import annotations
import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .models import SchematicGraph
from .parser import parse_schematic_json, parse_protel_netlist
from .datasheet_extractor import parse_bom, merge_bom_into_graph
from .parts_manager import PartsManager
from .reporter import generate_schematic_report

# Global live state
_LAST_LIVE_GRAPH: Optional[SchematicGraph] = None
_LAST_LIVE_REPORT: Optional[str] = None
_CACHE_REPORT_FILE = Path(__file__).resolve().parents[2] / "parts_cache" / ".last_live_report.md"


class EasyEDALiveHandler(BaseHTTPRequestHandler):
    """Receives live schematic dumps from the EasyEDA Pro extension over localhost:8765."""

    def do_POST(self):
        global _LAST_LIVE_GRAPH, _LAST_LIVE_REPORT
        if self.path == "/review":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                stripped = post_data.strip()
                if stripped.startswith("{") or stripped.startswith("[{"):
                    data = json.loads(stripped)
                    if isinstance(data, dict) and "netlist_text" in data:
                        graph = parse_protel_netlist(data["netlist_text"])
                        if "project_name" in data:
                            graph.project_name = data["project_name"]
                        if "bom_data" in data and isinstance(data["bom_data"], dict):
                            merge_bom_into_graph(graph, data["bom_data"])
                    else:
                        graph = parse_schematic_json(data)
                else:
                    graph = parse_protel_netlist(stripped)

                pm = PartsManager()
                report = generate_schematic_report(graph, pm)

                _LAST_LIVE_GRAPH = graph
                _LAST_LIVE_REPORT = report
                try:
                    _CACHE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _CACHE_REPORT_FILE.write_text(report, encoding="utf-8")
                except Exception:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                response = {
                    "status": "success",
                    "components_count": len(graph.components),
                    "nets_count": len(graph.nets),
                    "report_preview": report[:500]
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
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
    """Starts the background HTTP receiver for EasyEDA Pro live extensions."""
    server = HTTPServer(("127.0.0.1", port), EasyEDALiveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ==========================================
# MCP Tool Functions (Callable by Antigravity)
# ==========================================

def audit_schematic(schematic_path: Optional[str] = None, bom_path: Optional[str] = None) -> str:
    """
    Audits an EasyEDA schematic and returns a rendered Markdown report.
    If schematic_path is omitted or 'live', uses the last live schematic pushed from EasyEDA Pro.
    """
    global _LAST_LIVE_REPORT
    pm = PartsManager()

    if not schematic_path or schematic_path.lower() == "live":
        if _LAST_LIVE_REPORT:
            return _LAST_LIVE_REPORT
        if _CACHE_REPORT_FILE.exists():
            return _CACHE_REPORT_FILE.read_text(encoding="utf-8")
        return "No live schematic received yet from EasyEDA Pro. Use 'Audit Schematic with Antigravity' in EasyEDA Pro, or specify a file path."

    path = Path(schematic_path)
    if not path.exists():
        return f"Error: Schematic file not found: {schematic_path}"

    if path.suffix.lower() in (".tel", ".net"):
        graph = parse_protel_netlist(path)
    else:
        graph = parse_schematic_json(path)

    if bom_path and Path(bom_path).exists():
        bom_data = parse_bom(bom_path)
        merge_bom_into_graph(graph, bom_data)

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
    run_mcp_server()
