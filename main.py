from machine import Pin, SPI, ADC
import apa102, socket, time, random, onewire, ds18x20, json, os, gc
try:
    from machine import I2C
except:
    I2C = None

try:
    import urequests
except:
    urequests = None

try:
    import ussl
except:
    ussl = None

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

# Optional I2C sensor autodetect (BH1750/BME280/SHT3x)
i2c = None
i2c_addrs = []
if I2C is not None:
    try:
        # Typical ESP32 pins for I2C
        i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
        i2c_addrs = i2c.scan()
    except:
        i2c = None
        i2c_addrs = []

# Optional PIR autodetect candidates (best effort)
PIR_CANDIDATE_PINS = [27, 26, 25, 33, 32, 14, 13]
pir_candidates = []
for _pin in PIR_CANDIDATE_PINS:
    try:
        pir_candidates.append((_pin, Pin(_pin, Pin.IN)))
    except:
        pass
pir_selected_pin = None
pir_high_counter = 0

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
motion_detected = None
lux_source = "ldr"
temp_source = "none"
lightshow_active = {}
lightshow_start_times = {}
lightshow_last_trigger = 0
temp_read_counter = 0
timer_countdown_active = False
timer_countdown_end_ms = 0
timer_countdown_total_ms = 1
timer_done_flash_end_ms = 0

bh1750_lux = None

scheduler_config = {
    "enabled": False,
    "pauseDurationMin": 15,
    "lessons": [],
    "breaks": [],
}

# --- OTA UPDATE CONFIG ---
# Set to your own private random token before exposing ESP32 to network.
UPDATE_AUTH_TOKEN = "Vives_plus"
# Auto-generated at boot from hash(main.py).
FIRMWARE_VERSION = "fw-unknown"
# Example: https://raw.githubusercontent.com/<owner>/<repo>/<branch>
UPDATE_BASE_URL = "https://raw.githubusercontent.com/AlessioD200/LEDTEST/main"
UPDATE_DEFAULT_FILES = [
    {"local": "index.html", "remote": "web/index.html"},
    {"local": "styles.css", "remote": "web/styles.css"},
    {"local": "app.js", "remote": "web/app.js"},
]
UPDATE_VERSION_FILE = "ota_version.json"
update_last_result = {
    "ok": False,
    "message": "No update run yet",
    "updated": [],
    "ts": 0,
}
version_info = {
    "firmware": FIRMWARE_VERSION,
    "buildId": "boot-unknown",
    "otaCount": 0,
    "lastUpdateTs": 0,
    "lastUpdated": [],
}
update_job = None
update_running = False
update_reboot_at_ms = None
update_reboot_pending = False

sensor_registry = {
    "ldr": True,
    "ds18b20": bool(temp_roms),
    "bh1750": (0x23 in i2c_addrs) or (0x5C in i2c_addrs),
    "bme280": (0x76 in i2c_addrs) or (0x77 in i2c_addrs),
    "sht3x": (0x44 in i2c_addrs) or (0x45 in i2c_addrs),
    "pir": False,
}


def detect_motion_sensor():
    global pir_selected_pin, pir_high_counter
    if pir_selected_pin is not None:
        return
    # Best-effort auto detect: if one candidate pin reads HIGH repeatedly, assume PIR is connected there.
    for pin_no, pin_obj in pir_candidates:
        try:
            if pin_obj.value():
                pir_high_counter += 1
                if pir_high_counter >= 3:
                    pir_selected_pin = pin_no
                    sensor_registry["pir"] = True
                    break
            else:
                pir_high_counter = 0
        except:
            pass


def read_motion_value():
    if pir_selected_pin is None:
        return None
    for pin_no, pin_obj in pir_candidates:
        if pin_no == pir_selected_pin:
            try:
                return bool(pin_obj.value())
            except:
                return None
    return None


def read_bh1750_lux():
    if i2c is None:
        return None
    addr = 0x23 if 0x23 in i2c_addrs else (0x5C if 0x5C in i2c_addrs else None)
    if addr is None:
        return None
    try:
        # Continuously H-Resolution Mode
        i2c.writeto(addr, b"\x10")
        time.sleep_ms(180)
        data = i2c.readfrom(addr, 2)
        raw = (data[0] << 8) | data[1]
        lux = raw / 1.2
        return max(0.0, lux)
    except:
        return None


def read_sht3x_temp():
    if i2c is None:
        return None
    addr = 0x44 if 0x44 in i2c_addrs else (0x45 if 0x45 in i2c_addrs else None)
    if addr is None:
        return None
    try:
        i2c.writeto(addr, b"\x24\x00")
        time.sleep_ms(20)
        data = i2c.readfrom(addr, 6)
        raw_t = (data[0] << 8) | data[1]
        temp_c = -45 + (175 * raw_t / 65535.0)
        return temp_c
    except:
        return None


def read_bme280_temp():
    # Lightweight fallback detector only (real compensation omitted to keep memory low).
    # Returns None if not usable.
    if i2c is None:
        return None
    addr = 0x76 if 0x76 in i2c_addrs else (0x77 if 0x77 in i2c_addrs else None)
    if addr is None:
        return None
    try:
        # Simple check: read chip id register
        chip_id = i2c.readfrom_mem(addr, 0xD0, 1)[0]
        if chip_id not in (0x58, 0x60, 0x61):
            return None
        # Without full compensation this value is not reliable; keep as unavailable.
        return None
    except:
        return None


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


def parse_url(url):
    scheme = "http"
    rest = str(url)
    if rest.startswith("https://"):
        scheme = "https"
        rest = rest[8:]
    elif rest.startswith("http://"):
        rest = rest[7:]

    slash_idx = rest.find("/")
    if slash_idx >= 0:
        host_port = rest[:slash_idx]
        path = rest[slash_idx:]
    else:
        host_port = rest
        path = "/"

    if ":" in host_port:
        host, port_str = host_port.split(":", 1)
        try:
            port = int(port_str)
        except:
            port = 443 if scheme == "https" else 80
    else:
        host = host_port
        port = 443 if scheme == "https" else 80

    if not path:
        path = "/"
    return scheme, host, port, path


def sock_read(sock, n=512):
    if hasattr(sock, "read"):
        return sock.read(n)
    return sock.recv(n)


def sock_write(sock, data):
    if hasattr(sock, "write"):
        return sock.write(data)
    return sock.send(data)


def sock_readline(sock):
    line = b""
    while True:
        ch = sock_read(sock, 1)
        if not ch:
            break
        line += ch
        if ch == b"\n":
            break
        if len(line) > 4096:
            break
    return line


def download_to_file_stream(url, target_path, redirect_depth=0):
    if redirect_depth > 3:
        raise Exception("Too many redirects")

    scheme, host, port, path = parse_url(url)
    if scheme == "https" and ussl is None:
        raise Exception("HTTPS requested but ussl not available")

    tmp_path = target_path + ".tmp"
    _safe_remove(tmp_path)
    sock = None
    ssock = None
    has_default_timeout = hasattr(socket, "setdefaulttimeout")

    try:
        if has_default_timeout:
            try:
                socket.setdefaulttimeout(20)
            except:
                pass

        ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket()
        sock.connect(ai)
        ssock = sock
        if scheme == "https":
            try:
                ssock = ussl.wrap_socket(sock, server_hostname=host)
            except:
                ssock = ussl.wrap_socket(sock)

        req = "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nUser-Agent: esp32-ota\r\n\r\n".format(path, host)
        sock_write(ssock, req.encode())

        status_line = sock_readline(ssock)
        if not status_line:
            raise Exception("No HTTP response")

        try:
            status_code = int(status_line.split(b" ")[1])
        except:
            raise Exception("Invalid HTTP status line")

        headers = {}
        while True:
            line = sock_readline(ssock)
            if not line or line in (b"\r\n", b"\n"):
                break
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()

        if status_code in (301, 302, 303, 307, 308):
            loc = headers.get(b"location", b"")
            new_url = loc.decode() if isinstance(loc, bytes) else str(loc)
            if not new_url:
                raise Exception("Redirect without Location")
            if new_url.startswith("/"):
                new_url = "{}://{}{}".format(scheme, host, new_url)
            return download_to_file_stream(new_url, target_path, redirect_depth + 1)

        if status_code != 200:
            raise Exception("HTTP {} for {}".format(status_code, url))

        transfer = headers.get(b"transfer-encoding", b"").lower()
        clen_raw = headers.get(b"content-length", b"0")
        try:
            content_len = int(clen_raw)
        except:
            content_len = 0

        with open(tmp_path, "wb") as out:
            if transfer == b"chunked":
                while True:
                    sz_line = sock_readline(ssock)
                    if not sz_line:
                        break
                    sz_str = sz_line.strip().split(b";", 1)[0]
                    chunk_size = int(sz_str, 16) if sz_str else 0
                    if chunk_size <= 0:
                        # consume trailing CRLF
                        sock_readline(ssock)
                        break

                    remaining = chunk_size
                    while remaining > 0:
                        chunk = sock_read(ssock, min(512, remaining))
                        if not chunk:
                            raise Exception("Connection closed during chunk")
                        out.write(chunk)
                        remaining -= len(chunk)
                    # consume CRLF after each chunk
                    sock_readline(ssock)
                    gc.collect()
            elif content_len > 0:
                remaining = content_len
                while remaining > 0:
                    chunk = sock_read(ssock, min(512, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
                    gc.collect()
            else:
                while True:
                    chunk = sock_read(ssock, 512)
                    if not chunk:
                        break
                    out.write(chunk)
                    gc.collect()

        _safe_remove(target_path)
        os.rename(tmp_path, target_path)
        gc.collect()
    finally:
        if has_default_timeout:
            try:
                socket.setdefaulttimeout(None)
            except:
                pass
        if ssock is not None:
            try:
                ssock.close()
            except:
                pass
        if sock is not None and sock is not ssock:
            try:
                sock.close()
            except:
                pass
        _safe_remove(tmp_path)


def fnv1a_update(hash_val, data):
    for b in data:
        hash_val ^= b
        hash_val = (hash_val * 16777619) & 0xFFFFFFFF
    return hash_val


def file_hash32(path):
    try:
        h = 2166136261
        with open(path, "rb") as f:
            while True:
                chunk = f.read(512)
                if not chunk:
                    break
                h = fnv1a_update(h, chunk)
        return h
    except:
        return None


def detect_firmware_version():
    h = file_hash32("main.py")
    if h is None:
        return "fw-unknown"
    return "fw-{:08x}".format(h)


def compute_update_build_hash(paths):
    h = 2166136261
    if not isinstance(paths, list):
        return h

    sorted_paths = [str(p) for p in paths]
    sorted_paths.sort()
    for p in sorted_paths:
        h = fnv1a_update(h, p.encode())
        ph = file_hash32(p)
        if ph is not None:
            h = fnv1a_update(h, "{:08x}".format(ph).encode())
    return h


def load_version_info():
    global version_info
    version_info["firmware"] = FIRMWARE_VERSION
    try:
        with open(UPDATE_VERSION_FILE, "r") as f:
            raw = f.read()
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            build_id = parsed.get("buildId")
            if isinstance(build_id, str) and build_id:
                version_info["buildId"] = build_id
            version_info["otaCount"] = clamp_int(parsed.get("otaCount", 0), 0, 999999)
            version_info["lastUpdateTs"] = clamp_int(parsed.get("lastUpdateTs", 0), 0, 2147483647)
            last_updated = parsed.get("lastUpdated", [])
            if isinstance(last_updated, list):
                version_info["lastUpdated"] = [str(x) for x in last_updated][:12]
    except:
        pass


def save_version_info():
    tmp = UPDATE_VERSION_FILE + ".tmp"
    _safe_remove(tmp)
    try:
        payload = {
            "buildId": version_info.get("buildId", "boot-unknown"),
            "otaCount": int(version_info.get("otaCount", 0)),
            "lastUpdateTs": int(version_info.get("lastUpdateTs", 0)),
            "lastUpdated": version_info.get("lastUpdated", []),
        }
        with open(tmp, "w") as f:
            f.write(json.dumps(payload))
        _safe_remove(UPDATE_VERSION_FILE)
        os.rename(tmp, UPDATE_VERSION_FILE)
    except:
        _safe_remove(tmp)


def download_to_file(url, target_path):
    # Always use streaming socket downloader to avoid large-memory spikes during OTA.
    return download_to_file_stream(url, target_path)


def perform_github_update(base_url=None, files=None):
    global update_last_result, version_info

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
        remote_name = str(remote_path).lstrip("/")
        if "/api/ota" in base and remote_name.startswith("web/"):
            remote_name = remote_name[4:]
        url = base.rstrip("/") + "/" + remote_name
        try:
            download_to_file(url, str(local_path))
            updated.append(str(local_path))
        except Exception as e:
            emsg = str(e)
            if "MBEDTLS_ERR_RSA_PUBLIC_FAILED" in emsg or "MBEDTLS_ERR_MPI_ALLOC_FAILED" in emsg:
                raise Exception(
                    "TLS memory error on ESP32 during GitHub update. "
                    "Use a local HTTP mirror as baseUrl (for example http://<host-ip>:8000/ota). "
                    "Failing file: {}".format(local_path)
                )
            raise
        finally:
            gc.collect()

    update_last_result = {
        "ok": True,
        "message": "Update completed",
        "updated": updated,
        "ts": int(time.time()),
    }

    version_info["firmware"] = FIRMWARE_VERSION
    update_hash = compute_update_build_hash(updated)
    version_info["buildId"] = "ota-{}-{:08x}".format(int(update_last_result["ts"]), update_hash)
    version_info["otaCount"] = int(version_info.get("otaCount", 0)) + 1
    version_info["lastUpdateTs"] = int(update_last_result["ts"])
    version_info["lastUpdated"] = updated[:12]
    save_version_info()

    return update_last_result


def queue_update_job(base_url=None, files=None, reboot=False):
    global update_job, update_last_result
    if update_job or update_running:
        raise Exception("Update already running")

    update_job = {
        "baseUrl": base_url,
        "files": files,
        "reboot": bool(reboot),
    }
    update_last_result = {
        "ok": True,
        "message": "Update queued{}".format(", reboot requested" if bool(reboot) else ""),
        "updated": [],
        "ts": int(time.time()),
    }
    return update_last_result


def process_update_job():
    global update_job, update_running, update_last_result, update_reboot_at_ms, update_reboot_pending

    if update_job and not update_running:
        job = update_job
        update_job = None
        update_running = True
        update_last_result = {
            "ok": True,
            "message": "Update running",
            "updated": [],
            "ts": int(time.time()),
        }
        try:
            result = perform_github_update(job.get("baseUrl"), job.get("files"))
            if job.get("reboot") and machine is not None:
                update_reboot_pending = True
                # Give UI polling a short window to fetch final update result before reset.
                update_reboot_at_ms = time.ticks_add(time.ticks_ms(), 3500)
                result["message"] = "Update completed, reboot scheduled"
            update_last_result = result
        except Exception as e:
            update_last_result = {
                "ok": False,
                "message": str(e),
                "updated": [],
                "ts": int(time.time()),
            }
        finally:
            update_running = False

    if update_reboot_at_ms is not None and machine is not None:
        if time.ticks_diff(time.ticks_ms(), update_reboot_at_ms) >= 0:
            # Clear flags before reset attempt to avoid repeated crash loops if reset fails.
            update_reboot_at_ms = None
            update_reboot_pending = False
            try:
                gc.collect()
                time.sleep_ms(120)
                machine.reset()
            except Exception as e:
                update_last_result = {
                    "ok": False,
                    "message": "Reboot failed: {}".format(str(e)),
                    "updated": update_last_result.get("updated", []),
                    "ts": int(time.time()),
                }

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
                "motion": motion_detected,
                "luxSource": lux_source,
                "tempSource": temp_source,
            },
        },
        "sensors": {
            "available": sensor_registry,
            "pirPin": pir_selected_pin,
        },
        "scheduler": scheduler_config,
        "version": {
            "firmware": version_info.get("firmware", FIRMWARE_VERSION),
            "buildId": version_info.get("buildId", "boot-unknown"),
            "otaCount": version_info.get("otaCount", 0),
            "lastUpdateTs": version_info.get("lastUpdateTs", 0),
            "lastUpdated": version_info.get("lastUpdated", []),
        },
    }
    return payload


FIRMWARE_VERSION = detect_firmware_version()
version_info["firmware"] = FIRMWARE_VERSION
if version_info.get("buildId") in (None, "", "boot-unknown"):
    version_info["buildId"] = "boot-{}".format(FIRMWARE_VERSION)
load_version_info()


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
    global timer_countdown_active, timer_countdown_end_ms, timer_countdown_total_ms, timer_done_flash_end_ms

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
            lightshow_start_times[effect] = time.ticks_ms()

    if "timer" in payload and isinstance(payload.get("timer"), dict):
        timer = payload.get("timer")
        timer_mode = timer.get("mode", "off")
        rem_ms = clamp_int(timer.get("remainingMs", 0), 0, 86400000)
        total_ms = clamp_int(timer.get("totalMs", 1), 1, 86400000)

        if timer_mode == "countdown":
            timer_countdown_active = True
            timer_countdown_total_ms = max(1, total_ms)
            timer_countdown_end_ms = time.ticks_add(time.ticks_ms(), rem_ms)
            timer_done_flash_end_ms = 0
        elif timer_mode == "done":
            timer_countdown_active = False
            timer_countdown_total_ms = 1
            timer_countdown_end_ms = 0
            timer_done_flash_end_ms = time.ticks_add(time.ticks_ms(), rem_ms)
        else:
            timer_countdown_active = False
            timer_countdown_total_ms = 1
            timer_countdown_end_ms = 0
            timer_done_flash_end_ms = 0


# --- 5. MAIN LOOP ---
while True:

    # 5a. SENSORS
    try:
        detect_motion_sensor()

        val_raw = ldr.read()
        sensor_buffer.append(val_raw)
        sensor_buffer.pop(0)
        smooth_val = sum(sensor_buffer) / len(sensor_buffer)
        perc_val = int(((4095 - smooth_val) / 4095) * 100)
        perc_val = max(0, min(100, perc_val))

        # Optional digital motion read
        motion_detected = read_motion_value()

        # Optional BH1750 lux override (read less often)
        if temp_read_counter % 20 == 0:
            bh = read_bh1750_lux()
            if bh is not None:
                bh1750_lux = bh
        if bh1750_lux is not None:
            # Map lux to 0..100 scale where darker => lower value
            perc_val = int(max(0, min(100, bh1750_lux / 10.0)))
            lux_source = "bh1750"
        else:
            lux_source = "ldr"

        if auto_light:
            final_br = max(0.01, min(1.0, perc_val / 100.0))
        else:
            final_br = global_br

        temp_read_counter += 1
        if temp_read_counter >= 75:
            temp_read_counter = 0
            temp_source = "none"
            if temp_roms:
                try:
                    ds.convert_temp()
                    time.sleep_ms(5)
                    for rom in temp_roms:
                        temp_val = ds.read_temp(rom)
                        temp_val = max(-40, min(125, temp_val))
                        temp_source = "ds18b20"
                        break
                except:
                    pass
            if temp_source == "none":
                t_sht = read_sht3x_temp()
                if t_sht is not None:
                    temp_val = max(-40, min(125, t_sht))
                    temp_source = "sht3x"
            if temp_source == "none":
                t_bme = read_bme280_temp()
                if t_bme is not None:
                    temp_val = max(-40, min(125, t_bme))
                    temp_source = "bme280"
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
                status = {
                    "ok": update_last_result.get("ok"),
                    "message": update_last_result.get("message"),
                    "updated": update_last_result.get("updated"),
                    "ts": update_last_result.get("ts"),
                    "inProgress": bool(update_running or update_job),
                    "rebootPending": bool(update_reboot_pending),
                    "version": {
                        "firmware": version_info.get("firmware", FIRMWARE_VERSION),
                        "buildId": version_info.get("buildId", "boot-unknown"),
                        "otaCount": version_info.get("otaCount", 0),
                        "lastUpdateTs": version_info.get("lastUpdateTs", 0),
                        "lastUpdated": version_info.get("lastUpdated", []),
                    },
                }
                send_json(conn, status)

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
                        result = queue_update_job(
                            payload.get("baseUrl"),
                            payload.get("files"),
                            payload.get("reboot", False),
                        )
                        send_json(conn, result)
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
                    now_ms = time.ticks_ms()
                    if time.ticks_diff(now_ms, lightshow_last_trigger) > 100:
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

    # 5b.1 Background OTA job runner
    try:
        process_update_job()
    except:
        pass

    # 5c. LED RENDERING
    try:
        now_ms = time.ticks_ms()

        # Manual timer visualization from UI payload: countdown from all LEDs to 0, then flash.
        if timer_done_flash_end_ms:
            if time.ticks_diff(timer_done_flash_end_ms, now_ms) > 0:
                blink_on = ((now_ms // 180) % 2) == 0
                for i in range(NUM_LEDS):
                    if not blink_on:
                        strip[i] = (0, 0, 0, 0)
                    else:
                        m = i % 3
                        if m == 0:
                            strip[i] = (255, 40, 40, 1.0)
                        elif m == 1:
                            strip[i] = (40, 180, 255, 1.0)
                        else:
                            strip[i] = (80, 255, 120, 1.0)
                strip.write()
                time.sleep(0.01)
                continue
            else:
                timer_done_flash_end_ms = 0

        if timer_countdown_active:
            remaining_ms = time.ticks_diff(timer_countdown_end_ms, now_ms)
            if remaining_ms <= 0:
                timer_countdown_active = False
                timer_done_flash_end_ms = time.ticks_add(now_ms, 3200)
                for i in range(NUM_LEDS):
                    strip[i] = (0, 0, 0, 0)
                strip.write()
                time.sleep(0.01)
                continue

            ratio = remaining_ms / float(max(1, timer_countdown_total_ms))
            if ratio < 0:
                ratio = 0
            if ratio > 1:
                ratio = 1

            lit_count = int(ratio * NUM_LEDS + 0.5)
            if lit_count < 0:
                lit_count = 0
            if lit_count > NUM_LEDS:
                lit_count = NUM_LEDS

            if ratio > 0.5:
                cr, cg, cb = 255, 255, 255
            elif ratio > 0.2:
                cr, cg, cb = 255, 200, 80
            else:
                cr, cg, cb = 255, 70, 70

            for i in range(NUM_LEDS):
                if i < lit_count:
                    strip[i] = (cr, cg, cb, 1.0)
                else:
                    strip[i] = (0, 0, 0, 0)
            strip.write()
            time.sleep(0.01)
            continue

        active_effects = [e for e in lightshow_active if e in lightshow_start_times]

        if active_effects:
            for i in range(NUM_LEDS):
                strip[i] = (0, 0, 0, 0)

            for effect in active_effects:
                ls_el = time.ticks_diff(now_ms, lightshow_start_times[effect])

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
