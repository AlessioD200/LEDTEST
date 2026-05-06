#!/usr/bin/env python3
"""Local Raspberry Pi LED bridge for the Node backend.

Reads JSON command lines from stdin and writes JSON status/telemetry lines to stdout.
Falls back to a mock strip when running off-device so development and syntax validation
do not require Raspberry Pi hardware.
"""

from __future__ import annotations

import json
import math
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from rpi_ws281x import Color, PixelStrip, ws  # type: ignore
except Exception:  # pragma: no cover - expected on non-Pi machines
    Color = None
    PixelStrip = None
    ws = None

try:
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover - expected on non-Pi machines
    GPIO = None


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def mode_color(mode: str, custom: Optional[dict]) -> tuple[int, int, int]:
    if mode == "custom" and isinstance(custom, dict):
        return (
            int(clamp(custom.get("r", 255), 0, 255)),
            int(clamp(custom.get("g", 255), 0, 255)),
            int(clamp(custom.get("b", 255), 0, 255)),
        )

    mapping = {
        "white": (255, 255, 255),
        "warm": (255, 180, 90),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 110, 255),
        "purple": (180, 0, 255),
        "cyan": (0, 220, 255),
        "yellow": (255, 190, 0),
        "off": (0, 0, 0),
    }
    return mapping.get(mode, (255, 255, 255))


def wheel(pos: int) -> tuple[int, int, int]:
    pos %= 256
    if pos < 85:
        return 255 - pos * 3, pos * 3, 0
    if pos < 170:
        pos -= 85
        return 0, 255 - pos * 3, pos * 3
    pos -= 170
    return pos * 3, 0, 255 - pos * 3


def read_cpu_temp_c() -> Optional[float]:
    temp_file = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        raw = temp_file.read_text(encoding="utf-8").strip()
        return round(int(raw) / 1000.0, 1)
    except Exception:
        return None


class MockStrip:
    def __init__(self, count: int, *_args, **_kwargs):
        self._count = count
        self._pixels = [0] * count
        self._brightness = 255

    def begin(self) -> None:
        return None

    def numPixels(self) -> int:
        return self._count

    def setPixelColor(self, index: int, color: int) -> None:
        if 0 <= index < self._count:
            self._pixels[index] = color

    def setBrightness(self, brightness: int) -> None:
        self._brightness = brightness

    def show(self) -> None:
        return None


@dataclass
class DesiredState:
    power: bool = True
    mode: str = "white"
    auto: bool = False
    brightness: int = 50
    color: dict | None = None
    effect: str = "none"


class Bridge:
    def __init__(self) -> None:
        self.led_count = env_int("LED_COUNT", 60)
        self.led_gpio_pin = env_int("LED_GPIO_PIN", 18)
        self.led_brightness = env_int("LED_BRIGHTNESS", 255)
        self.led_dma = env_int("LED_DMA", 10)
        self.led_freq_hz = env_int("LED_FREQ_HZ", 800000)
        self.led_invert = env_bool("LED_INVERT", False)
        self.led_channel = env_int("LED_CHANNEL", 0)
        self.led_strip_type = str(os.environ.get("LED_STRIP_TYPE", "grb")).strip().lower()
        self.pir_gpio_pin = os.environ.get("PIR_GPIO_PIN", "").strip()

        self.running = True
        self.command_queue: queue.Queue[dict] = queue.Queue()
        self.desired = DesiredState(color={"r": 255, "g": 255, "b": 255})
        self.started_at = time.monotonic()
        self.last_status_sent = 0.0
        self.last_telemetry_sent = 0.0
        self.motion_state = False
        self.mock_mode = PixelStrip is None or Color is None

        strip_type = self.resolve_strip_type()
        if self.mock_mode:
            self.strip = MockStrip(self.led_count)
        else:
            self.strip = PixelStrip(
                self.led_count,
                self.led_gpio_pin,
                self.led_freq_hz,
                self.led_dma,
                self.led_invert,
                self.led_brightness,
                self.led_channel,
                strip_type,
            )
        self.strip.begin()

        self.pir_enabled = False
        if self.pir_gpio_pin and GPIO is not None:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(int(self.pir_gpio_pin), GPIO.IN)
                self.pir_enabled = True
            except Exception:
                self.pir_enabled = False

    def resolve_strip_type(self):
        if ws is None:
            return 0
        mapping = {
            "grb": ws.WS2811_STRIP_GRB,
            "rgb": ws.WS2811_STRIP_RGB,
            "brg": ws.WS2811_STRIP_BRG,
            "gbr": ws.WS2811_STRIP_GBR,
            "rgbw": ws.SK6812_STRIP_RGBW,
            "grbw": ws.SK6812_STRIP_GRBW,
        }
        return mapping.get(self.led_strip_type, ws.WS2811_STRIP_GRB)

    def emit(self, payload: dict) -> None:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def start_stdin_thread(self) -> None:
        def _reader() -> None:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.command_queue.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self.running = False

        threading.Thread(target=_reader, daemon=True).start()

    def send_online(self, online: bool) -> None:
        self.emit({
            "type": "online",
            "online": online,
            "localPi": True,
            "mock": self.mock_mode,
            "ts": int(time.time() * 1000),
        })

    def send_status(self) -> None:
        self.emit({
            "type": "status",
            "status": {
                "power": self.desired.power,
                "mode": self.desired.mode,
                "auto": self.desired.auto,
                "brightness": self.desired.brightness,
                "effect": self.desired.effect,
                "color": self.desired.color,
                "firmware": "rpi3-local-bridge",
                "localPi": True,
                "mock": self.mock_mode,
            },
        })
        self.last_status_sent = time.monotonic()

    def send_telemetry(self) -> None:
        if self.pir_enabled and GPIO is not None:
            try:
                self.motion_state = bool(GPIO.input(int(self.pir_gpio_pin)))
            except Exception:
                self.motion_state = False

        telemetry = {
            "temperature": read_cpu_temp_c(),
            "lux": None,
            "motion": self.motion_state,
            "uptime": int(time.monotonic() - self.started_at),
            "localPi": True,
            "mock": self.mock_mode,
        }
        self.emit({"type": "telemetry", "telemetry": telemetry})
        self.emit({"type": "heartbeat", "heartbeat": {"uptime": telemetry["uptime"], "localPi": True}})
        self.last_telemetry_sent = time.monotonic()

    def handle_command(self, command: dict) -> None:
        if command.get("type") != "set_state":
            return
        desired = command.get("desired") or {}
        self.desired = DesiredState(
            power=bool(desired.get("power", True)),
            mode=str(desired.get("mode", "white")),
            auto=bool(desired.get("auto", False)),
            brightness=int(clamp(desired.get("brightness", 50), 0, 100)),
            color=desired.get("color") if isinstance(desired.get("color"), dict) else {"r": 255, "g": 255, "b": 255},
            effect=str(desired.get("effect", "none")),
        )
        self.send_status()

    def apply_pixels(self) -> None:
        brightness_scale = clamp(self.desired.brightness / 100.0, 0.0, 1.0)
        if not self.desired.power or self.desired.mode == "off":
            brightness_scale = 0.0

        base_r, base_g, base_b = mode_color(self.desired.mode, self.desired.color)
        elapsed = time.monotonic() - self.started_at
        effect = self.desired.effect or "none"

        self.strip.setBrightness(int(clamp(self.led_brightness * brightness_scale, 0, 255)))

        for index in range(self.strip.numPixels()):
            red, green, blue = base_r, base_g, base_b

            if brightness_scale <= 0:
                red = green = blue = 0
            elif effect == "pulse":
                factor = 0.35 + 0.65 * ((math.sin(elapsed * 2.2) + 1.0) / 2.0)
                red = int(red * factor)
                green = int(green * factor)
                blue = int(blue * factor)
            elif effect == "strobe":
                if int(elapsed * 8) % 2:
                    red = green = blue = 0
            elif effect == "wave":
                factor = 0.2 + 0.8 * ((math.sin((elapsed * 4.0) + (index / 4.0)) + 1.0) / 2.0)
                red = int(red * factor)
                green = int(green * factor)
                blue = int(blue * factor)
            elif effect == "rainbow":
                red, green, blue = wheel((index * 256 // max(1, self.strip.numPixels()) + int(elapsed * 70)) % 256)

            if self.mock_mode:
                color_value = (red << 16) | (green << 8) | blue
            else:
                color_value = Color(int(red), int(green), int(blue))
            self.strip.setPixelColor(index, color_value)

        self.strip.show()

    def shutdown(self) -> None:
        self.running = False
        try:
            for index in range(self.strip.numPixels()):
                self.strip.setPixelColor(index, 0)
            self.strip.show()
        except Exception:
            pass
        if self.pir_enabled and GPIO is not None:
            try:
                GPIO.cleanup()
            except Exception:
                pass
        self.send_online(False)

    def run(self) -> None:
        self.start_stdin_thread()
        self.send_online(True)
        self.send_status()
        self.send_telemetry()

        while self.running:
            try:
                while True:
                    self.handle_command(self.command_queue.get_nowait())
            except queue.Empty:
                pass

            self.apply_pixels()

            now = time.monotonic()
            if now - self.last_telemetry_sent >= 1.0:
                self.send_telemetry()
            if now - self.last_status_sent >= 8.0:
                self.send_status()

            time.sleep(1 / 30)

        self.shutdown()


def main() -> int:
    bridge = Bridge()

    def _stop(_signum, _frame):
        bridge.running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())