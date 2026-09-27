"""
Robot dashboard (ESP32 + L298N) over WiFi, built with pygame.

Usage:
    1. Connect to the WiFi network created by the ESP32 (see robot_firmware.ino).
    2. Connect a gamepad to this PC (USB or bluetooth).
    3. python main.py

Screens (buttons at the top):
    Control   -> live control + telemetry + robot silhouette
    Presets   -> pick/create/edit joystick mapping presets
    Macros    -> create/edit automatic sequences assigned to buttons
    Test      -> see raw controller axes/buttons and adjust the mapping

Config files (config/ folder):
    settings.json         -> robot IP/port, control rate
    controller_map.json   -> which raw axis index corresponds to each stick/trigger
    presets.json          -> control presets
    macros.json           -> macros/autonomous sequences
"""

import json
import os
import time

import pygame

from network import RobotLink
from presets import PresetManager, INPUTS, INPUT_LABELS, TARGETS, default_mapping
from macros import MacroManager
from kinematics import DiffDriveEstimator
import render
from widgets import Button, NumberField, TextField, SelectableList, get_font

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

SCREEN_W, SCREEN_H = 1080, 680


def load_json(name):
    with open(os.path.join(CONFIG_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(name, data):
    with open(os.path.join(CONFIG_DIR, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def apply_deadzone(v, dz):
    if abs(v) < dz:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - dz) / (1.0 - dz)


class ControllerMap:
    def __init__(self):
        self.data = load_json("controller_map.json")

    def save(self):
        save_json("controller_map.json", self.data)

    def read(self, joystick):
        d = self.data
        axes = {}
        n_axes = joystick.get_numaxes()

        def get_axis(idx):
            if idx is None or idx >= n_axes:
                return 0.0
            return joystick.get_axis(idx)

        lx = get_axis(d["axis_left_x"])
        ly = get_axis(d["axis_left_y"])
        rx = get_axis(d["axis_right_x"])
        ry = get_axis(d["axis_right_y"])

        if d.get("invert_left_y"):
            ly = -ly
        if d.get("invert_right_y"):
            ry = -ry

        dz = d.get("deadzone", 0.1)
        axes["left_x"] = apply_deadzone(lx, dz)
        axes["left_y"] = apply_deadzone(ly, dz)
        axes["right_x"] = apply_deadzone(rx, dz)
        axes["right_y"] = apply_deadzone(ry, dz)

        rest = d.get("trigger_rest_value", -1.0)
        lt_raw = get_axis(d["axis_left_trigger"])
        rt_raw = get_axis(d["axis_right_trigger"])
        # normalize from [rest..1] to [0..1]
        span = (1.0 - rest) if (1.0 - rest) != 0 else 2.0
        lt = max(0.0, min(1.0, (lt_raw - rest) / span))
        rt = max(0.0, min(1.0, (rt_raw - rest) / span))
        triggers = {"left": lt, "right": rt}

        buttons = {i: bool(joystick.get_button(i)) for i in range(joystick.get_numbuttons())}

        return axes, triggers, buttons


class App:
    def __init__(self):
        pygame.init()
        pygame.joystick.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Robot Control Dashboard")
        self.clock = pygame.time.Clock()

        self.settings = load_json("settings.json")
        self.controller_map = ControllerMap()

        self.link = RobotLink(
            self.settings["robot_ip"],
            self.settings["robot_port"],
            self.settings.get("local_listen_port", 0),
            self.settings.get("control_rate_hz", 20),
        )
        self.link.start()

        self.preset_mgr = PresetManager(os.path.join(CONFIG_DIR, "presets.json"))
        self.macro_mgr = MacroManager(os.path.join(CONFIG_DIR, "macros.json"), self.link)

        self.estimator = DiffDriveEstimator()
        self.trail = []
        self.last_update_time = time.time()

        self.joystick = None
        self._init_joystick()

        self.screen_name = "control"
        self.editing_preset = None
        self.editing_macro = None

        self._build_top_buttons()
        self._build_preset_list_widgets()
        self._build_macro_list_widgets()
        self._build_test_screen_widgets()

    # ---------- setup ----------

    def _init_joystick(self):
        pygame.joystick.quit()
        pygame.joystick.init()
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
        else:
            self.joystick = None

    def _build_top_buttons(self):
        labels = [("control", "Control"), ("presets", "Presets"),
                  ("macros", "Macros"), ("test", "Controller test")]
        self.top_buttons = []
        x = 12
        for key, label in labels:
            btn = Button((x, 10, 130, 34), label, callback=lambda k=key: self._go_to(k))
            self.top_buttons.append(btn)
            x += 140
        self.btn_reload_joystick = Button(
            (SCREEN_W - 190, 10, 178, 34), "Rescan controller",
            callback=self._init_joystick, color=(60, 60, 40)
        )

    def _go_to(self, screen_name):
        self.screen_name = screen_name
        if screen_name == "presets":
            self._refresh_preset_list()
        if screen_name == "macros":
            self._refresh_macro_list()

    # ---------- preset list screen ----------

    def _build_preset_list_widgets(self):
        self.preset_list = SelectableList((30, 100, 380, 460), [])
        self.btn_activate_preset = Button((430, 100, 160, 36), "Activate", self._activate_selected_preset)
        self.btn_edit_preset = Button((430, 146, 160, 36), "Edit", self._edit_selected_preset)
        self.btn_new_preset = Button((430, 192, 160, 36), "New", self._new_preset)
        self.btn_delete_preset = Button((430, 238, 160, 36), "Delete", self._delete_selected_preset,
                                        color=(90, 40, 40))
        self._refresh_preset_list()

    def _refresh_preset_list(self):
        items = [(p["id"], p["name"]) for p in self.preset_mgr.list_presets()]
        self.preset_list.set_items(items)
        active = self.preset_mgr.get_active()
        if active:
            self.preset_list.selected = active["id"]

    def _activate_selected_preset(self):
        if self.preset_list.selected:
            self.preset_mgr.set_active(self.preset_list.selected)

    def _find_preset(self, preset_id):
        for p in self.preset_mgr.list_presets():
            if p["id"] == preset_id:
                return p
        return None

    def _edit_selected_preset(self):
        p = self._find_preset(self.preset_list.selected)
        if p:
            self._open_preset_editor(json.loads(json.dumps(p)))  # deep copy

    def _new_preset(self):
        new_id = f"preset_{int(time.time())}"
        self._open_preset_editor({
            "id": new_id, "name": "New preset", "description": "",
            "mappings": [default_mapping("left_y", "L"), default_mapping("right_y", "R")],
        })

    def _delete_selected_preset(self):
        if self.preset_list.selected:
            self.preset_mgr.delete(self.preset_list.selected)
            self._refresh_preset_list()

    # ---------- preset editor screen (generic input -> output mapping) ----------

    def _open_preset_editor(self, preset):
        self.editing_preset = preset
        self.preset_name_field = TextField((150, 96, 340, 32), preset.get("name", ""))
        self.preset_desc_field = TextField((150, 136, 700, 32), preset.get("description", ""))
        self._rebuild_mapping_widgets()

        self.btn_add_mapping = Button((30, 178, 170, 32), "+ Add mapping", self._add_mapping,
                                      color=(40, 70, 90))
        self.btn_save_preset = Button((30, 610, 160, 40), "Save", self._save_preset_editor,
                                      color=(40, 90, 40))
        self.btn_cancel_preset = Button((210, 610, 160, 40), "Cancel",
                                        lambda: self._go_to("presets"), color=(90, 40, 40))
        self.screen_name = "preset_edit"

    def _rebuild_mapping_widgets(self):
        self.mapping_widgets = []
        y = 250
        for i, m in enumerate(self.editing_preset["mappings"]):
            input_btn = Button((30, y, 190, 30), INPUT_LABELS.get(m["input"], m["input"]),
                                callback=lambda i=i: self._cycle_mapping_input(i), color=(60, 60, 90))
            target_btn = Button((230, y, 80, 30), m.get("target", "L"),
                                 callback=lambda i=i: self._cycle_mapping_target(i), color=(60, 90, 60))
            in_min_field = NumberField((320, y, 110, 30), int(m.get("in_min", -100)), step=5,
                                       min_value=-100, max_value=100)
            in_max_field = NumberField((440, y, 110, 30), int(m.get("in_max", 100)), step=5,
                                       min_value=-100, max_value=100)
            out_min_field = NumberField((560, y, 120, 30), int(m.get("out_min", -255)), step=5,
                                        min_value=-255, max_value=255)
            out_max_field = NumberField((690, y, 120, 30), int(m.get("out_max", 255)), step=5,
                                        min_value=-255, max_value=255)
            remove_btn = Button((820, y, 36, 30), "X", callback=lambda i=i: self._remove_mapping(i),
                                 color=(90, 40, 40))
            self.mapping_widgets.append({
                "input_btn": input_btn, "target_btn": target_btn,
                "in_min": in_min_field, "in_max": in_max_field,
                "out_min": out_min_field, "out_max": out_max_field,
                "remove_btn": remove_btn,
            })
            y += 38

    def _cycle_mapping_input(self, i):
        cur = self.editing_preset["mappings"][i]["input"]
        nxt = INPUTS[(INPUTS.index(cur) + 1) % len(INPUTS)] if cur in INPUTS else INPUTS[0]
        self.editing_preset["mappings"][i]["input"] = nxt
        self._rebuild_mapping_widgets()

    def _cycle_mapping_target(self, i):
        cur = self.editing_preset["mappings"][i].get("target", "L")
        nxt = TARGETS[(TARGETS.index(cur) + 1) % len(TARGETS)] if cur in TARGETS else "L"
        self.editing_preset["mappings"][i]["target"] = nxt
        self._rebuild_mapping_widgets()

    def _add_mapping(self):
        self.editing_preset["mappings"].append(default_mapping("left_y", "L"))
        self._rebuild_mapping_widgets()

    def _remove_mapping(self, i):
        del self.editing_preset["mappings"][i]
        self._rebuild_mapping_widgets()

    def _save_preset_editor(self):
        p = self.editing_preset
        p["name"] = self.preset_name_field.value.strip() or p["name"]
        p["description"] = self.preset_desc_field.value.strip()
        mappings = []
        for i, mw in enumerate(self.mapping_widgets):
            mappings.append({
                "input": self.editing_preset["mappings"][i]["input"],
                "target": self.editing_preset["mappings"][i]["target"],
                "in_min": mw["in_min"].value,
                "in_max": mw["in_max"].value,
                "out_min": mw["out_min"].value,
                "out_max": mw["out_max"].value,
            })
        p["mappings"] = mappings
        self.preset_mgr.add_or_update(p)
        self._go_to("presets")

    # ---------- macro list screen ----------

    def _build_macro_list_widgets(self):
        self.macro_list = SelectableList((30, 100, 380, 460), [])
        self.btn_edit_macro = Button((430, 100, 160, 36), "Edit", self._edit_selected_macro)
        self.btn_new_macro = Button((430, 146, 160, 36), "New", self._new_macro)
        self.btn_delete_macro = Button((430, 192, 160, 36), "Delete", self._delete_selected_macro,
                                       color=(90, 40, 40))
        self._refresh_macro_list()

    def _refresh_macro_list(self):
        items = [(m["id"], f'{m["name"]}  (btn {m.get("trigger_button")})')
                 for m in self.macro_mgr.list_macros()]
        self.macro_list.set_items(items)

    def _find_macro(self, macro_id):
        for m in self.macro_mgr.list_macros():
            if m["id"] == macro_id:
                return m
        return None

    def _edit_selected_macro(self):
        m = self._find_macro(self.macro_list.selected)
        if m:
            self._open_macro_editor(json.loads(json.dumps(m)))  # deep copy

    def _new_macro(self):
        new_id = f"macro_{int(time.time())}"
        self._open_macro_editor({
            "id": new_id, "name": "New macro", "trigger_button": 0,
            "mode": "on_press", "steps": []
        })

    def _delete_selected_macro(self):
        if self.macro_list.selected:
            self.macro_mgr.delete(self.macro_list.selected)
            self._refresh_macro_list()

    def _open_macro_editor(self, macro):
        self.editing_macro = macro
        self.macro_name_field = TextField((260, 100, 320, 32), macro["name"])
        self.macro_button_field = NumberField((260, 142, 140, 32), macro.get("trigger_button", 0),
                                              step=1, min_value=0, max_value=32)
        self.macro_mode_hold = macro.get("mode", "on_press") == "hold"
        self.btn_toggle_mode = Button((260, 184, 200, 32), "", self._toggle_macro_mode)

        self._rebuild_macro_step_widgets()

        self.btn_add_step = Button((260, 230, 160, 32), "+ Add step", self._add_macro_step,
                                    color=(40, 70, 90))
        self.btn_save_macro = Button((260, 560, 160, 40), "Save", self._save_macro_editor,
                                      color=(40, 90, 40))
        self.btn_cancel_macro = Button((440, 560, 160, 40), "Cancel",
                                        lambda: self._go_to("macros"), color=(90, 40, 40))
        self.screen_name = "macro_edit"

    def _toggle_macro_mode(self):
        self.macro_mode_hold = not self.macro_mode_hold

    def _rebuild_macro_step_widgets(self):
        self.step_widgets = []
        y = 270
        for i, step in enumerate(self.editing_macro["steps"]):
            motor_btn = Button((260, y, 90, 30), step.get("motor", "BOTH"),
                                callback=lambda i=i: self._cycle_step_motor(i), color=(60, 60, 90))
            speed_field = NumberField((360, y, 140, 30), int(step.get("speed", 0)), step=10)
            dur_field = NumberField((510, y, 140, 30), int(step.get("duration_ms", 0)), step=100,
                                    min_value=0, max_value=60000)
            remove_btn = Button((660, y, 40, 30), "X", callback=lambda i=i: self._remove_step(i),
                                 color=(90, 40, 40))
            self.step_widgets.append({
                "motor_btn": motor_btn, "speed_field": speed_field,
                "dur_field": dur_field, "remove_btn": remove_btn,
            })
            y += 38

    def _cycle_step_motor(self, i):
        order = ["L", "R", "BOTH"]
        cur = self.editing_macro["steps"][i].get("motor", "BOTH")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "L"
        self.editing_macro["steps"][i]["motor"] = nxt
        self._rebuild_macro_step_widgets()

    def _add_macro_step(self):
        self.editing_macro["steps"].append({"motor": "BOTH", "speed": 150, "duration_ms": 500})
        self._rebuild_macro_step_widgets()

    def _remove_step(self, i):
        del self.editing_macro["steps"][i]
        self._rebuild_macro_step_widgets()

    def _save_macro_editor(self):
        m = self.editing_macro
        m["name"] = self.macro_name_field.value.strip() or m["name"]
        m["trigger_button"] = self.macro_button_field.value
        m["mode"] = "hold" if self.macro_mode_hold else "on_press"
        steps = []
        for i, sw in enumerate(self.step_widgets):
            steps.append({
                "motor": self.editing_macro["steps"][i]["motor"],
                "speed": sw["speed_field"].value,
                "duration_ms": sw["dur_field"].value,
            })
        m["steps"] = steps
        self.macro_mgr.add_or_update(m)
        self._go_to("macros")

    # ---------- controller test screen ----------

    def _build_test_screen_widgets(self):
        d = self.controller_map.data
        y0 = 110
        self.test_fields = {}
        labels = [
            ("axis_left_x", "Left X axis"), ("axis_left_y", "Left Y axis"),
            ("axis_right_x", "Right X axis"), ("axis_right_y", "Right Y axis"),
            ("axis_left_trigger", "Left trigger axis"), ("axis_right_trigger", "Right trigger axis"),
        ]
        y = y0
        for key, _label in labels:
            field = NumberField((250, y, 120, 30), d.get(key) or 0, step=1, min_value=0, max_value=15)
            self.test_fields[key] = field
            y += 42

        self.btn_invert_left = Button((250, y, 220, 30), "", self._toggle_invert_left, color=(60, 60, 90))
        y += 42
        self.btn_invert_right = Button((250, y, 220, 30), "", self._toggle_invert_right, color=(60, 60, 90))
        y += 42
        self.deadzone_field = NumberField((250, y, 120, 30), int(d.get("deadzone", 0.1) * 100),
                                          step=1, min_value=0, max_value=90)
        self.btn_save_map = Button((250, y + 50, 200, 36), "Save mapping", self._save_controller_map,
                                    color=(40, 90, 40))

    def _toggle_invert_left(self):
        self.controller_map.data["invert_left_y"] = not self.controller_map.data.get("invert_left_y", False)

    def _toggle_invert_right(self):
        self.controller_map.data["invert_right_y"] = not self.controller_map.data.get("invert_right_y", False)

    def _save_controller_map(self):
        d = self.controller_map.data
        for key, field in self.test_fields.items():
            d[key] = field.value
        d["deadzone"] = self.deadzone_field.value / 100.0
        self.controller_map.save()

    # ---------- main loop ----------

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                self._handle_event(event)

            self._update(dt)
            self._draw()
            pygame.display.flip()

        self.link.stop()
        pygame.quit()

    def _handle_event(self, event):
        for btn in self.top_buttons:
            btn.handle_event(event)
        self.btn_reload_joystick.handle_event(event)

        if self.screen_name == "presets":
            self.preset_list.handle_event(event)
            self.btn_activate_preset.handle_event(event)
            self.btn_edit_preset.handle_event(event)
            self.btn_new_preset.handle_event(event)
            self.btn_delete_preset.handle_event(event)

        elif self.screen_name == "preset_edit":
            self.preset_name_field.handle_event(event)
            self.preset_desc_field.handle_event(event)
            self.btn_add_mapping.handle_event(event)
            self.btn_save_preset.handle_event(event)
            self.btn_cancel_preset.handle_event(event)
            for mw in self.mapping_widgets:
                mw["input_btn"].handle_event(event)
                mw["target_btn"].handle_event(event)
                mw["in_min"].handle_event(event)
                mw["in_max"].handle_event(event)
                mw["out_min"].handle_event(event)
                mw["out_max"].handle_event(event)
                mw["remove_btn"].handle_event(event)

        elif self.screen_name == "macros":
            self.macro_list.handle_event(event)
            self.btn_edit_macro.handle_event(event)
            self.btn_new_macro.handle_event(event)
            self.btn_delete_macro.handle_event(event)

        elif self.screen_name == "macro_edit":
            self.macro_name_field.handle_event(event)
            self.macro_button_field.handle_event(event)
            self.btn_toggle_mode.handle_event(event)
            self.btn_add_step.handle_event(event)
            self.btn_save_macro.handle_event(event)
            self.btn_cancel_macro.handle_event(event)
            for sw in self.step_widgets:
                sw["motor_btn"].handle_event(event)
                sw["speed_field"].handle_event(event)
                sw["dur_field"].handle_event(event)
                sw["remove_btn"].handle_event(event)

        elif self.screen_name == "test":
            for field in self.test_fields.values():
                field.handle_event(event)
            self.btn_invert_left.handle_event(event)
            self.btn_invert_right.handle_event(event)
            self.deadzone_field.handle_event(event)
            self.btn_save_map.handle_event(event)

    def _update(self, dt):
        if self.joystick is None:
            return

        axes, triggers, buttons = self.controller_map.read(self.joystick)

        # macros take priority (override); if no override is active, send the preset's output
        self.macro_mgr.process_buttons(buttons)
        if not self.link.is_override_active():
            left, right = self.preset_mgr.compute(axes, triggers)
            self.link.set_speeds(left, right)

        # update the position estimate for the silhouette (uses whatever is
        # actually being sent, preset or macro)
        cmd_l = self.link._override_l if self.link.is_override_active() else self.link._desired_l
        cmd_r = self.link._override_r if self.link.is_override_active() else self.link._desired_r
        self.estimator.update(cmd_l, cmd_r, dt)

    def _draw(self):
        self.screen.fill((10, 10, 14))
        for btn in self.top_buttons:
            btn.draw(self.screen)
        self.btn_reload_joystick.draw(self.screen)

        if self.screen_name == "control":
            self._draw_control_screen()
        elif self.screen_name == "presets":
            self._draw_presets_screen()
        elif self.screen_name == "preset_edit":
            self._draw_preset_edit_screen()
        elif self.screen_name == "macros":
            self._draw_macros_screen()
        elif self.screen_name == "macro_edit":
            self._draw_macro_edit_screen()
        elif self.screen_name == "test":
            self._draw_test_screen()

    def _draw_control_screen(self):
        font = get_font(20, bold=True)
        font_small = get_font(16)

        joy_status = "Controller: NOT CONNECTED" if self.joystick is None else f"Controller: {self.joystick.get_name()}"
        self.screen.blit(font_small.render(joy_status, True, (200, 200, 100)), (30, 60))

        active = self.preset_mgr.get_active()
        preset_name = active["name"] if active else "(none)"
        self.screen.blit(font.render(f"Active preset: {preset_name}", True, (230, 230, 230)), (30, 85))

        macro_status = "Macro running" if self.macro_mgr.is_running() else "No macro active"
        color = (230, 180, 60) if self.macro_mgr.is_running() else (140, 140, 140)
        self.screen.blit(font_small.render(macro_status, True, color), (30, 118))

        silhouette_rect = pygame.Rect(30, 150, 440, 420)
        # use the commands actually being sent (more responsive than waiting for telemetry)
        l = self.link._override_l if self.link.is_override_active() else self.link._desired_l
        r = self.link._override_r if self.link.is_override_active() else self.link._desired_r
        render.draw_silhouette(self.screen, silhouette_rect, l, r)

        telem_rect = pygame.Rect(500, 150, 470, 200)
        stale = self.link.telemetry.is_stale(self.settings.get("telemetry_timeout_s", 2.0))
        render.draw_telemetry_panel(self.screen, telem_rect, self.link.telemetry, stale)

        info_rect = pygame.Rect(500, 360, 470, 210)
        pygame.draw.rect(self.screen, (18, 18, 22), info_rect, border_radius=8)
        pygame.draw.rect(self.screen, (60, 60, 70), info_rect, 1, border_radius=8)
        lines = [
            f"Robot IP: {self.settings['robot_ip']}:{self.settings['robot_port']}",
            "Use the 'Presets' tab to change the control scheme.",
            "Use the 'Macros' tab to create automatic sequences",
            "assigned to controller buttons.",
            "Use 'Controller test' if the axes don't respond as expected.",
        ]
        y = info_rect.y + 14
        for line in lines:
            self.screen.blit(get_font(16).render(line, True, (200, 200, 200)), (info_rect.x + 12, y))
            y += 24

    def _draw_presets_screen(self):
        self.screen.blit(get_font(22, bold=True).render("Control presets", True, (230, 230, 230)), (30, 65))
        self.preset_list.draw(self.screen)
        self.btn_activate_preset.draw(self.screen)
        self.btn_edit_preset.draw(self.screen)
        self.btn_new_preset.draw(self.screen)
        self.btn_delete_preset.draw(self.screen)

        active = self.preset_mgr.get_active()
        if active:
            desc = active.get("description", "")
            self.screen.blit(get_font(16).render(f"Active: {active['name']}", True, (140, 220, 140)), (430, 290))
            words = desc.split(" ")
            line = ""
            y = 320
            for w in words:
                if len(line) + len(w) > 40:
                    self.screen.blit(get_font(15).render(line, True, (190, 190, 190)), (430, y))
                    y += 20
                    line = ""
                line += w + " "
            if line:
                self.screen.blit(get_font(15).render(line, True, (190, 190, 190)), (430, y))

    def _draw_preset_edit_screen(self):
        self.screen.blit(get_font(22, bold=True).render("Edit preset", True, (230, 230, 230)), (30, 65))
        self.screen.blit(get_font(16).render("Name:", True, (200, 200, 200)), (30, 102))
        self.preset_name_field.draw(self.screen)
        self.screen.blit(get_font(16).render("Description:", True, (200, 200, 200)), (30, 142))
        self.preset_desc_field.draw(self.screen)

        self.screen.blit(get_font(16, bold=True).render(
            "Mappings (click Input/Target to cycle through options):",
            True, (200, 200, 200)), (30, 218))
        headers = ["Input", "Target", "In min", "In max", "Out min", "Out max", ""]
        header_x = [30, 230, 320, 440, 560, 690, 820]
        for h, hx in zip(headers, header_x):
            self.screen.blit(get_font(13).render(h, True, (150, 150, 160)), (hx, 232))

        for mw in self.mapping_widgets:
            mw["input_btn"].draw(self.screen)
            mw["target_btn"].draw(self.screen)
            mw["in_min"].draw(self.screen)
            mw["in_max"].draw(self.screen)
            mw["out_min"].draw(self.screen)
            mw["out_max"].draw(self.screen)
            mw["remove_btn"].draw(self.screen)

        self.btn_add_mapping.draw(self.screen)

        hint = "Example: 'Left stick Y' -100..100 -> Out -255..255 on target 'L' drives the left motor with that stick."
        self.screen.blit(get_font(14).render(hint, True, (150, 150, 150)), (30, 575))
        hint2 = "Several mappings can target the same motor; their outputs are added together and clamped to -255..255."
        self.screen.blit(get_font(14).render(hint2, True, (150, 150, 150)), (30, 592))

        self.btn_save_preset.draw(self.screen)
        self.btn_cancel_preset.draw(self.screen)

    def _draw_macros_screen(self):
        self.screen.blit(get_font(22, bold=True).render("Macros / Autonomous sequences", True, (230, 230, 230)),
                          (30, 65))
        self.macro_list.draw(self.screen)
        self.btn_edit_macro.draw(self.screen)
        self.btn_new_macro.draw(self.screen)
        self.btn_delete_macro.draw(self.screen)
        hint = "Each macro fires on a controller button (index shown in parentheses)."
        self.screen.blit(get_font(15).render(hint, True, (170, 170, 170)), (430, 300))

    def _draw_macro_edit_screen(self):
        self.screen.blit(get_font(22, bold=True).render("Edit macro", True, (230, 230, 230)), (30, 65))
        self.screen.blit(get_font(16).render("Name:", True, (200, 200, 200)), (30, 106))
        self.macro_name_field.draw(self.screen)
        self.screen.blit(get_font(16).render("Trigger button:", True, (200, 200, 200)), (30, 148))
        self.macro_button_field.draw(self.screen)
        self.btn_toggle_mode.label = "Mode: hold" if self.macro_mode_hold else "Mode: single trigger"
        self.btn_toggle_mode.draw(self.screen)

        self.screen.blit(get_font(16).render("Steps (motor / speed / duration ms):",
                                              True, (200, 200, 200)), (30, 250))
        for sw in self.step_widgets:
            sw["motor_btn"].draw(self.screen)
            sw["speed_field"].draw(self.screen)
            sw["dur_field"].draw(self.screen)
            sw["remove_btn"].draw(self.screen)
        self.btn_add_step.draw(self.screen)
        self.btn_save_macro.draw(self.screen)
        self.btn_cancel_macro.draw(self.screen)

    def _draw_test_screen(self):
        self.screen.blit(get_font(22, bold=True).render("Controller test / axis mapping",
                                                          True, (230, 230, 230)), (30, 65))
        labels = ["Left X axis", "Left Y axis", "Right X axis", "Right Y axis",
                  "Left trigger axis", "Right trigger axis"]
        keys = ["axis_left_x", "axis_left_y", "axis_right_x", "axis_right_y",
                "axis_left_trigger", "axis_right_trigger"]
        y = 110
        for label, key in zip(labels, keys):
            self.screen.blit(get_font(16).render(label + ":", True, (200, 200, 200)), (30, y + 6))
            self.test_fields[key].draw(self.screen)
            y += 42

        self.btn_invert_left.label = f"Invert Left Y: {'YES' if self.controller_map.data.get('invert_left_y') else 'NO'}"
        self.btn_invert_left.draw(self.screen)
        y += 42
        self.btn_invert_right.label = f"Invert Right Y: {'YES' if self.controller_map.data.get('invert_right_y') else 'NO'}"
        self.btn_invert_right.draw(self.screen)
        y += 42
        self.screen.blit(get_font(16).render("Deadzone (%):", True, (200, 200, 200)), (30, y + 6))
        self.deadzone_field.draw(self.screen)
        y += 42
        self.btn_save_map.draw(self.screen)

        # live values
        live_x = 500
        self.screen.blit(get_font(18, bold=True).render("Live values:", True, (230, 230, 230)),
                          (live_x, 110))
        if self.joystick is None:
            self.screen.blit(get_font(16).render("No controller connected", True, (220, 100, 100)),
                              (live_x, 140))
        else:
            ty = 140
            for i in range(self.joystick.get_numaxes()):
                val = self.joystick.get_axis(i)
                self.screen.blit(get_font(15).render(f"Axis {i}: {val:+.2f}", True, (200, 220, 200)),
                                  (live_x, ty))
                ty += 20
            ty += 10
            self.screen.blit(get_font(16, bold=True).render("Buttons pressed:", True, (230, 230, 230)),
                              (live_x, ty))
            ty += 24
            pressed = [str(i) for i in range(self.joystick.get_numbuttons()) if self.joystick.get_button(i)]
            self.screen.blit(get_font(15).render(", ".join(pressed) if pressed else "(none)",
                                                  True, (200, 220, 200)), (live_x, ty))


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()
