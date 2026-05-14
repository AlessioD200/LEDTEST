import express from "express";
import cors from "cors";
import fs from "node:fs";
import path from "node:path";
import { WebSocketServer } from "ws";

function buildCompatState(state) {
  const desired = state?.desired || {};
  const telemetry = state?.device?.telemetry || {};
  const effect = desired.effect || "none";

  return {
    lux: Number.isFinite(telemetry.lux) ? telemetry.lux : 0,
    temp: Number.isFinite(telemetry.temperature) ? telemetry.temperature : 0,
    humidity: Number.isFinite(telemetry.humidity) ? telemetry.humidity : 0,
    co2: Number.isFinite(telemetry.co2) ? telemetry.co2 : 0,
    mode: desired.mode || "off",
    auto: Boolean(desired.auto),
    br: Number.isFinite(desired.brightness) ? desired.brightness : 50,
    effects: {
      wave: effect === "wave",
      pulse: effect === "pulse",
      strobe: effect === "strobe",
      rainbow: effect === "rainbow"
    },
    desired,
    device: state?.device || {},
    sensors: state?.sensors || { available: {}, pirPin: null },
    scheduler: state?.scheduler || {},
    version: state?.version || {}
  };
}

async function downloadFile(url, destPath) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }

  const data = Buffer.from(await response.arrayBuffer());
  const tmpPath = `${destPath}.tmp`;
  fs.mkdirSync(path.dirname(destPath), { recursive: true });
  fs.writeFileSync(tmpPath, data);
  fs.renameSync(tmpPath, destPath);
}

export function createServer({ config, stateStore, mqttService, scheduler }) {
  const app = express();
  app.use(cors());
  app.use(express.json());

  let updateRunning = false;
  let updateQueued = null;
  let updateRebootPending = false;
  let updateStatus = {
    ok: false,
    message: "No update run yet",
    updated: [],
    ts: 0
  };

  const tokenEnabled = config.updateAuthToken && config.updateAuthToken !== "change-me";

  function setUpdateStatus(next) {
    updateStatus = {
      ok: Boolean(next.ok),
      message: String(next.message || ""),
      updated: Array.isArray(next.updated) ? next.updated : [],
      ts: Number(next.ts || Date.now())
    };
  }

  async function runUpdateJob(job) {
    updateRunning = true;
    setUpdateStatus({ ok: true, message: "Update running", updated: [], ts: Date.now() });

    const baseUrl = String(job.baseUrl || config.defaultUpdateBaseUrl || "").trim();
    const files = Array.isArray(job.files) && job.files.length
      ? job.files
      : [
          { local: "index.html", remote: "web/index.html" },
          { local: "styles.css", remote: "web/styles.css" },
          { local: "app.js", remote: "web/app.js" }
        ];

    try {
      if (!baseUrl) {
        throw new Error("Update baseUrl missing");
      }

      const updated = [];
      for (const file of files) {
        if (!file || typeof file !== "object") continue;
        const local = String(file.local || "").trim();
        const remote = String(file.remote || "").trim();
        if (!local || !remote) continue;

        const target = path.join(config.webDashboardDir, local);
        const remotePath = remote.startsWith("/") ? remote.slice(1) : remote;
        const url = `${baseUrl.replace(/\/$/, "")}/${remotePath}`;
        await downloadFile(url, target);
        updated.push(local);
      }

      setUpdateStatus({
        ok: true,
        message: job.reboot ? "Update completed, reboot requested" : "Update completed",
        updated,
        ts: Date.now()
      });

      const currentVersion = stateStore.get().version || {};
      stateStore.patch({
        version: {
          firmware: "rpi-backend",
          buildId: `rpi-${Date.now()}`,
          otaCount: Number(currentVersion.otaCount || 0) + 1,
          lastUpdateTs: Date.now(),
          lastUpdated: updated
        }
      });

      if (job.reboot) {
        setTimeout(() => {
          process.exit(0);
        }, 1500);
      }
      updateRebootPending = false;
    } catch (error) {
      setUpdateStatus({
        ok: false,
        message: String(error?.message || error),
        updated: [],
        ts: Date.now()
      });
      updateRebootPending = false;
    } finally {
      updateRunning = false;
    }
  }

  function processQueuedUpdate() {
    if (updateRunning || !updateQueued) return;
    const job = updateQueued;
    updateQueued = null;
    runUpdateJob(job);
  }

  setInterval(processQueuedUpdate, 200);

  app.get("/api/health", (_req, res) => {
    res.json({ ok: true, ts: Date.now() });
  });

  app.get("/api/state", (_req, res) => {
    res.json(buildCompatState(stateStore.get()));
  });

  app.get("/api/sensor", (_req, res) => {
    const state = stateStore.get();
    const telemetry = state?.device?.telemetry || {};
    res.json({
      lux: Number.isFinite(telemetry.lux) ? telemetry.lux : 0,
      temp: Number.isFinite(telemetry.temperature) ? telemetry.temperature : 0,
      humidity: Number.isFinite(telemetry.humidity) ? telemetry.humidity : 0,
      co2: Number.isFinite(telemetry.co2) ? telemetry.co2 : 0
    });
  });

  app.get("/api/update/status", (_req, res) => {
    const state = stateStore.get();
    res.json({
      ...updateStatus,
      inProgress: Boolean(updateRunning || updateQueued),
      rebootPending: Boolean(updateRebootPending),
      version: state?.version || {}
    });
  });

  app.post("/api/update", (req, res) => {
    const body = req.body || {};
    const token = String(body.token || "");
    if (tokenEnabled && token !== config.updateAuthToken) {
      res.status(403).json({ ok: false, error: "Invalid token" });
      return;
    }

    if (updateRunning || updateQueued) {
      res.json({ ok: false, message: "Update already running", updated: [], ts: Date.now() });
      return;
    }

    updateQueued = {
      baseUrl: body.baseUrl,
      files: body.files,
      reboot: Boolean(body.reboot)
    };
    updateRebootPending = Boolean(body.reboot);
    setUpdateStatus({ ok: true, message: "Update queued", updated: [], ts: Date.now() });
    res.json(updateStatus);
  });

  app.post("/api/command", (req, res) => {
    let payload = req.body || {};
    if (payload && typeof payload === "object" && payload.desired && typeof payload.desired === "object") {
      payload = payload.desired;
    }

    const { power, mode, auto, brightness, color, effect, timer } = payload || {};
    const patch = {
      desired: {
        power: power ?? stateStore.get().desired.power,
        mode: mode ?? stateStore.get().desired.mode,
        auto: auto ?? stateStore.get().desired.auto,
        brightness: brightness ?? stateStore.get().desired.brightness,
        color: color ?? stateStore.get().desired.color,
        effect: effect ?? stateStore.get().desired.effect,
        timer: timer ?? stateStore.get().desired.timer
      }
    };
    const next = stateStore.patch(patch);
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.json(buildCompatState(next));
  });

  app.post("/api/scheduler", (req, res) => {
    const { enabled, pauseDurationMin, lessons, breaks } = req.body || {};
    const patch = {
      scheduler: {
        enabled: Boolean(enabled),
        pauseDurationMin: Math.max(1, Number(pauseDurationMin || 15)),
        lessons: Array.isArray(lessons) ? lessons : stateStore.get().scheduler.lessons,
        breaks: Array.isArray(breaks) ? breaks : stateStore.get().scheduler.breaks
      }
    };
    const next = stateStore.patch(patch);
    res.json(next);
  });

  app.post("/api/scheduler/start", (_req, res) => {
    const next = stateStore.patch({ scheduler: { enabled: true } });
    res.json(buildCompatState(next));
  });

  app.post("/api/scheduler/stop", (_req, res) => {
    const next = stateStore.patch({ scheduler: { enabled: false, runtime: { phase: "idle", pauseEndAt: null } } });
    res.json(buildCompatState(next));
  });

  app.get("/toggle/auto", (_req, res) => {
    const next = stateStore.patch({ desired: { auto: !Boolean(stateStore.get().desired.auto) } });
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.type("text/plain").send("OK");
  });

  app.get("/mode/:mode", (req, res) => {
    const mode = String(req.params.mode || "off");
    const next = stateStore.patch({ desired: { mode, power: mode !== "off", effect: "none" } });
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.type("text/plain").send("OK");
  });

  app.get("/set_global", (req, res) => {
    const br = Number(req.query.br);
    const brightness = Number.isFinite(br) ? Math.max(1, Math.min(100, Math.round(br))) : stateStore.get().desired.brightness;
    const next = stateStore.patch({ desired: { brightness } });
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.type("text/plain").send("OK");
  });

  app.get("/lightshow/:effect/toggle", (req, res) => {
    const effect = String(req.params.effect || "none");
    const current = String(stateStore.get().desired.effect || "none");
    const nextEffect = current === effect ? "none" : effect;
    const next = stateStore.patch({ desired: { effect: nextEffect } });
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.type("text/plain").send("OK");
  });

  app.get("/api/ota/:name", (req, res) => {
    const fileName = String(req.params.name || "");
    const map = {
      "index.html": path.join(config.webDashboardDir, "index.html"),
      "styles.css": path.join(config.webDashboardDir, "styles.css"),
      "app.js": path.join(config.webDashboardDir, "app.js")
    };

    const target = map[fileName];
    if (!target || !fs.existsSync(target)) {
      res.status(404).json({ ok: false, error: "File not found" });
      return;
    }

    if (fileName.endsWith(".html")) res.type("text/html; charset=utf-8");
    else if (fileName.endsWith(".css")) res.type("text/css; charset=utf-8");
    else if (fileName.endsWith(".js")) res.type("application/javascript; charset=utf-8");

    res.sendFile(target);
  });

  app.use("/touch", express.static(config.touchDashboardDir));
  app.get("/touch", (_req, res) => {
    res.sendFile(path.join(config.touchDashboardDir, "index.html"));
  });
  app.get("/kiosk", (_req, res) => {
    res.sendFile(path.join(config.touchDashboardDir, "7inch-kiosk.html"));
  });

  if (config.webDashboardDir && fs.existsSync(config.webDashboardDir)) {
    app.use(express.static(config.webDashboardDir));
  }

  app.get("/", (_req, res) => {
    if (config.webDashboardDir && fs.existsSync(config.webDashboardDir)) {
      res.sendFile(path.join(config.webDashboardDir, "index.html"));
      return;
    }
    res.sendFile(path.join(config.touchDashboardDir, "index.html"));
  });

  const server = app.listen(config.port, () => {
    // eslint-disable-next-line no-console
    console.log(`Backend listening on :${config.port}`);
  });

  const wss = new WebSocketServer({ server, path: "/ws" });
  const broadcastState = (state) => {
    const payload = JSON.stringify({ type: "state", state });
    wss.clients.forEach((client) => {
      if (client.readyState === 1) client.send(payload);
    });
  };

  wss.on("connection", (ws) => {
    ws.send(JSON.stringify({ type: "state", state: stateStore.get() }));
  });

  const originalPatch = stateStore.patch.bind(stateStore);
  stateStore.patch = (patchObj) => {
    const updated = originalPatch(patchObj);
    broadcastState(updated);
    return updated;
  };

  scheduler.broadcastState = broadcastState;

  return { app, server, broadcastState };
}
