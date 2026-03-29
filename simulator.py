"""
LED Controller Simulator
Draait op elke PC met Python 3 — geen ESP32 vereist.
Start: python3 simulator.py
Open:  http://localhost:8080
"""

import http.server
import threading
import json
import math
import random
import time
import os
import mimetypes

# ── State ─────────────────────────────────────────────────────────────────────
NUM_LEDS       = 140
state_lock     = threading.Lock()
state = {
    "mode":             "white",
    "auto_light":       False,
    "global_br":        0.5,
    "perc_val":         55,
    "temp_val":         22.4,
    "lightshow_active": {},
    "lightshow_start":  {},
    "last_trigger":     0,
}
led_colors = [(0, 0, 0)] * NUM_LEDS   # current rendered colors (r, g, b 0-255)


# ── Sensor simulation ─────────────────────────────────────────────────────────
def sensor_thread():
    t = 0.0
    while True:
        with state_lock:
            state["perc_val"] = int(50 + 30 * math.sin(t * 0.3))
            state["temp_val"] = round(22.0 + 3 * math.sin(t * 0.07) + random.uniform(-0.1, 0.1), 1)
        t += 0.1
        time.sleep(0.1)


# ── LED rendering ─────────────────────────────────────────────────────────────
def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, v))

def apply_br(r, g, b, br):
    return (clamp(int(r * br)), clamp(int(g * br)), clamp(int(b * br)))

def render_thread():
    global led_colors
    while True:
        with state_lock:
            mode        = state["mode"]
            auto_light  = state["auto_light"]
            global_br   = state["global_br"]
            perc_val    = state["perc_val"]
            ls_active   = dict(state["lightshow_active"])
            ls_start    = dict(state["lightshow_start"])

        final_br = max(0.01, min(1.0, perc_val / 100.0)) if auto_light else global_br
        now_ms   = int(time.time() * 1000)
        active   = [e for e in ls_active if e in ls_start]
        colors   = [(0, 0, 0)] * NUM_LEDS

        if active:
            for effect in active:
                ls_el = now_ms - ls_start[effect]

                if effect == "wave":
                    wc = (ls_el / 50.0) % (NUM_LEDS + 80)
                    for i in range(NUM_LEDS):
                        d = abs(i - wc)
                        if d < 40:
                            br = max(0.0, 1 - (d / 40.0) ** 2)
                            colors[i] = (clamp(int(255 * br)),) * 3

                elif effect == "pulse":
                    cp = NUM_LEDS // 2
                    wd = (ls_el / 30.0) % (NUM_LEDS // 2 + 20)
                    for i in range(NUM_LEDS):
                        dc = abs(i - cp)
                        if abs(dc - wd) < 15:
                            br = max(0.0, 1 - (abs(dc - wd) / 15.0) ** 2)
                            colors[i] = (clamp(int(255 * br)),) * 3

                elif effect == "strobe":
                    for i in range(NUM_LEDS):
                        if random.random() < 0.5:
                            colors[i] = (255, 255, 255)

                elif effect == "rainbow":
                    for i in range(NUM_LEDS):
                        hp = (i * 10 + ls_el // 20) % 360
                        h  = hp / 360.0
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
                        old = colors[i]
                        colors[i] = (clamp(old[0] + int(r * 0.8)),
                                     clamp(old[1] + int(g * 0.8)),
                                     clamp(old[2] + int(b * 0.8)))
        else:
            palette = {
                "red":    (255, 0,   0  ),
                "green":  (0,   255, 0  ),
                "blue":   (0,   0,   255),
                "white":  (255, 255, 255),
                "purple": (128, 0,   128),
                "cyan":   (0,   255, 255),
                "yellow": (255, 255, 0  ),
                "warm":   (255, 160, 60 ),
                "off":    (0,   0,   0  ),
            }
            base = palette.get(mode, (0, 0, 0))
            colors = [apply_br(*base, final_br)] * NUM_LEDS

        led_colors = colors
        time.sleep(0.03)   # ~30 fps


STATIC_DIR = os.path.join(os.path.dirname(__file__), "web")


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass   # quiet console

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_ok(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def send_static(self, rel_path):
        rel = rel_path.lstrip("/")
        if not rel:
            rel = "index.html"
        file_path = os.path.normpath(os.path.join(STATIC_DIR, rel))

        if not file_path.startswith(STATIC_DIR):
            self.send_error(403)
            return
        if not os.path.isfile(file_path):
            self.send_error(404)
            return

        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path

        if path == "/api/sensor":
            with state_lock:
                self.send_json({"lux": state["perc_val"], "temp": state["temp_val"]})

        elif path == "/api/state":
            with state_lock:
                s = dict(state)
            self.send_json({
                "lux":     s["perc_val"],
                "temp":    s["temp_val"],
                "mode":    s["mode"],
                "auto":    s["auto_light"],
                "br":      int(s["global_br"] * 100),
                "effects": {
                    "wave":    "wave"    in s["lightshow_active"],
                    "pulse":   "pulse"   in s["lightshow_active"],
                    "strobe":  "strobe"  in s["lightshow_active"],
                    "rainbow": "rainbow" in s["lightshow_active"],
                }
            })

        elif path == "/api/leds":
            colors = led_colors[:]   # snapshot
            self.send_json({"colors": colors})

        elif path.startswith("/set_global"):
            try:
                br = int(path.split("br=")[1]) / 100.0
                with state_lock:
                    state["global_br"] = br
            except Exception:
                pass
            self.send_ok()

        elif "/lightshow/" in path and "/toggle" in path:
            try:
                effect = path.split("/lightshow/")[1].split("/toggle")[0]
                now_ms = int(time.time() * 1000)
                with state_lock:
                    if now_ms - state["last_trigger"] > 100:
                        if effect in state["lightshow_active"]:
                            del state["lightshow_active"][effect]
                            state["lightshow_start"].pop(effect, None)
                        else:
                            state["lightshow_active"][effect] = True
                            state["lightshow_start"][effect]  = now_ms
                        state["last_trigger"] = now_ms
            except Exception:
                pass
            self.send_ok()

        elif path == "/toggle/auto":
            with state_lock:
                state["auto_light"] = not state["auto_light"]
            self.send_ok()

        elif path.startswith("/mode/"):
            try:
                m = path.split("/mode/")[1].split("?")[0].rstrip()
                with state_lock:
                    state["mode"] = m
                    state["lightshow_active"].clear()
                    state["lightshow_start"].clear()
            except Exception:
                pass
            self.send_ok()

        else:
            path_no_query = path.split("?", 1)[0]
            if path_no_query == "/":
                path_no_query = "/index.html"
            self.send_static(path_no_query)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    PORT = 8080

    threading.Thread(target=sensor_thread, daemon=True).start()
    threading.Thread(target=render_thread, daemon=True).start()

    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"\n  LED Controller Simulator")
    print(f"  {'─' * 36}")
    print(f"  Open in browser: {url}")
    print(f"  Stop:            Ctrl+C\n")

    try:
        # Try to auto-open the browser
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Simulator gestopt.")
