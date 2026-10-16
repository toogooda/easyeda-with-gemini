/**
 * EasyEDA Pro Live Extension for Antigravity & Gemini.
 * Sends active schematic components, pins, and nets to the local MCP server on http://127.0.0.1:8765/review.
 */

const ENDPOINT_URL = "http://127.0.0.1:8765/review";

function extractComponentsFromEditor(doc, primitives) {
  const components = [];
  const compMap = new Map();

  // Walk through device primitives
  if (Array.isArray(primitives)) {
    for (const prim of primitives) {
      if (prim.type === "DEVICE" || prim.type === "COMPONENT") {
        const refDes = prim.designator || prim.name || "";
        if (!refDes) continue;

        const compObj = {
          ref_des: refDes,
          value: prim.value || prim.comment || "",
          package: prim.package || prim.footprint || "",
          lcsc_id: prim.supplierPart || prim.lcscPart || prim.partNumber || "",
          datasheet: prim.datasheet || prim.link || "",
          pins: []
        };
        compMap.set(refDes, compObj);
        components.push(compObj);
      }
    }

    // Associate pins and connected nets
    for (const prim of primitives) {
      if (prim.type === "PIN") {
        const refDes = prim.parentDesignator || prim.deviceRef;
        const comp = compMap.get(refDes);
        if (comp) {
          comp.pins.push({
            number: String(prim.number || prim.pinNumber || ""),
            name: String(prim.name || prim.pinName || ""),
            net: String(prim.net || prim.netName || "")
          });
        }
      }
    }
  }

  return components;
}

export async function auditWithAntigravity() {
  try {
    const doc = await api.editor.getDocument();
    const primitives = await api.editor.getPrimitives();

    const payload = {
      project_name: (doc && doc.title) ? doc.title : "EasyEDA_Active_Design",
      version: "1.0",
      components: extractComponentsFromEditor(doc, primitives)
    };

    const resp = await fetch(ENDPOINT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!resp.ok) {
      throw new Error(`Server returned HTTP ${resp.status}`);
    }

    const data = await resp.json();
    api.ui.showMessage(`Antigravity Audit Complete! Evaluated ${data.components_count} components. Check your Antigravity IDE for the rendered report.`, "success");
  } catch (err) {
    api.ui.showMessage(`Failed to connect to local Antigravity MCP server: ${err.message}. Make sure the MCP server is running!`, "error");
  }
}

export function activate() {
  api.editor.registerMenu({
    id: "antigravity.audit",
    title: "Audit with Antigravity",
    menu: "Schematic/Tools",
    action: auditWithAntigravity
  });
}
