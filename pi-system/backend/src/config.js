import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const config = {
  port: Number(process.env.PORT || 3000),
  deviceMode: process.env.DEVICE_MODE || "simulator",
  mqttUrl: process.env.MQTT_URL || "mqtt://127.0.0.1:1883",
  mqttUser: process.env.MQTT_USER || "",
  mqttPassword: process.env.MQTT_PASSWORD || "",
  deviceId: process.env.DEVICE_ID || "esp32-led-1",
  stateFile: path.resolve(__dirname, "..", process.env.STATE_FILE || "./data/state.json"),
  touchDashboardDir: path.resolve(__dirname, "..", "public"),
  legacyDashboardDir: path.resolve(__dirname, "..", "..", "..", "web")
};
