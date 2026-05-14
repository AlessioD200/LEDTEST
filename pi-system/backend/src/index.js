import { config } from "./config.js";
import { makeTopics } from "./topics.js";
import { StateStore } from "./stateStore.js";
import { MqttService } from "./mqttService.js";
import { LocalPiDevice } from "./localPiDevice.js";
import { SimulatorDevice } from "./simulatorDevice.js";
import { Scheduler } from "./scheduler.js";
import { createServer } from "./server.js";

const stateStore = new StateStore(config.stateFile);
const topics = makeTopics(config.deviceId);

let broadcastState = () => {};

const transportHandlers = {
  onStatus: (status) => {
    stateStore.patch({
      device: {
        applied: status,
        lastSeen: Date.now(),
        online: true
      }
    });
  },
  onTelemetry: (telemetry) => {
    const patch = {
      device: {
        telemetry,
        lastSeen: Date.now(),
        online: true
      }
    };

    if (typeof telemetry?.scd30Available === "boolean") {
      patch.sensors = {
        available: {
          scd30: telemetry.scd30Available
        }
      };
    }

    stateStore.patch(patch);
  },
  onHeartbeat: () => {
    stateStore.patch({ device: { online: true, lastSeen: Date.now() } });
  },
  onOnline: (payload) => {
    stateStore.patch({ device: { online: Boolean(payload?.online), lastSeen: Date.now() } });
  }
};

const deviceTransport = config.deviceMode === "mqtt"
  ? new MqttService({
      url: config.mqttUrl,
      user: config.mqttUser,
      password: config.mqttPassword,
      topics,
      ...transportHandlers
    })
  : config.deviceMode === "local-pi"
    ? new LocalPiDevice({
        stateStore,
        bridgePath: config.localPiBridgePath,
        pythonBin: config.pythonBin,
        ledCount: config.ledCount,
        ledGpioPin: config.ledGpioPin,
        ledBrightness: config.ledBrightness,
        ledDma: config.ledDma,
        ledFreqHz: config.ledFreqHz,
        ledInvert: config.ledInvert,
        ledChannel: config.ledChannel,
        ledStripType: config.ledStripType,
        pirGpioPin: config.pirGpioPin,
        ...transportHandlers
      })
    : new SimulatorDevice({
        stateStore,
        ...transportHandlers
      });

if (typeof deviceTransport.start === "function") {
  deviceTransport.start();
}

const scheduler = new Scheduler(
  stateStore,
  (command) => deviceTransport.publishCommand(command),
  (state) => broadcastState(state)
);

const { broadcastState: bc } = createServer({
  config,
  stateStore,
  mqttService: deviceTransport,
  scheduler
});
broadcastState = bc;

scheduler.start();

process.on("SIGINT", () => {
  scheduler.stop();
  if (typeof deviceTransport.stop === "function") deviceTransport.stop();
  process.exit(0);
});
