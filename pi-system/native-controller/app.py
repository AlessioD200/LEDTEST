#!/usr/bin/env python3
"""Native Raspberry Pi touchscreen controller for LED backend."""

import json
import os
import threading
import tkinter as tk
from tkinter import ttk
from urllib import error, request


BACKEND_URL = os.environ.get("LED_BACKEND_URL", "http://127.0.0.1:3001")
POLL_MS = 2000

MODES = ["white", "warm", "red", "green", "blue", "purple", "cyan", "yellow", "off"]
EFFECTS = ["none", "wave", "pulse", "strobe", "rainbow"]


class ControllerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LED Touch Controller")
        self.root.configure(bg="#111827")
        self.root.attributes("-fullscreen", True)

        self.state = {}
        self.busy = False

        self.status_var = tk.StringVar(value="Connecting...")
        self.mode_var = tk.StringVar(value="white")
        self.effect_var = tk.StringVar(value="none")
        self.brightness_var = tk.IntVar(value=50)
        self.pause_var = tk.IntVar(value=15)

        self.build_ui()
        self.fetch_state_async()
        self.root.after(POLL_MS, self.poll_state)

    def build_ui(self):
        top = tk.Frame(self.root, bg="#1f2937", pady=10)
        top.pack(fill="x")

        title = tk.Label(
            top,
            text="LED Controller",
            fg="#f9fafb",
            bg="#1f2937",
            font=("Helvetica", 24, "bold"),
        )
        title.pack(side="left", padx=20)

        status = tk.Label(
            top,
            textvariable=self.status_var,
            fg="#93c5fd",
            bg="#1f2937",
            font=("Helvetica", 14, "bold"),
        )
        status.pack(side="right", padx=20)

        body = tk.Frame(self.root, bg="#111827")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        power_row = tk.Frame(body, bg="#111827")
        power_row.pack(fill="x", pady=(0, 16))

        self.make_button(power_row, "Power ON", "#16a34a", lambda: self.send_command({"power": True})).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self.make_button(power_row, "Power OFF", "#dc2626", lambda: self.send_command({"power": False})).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        mode_frame = tk.LabelFrame(
            body,
            text="Mode",
            bg="#111827",
            fg="#f9fafb",
            font=("Helvetica", 14, "bold"),
            bd=2,
            padx=10,
            pady=10,
        )
        mode_frame.pack(fill="x", pady=(0, 16))

        for idx, mode in enumerate(MODES):
            btn = self.make_button(
                mode_frame,
                mode.upper(),
                "#2563eb",
                lambda m=mode: self.send_command({"mode": m, "power": m != "off"}),
                height=2,
            )
            btn.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=6, pady=6)

        for i in range(3):
            mode_frame.grid_columnconfigure(i, weight=1)

        mid = tk.Frame(body, bg="#111827")
        mid.pack(fill="x", pady=(0, 16))

        bright_frame = tk.LabelFrame(
            mid,
            text="Brightness",
            bg="#111827",
            fg="#f9fafb",
            font=("Helvetica", 14, "bold"),
            bd=2,
            padx=10,
            pady=10,
        )
        bright_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.brightness_label = tk.Label(
            bright_frame,
            text="50%",
            bg="#111827",
            fg="#93c5fd",
            font=("Helvetica", 18, "bold"),
        )
        self.brightness_label.pack(pady=(0, 6))

        self.slider = tk.Scale(
            bright_frame,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.brightness_var,
            bg="#111827",
            fg="#f9fafb",
            troughcolor="#374151",
            highlightthickness=0,
            command=self.on_brightness_change,
            font=("Helvetica", 12),
        )
        self.slider.pack(fill="x")
        self.slider.bind("<ButtonRelease-1>", self.on_brightness_commit)

        effect_frame = tk.LabelFrame(
            mid,
            text="Effect",
            bg="#111827",
            fg="#f9fafb",
            font=("Helvetica", 14, "bold"),
            bd=2,
            padx=10,
            pady=10,
        )
        effect_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.effect_menu = ttk.Combobox(
            effect_frame,
            state="readonly",
            values=EFFECTS,
            textvariable=self.effect_var,
            font=("Helvetica", 14),
        )
        self.effect_menu.pack(fill="x", pady=(8, 10))

        self.make_button(
            effect_frame, "Apply Effect", "#7c3aed", self.apply_effect
        ).pack(fill="x")

        sched = tk.LabelFrame(
            body,
            text="Scheduler",
            bg="#111827",
            fg="#f9fafb",
            font=("Helvetica", 14, "bold"),
            bd=2,
            padx=10,
            pady=10,
        )
        sched.pack(fill="x")

        sched_row = tk.Frame(sched, bg="#111827")
        sched_row.pack(fill="x")

        tk.Label(
            sched_row,
            text="Pause (min)",
            bg="#111827",
            fg="#f9fafb",
            font=("Helvetica", 12, "bold"),
        ).pack(side="left", padx=(0, 8))

        tk.Entry(
            sched_row,
            textvariable=self.pause_var,
            width=6,
            font=("Helvetica", 14),
            justify="center",
        ).pack(side="left", padx=(0, 12))

        self.make_button(
            sched_row,
            "Save Pause",
            "#2563eb",
            self.save_scheduler,
            width=14,
        ).pack(side="left", padx=6)

        self.make_button(
            sched_row,
            "Start",
            "#16a34a",
            lambda: self.simple_post("/api/scheduler/start", {}),
            width=10,
        ).pack(side="left", padx=6)

        self.make_button(
            sched_row,
            "Stop",
            "#dc2626",
            lambda: self.simple_post("/api/scheduler/stop", {}),
            width=10,
        ).pack(side="left", padx=6)

        footer = tk.Frame(self.root, bg="#1f2937", pady=8)
        footer.pack(fill="x")

        self.make_button(
            footer,
            "Refresh",
            "#334155",
            self.fetch_state_async,
            width=10,
        ).pack(side="left", padx=12)

        self.make_button(
            footer,
            "Exit Fullscreen",
            "#334155",
            self.exit_fullscreen,
            width=14,
        ).pack(side="right", padx=12)

    def make_button(self, parent, text, color, cmd, width=18, height=2):
        return tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=color,
            fg="#ffffff",
            activebackground=color,
            activeforeground="#ffffff",
            bd=0,
            relief="flat",
            font=("Helvetica", 13, "bold"),
            padx=10,
            pady=8,
            width=width,
            height=height,
        )

    def exit_fullscreen(self):
        self.root.attributes("-fullscreen", False)

    def poll_state(self):
        self.fetch_state_async()
        self.root.after(POLL_MS, self.poll_state)

    def on_brightness_change(self, _value):
        self.brightness_label.config(text=f"{self.brightness_var.get()}%")

    def on_brightness_commit(self, _event):
        self.send_command({"brightness": int(self.brightness_var.get())})

    def apply_effect(self):
        self.send_command({"effect": self.effect_var.get()})

    def save_scheduler(self):
        pause = max(1, int(self.pause_var.get() or 15))
        scheduler = (self.state.get("scheduler") or {}).copy()
        scheduler["pauseDurationMin"] = pause
        self.simple_post("/api/scheduler", {
            "enabled": scheduler.get("enabled", False),
            "pauseDurationMin": pause,
            "lessons": scheduler.get("lessons", []),
            "breaks": scheduler.get("breaks", []),
        })

    def simple_post(self, path, payload):
        self.busy = True

        def worker():
            ok = self.http_post(path, payload)
            self.root.after(0, lambda: self.on_post_done(ok))

        threading.Thread(target=worker, daemon=True).start()

    def send_command(self, patch):
        self.simple_post("/api/command", patch)

    def on_post_done(self, ok):
        self.busy = False
        if ok:
            self.status_var.set("Connected")
            self.fetch_state_async()
        else:
            self.status_var.set("Command failed")

    def fetch_state_async(self):
        if self.busy:
            return

        def worker():
            state = self.http_get_json("/api/state")
            self.root.after(0, lambda: self.on_state(state))

        threading.Thread(target=worker, daemon=True).start()

    def on_state(self, state):
        if not state:
            self.status_var.set("Backend offline")
            return

        self.state = state
        self.status_var.set("Connected")
        desired = state.get("desired", {})
        scheduler = state.get("scheduler", {})

        self.mode_var.set(desired.get("mode", "white"))
        self.effect_var.set(desired.get("effect", "none"))

        br = int(desired.get("brightness", 50))
        self.brightness_var.set(br)
        self.brightness_label.config(text=f"{br}%")

        pause = int(scheduler.get("pauseDurationMin", 15))
        self.pause_var.set(pause)

    def http_get_json(self, path):
        url = f"{BACKEND_URL}{path}"
        try:
            with request.urlopen(url, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError):
            return None

    def http_post(self, path, payload):
        url = f"{BACKEND_URL}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=4):
                return True
        except (error.URLError, error.HTTPError, TimeoutError):
            return False


def main():
    root = tk.Tk()
    app = ControllerApp(root)
    root.bind("<Escape>", lambda _e: app.exit_fullscreen())
    root.mainloop()


if __name__ == "__main__":
    main()
