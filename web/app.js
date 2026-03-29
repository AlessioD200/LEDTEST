const MODES = [
  { key: "white", label: "WIT", color: "#9ca3af" },
  { key: "warm", label: "WARM", color: "#c87428" },
  { key: "red", label: "ROOD", color: "#cc0000" },
  { key: "green", label: "GROEN", color: "#15803d" },
  { key: "blue", label: "BLAUW", color: "#1d4ed8" },
  { key: "purple", label: "PAARS", color: "#7e22ce" },
  { key: "cyan", label: "CYAAN", color: "#0e7490" },
  { key: "yellow", label: "GEEL", color: "#a16207" },
  { key: "off", label: "UIT", color: "#111827" }
];
const EFFECTS = [
  { key: "wave", label: "Golf" },
  { key: "pulse", label: "Puls" },
  { key: "strobe", label: "Strobe" },
  { key: "rainbow", label: "Regenboog" }
];

const ui = {
  modeButtons: document.getElementById("mode-buttons"),
  effectsList: document.getElementById("effects-list"),
  autoLux: document.getElementById("auto-lux"),
  brightness: document.getElementById("brightness"),
  connDot: document.getElementById("conn-dot"),
  connText: document.getElementById("conn-text"),
  lux: document.getElementById("lux-val"),
  temp: document.getElementById("temp-val"),
  mode: document.getElementById("mode-val"),
  br: document.getElementById("br-val"),
  updated: document.getElementById("updated-at"),
  canvas: document.getElementById("led-canvas")
};

let currentState = {
  mode: "white",
  auto: true,
  br: 50,
  lux: 50,
  temp: 22,
  effects: {
    wave: false,
    pulse: false,
    strobe: false,
    rainbow: false
  }
};

const modeBase = {
  red: [255, 0, 0],
  green: [0, 255, 0],
  blue: [0, 0, 255],
  white: [255, 255, 255],
  purple: [128, 0, 128],
  cyan: [0, 255, 255],
  yellow: [255, 255, 0],
  warm: [255, 160, 60],
  off: [0, 0, 0]
};

function buildModes() {
  ui.modeButtons.innerHTML = "";
  MODES.forEach((m) => {
    const b = document.createElement("button");
    b.className = `mode-btn ${m.key === "off" ? "off" : ""}`;
    b.style.background = m.color;
    b.textContent = m.label;
    b.dataset.mode = m.key;
    b.onclick = () => {
      currentState.mode = m.key;
      currentState.effects = { wave: false, pulse: false, strobe: false, rainbow: false };
      renderState();
    };
    ui.modeButtons.appendChild(b);
  });
}

function buildEffects() {
  ui.effectsList.innerHTML = "";
  EFFECTS.forEach((e) => {
    const row = document.createElement("label");
    row.className = "effect-row";
    const left = document.createElement("span");
    left.textContent = e.label;
    const check = document.createElement("input");
    check.type = "checkbox";
    check.id = `effect-${e.key}`;
    check.onchange = () => {
      currentState.effects[e.key] = check.checked;
      renderState();
    };
    row.appendChild(left);
    row.appendChild(check);
    ui.effectsList.appendChild(row);
  });
}

function renderState() {
  ui.lux.textContent = `${currentState.lux}%`;
  ui.temp.textContent = `${Number(currentState.temp).toFixed(1)}°C`;
  ui.mode.textContent = String(currentState.mode || "-").toUpperCase();
  ui.br.textContent = `${currentState.br}%`;
  ui.autoLux.checked = !!currentState.auto;
  ui.brightness.disabled = !!currentState.auto;
  ui.brightness.value = currentState.br;

  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === currentState.mode);
  });
  EFFECTS.forEach((e) => {
    const el = document.getElementById(`effect-${e.key}`);
    if (el) el.checked = !!currentState.effects?.[e.key];
  });

  ui.updated.textContent = `Laatste update: ${new Date().toLocaleTimeString()}`;
}

function setConn(ok, text) {
  ui.connDot.classList.remove("ok", "err");
  ui.connDot.classList.add(ok ? "ok" : "err");
  ui.connText.textContent = text;
}

function drawLED(colors) {
  const ctx = ui.canvas.getContext("2d");
  const leds = Array.isArray(colors) ? colors : [];
  const img = ctx.createImageData(140, 1);
  for (let i = 0; i < 140; i++) {
    const c = leds[i] || [0, 0, 0];
    img.data[i * 4 + 0] = c[0] || 0;
    img.data[i * 4 + 1] = c[1] || 0;
    img.data[i * 4 + 2] = c[2] || 0;
    img.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

function clamp(v, lo = 0, hi = 255) {
  return Math.max(lo, Math.min(hi, v));
}

function renderLEDFrame(t) {
  const colors = new Array(140).fill(0).map(() => [0, 0, 0]);

  if (currentState.effects.wave || currentState.effects.pulse || currentState.effects.strobe || currentState.effects.rainbow) {
    if (currentState.effects.wave) {
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
    if (currentState.effects.pulse) {
      const c = 70;
      const wave = (t * 45) % 90;
      for (let i = 0; i < 140; i++) {
        const d = Math.abs(i - c);
        if (Math.abs(d - wave) < 12) {
          const b = Math.max(0, 1 - Math.abs(d - wave) / 12);
          const v = Math.floor(255 * b);
          colors[i] = [v, v, v];
        }
      }
    }
    if (currentState.effects.strobe) {
      for (let i = 0; i < 140; i++) {
        if (Math.random() < 0.35) colors[i] = [255, 255, 255];
      }
    }
    if (currentState.effects.rainbow) {
      for (let i = 0; i < 140; i++) {
        const h = ((i * 8 + t * 120) % 360) / 360;
        let r = 0, g = 0, b = 0;
        if (h < 1 / 6) {
          r = 255; g = Math.floor(255 * h * 6);
        } else if (h < 2 / 6) {
          r = Math.floor(255 * (1 - (h - 1 / 6) * 6)); g = 255;
        } else if (h < 3 / 6) {
          g = 255; b = Math.floor(255 * (h - 2 / 6) * 6);
        } else if (h < 4 / 6) {
          g = Math.floor(255 * (1 - (h - 3 / 6) * 6)); b = 255;
        } else if (h < 5 / 6) {
          r = Math.floor(255 * (h - 4 / 6) * 6); b = 255;
        } else {
          r = 255; b = Math.floor(255 * (1 - (h - 5 / 6) * 6));
        }
        colors[i] = [
          clamp(colors[i][0] + Math.floor(r * 0.75)),
          clamp(colors[i][1] + Math.floor(g * 0.75)),
          clamp(colors[i][2] + Math.floor(b * 0.75))
        ];
      }
    }
  } else {
    const base = modeBase[currentState.mode] || [0, 0, 0];
    const finalBr = currentState.auto ? Math.max(0.01, Math.min(1, currentState.lux / 100)) : currentState.br / 100;
    const pixel = [
      Math.floor(base[0] * finalBr),
      Math.floor(base[1] * finalBr),
      Math.floor(base[2] * finalBr)
    ];
    for (let i = 0; i < 140; i++) colors[i] = pixel;
  }

  drawLED(colors);
}

function tick() {
  const t = Date.now() / 1000;
  currentState.lux = Math.round(50 + 35 * Math.sin(t * 0.6));
  currentState.temp = 22 + 2.2 * Math.sin(t * 0.2);
  renderState();
  renderLEDFrame(t);
  setConn(true, "Simulator actief");
}

ui.autoLux.onchange = () => {
  currentState.auto = ui.autoLux.checked;
  renderState();
};

ui.brightness.onchange = () => {
  const value = Number(ui.brightness.value);
  currentState.br = value;
  renderState();
};

buildModes();
buildEffects();
renderState();
setConn(true, "Simulator actief");
tick();
setInterval(tick, 120);
