import fs from "node:fs";
import path from "node:path";
import { defaultState } from "./defaultState.js";

function deepMerge(target, source) {
  if (!source || typeof source !== "object") return target;
  const out = { ...target };
  for (const [k, v] of Object.entries(source)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out[k] = deepMerge(target[k] || {}, v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

export class StateStore {
  constructor(stateFile) {
    this.stateFile = stateFile;
    this.state = structuredClone(defaultState);
    this.load();
  }

  load() {
    const dir = path.dirname(this.stateFile);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    if (!fs.existsSync(this.stateFile)) {
      this.save();
      return;
    }
    const raw = fs.readFileSync(this.stateFile, "utf-8");
    const parsed = JSON.parse(raw || "{}");
    this.state = deepMerge(defaultState, parsed);
  }

  save() {
    fs.writeFileSync(this.stateFile, JSON.stringify(this.state, null, 2));
  }

  get() {
    return this.state;
  }

  patch(patchObj) {
    this.state = deepMerge(this.state, patchObj);
    this.save();
    return this.state;
  }

  set(newState) {
    this.state = deepMerge(defaultState, newState);
    this.save();
    return this.state;
  }
}
