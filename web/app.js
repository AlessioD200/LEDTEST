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

// ─── LED canvas contexts ─────────────────────
let ledCtx      = null;
let ledCtxKleur = null;

// ─── Inline lux chart context ─────────────────
let chartCtx = null;

// ─── Active modal ─────────────────────────────
let activeModal = null;

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
}

function drawLEDCanvas(ctx, colors) {
	if (!ctx) return;
	const w = ctx.canvas.width;
	const h = ctx.canvas.height;
	const n = 140;
	const gap  = 2;
	const ledW = (w - gap * (n - 1)) / n;
	const padV = 5;
	const ledH = h - padV * 2;

	ctx.fillStyle = "#060610";
	ctx.fillRect(0, 0, w, h);

	for (let i = 0; i < n; i++) {
		const c = colors[i] || [0, 0, 0];
		const x = i * (ledW + gap);
		ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
		ctx.fillRect(Math.floor(x), padV, Math.max(1, Math.floor(ledW)), ledH);
	}
}

window.addEventListener("resize", () => {
	// Re-measure canvas widths on resize
	const c = $("led-canvas");
	if (c && ledCtx) { c.width = c.offsetWidth || 700; }
	const ck = $("led-canvas-kleur");
	if (ck && ledCtxKleur) { ck.width = ck.offsetWidth || 700; }
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
	c.height = 110;
	chartCtx = c.getContext("2d");
}

function drawLuxChart(ctx, history, h) {
	if (!ctx) return;
	const w = ctx.canvas.width;
	ctx.clearRect(0, 0, w, h);

	// grid
	ctx.strokeStyle = "#e2e8f0"; ctx.lineWidth = 1;
	[0.25, 0.5, 0.75].forEach(f => {
		const y = h * (1 - f);
		ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
	});

	if (history.length < 2) return;
	const maxL = 1000;
	const step = w / (LUX_MAX - 1);

	const grad = ctx.createLinearGradient(0, 0, 0, h);
	grad.addColorStop(0, "rgba(227,6,19,.28)");
	grad.addColorStop(1, "rgba(227,6,19,.02)");

	ctx.beginPath();
	history.forEach((v, i) => {
		const x = i * step, y = h - (v / maxL) * h;
		if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
	});
	ctx.lineTo((history.length - 1) * step, h); ctx.lineTo(0, h);
	ctx.closePath(); ctx.fillStyle = grad; ctx.fill();

	ctx.beginPath();
	history.forEach((v, i) => {
		const x = i * step, y = h - (v / maxL) * h;
		if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
	});
	ctx.strokeStyle = "#e30613"; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
}

function drawChart() {
	if (!chartCtx) return;
	drawLuxChart(chartCtx, luxHistory, 110);
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
		const b = document.createElement("button");
		b.className = `mode-btn${m.key === "off" ? " off" : ""}`;
		b.style.background = m.color;
		b.textContent = m.label;
		b.dataset.mode = m.key;
		b.onclick = () => {
			state.mode = m.key;
			state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
			renderState();
		};
		container.appendChild(b);
	});
}

function buildEffects() {
	const container = $("effects-list");
	if (!container) return;
	container.innerHTML = "";
	EFFECTS.forEach(e => {
		const card = document.createElement("div");
		card.className = "effect-card";

		const left = document.createElement("div");
		left.className = "effect-left";

		const info = document.createElement("div");
		const name = document.createElement("div");
		name.className = "effect-name";
		name.textContent = e.label;
		const desc = document.createElement("div");
		desc.className = "effect-desc";
		desc.textContent = e.desc;
		info.appendChild(name);
		info.appendChild(desc);

		const badge = document.createElement("span");
		badge.className = "effect-badge";
		badge.id = `effect-state-${e.key}`;
		badge.textContent = "Uit";

		left.appendChild(info);
		left.appendChild(badge);

		const toggle = document.createElement("label");
		toggle.className = "toggle";
		const check = document.createElement("input");
		check.type = "checkbox";
		check.id = `effect-${e.key}`;
		check.onchange = () => {
			setActiveEffect(e.key, check.checked);
			renderState();
		};
		const sliderSpan = document.createElement("span");
		sliderSpan.className = "toggle-slider";
		toggle.appendChild(check); toggle.appendChild(sliderSpan);

		card.appendChild(left); card.appendChild(toggle);
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
	document.querySelectorAll(".mode-btn").forEach(b => {
		b.classList.toggle("active", b.dataset.mode === state.mode);
	});

	// effects
	const fxCount = Object.values(state.effects).filter(Boolean).length;
	const activeEffect = EFFECTS.find(effect => state.effects[effect.key]);
	const luxAverage = luxHistory.length
		? Math.round(luxHistory.reduce((sum, value) => sum + value, 0) / luxHistory.length)
		: Math.round(state.lux);
	EFFECTS.forEach(e => {
		const el    = $(`effect-${e.key}`);
		const badge = $(`effect-state-${e.key}`);
		if (el) el.checked = !!state.effects[e.key];
		if (badge) { badge.textContent = state.effects[e.key] ? "Actief" : "Uit"; badge.classList.toggle("on", !!state.effects[e.key]); }
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

function stopManualTimer() {
	state.manualTimer.active = false;
	state.manualTimer.endAt = null;
	state.manualTimer.durationMs = 0;
	updateManualTimerUI();
}

function startManualTimer() {
	const valueEl = $("manual-timer-value");
	const unitEl = $("manual-timer-unit");
	if (!valueEl || !unitEl) return;

	const rawValue = Number(valueEl.value);
	const safeValue = Math.max(1, Math.min(240, Number.isFinite(rawValue) ? rawValue : 10));
	valueEl.value = safeValue;
	const multiplier = unitEl.value === "hours" ? 60 * 60 * 1000 : 60 * 1000;
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
	const colors = Array.from({ length: 140 }, () => [0, 0, 0]);
	const anyFX  = Object.values(state.effects).some(Boolean);

	if (anyFX) {
		if (state.effects.wave) {
			const center = (t * 25) % (140 + 80);
			for (let i = 0; i < 140; i++) {
				const d = Math.abs(i - center);
				if (d < 40) {
					const b = Math.max(0, 1 - (d / 40) ** 2);
					const v = Math.floor(255 * b);
					colors[i] = [v, v, v];
				}
			}
		}
		if (state.effects.pulse) {
			const wave = Math.abs(Math.sin(t * 1.5));
			for (let i = 0; i < 140; i++) {
				const v = Math.floor(255 * wave);
				colors[i] = [clamp(colors[i][0] + v), clamp(colors[i][1] + v), clamp(colors[i][2] + v)];
			}
		}
		if (state.effects.strobe) {
			for (let i = 0; i < 140; i++) {
				if (Math.random() < 0.35) colors[i] = [255, 255, 255];
			}
		}
		if (state.effects.rainbow) {
			for (let i = 0; i < 140; i++) {
				const h = ((i * 8 + t * 120) % 360) / 360;
				const s = h * 6, f = s - Math.floor(s);
				let r = 0, g = 0, b = 0;
				if      (s < 1) { r = 255; g = Math.floor(255 * f); }
				else if (s < 2) { r = Math.floor(255 * (1 - f)); g = 255; }
				else if (s < 3) { g = 255; b = Math.floor(255 * f); }
				else if (s < 4) { g = Math.floor(255 * (1 - f)); b = 255; }
				else if (s < 5) { r = Math.floor(255 * f); b = 255; }
				else            { r = 255; b = Math.floor(255 * (1 - f)); }
				colors[i] = [clamp(colors[i][0] + Math.floor(r * .75)), clamp(colors[i][1] + Math.floor(g * .75)), clamp(colors[i][2] + Math.floor(b * .75))];
			}
		}
	} else {
		const base    = modeBase[state.mode] || [0, 0, 0];
		const finalBr = state.auto ? Math.max(0.01, Math.min(1, state.lux / 1000)) : state.br / 100;
		const pixel   = base.map(c => Math.floor(c * finalBr));
		for (let i = 0; i < 140; i++) colors[i] = pixel;
	}

	drawLEDCanvas(ledCtx,      colors);
	drawLEDCanvas(ledCtxKleur, colors);
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
				<div class="modal-gauge-wrap">
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
				</div>
				<div class="modal-stats-row">
					<div class="modal-stat"><div class="modal-stat-label">Huidig</div><div class="modal-stat-val" id="m-temp-cur">--</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Min bereik</div><div class="modal-stat-val">10°C</div></div>
					<div class="modal-stat"><div class="modal-stat-label">Max bereik</div><div class="modal-stat-val">40°C</div></div>
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
			setText("m-temp-cur", `${Number(state.temp).toFixed(1)}°C`);
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
					drawChart();
				}, 30);
			} else if (page === "kleur") {
				setTimeout(() => {
					const ck = $("led-canvas-kleur");
					if (ck) { ck.width = ck.offsetWidth || 700; ledCtxKleur = ck.getContext("2d"); }
				}, 30);
			}
		});
	});
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
$("auto-lux").addEventListener("change", () => { state.auto = $("auto-lux").checked; renderState(); });

// Brightness slider (live)
$("brightness").addEventListener("input", () => {
	if (state.auto) return;
	state.br = Number($("brightness").value);
	setText("brightness-val", `${state.br}%`);
	setText("brightness-val-kleur", `${state.br}%`);
	renderState();
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
	const t = Date.now() / 1000;
	state.lux  = Math.round(300 + 250 * Math.sin(t * 0.6));
	state.temp = 22 + 2.2 * Math.sin(t * 0.2);

	if (state.auto) {
		state.br = Math.round(Math.max(1, Math.min(100, state.lux / 10)));
	}

	if (state.manualTimer.active && state.manualTimer.endAt) {
		if (Date.now() >= state.manualTimer.endAt) {
			stopManualTimer();
			state.mode = "off";
			state.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
		}
	}

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
initNav();
initChart();
initLedCanvas();
renderState();
setConn(true, "Simulator actief");
updateManualTimerUI();
tick();
setInterval(tick, 120);
