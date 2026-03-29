from machine import Pin, SPI, ADC
import apa102, socket, time, math, random, onewire, ds18x20, json

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
lightshow_active = {}
lightshow_start_times = {}
lightshow_last_trigger = 0
temp_read_counter = 0

# --- 3. HTML (split in parts to save RAM) ---

HTML_HEAD = """\
<!DOCTYPE html><html lang="nl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LED Controller</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#f1f5f9;min-height:100vh}
header{background:linear-gradient(135deg,#e30613,#b50010);padding:16px 20px;display:flex;align-items:center;gap:14px;box-shadow:0 4px 20px rgba(227,6,19,.4)}
header svg{flex-shrink:0}
header h1{font-size:20px;font-weight:800;letter-spacing:1px}
header small{font-size:11px;opacity:.7;display:block;margin-top:1px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;padding:14px}
.card{background:#1e293b;border-radius:16px;padding:18px;border:1px solid #334155}
.card-title{font-size:10px;font-weight:700;letter-spacing:2px;color:#64748b;text-transform:uppercase;margin-bottom:14px;display:flex;align-items:center;gap:6px}
.card-title::before{content:'';flex:1;height:1px;background:#334155}
.color-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.cbtn{padding:14px 4px;border:2px solid transparent;border-radius:10px;cursor:pointer;font-size:10px;font-weight:700;letter-spacing:.5px;transition:all .2s;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.6)}
.cbtn:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.cbtn.active{border-color:#fff;box-shadow:0 0 0 3px rgba(255,255,255,.3),0 6px 20px rgba(0,0,0,.4);transform:translateY(-2px)}
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #1e293b}
.toggle-row:last-child{border:none}
.toggle-left{display:flex;align-items:center;gap:10px}
.toggle-dot{width:10px;height:10px;border-radius:50%;background:#334155;transition:.3s}
.toggle-dot.on{background:#22c55e;box-shadow:0 0 8px #22c55e}
.tlabel{font-size:13px;font-weight:600}
.tinfo{font-size:11px;color:#64748b;margin-top:1px}
.switch{position:relative;width:48px;height:26px;flex-shrink:0}
.switch input{opacity:0;width:0;height:0;position:absolute}
.sw-track{position:absolute;inset:0;background:#334155;border-radius:26px;cursor:pointer;transition:.3s}
.sw-track::before{content:'';position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.3s;box-shadow:0 2px 4px rgba(0,0,0,.3)}
input:checked+.sw-track{background:#e30613}
input:checked+.sw-track::before{transform:translateX(22px)}
.range-wrap{margin-top:6px}
.range-header{display:flex;justify-content:space-between;font-size:12px;color:#94a3b8;margin-bottom:8px}
.range-header span{font-weight:700;color:#e30613}
input[type=range]{width:100%;-webkit-appearance:none;height:6px;border-radius:6px;background:#334155;outline:none;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:22px;height:22px;border-radius:50%;background:#e30613;cursor:pointer;box-shadow:0 2px 8px rgba(227,6,19,.5);border:2px solid #fff}
input[type=range]:disabled{opacity:.4;cursor:not-allowed}
.sensor-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.sensor-box{background:#0f172a;border-radius:12px;padding:16px;text-align:center;border:1px solid #1e293b}
.s-value{font-size:42px;font-weight:900;line-height:1;background:linear-gradient(135deg,#e30613,#ff6b6b);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.s-unit{font-size:11px;color:#64748b;margin-top:4px;letter-spacing:1px;text-transform:uppercase}
.s-icon{font-size:22px;margin-bottom:4px}
.status-bar{background:#0f172a;border-top:1px solid #1e293b;padding:10px 14px;font-size:11px;color:#475569;display:flex;justify-content:space-between;align-items:center}
.dot-live{width:7px;height:7px;border-radius:50%;background:#22c55e;animation:blink 1.5s infinite;display:inline-block;margin-right:5px}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
@media(max-width:360px){.color-grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<header>
<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
<div><h1>LED CONTROLLER</h1><small>ESP32 &bull; APA102 &bull; 140 LEDs</small></div>
</header>
<div class="grid">
"""

HTML_COLORS = """\
<div class="card">
<div class="card-title">Kleur &amp; Modus</div>
<div class="color-grid">
<button class="cbtn" id="m-white"   style="background:#aaa"       onclick="setMode('white')">WIT</button>
<button class="cbtn" id="m-warm"    style="background:#c87428"    onclick="setMode('warm')">WARM</button>
<button class="cbtn" id="m-red"     style="background:#cc0000"    onclick="setMode('red')">ROOD</button>
<button class="cbtn" id="m-green"   style="background:#15803d"    onclick="setMode('green')">GROEN</button>
<button class="cbtn" id="m-blue"    style="background:#1d4ed8"    onclick="setMode('blue')">BLAUW</button>
<button class="cbtn" id="m-purple"  style="background:#7e22ce"    onclick="setMode('purple')">PAARS</button>
<button class="cbtn" id="m-cyan"    style="background:#0e7490"    onclick="setMode('cyan')">CYAAN</button>
<button class="cbtn" id="m-yellow"  style="background:#a16207"    onclick="setMode('yellow')">GEEL</button>
<button class="cbtn" id="m-off"     style="background:#1e293b;border:1px solid #334155;grid-column:span 4" onclick="setMode('off')">&#9866; UIT</button>
</div>
</div>
"""

HTML_CONTROLS = """\
<div class="card">
<div class="card-title">Helderheid &amp; Auto</div>
<div class="range-wrap">
<div class="range-header"><span>MASTER HELDERHEID</span><span id="br-val">__BR__%</span></div>
<input type="range" id="br" min="1" max="100" value="__BR__" oninput="document.getElementById('br-val').innerText=this.value+'%'" onchange="setGlobal()">
</div>
<div style="height:14px"></div>
<div class="toggle-row">
<div class="toggle-left">
<div class="dot" id="dot-auto"></div>
<div><div class="tlabel">Auto-Lux</div><div class="tinfo">Helderheid via lichtsensor</div></div>
</div>
<label class="switch"><input type="checkbox" id="auto-lux" __AUTOCHECKED__ onchange="toggleAuto()"><span class="sw-track"></span></label>
</div>
</div>
"""

HTML_LIGHTSHOW = """\
<div class="card">
<div class="card-title">Lightshow Effecten</div>
<div class="toggle-row">
<div class="toggle-left">
<div class="toggle-dot" id="dot-wave"></div>
<div><div class="tlabel">Golf</div><div class="tinfo">Bewegende lichtgolf</div></div>
</div>
<label class="switch"><input type="checkbox" id="ls-wave" onchange="toggleEffect('wave')"><span class="sw-track"></span></label>
</div>
<div class="toggle-row">
<div class="toggle-left">
<div class="toggle-dot" id="dot-pulse"></div>
<div><div class="tlabel">Puls</div><div class="tinfo">Uitdijende golven vanuit midden</div></div>
</div>
<label class="switch"><input type="checkbox" id="ls-pulse" onchange="toggleEffect('pulse')"><span class="sw-track"></span></label>
</div>
<div class="toggle-row">
<div class="toggle-left">
<div class="toggle-dot" id="dot-strobe"></div>
<div><div class="tlabel">Strobe</div><div class="tinfo">Snelle glitter flitsen</div></div>
</div>
<label class="switch"><input type="checkbox" id="ls-strobe" onchange="toggleEffect('strobe')"><span class="sw-track"></span></label>
</div>
<div class="toggle-row">
<div class="toggle-left">
<div class="toggle-dot" id="dot-rainbow"></div>
<div><div class="tlabel">Regenboog</div><div class="tinfo">Continue kleurencyclus</div></div>
</div>
<label class="switch"><input type="checkbox" id="ls-rainbow" onchange="toggleEffect('rainbow')"><span class="sw-track"></span></label>
</div>
</div>
"""

HTML_SENSORS = """\
<div class="card">
<div class="card-title">Sensoren</div>
<div class="sensor-row">
<div class="sensor-box">
<div class="s-icon">&#9728;</div>
<div class="s-value" id="s-lux">__LUX__</div>
<div class="s-unit">% Lichtintensiteit</div>
</div>
<div class="sensor-box">
<div class="s-icon">&#127777;</div>
<div class="s-value" id="s-temp">__TEMP__</div>
<div class="s-unit">&deg;C Temperatuur</div>
</div>
</div>
</div>
"""

HTML_TAIL = """\
</div>
<div class="status-bar">
<div><span class="dot-live"></span>Live verbinding actief</div>
<div id="last-update">--</div>
</div>
<script>
var currentMode='__MODE__';
var effects={wave:__WAVE__,pulse:__PULSE__,strobe:__STROBE__,rainbow:__RAINBOW__};

function markMode(m){
  document.querySelectorAll('.cbtn').forEach(b=>b.classList.remove('active'));
  var el=document.getElementById('m-'+m);
  if(el)el.classList.add('active');
  currentMode=m;
}
function markEffects(){
  ['wave','pulse','strobe','rainbow'].forEach(function(e){
    var chk=document.getElementById('ls-'+e);
    var dot=document.getElementById('dot-'+e);
    if(chk){chk.checked=!!effects[e];}
    if(dot){dot.className='toggle-dot'+(effects[e]?' on':'');}
  });
}
function syncAutoUI(isAuto){
  var br=document.getElementById('br');
  br.disabled=isAuto;
  var dot=document.getElementById('dot-auto');
  if(dot){dot.className='toggle-dot'+(isAuto?' on':'');}
}

function setMode(m){
  fetch('/mode/'+m).then(function(){markMode(m);effects={};markEffects();});
}
function setGlobal(){
  var v=document.getElementById('br').value;
  fetch('/set_global?br='+v);
}
function toggleAuto(){
  var chk=document.getElementById('auto-lux');
  fetch('/toggle/auto').then(function(){syncAutoUI(chk.checked);});
}
function toggleEffect(e){
  fetch('/lightshow/'+e+'/toggle').then(function(){
    effects[e]=!effects[e];markEffects();
  });
}

function pollState(){
  fetch('/api/state').then(function(r){return r.json();}).then(function(d){
    document.getElementById('s-lux').innerText=d.lux;
    document.getElementById('s-temp').innerText=d.temp.toFixed(1);
    if(d.mode!==currentMode)markMode(d.mode);
    var chk=document.getElementById('auto-lux');
    if(chk.checked!==d.auto){chk.checked=d.auto;syncAutoUI(d.auto);}
    var brEl=document.getElementById('br');
    if(!d.auto&&Math.abs(parseInt(brEl.value)-d.br)>1){
      brEl.value=d.br;
      document.getElementById('br-val').innerText=d.br+'%';
    }
    var dirty=false;
    ['wave','pulse','strobe','rainbow'].forEach(function(e){
      if(!!effects[e]!==!!d.effects[e]){effects[e]=d.effects[e];dirty=true;}
    });
    if(dirty)markEffects();
    var now=new Date();
    document.getElementById('last-update').innerText='Update: '+now.getHours()+':'+String(now.getMinutes()).padStart(2,'0')+':'+String(now.getSeconds()).padStart(2,'0');
  }).catch(function(){});
}

markMode(currentMode);
markEffects();
syncAutoUI(document.getElementById('auto-lux').checked);
setInterval(pollState,1500);
</script>
</body></html>"""


def get_html():
    br_val = int(global_br * 100)
    autochecked = "checked" if auto_light else ""
    mode_safe = mode if mode else "off"

    wave_js   = "true" if "wave"    in lightshow_active else "false"
    pulse_js  = "true" if "pulse"   in lightshow_active else "false"
    strobe_js = "true" if "strobe"  in lightshow_active else "false"
    rainbow_js= "true" if "rainbow" in lightshow_active else "false"

    controls = HTML_CONTROLS.replace("__BR__",      str(br_val)) \
                             .replace("__AUTOCHECKED__", autochecked)

    sensors = HTML_SENSORS.replace("__LUX__",  str(perc_val)) \
                           .replace("__TEMP__", str(round(temp_val, 1)))

    tail = HTML_TAIL.replace("__MODE__",    mode_safe)   \
                    .replace("__WAVE__",    wave_js)     \
                    .replace("__PULSE__",   pulse_js)    \
                    .replace("__STROBE__",  strobe_js)   \
                    .replace("__RAINBOW__", rainbow_js)

    return HTML_HEAD + HTML_COLORS + controls + HTML_LIGHTSHOW + sensors + tail


# --- 4. SERVER ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(3)
s.settimeout(0.01)


def send_json(conn, data):
    body = json.dumps(data)
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n\r\n')
    conn.send(body)


def send_ok(conn):
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')


def send_html(conn):
    html = get_html()
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
    # Send in chunks to avoid hitting socket buffer limits
    chunk = 1024
    for i in range(0, len(html), chunk):
        conn.send(html[i:i + chunk])


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
            req = conn.recv(1024).decode("utf-8", "ignore")
            try:
                path = req.split('\r\n')[0].split()[1]
            except:
                path = "/"

            if path == "/api/sensor":
                send_json(conn, {"lux": perc_val, "temp": round(temp_val, 1)})

            elif path == "/api/state":
                send_json(conn, {
                    "lux":     perc_val,
                    "temp":    round(temp_val, 1),
                    "mode":    mode,
                    "auto":    auto_light,
                    "br":      int(global_br * 100),
                    "effects": {
                        "wave":    "wave"    in lightshow_active,
                        "pulse":   "pulse"   in lightshow_active,
                        "strobe":  "strobe"  in lightshow_active,
                        "rainbow": "rainbow" in lightshow_active,
                    }
                })

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
