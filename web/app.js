/* ═══════════════════════════════════════════
	 LED Dashboard – app.js
═══════════════════════════════════════════ */

// ─── Preset modes ───────────────────────────
const MODES = [
	{ key: "white",  label: "WIT",    color: "#9ca3af" },
	{ key: "warm",   label: "WARM",   color: "#c87428" },
	{ key: "red",    label: "ROOD",   color: "#cc0000" },
	{ key: "green",  label: "GROEN",  color: "#15803d" },
	{ key: "blue",   label: "BLAUW",  color: "#1d4ed8" },
	{ key: "purple", label: "PAARS",  color: "#7e22ce" },
	{ key: "cyan",   label: "CYAAN",  color: "#0e7490" },
	{ key: "yellow", label: "GEEL",   color: "#a16207" },
	{ key: "off",    label: "UIT",    color: "#111827" }
];

const EFFECTS = [
	{ key: "wave",    label: "Golf",      desc: "Golvende beweging over de strip" },
	{ key: "pulse",   label: "Puls",      desc: "Ritmisch opflakkeren"            },
	{ key: "strobe",  label: "Strobe",    desc: "Snel flitsen"                    },
	{ key: "rainbow", label: "Regenboog", desc: "Doorlopend kleurspectrum"        }
];

const modeBase = {
	red:    [255,   0,   0],
	green:  [  0, 200,   0],
	blue:   [  0,   0, 255],
	white:  [255, 255, 255],
	purple: [160,   0, 200],
	cyan:   [  0, 220, 220],
	yellow: [255, 220,   0],
	warm:   [255, 155,  50],
	off:    [  0,   0,   0],
	custom: [255, 255, 255]
};

// ─── State ────────────────────────────────────
let state = {
	mode:    "white",
	auto:    false,
	br:      50,
	lux:     300,
	temp:    22,
	effects: { wave: false, pulse: false, strobe: false, rainbow: false },
	customColor: [255, 255, 255],
	manualTimer: {
		active: false,
		endAt: null,
		durationMs: 0
	}
};

// ─── Lux history (for chart) ─────────────────
const LUX_MAX      = 60;
const luxHistory   = [];
const LED_COUNT    = 48;

const LESSON_LED_COUNT = 28;
const LESSON_MS_PER_MINUTE = 250;
let pauseDurationMinutes = 15;
const DEFAULT_LESSON_SCHEDULE = [
	{ label: "Les 1", start: "08:30", end: "10:00" },
	{ label: "Les 2", start: "10:15", end: "11:45" },
	{ label: "Les 3", start: "12:30", end: "14:00" },
	{ label: "Les 4", start: "14:15", end: "15:45" }
];
const DEFAULT_PAUSE_MARKERS = ["10:00", "11:45", "14:00"];

let lessonSchedule = DEFAULT_LESSON_SCHEDULE.map(item => ({ ...item }));
let pauseMarkers = [...DEFAULT_PAUSE_MARKERS];
let scheduleBounds = { dayStart: 8 * 60, dayEnd: 16 * 60 };
let lessonEvents = [];

let lessonTimer = {
	running: false,
	phase: "idle",
	currentMinute: 0,
	nextEventIndex: 0,
	phaseStartedAt: 0,
	phaseDurationMs: 0,
	countdownEndsAt: 0,
	blinkUntil: 0
};

// ─── LED canvas contexts ─────────────────────
let ledCtx      = null;
let ledCtxKleur = null;
let lastLedColors = Array.from({ length: LED_COUNT }, () => [0, 0, 0]);

// ─── Inline lux chart context ─────────────────
let chartCtx = null;

// ─── Active modal ─────────────────────────────
let activeModal = null;
let backendSync = {
	enabled: false,
	ws: null,
	baseUrl: window.location.origin && window.location.origin !== "null"
		? window.location.origin
		: `${window.location.protocol}//${window.location.hostname || "127.0.0.1"}:3000`,
	lastState: null
};

// ─── Helper ───────────────────────────────────
const $ = id => document.getElementById(id);
function setText(id, val) { const el = $(id); if (el) el.textContent = val; }
function clamp(v, lo = 0, hi = 255) { return Math.max(lo, Math.min(hi, v)); }
function pad2(v) { return String(v).padStart(2, "0"); }
function formatRemaining(ms) {
	const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
	const hours = Math.floor(totalSeconds / 3600);
	const minutes = Math.floor((totalSeconds % 3600) / 60);
	const seconds = totalSeconds % 60;
	if (hours > 0) return `${hours}u ${pad2(minutes)}m ${pad2(seconds)}s`;
	return `${minutes}m ${pad2(seconds)}s`;
}

function apiUrl(path) {
	return `${backendSync.baseUrl}${path}`;
}

async function apiRequest(path, options = {}) {
	const response = await fetch(apiUrl(path), {
		headers: { "Content-Type": "application/json", ...(options.headers || {}) },
		...options
	});
	if (!response.ok) throw new Error(`HTTP ${response.status}`);
	if (response.status === 204) return null;
	return response.json();
}

function getDesiredPayload() {
	const activeEffect = EFFECTS.find(effect => state.effects[effect.key]);
	const color = state.mode === "custom"
		? { r: state.customColor[0], g: state.customColor[1], b: state.customColor[2] }
		: { r: (modeBase[state.mode] || [255, 255, 255])[0], g: (modeBase[state.mode] || [255, 255, 255])[1], b: (modeBase[state.mode] || [255, 255, 255])[2] };
	return {
		power: state.mode !== "off",
		mode: state.mode,
		auto: state.auto,
		brightness: state.br,
		color,
		effect: activeEffect ? activeEffect.key : "none"
	};
}

function applyBackendState(snapshot) {
	if (!snapshot) return;
	backendSync.lastState = snapshot;
	const desired = snapshot.desired || {};
	const telemetry = snapshot.device?.telemetry || {};
	state.mode = desired.mode || state.mode;
	state.auto = !!desired.auto;
	state.br = Number.isFinite(desired.brightness) ? desired.brightness : state.br;
	state.lux = Number.isFinite(telemetry.lux) ? telemetry.lux : state.lux;
	state.temp = Number.isFinite(telemetry.temperature) ? telemetry.temperature : state.temp;
	state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
	if (desired.effect && desired.effect !== "none") {
		state.effects[desired.effect] = true;
	}
	if (desired.color && Number.isFinite(desired.color.r) && Number.isFinite(desired.color.g) && Number.isFinite(desired.color.b)) {
		state.customColor = [desired.color.r, desired.color.g, desired.color.b];
		modeBase.custom = [...state.customColor];
		setText("custom-color-hex", rgbToHex(state.customColor));
		const sw = $("custom-color-swatch");
		if (sw) sw.style.background = rgbToHex(state.customColor);
		const picker = $("custom-color");
		if (picker) picker.value = rgbToHex(state.customColor);
	}

	const scheduler = snapshot.scheduler || {};
	const nextLessons = Array.isArray(scheduler.lessons) && scheduler.lessons.length
		? scheduler.lessons.map((lesson, index) => ({
			label: lesson.name || lesson.label || `Les ${index + 1}`,
			start: lesson.start,
			end: lesson.end
		}))
		: lessonSchedule;
	const nextBreaks = Array.isArray(scheduler.breaks) ? [...scheduler.breaks] : pauseMarkers;
	const nextPauseDuration = Number.isFinite(scheduler.pauseDurationMin) ? scheduler.pauseDurationMin : pauseDurationMinutes;
	const schedulerChanged = JSON.stringify(nextLessons) !== JSON.stringify(lessonSchedule)
		|| JSON.stringify(nextBreaks) !== JSON.stringify(pauseMarkers)
		|| nextPauseDuration !== pauseDurationMinutes;
	if (schedulerChanged) {
		lessonSchedule = nextLessons;
		pauseMarkers = nextBreaks;
		pauseDurationMinutes = nextPauseDuration;
		renderLessonConfigRows();
		rebuildLessonTimeline();
		const list = $("lesson-list");
		if (list) {
			const lessonRows = lessonSchedule.map(item => `<li>${item.label}: ${item.start} - ${item.end}</li>`);
			const pauseRows = pauseMarkers.map((value, i) => `<li>Pauze ${i + 1}: ${value} (${pauseDurationMinutes} min)</li>`);
			list.innerHTML = [...lessonRows, ...pauseRows].join("");
		}
		const pauseDurationInput = $("pause-duration-min");
		if (pauseDurationInput) pauseDurationInput.value = String(pauseDurationMinutes);
		renderLessonTimer();
	}

	luxHistory.push(state.lux);
	if (luxHistory.length > LUX_MAX) luxHistory.shift();
	renderState();
	renderLEDFrame(Date.now() / 1000);
	drawChart();
	updateModal();
	setConn(!!snapshot.device?.online, snapshot.device?.online ? "Simulator backend actief" : "Backend offline");
}

async function pushDesiredState() {
	if (!backendSync.enabled) return;
	try {
		await apiRequest("/api/command", {
			method: "POST",
			body: JSON.stringify(getDesiredPayload())
		});
	} catch {
		setConn(false, "Backend fout");
	}
}

async function pushSchedulerConfig() {
	if (!backendSync.enabled) return;
	try {
		await apiRequest("/api/scheduler", {
			method: "POST",
			body: JSON.stringify({
				enabled: lessonTimer.running,
				pauseDurationMin: pauseDurationMinutes,
				lessons: lessonSchedule.map((lesson, index) => ({ name: lesson.label || `Les ${index + 1}`, start: lesson.start, end: lesson.end })),
				breaks: pauseMarkers
			})
		});
	} catch {
		setConn(false, "Scheduler sync fout");
	}
}

async function pushSchedulerRun(enabled) {
	if (!backendSync.enabled) return;
	try {
		await apiRequest(enabled ? "/api/scheduler/start" : "/api/scheduler/stop", { method: "POST" });
	} catch {
		setConn(false, "Scheduler start/stop fout");
	}
}

function connectBackendSocket() {
	if (!backendSync.enabled) return;
	const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
	const wsUrl = `${protocol}//${new URL(backendSync.baseUrl).host}/ws`;
	const ws = new WebSocket(wsUrl);
	backendSync.ws = ws;
	ws.addEventListener("message", event => {
		try {
			const payload = JSON.parse(event.data);
			if (payload.type === "state") applyBackendState(payload.state);
		} catch {
			// ignore malformed packets
		}
	});
	ws.addEventListener("close", () => {
		if (!backendSync.enabled) return;
		setConn(false, "Backend herverbinden...");
		setTimeout(connectBackendSocket, 2000);
	});
	ws.addEventListener("error", () => {
		ws.close();
	});
}

async function initBackendSync() {
	try {
		const snapshot = await apiRequest("/api/state");
		backendSync.enabled = true;
		applyBackendState(snapshot);
		connectBackendSocket();
	} catch {
		backendSync.enabled = false;
		setConn(true, "Lokale simulator actief");
	}
}

// ═══════════════════════════════════════════════
//  LED CANVAS STRIP
// ═══════════════════════════════════════════════
function initLedCanvas() {
	const c = $("led-canvas");
	if (c) {
		c.width  = c.offsetWidth || 700;
		c.height = 44;
		ledCtx   = c.getContext("2d");
	}
	const ck = $("led-canvas-kleur");
	if (ck) {
		ck.width  = ck.offsetWidth || 700;
		ck.height = 44;
		ledCtxKleur = ck.getContext("2d");
	}
	drawSyncedLedPreviews();
}

function drawSyncedLedPreviews() {
	drawLEDCanvas(ledCtx, lastLedColors);
	drawLEDCanvas(ledCtxKleur, lastLedColors);
}

function drawLEDCanvas(ctx, colors) {
	if (!ctx) return;
	const cw = ctx.canvas.width;
	const ch = ctx.canvas.height;
	const n  = LED_COUNT;
	const pad = 5;
	const gap = 3;
	const maxSquareByWidth = (cw - pad * 2 - gap * (n - 1)) / n;
	const sq = Math.max(3, Math.min(ch - pad * 2, maxSquareByWidth));
	const contentW = n * sq + (n - 1) * gap;
	const startX = (cw - contentW) / 2;
	const y = (ch - sq) / 2;

	ctx.fillStyle = "#060610";
	ctx.fillRect(0, 0, cw, ch);

	for (let i = 0; i < n; i++) {
		const c = colors[i] || [0, 0, 0];
		ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
		ctx.fillRect(startX + i * (sq + gap), y, sq, sq);
	}
}

window.addEventListener("resize", () => {
	// Re-measure canvas widths on resize
	const c = $("led-canvas");
	if (c && ledCtx) { c.width = c.offsetWidth || 700; }
	const ck = $("led-canvas-kleur");
	if (ck && ledCtxKleur) { ck.width = ck.offsetWidth || 700; }
	drawSyncedLedPreviews();
	const lc = $("lux-chart");
	if (lc && chartCtx) { lc.width = lc.offsetWidth || 400; }
});

// ═══════════════════════════════════════════════
//  INLINE LUX CHART (status page)
// ═══════════════════════════════════════════════
function initChart() {
	const c = $("lux-chart");
	if (!c) return;
	c.width  = c.offsetWidth || 400;
	c.height = 130;
	chartCtx = c.getContext("2d");
}

function drawLuxChart(ctx, history, totalH) {
	if (!ctx) return;
	const w  = ctx.canvas.width;
	const pL = 44, pB = 22, pT = 6, pR = 6;
	const cW = w - pL - pR;
	const cH = totalH - pB - pT;
	const maxL = 1000;

	ctx.clearRect(0, 0, w, totalH);

	// chart background
	ctx.fillStyle = "#f8fafc";
	ctx.fillRect(pL, pT, cW, cH);

	// Y axis lines + labels
	ctx.font = "10px system-ui,sans-serif";
	ctx.textBaseline = "middle";
	ctx.textAlign = "right";
	[0, 250, 500, 750, 1000].forEach(val => {
		const y = pT + cH * (1 - val / maxL);
		ctx.strokeStyle = val === 0 ? "#cbd5e1" : "#e2e8f0";
		ctx.lineWidth = 1;
		ctx.beginPath(); ctx.moveTo(pL, y); ctx.lineTo(pL + cW, y); ctx.stroke();
		ctx.fillStyle = "#94a3b8";
		ctx.fillText(val === 1000 ? "1k lx" : val + " lx", pL - 5, y);
	});

	// X axis border
	ctx.strokeStyle = "#cbd5e1"; ctx.lineWidth = 1;
	ctx.beginPath(); ctx.moveTo(pL, pT + cH); ctx.lineTo(pL + cW, pT + cH); ctx.stroke();

	// X time labels
	ctx.textAlign = "center";
	ctx.textBaseline = "top";
	ctx.fillStyle = "#94a3b8";
	["60s", "45s", "30s", "15s", "nu"].forEach((label, i) => {
		const x = pL + (i / 4) * cW;
		ctx.fillText(label, x, pT + cH + 5);
	});

	if (history.length < 2) return;

	const step = cW / (LUX_MAX - 1);

	const grad = ctx.createLinearGradient(0, pT, 0, pT + cH);
	grad.addColorStop(0, "rgba(227,6,19,.28)");
	grad.addColorStop(1, "rgba(227,6,19,.02)");

	ctx.save();
	ctx.beginPath();
	ctx.rect(pL, pT, cW, cH);
	ctx.clip();

	ctx.beginPath();
	history.forEach((v, i) => {
		const x = pL + i * step, y = pT + cH - (v / maxL) * cH;
		if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
	});
	ctx.lineTo(pL + (history.length - 1) * step, pT + cH);
	ctx.lineTo(pL, pT + cH);
	ctx.closePath();
	ctx.fillStyle = grad; ctx.fill();

	ctx.beginPath();
	history.forEach((v, i) => {
		const x = pL + i * step, y = pT + cH - (v / maxL) * cH;
		if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
	});
	ctx.strokeStyle = "#e30613"; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
	ctx.restore();
}

function drawChart() {
	if (!chartCtx) return;
	drawLuxChart(chartCtx, luxHistory, 130);
}

// ═══════════════════════════════════════════════
//  TEMPERATURE ARC GAUGE
// ═══════════════════════════════════════════════
function updateTempGauge(tempC) {
	const arc = $("temp-arc"), txt = $("temp-gauge-text");
	if (!arc) return;
	const pct = Math.max(0, Math.min(1, (tempC - 10) / 30));
	arc.style.strokeDashoffset = 283 - pct * 283;
	if (txt) txt.textContent = `${Number(tempC).toFixed(1)}°C`;
}

function setActiveEffect(effectKey, enabled) {
	EFFECTS.forEach(effect => {
		state.effects[effect.key] = enabled && effect.key === effectKey;
	});
}

// ═══════════════════════════════════════════════
//  BUILD UI ELEMENTS
// ═══════════════════════════════════════════════
function buildModes() {
	const container = $("mode-buttons");
	if (!container) return;
	container.innerHTML = "";
	MODES.forEach(m => {
		const card = document.createElement("div");
		card.className = `mode-card${m.key === "off" ? " mode-card-off" : ""}`;
		card.dataset.mode = m.key;
		card.id = `mode-card-${m.key}`;
		card.onclick = () => {
			state.mode = m.key;
			state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
			renderState();
			pushDesiredState();
		};

		// preview swatch
		const preview = document.createElement("div");
		preview.className = "mode-card-preview";
		preview.style.background = m.key === "white" ? "linear-gradient(135deg,#fff 60%,#e2e8f0)" : m.color;
		if (m.key === "off") preview.style.background = "#1e293b";

		// label
		const label = document.createElement("span");
		label.className = "mode-card-label";
		label.textContent = m.label;

		// checkmark badge
		const check = document.createElement("span");
		check.className = "mode-card-check";
		check.innerHTML = `<svg viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1.5,5 4,7.5 8.5,2.5"/></svg>`;

		card.appendChild(preview);
		card.appendChild(label);
		card.appendChild(check);
		container.appendChild(card);
	});
}

const EFFECT_ICONS = {
	wave:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12 Q5 6 8 12 Q11 18 14 12 Q17 6 20 12 Q21.5 15 22 12"/></svg>`,
	pulse:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,12 6,12 8,5 10,19 12,12 14,12 16,8 18,16 20,12 22,12"/></svg>`,
	strobe:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13,2 7,13 12,13 11,22 17,11 12,11"/></svg>`,
	rainbow: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17a9 9 0 0 1 18 0"/><path d="M6 17a6 6 0 0 1 12 0"/><path d="M9 17a3 3 0 0 1 6 0"/></svg>`
};

function buildEffects() {
	const container = $("effects-list");
	if (!container) return;
	container.innerHTML = "";
	EFFECTS.forEach(e => {
		const card = document.createElement("div");
		card.className = "effect-card-new";
		card.id = `effect-card-${e.key}`;
		card.onclick = () => {
			const isActive = !!state.effects[e.key];
			setActiveEffect(e.key, !isActive);
			renderState();
			pushDesiredState();
		};

		const iconWrap = document.createElement("div");
		iconWrap.className = "effect-icon-new";
		iconWrap.innerHTML = EFFECT_ICONS[e.key] || "";

		const info = document.createElement("div");
		const name = document.createElement("div");
		name.className = "effect-name-new";
		name.textContent = e.label;
		const desc = document.createElement("div");
		desc.className = "effect-desc-new";
		desc.textContent = e.desc;
		info.appendChild(name);
		info.appendChild(desc);

		const footer = document.createElement("div");
		footer.className = "effect-footer-new";
		const badge = document.createElement("span");
		badge.className = "effect-status-badge";
		badge.id = `effect-state-${e.key}`;
		badge.textContent = "Uit";
		footer.appendChild(badge);

		card.appendChild(iconWrap);
		card.appendChild(info);
		card.appendChild(footer);
		container.appendChild(card);
	});
}

// ═══════════════════════════════════════════════
//  RENDER STATE
// ═══════════════════════════════════════════════
function renderState() {
	setText("lux-val",  `${Math.round(state.lux)} lux`);
	setText("temp-val", `${Number(state.temp).toFixed(1)}°C`);
	setText("mode-val", String(state.mode).toUpperCase());
	setText("br-val",   `${state.br}%`);

	// brightness slider
	const bSlider = $("brightness");
	if (bSlider) { bSlider.disabled = !!state.auto; bSlider.value = state.br; }
	setText("brightness-val", `${state.br}%`);
	setText("brightness-val-kleur", `${state.br}%`);

	// auto-lux checkbox
	const alCheck = $("auto-lux");
	if (alCheck) alCheck.checked = !!state.auto;

	// mode buttons
	document.querySelectorAll(".mode-card").forEach(b => {
		b.classList.toggle("active", b.dataset.mode === state.mode);
	});
	setText("kleur-current-badge", state.mode.toUpperCase());

	// effects
	const fxCount = Object.values(state.effects).filter(Boolean).length;
	const activeEffect = EFFECTS.find(effect => state.effects[effect.key]);
	const luxAverage = luxHistory.length
		? Math.round(luxHistory.reduce((sum, value) => sum + value, 0) / luxHistory.length)
		: Math.round(state.lux);
	EFFECTS.forEach(e => {
		const card  = $(`effect-card-${e.key}`);
		const badge = $(`effect-state-${e.key}`);
		if (card)  card.classList.toggle("effect-active-new", !!state.effects[e.key]);
		if (badge) badge.textContent = state.effects[e.key] ? "Actief" : "Uit";
	});
	setText("effects-summary", activeEffect ? activeEffect.label : "Geen actief");
	setText("lux-meta", `Gemiddeld ${luxAverage} lux`);
	setText("temp-meta", state.temp >= 27 ? "Boven normaal bereik" : state.temp <= 17 ? "Koele omgeving" : "Normaal bereik");
	setText("mode-meta", activeEffect ? `Effect: ${activeEffect.label}` : "Geen effect actief");
	setText("br-meta", `${state.auto ? "Auto-Lux" : "Handmatig"} geregeld`);

	// chips
	setText("status-conn",    "Actief");
	setText("status-auto",    state.auto ? "Aan" : "Uit");
	setText("status-effects", activeEffect ? activeEffect.label : "Geen actief");
	setText("status-control", state.auto ? "Sensor" : "Handmatig");
	setText("status-lesson", getLessonStatusShort());

	updateTempGauge(state.temp);
	updateManualTimerUI();
	setText("updated-at", `Laatste update: ${new Date().toLocaleTimeString()}`);
}

function updateManualTimerUI() {
	const status = $("manual-timer-status");
	const meta = $("manual-timer-meta");
	const stopBtn = $("manual-timer-stop");
	const startBtn = $("manual-timer-start");
	if (!status || !meta) return;

	if (state.manualTimer.active && state.manualTimer.endAt) {
		const remaining = Math.max(0, state.manualTimer.endAt - Date.now());
		status.textContent = formatRemaining(remaining);
		status.classList.add("active");
		meta.textContent = `LED-strip gaat uit over ${formatRemaining(remaining)}.`;
		if (stopBtn) stopBtn.disabled = false;
		if (startBtn) startBtn.textContent = "Herstart timer";
	} else {
		status.textContent = "Niet actief";
		status.classList.remove("active");
		meta.textContent = "Zet de LED-strip automatisch uit na de gekozen duur.";
		if (stopBtn) stopBtn.disabled = true;
		if (startBtn) startBtn.textContent = "Start timer";
	}
}

function stopManualTimer(timerDone = false) {
	state.manualTimer.active = false;
	state.manualTimer.endAt = null;
	state.manualTimer.durationMs = 0;

	if (timerDone) {
		const statusEl = $("manual-timer-status");
		if (statusEl) {
			statusEl.textContent = "Timer afgelopen!";
			statusEl.classList.add("active", "timer-done");
			setTimeout(() => {
				statusEl.classList.remove("active", "timer-done");
				updateManualTimerUI();
			}, 4000);
		}
		document.querySelectorAll(".led-strip-wrap").forEach(el => {
			el.classList.add("blink-alert");
			setTimeout(() => el.classList.remove("blink-alert"), 3200);
		});
	} else {
		updateManualTimerUI();
	}
}

function startManualTimer() {
	const valueEl = $("manual-timer-value");
	const unitEl = $("manual-timer-unit");
	if (!valueEl || !unitEl) return;

	const rawValue = Number(valueEl.value);
	const safeValue = Math.max(1, Math.min(240, Number.isFinite(rawValue) ? rawValue : 10));
	valueEl.value = safeValue;
	const multiplier = unitEl.value === "hours"
		? 60 * 60 * 1000
		: unitEl.value === "seconds"
			? 1000
			: 60 * 1000;
	const durationMs = safeValue * multiplier;

	state.manualTimer.active = true;
	state.manualTimer.durationMs = durationMs;
	state.manualTimer.endAt = Date.now() + durationMs;
	updateManualTimerUI();
}

function setConn(ok, text) {
	const dot = $("conn-dot"), txt = $("conn-text");
	if (dot) { dot.className = `dot ${ok ? "ok" : "err"}`; }
	if (txt) txt.textContent = text;
	setText("status-conn", ok ? "Actief" : "Verbroken");
}

// ═══════════════════════════════════════════════
//  LED FRAME
// ═══════════════════════════════════════════════
function renderLEDFrame(t) {
	const colors = Array.from({ length: LED_COUNT }, () => [0, 0, 0]);
	const anyFX  = Object.values(state.effects).some(Boolean);
	const rawBase = state.mode === "custom"
		? state.customColor
		: (modeBase[state.mode] || [0, 0, 0]);
	const finalBr = state.auto ? Math.max(0.01, Math.min(1, state.lux / 1000)) : state.br / 100;
	const base = rawBase.map(c => Math.floor(c * finalBr));
	const peak = Math.max(1, rawBase[0], rawBase[1], rawBase[2]);
	const tint = [rawBase[0] / peak, rawBase[1] / peak, rawBase[2] / peak];
	const scaledBase = factor => [
		clamp(Math.floor(base[0] * factor)),
		clamp(Math.floor(base[1] * factor)),
		clamp(Math.floor(base[2] * factor))
	];

	if (anyFX) {
		if (state.effects.wave) {
			const center = (t * 18) % (LED_COUNT + 24);
			for (let i = 0; i < LED_COUNT; i++) {
				const d = Math.abs(i - center);
				if (d < 14) {
					const f = Math.max(0, 1 - (d / 14) ** 2);
					colors[i] = scaledBase(f);
				}
			}
		}
		if (state.effects.pulse) {
			const wave = Math.abs(Math.sin(t * 1.5));
			for (let i = 0; i < LED_COUNT; i++) {
				const pulseColor = scaledBase(0.25 + wave * 0.75);
				colors[i] = [
					clamp(Math.max(colors[i][0], pulseColor[0])),
					clamp(Math.max(colors[i][1], pulseColor[1])),
					clamp(Math.max(colors[i][2], pulseColor[2]))
				];
			}
		}
		if (state.effects.strobe) {
			for (let i = 0; i < LED_COUNT; i++) {
				if (Math.random() < 0.35) {
					colors[i] = scaledBase(1);
				} else {
					colors[i] = scaledBase(0.08);
				}
			}
		}
		if (state.effects.rainbow) {
			for (let i = 0; i < LED_COUNT; i++) {
				const h = ((i * 8 + t * 120) % 360) / 360;
				const s = h * 6, f = s - Math.floor(s);
				let r = 0, g = 0, b = 0;
				if      (s < 1) { r = 255; g = Math.floor(255 * f); }
				else if (s < 2) { r = Math.floor(255 * (1 - f)); g = 255; }
				else if (s < 3) { g = 255; b = Math.floor(255 * f); }
				else if (s < 4) { g = Math.floor(255 * (1 - f)); b = 255; }
				else if (s < 5) { r = Math.floor(255 * f); b = 255; }
				else            { r = 255; b = Math.floor(255 * (1 - f)); }
				const tr = Math.floor(r * tint[0] * finalBr);
				const tg = Math.floor(g * tint[1] * finalBr);
				const tb = Math.floor(b * tint[2] * finalBr);
				colors[i] = [clamp(Math.max(colors[i][0], tr)), clamp(Math.max(colors[i][1], tg)), clamp(Math.max(colors[i][2], tb))];
			}
		}
	} else {
		for (let i = 0; i < LED_COUNT; i++) colors[i] = base;
	}

	lastLedColors = colors.map(pixel => [...pixel]);
	drawSyncedLedPreviews();
}

// ═══════════════════════════════════════════════
//  MODAL SYSTEM
// ═══════════════════════════════════════════════
function rgbToHex(rgb) {
	return "#" + rgb.map(v => v.toString(16).padStart(2, "0")).join("");
}

const MODALS = {
	lux: {
		title: "Lichtsterkte",
		html() {
			return `
				<div class="modal-big-num">
					<span id="m-lux-val">${Math.round(state.lux)}</span>
					<span class="modal-unit">lux</span>
				</div>
				<div class="modal-stats-row">
					<div class="modal-stat"><div class="modal-stat-label">Min (sessie)</div><div class="modal-stat-val" id="m-lux-min">--</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Max (sessie)</div><div class="modal-stat-val" id="m-lux-max">--</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Gemiddeld</div><div class="modal-stat-val" id="m-lux-avg">--</div></div>
				</div>
				<canvas id="m-chart" class="modal-chart-canvas"></canvas>`;
		},
		init() {
			const c = $("m-chart");
			if (c) { c.width = c.offsetWidth || 560; c.height = 180; }
		},
		update() {
			setText("m-lux-val", Math.round(state.lux));
			if (luxHistory.length) {
				const min = Math.min(...luxHistory), max = Math.max(...luxHistory);
				const avg = Math.round(luxHistory.reduce((a, b) => a + b, 0) / luxHistory.length);
				setText("m-lux-min", min + " lux");
				setText("m-lux-max", max + " lux");
				setText("m-lux-avg", avg + " lux");
			}
			const c = $("m-chart");
			if (c) drawLuxChart(c.getContext("2d"), luxHistory, 180);
		}
	},

	temp: {
		title: "Temperatuur",
		html() {
			return `
				<div class="modal-stats-row" style="margin-bottom:24px">
					<div class="modal-stat"><div class="modal-stat-label">Sensor minimum</div><div class="modal-stat-val">10°C</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Sensor maximum</div><div class="modal-stat-val">40°C</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Normaal binnenklimaat</div><div class="modal-stat-val">18–22°C</div></div>
				</div>
				<div class="modal-gauge-wrap" style="padding:24px 0 8px">
					<svg class="modal-temp-svg" viewBox="0 0 320 175">
						<defs>
							<linearGradient id="tg2" x1="0%" y1="0%" x2="100%" y2="0%">
								<stop offset="0%" stop-color="#3b82f6"/>
								<stop offset="40%" stop-color="#22c55e"/>
								<stop offset="100%" stop-color="#ef4444"/>
							</linearGradient>
						</defs>
						<path d="M 30 158 A 130 130 0 0 1 290 158" fill="none" stroke="#e5e7eb" stroke-width="22" stroke-linecap="round"/>
						<path id="m-temp-arc" d="M 30 158 A 130 130 0 0 1 290 158" fill="none" stroke="url(#tg2)" stroke-width="22" stroke-linecap="round" stroke-dasharray="408" stroke-dashoffset="408"/>
						<text x="160" y="132" text-anchor="middle" font-size="44" font-weight="800" fill="#0f172a" font-family="-apple-system,sans-serif" id="m-temp-text">--°C</text>
						<text x="30"  y="176" text-anchor="middle" font-size="13" fill="#9ca3af" font-family="-apple-system,sans-serif">10°C</text>
						<text x="290" y="176" text-anchor="middle" font-size="13" fill="#9ca3af" font-family="-apple-system,sans-serif">40°C</text>
					</svg>
				</div>`;
		},
		init() {},
		update() {
			const arc = $("m-temp-arc"), txt = $("m-temp-text");
			if (arc) {
				const pct = Math.max(0, Math.min(1, (state.temp - 10) / 30));
				arc.style.strokeDashoffset = 408 - pct * 408;
			}
			if (txt) txt.textContent = `${Number(state.temp).toFixed(1)}°C`;
		}
	},

	modus: {
		title: "Modus",
		html() {
			const base = modeBase[state.mode] || [0, 0, 0];
			const hex  = state.mode === "custom" ? rgbToHex(state.customColor) : rgbToHex(base);
			const fxCount = Object.values(state.effects).filter(Boolean).length;
			return `
				<div class="modal-modus-swatch" id="m-mode-swatch" style="background:${hex}"></div>
				<div class="modal-big-num" style="font-size:36px;margin-bottom:16px"><span id="m-mode-name">${state.mode.toUpperCase()}</span></div>
				<div class="modal-stats-row">
					<div class="modal-stat"><div class="modal-stat-label">Effecten actief</div><div class="modal-stat-val" id="m-mode-fx">${fxCount}</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Helderheid</div><div class="modal-stat-val" id="m-mode-br">${state.br}%</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Regeling</div><div class="modal-stat-val" id="m-mode-ctrl">${state.auto ? "Auto-Lux" : "Handmatig"}</div></div>
				</div>`;
		},
		init() {},
		update() {
			const base = modeBase[state.mode] || [0, 0, 0];
			const hex  = state.mode === "custom" ? rgbToHex(state.customColor) : rgbToHex(base);
			const sw   = $("m-mode-swatch");
			if (sw) sw.style.background = hex;
			setText("m-mode-name", state.mode.toUpperCase());
			setText("m-mode-fx",   Object.values(state.effects).filter(Boolean).length);
			setText("m-mode-br",   state.br + "%");
			setText("m-mode-ctrl", state.auto ? "Auto-Lux" : "Handmatig");
		}
	},

	helderheid: {
		title: "Helderheid",
		html() {
			return `
				<div class="modal-big-num">
					<span id="m-br-val">${state.br}</span>
					<span class="modal-unit">%</span>
				</div>
				<div class="modal-br-track">
					<div class="modal-br-fill" id="m-br-fill" style="width:${state.br}%"></div>
				</div>
				<div class="modal-stats-row">
					<div class="modal-stat"><div class="modal-stat-label">Regeling</div><div class="modal-stat-val" id="m-br-mode">${state.auto ? "Auto-Lux" : "Handmatig"}</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Sensor lux</div><div class="modal-stat-val" id="m-br-lux">${Math.round(state.lux)} lux</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Status</div><div class="modal-stat-val" id="m-br-status">${state.br > 0 ? "Aan" : "Uit"}</div></div>
				</div>`;
		},
		init() {},
		update() {
			setText("m-br-val", state.br);
			const fill = $("m-br-fill");
			if (fill) fill.style.width = state.br + "%";
			setText("m-br-mode",   state.auto ? "Auto-Lux" : "Handmatig");
			setText("m-br-lux",    Math.round(state.lux) + " lux");
			setText("m-br-status", state.br > 0 ? "Aan" : "Uit");
		}
	}
};

function openModal(type) {
	const m = MODALS[type];
	if (!m) return;
	activeModal = type;
	setText("modal-title", m.title);
	const body = $("modal-body");
	if (body) body.innerHTML = m.html();
	$("modal-overlay").classList.add("open");
	requestAnimationFrame(() => { m.init(); m.update(); });
}

function closeModal() {
	activeModal = null;
	$("modal-overlay").classList.remove("open");
}

function updateModal() {
	if (!activeModal) return;
	const m = MODALS[activeModal];
	if (m && m.update) m.update();
}

// ═══════════════════════════════════════════════
//  NAVIGATION
// ═══════════════════════════════════════════════
function initNav() {
	document.querySelectorAll(".nav-btn").forEach(btn => {
		btn.addEventListener("click", () => {
			const page = btn.dataset.page;
			document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
			document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
			btn.classList.add("active");
			const pageEl = $(`page-${page}`);
			if (pageEl) pageEl.classList.add("active");
			// Re-init canvases after layout shift
			if (page === "status") {
				setTimeout(() => {
					initChart();
					const c = $("led-canvas");
					if (c) { c.width = c.offsetWidth || 700; ledCtx = c.getContext("2d"); }
					drawSyncedLedPreviews();
					drawChart();
				}, 30);
			} else if (page === "kleur") {
				setTimeout(() => {
					const ck = $("led-canvas-kleur");
					if (ck) { ck.width = ck.offsetWidth || 700; ledCtxKleur = ck.getContext("2d"); }
					drawSyncedLedPreviews();
				}, 30);
			}
		});
	});
}

function hhmmToMin(value) {
	const [h, m] = String(value).split(":").map(Number);
	return (h * 60) + m;
}

function minToHhmm(total) {
	const h = Math.floor(total / 60);
	const m = total % 60;
	return `${pad2(h)}:${pad2(m)}`;
}

function isValidHhmm(value) {
	if (!/^\d{2}:\d{2}$/.test(String(value))) return false;
	const [h, m] = String(value).split(":").map(Number);
	return h >= 0 && h <= 23 && m >= 0 && m <= 59;
}

function createLessonRow(start = "08:30", end = "10:00") {
	const row = document.createElement("div");
	row.className = "lesson-row";
	row.innerHTML = `
		<input type="time" class="input lesson-time-input lesson-start" value="${start}" />
		<input type="time" class="input lesson-time-input lesson-end" value="${end}" />
		<button type="button" class="btn btn-secondary lesson-remove-btn" aria-label="Verwijder les">X</button>`;
	const removeBtn = row.querySelector(".lesson-remove-btn");
	if (removeBtn) removeBtn.addEventListener("click", () => row.remove());
	return row;
}

function createPauseRow(value = "10:00") {
	const row = document.createElement("div");
	row.className = "pause-row";
	row.innerHTML = `
		<input type="time" class="input lesson-time-input pause-time" value="${value}" />
		<button type="button" class="btn btn-secondary lesson-remove-btn" aria-label="Verwijder pauze">X</button>`;
	const removeBtn = row.querySelector(".lesson-remove-btn");
	if (removeBtn) removeBtn.addEventListener("click", () => row.remove());
	return row;
}

function renderLessonConfigRows() {
	const lessonRows = $("lesson-rows");
	const pauseRows = $("pause-rows");
	if (!lessonRows || !pauseRows) return;

	lessonRows.innerHTML = "";
	lessonSchedule.forEach(item => lessonRows.appendChild(createLessonRow(item.start, item.end)));

	pauseRows.innerHTML = "";
	pauseMarkers.forEach(value => pauseRows.appendChild(createPauseRow(value)));
}

function collectLessonsFromRows() {
	const rows = Array.from(document.querySelectorAll("#lesson-rows .lesson-row"));
	if (!rows.length) return { ok: false, message: "Voeg minstens 1 les toe." };

	const parsed = [];
	for (let i = 0; i < rows.length; i++) {
		const startVal = rows[i].querySelector(".lesson-start")?.value || "";
		const endVal = rows[i].querySelector(".lesson-end")?.value || "";
		if (!isValidHhmm(startVal) || !isValidHhmm(endVal)) {
			return { ok: false, message: `Les ${i + 1} heeft een ongeldige tijd.` };
		}
		const startMin = hhmmToMin(startVal);
		const endMin = hhmmToMin(endVal);
		if (endMin <= startMin) {
			return { ok: false, message: `Les ${i + 1}: einde moet na start liggen.` };
		}
		parsed.push({ start: startVal, end: endVal, startMin, endMin });
	}

	parsed.sort((a, b) => a.startMin - b.startMin);
	const lessons = parsed.map((item, idx) => ({ label: `Les ${idx + 1}`, start: item.start, end: item.end }));
	return { ok: true, lessons };
}

function collectPausesFromRows() {
	const rows = Array.from(document.querySelectorAll("#pause-rows .pause-row"));
	const pauses = [];
	for (let i = 0; i < rows.length; i++) {
		const pauseVal = rows[i].querySelector(".pause-time")?.value || "";
		if (!pauseVal) continue;
		if (!isValidHhmm(pauseVal)) {
			return { ok: false, message: `Pauze ${i + 1} heeft een ongeldige tijd.` };
		}
		pauses.push(pauseVal);
	}
	return { ok: true, pauses };
}

function rebuildLessonTimeline() {
	const sortedLessons = lessonSchedule
		.map((item, i) => ({ ...item, startMin: hhmmToMin(item.start), endMin: hhmmToMin(item.end), order: i }))
		.sort((a, b) => a.startMin - b.startMin);

	if (!sortedLessons.length) {
		scheduleBounds = { dayStart: 8 * 60, dayEnd: 16 * 60 };
		lessonEvents = [];
		return;
	}

	scheduleBounds = {
		dayStart: sortedLessons[0].startMin,
		dayEnd: sortedLessons[sortedLessons.length - 1].endMin
	};

	const eventsRaw = [];
	sortedLessons.forEach(lesson => {
		eventsRaw.push({
			minute: lesson.endMin,
			type: "lesson-end",
			label: `${lesson.label} einde`,
			lesson
		});
	});
	pauseMarkers.forEach(value => {
		eventsRaw.push({
			minute: hhmmToMin(value),
			type: "pause",
			label: `Pauze ${value}`
		});
	});

	const byMinute = new Map();
	eventsRaw.forEach(ev => {
		if (ev.minute < scheduleBounds.dayStart || ev.minute > scheduleBounds.dayEnd) return;
		if (!byMinute.has(ev.minute)) {
			byMinute.set(ev.minute, ev);
			return;
		}
		const existing = byMinute.get(ev.minute);
		if (existing.type !== "pause" && ev.type === "pause") byMinute.set(ev.minute, ev);
	});

	lessonEvents = Array.from(byMinute.values()).sort((a, b) => a.minute - b.minute);
}

function scheduleMinToLed(minuteValue) {
	const span = Math.max(1, scheduleBounds.dayEnd - scheduleBounds.dayStart);
	const p = (minuteValue - scheduleBounds.dayStart) / span;
	return Math.max(0, Math.min(LESSON_LED_COUNT - 1, Math.round(p * (LESSON_LED_COUNT - 1))));
}

function getCurrentLessonForMinute(minuteValue) {
	return lessonSchedule.find(lesson => {
		const s = hhmmToMin(lesson.start);
		const e = hhmmToMin(lesson.end);
		return minuteValue >= s && minuteValue <= e;
	}) || null;
}

function resetLessonTimerState() {
	lessonTimer.running = false;
	lessonTimer.phase = "idle";
	lessonTimer.currentMinute = scheduleBounds.dayStart;
	lessonTimer.nextEventIndex = 0;
	lessonTimer.phaseStartedAt = 0;
	lessonTimer.phaseDurationMs = 0;
	lessonTimer.countdownEndsAt = 0;
	lessonTimer.blinkUntil = 0;
}

function buildLessonUI() {
	rebuildLessonTimeline();
	resetLessonTimerState();

	const strip = $("lesson-led-strip");
	if (strip) {
		strip.innerHTML = "";
		for (let i = 0; i < LESSON_LED_COUNT; i++) {
			const led = document.createElement("div");
			led.className = "lesson-led";
			led.id = `lesson-led-${i}`;
			strip.appendChild(led);
		}
	}
	renderLessonConfigRows();

	const list = $("lesson-list");
	if (list) {
		const lessonRows = lessonSchedule.map(item => `<li>${item.label}: ${item.start} - ${item.end}</li>`);
		const pauseRows = pauseMarkers.map((value, i) => `<li>Pauze ${i + 1}: ${value} (${pauseDurationMinutes} min)</li>`);
		list.innerHTML = [...lessonRows, ...pauseRows].join("");
	}

	const pauseDurationInput = $("pause-duration-min");
	if (pauseDurationInput) pauseDurationInput.value = String(pauseDurationMinutes);

	renderLessonTimer();
}

function setLessonPhase(phase, durationMs = 0, countdownEndsAt = 0) {
	lessonTimer.phase = phase;
	lessonTimer.phaseStartedAt = Date.now();
	lessonTimer.phaseDurationMs = durationMs;
	lessonTimer.countdownEndsAt = countdownEndsAt;
}

function applyLessonConfig() {
	const lessonResult = collectLessonsFromRows();
	if (!lessonResult.ok) {
		setText("lesson-current", lessonResult.message);
		return;
	}

	const pauseResult = collectPausesFromRows();
	if (!pauseResult.ok) {
		setText("lesson-current", pauseResult.message);
		return;
	}

	const pauseDurationInput = $("pause-duration-min");
	const pauseRaw = Number(pauseDurationInput ? pauseDurationInput.value : pauseDurationMinutes);
	pauseDurationMinutes = Math.max(1, Math.min(120, Number.isFinite(pauseRaw) ? pauseRaw : 15));

	lessonSchedule = lessonResult.lessons;
	pauseMarkers = pauseResult.pauses;
	buildLessonUI();
	setText("lesson-current", "Lesuren en pauzes toegepast.");
	pushSchedulerConfig();
}

function startLessonTimerSimulation() {
	if (!lessonEvents.length) {
		setText("lesson-current", "Geen geldige events: zet lesuren/pauzes en klik Toepassen.");
		return;
	}
	lessonTimer.running = true;
	lessonTimer.phase = "run";
	lessonTimer.currentMinute = scheduleBounds.dayStart;
	lessonTimer.nextEventIndex = 0;
	lessonTimer.phaseStartedAt = Date.now();
	renderLessonTimer();
	pushSchedulerConfig();
	pushSchedulerRun(true);
}

function stopLessonTimerSimulation() {
	resetLessonTimerState();
	renderLessonTimer();
	pushSchedulerRun(false);
}

function getLessonCurrentLabel() {
	if (lessonTimer.phase === "done") return "Laatste tijdstip bereikt";
	if (!lessonTimer.running) return "Inactief";
	const nextEvent = lessonEvents[lessonTimer.nextEventIndex] || null;
	if (lessonTimer.phase === "run" && nextEvent) {
		const kind = nextEvent.type === "pause" ? "pauze" : "leseinde";
		return `Witte LED telt op naar ${kind} (${minToHhmm(nextEvent.minute)}).`;
	}
	if (lessonTimer.phase === "countdown") {
		const leftMs = Math.max(0, lessonTimer.countdownEndsAt - Date.now());
		const leftMin = Math.ceil(leftMs / LESSON_MS_PER_MINUTE);
		return `Pauzetimer (${pauseDurationMinutes} min): nog ${leftMin} min`;
	}
	if (lessonTimer.phase === "blink") return "Event bereikt: waarschuwing knippert";
	return "Actief";
}

function getLessonStatusShort() {
	if (lessonTimer.phase === "done") return "Klaar";
	if (!lessonTimer.running) return "Inactief";
	if (lessonTimer.phase === "countdown") return "Pauze timer";
	if (lessonTimer.phase === "blink") return "Waarschuwing";
	return "Lopend";
}

function renderLessonTimer() {
	const phaseEl = $("lesson-phase");
	const currentEl = $("lesson-current");
	const windowEl = $("lesson-window");
	if (phaseEl) {
		phaseEl.textContent = lessonTimer.running ? "Actief" : "Inactief";
		phaseEl.classList.toggle("running", lessonTimer.running);
	}

	const activeLesson = getCurrentLessonForMinute(lessonTimer.currentMinute);
	const nextLesson = lessonSchedule.find(item => hhmmToMin(item.start) >= lessonTimer.currentMinute) || null;
	const showLesson = activeLesson || nextLesson;
	if (currentEl) currentEl.textContent = getLessonCurrentLabel();
	if (windowEl) {
		windowEl.textContent = showLesson
			? `Start - Einde: ${showLesson.start} - ${showLesson.end}`
			: "Start - Einde: --";
	}

	const leds = Array.from({ length: LESSON_LED_COUNT }, () => "");
	if (lessonTimer.running) {
		const nextEvent = lessonEvents[lessonTimer.nextEventIndex] || null;
		if (nextEvent && lessonTimer.phase !== "done") {
			leds[scheduleMinToLed(nextEvent.minute)] = "on-green";
		}

		if (lessonTimer.phase === "run") {
			const cursor = scheduleMinToLed(lessonTimer.currentMinute);
			for (let i = 0; i <= cursor; i++) leds[i] = "on-base";
			leds[cursor] = "on-white";
		}

		if (lessonTimer.phase === "countdown") {
			const elapsed = Date.now() - lessonTimer.phaseStartedAt;
			const ratio = Math.max(0, Math.min(1, elapsed / Math.max(1, lessonTimer.phaseDurationMs)));
			const litCount = Math.max(0, Math.round((1 - ratio) * LESSON_LED_COUNT));
			for (let i = 0; i < litCount; i++) leds[i] = "on-white";
		}

		if (lessonTimer.phase === "blink") {
			const blinkOn = Math.floor(Date.now() / 200) % 2 === 0;
			if (blinkOn) {
				for (let i = 0; i < LESSON_LED_COUNT; i++) leds[i] = "on-red";
			}
		}
	}

	for (let i = 0; i < LESSON_LED_COUNT; i++) {
		const ledEl = $(`lesson-led-${i}`);
		if (!ledEl) continue;
		ledEl.className = `lesson-led${leds[i] ? ` ${leds[i]}` : ""}`;
	}
}

function updateLessonTimerTick() {
	if (!lessonTimer.running) return;
	const now = Date.now();

	if (lessonTimer.phase === "run") {
		lessonTimer.currentMinute += 0.4;
		const nextEvent = lessonEvents[lessonTimer.nextEventIndex] || null;
		if (nextEvent && lessonTimer.currentMinute >= nextEvent.minute) {
			lessonTimer.currentMinute = nextEvent.minute;
			const countdownMs = pauseDurationMinutes * LESSON_MS_PER_MINUTE;
			setLessonPhase("countdown", countdownMs, now + countdownMs);
		}
		renderLessonTimer();
		return;
	}

	if (lessonTimer.phase === "countdown") {
		if (now < lessonTimer.countdownEndsAt) {
			renderLessonTimer();
			return;
		}
		lessonTimer.nextEventIndex += 1;
		setLessonPhase("blink", 1800);
		renderLessonTimer();
		return;
	}

	if (lessonTimer.phase === "blink") {
		if (now - lessonTimer.phaseStartedAt < lessonTimer.phaseDurationMs) {
			renderLessonTimer();
			return;
		}
		if (lessonTimer.nextEventIndex >= lessonEvents.length) {
			lessonTimer.phase = "done";
			lessonTimer.running = false;
			renderLessonTimer();
			return;
		}
		setLessonPhase("run", 0);
		renderLessonTimer();
		return;
	}
}

// ═══════════════════════════════════════════════
//  EVENT LISTENERS
// ═══════════════════════════════════════════════
// Stat card clicks → open modal
document.querySelectorAll(".stat-card.clickable").forEach(card => {
	card.addEventListener("click", () => openModal(card.dataset.modal));
});

// Modal close
$("modal-close").addEventListener("click", closeModal);
$("modal-overlay").addEventListener("click", e => { if (e.target === $("modal-overlay")) closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

// Auto-lux toggle
$("auto-lux").addEventListener("change", () => {
	state.auto = $("auto-lux").checked;
	renderState();
	pushDesiredState();
});

// Brightness slider (live)
$("brightness").addEventListener("input", () => {
	if (state.auto) return;
	state.br = Number($("brightness").value);
	setText("brightness-val", `${state.br}%`);
	setText("brightness-val-kleur", `${state.br}%`);
	renderState();
	pushDesiredState();
});

// Automation sliders
["lux-threshold", "motion-timeout", "dim-min"].forEach(id => {
	const el = $(id);
	if (!el) return;
	el.addEventListener("input", () => {
		const map = { "lux-threshold": ["lux-threshold-val", v => `${v} lux`], "motion-timeout": ["motion-timeout-val", v => `${v}s`], "dim-min": ["dim-min-val", v => `${v}%`] };
		const [outId, fmt] = map[id];
		setText(outId, fmt(el.value));
	});
});

// Custom colour picker
function hexToRgb(hex) {
	return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}

const colorPicker = $("custom-color");
if (colorPicker) {
	colorPicker.addEventListener("input", () => {
		const hex = colorPicker.value;
		const sw = $("custom-color-swatch");
		if (sw) sw.style.background = hex;
		setText("custom-color-hex", hex);
	});
}

const applyBtn = $("apply-custom-color");
if (applyBtn) {
	applyBtn.addEventListener("click", () => {
		const hex = colorPicker.value;
		const rgb = hexToRgb(hex);
		state.customColor = rgb;
		modeBase.custom   = rgb;
		state.mode = "custom";
		state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
		renderState();
		pushDesiredState();
	});
}

const timerStartBtn = $("manual-timer-start");
if (timerStartBtn) {
	timerStartBtn.addEventListener("click", startManualTimer);
}

const timerStopBtn = $("manual-timer-stop");
if (timerStopBtn) {
	timerStopBtn.addEventListener("click", stopManualTimer);
}

const lessonTimerStartBtn = $("lesson-timer-start");
if (lessonTimerStartBtn) {
	lessonTimerStartBtn.addEventListener("click", startLessonTimerSimulation);
}

const lessonTimerStopBtn = $("lesson-timer-stop");
if (lessonTimerStopBtn) {
	lessonTimerStopBtn.addEventListener("click", stopLessonTimerSimulation);
}

const lessonConfigApplyBtn = $("lesson-config-apply");
if (lessonConfigApplyBtn) {
	lessonConfigApplyBtn.addEventListener("click", applyLessonConfig);
}

const addLessonRowBtn = $("add-lesson-row");
if (addLessonRowBtn) {
	addLessonRowBtn.addEventListener("click", () => {
		const container = $("lesson-rows");
		if (!container) return;
		const lastEnd = container.querySelector(".lesson-row:last-child .lesson-end")?.value;
		const start = isValidHhmm(lastEnd) ? lastEnd : "08:30";
		const endMin = hhmmToMin(start) + 60;
		const end = endMin > (23 * 60 + 59) ? "23:59" : minToHhmm(endMin);
		container.appendChild(createLessonRow(start, end));
	});
}

const addPauseRowBtn = $("add-pause-row");
if (addPauseRowBtn) {
	addPauseRowBtn.addEventListener("click", () => {
		const container = $("pause-rows");
		if (!container) return;
		const lastPause = container.querySelector(".pause-row:last-child .pause-time")?.value;
		const nextMin = isValidHhmm(lastPause) ? Math.min(hhmmToMin(lastPause) + 15, 23 * 60 + 59) : 10 * 60;
		container.appendChild(createPauseRow(minToHhmm(nextMin)));
	});
}

document.querySelectorAll(".preset-btn[data-minutes]").forEach(btn => {
	btn.addEventListener("click", () => {
		const valueEl = $("manual-timer-value");
		const unitEl = $("manual-timer-unit");
		if (!valueEl || !unitEl) return;
		valueEl.value = Number(btn.dataset.minutes) || 10;
		unitEl.value = "minutes";
		startManualTimer();
	});
});

// ═══════════════════════════════════════════════
//  SIMULATION TICK
// ═══════════════════════════════════════════════
function tick() {
	if (backendSync.enabled) {
		const t = Date.now() / 1000;
		if (state.manualTimer.active && state.manualTimer.endAt) {
			if (Date.now() >= state.manualTimer.endAt) {
				state.mode = "off";
				state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
				pushDesiredState();
				stopManualTimer(true);
			}
		}
		updateLessonTimerTick();
		renderState();
		renderLEDFrame(t);
		updateModal();
		return;
	}

	const t = Date.now() / 1000;
	state.lux  = Math.round(300 + 250 * Math.sin(t * 0.6));
	state.temp = 22 + 2.2 * Math.sin(t * 0.2);

	if (state.auto) {
		state.br = Math.round(Math.max(1, Math.min(100, state.lux / 10)));
	}

	if (state.manualTimer.active && state.manualTimer.endAt) {
		if (Date.now() >= state.manualTimer.endAt) {
				state.mode = "off";
			state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
			stopManualTimer(true);
		}
	}

	updateLessonTimerTick();

	luxHistory.push(state.lux);
	if (luxHistory.length > LUX_MAX) luxHistory.shift();

	renderState();
	renderLEDFrame(t);
	drawChart();
	updateModal();
	setConn(true, "Simulator actief");
}

// ═══════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════
buildModes();
buildEffects();
buildLessonUI();
initNav();
initChart();
initLedCanvas();
renderState();
initBackendSync();
updateManualTimerUI();
tick();
setInterval(tick, 120);
