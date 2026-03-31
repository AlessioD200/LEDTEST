function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export class SimulatorDevice {
  constructor({ stateStore, onStatus, onTelemetry, onHeartbeat, onOnline }) {
    this.stateStore = stateStore;
    this.onStatus = onStatus;
    this.onTelemetry = onTelemetry;
    this.onHeartbeat = onHeartbeat;
    this.onOnline = onOnline;
    this.startedAt = Date.now();
    this.tickHandle = null;
    this.effect = "none";
  }

  start() {
    this.onOnline({ online: true, simulated: true });
    this.publishCurrentState();
    this.tickHandle = setInterval(() => this.tick(), 1000);
  }

  stop() {
    if (this.tickHandle) clearInterval(this.tickHandle);
    this.tickHandle = null;
  }

  tick() {
    const elapsed = (Date.now() - this.startedAt) / 1000;
    const telemetry = {
      temperature: Number((22 + Math.sin(elapsed / 20) * 2.5).toFixed(1)),
      lux: Math.round(280 + Math.sin(elapsed / 8) * 180),
      uptime: Math.round(elapsed),
      simulated: true
    };
    this.onTelemetry(telemetry);
    this.onHeartbeat({ uptime: telemetry.uptime, simulated: true });
  }

  publishCurrentState(extra = {}) {
    const desired = this.stateStore.get().desired;
    this.onStatus({
      power: desired.power,
      mode: desired.mode,
      auto: desired.auto,
      brightness: desired.brightness,
      effect: desired.effect,
      color: desired.color,
      simulated: true,
      ...extra
    });
  }

  publishCommand(command) {
    if (command?.type === "set_state") {
      this.publishCurrentState();
      return;
    }

    if (command?.type === "break_start" || command?.type === "lesson_end") {
      this.publishCurrentState({ lastEvent: command.type, event: command.event || null });
      return;
    }

    if (command?.type === "pause_end") {
      this.publishCurrentState({ lastEvent: "pause_end" });
    }
  }
}
