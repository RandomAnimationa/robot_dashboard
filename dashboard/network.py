"""
UDP communication with the robot (ESP32).

- Sends speed commands "L:<int>,R:<int>\n" at a fixed rate (control_rate_hz).
- Receives telemetry "T:up=...,rssi=...,l=...,r=...,batt=...,clients=...\n" in a
  separate thread and exposes it via `RobotLink.telemetry` (thread-safe).
- Supports a temporary "override" (used by the macro system) that replaces,
  while active, whatever values normal control would send.
"""

import socket
import threading
import time


class Telemetry:
    def __init__(self):
        self.uptime_ms = 0
        self.rssi = 0
        self.left = 0
        self.right = 0
        self.battery = 0.0
        self.clients = 0
        self.last_update = 0.0

    def is_stale(self, timeout_s):
        return (time.time() - self.last_update) > timeout_s

    def as_dict(self):
        return {
            "uptime_ms": self.uptime_ms,
            "rssi": self.rssi,
            "left": self.left,
            "right": self.right,
            "battery": self.battery,
            "clients": self.clients,
        }


class RobotLink:
    def __init__(self, robot_ip, robot_port, local_listen_port=0, control_rate_hz=20):
        self.robot_addr = (robot_ip, robot_port)
        self.control_period = 1.0 / max(1, control_rate_hz)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", local_listen_port))
        self.sock.settimeout(0.5)

        self.telemetry = Telemetry()

        self._lock = threading.Lock()
        self._desired_l = 0
        self._desired_r = 0

        self._override_active = False
        self._override_l = 0
        self._override_r = 0

        self._running = False
        self._send_thread = None
        self._recv_thread = None

    # ---------- public API ----------

    def start(self):
        self._running = True
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._send_thread.start()
        self._recv_thread.start()

    def stop(self):
        self._running = False
        self.set_speeds(0, 0)
        time.sleep(0.1)
        try:
            self.sock.close()
        except OSError:
            pass

    def set_speeds(self, left, right):
        """Desired speeds from normal control (joystick/presets)."""
        with self._lock:
            self._desired_l = int(max(-255, min(255, left)))
            self._desired_r = int(max(-255, min(255, right)))

    def set_override(self, left, right):
        """Used by macros: forces speeds while the override is active."""
        with self._lock:
            self._override_active = True
            self._override_l = int(max(-255, min(255, left)))
            self._override_r = int(max(-255, min(255, right)))

    def clear_override(self):
        with self._lock:
            self._override_active = False

    def is_override_active(self):
        with self._lock:
            return self._override_active

    # ---------- internal ----------

    def _current_command(self):
        with self._lock:
            if self._override_active:
                return self._override_l, self._override_r
            return self._desired_l, self._desired_r

    def _send_loop(self):
        while self._running:
            l, r = self._current_command()
            msg = f"L:{l},R:{r}\n".encode("ascii")
            try:
                self.sock.sendto(msg, self.robot_addr)
            except OSError:
                pass
            time.sleep(self.control_period)

    def _recv_loop(self):
        while self._running:
            try:
                data, _addr = self.sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            self._parse_telemetry(data)

    def _parse_telemetry(self, data):
        try:
            text = data.decode("ascii", errors="ignore").strip()
        except UnicodeDecodeError:
            return
        if not text.startswith("T:"):
            return
        fields = text[2:].split(",")
        parsed = {}
        for f in fields:
            if "=" not in f:
                continue
            k, v = f.split("=", 1)
            parsed[k] = v
        try:
            t = self.telemetry
            t.uptime_ms = int(parsed.get("up", t.uptime_ms))
            t.rssi = int(parsed.get("rssi", t.rssi))
            t.left = int(parsed.get("l", t.left))
            t.right = int(parsed.get("r", t.right))
            t.battery = float(parsed.get("batt", t.battery))
            t.clients = int(parsed.get("clients", t.clients))
            t.last_update = time.time()
        except ValueError:
            pass
