# Raspberry Pi 3 Local LED Install

This setup removes the ESP32 from the control path. The Raspberry Pi 3 runs the backend, the touchscreen dashboard, and the LED strip driver locally.

## What this installs

- Node backend in `DEVICE_MODE=local-pi`
- local Python WS281x bridge for the LED strip
- Chromium kiosk pointing to the touchscreen dashboard
- systemd services for backend + kiosk

## Assumptions

- Raspberry Pi OS with Desktop is installed
- your 7-inch touchscreen is connected and working
- your LED strip is a WS281x-compatible strip connected to the Pi
- data line is on GPIO18 unless you change it
- the strip has its own proper power supply
- ground of the strip power supply and the Pi are shared

## Wiring baseline

- LED data: GPIO18 on the Pi to LED DIN
- LED ground: Pi GND to LED power supply GND
- LED power: external 5V power supply sized for the strip

Do not power a long LED strip directly from the Pi 5V pin.

## Install steps

1. Clone the repository on the Pi.

```bash
git clone https://github.com/AlessioD200/LEDTEST.git
cd LEDTEST
```

2. Run the Pi installer.

```bash
chmod +x pi-system/deploy/install-rpi3-local.sh
./pi-system/deploy/install-rpi3-local.sh
```

3. If your strip is not on GPIO18 or uses a different pixel order, rerun with env vars.

```bash
LED_COUNT=144 LED_GPIO_PIN=18 LED_STRIP_TYPE=grb ./pi-system/deploy/install-rpi3-local.sh
```

Optional PIR input:

```bash
PIR_GPIO_PIN=27 ./pi-system/deploy/install-rpi3-local.sh
```

4. Reboot once.

```bash
sudo reboot
```

## After reboot

- the backend should be available at `http://127.0.0.1:3001/`
- the kiosk should open the dashboard fullscreen on the touchscreen
- the dashboard should control the LED strip directly from the Pi

## Verification

Run these checks on the Pi:

```bash
systemctl status led-backend.service --no-pager
systemctl status led-kiosk.service --no-pager
curl http://127.0.0.1:3001/api/health
curl http://127.0.0.1:3001/api/state
```

You should see:

- backend service is `active (running)`
- kiosk service is `active (running)` once the desktop session is available
- `/api/health` returns `{ "ok": true, ... }`
- `/api/state` returns `device.online: true`

## Important env vars

These are written into `pi-system/backend/.env` by the installer:

- `DEVICE_MODE=local-pi`
- `PORT=3001`
- `LED_COUNT`
- `LED_GPIO_PIN`
- `LED_BRIGHTNESS`
- `LED_DMA`
- `LED_FREQ_HZ`
- `LED_INVERT`
- `LED_CHANNEL`
- `LED_STRIP_TYPE`
- `PIR_GPIO_PIN` if provided

## Troubleshooting

If the backend is up but the strip stays dark:

1. Check the configured pin and pixel order in `pi-system/backend/.env`.
2. Make sure the strip power supply is on and shares ground with the Pi.
3. Check backend logs:

```bash
journalctl -u led-backend.service -n 200 --no-pager
```

4. If the kiosk does not appear, confirm a desktop session is running on `:0` and check:

```bash
journalctl -u led-kiosk.service -n 200 --no-pager
```

## Manual restart commands

```bash
sudo systemctl restart led-backend.service
sudo systemctl restart led-kiosk.service
```