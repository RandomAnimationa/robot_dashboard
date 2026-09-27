"""
Macro ("autonomous") system: sequences of steps like
  { "motor": "L"/"R"/"BOTH", "speed": -255..255, "duration_ms": int }
assignable to a controller button.

When a macro fires, it takes exclusive control of the robot (override in
RobotLink) for the duration of the sequence and then hands control back to
the active preset.

mode:
  "on_press"  -> runs once, fully, when the button is pressed
  "hold"      -> repeats/holds while the button stays pressed
                 (if released before finishing, it's cut short and stopped)
"""

import json
import os
import threading
import time


class MacroManager:
    def __init__(self, path, robot_link):
        self.path = path
        self.link = robot_link
        self.data = {"macros": []}
        self.load()

        self._running_thread = None
        self._stop_flag = threading.Event()
        self._button_state = {}

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        if "macros" not in self.data:
            self.data["macros"] = []

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def list_macros(self):
        return self.data.get("macros", [])

    def get_by_button(self, button_index):
        for m in self.list_macros():
            if m.get("trigger_button") == button_index:
                return m
        return None

    def add_or_update(self, macro):
        macros = self.list_macros()
        for i, m in enumerate(macros):
            if m["id"] == macro["id"]:
                macros[i] = macro
                self.save()
                return
        macros.append(macro)
        self.save()

    def delete(self, macro_id):
        self.data["macros"] = [m for m in self.list_macros() if m["id"] != macro_id]
        self.save()

    def is_running(self):
        return self._running_thread is not None and self._running_thread.is_alive()

    def process_buttons(self, button_states):
        """
        button_states: dict {index: bool} with the current state of each button.
        Detects press/release edges and starts/stops macros according to their mode.
        """
        for idx, pressed in button_states.items():
            was_pressed = self._button_state.get(idx, False)
            self._button_state[idx] = pressed

            macro = self.get_by_button(idx)
            if macro is None:
                continue

            just_pressed = pressed and not was_pressed
            just_released = (not pressed) and was_pressed
            mode = macro.get("mode", "on_press")

            if mode == "on_press" and just_pressed and not self.is_running():
                self._start(macro)
            elif mode == "hold":
                if just_pressed and not self.is_running():
                    self._start(macro)
                elif just_released:
                    self._stop_flag.set()

    def _start(self, macro):
        self._stop_flag.clear()
        self._running_thread = threading.Thread(
            target=self._run_macro, args=(macro,), daemon=True
        )
        self._running_thread.start()

    def _run_macro(self, macro):
        for step in macro.get("steps", []):
            if self._stop_flag.is_set():
                break
            speed = int(step.get("speed", 0))
            motor = step.get("motor", "BOTH")
            duration_s = max(0, int(step.get("duration_ms", 0))) / 1000.0

            if motor == "L":
                self._apply(speed, None)
            elif motor == "R":
                self._apply(None, speed)
            else:  # BOTH
                self._apply(speed, speed)

            # split the sleep so we can bail out early if the button is released
            end = time.time() + duration_s
            while time.time() < end:
                if self._stop_flag.is_set():
                    break
                time.sleep(0.02)

        self.link.clear_override()

    def _apply(self, left, right):
        # Keeps the last value of whichever wheel isn't specified in this step.
        cur_l = self._last_l if hasattr(self, "_last_l") else 0
        cur_r = self._last_r if hasattr(self, "_last_r") else 0
        l = cur_l if left is None else left
        r = cur_r if right is None else right
        self._last_l, self._last_r = l, r
        self.link.set_override(l, r)
