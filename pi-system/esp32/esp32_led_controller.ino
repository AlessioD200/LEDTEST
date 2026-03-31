#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <FastLED.h>

#define LED_PIN 5
#define LED_COUNT 140
#define LED_TYPE WS2812B
#define COLOR_ORDER GRB

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";

const char* MQTT_HOST = "192.168.1.10";
const int MQTT_PORT = 1883;
const char* MQTT_USER = "leduser";
const char* MQTT_PASS = "change-me";

const char* DEVICE_ID = "esp32-led-1";
String TOPIC_CMD;
String TOPIC_STATUS;
String TOPIC_TELE;
String TOPIC_HEART;
String TOPIC_ONLINE;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
CRGB leds[LED_COUNT];

struct DesiredState {
  bool power = true;
  String mode = "white";
  int brightness = 50;
  CRGB color = CRGB(255, 255, 255);
  String effect = "none";
} desired;

unsigned long lastHeartbeatMs = 0;
unsigned long heartbeatEveryMs = 3000;

CRGB modeColor(const String& mode) {
  if (mode == "red") return CRGB::Red;
  if (mode == "green") return CRGB::Green;
  if (mode == "blue") return CRGB::Blue;
  if (mode == "purple") return CRGB(128, 0, 128);
  if (mode == "cyan") return CRGB::Cyan;
  if (mode == "yellow") return CRGB::Yellow;
  if (mode == "warm") return CRGB(255, 150, 60);
  if (mode == "off") return CRGB::Black;
  return CRGB::White;
}

void publishOnline(bool online) {
  StaticJsonDocument<96> doc;
  doc["online"] = online;
  doc["ts"] = millis();
  char out[96];
  serializeJson(doc, out);
  mqtt.publish(TOPIC_ONLINE.c_str(), out, true);
}

void publishStatus() {
  StaticJsonDocument<256> doc;
  doc["power"] = desired.power;
  doc["mode"] = desired.mode;
  doc["brightness"] = desired.brightness;
  doc["effect"] = desired.effect;
  doc["r"] = desired.color.r;
  doc["g"] = desired.color.g;
  doc["b"] = desired.color.b;
  char out[256];
  serializeJson(doc, out);
  mqtt.publish(TOPIC_STATUS.c_str(), out, false);
}

void publishHeartbeat() {
  StaticJsonDocument<128> doc;
  doc["uptime"] = millis();
  char out[128];
  serializeJson(doc, out);
  mqtt.publish(TOPIC_HEART.c_str(), out, false);
}

void applyLedState() {
  CRGB base = desired.mode == "white" ? desired.color : modeColor(desired.mode);
  if (!desired.power || desired.mode == "off") {
    base = CRGB::Black;
  }

  int b = constrain(desired.brightness, 1, 100);
  FastLED.setBrightness(map(b, 1, 100, 2, 255));

  if (desired.effect == "none") {
    fill_solid(leds, LED_COUNT, base);
  } else if (desired.effect == "strobe") {
    bool on = (millis() / 120) % 2 == 0;
    fill_solid(leds, LED_COUNT, on ? base : CRGB::Black);
  } else if (desired.effect == "pulse") {
    uint8_t wave = beatsin8(30, 20, 255);
    CRGB c = base;
    c.nscale8_video(wave);
    fill_solid(leds, LED_COUNT, c);
  } else if (desired.effect == "wave") {
    for (int i = 0; i < LED_COUNT; i++) {
      uint8_t wave = sin8(i * 8 + millis() / 8);
      CRGB c = base;
      c.nscale8_video(wave);
      leds[i] = c;
    }
  } else if (desired.effect == "rainbow") {
    fill_rainbow(leds, LED_COUNT, millis() / 20, 7);
    for (int i = 0; i < LED_COUNT; i++) {
      leds[i].nscale8_video(map(constrain(desired.brightness, 1, 100), 1, 100, 2, 255));
    }
  }

  FastLED.show();
}

void handleCommand(const JsonDocument& doc) {
  const char* type = doc["type"] | "";
  if (String(type) == "set_state") {
    JsonVariant desiredIn = doc["desired"];
    desired.power = desiredIn["power"] | desired.power;
    desired.mode = String((const char*)desiredIn["mode"] | desired.mode.c_str());
    desired.brightness = desiredIn["brightness"] | desired.brightness;
    desired.effect = String((const char*)desiredIn["effect"] | desired.effect.c_str());

    if (!desiredIn["color"].isNull()) {
      desired.color = CRGB(
        desiredIn["color"]["r"] | desired.color.r,
        desiredIn["color"]["g"] | desired.color.g,
        desiredIn["color"]["b"] | desired.color.b
      );
    }

    publishStatus();
  }

  if (String(type) == "break_start" || String(type) == "lesson_end") {
    for (int i = 0; i < 6; i++) {
      fill_solid(leds, LED_COUNT, CRGB::White);
      FastLED.show();
      delay(140);
      fill_solid(leds, LED_COUNT, CRGB::Black);
      FastLED.show();
      delay(110);
    }
    publishStatus();
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<768> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) return;
  handleCommand(doc);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
  }
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS, TOPIC_ONLINE.c_str(), 1, true, "{\"online\":false}")) {
      mqtt.subscribe(TOPIC_CMD.c_str());
      publishOnline(true);
      publishStatus();
    } else {
      delay(1000);
    }
  }
}

void setup() {
  TOPIC_CMD = String("led/") + DEVICE_ID + "/cmd";
  TOPIC_STATUS = String("led/") + DEVICE_ID + "/status";
  TOPIC_TELE = String("led/") + DEVICE_ID + "/telemetry";
  TOPIC_HEART = String("led/") + DEVICE_ID + "/heartbeat";
  TOPIC_ONLINE = String("led/") + DEVICE_ID + "/online";

  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, LED_COUNT);
  FastLED.clear(true);

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  applyLedState();

  if (millis() - lastHeartbeatMs >= heartbeatEveryMs) {
    lastHeartbeatMs = millis();
    publishHeartbeat();
  }
}
