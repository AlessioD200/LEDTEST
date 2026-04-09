from machine import Pin, SPI, ADC
import apa102, socket, time, random, onewire, ds18x20, json, os

try:
    import urequests
except:
    urequests = None

try:
    import machine
except:
    machine = None

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

# --- OTA UPDATE CONFIG ---
# Set to your own private random token before exposing ESP32 to network.
UPDATE_AUTH_TOKEN = "Vives_plus"
# Example: https://raw.githubusercontent.com/<owner>/<repo>/<branch>
UPDATE_BASE_URL = "https://raw.githubusercontent.com/AlessioD200/LEDTEST/main"
UPDATE_DEFAULT_FILES = [
    {"local": "index.html", "remote": "web/index.html"},
    {"local": "styles.css", "remote": "web/styles.css"},
    {"local": "app.js", "remote": "web/app.js"},
]
update_last_result = {
    "ok": False,
    "message": "No update run yet",
    "updated": [],
    "ts": 0,
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


def _safe_remove(path):
    try:
        os.remove(path)
    except:
        pass


def download_to_file(url, target_path):
    if urequests is None:
        raise Exception("urequests not available on this firmware")

    resp = None
    tmp_path = target_path + ".tmp"
    _safe_remove(tmp_path)

    try:
        resp = urequests.get(url)
        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise Exception("HTTP {} for {}".format(status, url))

        with open(tmp_path, "wb") as out:
            raw = getattr(resp, "raw", None)
            if raw and hasattr(raw, "read"):
                while True:
                    chunk = raw.read(512)
                    if not chunk:
                        break
                    out.write(chunk)
            else:
                out.write(resp.content)

        _safe_remove(target_path)
        os.rename(tmp_path, target_path)
    finally:
        if resp:
            try:
                resp.close()
            except:
                pass
        _safe_remove(tmp_path)


def perform_github_update(base_url=None, files=None):
    global update_last_result

    base = base_url or UPDATE_BASE_URL
    if not base:
        raise Exception("UPDATE_BASE_URL is empty")

    entries = files if isinstance(files, list) and len(files) > 0 else UPDATE_DEFAULT_FILES
    updated = []

    for item in entries:
        local_path = item.get("local") if isinstance(item, dict) else None
        remote_path = item.get("remote") if isinstance(item, dict) else None
        if not local_path or not remote_path:
            continue
        url = base.rstrip("/") + "/" + str(remote_path).lstrip("/")
        download_to_file(url, str(local_path))
        updated.append(str(local_path))

    update_last_result = {
        "ok": True,
        "message": "Update completed",
        "updated": updated,
        "ts": int(time.time()),
    }
    return update_last_result

# --- 3. HTML (separate files on ESP filesystem to reduce RAM) ---

FALLBACK_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LED Controller</title><style>body{font-family:sans-serif;margin:20px;background:#0f172a;color:#e2e8f0}code{background:#1e293b;padding:2px 6px;border-radius:4px}</style></head><body><h2>LED Controller</h2><p>Web assets ontbreken op de ESP32 filesystem.</p><p>Upload <code>index.html</code>, <code>styles.css</code>, <code>app.js</code> en optioneel <code>Logo-v.png</code>.</p></body></html>"""

STATIC_FILE_CANDIDATES = {
    "/": ["index.html", "/index.html", "web/index.html", "/web/index.html"],
    "/index.html": ["index.html", "/index.html", "web/index.html", "/web/index.html"],
    "/styles.css": ["styles.css", "/styles.css", "web/styles.css", "/web/styles.css"],
    "/app.js": ["app.js", "/app.js", "web/app.js", "/web/app.js"],
    "/Logo-v.png": ["Logo-v.png", "/Logo-v.png", "web/Logo-v.png", "/web/Logo-v.png"],
}

STATIC_CONTENT_TYPES = {
    "/": "text/html; charset=utf-8",
    "/index.html": "text/html; charset=utf-8",
    "/styles.css": "text/css; charset=utf-8",
    "/app.js": "application/javascript; charset=utf-8",
    "/Logo-v.png": "image/png",
}

def get_html():
    return FALLBACK_HTML

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


def send_forbidden(conn, msg="Forbidden"):
    body = json.dumps({"ok": False, "error": msg})
    conn.send(b'HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\n\r\n')
    conn.send(body.encode())


def send_ok(conn):
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')


def send_html(conn):
    html = get_html()
    conn.send(b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
    chunk = 1024
    for i in range(0, len(html), chunk):
        conn.send(html[i:i + chunk].encode())


def send_static_for_path(conn, path):
    raw_path = path.split("?")[0]
    candidates = STATIC_FILE_CANDIDATES.get(raw_path)
    if not candidates:
        return False

    content_type = STATIC_CONTENT_TYPES.get(raw_path, "application/octet-stream")

    for file_path in candidates:
        try:
            f = open(file_path, "rb")
        except:
            continue

        try:
            header = "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nCache-Control: no-store\r\nPragma: no-cache\r\n\r\n".format(content_type)
            conn.send(header.encode())
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break
                conn.send(chunk)
            return True
        except:
            pass
        finally:
            try:
                f.close()
            except:
                pass

    if raw_path in ("/", "/index.html"):
        send_html(conn)
        return True

    return False


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
            route_path = path.split("?")[0]

            if method == "GET" and send_static_for_path(conn, route_path):
                pass

            elif route_path == "/api/sensor":
                send_json(conn, {"lux": perc_val, "temp": round(temp_val, 1)})

            elif route_path == "/api/state":
                send_json(conn, build_state_payload())

            elif method == "POST" and route_path == "/api/command":
                try:
                    payload = json.loads(body) if body else {}
                    if isinstance(payload, dict):
                        if isinstance(payload.get("desired"), dict):
                            payload = payload.get("desired")
                        apply_command_payload(payload)
                except:
                    pass
                send_json(conn, {"ok": True})

            elif method == "POST" and route_path == "/api/scheduler":
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

            elif method == "POST" and route_path == "/api/scheduler/start":
                scheduler_config["enabled"] = True
                send_json(conn, {"ok": True})

            elif method == "POST" and route_path == "/api/scheduler/stop":
                scheduler_config["enabled"] = False
                send_json(conn, {"ok": True})

            elif method == "GET" and route_path == "/api/update/status":
                send_json(conn, update_last_result)

            elif method == "POST" and route_path == "/api/update":
                try:
                    payload = json.loads(body) if body else {}
                except:
                    payload = {}

                if not isinstance(payload, dict):
                    payload = {}

                token = str(payload.get("token", ""))
                if UPDATE_AUTH_TOKEN and UPDATE_AUTH_TOKEN != "change-me" and token != UPDATE_AUTH_TOKEN:
                    send_forbidden(conn, "Invalid token")
                else:
                    try:
                        result = perform_github_update(
                            payload.get("baseUrl"),
                            payload.get("files"),
                        )
                        send_json(conn, result)

                        if payload.get("reboot", True) and machine is not None:
                            time.sleep_ms(250)
                            machine.reset()
                    except Exception as e:
                        update_last_result = {
                            "ok": False,
                            "message": str(e),
                            "updated": [],
                            "ts": int(time.time()),
                        }
                        send_json(conn, update_last_result)

            elif route_path.startswith("/set_global"):
                try:
                    global_br = int(path.split("br=")[1]) / 100.0
                except:
                    pass
                send_ok(conn)

            elif route_path.startswith("/lightshow/") and route_path.endswith("/toggle"):
                try:
                    effect = route_path.split("/lightshow/")[1].split("/toggle")[0]
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

            elif route_path == "/toggle/auto":
                auto_light = not auto_light
                send_ok(conn)

            elif route_path.startswith("/mode/"):
                try:
                    mode = route_path.split("/mode/")[1]
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
