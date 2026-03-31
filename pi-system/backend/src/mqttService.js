import mqtt from "mqtt";

export class MqttService {
  constructor({ url, user, password, topics, onStatus, onTelemetry, onHeartbeat, onOnline }) {
    this.topics = topics;
    this.onStatus = onStatus;
    this.onTelemetry = onTelemetry;
    this.onHeartbeat = onHeartbeat;
    this.onOnline = onOnline;

    this.client = mqtt.connect(url, {
      username: user || undefined,
      password: password || undefined,
      reconnectPeriod: 2000,
      clean: true
    });

    this.client.on("connect", () => {
      this.client.subscribe([topics.status, topics.telemetry, topics.heartbeat, topics.online]);
    });

    this.client.on("message", (topic, payloadBuf) => {
      const payloadRaw = payloadBuf.toString("utf-8");
      let payload = null;
      try {
        payload = payloadRaw ? JSON.parse(payloadRaw) : null;
      } catch {
        payload = { raw: payloadRaw };
      }

      if (topic === topics.status) this.onStatus(payload);
      if (topic === topics.telemetry) this.onTelemetry(payload);
      if (topic === topics.heartbeat) this.onHeartbeat(payload);
      if (topic === topics.online) this.onOnline(payload);
    });
  }

  publishCommand(command) {
    this.client.publish(this.topics.cmd, JSON.stringify(command), { qos: 1 });
  }

  publishOnline(value) {
    this.client.publish(this.topics.online, JSON.stringify({ online: value, ts: Date.now() }), { qos: 1, retain: true });
  }
}
