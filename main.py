from machine import Pin, SPI, ADC
import apa102, socket, time, random, onewire, ds18x20, json

# --- 1. CONFIG ---
NUM_LEDS = 140
spi = SPI(1, baudrate=2000000, sck=Pin(5), mosi=Pin(18))
strip = apa102.APA102(spi, NUM_LEDS)
ldr = ADC(Pin(34))
ldr.atten(ADC.ATTN_11DB)

# DS18B20 Temperature Sensor
DATA_PIN = 4
dat = Pin(DATA_PIN)
ow = onewire.OneWire(dat)
ds = ds18x20.DS18X20(ow)
temp_roms = ds.scan()

if not temp_roms:
    print("No DS18B20 sensor found!")
else:
    print("Temperature sensor found:", temp_roms)

# --- 2. STATE ---
mode = "white"
auto_light = False
offset = 0.0
smooth_val = 2000.0
perc_val = 50
temp_val = 20.0
sensor_buffer = [2000.0] * 10
global_br = 0.5
custom_color = (255, 255, 255)
lightshow_active = {}
lightshow_start_times = {}
lightshow_last_trigger = 0
temp_read_counter = 0

scheduler_config = {
    "enabled": False,
    "pauseDurationMin": 15,
    "lessons": [],
    "breaks": [],
}


def clamp_int(value, low, high):
    try:
        value = int(value)
    except:
        return low
    if value < low:
        return low
    if value > high:
        return high
    return value

# --- 3. HTML (embedded from web folder for identical ESP32 UI) ---

WEB_INDEX_HTML = r'''<!DOCTYPE html>
<html lang="nl">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<title>LED Dashboard</title>
	<style>/* ═══════════════════════════════════════════
	 DESIGN TOKENS – light mode only
═══════════════════════════════════════════ */
:root {
	--bg:           #f0f2f7;
	--surface:      #ffffff;
	--surface-2:    #f8f9fc;
	--text:         #0f172a;
	--muted:        #64748b;
	--accent:       #e30613;
	--accent-dark:  #b50010;
	--ok:           #22c55e;
	--warn:         #f59e0b;
	--danger:       #ef4444;
	--border:       #e2e8f0;
	--sidebar-w:    220px;
	--topbar-h:     62px;
	--card-shadow:  0 1px 3px rgba(0,0,0,.07), 0 4px 14px rgba(0,0,0,.05);
	--radius:       12px;
	--radius-sm:    8px;
	--chip-conn-bg: #eff6ff; --chip-conn-fg: #1d4ed8;
	--chip-auto-bg: #fefce8; --chip-auto-fg: #a16207;
	--chip-fx-bg:   #f0fdf4; --chip-fx-fg:   #15803d;
	--chip-ctrl-bg: #faf5ff; --chip-ctrl-fg: #7e22ce;
}

/* ═══════════════════════════════════════════
	 RESET
═══════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
	font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
	background: var(--bg);
	color: var(--text);
	min-height: 100vh;
	overflow-x: hidden;
}

/* ═══════════════════════════════════════════
	 TOP BAR – full width
═══════════════════════════════════════════ */
.topbar {
	position: fixed;
	top: 0; left: 0; right: 0;
	height: var(--topbar-h);
	z-index: 200;
	background: linear-gradient(135deg, var(--accent-dark), var(--accent));
	box-shadow: 0 2px 10px rgba(0,0,0,.22);
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 0 24px;
	gap: 16px;
}
.brand-wrap { display: flex; align-items: center; gap: 14px; }

.vives-logo-img {
	height: 40px;
	width: auto;
	object-fit: contain;
	border-radius: 6px;
	background: #fff;
	padding: 4px 8px;
}

.brand-text h1 { font-size: 17px; font-weight: 700; color: #fff; line-height: 1.2; }
.brand-text p  { font-size: 11px; color: rgba(255,255,255,.78); }
.topbar-right  { display: flex; align-items: center; gap: 12px; }

.status-pill {
	display: flex; align-items: center; gap: 8px;
	background: rgba(255,255,255,.18);
	border: 1px solid rgba(255,255,255,.3);
	border-radius: 999px;
	padding: 6px 14px;
	font-size: 12px; color: #fff; white-space: nowrap;
}
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); flex-shrink: 0; }
.dot.ok  { background: var(--ok); }
.dot.err { background: var(--danger); }

/* ═══════════════════════════════════════════
	 LAYOUT
═══════════════════════════════════════════ */
.layout {
	display: flex;
	margin-top: var(--topbar-h);
	min-height: calc(100vh - var(--topbar-h));
}

/* ═══════════════════════════════════════════
	 SIDEBAR
═══════════════════════════════════════════ */
.sidebar {
	width: var(--sidebar-w);
	flex-shrink: 0;
	background: var(--surface);
	border-right: 1px solid var(--border);
	padding: 16px 10px;
	position: sticky;
	top: var(--topbar-h);
	height: calc(100vh - var(--topbar-h));
	overflow-y: auto;
}
.nav-list { list-style: none; display: flex; flex-direction: column; gap: 4px; }
.nav-btn {
	width: 100%; display: flex; align-items: center; gap: 10px;
	padding: 10px 12px; border: none; border-radius: var(--radius-sm);
	background: transparent; color: var(--muted);
	font-size: 14px; font-weight: 500; cursor: pointer; text-align: left;
	transition: background .15s, color .15s;
}
.nav-btn svg { width: 18px; height: 18px; flex-shrink: 0; fill: currentColor; }
.nav-btn:hover { background: var(--bg); color: var(--text); }
.nav-btn.active { background: #fee2e2; color: var(--accent); font-weight: 600; }

/* ═══════════════════════════════════════════
	 MAIN CONTENT
═══════════════════════════════════════════ */
.main-content { flex: 1; min-width: 0; padding: 24px; overflow-y: auto; }

/* ═══════════════════════════════════════════
	 PAGES
═══════════════════════════════════════════ */
.page { display: none; }
.page.active { display: block; }

.page-header {
	display: flex; align-items: baseline;
	justify-content: space-between; gap: 12px; margin-bottom: 20px;
}
.page-header h2 { font-size: 22px; font-weight: 700; }
.section-title {
	font-size: 11px; font-weight: 700; letter-spacing: .08em;
	text-transform: uppercase; color: var(--muted); margin-bottom: 10px;
}
.small { font-size: 12px; color: var(--muted); }

/* ═══════════════════════════════════════════
	 STATUS PAGE – two-column layout
═══════════════════════════════════════════ */
.status-layout {
	display: flex;
	gap: 16px;
	align-items: flex-start;
}
.status-left { flex: 1; min-width: 0; }
.status-right {
	width: 210px;
	flex-shrink: 0;
	position: sticky;
	top: calc(var(--topbar-h) + 24px);
}

/* ═══════════════════════════════════════════
	 STAT CARDS (clickable)
═══════════════════════════════════════════ */
.stat-cards {
	display: grid;
	grid-template-columns: repeat(4, 1fr);
	gap: 8px;
	margin-bottom: 14px;
}
.stat-card {
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: var(--radius);
	padding: 10px 12px;
	display: flex;
	flex-direction: column;
	align-items: flex-start;
	justify-content: space-between;
	gap: 8px;
	box-shadow: var(--card-shadow);
	text-align: left;
	font-family: inherit;
	color: var(--text);
}
.stat-card.clickable {
	cursor: pointer;
	transition: transform .15s, box-shadow .15s, border-color .15s;
}
.stat-card.clickable:hover {
	transform: translateY(-2px);
	box-shadow: 0 6px 20px rgba(0,0,0,.10);
	border-color: #cbd5e1;
}
.stat-card.clickable:active { transform: translateY(0); }

.stat-icon {
	width: 30px; height: 30px; border-radius: 7px;
	display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.stat-icon svg { width: 15px; height: 15px; }
.lux-icon  { background: #fefce8; color: #a16207; }
.temp-icon { background: #fff1f2; color: var(--accent); }
.mode-icon { background: #f0fdf4; color: #15803d; }
.br-icon   { background: #eff6ff; color: #1d4ed8; }

.stat-info {
	width: 100%;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 4px;
}
.stat-label { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.stat-value { font-size: 17px; font-weight: 800; line-height: 1.2; }
.stat-meta { font-size: 10px; line-height: 1.3; color: var(--muted); }
.stat-arrow {
	font-size: 13px;
	color: #cbd5e1;
	line-height: 1;
	flex-shrink: 0;
	align-self: flex-end;
	margin-top: auto;
}

/* ═══════════════════════════════════════════
	 STATUS CHIPS – RIGHT SIDEBAR (vertical)
═══════════════════════════════════════════ */
.status-chips-sidebar {
	display: flex;
	flex-direction: column;
	gap: 8px;
}
.status-chip-sidebar {
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: var(--radius);
	padding: 12px 14px;
	display: flex;
	align-items: center;
	gap: 12px;
	box-shadow: var(--card-shadow);
}
.chip-icon {
	width: 34px; height: 34px; border-radius: 8px;
	display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.chip-icon svg { width: 16px; height: 16px; }
.chip-conn { background: var(--chip-conn-bg); color: var(--chip-conn-fg); }
.chip-auto { background: var(--chip-auto-bg); color: var(--chip-auto-fg); }
.chip-fx   { background: var(--chip-fx-bg);   color: var(--chip-fx-fg);  }
.chip-ctrl { background: var(--chip-ctrl-bg); color: var(--chip-ctrl-fg); }
.chip-lesson { background: #ecfeff; color: #0f766e; }
.chip-body { display: flex; flex-direction: column; gap: 1px; }
.chip-label { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.chip-val { font-size: 13px; font-weight: 700; }

/* ═══════════════════════════════════════════
	 LED PREVIEW – single line canvas strip
═══════════════════════════════════════════ */
.led-preview-section { margin-top: 4px; }
.led-strip-wrap {
	border-radius: 10px;
	overflow: hidden;
	border: 1px solid #1a1a22;
	box-shadow: 0 4px 18px rgba(0,0,0,.22);
}
.led-canvas {
	display: block;
	width: 100% !important;
	height: 44px;
	background: #080810;
}
.desktop-only { display: block; }

/* ═══════════════════════════════════════════
	 KLEUR & MODUS PAGE
═══════════════════════════════════════════ */
/* ─── Blink alert (timer expired) ─── */
@keyframes blink-alert { 0%,100%{opacity:1} 50%{opacity:.1} }
.blink-alert { animation: blink-alert .4s ease-in-out 8; }
.manual-timer-status.timer-done { background:#fee2e2 !important; color:var(--accent) !important; }

/* ─── Kleur & Modus page layout ─── */
.kleur-led-bar { margin-bottom: 16px; }
.kleur-body + .kleur-led-bar { margin-top: 16px; margin-bottom: 0; }
.kleur-body {
	display: grid;
	grid-template-columns: 1fr 340px;
	gap: 20px;
	align-items: start;
}

/* Mode grid – card style */
.mode-grid {
	display: grid;
	grid-template-columns: repeat(4, 1fr);
	gap: 8px;
	margin-bottom: 14px;
}
.mode-card {
	background: var(--surface);
	border: 2px solid var(--border);
	border-radius: 12px;
	cursor: pointer;
	overflow: hidden;
	display: flex; flex-direction: column; align-items: center;
	transition: transform .12s, border-color .12s, box-shadow .12s;
	position: relative;
}
.mode-card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,0,0,.10); }
.mode-card.active { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(227,6,19,.12); }
.mode-card-off { grid-column: span 2; flex-direction: row; }
.mode-card-preview { width: 100%; height: 52px; display: block; }
.mode-card-off .mode-card-preview { width: 36px; height: 36px; border-radius: 8px; margin: 10px 10px 10px 12px; flex-shrink:0; }
.mode-card-label {
	font-size: 10px; font-weight: 700; text-transform: uppercase;
	letter-spacing: .06em; color: var(--text);
	padding: 6px 4px; text-align: center;
}
.mode-card-off .mode-card-label { padding: 0; font-size: 12px; }
.mode-card-check {
	position: absolute; top: 4px; right: 4px;
	width: 18px; height: 18px;
	background: var(--accent); border-radius: 50%;
	display: none; align-items: center; justify-content: center; color: #fff;
}
.mode-card-check svg { width: 10px; height: 10px; }
.mode-card.active .mode-card-check { display: flex; }

/* Custom color card */
.custom-color-card {
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: var(--radius);
	overflow: hidden; box-shadow: var(--card-shadow);
	display: flex; align-items: stretch; min-height: 80px;
}
.custom-color-preview { width: 80px; flex-shrink: 0; transition: background .2s; }
.custom-color-controls { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.custom-color-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 0; }
.custom-color-row { display: flex; align-items: center; gap: 10px; }
.custom-color-meta { display: flex; flex-direction: column; gap: 4px; }
.custom-color-hex-label { font-size: 12px; font-family: monospace; color: var(--muted); }

.color-picker-input {
	width: 48px; height: 36px; padding: 2px;
	border: 1px solid var(--border); border-radius: var(--radius-sm);
	background: var(--surface); cursor: pointer;
}
.field-label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 6px; }

/* Brightness panel */
.brightness-panel {
	background: var(--surface); border: 1px solid var(--border);
	border-radius: var(--radius); padding: 14px 16px;
	box-shadow: var(--card-shadow); margin-bottom: 16px;
}
.brightness-panel-head {
	display: flex; align-items: flex-start; justify-content: space-between;
	gap: 12px; margin-bottom: 10px;
}
.brightness-big-val { font-size: 28px; font-weight: 800; color: var(--accent); line-height: 1; }

/* Effects panel */
.effects-panel {
	background: var(--surface); border: 1px solid var(--border);
	border-radius: var(--radius); padding: 14px 16px;
	box-shadow: var(--card-shadow);
}
.effects-panel-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.effects-count-badge {
	font-size: 11px; font-weight: 700; padding: 2px 8px;
	border-radius: 999px; background: #fee2e2; color: var(--accent);
	border: 1px solid #fca5a5;
}
.effects-grid-new { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.effect-card-new {
	background: var(--surface-2); border: 1.5px solid var(--border);
	border-radius: var(--radius-sm); padding: 12px;
	display: flex; flex-direction: column; gap: 8px;
	transition: border-color .15s, box-shadow .15s; cursor: pointer;
}
.effect-card-new.effect-active-new {
	border-color: var(--accent); box-shadow: 0 0 0 2px rgba(227,6,19,.1);
	background: #fff5f5;
}
.effect-icon-new {
	width: 32px; height: 32px; border-radius: 8px;
	background: var(--bg); display: flex; align-items: center;
	justify-content: center; color: var(--muted);
}
.effect-icon-new svg { width: 18px; height: 18px; }
.effect-card-new.effect-active-new .effect-icon-new { background: #fee2e2; color: var(--accent); }
.effect-name-new { font-size: 12px; font-weight: 700; }
.effect-desc-new { font-size: 10px; color: var(--muted); line-height: 1.3; }
.effect-footer-new { display: flex; align-items: center; justify-content: space-between; }
.effect-status-badge {
	font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
	padding: 2px 7px; border-radius: 999px;
	background: var(--bg); border: 1px solid var(--border); color: var(--muted);
}
.effect-card-new.effect-active-new .effect-status-badge {
	background: #f0fdf4; border-color: #bbf7d0; color: #15803d;
}

@media (max-width: 1100px) { .mode-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px)  { .kleur-body { grid-template-columns: 1fr; } }

/* ═══════════════════════════════════════════
	 AUTOMATION PAGE
═══════════════════════════════════════════ */
.auto-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.auto-card {
	background: var(--surface); border: 1px solid var(--border);
	border-radius: var(--radius); overflow: hidden; box-shadow: var(--card-shadow);
}
.auto-card-header {
	display: flex; align-items: center; gap: 12px;
	padding: 15px 16px; border-bottom: 1px solid var(--border);
}
.auto-header-text { flex: 1; min-width: 0; }
.auto-header-text h3 { font-size: 14px; font-weight: 600; margin-bottom: 2px; }
.auto-icon {
	width: 38px; height: 38px; border-radius: 9px;
	display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.auto-icon svg { width: 19px; height: 19px; }
.auto-lux-icon { background: #fefce8; color: #a16207; }
.bright-icon   { background: #eff6ff; color: #1d4ed8; }
.timer-icon    { background: #f0fdf4; color: #15803d; }
.motion-icon   { background: #fdf4ff; color: #9333ea; }
.dim-icon      { background: #fff7ed; color: #ea580c; }
.ct-icon       { background: #fff1f2; color: var(--accent); }
.auto-card-body { padding: 14px 16px; }

/* Toggle switch */
.toggle { position: relative; display: inline-flex; width: 44px; height: 24px; flex-shrink: 0; }
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
	position: absolute; inset: 0;
	background: #cbd5e1; border-radius: 999px; cursor: pointer; transition: background .2s;
}
.toggle-slider::before {
	content: ""; position: absolute;
	width: 18px; height: 18px; left: 3px; top: 3px;
	background: #fff; border-radius: 50%;
	transition: transform .2s; box-shadow: 0 1px 3px rgba(0,0,0,.2);
}
.toggle input:checked + .toggle-slider { background: var(--accent); }
.toggle input:checked + .toggle-slider::before { transform: translateX(20px); }

/* Sliders */
.slider { width: 100%; accent-color: var(--accent); margin-top: 4px; }
.slider-labels {
	display: flex; justify-content: space-between;
	font-size: 10px; color: var(--muted); margin-top: 4px;
}
.slider-labels span:nth-child(2) { font-weight: 600; color: var(--text); }
.time-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.time-field { display: flex; flex-direction: column; gap: 4px; }
.manual-timer-wrap {
	margin-top: 16px;
	padding-top: 16px;
	border-top: 1px solid var(--border);
	display: flex;
	flex-direction: column;
	gap: 12px;
}
.manual-timer-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
}
.manual-timer-header h4 {
	font-size: 13px;
	font-weight: 700;
	color: var(--text);
}
.manual-timer-status {
	font-size: 11px;
	font-weight: 700;
	padding: 4px 10px;
	border-radius: 999px;
	background: #e2e8f0;
	color: #475569;
	white-space: nowrap;
}
.manual-timer-status.active {
	background: #fef3c7;
	color: #b45309;
}
.manual-timer-controls {
	display: flex;
	align-items: flex-end;
	justify-content: space-between;
	gap: 12px;
	flex-wrap: wrap;
}
.manual-timer-inputs {
	display: grid;
	grid-template-columns: minmax(110px, 140px) minmax(120px, 160px);
	gap: 12px;
	flex: 1;
}
.manual-timer-actions {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
}
.manual-timer-presets {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
}
.preset-btn,
.btn-secondary {
	background: var(--surface-2);
	color: var(--text);
	border: 1px solid var(--border);
	border-radius: var(--radius-sm);
	padding: 9px 14px;
	font-size: 12px;
	font-weight: 600;
	cursor: pointer;
	transition: background .15s, border-color .15s, color .15s;
}
.preset-btn:hover,
.btn-secondary:hover {
	background: #f8fafc;
	border-color: #cbd5e1;
}
.manual-timer-meta { margin: 0; }
.lesson-timer-wrap {
	margin-top: 12px;
	padding-top: 12px;
	border-top: 1px dashed var(--border);
	display: flex;
	flex-direction: column;
	gap: 8px;
}
.lesson-timer-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 10px;
}
.lesson-timer-head h4 { font-size: 13px; font-weight: 700; }
.lesson-config-grid {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 8px;
}
.lesson-config-field { display: flex; flex-direction: column; gap: 4px; }
.lesson-config-rows {
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.lesson-row,
.pause-row {
	display: grid;
	gap: 6px;
	align-items: center;
}
.lesson-row { grid-template-columns: 1fr 1fr auto; }
.pause-row { grid-template-columns: 1fr auto; }
.lesson-time-input {
	padding: 7px 9px;
	font-size: 12px;
}
.lesson-remove-btn {
	padding: 7px 10px;
	font-size: 11px;
	line-height: 1;
}
.lesson-add-btn {
	align-self: flex-start;
	padding: 6px 11px;
	font-size: 11px;
}
.lesson-timer-phase {
	font-size: 10px;
	font-weight: 700;
	padding: 4px 9px;
	border-radius: 999px;
	background: #e2e8f0;
	color: #475569;
}
.lesson-timer-phase.running {
	background: #dcfce7;
	color: #166534;
}
.lesson-led-strip {
	display: grid;
	grid-template-columns: repeat(28, 1fr);
	gap: 3px;
	padding: 8px;
	background: #0b1220;
	border-radius: 10px;
	border: 1px solid #1e293b;
}
.lesson-led {
	aspect-ratio: 1 / 1;
	border-radius: 3px;
	background: #111827;
	border: 1px solid #1f2937;
	transition: background .12s, box-shadow .12s;
}
.lesson-led.on-white { background: #f8fafc; box-shadow: 0 0 8px rgba(248,250,252,.65); }
.lesson-led.on-green { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,.6); }
.lesson-led.on-red { background: #e30613; box-shadow: 0 0 8px rgba(227,6,19,.55); }
.lesson-led.on-base { background: #60a5fa; box-shadow: 0 0 8px rgba(96,165,250,.55); }
.lesson-timer-actions {
	display: flex;
	gap: 8px;
	flex-wrap: wrap;
}
.lesson-list {
	list-style: none;
	display: grid;
	grid-template-columns: 1fr;
	gap: 5px;
	margin-top: 2px;
}
.lesson-list li {
	font-size: 11px;
	color: var(--muted);
	padding: 4px 6px;
	background: var(--surface-2);
	border: 1px solid var(--border);
	border-radius: 6px;
}
.input {
	width: 100%; background: var(--surface-2);
	border: 1px solid var(--border); color: var(--text);
	border-radius: var(--radius-sm); padding: 8px 10px; font-size: 13px;
}
.ct-preview {
	height: 30px; border-radius: 8px;
	background: linear-gradient(to right, #ff9500, #fff5e6, #e8f4ff, #b3d9ff);
	border: 1px solid var(--border);
}
.btn {
	background: var(--accent); color: #fff; border: none;
	border-radius: var(--radius-sm); padding: 9px 16px;
	font-size: 13px; font-weight: 600; cursor: pointer; transition: background .15s;
}
.btn:hover { background: var(--accent-dark); }

/* ═══════════════════════════════════════════
	 MODAL
═══════════════════════════════════════════ */
.modal-overlay {
	position: fixed; inset: 0; z-index: 500;
	background: rgba(15, 23, 42, .55);
	backdrop-filter: blur(6px);
	-webkit-backdrop-filter: blur(6px);
	display: flex; align-items: center; justify-content: center;
	padding: 24px;
	opacity: 0; pointer-events: none;
	transition: opacity .22s;
}
.modal-overlay.open { opacity: 1; pointer-events: auto; }
.modal-card {
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: 18px;
	box-shadow: 0 24px 60px rgba(0,0,0,.2);
	width: min(640px, 100%);
	max-height: calc(100vh - 48px);
	overflow-y: auto;
	transform: translateY(16px) scale(.97);
	transition: transform .22s;
}
.modal-overlay.open .modal-card { transform: translateY(0) scale(1); }
.modal-header {
	display: flex; align-items: center; justify-content: space-between;
	padding: 20px 24px 0;
}
.modal-header h2 { font-size: 20px; font-weight: 700; }
.modal-close {
	width: 32px; height: 32px; border: none; border-radius: 8px; cursor: pointer;
	background: var(--bg); color: var(--muted);
	display: flex; align-items: center; justify-content: center;
	transition: background .15s, color .15s;
}
.modal-close:hover { background: #fee2e2; color: var(--accent); }
.modal-close svg { width: 16px; height: 16px; }
.modal-body { padding: 20px 24px 24px; }

/* Modal content helpers */
.modal-big-num {
	font-size: 56px; font-weight: 800; line-height: 1;
	margin-bottom: 20px; color: var(--text);
	display: flex; align-items: baseline; gap: 8px;
}
.modal-unit { font-size: 24px; font-weight: 500; color: var(--muted); }
.modal-stats-row {
	display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px;
}
.modal-stat {
	background: var(--surface-2); border: 1px solid var(--border);
	border-radius: var(--radius-sm); padding: 12px;
}
.modal-stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: 4px; }
.modal-stat-val { font-size: 18px; font-weight: 700; }
.modal-chart-canvas { width: 100% !important; height: 180px; display: block; border-radius: 8px; }
.modal-gauge-wrap { display: flex; justify-content: center; padding: 10px 0; }
.modal-temp-svg { width: 100%; max-width: 320px; }
.modal-modus-swatch {
	width: 100%; height: 90px; border-radius: 12px;
	border: 1px solid var(--border); margin-bottom: 20px;
	transition: background .3s;
}
.modal-br-track {
	height: 14px; background: var(--bg); border-radius: 999px;
	border: 1px solid var(--border); overflow: hidden; margin-bottom: 20px;
}
.modal-br-fill { height: 100%; background: var(--accent); border-radius: 999px; transition: width .2s; }

/* ═══════════════════════════════════════════
	 RESPONSIVE
═══════════════════════════════════════════ */
@media (max-width: 1100px) {
	.kleur-layout { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
	.status-layout { flex-direction: column; }
	.status-right { width: 100%; position: static; }
	.status-chips-sidebar { flex-direction: row; flex-wrap: wrap; }
	.status-chip-sidebar { flex: 1; min-width: 140px; }
	.stat-cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
	:root { --sidebar-w: 0px; }
	.sidebar {
		display: flex; position: fixed;
		bottom: 0; left: 0; right: 0; top: auto;
		height: 58px; width: 100%;
		border-right: none; border-top: 1px solid var(--border);
		padding: 0; z-index: 150; background: var(--surface);
	}
	.nav-list { flex-direction: row; width: 100%; gap: 0; }
	.nav-btn {
		flex: 1; flex-direction: column; align-items: center; justify-content: center;
		gap: 3px; padding: 6px 4px; font-size: 10px; border-radius: 0;
	}
	.nav-btn svg { width: 20px; height: 20px; }
	.main-content { padding: 16px; padding-bottom: 74px; }
	.desktop-only { display: none !important; }
	.auto-grid { grid-template-columns: 1fr; }
	.page-header { flex-direction: column; align-items: flex-start; gap: 4px; }
	.modal-big-num { font-size: 44px; }
	.modal-stats-row { grid-template-columns: 1fr 1fr; }
	.manual-brightness-head { flex-direction: column; align-items: flex-start; }
	.manual-timer-header { flex-direction: column; align-items: flex-start; }
	.manual-timer-inputs { grid-template-columns: 1fr; width: 100%; }
	.manual-timer-actions { width: 100%; }
	.lesson-config-grid { grid-template-columns: 1fr; }
	.lesson-led-strip { grid-template-columns: repeat(20, 1fr); }
}
@media (max-width: 480px) {
	.stat-cards { grid-template-columns: repeat(2, 1fr); }
}

@media (pointer: coarse) {
	body { -webkit-tap-highlight-color: transparent; }
	.btn,
	.preset-btn,
	.btn-secondary,
	.nav-btn,
	.mode-card,
	.effect-card-new,
	.lesson-add-btn,
	.lesson-remove-btn {
		min-height: 44px;
	}
	.input,
	select.input,
	input[type="time"],
	input[type="number"],
	.color-picker-input {
		min-height: 44px;
		font-size: 16px;
	}
	input[type=range]::-webkit-slider-thumb {
		width: 28px;
		height: 28px;
	}
	.stat-card.clickable:hover,
	.mode-card:hover,
	.btn:hover,
	.preset-btn:hover,
	.btn-secondary:hover {
		transform: none;
	}
}
</style>
</head>
<body>

	<!-- TOP BAR – full width -->
	<header class="topbar">
		<div class="brand-wrap">
			<img src="Logo-v.png" alt="VIVES" class="vives-logo-img" />
			<div class="brand-text">
				<h1>LED Dashboard</h1>
				<p>Realtime simulator</p>
			</div>
		</div>
		<div class="topbar-right">
			<div class="status-pill">
				<span id="conn-dot" class="dot ok"></span>
				<span id="conn-text">Simulator actief</span>
			</div>
		</div>
	</header>

	<!-- LAYOUT WRAPPER -->
	<div class="layout">

		<!-- SIDEBAR -->
		<nav class="sidebar" id="sidebar">
			<ul class="nav-list">
				<li>
					<button class="nav-btn active" data-page="status">
						<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 13h4v8H3zm5-5h4v13H8zm5-5h4v18h-4z"/></svg>
						<span>Status</span>
					</button>
				</li>
				<li>
					<button class="nav-btn" data-page="kleur">
						<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-.99 0-.83.67-1.5 1.5-1.5H16c2.76 0 5-2.24 5-5 0-4.42-4.03-8-9-8zm-5.5 9c-.83 0-1.5-.67-1.5-1.5S5.67 9 6.5 9 8 9.67 8 10.5 7.33 12 6.5 12zm3-4C8.67 8 8 7.33 8 6.5S8.67 5 9.5 5s1.5.67 1.5 1.5S10.33 8 9.5 8zm5 0c-.83 0-1.5-.67-1.5-1.5S13.67 5 14.5 5s1.5.67 1.5 1.5S15.33 8 14.5 8zm3 4c-.83 0-1.5-.67-1.5-1.5S16.67 9 17.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>
						<span>Kleur &amp; Modus</span>
					</button>
				</li>
				<li>
					<button class="nav-btn" data-page="automatisatie">
						<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>
						<span>Automatisatie</span>
					</button>
				</li>
			</ul>
		</nav>

		<!-- MAIN CONTENT -->
		<main class="main-content" id="main-content">

			<!-- PAGE: STATUS -->
			<section class="page active" id="page-status">
				<div class="page-header">
					<h2>Status Overzicht</h2>
					<p class="small" id="updated-at">Laatste update: --</p>
				</div>

				<div class="status-layout">

					<!-- LEFT: metrics + gauges + LED -->
					<div class="status-left">

						<div class="stat-cards">
							<button class="stat-card clickable" data-modal="lux" aria-label="Open lux detail">
								<div class="stat-icon lux-icon">
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
								</div>
								<div class="stat-info">
									<span class="stat-label">Lichtsterkte</span>
									<strong class="stat-value" id="lux-val">-- lux</strong>
									<span class="stat-meta" id="lux-meta">Gemiddelde sensorwaarde</span>
								</div>
								<span class="stat-arrow">›</span>
							</button>

							<button class="stat-card clickable" data-modal="temp" aria-label="Open temperatuur detail">
								<div class="stat-icon temp-icon">
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 14.04V5a2 2 0 0 0-4 0v9.04A5 5 0 1 0 14 14.04z"/></svg>
								</div>
								<div class="stat-info">
									<span class="stat-label">Temperatuur</span>
									<strong class="stat-value" id="temp-val">--°C</strong>
									<span class="stat-meta" id="temp-meta">Omgevingssensor</span>
								</div>
								<span class="stat-arrow">›</span>
							</button>

							<button class="stat-card clickable" data-modal="modus" aria-label="Open modus detail">
								<div class="stat-icon mode-icon">
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
								</div>
								<div class="stat-info">
									<span class="stat-label">Modus</span>
									<strong class="stat-value" id="mode-val">--</strong>
									<span class="stat-meta" id="mode-meta">Kleur en effectstatus</span>
								</div>
								<span class="stat-arrow">›</span>
							</button>

							<button class="stat-card clickable" data-modal="helderheid" aria-label="Open helderheid detail">
								<div class="stat-icon br-icon">
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M3 12h2M19 12h2M12 3v2M12 19v2"/></svg>
								</div>
								<div class="stat-info">
									<span class="stat-label">Helderheid</span>
									<strong class="stat-value" id="br-val">--%</strong>
									<span class="stat-meta" id="br-meta">Handmatige regeling</span>
								</div>
								<span class="stat-arrow">›</span>
							</button>
						</div>

						<!-- LED Preview – single line canvas, desktop only -->
						<div class="led-preview-section desktop-only">
							<h3 class="section-title">LED Preview</h3>
							<div class="led-strip-wrap">
								<canvas id="led-canvas" class="led-canvas"></canvas>
							</div>
						</div>

					</div><!-- /status-left -->

					<!-- RIGHT: system status chips (vertical) -->
					<div class="status-right">
						<h3 class="section-title">Systeemstatus</h3>
						<div class="status-chips-sidebar">

							<div class="status-chip-sidebar">
								<div class="chip-icon chip-conn">
									<svg viewBox="0 0 24 24" fill="currentColor"><path d="M1 9l2 2c4.97-4.97 13.03-4.97 18 0l2-2C16.93 2.93 7.08 2.93 1 9zm8 8l3 3 3-3c-1.65-1.66-4.34-1.66-6 0zm-4-4 2 2c2.76-2.76 7.24-2.76 10 0l2-2C15.14 9.14 8.87 9.14 5 13z"/></svg>
								</div>
								<div class="chip-body">
									<span class="chip-label">Verbinding</span>
									<strong class="chip-val" id="status-conn">Actief</strong>
								</div>
							</div>

							<div class="status-chip-sidebar">
								<div class="chip-icon chip-auto">
									<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"/><path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
								</div>
								<div class="chip-body">
									<span class="chip-label">Auto-Lux</span>
									<strong class="chip-val" id="status-auto">Uit</strong>
								</div>
							</div>

							<div class="status-chip-sidebar">
								<div class="chip-icon chip-fx">
									<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 2v11h3v9l7-12h-4l4-8z"/></svg>
								</div>
								<div class="chip-body">
									<span class="chip-label">Effecten</span>
									<strong class="chip-val" id="status-effects">Geen actief</strong>
								</div>
							</div>

							<div class="status-chip-sidebar">
								<div class="chip-icon chip-ctrl">
									<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 11V6a1 1 0 0 1 2 0v5h1V4a1 1 0 0 1 2 0v7h1V5a1 1 0 0 1 2 0v6h1V7a1 1 0 1 1 2 0v8.2c0 2.4-1 4.6-2.8 6.2L13 23H9.5l-4.4-4.4A3 3 0 0 1 4 16.5V12a1 1 0 0 1 2 0v-1z"/></svg>
								</div>
								<div class="chip-body">
									<span class="chip-label">Regeling</span>
									<strong class="chip-val" id="status-control">Handmatig</strong>
								</div>
							</div>

							<div class="status-chip-sidebar">
								<div class="chip-icon chip-lesson">
									<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3h-1V1h-2v2H8V1H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V9h14v10zm-7-9a4 4 0 1 0 4 4 4 4 0 0 0-4-4zm.5 4.2V12h-1v3h3v-1z"/></svg>
								</div>
								<div class="chip-body">
									<span class="chip-label">Lesrooster</span>
									<strong class="chip-val" id="status-lesson">Inactief</strong>
								</div>
							</div>

						</div>
					</div><!-- /status-right -->

				</div><!-- /status-layout -->
			</section>

			<!-- PAGE: KLEUR & MODUS -->
			<section class="page" id="page-kleur">
				<div class="page-header">
					<h2>Kleur &amp; Modus</h2>
					<p class="small">Strip actief: <strong id="kleur-current-badge">WIT</strong></p>
				</div>

				<div class="kleur-body">

					<!-- LEFT: mode picker + custom color -->
					<div class="kleur-col-left">
						<p class="section-title">Kleurmodel</p>
						<div class="mode-grid" id="mode-buttons"></div>

						<div class="custom-color-card">
							<div class="custom-color-preview" id="custom-color-swatch" style="background:#ffffff"></div>
							<div class="custom-color-controls">
								<p class="custom-color-title">Aangepaste kleur</p>
								<div class="custom-color-row">
									<input type="color" id="custom-color" value="#ffffff" class="color-picker-input" />
									<div class="custom-color-meta">
										<span class="custom-color-hex-label" id="custom-color-hex">#ffffff</span>
										<button class="btn" id="apply-custom-color">Toepassen</button>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- RIGHT: brightness + effects -->
					<div class="kleur-col-right">
						<div class="brightness-panel">
							<div class="brightness-panel-head">
								<div>
									<p class="section-title" style="margin-bottom:2px">Helderheid</p>
									<p class="small">Auto-Lux schakelt deze slider automatisch uit.</p>
								</div>
								<span class="brightness-big-val" id="brightness-val-kleur">50%</span>
							</div>
							<input type="range" id="brightness" min="1" max="100" value="50" class="slider" />
							<div class="slider-labels"><span>1%</span><span id="brightness-val">50%</span><span>100%</span></div>
						</div>

						<div class="effects-panel">
							<div class="effects-panel-head">
								<p class="section-title" style="margin-bottom:0">Animatie-effecten</p>
								<span class="effects-count-badge" id="effects-summary">Geen actief</span>
							</div>
							<p class="small" style="margin:4px 0 12px">Slechts één effect tegelijk actief.</p>
							<div class="effects-grid-new" id="effects-list"></div>
						</div>
					</div>

				</div>

				<!-- LED preview onderaan -->
				<div class="kleur-led-bar desktop-only">
					<div class="led-strip-wrap">
						<canvas id="led-canvas-kleur" class="led-canvas"></canvas>
					</div>
				</div>
			</section>

			<!-- PAGE: AUTOMATISATIE -->
			<section class="page" id="page-automatisatie">
				<div class="page-header">
					<h2>Automatisatie</h2>
					<p class="small">Beheer automatische regelingen en schema's.</p>
				</div>
				<div class="auto-grid">

					<div class="auto-card">
						<div class="auto-card-header">
							<div class="auto-icon auto-lux-icon">
								<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"/><path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2"/></svg>
							</div>
							<div class="auto-header-text">
								<h3>Auto-Lux</h3>
								<p class="small">Regelt helderheid op basis van omgevingslicht.</p>
							</div>
							<label class="toggle"><input type="checkbox" id="auto-lux" /><span class="toggle-slider"></span></label>
						</div>
						<div class="auto-card-body">
							<label class="field-label" for="lux-threshold">Drempelwaarde (lux)</label>
							<input type="range" id="lux-threshold" min="0" max="1000" value="300" class="slider" />
							<div class="slider-labels"><span>0 lux</span><span id="lux-threshold-val">300 lux</span><span>1000 lux</span></div>
						</div>
					</div>

					<div class="auto-card">
						<div class="auto-card-header">
							<div class="auto-icon timer-icon">
								<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61-1.42-1.42c-.43-.43-.99-.65-1.45-.63L14.59 7.9c.34.3.57.7.7 1.1C17.09 9.54 18 10.96 18 12.5 18 15.53 15.54 18 12.5 18S7 15.53 7 12.5C7 10.96 7.91 9.54 9.71 9c.13-.4.36-.8.7-1.1L8.84 5.34c-.46-.02-1.02.2-1.45.63L5.97 7.39C4.13 9.23 3 11.73 3 14.5 3 20.28 7.72 25 13.5 25S24 20.28 24 14.5c0-2.77-1.13-5.27-2.97-7.11z"/></svg>
							</div>
							<div class="auto-header-text">
								<h3>Timer</h3>
								<p class="small">Zet LED automatisch aan/uit op tijdstip.</p>
							</div>
							<label class="toggle"><input type="checkbox" id="timer-enabled" /><span class="toggle-slider"></span></label>
						</div>
						<div class="auto-card-body">
							<div class="time-row">
								<div class="time-field">
									<label class="field-label" for="timer-on">Aan om</label>
									<input type="time" id="timer-on" value="07:00" class="input" />
								</div>
								<div class="time-field">
									<label class="field-label" for="timer-off">Uit om</label>
									<input type="time" id="timer-off" value="22:00" class="input" />
								</div>
							</div>
							<div class="manual-timer-wrap">
								<div class="manual-timer-header">
									<h4>Manuele timer</h4>
									<span class="manual-timer-status" id="manual-timer-status">Niet actief</span>
								</div>
								<div class="manual-timer-controls">
									<div class="manual-timer-inputs">
										<div class="time-field">
											<label class="field-label" for="manual-timer-value">Duur</label>
											<input type="number" id="manual-timer-value" min="1" max="240" value="10" class="input" />
										</div>
										<div class="time-field">
											<label class="field-label" for="manual-timer-unit">Eenheid</label>
											<select id="manual-timer-unit" class="input">
												<option value="seconds">Seconden</option>
												<option value="minutes" selected>Minuten</option>
												<option value="hours">Uren</option>
											</select>
										</div>
									</div>
									<div class="manual-timer-actions">
										<button class="btn" id="manual-timer-start">Start timer</button>
										<button class="btn btn-secondary" id="manual-timer-stop" type="button">Stop</button>
									</div>
								</div>
								<div class="manual-timer-presets">
									<button class="preset-btn" type="button" data-minutes="10">10 min</button>
									<button class="preset-btn" type="button" data-minutes="30">30 min</button>
									<button class="preset-btn" type="button" data-minutes="60">1 uur</button>
								</div>
								<p class="small manual-timer-meta" id="manual-timer-meta">Zet de LED-strip automatisch uit na de gekozen duur.</p>

								<div class="lesson-timer-wrap">
									<div class="lesson-timer-head">
										<h4>Lesrooster timer</h4>
										<span class="lesson-timer-phase" id="lesson-phase">Inactief</span>
									</div>
									<div class="lesson-config-grid">
										<div class="lesson-config-field">
											<label class="field-label">Lesuren (start + einde)</label>
											<div class="lesson-config-rows" id="lesson-rows"></div>
											<button class="btn btn-secondary lesson-add-btn" id="add-lesson-row" type="button">Les toevoegen</button>
										</div>
										<div class="lesson-config-field">
											<label class="field-label">Pauzemomenten</label>
											<div class="lesson-config-rows" id="pause-rows"></div>
											<button class="btn btn-secondary lesson-add-btn" id="add-pause-row" type="button">Pauze toevoegen</button>
										</div>
									</div>
									<div class="lesson-timer-actions">
										<label class="field-label" for="pause-duration-min" style="margin-bottom:0">Pauzeduur (min)</label>
										<input type="number" id="pause-duration-min" min="1" max="120" value="15" class="input" style="width:90px" />
										<button class="btn" id="lesson-config-apply" type="button">Toepassen</button>
									</div>
									<p class="small" id="lesson-current">Volgende les: --</p>
									<p class="small" id="lesson-window">Start - Einde: --</p>
									<div class="lesson-led-strip" id="lesson-led-strip" aria-label="Lesrooster LED timer"></div>
									<div class="lesson-timer-actions">
										<button class="btn" id="lesson-timer-start" type="button">Start lesrooster</button>
										<button class="btn btn-secondary" id="lesson-timer-stop" type="button">Stop</button>
									</div>
									<ul class="lesson-list" id="lesson-list"></ul>
								</div>
							</div>
						</div>
					</div>

					<div class="auto-card">
						<div class="auto-card-header">
							<div class="auto-icon motion-icon">
								<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.49 5.48c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm-3.6 13.9 1-4.4 2.1 2v6h2v-7.5l-2.1-2 .6-3c1.3 1.5 3.3 2.5 5.5 2.5v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1l-5.2 2.2v4.7h2v-3.4l1.8-.7-1.6 8.1-4.9-1-.4 2 7 1.4z"/></svg>
							</div>
							<div class="auto-header-text">
								<h3>Bewegingssensor</h3>
								<p class="small">LED aan bij beweging detectie.</p>
							</div>
							<label class="toggle"><input type="checkbox" id="motion-enabled" /><span class="toggle-slider"></span></label>
						</div>
						<div class="auto-card-body">
							<label class="field-label" for="motion-timeout">Vertraging na beweging</label>
							<input type="range" id="motion-timeout" min="10" max="300" value="60" class="slider" />
							<div class="slider-labels"><span>10s</span><span id="motion-timeout-val">60s</span><span>300s</span></div>
						</div>
					</div>

					<div class="auto-card">
						<div class="auto-card-header">
							<div class="auto-icon dim-icon">
								<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 8.69V4h-4.69L12 .69 8.69 4H4v4.69L.69 12 4 15.31V20h4.69L12 23.31 15.31 20H20v-4.69L23.31 12 20 8.69zM12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-10c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z"/></svg>
							</div>
							<div class="auto-header-text">
								<h3>Dimschema</h3>
								<p class="small">Graduele dim doorheen de dag.</p>
							</div>
							<label class="toggle"><input type="checkbox" id="dim-enabled" /><span class="toggle-slider"></span></label>
						</div>
						<div class="auto-card-body">
							<label class="field-label" for="dim-min">Minimale helderheid</label>
							<input type="range" id="dim-min" min="1" max="50" value="10" class="slider" />
							<div class="slider-labels"><span>1%</span><span id="dim-min-val">10%</span><span>50%</span></div>
						</div>
					</div>

					<div class="auto-card">
						<div class="auto-card-header">
							<div class="auto-icon ct-icon">
								<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7 1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91 1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z"/></svg>
							</div>
							<div class="auto-header-text">
								<h3>Kleurtemperatuur</h3>
								<p class="small">Warm 's avonds, koel overdag.</p>
							</div>
							<label class="toggle"><input type="checkbox" id="ct-enabled" /><span class="toggle-slider"></span></label>
						</div>
						<div class="auto-card-body">
							<div class="ct-preview" id="ct-preview"></div>
							<p class="small" style="margin-top:8px">Warm wit (avond) → Koel wit (middag)</p>
						</div>
					</div>

				</div>
			</section>

		</main>
	</div>

	<!-- MODAL OVERLAY -->
	<div class="modal-overlay" id="modal-overlay" role="dialog" aria-modal="true">
		<div class="modal-card" id="modal-card">
			<div class="modal-header">
				<h2 id="modal-title">--</h2>
				<button class="modal-close" id="modal-close" aria-label="Sluiten">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
				</button>
			</div>
			<div class="modal-body" id="modal-body"></div>
		</div>
	</div>

	<script>/* ═══════════════════════════════════════════
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
</script>
</body>
</html>
'''

def get_html():
    return WEB_INDEX_HTML

# --- 4. SERVER ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(3)
s.settimeout(0.01)


def send_json(conn, data):
    body = json.dumps(data)
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
    conn.send(body.encode())


def send_ok(conn):
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')


def send_html(conn):
    html = get_html()
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
    # Send in chunks to avoid hitting socket buffer limits
    chunk = 1024
    for i in range(0, len(html), chunk):
        conn.send(html[i:i + chunk].encode())


def build_state_payload():
    effect_name = "none"
    if "wave" in lightshow_active:
        effect_name = "wave"
    elif "pulse" in lightshow_active:
        effect_name = "pulse"
    elif "strobe" in lightshow_active:
        effect_name = "strobe"
    elif "rainbow" in lightshow_active:
        effect_name = "rainbow"

    payload = {
        # Legacy flat fields for built-in HTML
        "lux": perc_val,
        "temp": round(temp_val, 1),
        "mode": mode,
        "auto": auto_light,
        "br": int(global_br * 100),
        "effects": {
            "wave": "wave" in lightshow_active,
            "pulse": "pulse" in lightshow_active,
            "strobe": "strobe" in lightshow_active,
            "rainbow": "rainbow" in lightshow_active,
        },
        # Snapshot fields expected by renewed web app
        "desired": {
            "power": mode != "off",
            "mode": mode,
            "auto": auto_light,
            "brightness": int(global_br * 100),
            "color": {
                "r": custom_color[0],
                "g": custom_color[1],
                "b": custom_color[2],
            },
            "effect": effect_name,
        },
        "device": {
            "online": True,
            "telemetry": {
                "lux": perc_val,
                "temperature": round(temp_val, 1),
            },
        },
        "scheduler": scheduler_config,
    }
    return payload


def parse_request(req):
    try:
        first = req.split('\r\n')[0]
        method = first.split()[0]
        path = first.split()[1]
    except:
        method = "GET"
        path = "/"

    body = ""
    if '\r\n\r\n' in req:
        body = req.split('\r\n\r\n', 1)[1]
    return method, path, body


def apply_command_payload(payload):
    global mode, auto_light, global_br, custom_color, lightshow_active, lightshow_start_times

    if "auto" in payload:
        auto_light = bool(payload.get("auto"))

    if "brightness" in payload:
        global_br = clamp_int(payload.get("brightness"), 1, 100) / 100.0

    if "color" in payload and isinstance(payload.get("color"), dict):
        c = payload.get("color")
        custom_color = (
            clamp_int(c.get("r", 255), 0, 255),
            clamp_int(c.get("g", 255), 0, 255),
            clamp_int(c.get("b", 255), 0, 255),
        )

    if "mode" in payload and isinstance(payload.get("mode"), str):
        mode = payload.get("mode")
        lightshow_active.clear()
        lightshow_start_times.clear()

    if payload.get("power") is False:
        mode = "off"
        lightshow_active.clear()
        lightshow_start_times.clear()

    if "effect" in payload:
        effect = payload.get("effect")
        lightshow_active.clear()
        lightshow_start_times.clear()
        if effect in ("wave", "pulse", "strobe", "rainbow"):
            lightshow_active[effect] = True
            lightshow_start_times[effect] = int(time.time() * 1000)


# --- 5. MAIN LOOP ---
while True:

    # 5a. SENSORS
    try:
        val_raw = ldr.read()
        sensor_buffer.append(val_raw)
        sensor_buffer.pop(0)
        smooth_val = sum(sensor_buffer) / len(sensor_buffer)
        perc_val = int(((4095 - smooth_val) / 4095) * 100)
        perc_val = max(0, min(100, perc_val))

        if auto_light:
            final_br = max(0.01, min(1.0, perc_val / 100.0))
        else:
            final_br = global_br

        temp_read_counter += 1
        if temp_read_counter >= 75:
            temp_read_counter = 0
            if temp_roms:
                try:
                    ds.convert_temp()
                    time.sleep_ms(5)
                    for rom in temp_roms:
                        temp_val = ds.read_temp(rom)
                        temp_val = max(-40, min(125, temp_val))
                        break
                except:
                    pass
    except:
        pass

    # 5b. HTTP SERVER
    try:
        conn, addr = s.accept()
        try:
            req = conn.recv(2048).decode("utf-8", "ignore")
            method, path, body = parse_request(req)

            if path in ("/", "/index.html", "/styles.css", "/app.js"):
                send_html(conn)

            elif path == "/api/sensor":
                send_json(conn, {"lux": perc_val, "temp": round(temp_val, 1)})

            elif path == "/api/state":
                send_json(conn, build_state_payload())

            elif method == "POST" and path == "/api/command":
                try:
                    payload = json.loads(body) if body else {}
                    if isinstance(payload, dict):
                        if isinstance(payload.get("desired"), dict):
                            payload = payload.get("desired")
                        apply_command_payload(payload)
                except:
                    pass
                send_json(conn, {"ok": True})

            elif method == "POST" and path == "/api/scheduler":
                try:
                    payload = json.loads(body) if body else {}
                    if isinstance(payload, dict):
                        if "enabled" in payload:
                            scheduler_config["enabled"] = bool(payload.get("enabled"))
                        scheduler_config["pauseDurationMin"] = clamp_int(payload.get("pauseDurationMin", 15), 1, 240)
                        lessons = payload.get("lessons", [])
                        breaks = payload.get("breaks", [])
                        scheduler_config["lessons"] = lessons if isinstance(lessons, list) else []
                        scheduler_config["breaks"] = breaks if isinstance(breaks, list) else []
                except:
                    pass
                send_json(conn, {"ok": True})

            elif method == "POST" and path == "/api/scheduler/start":
                scheduler_config["enabled"] = True
                send_json(conn, {"ok": True})

            elif method == "POST" and path == "/api/scheduler/stop":
                scheduler_config["enabled"] = False
                send_json(conn, {"ok": True})

            elif path.startswith("/set_global"):
                try:
                    global_br = int(path.split("br=")[1]) / 100.0
                except:
                    pass
                send_ok(conn)

            elif path.startswith("/lightshow/") and path.endswith("/toggle"):
                try:
                    effect = path.split("/lightshow/")[1].split("/toggle")[0]
                    now_ms = int(time.time() * 1000)
                    if now_ms - lightshow_last_trigger > 100:
                        if effect in lightshow_active:
                            del lightshow_active[effect]
                            lightshow_start_times.pop(effect, None)
                        else:
                            lightshow_active[effect] = True
                            lightshow_start_times[effect] = now_ms
                        lightshow_last_trigger = now_ms
                except:
                    pass
                send_ok(conn)

            elif path == "/toggle/auto":
                auto_light = not auto_light
                send_ok(conn)

            elif path.startswith("/mode/"):
                try:
                    mode = path.split("/mode/")[1].split("?")[0].split(" ")[0]
                    lightshow_active.clear()
                    lightshow_start_times.clear()
                except:
                    pass
                send_ok(conn)

            else:
                send_html(conn)
        finally:
            conn.close()
    except:
        pass

    # 5c. LED RENDERING
    try:
        now_ms = int(time.time() * 1000)
        active_effects = [e for e in lightshow_active if e in lightshow_start_times]

        if active_effects:
            for i in range(NUM_LEDS):
                strip[i] = (0, 0, 0, 0)

            for effect in active_effects:
                ls_el = now_ms - lightshow_start_times[effect]

                if effect == "wave":
                    wc = (ls_el / 50.0) % (NUM_LEDS + 80)
                    for i in range(NUM_LEDS):
                        d = abs(i - wc)
                        if d < 40:
                            br = max(0, int(255 * (1 - (d / 40.0) ** 2)))
                            strip[i] = (br, br, br, 1.0)

                elif effect == "pulse":
                    cp = NUM_LEDS // 2
                    wd = (ls_el / 30.0) % (NUM_LEDS // 2 + 20)
                    for i in range(NUM_LEDS):
                        dc = abs(i - cp)
                        if abs(dc - wd) < 15:
                            br = max(0, int(255 * (1 - (abs(dc - wd) / 15.0) ** 2)))
                            strip[i] = (br, br, br, 1.0)

                elif effect == "strobe":
                    for i in range(NUM_LEDS):
                        if random.random() < 0.5:
                            strip[i] = (255, 255, 255, 1.0)

                elif effect == "rainbow":
                    for i in range(NUM_LEDS):
                        hp = (i * 10 + ls_el // 20) % 360
                        h = hp / 360.0
                        if h < 0.1667:
                            r, g, b = 255, int(255 * h * 6), 0
                        elif h < 0.3333:
                            r, g, b = int(255 * (1 - (h - 0.1667) * 6)), 255, 0
                        elif h < 0.5:
                            r, g, b = 0, 255, int(255 * (h - 0.3333) * 6)
                        elif h < 0.6667:
                            r, g, b = 0, int(255 * (1 - (h - 0.5) * 6)), 255
                        elif h < 0.8333:
                            r, g, b = int(255 * (h - 0.6667) * 6), 0, 255
                        else:
                            r, g, b = 255, 0, int(255 * (1 - (h - 0.8333) * 6))
                        strip[i] = (r, g, b, 0.8)

            strip.write()

        else:
            colors = {
                "red":    (255, 0,   0,   final_br),
                "green":  (0,   255, 0,   final_br),
                "blue":   (0,   0,   255, final_br),
                "white":  (255, 255, 255, final_br),
                "purple": (128, 0,   128, final_br),
                "cyan":   (0,   255, 255, final_br),
                "yellow": (255, 255, 0,   final_br),
                "warm":   (255, 160, 60,  final_br),
                "custom": (custom_color[0], custom_color[1], custom_color[2], final_br),
                "off":    (0,   0,   0,   0),
            }
            c = colors.get(mode, (0, 0, 0, 0))
            for i in range(NUM_LEDS):
                strip[i] = c
            strip.write()

    except:
        lightshow_active.clear()
        lightshow_start_times.clear()

    time.sleep(0.01)
