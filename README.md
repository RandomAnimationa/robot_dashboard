# ESP32 + L298N robot control (WiFi + gamepad + pygame dashboard)

## 1. Firmware (`esp32_firmware/robot_firmware.ino`)

- Wiring used (already set in the code):
  - Left motor: `PWM1=GPIO16`, `IN1=GPIO33`, `IN2=GPIO32`
  - Right motor: `PWM2=GPIO4`, `IN3=GPIO26`, `IN4=GPIO25`
- The ESP32 creates its own WiFi network:
  - SSID: `RobotESP32`
  - Password: `robot1234`
  - Robot IP once connected: `192.168.4.1`
- Flash it with the Arduino IDE (board "ESP32 Dev Module" or whichever matches your board).
  Uses the ESP32 Arduino core v3.x `ledc` API (`ledcAttach` / `ledcWrite(pin, ...)`).
- UDP protocol, port `4210`:
  - PC -> Robot: `L:<-255..255>,R:<-255..255>\n`
  - Robot -> PC: `T:up=...,rssi=...,l=...,r=...,batt=...,clients=...\n`
- There's a watchdog: if no command arrives within 500 ms, the robot stops itself
  (in case the connection to the dashboard drops).
- Battery reading is optional and disabled by default (`BATTERY_ENABLED false`).
  If you add a voltage divider to an ADC pin, enable it and adjust
  `BATTERY_PIN` / `BATTERY_DIVIDER`.

## 2. Dashboard (`dashboard/`)

Requires Python 3 and pygame:

```bash
python -m venv venv   # create your virtual environment
source venv/bin/activate   # activate it
```

```bash
pip install pygame-ce
```

Before running it:

1. Connect your PC to the `RobotESP32` WiFi network.
2. Connect a controller/gamepad (USB or bluetooth) to the PC.

Run:

```bash
cd dashboard
python3 main.py
```

### Screens

- **Control**: robot silhouette (each wheel's color shows forward/reverse/stopped),
  live telemetry panel, active preset, and macro status.
- **Presets**: pick, create, edit, or delete control mapping presets. Each preset is
  a list of **mappings**, and each mapping is simply:

  > take this **input** (a joystick axis or a trigger), and map its value from
  > `[in_min..in_max]` to `[out_min..out_max]` on this **target** motor.

  For example: `Left stick Y: -100..100 -> Motor L: -255..255`. Axes are shown on a
  `-100..100` scale and triggers on a `0..100` scale; motor outputs go from `-255`
  to `255`. Several mappings can target the same motor (e.g. one mapping adds
  throttle, another adds steering) — their outputs are added together and clamped
  to `-255..255`. To invert a mapping, just swap its `out_min`/`out_max` values
  (e.g. `out_min=255, out_max=-255`).

  4 presets come built in by default, all built with this same mapping system:
  1. **Tank**: each stick controls one wheel (forward/back).
  2. **Split arcade**: one stick (Y axis) drives both wheels forward/back, the other
     stick (X axis) steers.
  3. **Triggers + steering**: right trigger accelerates forward, left trigger
     accelerates in reverse, one stick steers.
  4. **Single stick**: Y axis = forward/back, X axis = steering, all on one stick.
- **Macros**: create movement sequences ("autonomous" routines) assigned to a
  controller button. Each macro is an ordered list of steps
  `{motor: L/R/BOTH, speed, duration in ms}`. "Single trigger" mode runs the whole
  sequence once when the button is pressed; "hold" mode cuts the sequence short if
  you release the button before it finishes. While a macro is running it takes full
  control of the robot (normal joystick control is paused) and hands it back
  automatically once it's done.
- **Controller test**: shows live raw axis and button values from your controller,
  so you can identify which axis index corresponds to each stick/trigger if the
  default mapping doesn't match your controller model. From this screen you can
  adjust and save the mapping (`config/controller_map.json`), invert Y axes, and
  adjust the deadzone.

### Config files (`dashboard/config/`)

- `settings.json`: robot IP/port and command send rate (Hz).
- `controller_map.json`: which raw axis index corresponds to each stick/trigger,
  Y-axis inversion, deadzone.
- `presets.json`: saved presets and which one is active.
- `macros.json`: saved macros.

Everything is stored as plain JSON, so you can also edit these files by hand if
you prefer.

## Notes

- The position/orientation shown in the silhouette is only a dead-reckoning
  estimate (it integrates the speeds being sent) — there are no encoders or IMU,
  so it will drift over time. It's just there to give a visual sense of movement.
- If you switch controllers (a different gamepad model), you'll likely need to
  re-adjust `controller_map.json` from the "Controller test" screen.
