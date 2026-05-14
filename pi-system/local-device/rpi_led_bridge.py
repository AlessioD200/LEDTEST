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
    import spidev as _spidev  # type: ignore
    _spidev_available = True
except Exception:  # pragma: no cover - expected on non-Pi machines
    _spidev = None  # type: ignore
    _spidev_available = False

try:
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover - expected on non-Pi machines
    GPIO = None

try:
    import board  # type: ignore
    import busio  # type: ignore
    from adafruit_scd30 import SCD30 as _SCD30  # type: ignore
    _scd30_lib_available = True
except Exception:  # pragma: no cover - expected when package is not installed
    board = None  # type: ignore
    busio = None  # type: ignore
    _SCD30 = None  # type: ignore
    _scd30_lib_available = False


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


class APA102Strip:
    """Hardware SPI driver for APA102/SK9822 LED strips.

    Frame format per LED: [0b111_bbbbb, Blue, Green, Red]
    where bbbbb is 5-bit global brightness (0-31).
    """

    def __init__(self, count: int, spi_bus: int = 0, spi_device: int = 0,
                 max_speed_hz: int = 8_000_000):
        self._count = count
        self._spi_bus = spi_bus
        self._spi_device = spi_device
        self._max_speed_hz = max_speed_hz
        # Store as packed (r<<16)|(g<<8)|b ints
        self._pixels: list[int] = [0] * count
        self._brightness = 255  # 0-255
        self._spi = None

    def begin(self) -> None:
        dev = _spidev.SpiDev()  # type: ignore[union-attr]
        dev.open(self._spi_bus, self._spi_device)
        dev.max_speed_hz = self._max_speed_hz
        dev.mode = 0b00
        self._spi = dev

    def numPixels(self) -> int:
        return self._count

    def setPixelColor(self, index: int, color: int) -> None:
        """color is (r << 16) | (g << 8) | b"""
        if 0 <= index < self._count:
            self._pixels[index] = color

    def setBrightness(self, brightness: int) -> None:
        self._brightness = max(0, min(255, brightness))

    def show(self) -> None:
        if self._spi is None:
            return
        # Scale global brightness 0-255 → 0-31 (APA102 5-bit)
        apa_br = (self._brightness * 31) // 255
        header_byte = 0b11100000 | apa_br
        buf = bytearray(4)  # start frame: 4 x 0x00
        for packed in self._pixels:
            r = (packed >> 16) & 0xFF
            g = (packed >> 8) & 0xFF
            b = packed & 0xFF
            buf += bytearray([header_byte, b, g, r])
        # End frame: ceil(n/2) bytes of 0x00.
        # 0x00 provides the required clock pulses without being misinterpreted
        # as an LED frame (0xFF header would make the last LEDs appear white).
        end_bytes = max(1, (self._count + 1) // 2)
        buf += bytearray(end_bytes)
        # xfer2 is limited to ~4096 bytes on some kernels; chunk if needed
        chunk = 4096
        for offset in range(0, len(buf), chunk):
            self._spi.xfer2(list(buf[offset:offset + chunk]))


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
        self.led_count = env_int("LED_COUNT", 144)
        self.led_brightness = env_int("LED_BRIGHTNESS", 255)
        self.spi_bus = env_int("SPI_BUS", 0)
        self.spi_device = env_int("SPI_DEVICE", 0)
        self.pir_gpio_pin = os.environ.get("PIR_GPIO_PIN", "").strip()

        self.running = True
        self.command_queue: queue.Queue[dict] = queue.Queue()
        self.desired = DesiredState(color={"r": 255, "g": 255, "b": 255})
        self.started_at = time.monotonic()
        self.last_status_sent = 0.0
        self.last_telemetry_sent = 0.0
        self.motion_state = False
        self.mock_mode = not _spidev_available or not Path("/dev/spidev0.0").exists()
        self.scd30_enabled = env_bool("SCD30_ENABLED", True)
        self.scd30 = None
        self.scd30_detected = False
        self.scd30_last_read = 0.0
        self.scd30_data = {
            "co2": None,
            "humidity": None,
            "temperature": None,
        }

        if self.mock_mode:
            self.strip = MockStrip(self.led_count)
        else:
            self.strip = APA102Strip(
                self.led_count,
                spi_bus=self.spi_bus,
                spi_device=self.spi_device,
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

        if self.scd30_enabled and _scd30_lib_available and board is not None and busio is not None and _SCD30 is not None:
            try:
                i2c = busio.I2C(board.SCL, board.SDA)
                try:
                    self.scd30 = _SCD30(i2c, 0x61)
                except TypeError:
                    self.scd30 = _SCD30(i2c)
                self.scd30_detected = True
            except Exception:
                self.scd30 = None
                self.scd30_detected = False

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
        now = time.monotonic()

        if self.scd30_detected and self.scd30 is not None and (now - self.scd30_last_read) >= 2.0:
            try:
                if getattr(self.scd30, "data_available", True):
                    co2 = getattr(self.scd30, "CO2", None)
                    humidity = getattr(self.scd30, "relative_humidity", None)
                    temperature = getattr(self.scd30, "temperature", None)

                    self.scd30_data["co2"] = round(float(co2), 0) if co2 is not None else None
                    self.scd30_data["humidity"] = round(float(humidity), 1) if humidity is not None else None
                    self.scd30_data["temperature"] = round(float(temperature), 1) if temperature is not None else None
            except Exception:
                self.scd30_detected = False
            finally:
                self.scd30_last_read = now

        if self.pir_enabled and GPIO is not None:
            try:
                self.motion_state = bool(GPIO.input(int(self.pir_gpio_pin)))
            except Exception:
                self.motion_state = False

        ambient_temp = self.scd30_data["temperature"]
        if ambient_temp is None:
            ambient_temp = read_cpu_temp_c()

        telemetry = {
            "temperature": ambient_temp,
            "humidity": self.scd30_data["humidity"],
            "co2": self.scd30_data["co2"],
            "lux": None,
            "motion": self.motion_state,
            "uptime": int(time.monotonic() - self.started_at),
            "scd30Available": bool(self.scd30_detected),
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

            color_value = (red << 16) | (green << 8) | blue
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