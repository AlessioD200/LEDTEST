export const defaultState = {
  desired: {
    power: true,
    mode: "white",
    auto: false,
    brightness: 50,
    color: { r: 255, g: 255, b: 255 },
    effect: "none",
    timer: {
      mode: "off",
      remainingMs: 0,
      totalMs: 0
    }
  },
  device: {
    online: false,
    lastSeen: null,
    firmware: "unknown",
    applied: null,
    telemetry: {
      temperature: null,
      lux: null,
      uptime: null,
      motion: null
    }
  },
  sensors: {
    available: {
      ldr: false,
      bh1750: false,
      ds18b20: false,
      sht3x: false,
      bme280: false,
      pir: false
    },
    pirPin: null
  },
  version: {
    firmware: "rpi-backend",
    buildId: "rpi-local",
    otaCount: 0,
    lastUpdateTs: 0,
    lastUpdated: []
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
