/**
 * EasyEDA Pro Live Extension for Antigravity & Gemini.
 * Sends active schematic netlist or components to the local review engine on http://127.0.0.1:8765/review.
 */

const ENDPOINT_URL = "http://127.0.0.1:8765/review";

export async function auditWithAntigravity() {
  try {
    let payload = null;

    // Method 1: Export active netlist via official EasyEDA Pro API
    if (typeof eda !== "undefined" && eda.sch_ManufactureData && typeof eda.sch_ManufactureData.getNetlistFile === "function") {
      try {
        const netlistFile = await eda.sch_ManufactureData.getNetlistFile("schematic", "Protel2");
        if (netlistFile) {
          const text = await netlistFile.text();
          if (text && text.length > 10) {
            payload = {
              project_name: "EasyEDA_Active_Design",
              netlist_text: text
            };
          }
        }
      } catch (err) {
        console.warn("Direct netlist export fallback:", err);
      }
    }

    // Method 2: Fallback to primitive component traversal
    if (!payload && typeof eda !== "undefined" && eda.sch_PrimitiveComponent) {
      try {
        const comps = await eda.sch_PrimitiveComponent.getAll();
        const compList = [];
        if (Array.isArray(comps)) {
          for (const c of comps) {
            const des = typeof c.getState_Designator === "function" ? c.getState_Designator() : (c.designator || "");
            if (des) {
              compList.push({
                ref_des: des,
                value: typeof c.getState_Value === "function" ? c.getState_Value() : (c.value || ""),
                package: typeof c.getState_Package === "function" ? c.getState_Package() : (c.package || ""),
                pins: []
              });
            }
          }
        }
        if (compList.length > 0) {
          payload = {
            project_name: "EasyEDA_Active_Design",
            components: compList
          };
        }
      } catch (err) {
        console.warn("Primitive extraction fallback:", err);
      }
    }

    if (!payload) {
      throw new Error("Could not extract active schematic. Please ensure a schematic sheet is open in EasyEDA Pro.");
    }

    let resp;
    if (typeof eda !== "undefined" && eda.sys_ClientUrl && typeof eda.sys_ClientUrl.request === "function") {
      resp = await eda.sys_ClientUrl.request(
        ENDPOINT_URL,
        "POST",
        { "Content-Type": "application/json" },
        JSON.stringify(payload)
      );
    } else {
      resp = await fetch(ENDPOINT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }

    if (resp && resp.status && resp.status >= 400) {
      throw new Error(`Local MCP server returned HTTP ${resp.status}`);
    }

    let data = {};
    try {
      if (typeof resp.json === "function") {
        data = await resp.json();
      } else if (typeof resp.text === "function") {
        data = JSON.parse(await resp.text());
      } else if (typeof resp === "string") {
        data = JSON.parse(resp);
      } else if (resp && typeof resp === "object") {
        data = resp;
      }
    } catch (parseErr) {
      data = { status: "success" };
    }

    const count = data.components_count !== undefined ? data.components_count : "active";
    alert(`Antigravity Audit Complete!\nEvaluated ${count} components.\nCheck your Antigravity IDE for the rendered review report.`);
  } catch (err) {
    alert(`Antigravity Reviewer Error:\n${err.message}\n\nPlease ensure your local MCP server or live receiver is running on port 8765.`);
  }
}

export function activate() {
  console.log("Antigravity Reviewer extension activated.");
}

export function deactivate() {
  console.log("Antigravity Reviewer extension deactivated.");
}
