export function makeTopics(deviceId) {
  const base = `led/${deviceId}`;
  return {
    cmd: `${base}/cmd`,
    status: `${base}/status`,
    telemetry: `${base}/telemetry`,
    heartbeat: `${base}/heartbeat`,
    online: `${base}/online`
  };
}
