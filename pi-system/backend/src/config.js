import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const toNumber = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};
const toNullableNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

export const config = {
  port: Number(process.env.PORT || 3000),
  deviceMode: process.env.DEVICE_MODE || "simulator",
  mqttUrl: process.env.MQTT_URL || "mqtt://127.0.0.1:1883",
  mqttUser: process.env.MQTT_USER || "",
  mqttPassword: process.env.MQTT_PASSWORD || "",
  updateAuthToken: process.env.UPDATE_AUTH_TOKEN || "Vives_plus",
  defaultUpdateBaseUrl: process.env.UPDATE_BASE_URL || "https://raw.githubusercontent.com/AlessioD200/LEDTEST/main",
  deviceId: process.env.DEVICE_ID || "esp32-led-1",
  stateFile: path.resolve(__dirname, "..", process.env.STATE_FILE || "./data/state.json"),
  touchDashboardDir: path.resolve(__dirname, "..", "public"),
  // Primary dashboard used on Pi touchscreen (same UI as ESP/web folder).
  webDashboardDir: path.resolve(__dirname, "..", "..", "..", "web"),
  pythonBin: process.env.PYTHON_BIN || "python3",
  localPiBridgePath: path.resolve(__dirname, "..", "..", "local-device", "rpi_led_bridge.py"),
  ledCount: toNumber(process.env.LED_COUNT, 60),
  ledGpioPin: toNumber(process.env.LED_GPIO_PIN, 18),
  ledBrightness: toNumber(process.env.LED_BRIGHTNESS, 255),
  ledDma: toNumber(process.env.LED_DMA, 10),
  ledFreqHz: toNumber(process.env.LED_FREQ_HZ, 800000),
  ledInvert: ["1", "true", "yes", "on"].includes(String(process.env.LED_INVERT || "").toLowerCase()),
  ledChannel: toNumber(process.env.LED_CHANNEL, 0),
  ledStripType: process.env.LED_STRIP_TYPE || "grb",
  pirGpioPin: toNullableNumber(process.env.PIR_GPIO_PIN)
};
