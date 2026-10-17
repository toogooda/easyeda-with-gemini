var edaEsbuildExportName = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  var src_exports = {};
  __export(src_exports, {
    about: () => about,
    activate: () => activate,
    auditWithAntigravity: () => auditWithAntigravity,
    deactivate: () => deactivate
  });

  const ENDPOINT_URL = "http://127.0.0.1:8765/review?client=localhost";

  function showDialog(message, title = "Antigravity Reviewer") {
    try {
      if (typeof eda !== "undefined" && eda.sys_Dialog && typeof eda.sys_Dialog.showInformationMessage === "function") {
        eda.sys_Dialog.showInformationMessage(message, title);
        return;
      }
    } catch (e) {}
    if (typeof alert === "function") {
      alert(title + "\n\n" + message);
    }
  }

  function activate(status, arg) {
    console.log("Antigravity Reviewer extension activated.");
  }

  function deactivate() {
    console.log("Antigravity Reviewer extension deactivated.");
  }

  function about() {
    showDialog(
      "Antigravity Schematic Reviewer v1.0.0\nConnects EasyEDA Pro to Antigravity & Gemini via MCP (http://127.0.0.1:8765/review).",
      "About Antigravity Reviewer"
    );
  }

  async function extractComponentMetadata() {
    const bomMeta = {};
    if (typeof eda !== "undefined" && eda.sch_PrimitiveComponent && typeof eda.sch_PrimitiveComponent.getAll === "function") {
      try {
        const comps = await eda.sch_PrimitiveComponent.getAll(undefined, true);
        if (Array.isArray(comps)) {
          for (const c of comps) {
            const des = typeof c.getState_Designator === "function" ? c.getState_Designator() : (c.designator || "");
            if (!des) continue;
            const val = typeof c.getState_Value === "function" ? c.getState_Value() : (c.value || c.comment || "");
            const pkg = typeof c.getState_Package === "function" ? c.getState_Package() : (c.package || c.footprint || "");
            const lcsc = typeof c.getState_SupplierId === "function" ? c.getState_SupplierId() : (c.supplierId || c.supplierPart || c.lcscPart || "");
            const sheet = typeof c.getState_Datasheet === "function" ? c.getState_Datasheet() : (c.datasheet || "");
            bomMeta[des] = {
              ref_des: des,
              value: String(val || ""),
              footprint: String(pkg || ""),
              lcsc_id: String(lcsc || ""),
              datasheet: String(sheet || "")
            };
          }
        }
      } catch (e) {
        console.warn("Component metadata extraction warning:", e);
      }
    }
    return bomMeta;
  }

  async function auditWithAntigravity() {
    try {
      let netlistText = null;
      let bomCsv = null;

      // 1. Try SCH_ManufactureData.getNetlistFile ('Allegro' gives .tel format, fallback to 'Protel2')
      if (typeof eda !== "undefined" && eda.sch_ManufactureData && typeof eda.sch_ManufactureData.getNetlistFile === "function") {
        for (const fmt of ["Allegro", "Protel2"]) {
          try {
            const netlistFile = await eda.sch_ManufactureData.getNetlistFile("schematic", fmt);
            if (netlistFile) {
              if (typeof netlistFile.text === "function") {
                netlistText = await netlistFile.text();
              } else if (typeof netlistFile === "string") {
                netlistText = netlistFile;
              }
              if (netlistText && netlistText.length > 10) {
                break;
              }
            }
          } catch (err) {
            console.warn("getNetlistFile (" + fmt + ") fallback:", err);
          }
        }
      }

      // 2. Fallback to SCH_Netlist.getNetlist
      if ((!netlistText || netlistText.length < 10) && typeof eda !== "undefined" && eda.sch_Netlist && typeof eda.sch_Netlist.getNetlist === "function") {
        for (const fmt of ["Allegro", "Protel2"]) {
          try {
            const res = await eda.sch_Netlist.getNetlist(fmt);
            if (typeof res === "string" && res.length > 10) {
              netlistText = res;
              break;
            } else if (res && typeof res.text === "function") {
              netlistText = await res.text();
              if (netlistText && netlistText.length > 10) break;
            }
          } catch (err) {
            console.warn("getNetlist (" + fmt + ") fallback:", err);
          }
        }
      }

      // 3. Try SCH_ManufactureData.getBomFile ('csv') to get LCSC IDs and Datasheet URLs
      if (typeof eda !== "undefined" && eda.sch_ManufactureData && typeof eda.sch_ManufactureData.getBomFile === "function") {
        try {
          const bomFile = await eda.sch_ManufactureData.getBomFile("bom", "csv");
          if (bomFile) {
            if (typeof bomFile.text === "function") {
              bomCsv = await bomFile.text();
            } else if (typeof bomFile === "string") {
              bomCsv = bomFile;
            }
          }
        } catch (err) {
          console.warn("getBomFile fallback:", err);
        }
      }

      const bomMeta = await extractComponentMetadata();

      let payload = null;
      if (netlistText && netlistText.length > 10) {
        payload = {
          project_name: "EasyEDA_Active_Design",
          netlist_text: netlistText,
          bom_csv: bomCsv || "",
          bom_data: bomMeta
        };
      } else if (Object.keys(bomMeta).length > 0) {
        payload = {
          project_name: "EasyEDA_Active_Design",
          components: Object.values(bomMeta).map((m) => ({
            ref_des: m.ref_des,
            value: m.value,
            package: m.footprint,
            lcsc_id: m.lcsc_id,
            datasheet: m.datasheet,
            pins: []
          }))
        };
      }

      if (!payload) {
        showDialog(
          "Could not extract active schematic data. Please make sure a schematic sheet is currently open in the editor.",
          "Antigravity Reviewer"
        );
        return;
      }

      const bodyString = JSON.stringify(payload);
      let resp;
      if (typeof eda !== "undefined" && eda.sys_ClientUrl && typeof eda.sys_ClientUrl.request === "function") {
        resp = await eda.sys_ClientUrl.request(
          ENDPOINT_URL,
          "POST",
          bodyString,
          { headers: { "Content-Type": "application/json" } }
        );
      } else {
        resp = await fetch(ENDPOINT_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: bodyString
        });
      }

      if (resp && resp.status && resp.status >= 400) {
        let errDetail = "HTTP " + resp.status;
        try {
          if (typeof resp.text === "function") {
            errDetail += " - " + (await resp.text());
          }
        } catch (e) {}
        throw new Error("Local MCP server returned " + errDetail);
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

      const count = data.components_count !== undefined ? data.components_count : (payload.components ? payload.components.length : "active");
      showDialog(
        "Antigravity Audit Complete!\nEvaluated " + count + " components.\n\nSwitch to your Antigravity IDE and ask:\n\"Review my open EasyEDA schematic\"",
        "Antigravity Audit Complete"
      );
    } catch (err) {
      showDialog(
        "Could not connect to local Antigravity receiver (" + err.message + ").\n\nPlease make sure the Antigravity MCP server or live receiver is running on http://127.0.0.1:8765!",
        "Connection Error"
      );
    }
  }

  return __toCommonJS(src_exports);
})();
