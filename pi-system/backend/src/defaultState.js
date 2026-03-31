export const defaultState = {
  desired: {
    power: true,
    mode: "white",
    auto: false,
    brightness: 50,
    color: { r: 255, g: 255, b: 255 },
    effect: "none"
  },
  device: {
    online: false,
    lastSeen: null,
    firmware: "unknown",
    applied: null,
    telemetry: {
      temperature: null,
      lux: null,
      uptime: null
    }
  },
  scheduler: {
    enabled: false,
    pauseDurationMin: 15,
    lessons: [
      { name: "Les 1", start: "08:30", end: "10:00" },
      { name: "Les 2", start: "10:15", end: "11:45" }
    ],
    breaks: ["10:00"],
    runtime: {
      phase: "idle",
      nextEvent: null,
      pauseEndAt: null,
      lastTriggeredKey: null
    }
  }
};
