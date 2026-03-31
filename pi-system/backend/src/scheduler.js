function toMinutes(hhmm) {
  const [h, m] = String(hhmm).split(":").map(Number);
  if (!Number.isInteger(h) || !Number.isInteger(m)) return null;
  if (h < 0 || h > 23 || m < 0 || m > 59) return null;
  return h * 60 + m;
}

function nowMinutes() {
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
}

function makeDayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function buildEvents(lessons, breaks) {
  const events = [];
  lessons.forEach((l) => {
    const m = toMinutes(l.end);
    if (m !== null) events.push({ minute: m, type: "lesson-end", name: l.name || "Les" });
  });
  breaks.forEach((b) => {
    const m = toMinutes(b);
    if (m !== null) events.push({ minute: m, type: "break", name: `Pauze ${b}` });
  });
  events.sort((a, b) => a.minute - b.minute);
  return events;
}

export class Scheduler {
  constructor(stateStore, publishCommand, broadcastState) {
    this.stateStore = stateStore;
    this.publishCommand = publishCommand;
    this.broadcastState = broadcastState;
    this.timer = null;
  }

  start() {
    this.timer = setInterval(() => this.tick(), 1000);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  tick() {
    const state = this.stateStore.get();
    if (!state.scheduler.enabled) return;

    const runtime = state.scheduler.runtime || {};
    const dayKey = makeDayKey();
    const minute = nowMinutes();
    const events = buildEvents(state.scheduler.lessons, state.scheduler.breaks);
    const pauseDurationMin = Math.max(1, Number(state.scheduler.pauseDurationMin || 15));

    if (runtime.phase === "pause" && runtime.pauseEndAt && Date.now() >= runtime.pauseEndAt) {
      const next = {
        phase: "running",
        pauseEndAt: null,
        nextEvent: null
      };
      this.stateStore.patch({ scheduler: { runtime: { ...runtime, ...next } } });
      this.publishCommand({ type: "pause_end", ts: Date.now() });
      this.broadcastState(this.stateStore.get());
      return;
    }

    const currentEvent = events.find((e) => e.minute === minute);
    if (!currentEvent) return;

    const triggerKey = `${dayKey}:${currentEvent.type}:${currentEvent.minute}`;
    if (runtime.lastTriggeredKey === triggerKey) return;

    const pauseEndAt = Date.now() + pauseDurationMin * 60 * 1000;
    this.stateStore.patch({
      scheduler: {
        runtime: {
          ...runtime,
          phase: "pause",
          nextEvent: currentEvent,
          pauseEndAt,
          lastTriggeredKey: triggerKey
        }
      }
    });

    this.publishCommand({
      type: currentEvent.type === "break" ? "break_start" : "lesson_end",
      event: currentEvent,
      pauseDurationMin,
      ts: Date.now()
    });
    this.broadcastState(this.stateStore.get());
  }
}
