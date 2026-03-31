#!/usr/bin/env python3
"""Kivy-based Raspberry Pi touchscreen LED controller."""

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib import error, request

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

BACKEND_URL = os.environ.get("LED_BACKEND_URL", "http://127.0.0.1:3001")
UPDATE_REPO_DIR = Path(os.environ.get("LED_UPDATE_REPO_DIR", "/home/ledvives/LEDTEST"))
UPDATE_BRANCH = os.environ.get("LED_UPDATE_BRANCH", "main")
REPO_APP_REL = Path("pi-system/native-controller/app_kivy.py")
REPO_SYNC_TARGETS = [
    (Path("pi-system/deploy/native-app/led-controller.desktop"), Path("/opt/led-pi/deploy/native-app/led-controller.desktop")),
    (Path("pi-system/deploy/native-app/install-native-controller.sh"), Path("/opt/led-pi/deploy/native-app/install-native-controller.sh")),
]
POLL_SECONDS = 1.2
ANIM_SECONDS = 1 / 30
KIOSK_ENFORCE_SECONDS = 2.0

MODES = ["white", "warm", "red", "green", "blue", "purple", "cyan", "yellow", "off"]
EFFECTS = ["none", "wave", "pulse", "strobe", "rainbow"]

RED = (0.84, 0.1, 0.13, 1)
GREEN = (0.12, 0.62, 0.33, 1)
BLUE = (0.0, 0.44, 0.79, 1)
BG = (0.965, 0.969, 0.984, 1)
CARD = (1, 1, 1, 1)
TEXT = (0.106, 0.122, 0.137, 1)
MUTED = (0.4, 0.42, 0.45, 1)
SOFT = (0.95, 0.95, 0.97, 1)
PRIMARY_DARK = (0.74, 0.08, 0.11, 1)


def tone(color, factor):
    red, green, blue = color[:3]
    alpha = color[3] if len(color) > 3 else 1
    return (clamp(red * factor, 0, 1), clamp(green * factor, 0, 1), clamp(blue * factor, 0, 1), alpha)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def hsv_to_rgb(hue, saturation, value):
    index = int(hue * 6)
    fraction = hue * 6 - index
    p = value * (1 - saturation)
    q = value * (1 - fraction * saturation)
    t = value * (1 - (1 - fraction) * saturation)
    index %= 6
    if index == 0:
        red, green, blue = value, t, p
    elif index == 1:
        red, green, blue = q, value, p
    elif index == 2:
        red, green, blue = p, value, t
    elif index == 3:
        red, green, blue = p, q, value
    elif index == 4:
        red, green, blue = t, p, value
    else:
        red, green, blue = value, p, q
    return int(red * 255), int(green * 255), int(blue * 255)


def draw_text(canvas, text, x, y, color, font_size, bold=False):
    label = CoreLabel(text=text, font_size=font_size, bold=bold, color=color)
    label.refresh()
    texture = label.texture
    Color(1, 1, 1, 1)
    Rectangle(texture=texture, pos=(x, y), size=texture.size)


class Card(BoxLayout):
    def __init__(self, title, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(12), padding=dp(16), size_hint_y=None, **kwargs)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*CARD)
            self._bg = RoundedRectangle(radius=[dp(18)])
            Color(0.9, 0.91, 0.94, 1)
            self._border = Line(rounded_rectangle=(0, 0, 0, 0, dp(18)), width=1)
        self.bind(pos=self._sync_canvas, size=self._sync_canvas)
        self.add_widget(AppLabel(text=title, color=RED, bold=True, font_size="18sp", size_hint_y=None, height=dp(28), halign="left", valign="middle"))

    def _sync_canvas(self, *_args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.rounded_rectangle = (*self.pos, *self.size, dp(18))


class GaugeWidget(Widget):
    def __init__(self, label, accent, minimum, maximum, suffix="", decimals=1, **kwargs):
        super().__init__(size_hint_y=None, height=dp(180), **kwargs)
        self.label_text = label
        self.accent = accent
        self.minimum = minimum
        self.maximum = maximum
        self.suffix = suffix
        self.decimals = decimals
        self.value = None
        self.bind(pos=self.redraw, size=self.redraw)

    def set_value(self, value):
        self.value = value
        self.redraw()

    def redraw(self, *_args):
        self.canvas.clear()
        cx = self.center_x
        cy = self.y + self.height * 0.53
        radius = min(self.width * 0.35, self.height * 0.34)
        start = 140
        span = 260

        with self.canvas:
            Color(0.91, 0.92, 0.95, 1)
            Line(circle=(cx, cy, radius, start, start + span), width=dp(10), cap="round")

            ratio = 0
            if isinstance(self.value, (int, float)):
                ratio = clamp((self.value - self.minimum) / max(1e-6, self.maximum - self.minimum), 0, 1)

            Color(*self.accent)
            Line(circle=(cx, cy, radius, start, start + span * ratio), width=dp(10), cap="round")

            angle = math.radians(start + span * ratio)
            dot_x = cx + radius * math.cos(angle)
            dot_y = cy + radius * math.sin(angle)
            Ellipse(pos=(dot_x - dp(5), dot_y - dp(5)), size=(dp(10), dp(10)))

            value_text = "--"
            if isinstance(self.value, (int, float)):
                value_text = f"{self.value:.{self.decimals}f}{self.suffix}"

            draw_text(self.canvas, self.label_text, cx - dp(44), cy - dp(48), MUTED, dp(15), True)
            draw_text(self.canvas, value_text, cx - dp(50), cy - dp(12), TEXT, dp(26), True)


class SparklineWidget(Widget):
    def __init__(self, accent, **kwargs):
        super().__init__(size_hint_y=None, height=dp(92), **kwargs)
        self.accent = accent
        self.values = []
        self.bind(pos=self.redraw, size=self.redraw)

    def set_values(self, values):
        self.values = values
        self.redraw()

    def redraw(self, *_args):
        self.canvas.clear()
        with self.canvas:
            Color(0.97, 0.973, 0.984, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(0.89, 0.91, 0.94, 1)
            Line(rounded_rectangle=(*self.pos, *self.size, dp(14)), width=1)

            if len(self.values) < 2:
                return

            minimum = min(self.values)
            maximum = max(self.values)
            flat_series = abs(maximum - minimum) < 1e-6

            pad_x = dp(8)
            pad_y = dp(10)
            usable_w = max(dp(20), self.width - pad_x * 2)
            usable_h = max(dp(20), self.height - pad_y * 2)
            points = []

            for index, value in enumerate(self.values):
                x = self.x + pad_x + usable_w * (index / max(1, len(self.values) - 1))
                if flat_series:
                    ratio = 0.5
                else:
                    ratio = (value - minimum) / (maximum - minimum)
                y = self.y + pad_y + usable_h * ratio
                points.extend([x, y])

            Color(*self.accent)
            Line(points=points, width=dp(2.2), cap="round", joint="round")


class AppLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(size=self._sync_text_box)
        self._sync_text_box()

    def _sync_text_box(self, *_args):
        self.text_size = (max(0, self.width - dp(2)), self.height)


class RoundButton(Button):
    def __init__(self, radius=14, border_color=(0.82, 0.85, 0.9, 1), **kwargs):
        bg_color = kwargs.get("background_color", SOFT)
        kwargs["background_normal"] = ""
        kwargs["background_down"] = ""
        kwargs["background_color"] = (0, 0, 0, 0)
        kwargs.setdefault("color", TEXT)
        kwargs.setdefault("bold", True)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.radius = dp(radius)
        self.base_color = bg_color
        self.border_color = border_color
        self.padding = [dp(10), dp(8)]
        with self.canvas.before:
            self._bg_color_instr = Color(*self.base_color)
            self._bg = RoundedRectangle(radius=[self.radius])
            self._border_color_instr = Color(*self.border_color)
            self._border = Line(rounded_rectangle=(0, 0, 0, 0, self.radius), width=1)
        self.bind(pos=self._redraw, size=self._redraw, state=self._redraw)
        self.bind(size=self._sync_text_box)
        self._sync_text_box()
        self._redraw()

    def _sync_text_box(self, *_args):
        self.text_size = (max(0, self.width - dp(20)), max(0, self.height - dp(8)))

    def _redraw(self, *_args):
        if self.state == "down":
            self._bg_color_instr.rgba = tone(self.base_color, 0.88)
        else:
            self._bg_color_instr.rgba = self.base_color
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._border.rounded_rectangle = (*self.pos, *self.size, self.radius)


class LedPreviewWidget(Widget):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(82), **kwargs)
        self.rgb = [255, 255, 255]
        self.brightness = 50
        self.effect = "none"
        self.power_on = True
        self.phase = 0.0
        self.bind(pos=self.redraw, size=self.redraw)

    def redraw(self, *_args):
        self.canvas.clear()
        led_count = 28
        gap = dp(4)

        with self.canvas:
            Color(0.06, 0.067, 0.078, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(16)])

            led_w = (self.width - dp(20) - gap * (led_count - 1)) / led_count
            led_h = self.height - dp(28)
            x = self.x + dp(10)
            y = self.y + dp(14)
            base_r, base_g, base_b = self.rgb
            brightness = clamp(self.brightness / 100.0, 0.0, 1.0)

            for index in range(led_count):
                if not self.power_on:
                    red = green = blue = 0
                elif self.effect == "rainbow":
                    red, green, blue = hsv_to_rgb((self.phase * 0.2 + index / led_count) % 1.0, 0.9, brightness)
                else:
                    intensity = 1.0
                    if self.effect == "pulse":
                        intensity = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(self.phase * 4))
                    elif self.effect == "wave":
                        intensity = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self.phase * 4 + index * 0.35))
                    elif self.effect == "strobe":
                        intensity = 1.0 if int(self.phase * 7) % 2 == 0 else 0.1
                    red = int(base_r * brightness * intensity)
                    green = int(base_g * brightness * intensity)
                    blue = int(base_b * brightness * intensity)

                Color(red / 255, green / 255, blue / 255, 1)
                RoundedRectangle(pos=(x, y), size=(led_w, led_h), radius=[dp(10)])
                x += led_w + gap


class Section(Screen):
    def __init__(self, name, **kwargs):
        super().__init__(name=name, **kwargs)
        scroll = ScrollView(bar_width=dp(6), scroll_type=["bars", "content"])
        self.content = BoxLayout(
            orientation="vertical",
            spacing=dp(16),
            padding=[dp(22), dp(18), dp(22), dp(28)],
            size_hint_y=None,
        )
        self.content.bind(minimum_height=self.content.setter("height"))
        scroll.add_widget(self.content)
        self.add_widget(scroll)


class LEDControllerApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = {}
        self.fetch_in_flight = False
        self.temp_history = deque(maxlen=90)
        self.lux_history = deque(maxlen=90)
        self.current_rgb = [255, 255, 255]
        self.current_brightness = 50
        self.current_effect = "none"
        self.current_power = True
        self.phase = 0.0
        self.manual_timer_remaining_s = 0
        self.manual_timer_event = None
        self.last_timer_power = None
        self.app_file = Path(__file__).resolve()
        self.repo_dir = UPDATE_REPO_DIR

    def build(self):
        Window.clearcolor = BG
        self.enforce_kiosk_window()

        root = BoxLayout(orientation="horizontal")

        self.sidebar = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(236), padding=[dp(16), dp(18), dp(16), dp(16)], spacing=dp(10))
        with self.sidebar.canvas.before:
            Color(*RED)
            self.sidebar_bg = RoundedRectangle(radius=[0])
        self.sidebar.bind(pos=self._update_sidebar, size=self._update_sidebar)

        title = AppLabel(text="LED Dashboard", color=(1, 1, 1, 1), bold=True, font_size="30sp", size_hint_y=None, height=dp(44), halign="left", valign="middle")
        self.status_label = AppLabel(text="Verbinden...", color=(1, 1, 1, 1), bold=True, font_size="16sp", size_hint_y=None, height=dp(26), halign="left", valign="middle")
        self.sidebar.add_widget(title)
        self.sidebar.add_widget(self.status_label)

        self.screen_manager = ScreenManager(transition=NoTransition())
        self.nav_buttons = {}
        for page in ["Status", "Kleur & Modus", "Automatisatie", "Info & Updates"]:
            self.sidebar.add_widget(self.make_nav_button(page))

        self.sidebar.add_widget(self.make_action_button("Power ON", GREEN, lambda *_: self.send_command({"power": True})))
        self.sidebar.add_widget(self.make_action_button("Power OFF", (0.69, 0.0, 0.13, 1), lambda *_: self.send_command({"power": False})))
        self.sidebar.add_widget(self.make_action_button("LED status opvragen", (0.19, 0.21, 0.25, 1), lambda *_: self.fetch_state_async()))
        self.sidebar.add_widget(self.make_action_button("Herlaad fullscreen", (0.19, 0.21, 0.25, 1), lambda *_: self.enforce_kiosk_window()))
        self.sidebar.add_widget(Widget())

        self.status_screen = self.build_status_screen()
        self.color_screen = self.build_color_screen()
        self.automation_screen = self.build_automation_screen()
        self.info_screen = self.build_info_screen()
        for screen in [self.status_screen, self.color_screen, self.automation_screen, self.info_screen]:
            self.screen_manager.add_widget(screen)

        root.add_widget(self.sidebar)
        root.add_widget(self.screen_manager)

        self.switch_screen("Status")
        Clock.schedule_interval(self.poll_state, POLL_SECONDS)
        Clock.schedule_interval(self.animation_tick, ANIM_SECONDS)
        Clock.schedule_interval(lambda _dt: self.enforce_kiosk_window(), KIOSK_ENFORCE_SECONDS)
        Clock.schedule_once(lambda _dt: self.fetch_state_async(), 0.2)
        return root

    def on_start(self):
        # Run once after window creation to keep the app in front in kiosk setups.
        self.enforce_kiosk_window()

    def enforce_kiosk_window(self):
        Window.borderless = True
        Window.fullscreen = "auto"
        if hasattr(Window, "always_on_top"):
            Window.always_on_top = True
        if hasattr(Window, "show_cursor"):
            Window.show_cursor = False
        if hasattr(Window, "raise_window"):
            Window.raise_window()

    def _update_sidebar(self, *_args):
        self.sidebar_bg.pos = self.sidebar.pos
        self.sidebar_bg.size = self.sidebar.size

    def make_nav_button(self, page):
        button = RoundButton(
            text=page,
            size_hint_y=None,
            height=dp(46),
            background_color=PRIMARY_DARK,
            border_color=(1, 1, 1, 0.25),
            color=(1, 1, 1, 1),
        )
        button.bind(on_release=lambda *_args, name=page: self.switch_screen(name))
        self.nav_buttons[page] = button
        return button

    def make_action_button(self, text, color, callback):
        button = RoundButton(text=text, size_hint_y=None, height=dp(42), background_color=color, border_color=(1, 1, 1, 0.15), color=(1, 1, 1, 1))
        button.bind(on_release=callback)
        return button

    def page_header(self, parent, title, subtitle):
        parent.add_widget(AppLabel(text=title, size_hint_y=None, height=dp(40), color=TEXT, bold=True, font_size="30sp", halign="left", valign="middle"))
        parent.add_widget(AppLabel(text=subtitle, size_hint_y=None, height=dp(24), color=MUTED, font_size="15sp", halign="left", valign="middle"))

    def make_stat_box(self, parent, title):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(5), size_hint_y=None, height=dp(92))
        with box.canvas.before:
            Color(*SOFT)
            box_bg = RoundedRectangle(radius=[dp(14)])
        box.bind(pos=lambda inst, *_: setattr(box_bg, "pos", inst.pos), size=lambda inst, *_: setattr(box_bg, "size", inst.size))
        box.add_widget(AppLabel(text=title, color=MUTED, bold=True, font_size="14sp", size_hint_y=None, height=dp(20), halign="left"))
        value = AppLabel(text="--", color=TEXT, bold=True, font_size="22sp", halign="left", valign="middle")
        box.add_widget(value)
        parent.add_widget(box)
        return value

    def build_status_screen(self):
        screen = Section(name="Status")
        self.page_header(screen.content, "Status", "Realtime device en simulator gegevens")

        overview = Card("Overzicht")
        grid = GridLayout(cols=3, spacing=dp(10), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        self.online_value = self.make_stat_box(grid, "Verbinding")
        self.temp_value = self.make_stat_box(grid, "Temperatuur")
        self.lux_value = self.make_stat_box(grid, "Lichtsterkte")
        self.mode_live_value = self.make_stat_box(grid, "Modus")
        self.brightness_live_value = self.make_stat_box(grid, "Helderheid")
        self.effect_live_value = self.make_stat_box(grid, "Effect")
        overview.add_widget(grid)
        screen.content.add_widget(overview)

        gauges = Card("Sensoren")
        gauge_row = GridLayout(cols=2, spacing=dp(12), size_hint_y=None, height=dp(190))
        self.temp_gauge = GaugeWidget(label="Temperatuur", accent=RED, minimum=10, maximum=45, suffix=" C", decimals=1)
        self.lux_gauge = GaugeWidget(label="Licht", accent=BLUE, minimum=0, maximum=1000, suffix=" lux", decimals=0)
        gauge_row.add_widget(self.temp_gauge)
        gauge_row.add_widget(self.lux_gauge)
        gauges.add_widget(gauge_row)
        screen.content.add_widget(gauges)

        trends = Card("Trends")
        trends.add_widget(Label(text="Temperatuur", size_hint_y=None, height=dp(22), color=RED, bold=True, halign="left", valign="middle"))
        self.temp_spark = SparklineWidget(accent=RED)
        trends.add_widget(self.temp_spark)
        trends.add_widget(Label(text="Lichtsterkte", size_hint_y=None, height=dp(22), color=BLUE, bold=True, halign="left", valign="middle"))
        self.lux_spark = SparklineWidget(accent=BLUE)
        trends.add_widget(self.lux_spark)
        screen.content.add_widget(trends)

        preview = Card("LED Preview")
        self.preview_widget = LedPreviewWidget()
        preview.add_widget(self.preview_widget)
        screen.content.add_widget(preview)
        return screen

    def build_color_screen(self):
        screen = Section(name="Kleur & Modus")
        self.page_header(screen.content, "Kleur & Modus", "Kies modus, helderheid, effect en RGB")

        mode_card = Card("Modus")
        mode_grid = GridLayout(cols=3, spacing=dp(10), size_hint_y=None)
        mode_grid.bind(minimum_height=mode_grid.setter("height"))
        self.mode_buttons = {}
        for mode in MODES:
            button = RoundButton(text=mode.upper(), size_hint_y=None, height=dp(52), background_color=SOFT, color=TEXT)
            button.bind(on_release=lambda _button, value=mode: self.send_command({"mode": value, "power": value != "off"}))
            self.mode_buttons[mode] = button
            mode_grid.add_widget(button)
        mode_card.add_widget(mode_grid)
        screen.content.add_widget(mode_card)

        brightness_card = Card("Helderheid")
        self.brightness_value_label = AppLabel(text="50%", color=RED, bold=True, font_size="34sp", size_hint_y=None, height=dp(42), halign="center")
        self.brightness_slider = Slider(min=0, max=100, value=50, step=1, size_hint_y=None, height=dp(44))
        self.brightness_slider.bind(value=self.on_brightness_change)
        brightness_apply = RoundButton(text="Helderheid toepassen", size_hint_y=None, height=dp(44), background_color=RED, border_color=(0.73, 0.1, 0.15, 1), color=(1, 1, 1, 1))
        brightness_apply.bind(on_release=lambda *_: self.send_command({"brightness": int(self.brightness_slider.value)}))
        brightness_card.add_widget(self.brightness_value_label)
        brightness_card.add_widget(self.brightness_slider)
        brightness_card.add_widget(brightness_apply)
        screen.content.add_widget(brightness_card)

        effect_card = Card("Effect")
        self.effect_spinner = Spinner(text="none", values=EFFECTS, size_hint_y=None, height=dp(44), background_normal="", background_color=SOFT, color=TEXT)
        effect_apply = RoundButton(text="Effect toepassen", size_hint_y=None, height=dp(44), background_color=RED, border_color=(0.73, 0.1, 0.15, 1), color=(1, 1, 1, 1))
        effect_apply.bind(on_release=lambda *_: self.send_command({"effect": self.effect_spinner.text}))
        effect_card.add_widget(self.effect_spinner)
        effect_card.add_widget(effect_apply)
        screen.content.add_widget(effect_card)

        rgb_card = Card("RGB kleur")
        self.rgb_sliders = {}
        self.rgb_labels = {}
        for channel, color in [("R", (0.9, 0.22, 0.21, 1)), ("G", (0.12, 0.56, 0.25, 1)), ("B", (0.1, 0.45, 0.9, 1))]:
            row = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None, height=dp(74))
            label = AppLabel(text=f"{channel}: 255", color=color, bold=True, size_hint_y=None, height=dp(20), halign="left")
            slider = Slider(min=0, max=255, value=255, step=1, size_hint_y=None, height=dp(40))
            slider.bind(value=lambda _slider, value, channel_name=channel, label_widget=label: setattr(label_widget, "text", f"{channel_name}: {int(value)}"))
            self.rgb_sliders[channel] = slider
            self.rgb_labels[channel] = label
            row.add_widget(label)
            row.add_widget(slider)
            rgb_card.add_widget(row)
        rgb_apply = RoundButton(text="RGB toepassen", size_hint_y=None, height=dp(44), background_color=RED, border_color=(0.73, 0.1, 0.15, 1), color=(1, 1, 1, 1))
        rgb_apply.bind(on_release=lambda *_: self.send_command({
            "color": {
                "r": int(self.rgb_sliders["R"].value),
                "g": int(self.rgb_sliders["G"].value),
                "b": int(self.rgb_sliders["B"].value),
            }
        }))
        rgb_card.add_widget(rgb_apply)
        screen.content.add_widget(rgb_card)
        return screen

    def build_automation_screen(self):
        screen = Section(name="Automatisatie")
        self.page_header(screen.content, "Automatisatie", "Auto-lux, timer, manuele timer en lesrooster")

        auto_card = Card("Auto-lux")
        auto_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(12))
        auto_row.add_widget(AppLabel(text="Actief", color=TEXT, bold=True))
        self.auto_lux_switch = Switch(active=False)
        self.auto_lux_switch.bind(active=lambda *_: self.send_command({"auto": bool(self.auto_lux_switch.active)}))
        auto_row.add_widget(self.auto_lux_switch)
        auto_card.add_widget(auto_row)
        threshold_row = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(74), spacing=dp(4))
        self.lux_threshold_label = AppLabel(text="Drempel: 300 lux", color=MUTED, bold=True, size_hint_y=None, height=dp(20), halign="left")
        self.lux_threshold_slider = Slider(min=0, max=1000, value=300, step=5, size_hint_y=None, height=dp(40))
        self.lux_threshold_slider.bind(value=lambda *_: setattr(self.lux_threshold_label, "text", f"Drempel: {int(self.lux_threshold_slider.value)} lux"))
        threshold_row.add_widget(self.lux_threshold_label)
        threshold_row.add_widget(self.lux_threshold_slider)
        auto_card.add_widget(threshold_row)
        screen.content.add_widget(auto_card)

        timer_card = Card("Timer")
        timer_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(12))
        timer_row.add_widget(AppLabel(text="Actief", color=TEXT, bold=True))
        self.timer_switch = Switch(active=False)
        self.timer_switch.bind(active=lambda *_: self.apply_clock_timer_once())
        timer_row.add_widget(self.timer_switch)
        timer_card.add_widget(timer_row)
        time_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.timer_on_input = TextInput(text="07:00", multiline=False, size_hint_x=0.35)
        self.timer_off_input = TextInput(text="22:00", multiline=False, size_hint_x=0.35)
        time_row.add_widget(AppLabel(text="Aan", color=MUTED, bold=True, size_hint_x=0.15))
        time_row.add_widget(self.timer_on_input)
        time_row.add_widget(AppLabel(text="Uit", color=MUTED, bold=True, size_hint_x=0.15))
        time_row.add_widget(self.timer_off_input)
        timer_card.add_widget(time_row)
        manual_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.manual_value_input = TextInput(text="10", multiline=False, input_filter="int", size_hint_x=0.2)
        self.manual_unit_spinner = Spinner(text="minutes", values=["seconds", "minutes", "hours"], size_hint_x=0.28)
        start_btn = RoundButton(text="Start", background_color=GREEN, border_color=(0.09, 0.48, 0.25, 1), color=(1, 1, 1, 1))
        stop_btn = RoundButton(text="Stop", background_color=(0.69, 0.0, 0.13, 1), border_color=(0.58, 0.04, 0.16, 1), color=(1, 1, 1, 1))
        start_btn.bind(on_release=lambda *_: self.start_manual_timer())
        stop_btn.bind(on_release=lambda *_: self.stop_manual_timer())
        manual_row.add_widget(AppLabel(text="Manueel", color=TEXT, bold=True, size_hint_x=0.18))
        manual_row.add_widget(self.manual_value_input)
        manual_row.add_widget(self.manual_unit_spinner)
        manual_row.add_widget(start_btn)
        manual_row.add_widget(stop_btn)
        timer_card.add_widget(manual_row)
        self.manual_status_label = AppLabel(text="Niet actief", color=MUTED, bold=True, size_hint_y=None, height=dp(22), halign="left")
        timer_card.add_widget(self.manual_status_label)
        screen.content.add_widget(timer_card)

        scheduler_card = Card("Lesrooster")
        scheduler_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(12))
        scheduler_row.add_widget(AppLabel(text="Actief", color=TEXT, bold=True))
        self.scheduler_switch = Switch(active=False)
        scheduler_row.add_widget(self.scheduler_switch)
        scheduler_row.add_widget(AppLabel(text="Pauze min", color=MUTED, bold=True))
        self.pause_input = TextInput(text="15", multiline=False, input_filter="int", size_hint_x=0.22)
        scheduler_row.add_widget(self.pause_input)
        save_btn = RoundButton(text="Opslaan", background_color=RED, border_color=(0.73, 0.1, 0.15, 1), color=(1, 1, 1, 1), size_hint_x=0.25)
        save_btn.bind(on_release=lambda *_: self.save_scheduler())
        scheduler_row.add_widget(save_btn)
        scheduler_card.add_widget(scheduler_row)
        scheduler_card.add_widget(AppLabel(text="Lessen: naam,start,einde per regel", color=MUTED, size_hint_y=None, height=dp(20), halign="left"))
        self.lessons_input = TextInput(text="Les 1,08:30,10:00\nLes 2,10:15,11:45", multiline=True, size_hint_y=None, height=dp(120))
        scheduler_card.add_widget(self.lessons_input)
        scheduler_card.add_widget(AppLabel(text="Pauzes: tijd per regel", color=MUTED, size_hint_y=None, height=dp(20), halign="left"))
        self.breaks_input = TextInput(text="10:00", multiline=True, size_hint_y=None, height=dp(90))
        scheduler_card.add_widget(self.breaks_input)
        screen.content.add_widget(scheduler_card)
        return screen

    def build_info_screen(self):
        screen = Section(name="Info & Updates")
        self.page_header(screen.content, "Info & Updates", "Check op updates via git en werk lokaal automatisch bij")

        card = Card("App informatie")
        self.backend_label = AppLabel(text=f"Backend: {BACKEND_URL}", color=TEXT, size_hint_y=None, height=dp(22), halign="left")
        self.repo_label = AppLabel(text=f"Repo: {self.repo_dir}", color=TEXT, size_hint_y=None, height=dp(22), halign="left")
        self.current_version_label = AppLabel(text="Lokale commit: laden...", color=TEXT, size_hint_y=None, height=dp(22), halign="left")
        self.remote_version_label = AppLabel(text=f"Remote ({UPDATE_BRANCH}): laden...", color=TEXT, size_hint_y=None, height=dp(22), halign="left")
        self.update_status_label = AppLabel(text="Nog niet gecontroleerd", color=MUTED, bold=True, size_hint_y=None, height=dp(22), halign="left")
        card.add_widget(self.backend_label)
        card.add_widget(self.repo_label)
        card.add_widget(self.current_version_label)
        card.add_widget(self.remote_version_label)
        card.add_widget(self.update_status_label)
        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        check_btn = RoundButton(text="Check git updates", background_color=(0.19, 0.21, 0.25, 1), border_color=(0.15, 0.16, 0.2, 1), color=(1, 1, 1, 1))
        apply_btn = RoundButton(text="Update via git pull", background_color=GREEN, border_color=(0.09, 0.48, 0.25, 1), color=(1, 1, 1, 1))
        restart_btn = RoundButton(text="Herstart app", background_color=RED, border_color=(0.73, 0.1, 0.15, 1), color=(1, 1, 1, 1))
        check_btn.bind(on_release=lambda *_: self.check_updates_async())
        apply_btn.bind(on_release=lambda *_: self.apply_update_async())
        restart_btn.bind(on_release=lambda *_: self.restart_self())
        buttons.add_widget(check_btn)
        buttons.add_widget(apply_btn)
        buttons.add_widget(restart_btn)
        card.add_widget(buttons)
        card.add_widget(AppLabel(text="Na een push: Check git updates en daarna Update via git pull. De app probeert daarna ook desktop/install-bestanden lokaal te synchroniseren.", color=MUTED, size_hint_y=None, height=dp(44), halign="left", valign="middle"))
        screen.content.add_widget(card)

        self.refresh_version_labels()
        return screen

    def switch_screen(self, name):
        self.screen_manager.current = name
        for page, button in self.nav_buttons.items():
            if page == name:
                button.base_color = (1, 1, 1, 1)
                button.color = RED
            else:
                button.base_color = PRIMARY_DARK
                button.color = (1, 1, 1, 1)
            button._redraw()

    def on_brightness_change(self, _slider, value):
        self.brightness_value_label.text = f"{int(value)}%"

    def poll_state(self, _dt):
        if self.timer_switch.active:
            self.apply_clock_timer_once()
        self.fetch_state_async()

    def animation_tick(self, dt):
        self.phase += dt
        self.preview_widget.phase = self.phase
        self.preview_widget.redraw()

    def fetch_state_async(self):
        if self.fetch_in_flight:
            return
        self.fetch_in_flight = True

        def worker():
            state = self.http_get_json("/api/state")
            Clock.schedule_once(lambda _dt: self.on_state(state), 0)

        threading.Thread(target=worker, daemon=True).start()

    def on_state(self, state):
        self.fetch_in_flight = False
        if not state:
            self.status_label.text = "Backend offline"
            return

        self.state = state
        self.status_label.text = "Verbonden"

        desired = state.get("desired", {})
        scheduler = state.get("scheduler", {})
        device = state.get("device", {})
        telemetry = device.get("telemetry", {})
        applied = device.get("applied") if isinstance(device.get("applied"), dict) else {}
        live = applied if applied else desired

        temp = to_float(telemetry.get("temperature"))
        lux = to_float(telemetry.get("lux"))
        live_mode = live.get("mode", desired.get("mode", "white"))
        live_effect = live.get("effect", desired.get("effect", "none"))
        live_brightness = int(live.get("brightness", desired.get("brightness", 50)))
        live_color = live.get("color") or desired.get("color") or {"r": 255, "g": 255, "b": 255}
        live_power = bool(live.get("power", desired.get("power", True)))

        self.current_rgb = [int(live_color.get("r", 255)), int(live_color.get("g", 255)), int(live_color.get("b", 255))]
        self.current_brightness = live_brightness
        self.current_effect = live_effect
        self.current_power = live_power

        self.preview_widget.rgb = self.current_rgb
        self.preview_widget.brightness = live_brightness
        self.preview_widget.effect = live_effect
        self.preview_widget.power_on = live_power
        self.preview_widget.redraw()

        self.online_value.text = "Online" if device.get("online", False) else "Offline"
        self.temp_value.text = f"{temp:.1f} C" if temp is not None else "--"
        self.lux_value.text = f"{lux:.0f} lux" if lux is not None else "--"
        self.mode_live_value.text = str(live_mode).upper()
        self.brightness_live_value.text = f"{live_brightness}%"
        self.effect_live_value.text = str(live_effect).upper()

        self.temp_gauge.set_value(temp)
        self.lux_gauge.set_value(lux)

        if temp is not None:
            self.temp_history.append(temp)
            self.temp_spark.set_values(list(self.temp_history))
        if lux is not None:
            self.lux_history.append(lux)
            self.lux_spark.set_values(list(self.lux_history))

        desired_mode = desired.get("mode", "white")
        for mode, button in self.mode_buttons.items():
            if mode == desired_mode:
                button.base_color = RED
                button.color = (1, 1, 1, 1)
            else:
                button.base_color = SOFT
                button.color = TEXT
            button._redraw()

        brightness = int(desired.get("brightness", 50))
        self.brightness_slider.value = brightness
        self.brightness_value_label.text = f"{brightness}%"
        self.effect_spinner.text = desired.get("effect", "none")

        desired_color = desired.get("color") or {"r": 255, "g": 255, "b": 255}
        for channel, key in [("R", "r"), ("G", "g"), ("B", "b")]:
            value = int(desired_color.get(key, 255))
            self.rgb_sliders[channel].value = value
            self.rgb_labels[channel].text = f"{channel}: {value}"

        self.auto_lux_switch.active = bool(desired.get("auto", False))
        self.scheduler_switch.active = bool(scheduler.get("enabled", False))
        self.pause_input.text = str(int(scheduler.get("pauseDurationMin", 15)))
        self.lessons_input.text = self.lessons_to_text(scheduler.get("lessons", []))
        self.breaks_input.text = "\n".join(scheduler.get("breaks", []))

    def lessons_to_text(self, lessons):
        lines = []
        for lesson in lessons or []:
            lines.append(f"{lesson.get('name', 'Les')},{lesson.get('start', '08:30')},{lesson.get('end', '10:00')}")
        return "\n".join(lines)

    def parse_lessons(self):
        out = []
        for raw_line in self.lessons_input.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 3:
                out.append({"name": parts[0] or "Les", "start": parts[1], "end": parts[2]})
        return out

    def parse_breaks(self):
        return [line.strip() for line in self.breaks_input.text.splitlines() if line.strip()]

    def save_scheduler(self):
        pause_value = int(self.pause_input.text or "15")
        self.simple_post(
            "/api/scheduler",
            {
                "enabled": bool(self.scheduler_switch.active),
                "pauseDurationMin": max(1, pause_value),
                "lessons": self.parse_lessons(),
                "breaks": self.parse_breaks(),
            },
        )

    def start_manual_timer(self):
        value = max(1, int(self.manual_value_input.text or "1"))
        factor = {"seconds": 1, "minutes": 60, "hours": 3600}.get(self.manual_unit_spinner.text, 60)
        self.manual_timer_remaining_s = value * factor
        self.stop_manual_timer(cancel_only=True)
        self.send_command({"power": True})
        self.manual_timer_event = Clock.schedule_interval(self._tick_manual_timer, 1.0)
        self._tick_manual_timer(0)

    def stop_manual_timer(self, *_args, cancel_only=False):
        if self.manual_timer_event is not None:
            self.manual_timer_event.cancel()
            self.manual_timer_event = None
        if not cancel_only:
            self.manual_status_label.text = "Niet actief"

    def _tick_manual_timer(self, _dt):
        if self.manual_timer_remaining_s <= 0:
            self.manual_status_label.text = "Klaar - LED uit"
            self.send_command({"power": False})
            self.stop_manual_timer(cancel_only=True)
            return False

        mins, secs = divmod(self.manual_timer_remaining_s, 60)
        self.manual_status_label.text = f"Resterend {mins:02d}:{secs:02d}"
        self.manual_timer_remaining_s -= 1
        return True

    def apply_clock_timer_once(self, *_args):
        if not self.timer_switch.active:
            self.last_timer_power = None
            return

        try:
            on_hour, on_minute = [int(part) for part in self.timer_on_input.text.split(":")]
            off_hour, off_minute = [int(part) for part in self.timer_off_input.text.split(":")]
        except Exception:
            return

        now = time.localtime()
        now_mins = now.tm_hour * 60 + now.tm_min
        on_mins = on_hour * 60 + on_minute
        off_mins = off_hour * 60 + off_minute
        if on_mins <= off_mins:
            should_on = on_mins <= now_mins < off_mins
        else:
            should_on = now_mins >= on_mins or now_mins < off_mins

        if self.last_timer_power is should_on:
            return
        self.last_timer_power = should_on
        self.send_command({"power": bool(should_on)})

    def send_command(self, payload):
        self.simple_post("/api/command", payload)

    def simple_post(self, path, payload):
        def worker():
            ok = self.http_post(path, payload)
            Clock.schedule_once(lambda _dt: self.on_post_done(ok), 0)

        threading.Thread(target=worker, daemon=True).start()

    def on_post_done(self, ok):
        self.status_label.text = "Verbonden" if ok else "Commando mislukt"
        if ok:
            self.fetch_state_async()

    def run_git(self, *args):
        command = ["git", "-C", str(self.repo_dir), *args]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output

    def repo_ready(self):
        return self.repo_dir.exists() and (self.repo_dir / ".git").exists()

    def sync_runtime_files_from_repo(self):
        copied = 0
        warnings = []

        source_app = self.repo_dir / REPO_APP_REL
        if source_app.exists() and source_app.resolve() != self.app_file.resolve():
            try:
                self.app_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_app, self.app_file)
                copied += 1
            except OSError as exc:
                warnings.append(f"app sync mislukt: {exc}")

        for source_rel, target_path in REPO_SYNC_TARGETS:
            source_path = self.repo_dir / source_rel
            if not source_path.exists():
                continue
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                copied += 1
            except OSError as exc:
                warnings.append(f"{target_path.name}: {exc}")

        return copied, warnings

    def refresh_version_labels(self):
        if not self.repo_ready():
            self.current_version_label.text = "Lokale commit: geen git repo"
            self.remote_version_label.text = f"Remote ({UPDATE_BRANCH}): onbekend"
            return

        local_ok, local = self.run_git("rev-parse", "--short", "HEAD")
        remote_ok, remote = self.run_git("rev-parse", "--short", f"origin/{UPDATE_BRANCH}")
        self.current_version_label.text = f"Lokale commit: {local if local_ok else 'onbekend'}"
        self.remote_version_label.text = f"Remote ({UPDATE_BRANCH}): {remote if remote_ok else 'onbekend'}"

    def check_updates_async(self):
        self.update_status_label.text = "Controleren..."

        def worker():
            if not self.repo_ready():
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Geen git repo op {self.repo_dir}"), 0)
                return

            fetch_ok, fetch_out = self.run_git("fetch", "--prune", "origin")
            if not fetch_ok:
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Fetch mislukt: {fetch_out}"), 0)
                return

            local_ok, local = self.run_git("rev-parse", "--short", "HEAD")
            remote_ok, remote = self.run_git("rev-parse", "--short", f"origin/{UPDATE_BRANCH}")
            count_ok, counts = self.run_git("rev-list", "--left-right", "--count", f"HEAD...origin/{UPDATE_BRANCH}")

            ahead = behind = 0
            if count_ok:
                parts = counts.split()
                if len(parts) >= 2:
                    ahead = int(parts[0])
                    behind = int(parts[1])

            def finish(_dt):
                self.refresh_version_labels()
                if not (local_ok and remote_ok):
                    self.update_status_label.text = "Kon git commits niet lezen"
                elif behind > 0:
                    self.update_status_label.text = f"Update beschikbaar ({local} -> {remote}, {behind} commit(s) achter)"
                elif ahead > 0:
                    self.update_status_label.text = "Lokale branch loopt voor op origin"
                else:
                    self.update_status_label.text = "Up-to-date met origin"

            Clock.schedule_once(finish, 0)

        threading.Thread(target=worker, daemon=True).start()

    def apply_update_async(self):
        self.update_status_label.text = "Installeren..."

        def worker():
            if not self.repo_ready():
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Geen git repo op {self.repo_dir}"), 0)
                return

            fetch_ok, fetch_out = self.run_git("fetch", "--prune", "origin")
            if not fetch_ok:
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Fetch mislukt: {fetch_out}"), 0)
                return

            pull_ok, pull_out = self.run_git("pull", "--ff-only", "origin", UPDATE_BRANCH)
            if not pull_ok:
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Git pull mislukt: {pull_out}"), 0)
                return

            copied, warnings = self.sync_runtime_files_from_repo()

            if warnings:
                warning_text = "; ".join(warnings[:2])
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Update ok, maar sync-waarschuwing: {warning_text}"), 0)
            else:
                Clock.schedule_once(lambda _dt: setattr(self.update_status_label, "text", f"Update klaar ({copied} bestand(en) gesynchroniseerd), herstarten..."), 0)

            Clock.schedule_once(lambda _dt: self.restart_self(), 0.7)

        threading.Thread(target=worker, daemon=True).start()

    def restart_self(self):
        os.execv(sys.executable, [sys.executable, str(self.app_file)])

    def http_get_json(self, path):
        url = f"{BACKEND_URL}{path}"
        try:
            with request.urlopen(url, timeout=1.8) as response:
                return json.loads(response.read().decode("utf-8"))
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
    LEDControllerApp().run()


if __name__ == "__main__":
    main()
