#!/usr/bin/env python3
"""Native Raspberry Pi touchscreen LED controller (web-like layout)."""

import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import ttk
from urllib import error, request

BACKEND_URL = os.environ.get("LED_BACKEND_URL", "http://127.0.0.1:3001")
POLL_MS = 1200
ANIM_MS = 33

MODES = ["white", "warm", "red", "green", "blue", "purple", "cyan", "yellow", "off"]
EFFECTS = ["none", "wave", "pulse", "strobe", "rainbow"]

RED = "#d71920"
WHITE = "#ffffff"
BG = "#f6f7fb"
CARD = "#ffffff"
TEXT = "#1b1f23"
MUTED = "#666b73"


class ControllerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("LED Dashboard")
        self.root.configure(bg=BG)
        self.root.attributes("-fullscreen", True)
        self.root.option_add("*Font", "Helvetica 10")

        self.state = {}
        self.busy = False
        self.nav_buttons = {}
        self.pages = {}
        self.mode_buttons = {}
        self.repo_root = Path(__file__).resolve().parents[2]

        self.temp_history = deque(maxlen=90)
        self.lux_history = deque(maxlen=90)

        self.touch_scroll_active = False
        self.touch_scroll_last_y = 0
        self.fetch_in_flight = False

        self.current_led_color = {"r": 255, "g": 255, "b": 255}
        self.current_led_brightness = 50
        self.current_led_effect = "none"
        self.current_led_power = True

        self.manual_timer_remaining_s = 0
        self.manual_timer_job = None

        self.lesson_rows = []
        self.break_rows = []

        self.status_var = tk.StringVar(value="Verbinden...")
        self.online_var = tk.StringVar(value="Offline")
        self.temp_var = tk.StringVar(value="--")
        self.lux_var = tk.StringVar(value="--")
        self.mode_live_var = tk.StringVar(value="--")
        self.brightness_live_var = tk.StringVar(value="--")
        self.info_current_version_var = tk.StringVar(value="Laden...")
        self.info_remote_version_var = tk.StringVar(value="Onbekend")
        self.info_update_status_var = tk.StringVar(value="Nog niet gecontroleerd")

        self.mode_var = tk.StringVar(value="white")
        self.effect_var = tk.StringVar(value="none")
        self.brightness_var = tk.IntVar(value=50)

        self.r_var = tk.IntVar(value=255)
        self.g_var = tk.IntVar(value=255)
        self.b_var = tk.IntVar(value=255)

        self.auto_lux_var = tk.IntVar(value=0)
        self.lux_threshold_var = tk.IntVar(value=300)
        self.lux_threshold_label_var = tk.StringVar(value="300 lux")

        self.timer_enabled_var = tk.IntVar(value=0)
        self.timer_on_var = tk.StringVar(value="07:00")
        self.timer_off_var = tk.StringVar(value="22:00")
        self.manual_timer_value_var = tk.IntVar(value=10)
        self.manual_timer_unit_var = tk.StringVar(value="minutes")
        self.manual_timer_status_var = tk.StringVar(value="Niet actief")

        self.automation_enabled_var = tk.IntVar(value=0)
        self.pause_var = tk.IntVar(value=15)

        self.motion_enabled_var = tk.IntVar(value=0)
        self.motion_timeout_var = tk.IntVar(value=60)
        self.dim_enabled_var = tk.IntVar(value=0)
        self.dim_min_var = tk.IntVar(value=10)
        self.ct_enabled_var = tk.IntVar(value=0)

        self.configure_styles()
        self.build_ui()
        self.show_page("Status")
        self.root.after(250, self.enforce_fullscreen)
        self.root.after(1200, self.enforce_fullscreen)
        self.fetch_state_async()
        self.root.after(POLL_MS, self.poll_state)
        self.root.after(ANIM_MS, self.animation_tick)

    def configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT)

    def build_ui(self):
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(shell, width=220, bg=RED)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.content = tk.Frame(shell, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.content_canvas = tk.Canvas(self.content, bg=BG, highlightthickness=0)
        self.content_canvas.pack(fill="both", expand=True)

        self.content_inner = tk.Frame(self.content_canvas, bg=BG)
        self.content_window = self.content_canvas.create_window((0, 0), window=self.content_inner, anchor="nw")

        self.content_inner.bind("<Configure>", self.on_content_configure)
        self.content_canvas.bind("<Configure>", self.on_canvas_configure)

        self.content_canvas.bind("<ButtonPress-1>", self.on_touch_start)
        self.content_canvas.bind("<B1-Motion>", self.on_touch_drag)
        self.content_canvas.bind("<ButtonRelease-1>", self.on_touch_end)
        self.content_inner.bind("<ButtonPress-1>", self.on_touch_start)
        self.content_inner.bind("<B1-Motion>", self.on_touch_drag)
        self.content_inner.bind("<ButtonRelease-1>", self.on_touch_end)

        self.root.bind_all("<MouseWheel>", self.on_mousewheel)
        self.root.bind_all("<Button-4>", self.on_mousewheel_linux)
        self.root.bind_all("<Button-5>", self.on_mousewheel_linux)

        self.build_sidebar()
        self.build_pages()

    def build_sidebar(self):
        tk.Label(
            self.sidebar,
            text="LED Dashboard",
            bg=RED,
            fg=WHITE,
            font=("Helvetica", 18, "bold"),
        ).pack(anchor="w", padx=20, pady=(20, 4))

        tk.Label(
            self.sidebar,
            textvariable=self.status_var,
            bg=RED,
            fg=WHITE,
            font=("Helvetica", 11, "bold"),
        ).pack(anchor="w", padx=20, pady=(0, 16))

        for name in ["Status", "Kleur & Modus", "Automatisatie"]:
            btn = tk.Button(
                self.sidebar,
                text=name,
                command=lambda n=name: self.show_page(n),
                bg=RED,
                fg=WHITE,
                activebackground=WHITE,
                activeforeground=RED,
                relief="flat",
                bd=0,
                anchor="w",
                font=("Helvetica", 12, "bold"),
                padx=20,
                pady=10,
            )
            btn.pack(fill="x")
            self.nav_buttons[name] = btn

        info_btn = tk.Button(
            self.sidebar,
            text="Info & Updates",
            command=lambda: self.show_page("Info & Updates"),
            bg=RED,
            fg=WHITE,
            activebackground=WHITE,
            activeforeground=RED,
            relief="flat",
            bd=0,
            anchor="w",
            font=("Helvetica", 12, "bold"),
            padx=20,
            pady=10,
        )
        info_btn.pack(fill="x")
        self.nav_buttons["Info & Updates"] = info_btn

        tk.Frame(self.sidebar, bg=WHITE, height=1).pack(fill="x", padx=16, pady=16)

        self.sidebar_button("Power ON", "#1f9d55", lambda: self.send_command({"power": True}))
        self.sidebar_button("Power OFF", "#b00020", lambda: self.send_command({"power": False}))
        self.sidebar_button("LED status opvragen", "#2f3640", self.fetch_state_async)
        self.sidebar_button("Scroll omhoog", "#7a0f14", lambda: self.content_canvas.yview_scroll(-5, "units"))
        self.sidebar_button("Scroll omlaag", "#7a0f14", lambda: self.content_canvas.yview_scroll(5, "units"))
        self.sidebar_button("Exit fullscreen", "#2f3640", self.exit_fullscreen)

    def sidebar_button(self, text, color, command):
        tk.Button(
            self.sidebar,
            text=text,
            command=command,
            bg=color,
            fg=WHITE,
            activebackground=color,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            font=("Helvetica", 10, "bold"),
            padx=10,
            pady=8,
        ).pack(fill="x", padx=20, pady=5)

    def build_pages(self):
        self.pages["Status"] = self.build_status_page()
        self.pages["Kleur & Modus"] = self.build_color_page()
        self.pages["Automatisatie"] = self.build_automation_page()
        self.pages["Info & Updates"] = self.build_info_page()

    def page_title(self, page, title, subtitle=""):
        tk.Label(page, text=title, bg=BG, fg=TEXT, font=("Helvetica", 20, "bold")).pack(anchor="w", padx=20, pady=(16, 2))
        if subtitle:
            tk.Label(page, text=subtitle, bg=BG, fg=MUTED, font=("Helvetica", 10)).pack(anchor="w", padx=20, pady=(0, 8))

    def card(self, parent, title):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", padx=16, pady=8)
        card = tk.Frame(wrap, bg=CARD, relief="solid", bd=1)
        card.pack(fill="x")
        tk.Label(card, text=title, bg=CARD, fg=RED, font=("Helvetica", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        return card

    def build_status_page(self):
        page = tk.Frame(self.content_inner, bg=BG)
        self.page_title(page, "Status", "Realtime simulator gegevens")

        status_card = self.card(page, "Overzicht")
        grid = tk.Frame(status_card, bg=CARD)
        grid.pack(fill="x", padx=12, pady=(4, 12))

        self.status_tile(grid, "Verbinding", self.online_var, 0, 0)
        self.status_tile(grid, "Temperatuur", self.temp_var, 0, 1)
        self.status_tile(grid, "Lichtsterkte", self.lux_var, 0, 2)
        self.status_tile(grid, "Modus", self.mode_live_var, 1, 0)
        self.status_tile(grid, "Helderheid", self.brightness_live_var, 1, 1)

        for col in range(3):
            grid.grid_columnconfigure(col, weight=1)

        chart_card = self.card(page, "Grafieken")
        self.graph_canvas = tk.Canvas(chart_card, bg="#fcfcfd", height=230, highlightthickness=0)
        self.graph_canvas.pack(fill="x", padx=12, pady=(8, 12))

        led_card = self.card(page, "LED Preview")
        self.led_preview_canvas = tk.Canvas(led_card, bg="#101114", height=60, highlightthickness=0)
        self.led_preview_canvas.pack(fill="x", padx=12, pady=(8, 12))

        return page

    def status_tile(self, parent, label, value_var, row, col):
        tile = tk.Frame(parent, bg="#f4f5f8")
        tile.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
        tk.Label(tile, text=label, bg="#f4f5f8", fg=MUTED, font=("Helvetica", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(tile, textvariable=value_var, bg="#f4f5f8", fg=TEXT, font=("Helvetica", 13, "bold")).pack(anchor="w", padx=10, pady=(0, 10))

    def build_color_page(self):
        page = tk.Frame(self.content_inner, bg=BG)
        self.page_title(page, "Kleur & Modus", "Kies mode, kleur, effect en helderheid")

        mode_card = self.card(page, "Modus")
        mode_grid = tk.Frame(mode_card, bg=CARD)
        mode_grid.pack(fill="x", padx=12, pady=(6, 12))

        for idx, mode in enumerate(MODES):
            btn = tk.Button(
                mode_grid,
                text=mode.upper(),
                command=lambda m=mode: self.send_command({"mode": m, "power": m != "off"}),
                bg="#eff0f3",
                fg=TEXT,
                activebackground=RED,
                activeforeground=WHITE,
                relief="flat",
                bd=0,
                font=("Helvetica", 12, "bold"),
                padx=10,
                pady=12,
            )
            btn.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=5, pady=5)
            self.mode_buttons[mode] = btn

        for i in range(3):
            mode_grid.grid_columnconfigure(i, weight=1)

        settings_row = tk.Frame(page, bg=BG)
        settings_row.pack(fill="x", padx=8)

        bright_card = self.card(settings_row, "Helderheid")
        bright_card.pack(side="left", fill="both", expand=True, padx=(8, 4))

        self.brightness_label = tk.Label(bright_card, text="50%", bg=CARD, fg=RED, font=("Helvetica", 22, "bold"))
        self.brightness_label.pack(pady=(4, 6))

        bright_scale = tk.Scale(
            bright_card,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.brightness_var,
            bg=CARD,
            fg=TEXT,
            troughcolor="#e7e8ec",
            highlightthickness=0,
            command=self.on_brightness_change,
            length=340,
        )
        bright_scale.pack(fill="x", padx=12, pady=(0, 10))
        bright_scale.bind("<ButtonRelease-1>", self.on_brightness_commit)

        effect_card = self.card(settings_row, "Effect")
        effect_card.pack(side="left", fill="both", expand=True, padx=(4, 8))

        self.effect_menu = ttk.Combobox(effect_card, state="readonly", values=EFFECTS, textvariable=self.effect_var, font=("Helvetica", 12))
        self.effect_menu.pack(fill="x", padx=12, pady=(8, 8))
        tk.Button(effect_card, text="Toepassen", command=self.apply_effect, bg=RED, fg=WHITE, relief="flat", bd=0, font=("Helvetica", 12, "bold"), padx=10, pady=10).pack(fill="x", padx=12, pady=(0, 10))

        rgb_card = self.card(page, "Aangepaste kleur")
        rgb_body = tk.Frame(rgb_card, bg=CARD)
        rgb_body.pack(fill="x", padx=12, pady=(8, 12))

        self.rgb_slider(rgb_body, "R", self.r_var).pack(fill="x", pady=3)
        self.rgb_slider(rgb_body, "G", self.g_var).pack(fill="x", pady=3)
        self.rgb_slider(rgb_body, "B", self.b_var).pack(fill="x", pady=3)
        tk.Button(rgb_body, text="Apply RGB", command=self.apply_rgb, bg=RED, fg=WHITE, relief="flat", bd=0, font=("Helvetica", 12, "bold"), padx=10, pady=10).pack(anchor="e", pady=(6, 0))

        return page

    def rgb_slider(self, parent, name, var):
        row = tk.Frame(parent, bg=CARD)
        tk.Label(row, text=name, bg=CARD, fg=TEXT, width=3, font=("Helvetica", 11, "bold")).pack(side="left")
        tk.Scale(row, from_=0, to=255, orient="horizontal", variable=var, bg=CARD, fg=TEXT, troughcolor="#e7e8ec", highlightthickness=0, length=360).pack(side="left", fill="x", expand=True)
        return row

    def build_automation_page(self):
        page = tk.Frame(self.content_inner, bg=BG)
        self.page_title(page, "Automatisatie", "Auto-Lux, timer en lesrooster")

        auto_lux_card = self.card(page, "Auto-Lux")
        auto_lux_row = tk.Frame(auto_lux_card, bg=CARD)
        auto_lux_row.pack(fill="x", padx=12, pady=(8, 12))

        tk.Label(auto_lux_row, text="Auto-Lux actief", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).pack(side="left")
        self.toggle_slider(auto_lux_row, self.auto_lux_var, self.toggle_auto_lux).pack(side="left", padx=(8, 12))
        tk.Scale(auto_lux_row, from_=0, to=1000, orient="horizontal", variable=self.lux_threshold_var, bg=CARD, fg=TEXT, troughcolor="#e7e8ec", highlightthickness=0, length=200, command=lambda v: self.lux_threshold_label_var.set(f"{int(float(v))} lux")).pack(side="left", padx=8)
        tk.Label(auto_lux_row, textvariable=self.lux_threshold_label_var, bg=CARD, fg=MUTED, font=("Helvetica", 11, "bold")).pack(side="left")

        timer_card = self.card(page, "Timer")
        timer_top = tk.Frame(timer_card, bg=CARD)
        timer_top.pack(fill="x", padx=12, pady=(8, 6))
        tk.Label(timer_top, text="Timer actief", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).pack(side="left")
        self.toggle_slider(timer_top, self.timer_enabled_var, self.on_timer_toggle).pack(side="left", padx=(8, 10))
        tk.Label(timer_top, text="Aan", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).pack(side="left", padx=(16, 4))
        tk.Entry(timer_top, textvariable=self.timer_on_var, width=7, font=("Helvetica", 11)).pack(side="left")
        tk.Label(timer_top, text="Uit", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).pack(side="left", padx=(12, 4))
        tk.Entry(timer_top, textvariable=self.timer_off_var, width=7, font=("Helvetica", 11)).pack(side="left")

        manual = tk.Frame(timer_card, bg=CARD)
        manual.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(manual, text="Manuele timer", bg=CARD, fg=TEXT, font=("Helvetica", 12, "bold")).pack(side="left")
        tk.Entry(manual, textvariable=self.manual_timer_value_var, width=5, font=("Helvetica", 11)).pack(side="left", padx=(10, 6))
        ttk.Combobox(manual, textvariable=self.manual_timer_unit_var, state="readonly", width=9, values=["seconds", "minutes", "hours"]).pack(side="left", padx=(0, 8))
        tk.Button(manual, text="Start", command=self.start_manual_timer, bg="#1f9d55", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 11, "bold"), padx=10, pady=7).pack(side="left", padx=3)
        tk.Button(manual, text="Stop", command=self.stop_manual_timer, bg="#b00020", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 11, "bold"), padx=10, pady=7).pack(side="left", padx=3)
        tk.Label(manual, textvariable=self.manual_timer_status_var, bg=CARD, fg=MUTED, font=("Helvetica", 11, "bold")).pack(side="left", padx=10)

        roster_card = self.card(page, "Lesrooster")
        roster_actions = tk.Frame(roster_card, bg=CARD)
        roster_actions.pack(fill="x", padx=12, pady=(8, 8))

        tk.Label(roster_actions, text="Lesrooster actief", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).pack(side="left")
        self.toggle_slider(roster_actions, self.automation_enabled_var, self.toggle_automation).pack(side="left", padx=(8, 10))
        tk.Label(roster_actions, text="Pauze (min)", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).pack(side="left", padx=(12, 5))
        tk.Entry(roster_actions, textvariable=self.pause_var, width=5, font=("Helvetica", 11)).pack(side="left")
        tk.Button(roster_actions, text="Opslaan", command=self.save_scheduler, bg=RED, fg=WHITE, relief="flat", bd=0, font=("Helvetica", 11, "bold"), padx=10, pady=7).pack(side="left", padx=6)
        tk.Button(roster_actions, text="Start", command=lambda: self.simple_post("/api/scheduler/start", {}), bg="#1f9d55", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 11, "bold"), padx=10, pady=7).pack(side="left", padx=3)
        tk.Button(roster_actions, text="Stop", command=lambda: self.simple_post("/api/scheduler/stop", {}), bg="#b00020", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 11, "bold"), padx=10, pady=7).pack(side="left", padx=3)

        lists = tk.Frame(roster_card, bg=CARD)
        lists.pack(fill="x", padx=12, pady=(0, 12))
        left = tk.Frame(lists, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = tk.Frame(lists, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        tk.Label(left, text="Lessen", bg=CARD, fg=TEXT, font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.lesson_rows_wrap = tk.Frame(left, bg=CARD)
        self.lesson_rows_wrap.pack(fill="x", pady=(4, 6))
        tk.Button(left, text="Les toevoegen", command=self.add_lesson_row, bg="#ececf0", fg=TEXT, relief="flat", bd=0, font=("Helvetica", 10, "bold"), padx=8, pady=6).pack(anchor="w")

        tk.Label(right, text="Pauzes", bg=CARD, fg=TEXT, font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.break_rows_wrap = tk.Frame(right, bg=CARD)
        self.break_rows_wrap.pack(fill="x", pady=(4, 6))
        tk.Button(right, text="Pauze toevoegen", command=self.add_break_row, bg="#ececf0", fg=TEXT, relief="flat", bd=0, font=("Helvetica", 10, "bold"), padx=8, pady=6).pack(anchor="w")

        other_card = self.card(page, "Overige automatiseringen")
        other = tk.Frame(other_card, bg=CARD)
        other.pack(fill="x", padx=12, pady=(8, 12))
        tk.Label(other, text="Bewegingssensor", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.toggle_slider(other, self.motion_enabled_var).grid(row=0, column=1, padx=8)
        tk.Scale(other, from_=10, to=300, orient="horizontal", variable=self.motion_timeout_var, bg=CARD, troughcolor="#e7e8ec", highlightthickness=0, length=170).grid(row=0, column=2, padx=8)
        tk.Label(other, text="Dimschema", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.toggle_slider(other, self.dim_enabled_var).grid(row=1, column=1, padx=8, pady=(8, 0))
        tk.Scale(other, from_=1, to=50, orient="horizontal", variable=self.dim_min_var, bg=CARD, troughcolor="#e7e8ec", highlightthickness=0, length=170).grid(row=1, column=2, padx=8, pady=(8, 0))
        tk.Label(other, text="Kleurtemperatuur", bg=CARD, fg=TEXT, font=("Helvetica", 11, "bold")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.toggle_slider(other, self.ct_enabled_var).grid(row=2, column=1, padx=8, pady=(8, 0))

        return page

    def build_info_page(self):
        page = tk.Frame(self.content_inner, bg=BG)
        self.page_title(page, "Info & Updates", "Bekijk versie en werk de app direct bij")

        app_card = self.card(page, "App informatie")
        info = tk.Frame(app_card, bg=CARD)
        info.pack(fill="x", padx=12, pady=(8, 12))

        tk.Label(info, text="Backend URL", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        tk.Label(info, text=BACKEND_URL, bg=CARD, fg=TEXT, font=("Helvetica", 10)).grid(row=0, column=1, sticky="w", pady=(0, 6))

        tk.Label(info, text="Lokale versie", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(0, 6))
        tk.Label(info, textvariable=self.info_current_version_var, bg=CARD, fg=TEXT, font=("Helvetica", 10)).grid(row=1, column=1, sticky="w", pady=(0, 6))

        tk.Label(info, text="Remote versie", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 6))
        tk.Label(info, textvariable=self.info_remote_version_var, bg=CARD, fg=TEXT, font=("Helvetica", 10)).grid(row=2, column=1, sticky="w", pady=(0, 6))

        tk.Label(info, text="Status", bg=CARD, fg=MUTED, font=("Helvetica", 10, "bold")).grid(row=3, column=0, sticky="w")
        tk.Label(info, textvariable=self.info_update_status_var, bg=CARD, fg=TEXT, font=("Helvetica", 10, "bold")).grid(row=3, column=1, sticky="w")

        actions = tk.Frame(app_card, bg=CARD)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(actions, text="Check updates", command=self.check_updates_async, bg="#2f3640", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 10, "bold"), padx=12, pady=8).pack(side="left", padx=(0, 8))
        tk.Button(actions, text="Update app", command=self.apply_update_async, bg="#1f9d55", fg=WHITE, relief="flat", bd=0, font=("Helvetica", 10, "bold"), padx=12, pady=8).pack(side="left", padx=(0, 8))
        tk.Button(actions, text="Herstart app", command=self.restart_self, bg=RED, fg=WHITE, relief="flat", bd=0, font=("Helvetica", 10, "bold"), padx=12, pady=8).pack(side="left")

        help_card = self.card(page, "Snel hulp")
        tips = tk.Frame(help_card, bg=CARD)
        tips.pack(fill="x", padx=12, pady=(8, 12))
        tk.Label(
            tips,
            text="1) Druk op Check updates\n2) Als update beschikbaar is: druk op Update app\n3) App herstart daarna automatisch",
            justify="left",
            bg=CARD,
            fg=TEXT,
            font=("Helvetica", 10),
        ).pack(anchor="w")

        self.refresh_local_version()
        return page

    def run_git(self, *args):
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return completed.stdout.strip(), None
        except FileNotFoundError:
            return "", "git niet gevonden"
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or "git command mislukt").strip()
            return "", err

    def refresh_local_version(self):
        head, err = self.run_git("rev-parse", "--short", "HEAD")
        if err:
            self.info_current_version_var.set("Onbekend")
            self.info_update_status_var.set(f"Fout: {err}")
            return
        self.info_current_version_var.set(head)

    def check_updates_async(self):
        self.info_update_status_var.set("Controleren...")

        def worker():
            _, err = self.run_git("fetch", "--all", "--prune")
            if err:
                self.root.after(0, lambda: self.info_update_status_var.set(f"Fout: {err}"))
                return

            local_head, err_local = self.run_git("rev-parse", "--short", "HEAD")
            remote_head, err_remote = self.run_git("rev-parse", "--short", "@{u}")

            if err_local:
                self.root.after(0, lambda: self.info_update_status_var.set(f"Fout: {err_local}"))
                return
            if err_remote:
                self.root.after(0, lambda: self.info_update_status_var.set("Geen upstream branch ingesteld"))
                return

            def apply_ui():
                self.info_current_version_var.set(local_head)
                self.info_remote_version_var.set(remote_head)
                if local_head == remote_head:
                    self.info_update_status_var.set("Up-to-date")
                else:
                    self.info_update_status_var.set("Update beschikbaar")

            self.root.after(0, apply_ui)

        threading.Thread(target=worker, daemon=True).start()

    def apply_update_async(self):
        self.info_update_status_var.set("Updaten...")

        def worker():
            _, err = self.run_git("pull", "--ff-only")
            if err:
                self.root.after(0, lambda: self.info_update_status_var.set(f"Update mislukt: {err}"))
                return

            self.root.after(0, lambda: self.info_update_status_var.set("Update klaar, herstarten..."))
            self.root.after(900, self.restart_self)

        threading.Thread(target=worker, daemon=True).start()

    def restart_self(self):
        self.root.destroy()
        os.execv(sys.executable, [sys.executable, __file__])

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.content_canvas.yview_moveto(0)

        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.configure(bg=WHITE, fg=RED)
            else:
                btn.configure(bg=RED, fg=WHITE)

    def enforce_fullscreen(self):
        self.root.overrideredirect(False)
        self.root.attributes("-fullscreen", True)
        self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        self.root.lift()

    def exit_fullscreen(self):
        self.root.attributes("-fullscreen", False)

    def on_content_configure(self, _event):
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def on_canvas_configure(self, event):
        self.content_canvas.itemconfigure(self.content_window, width=event.width)

    def on_touch_start(self, event):
        if self.is_interactive_widget(event.widget):
            self.touch_scroll_active = False
            return
        self.touch_scroll_active = True
        self.touch_scroll_last_y = event.y_root

    def on_touch_drag(self, event):
        if not self.touch_scroll_active:
            return
        dy = event.y_root - self.touch_scroll_last_y
        self.touch_scroll_last_y = event.y_root
        self.scroll_by_pixels(-dy)

    def on_touch_end(self, _event):
        self.touch_scroll_active = False

    def on_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self.content_canvas.yview_scroll(delta * 3, "units")

    def on_mousewheel_linux(self, event):
        if event.num == 4:
            self.content_canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self.content_canvas.yview_scroll(3, "units")

    def is_interactive_widget(self, widget):
        interactive = (tk.Button, tk.Scale, tk.Entry, ttk.Combobox, tk.Checkbutton)
        return isinstance(widget, interactive)

    def scroll_by_pixels(self, pixels):
        bbox = self.content_canvas.bbox("all")
        if not bbox:
            return
        content_height = max(1, bbox[3] - bbox[1])
        view_height = max(1, self.content_canvas.winfo_height())
        max_scroll = max(1, content_height - view_height)

        y0, _ = self.content_canvas.yview()
        cur_px = y0 * max_scroll
        next_px = min(max(cur_px + pixels, 0), max_scroll)
        self.content_canvas.yview_moveto(next_px / max_scroll)

    def toggle_slider(self, parent, variable, command=None):
        slider = tk.Scale(
            parent,
            from_=0,
            to=1,
            resolution=1,
            orient="horizontal",
            showvalue=0,
            variable=variable,
            bg=CARD,
            fg=TEXT,
            troughcolor="#e7e8ec",
            highlightthickness=0,
            sliderlength=22,
            length=70,
        )
        if command is not None:
            slider.configure(command=lambda _v: command())
        return slider

    def poll_state(self):
        if self.timer_enabled_var.get():
            self.apply_clock_timer_once()
        self.fetch_state_async()
        self.root.after(POLL_MS, self.poll_state)

    def on_brightness_change(self, _value):
        self.brightness_label.config(text=f"{self.brightness_var.get()}%")

    def on_brightness_commit(self, _event):
        self.send_command({"brightness": int(self.brightness_var.get())})

    def apply_effect(self):
        self.send_command({"effect": self.effect_var.get()})

    def apply_rgb(self):
        self.send_command({"color": {"r": int(self.r_var.get()), "g": int(self.g_var.get()), "b": int(self.b_var.get())}})

    def toggle_auto_lux(self):
        self.send_command({"auto": bool(self.auto_lux_var.get())})

    def on_timer_toggle(self):
        if self.timer_enabled_var.get():
            self.apply_clock_timer_once()

    def apply_clock_timer_once(self):
        try:
            on_h, on_m = [int(x) for x in self.timer_on_var.get().split(":")]
            off_h, off_m = [int(x) for x in self.timer_off_var.get().split(":")]
        except Exception:
            return

        now = time.localtime()
        now_mins = now.tm_hour * 60 + now.tm_min
        on_mins = on_h * 60 + on_m
        off_mins = off_h * 60 + off_m

        if on_mins <= off_mins:
            should_on = on_mins <= now_mins < off_mins
        else:
            should_on = now_mins >= on_mins or now_mins < off_mins

        self.send_command({"power": bool(should_on)})

    def toggle_automation(self):
        self.save_scheduler()

    def start_manual_timer(self):
        value = max(1, int(self.manual_timer_value_var.get() or 1))
        factor = 1 if self.manual_timer_unit_var.get() == "seconds" else 60 if self.manual_timer_unit_var.get() == "minutes" else 3600
        self.manual_timer_remaining_s = value * factor
        self.stop_manual_timer(cancel_only=True)
        self.send_command({"power": True})
        self._tick_manual_timer()

    def stop_manual_timer(self, cancel_only=False):
        if self.manual_timer_job is not None:
            self.root.after_cancel(self.manual_timer_job)
            self.manual_timer_job = None
        if not cancel_only:
            self.manual_timer_status_var.set("Niet actief")

    def _tick_manual_timer(self):
        if self.manual_timer_remaining_s <= 0:
            self.manual_timer_status_var.set("Klaar - LED uit")
            self.send_command({"power": False})
            self.manual_timer_job = None
            return

        mins, secs = divmod(self.manual_timer_remaining_s, 60)
        self.manual_timer_status_var.set(f"Resterend {mins:02d}:{secs:02d}")
        self.manual_timer_remaining_s -= 1
        self.manual_timer_job = self.root.after(1000, self._tick_manual_timer)

    def add_lesson_row(self, lesson=None):
        lesson = lesson or {"name": f"Les {len(self.lesson_rows) + 1}", "start": "08:30", "end": "10:00"}
        row = tk.Frame(self.lesson_rows_wrap, bg=CARD)
        row.pack(fill="x", pady=3)
        name_var = tk.StringVar(value=lesson.get("name", "Les"))
        start_var = tk.StringVar(value=lesson.get("start", "08:30"))
        end_var = tk.StringVar(value=lesson.get("end", "10:00"))
        tk.Entry(row, textvariable=name_var, width=10, font=("Helvetica", 10)).pack(side="left", padx=(0, 4))
        tk.Entry(row, textvariable=start_var, width=6, font=("Helvetica", 10)).pack(side="left", padx=2)
        tk.Entry(row, textvariable=end_var, width=6, font=("Helvetica", 10)).pack(side="left", padx=2)
        tk.Button(row, text="x", command=lambda r=row: self.remove_lesson_row(r), bg="#ececf0", relief="flat", bd=0).pack(side="left", padx=3)
        self.lesson_rows.append((row, name_var, start_var, end_var))

    def remove_lesson_row(self, row_widget):
        self.lesson_rows = [r for r in self.lesson_rows if r[0] != row_widget]
        row_widget.destroy()

    def add_break_row(self, break_time="10:00"):
        row = tk.Frame(self.break_rows_wrap, bg=CARD)
        row.pack(fill="x", pady=3)
        time_var = tk.StringVar(value=break_time)
        tk.Entry(row, textvariable=time_var, width=8, font=("Helvetica", 10)).pack(side="left", padx=(0, 4))
        tk.Button(row, text="x", command=lambda r=row: self.remove_break_row(r), bg="#ececf0", relief="flat", bd=0).pack(side="left", padx=3)
        self.break_rows.append((row, time_var))

    def remove_break_row(self, row_widget):
        self.break_rows = [r for r in self.break_rows if r[0] != row_widget]
        row_widget.destroy()

    def read_lessons(self):
        out = []
        for _, name_var, start_var, end_var in self.lesson_rows:
            start = start_var.get().strip()
            end = end_var.get().strip()
            if start and end:
                out.append({"name": name_var.get().strip() or "Les", "start": start, "end": end})
        return out

    def read_breaks(self):
        out = []
        for _, t_var in self.break_rows:
            t = t_var.get().strip()
            if t:
                out.append(t)
        return out

    def populate_schedule_rows_if_empty(self, scheduler):
        if not self.lesson_rows:
            for lesson in scheduler.get("lessons", []):
                self.add_lesson_row(lesson)
        if not self.break_rows:
            for br in scheduler.get("breaks", []):
                self.add_break_row(br)

    def save_scheduler(self):
        self.simple_post(
            "/api/scheduler",
            {
                "enabled": bool(self.automation_enabled_var.get()),
                "pauseDurationMin": max(1, int(self.pause_var.get() or 15)),
                "lessons": self.read_lessons(),
                "breaks": self.read_breaks(),
            },
        )

    def send_command(self, payload):
        self.simple_post("/api/command", payload)

    def simple_post(self, path, payload):
        self.busy = True

        def worker():
            ok = self.http_post(path, payload)
            self.root.after(0, lambda: self.on_post_done(ok))

        threading.Thread(target=worker, daemon=True).start()

    def on_post_done(self, ok):
        self.busy = False
        self.status_var.set("Verbonden" if ok else "Commando mislukt")
        if ok:
            self.fetch_state_async()

    def fetch_state_async(self):
        if self.busy or self.fetch_in_flight:
            return

        self.fetch_in_flight = True

        def worker():
            state = self.http_get_json("/api/state")
            self.root.after(0, lambda: self.on_state(state))

        threading.Thread(target=worker, daemon=True).start()

    def on_state(self, state):
        self.fetch_in_flight = False
        if not state:
            self.status_var.set("Backend offline")
            return

        self.state = state
        self.status_var.set("Verbonden")

        desired = state.get("desired", {})
        scheduler = state.get("scheduler", {})
        device = state.get("device", {})
        telemetry = device.get("telemetry", {})
        applied = device.get("applied") if isinstance(device.get("applied"), dict) else {}
        live = applied if applied else desired

        mode = desired.get("mode", "white")
        effect = desired.get("effect", "none")
        brightness = int(desired.get("brightness", 50))
        color = desired.get("color") or {"r": 255, "g": 255, "b": 255}

        live_mode = live.get("mode", mode)
        live_effect = live.get("effect", effect)
        live_brightness = int(live.get("brightness", brightness))
        live_color = live.get("color") or color
        live_power = bool(live.get("power", desired.get("power", True)))

        self.current_led_color = {
            "r": int(live_color.get("r", 255)),
            "g": int(live_color.get("g", 255)),
            "b": int(live_color.get("b", 255)),
        }
        self.current_led_brightness = live_brightness
        self.current_led_effect = live_effect
        self.current_led_power = live_power

        self.mode_var.set(mode)
        self.effect_var.set(effect)
        self.brightness_var.set(brightness)
        self.brightness_label.config(text=f"{brightness}%")

        self.r_var.set(int(color.get("r", 255)))
        self.g_var.set(int(color.get("g", 255)))
        self.b_var.set(int(color.get("b", 255)))

        self.auto_lux_var.set(1 if desired.get("auto", False) else 0)
        self.pause_var.set(int(scheduler.get("pauseDurationMin", 15)))
        self.automation_enabled_var.set(1 if scheduler.get("enabled", False) else 0)
        self.populate_schedule_rows_if_empty(scheduler)

        online = bool(device.get("online", False))
        temp = telemetry.get("temperature")
        lux = telemetry.get("lux")

        self.online_var.set("Online" if online else "Offline")
        self.temp_var.set(f"{temp:.1f} C" if isinstance(temp, (int, float)) else "--")
        self.lux_var.set(f"{lux:.0f} lux" if isinstance(lux, (int, float)) else "--")
        self.mode_live_var.set(str(live_mode).upper())
        self.brightness_live_var.set(f"{live_brightness}%")

        for mode_name, btn in self.mode_buttons.items():
            if mode_name == mode:
                btn.configure(bg=RED, fg=WHITE)
            else:
                btn.configure(bg="#eff0f3", fg=TEXT)

        if isinstance(temp, (int, float)):
            self.temp_history.append(float(temp))
        if isinstance(lux, (int, float)):
            self.lux_history.append(float(lux))

        self.draw_graphs()

    def animation_tick(self):
        self.draw_led_preview(
            self.current_led_color,
            self.current_led_brightness,
            self.current_led_effect,
            self.current_led_power,
        )
        self.root.after(ANIM_MS, self.animation_tick)

    def draw_graphs(self):
        if not hasattr(self, "graph_canvas"):
            return

        c = self.graph_canvas
        c.delete("all")

        width = max(c.winfo_width(), 760)
        height = 230
        c.configure(height=height)

        c.create_rectangle(0, 0, width, height, fill="#fcfcfd", outline="")

        temp_now = self.temp_history[-1] if self.temp_history else None
        lux_now = self.lux_history[-1] if self.lux_history else None

        self.draw_gauge(c, 170, 92, 64, temp_now, 10, 45, RED, "Temp")
        self.draw_gauge(c, 390, 92, 64, lux_now, 0, 1000, "#0070c9", "Lux", value_fmt=lambda v: f"{v:.0f}")

        c.create_text(525, 14, anchor="nw", text="Trend", fill=MUTED, font=("Helvetica", 10, "bold"))
        self.draw_sparkline(c, list(self.temp_history), 520, 36, width - 20, 98, RED)
        self.draw_sparkline(c, list(self.lux_history), 520, 124, width - 20, 186, "#0070c9")
        c.create_text(520, 26, anchor="nw", text="Temperatuur", fill=RED, font=("Helvetica", 9, "bold"))
        c.create_text(520, 114, anchor="nw", text="Lichtsterkte", fill="#0070c9", font=("Helvetica", 9, "bold"))

    def draw_gauge(self, canvas, cx, cy, radius, value, vmin, vmax, color, label, value_fmt=None):
        start = 140
        span = 260
        box = (cx - radius, cy - radius, cx + radius, cy + radius)

        canvas.create_arc(*box, start=start, extent=span, style="arc", width=12, outline="#e8ebf1")
        if isinstance(value, (int, float)):
            ratio = max(0.0, min(1.0, (value - vmin) / max(1e-6, (vmax - vmin))))
            canvas.create_arc(*box, start=start, extent=span * ratio, style="arc", width=12, outline=color)
            a = math.radians(start + span * ratio)
            x = cx + (radius - 2) * math.cos(a)
            y = cy + (radius - 2) * math.sin(a)
            canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline="")
            text = value_fmt(value) if value_fmt else f"{value:.1f}"
        else:
            text = "--"

        canvas.create_text(cx, cy + 4, text=text, fill=TEXT, font=("Helvetica", 17, "bold"))
        canvas.create_text(cx, cy + 27, text=label, fill=MUTED, font=("Helvetica", 10, "bold"))

    def draw_sparkline(self, canvas, values, x0, y0, x1, y1, color):
        canvas.create_rectangle(x0, y0, x1, y1, fill="#f7f8fb", outline="#e4e7ee")
        if len(values) < 2:
            return

        vmin = min(values)
        vmax = max(values)
        if abs(vmax - vmin) < 1e-6:
            vmax = vmin + 1

        step_x = (x1 - x0 - 10) / max(1, len(values) - 1)
        points = []
        for i, v in enumerate(values):
            x = x0 + 5 + i * step_x
            ratio = (v - vmin) / (vmax - vmin)
            y = y1 - 5 - (y1 - y0 - 10) * ratio
            points.extend([x, y])

        canvas.create_line(*points, fill=color, width=2, smooth=True)
        canvas.create_text(x1 - 6, points[-1], anchor="e", text=f"{values[-1]:.1f}", fill=color, font=("Helvetica", 9, "bold"))

    def draw_led_preview(self, color, brightness, effect, power_on):
        if not hasattr(self, "led_preview_canvas"):
            return

        c = self.led_preview_canvas
        c.delete("all")

        width = max(c.winfo_width(), 760)
        h = 60
        c.configure(height=h)
        c.create_rectangle(0, 0, width, h, fill="#101114", outline="")

        leds = 28
        gap = 4
        led_w = (width - 20 - (leds - 1) * gap) / leds
        y0, y1 = 12, 48
        x = 10
        t = time.time()

        br = max(0.0, min(1.0, brightness / 100.0))
        r0 = int(color.get("r", 255))
        g0 = int(color.get("g", 255))
        b0 = int(color.get("b", 255))

        for i in range(leds):
            if not power_on:
                rr, gg, bb = 0, 0, 0
            elif effect == "rainbow":
                rr, gg, bb = self.hsv_to_rgb((t * 0.2 + i / leds) % 1.0, 0.9, br)
            else:
                intensity = 1.0
                if effect == "pulse":
                    intensity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 4))
                elif effect == "wave":
                    intensity = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(t * 4 + i * 0.35))
                elif effect == "strobe":
                    intensity = 1.0 if int(t * 7) % 2 == 0 else 0.1
                rr = int(r0 * br * intensity)
                gg = int(g0 * br * intensity)
                bb = int(b0 * br * intensity)

            c.create_oval(x, y0, x + led_w, y1, fill=f"#{rr:02x}{gg:02x}{bb:02x}", outline="")
            x += led_w + gap

    def hsv_to_rgb(self, h, s, v):
        i = int(h * 6)
        f = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        i %= 6
        if i == 0:
            r, g, b = v, t, p
        elif i == 1:
            r, g, b = q, v, p
        elif i == 2:
            r, g, b = p, v, t
        elif i == 3:
            r, g, b = p, q, v
        elif i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

    def http_get_json(self, path):
        url = f"{BACKEND_URL}{path}"
        try:
            with request.urlopen(url, timeout=1.8) as resp:
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
