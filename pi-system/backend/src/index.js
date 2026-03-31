import { config } from "./config.js";
import { makeTopics } from "./topics.js";
import { StateStore } from "./stateStore.js";
import { MqttService } from "./mqttService.js";
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
    stateStore.patch({
      device: {
        telemetry,
        lastSeen: Date.now(),
        online: true
      }
    });
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
