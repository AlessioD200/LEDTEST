import express from "express";
import cors from "cors";
import path from "node:path";
import { WebSocketServer } from "ws";

export function createServer({ config, stateStore, mqttService, scheduler }) {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.get("/api/health", (_req, res) => {
    res.json({ ok: true, ts: Date.now() });
  });

  app.get("/api/state", (_req, res) => {
    res.json(stateStore.get());
  });

  app.post("/api/command", (req, res) => {
    const { power, mode, auto, brightness, color, effect } = req.body || {};
    const patch = {
      desired: {
        power: power ?? stateStore.get().desired.power,
        mode: mode ?? stateStore.get().desired.mode,
        auto: auto ?? stateStore.get().desired.auto,
        brightness: brightness ?? stateStore.get().desired.brightness,
        color: color ?? stateStore.get().desired.color,
        effect: effect ?? stateStore.get().desired.effect
      }
    };
    const next = stateStore.patch(patch);
    mqttService.publishCommand({ type: "set_state", desired: next.desired, ts: Date.now() });
    res.json(next);
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
    res.json(next);
  });

  app.post("/api/scheduler/stop", (_req, res) => {
    const next = stateStore.patch({ scheduler: { enabled: false, runtime: { phase: "idle", pauseEndAt: null } } });
    res.json(next);
  });

  app.use("/touch", express.static(config.touchDashboardDir));
  app.get("/touch", (_req, res) => {
    res.sendFile(path.join(config.touchDashboardDir, "index.html"));
  });

  app.use(express.static(config.legacyDashboardDir));
  app.get("/", (_req, res) => {
    res.sendFile(path.join(config.legacyDashboardDir, "index.html"));
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
