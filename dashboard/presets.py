"""
Control presets: fully generic input -> output mapping system.

A preset is just a list of "mappings". Each mapping says:
    "take this input (a joystick axis or a trigger), and map its value
     from [in_min..in_max] to [out_min..out_max] on this motor"

Example: "Left stick Y: -100..100  ->  Motor L: -255..255"

Multiple mappings can target the same motor (their outputs are added
together and clamped to -255..255), which is how things like "throttle +
turn" combos are built: one mapping adds throttle to both motors, another
adds/subtracts turn on top.

Available inputs (raw ranges before the -100..100 / 0..100 convention used
in the UI):
    left_x, left_y, right_x, right_y   -> joystick axes, raw -1..1
    left_trigger, right_trigger        -> triggers, raw 0..1

Available targets: "L", "R", "BOTH" (adds to both motors at once)

Presets are stored/loaded from config/presets.json.
"""

import json
import os

MAX_SPEED = 255

INPUTS = ["left_x", "left_y", "right_x", "right_y", "left_trigger", "right_trigger"]
TARGETS = ["L", "R", "BOTH"]

INPUT_LABELS = {
    "left_x": "Left stick X",
    "left_y": "Left stick Y",
    "right_x": "Right stick X",
    "right_y": "Right stick Y",
    "left_trigger": "Left trigger",
    "right_trigger": "Right trigger",
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def get_input_percent(input_name, axes, triggers):
    """Returns the raw value of the given input, scaled to a -100..100
    (axes) or 0..100 (triggers) range, matching what the preset editor
    shows and lets you map."""
    if input_name in ("left_x", "left_y", "right_x", "right_y"):
        return axes.get(input_name, 0.0) * 100.0
    if input_name == "left_trigger":
        return triggers.get("left", 0.0) * 100.0
    if input_name == "right_trigger":
        return triggers.get("right", 0.0) * 100.0
    return 0.0


def apply_mapping(mapping, axes, triggers):
    """Returns the output contribution (a float, before clamping/summing)
    of a single mapping given the current controller state."""
    val = get_input_percent(mapping["input"], axes, triggers)

    in_min = mapping.get("in_min", -100)
    in_max = mapping.get("in_max", 100)
    out_min = mapping.get("out_min", -255)
    out_max = mapping.get("out_max", 255)

    lo, hi = (in_min, in_max) if in_min <= in_max else (in_max, in_min)
    val = _clamp(val, lo, hi)

    if in_max == in_min:
        t = 0.0
    else:
        t = (val - in_min) / (in_max - in_min)
        t = _clamp(t, 0.0, 1.0)

    return out_min + t * (out_max - out_min)


def default_mapping(input_name="left_y", target="L"):
    return {
        "input": input_name,
        "target": target,
        "in_min": 0 if input_name.endswith("trigger") else -100,
        "in_max": 100,
        "out_min": -255,
        "out_max": 255,
    }


class PresetManager:
    def __init__(self, path):
        self.path = path
        self.data = {"active_preset": None, "presets": []}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        if not self.data.get("presets"):
            self.data = {"active_preset": None, "presets": []}

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def list_presets(self):
        return self.data.get("presets", [])

    def get_active(self):
        active_id = self.data.get("active_preset")
        for p in self.list_presets():
            if p["id"] == active_id:
                return p
        return self.list_presets()[0] if self.list_presets() else None

    def set_active(self, preset_id):
        self.data["active_preset"] = preset_id
        self.save()

    def add_or_update(self, preset):
        presets = self.list_presets()
        for i, p in enumerate(presets):
            if p["id"] == preset["id"]:
                presets[i] = preset
                self.save()
                return
        presets.append(preset)
        self.save()

    def delete(self, preset_id):
        self.data["presets"] = [p for p in self.list_presets() if p["id"] != preset_id]
        if self.data.get("active_preset") == preset_id:
            remaining = self.list_presets()
            self.data["active_preset"] = remaining[0]["id"] if remaining else None
        self.save()

    def compute(self, axes, triggers):
        preset = self.get_active()
        if preset is None:
            return 0, 0

        total_l = 0.0
        total_r = 0.0
        for mapping in preset.get("mappings", []):
            contribution = apply_mapping(mapping, axes, triggers)
            target = mapping.get("target", "L")
            if target in ("L", "BOTH"):
                total_l += contribution
            if target in ("R", "BOTH"):
                total_r += contribution

        return int(_clamp(total_l, -MAX_SPEED, MAX_SPEED)), int(_clamp(total_r, -MAX_SPEED, MAX_SPEED))
