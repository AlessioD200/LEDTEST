import { spawn } from "node:child_process";
import readline from "node:readline";

export class LocalPiDevice {
  constructor({
    stateStore,
    bridgePath,
    pythonBin,
    ledCount,
    ledGpioPin,
    ledBrightness,
    ledDma,
    ledFreqHz,
    ledInvert,
    ledChannel,
    ledStripType,
    pirGpioPin,
    onStatus,
    onTelemetry,
    onHeartbeat,
    onOnline
  }) {
    this.stateStore = stateStore;
    this.bridgePath = bridgePath;
    this.pythonBin = pythonBin;
    this.ledCount = ledCount;
    this.ledGpioPin = ledGpioPin;
    this.ledBrightness = ledBrightness;
    this.ledDma = ledDma;
    this.ledFreqHz = ledFreqHz;
    this.ledInvert = ledInvert;
    this.ledChannel = ledChannel;
    this.ledStripType = ledStripType;
    this.pirGpioPin = pirGpioPin;
    this.onStatus = onStatus;
    this.onTelemetry = onTelemetry;
    this.onHeartbeat = onHeartbeat;
    this.onOnline = onOnline;

    this.child = null;
    this.stdoutRl = null;
    this.stderrRl = null;
    this.shouldRun = false;
    this.restartTimer = null;
    this.pendingCommands = [];
  }

  start() {
    this.shouldRun = true;
    this.stateStore.patch({
      sensors: {
        available: {
          ldr: false,
          bh1750: false,
          ds18b20: false,
          sht3x: false,
          bme280: false,
          pir: Number.isInteger(this.pirGpioPin)
        },
        pirPin: Number.isInteger(this.pirGpioPin) ? this.pirGpioPin : null
      }
    });
    this.spawnBridge();
  }

  stop() {
    this.shouldRun = false;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    if (this.stdoutRl) this.stdoutRl.close();
    if (this.stderrRl) this.stderrRl.close();
    this.stdoutRl = null;
    this.stderrRl = null;
    if (this.child) {
      this.child.kill("SIGTERM");
      this.child = null;
    }
    this.onOnline({ online: false, localPi: true });
  }

  publishCommand(command) {
    if (!command || typeof command !== "object") return;
    this.pendingCommands.push(command);
    if (this.pendingCommands.length > 8) {
      this.pendingCommands = this.pendingCommands.slice(-8);
    }
    this.flushPending();
  }

  spawnBridge() {
    const env = {
      ...process.env,
      LED_COUNT: String(this.ledCount),
      LED_GPIO_PIN: String(this.ledGpioPin),
      LED_BRIGHTNESS: String(this.ledBrightness),
      LED_DMA: String(this.ledDma),
      LED_FREQ_HZ: String(this.ledFreqHz),
      LED_INVERT: this.ledInvert ? "1" : "0",
      LED_CHANNEL: String(this.ledChannel),
      LED_STRIP_TYPE: this.ledStripType,
      PIR_GPIO_PIN: Number.isInteger(this.pirGpioPin) ? String(this.pirGpioPin) : ""
    };

    this.child = spawn(this.pythonBin, [this.bridgePath], {
      env,
      stdio: ["pipe", "pipe", "pipe"]
    });

    this.stdoutRl = readline.createInterface({ input: this.child.stdout });
    this.stderrRl = readline.createInterface({ input: this.child.stderr });

    this.stdoutRl.on("line", (line) => this.handleLine(line));
    this.stderrRl.on("line", (line) => {
      if (line.trim()) console.error(`[local-pi] ${line}`);
    });

    this.child.on("spawn", () => {
      this.onOnline({ online: true, localPi: true, starting: true });
      this.pendingCommands.push({ type: "set_state", desired: this.stateStore.get().desired, ts: Date.now() });
      this.flushPending();
    });

    this.child.on("exit", (code, signal) => {
      this.child = null;
      if (this.stdoutRl) this.stdoutRl.close();
      if (this.stderrRl) this.stderrRl.close();
      this.stdoutRl = null;
      this.stderrRl = null;
      this.onOnline({ online: false, localPi: true, code, signal });

      if (!this.shouldRun) return;
      this.restartTimer = setTimeout(() => this.spawnBridge(), 2000);
    });
  }

  flushPending() {
    if (!this.child || !this.child.stdin || !this.child.stdin.writable) return;
    while (this.pendingCommands.length) {
      const command = this.pendingCommands.shift();
      this.child.stdin.write(`${JSON.stringify(command)}\n`);
    }
  }

  handleLine(line) {
    if (!line.trim()) return;

    let payload;
    try {
      payload = JSON.parse(line);
    } catch {
      console.error(`[local-pi] invalid json: ${line}`);
      return;
    }

    if (payload.type === "status") this.onStatus(payload.status || {});
    if (payload.type === "telemetry") this.onTelemetry(payload.telemetry || {});
    if (payload.type === "heartbeat") this.onHeartbeat(payload.heartbeat || {});
    if (payload.type === "online") this.onOnline(payload);
  }
}