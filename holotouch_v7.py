from pathlib import Path
from math import acos, degrees, sqrt
from collections import deque
from statistics import median
import ctypes
import json
import os
import psutil
import queue
import sys
import threading
import time

import cv2
import mediapipe as mp
import serial
from serial.tools import list_ports


FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
USER_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "hand_landmarker.task"
CONFIG_PATH = USER_DIR / "config.json"


DEFAULT_CONFIG = {
    "camera_index": 0,
    "serial_port": "AUTO",
    "serial_baud": 115200,
    "mirror_camera": True,
    "swap_handedness": False,
    "cursor_hand": "Left",
    "action_hand": "Right",
    "single_hand_fallback": True,
    "calibration_blocks_control": False,

    "mouse_gain": 2.25,
    "precision_gain": 0.55,
    "dead_zone_px": 1.4,
    "max_move": 62,
    "cursor_smoothing_still": 0.82,
    "cursor_smoothing_fast": 0.34,
    "cursor_speed_reference": 28.0,
    "max_camera_jump_px": 90.0,

    "click_cooldown": 0.34,
    "drag_hold_seconds": 0.52,
    "pinch_press_ratio": 0.32,
    "pinch_release_ratio": 0.40,
    "pinch_exclusive_margin": 0.045,
    "precision_ring_ratio": 0.33,

    "scroll_gain": 0.12,
    "scroll_max_step": 6,

    "swipe_min_px": 78,
    "swipe_min_speed": 155.0,
    "swipe_direction_ratio": 1.35,
    "swipe_cooldown": 0.72,

    "three_hold_seconds": 0.52,
    "radial_hold_seconds": 0.70,
    "radial_select_radius_px": 92,
    "radial_select_hold_seconds": 0.28,
    "both_palms_lock_seconds": 0.90,
    "fist_hold_seconds": 0.35,
    "zoom_step_px": 34,
    "lost_hand_grace_frames": 3,
    "calibration_seconds": 2.2,

    "auto_profiles": True,
    "show_skeleton": True,
    "show_debug": False,

    "app_profiles": {
        "chrome.exe": "BROWSER",
        "msedge.exe": "BROWSER",
        "firefox.exe": "BROWSER",
        "powerpnt.exe": "PRESENT",
        "spotify.exe": "MEDIA",
        "vlc.exe": "MEDIA",
        "code.exe": "EDIT"
    },

    "profiles": {
        "MOUSE": {
            "primary": "CLICK", "secondary": "RIGHTCLICK", "three": "ALT_TAB",
            "swipe_left": "BACK", "swipe_right": "FORWARD",
            "swipe_up": "PAGE_UP", "swipe_down": "PAGE_DOWN"
        },
        "BROWSER": {
            "primary": "CLICK", "secondary": "RIGHTCLICK", "three": "ALT_TAB",
            "swipe_left": "BACK", "swipe_right": "FORWARD",
            "swipe_up": "PAGE_UP", "swipe_down": "PAGE_DOWN"
        },
        "MEDIA": {
            "primary": "PLAY_PAUSE", "secondary": "MUTE", "three": "FULLSCREEN",
            "swipe_left": "PREV_TRACK", "swipe_right": "NEXT_TRACK",
            "swipe_up": "VOL_UP", "swipe_down": "VOL_DOWN"
        },
        "PRESENT": {
            "primary": "RIGHT", "secondary": "LEFT", "three": "F5",
            "swipe_left": "LEFT", "swipe_right": "RIGHT",
            "swipe_up": "PAGE_UP", "swipe_down": "PAGE_DOWN"
        },
        "NAV": {
            "primary": "ENTER", "secondary": "ESC", "three": "WIN_TAB",
            "swipe_left": "LEFT", "swipe_right": "RIGHT",
            "swipe_up": "UP", "swipe_down": "DOWN"
        },
        "EDIT": {
            "primary": "CLICK", "secondary": "RIGHTCLICK", "three": "ALT_TAB",
            "swipe_left": "UNDO", "swipe_right": "REDO",
            "swipe_up": "PAGE_UP", "swipe_down": "PAGE_DOWN"
        }
    },

    "radial_menu": {
        "MOUSE": {"left": "COPY", "right": "PASTE", "up": "ALT_TAB", "down": "WIN_D"},
        "BROWSER": {"left": "BACK", "right": "FORWARD", "up": "NEW_TAB", "down": "CLOSE_TAB"},
        "MEDIA": {"left": "PREV_TRACK", "right": "NEXT_TRACK", "up": "VOL_UP", "down": "VOL_DOWN"},
        "PRESENT": {"left": "LEFT", "right": "RIGHT", "up": "F5", "down": "ESC"},
        "NAV": {"left": "BACK", "right": "FORWARD", "up": "WIN_TAB", "down": "WIN_D"},
        "EDIT": {"left": "UNDO", "right": "REDO", "up": "COPY", "down": "PASTE"}
    }
}


def deep_merge(base, incoming):
    out = dict(base)
    for k, v in incoming.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg = deep_merge(DEFAULT_CONFIG, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as exc:
            print("Aviso config:", exc)
    else:
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


CFG = load_config()

FINGER_DEFINITIONS = (
    ("Pulgar", 2, 3, 4, 4),
    ("Indice", 5, 6, 7, 8),
    ("Medio", 9, 10, 11, 12),
    ("Anular", 13, 14, 15, 16),
    ("Menique", 17, 18, 19, 20),
)

HAND_CONNECTIONS = mp.tasks.vision.HandLandmarksConnections.HAND_CONNECTIONS


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def dist3(a, b):
    return sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)


def dist2(a, b):
    return sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def joint_angle(first, vertex, last):
    a = (first.x-vertex.x, first.y-vertex.y, first.z-vertex.z)
    b = (last.x-vertex.x, last.y-vertex.y, last.z-vertex.z)
    dot = sum(x*y for x, y in zip(a, b))
    mag = sqrt(sum(x*x for x in a) * sum(y*y for y in b))
    if mag == 0:
        return 0.0
    return degrees(acos(max(-1.0, min(1.0, dot / mag))))


def classify_fingers(world):
    palm_width = max(dist3(world[5], world[17]), 1e-6)
    states = {}
    for name, base, middle, end, tip in FINGER_DEFINITIONS:
        first_angle = joint_angle(world[base], world[middle], world[end])
        if name == "Pulgar":
            states[name] = first_angle >= 138 and dist3(world[tip], world[5]) >= palm_width * 0.36
        else:
            second_angle = joint_angle(world[middle], world[end], world[tip])
            threshold = 130 if name == "Indice" else 138
            states[name] = first_angle >= threshold and second_angle >= threshold
    return states


def four_open(f):
    return all(f[n] for n in ("Indice", "Medio", "Anular", "Menique"))


def is_fist(f):
    return not any(f[n] for n in ("Indice", "Medio", "Anular", "Menique"))


def three_fingers(f):
    return f["Indice"] and f["Medio"] and f["Anular"] and not f["Menique"]


def cursor_pose(f):
    return f["Indice"] and not f["Medio"] and not f["Anular"] and not f["Menique"]


def scroll_pose(f):
    return f["Indice"] and f["Medio"] and not f["Anular"] and not f["Menique"]


class Esp32USB:
    def __init__(self, preferred="AUTO", baud=115200):
        self.preferred = str(preferred or "AUTO")
        self.baud = int(baud)
        self.ser = None
        self.port = None
        self.mode = "MOUSE"
        self.locked = False
        self.last_action = "-"
        self.last_seen = 0.0
        self.events = queue.Queue()
        self._stop = threading.Event()
        self._reader = None
        self._write_lock = threading.Lock()

    def _candidate_ports(self):
        ports = [p.device for p in list_ports.comports()]
        if self.preferred.upper() != "AUTO":
            return [self.preferred] + [p for p in ports if p != self.preferred]
        return ports

    def connect(self):
        self.close()
        for port in self._candidate_ports():
            s = None
            try:
                s = serial.Serial(port, self.baud, timeout=0.12, write_timeout=0.22)
                time.sleep(0.85)
                s.reset_input_buffer()
                deadline = time.monotonic() + 2.4
                found = None
                next_hello = 0.0
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_hello:
                        s.write(b"HELLO\n")
                        s.flush()
                        next_hello = time.monotonic() + 0.45
                    line = s.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("HOLOTOUCH_USB,V7,"):
                        found = line
                        break
                if not found:
                    s.close()
                    continue

                self.ser = s
                self.port = port
                self._parse(found)
                self._stop.clear()
                self._reader = threading.Thread(target=self._reader_loop, daemon=True)
                self._reader.start()
                print("HOLOTOUCH V7 conectado en", port)
                return True
            except (serial.SerialException, OSError):
                try:
                    if s:
                        s.close()
                except Exception:
                    pass
        return False

    def _parse(self, line):
        if line.startswith("HOLOTOUCH_USB,V7,"):
            parts = line.split(",")
            if len(parts) >= 4:
                self.mode = parts[2]
                self.locked = parts[3] == "1"
            self.last_seen = time.monotonic()
        elif line.startswith("STATUS,"):
            parts = line.split(",")
            if len(parts) >= 3:
                self.mode = parts[1]
                self.locked = parts[2] == "1"
            if len(parts) >= 4:
                self.last_action = parts[3]
            self.last_seen = time.monotonic()
        elif line.startswith("EVENT,"):
            self.events.put(line[6:].strip())
            self.last_seen = time.monotonic()
        elif line == "PONG":
            self.last_seen = time.monotonic()

    def _reader_loop(self):
        while not self._stop.is_set() and self.ser:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self._parse(line)
            except (serial.SerialException, OSError):
                try:
                    if self.ser:
                        self.ser.close()
                except Exception:
                    pass
                self.ser = None
                self.port = None
                break

    def send(self, command):
        if not self.ser or not self.ser.is_open:
            return False
        try:
            with self._write_lock:
                self.ser.write((command + "\n").encode("ascii", errors="ignore"))
            return True
        except (serial.SerialException, OSError):
            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
            self.port = None
            return False

    def pop_events(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        self._stop.set()
        s = self.ser
        self.ser = None
        if s:
            try:
                s.close()
            except Exception:
                pass
        self.port = None


def foreground_process():
    if os.name != "nt":
        return ""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def app_profile(process_name, manual_mode, auto_enabled):
    if auto_enabled:
        hit = CFG.get("app_profiles", {}).get(process_name.lower())
        if hit:
            return str(hit).upper()
    return manual_mode.upper()


# ---------- UI ----------

ACCENT = (90, 230, 180)
ACCENT2 = (255, 190, 80)
WHITE = (242, 247, 250)
MUTED = (160, 175, 188)
DARK = (12, 17, 23)
DANGER = (90, 90, 255)


def panel(frame, p1, p2, color=DARK, alpha=0.78):
    over = frame.copy()
    cv2.rectangle(over, p1, p2, color, -1, cv2.LINE_AA)
    cv2.addWeighted(over, alpha, frame, 1-alpha, 0, frame)


def txt(frame, s, xy, scale=0.5, color=WHITE, thick=1):
    cv2.putText(frame, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, (0,0,0), thick+2, cv2.LINE_AA)
    cv2.putText(frame, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def chip(frame, s, x, y, color=ACCENT):
    (tw, _), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    panel(frame, (x, y-18), (x+tw+16, y+7), (20, 28, 34), 0.80)
    cv2.rectangle(frame, (x, y-18), (x+tw+16, y+7), color, 1, cv2.LINE_AA)
    txt(frame, s, (x+8, y), 0.45, color)


def ring(frame, center, progress, color=ACCENT, radius=28):
    progress = clamp(progress, 0.0, 1.0)
    cv2.circle(frame, center, radius, (70,80,90), 2, cv2.LINE_AA)
    cv2.ellipse(frame, center, (radius, radius), -90, 0, progress*360, color, 3, cv2.LINE_AA)


def draw_hand(frame, hand, role):
    pts = hand["points"]
    if CFG.get("show_skeleton", True):
        for c in HAND_CONNECTIONS:
            cv2.line(frame, pts[c.start], pts[c.end], (70,185,155), 1, cv2.LINE_AA)
        for i, p in enumerate(pts):
            cv2.circle(frame, p, 4 if i in (4,8,12,16,20) else 2, WHITE, -1, cv2.LINE_AA)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x1, y1, x2, y2 = max(0,min(xs)-10), max(0,min(ys)-10), max(xs)+10, max(ys)+10
    col = ACCENT if role == "CURSOR" else ACCENT2
    cv2.rectangle(frame, (x1,y1), (x2,y2), col, 1, cv2.LINE_AA)
    chip(frame, f"{role} {hand['label'][0]}", x1, max(22, y1-4), col)


def draw_radial(frame, center, items, selected, progress):
    cx, cy = center
    over = frame.copy()
    cv2.circle(over, center, 116, (8,13,18), -1, cv2.LINE_AA)
    cv2.addWeighted(over, 0.76, frame, 0.24, 0, frame)

    positions = {
        "up": (cx, cy-80),
        "down": (cx, cy+80),
        "left": (cx-88, cy),
        "right": (cx+88, cy),
    }
    for direction, pos in positions.items():
        label = items.get(direction, "-").replace("_"," ")[:10]
        col = ACCENT if selected == direction else WHITE
        cv2.circle(frame, pos, 27, (24,31,38), -1, cv2.LINE_AA)
        cv2.circle(frame, pos, 27, col, 2 if selected == direction else 1, cv2.LINE_AA)
        (tw,_), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.34, 1)
        txt(frame, label, (pos[0]-tw//2, pos[1]+4), 0.34, col)

    ring(frame, center, progress, ACCENT, 32)


def draw_help(frame, profile):
    h, w = frame.shape[:2]
    panel(frame, (40,40), (w-40,h-40), (7,11,16), 0.94)
    txt(frame, "HOLOTOUCH V7 PRO", (72,80), 0.78, ACCENT, 2)
    lines = [
        "CURSOR: indice mueve | indice+medio scroll | pulgar+anular precision",
        "ACCIONES: pinza indice principal/drag | pinza medio secundaria",
        "ACCIONES: 3 dedos especial | palma swipe | palma quieta radial",
        "PUNO en mano de acciones = fail-safe / cancelar",
        "DOS PINZAS = zoom | DOS PALMAS mantenidas = lock/unlock",
        "",
        f"Perfil: {profile}",
        "H ayuda | D debug | X cambia manos | C recalibra | A auto-app",
        "1 Mouse | 2 Media | 3 Present | 4 Nav | R reconectar | F fullscreen",
        "ESC / Q salir"
    ]
    y = 116
    for line in lines:
        txt(frame, line, (72,y), 0.46, WHITE if line else MUTED)
        y += 27


class Calibrator:
    def __init__(self, seconds):
        self.seconds = float(seconds)
        self.reset()

    def reset(self):
        self.started = None
        self.widths = []
        self.tip_steps = deque(maxlen=80)
        self.last_tip = None
        self.done = False
        self.palm_px = None
        self.jitter_px = None

    def update(self, hand, now):
        if self.done or hand is None:
            return
        if self.started is None:
            self.started = now
        self.widths.append(hand["palm_px"])
        tip = hand["points"][8]
        if self.last_tip is not None:
            self.tip_steps.append(dist2(tip, self.last_tip))
        self.last_tip = tip

        if now - self.started >= self.seconds and len(self.widths) >= 20:
            self.palm_px = float(median(self.widths))
            self.jitter_px = float(median(self.tip_steps)) if self.tip_steps else 1.0
            self.done = True

    def progress(self, now):
        if self.done:
            return 1.0
        if self.started is None:
            return 0.0
        return clamp((now-self.started)/self.seconds, 0.0, 1.0)


def handed_label(result, i):
    try:
        label = result.handedness[i][0].category_name
    except Exception:
        label = "Unknown"
    if CFG.get("swap_handedness", False):
        label = "Right" if label == "Left" else "Left" if label == "Right" else label
    return label


def build_hands(result, w, h):
    hands = {}
    if not result.hand_landmarks or not result.hand_world_landmarks:
        return hands

    for i, (landmarks, world) in enumerate(zip(result.hand_landmarks, result.hand_world_landmarks)):
        label = handed_label(result, i)
        points = [(int(lm.x*w), int(lm.y*h)) for lm in landmarks]
        fingers = classify_fingers(world)
        palm_norm = max(dist3(landmarks[5], landmarks[17]), 1e-6)
        palm_px = max(dist2(points[5], points[17]), 1.0)
        ratios = {
            "index": dist3(landmarks[4], landmarks[8]) / palm_norm,
            "middle": dist3(landmarks[4], landmarks[12]) / palm_norm,
            "ring": dist3(landmarks[4], landmarks[16]) / palm_norm,
        }
        center = (
            int(sum(points[j][0] for j in (0,5,9,13,17))/5),
            int(sum(points[j][1] for j in (0,5,9,13,17))/5),
        )
        score = 0.0
        try:
            score = float(result.handedness[i][0].score)
        except Exception:
            pass
        data = {
            "label": label, "score": score, "landmarks": landmarks, "world": world,
            "points": points, "fingers": fingers, "palm_px": palm_px,
            "ratios": ratios, "center": center,
        }
        if label not in hands or score > hands[label]["score"]:
            hands[label] = data

    return hands


class PinchLatch:
    def __init__(self):
        self.active = False

    def update(self, ratio, press, release):
        if self.active:
            if ratio >= release:
                self.active = False
        else:
            if ratio <= press:
                self.active = True
        return self.active

    def reset(self):
        self.active = False


class GestureEngine:
    def __init__(self, link):
        self.link = link

        self.cursor_label = str(CFG.get("cursor_hand", "Left")).title()
        self.action_label = str(CFG.get("action_hand", "Right")).title()

        self.auto_profiles = bool(CFG.get("auto_profiles", True))
        self.profile = "MOUSE"
        self.last_profile = None

        self.filtered_tip = None
        self.last_filtered_tip = None
        self.last_raw_tip = None
        self.scroll_prev_y = None
        self.scroll_accum = 0.0

        self.primary_latch = PinchLatch()
        self.secondary_latch = PinchLatch()
        self.primary_prev = False
        self.secondary_prev = False
        self.primary_started = None
        self.dragging = False
        self.last_primary_action = 0.0
        self.last_secondary_action = 0.0

        self.three_started = None
        self.three_fired = False

        self.swipe_start = None
        self.last_swipe = 0.0

        self.radial_open = False
        self.radial_center = None
        self.radial_selected = None
        self.radial_selected_at = None

        self.both_palms_started = None
        self.both_palms_fired = False

        self.zoom_active = False
        self.zoom_anchor = None
        self.zoom_suppress_until = 0.0

        self.safety_fist = False
        self.fist_started = None
        self.fist_fired = False
        self.lost_cursor = 0
        self.lost_action = 0

        self.gesture = "LISTO"
        self.gesture_progress = 0.0
        self.precision = False

        self.calibrator = Calibrator(CFG.get("calibration_seconds", 2.2))

    def role_code(self, label):
        return "L" if label == "Left" else "R"

    def sync_roles(self):
        self.link.send(
            f"ROLE,{self.role_code(self.cursor_label)},{self.role_code(self.action_label)}"
        )

    def swap_roles(self):
        self.cursor_label, self.action_label = self.action_label, self.cursor_label
        self.reset_transient()
        self.sync_roles()

    def reset_transient(self):
        if self.dragging:
            self.link.send("DRAG_END")

        self.filtered_tip = None
        self.last_filtered_tip = None
        self.last_raw_tip = None
        self.scroll_prev_y = None
        self.scroll_accum = 0.0

        self.primary_latch.reset()
        self.secondary_latch.reset()
        self.primary_prev = False
        self.secondary_prev = False
        self.primary_started = None
        self.dragging = False

        self.three_started = None
        self.three_fired = False

        self.swipe_start = None
        self.radial_open = False
        self.radial_center = None
        self.radial_selected = None
        self.radial_selected_at = None

        self.both_palms_started = None
        self.both_palms_fired = False

        self.zoom_active = False
        self.zoom_anchor = None

    def dispatch(self, key):
        mapping = CFG.get("profiles", {}).get(self.profile, {})
        action = mapping.get(key)
        if action:
            self.link.send(f"ACT,{action}")
            return action
        return None

    def dispatch_direct(self, action):
        if action:
            self.link.send(f"ACT,{action}")

    def update_profile(self):
        process = foreground_process()
        self.profile = app_profile(process, self.link.mode, self.auto_profiles)

        if self.profile != self.last_profile:
            self.last_profile = self.profile
            self.link.send(f"PROFILE,{self.profile}")

            # Evita que un gesto comenzado en una app se dispare al cambiar de app.
            self.primary_started = None
            self.three_started = None
            self.swipe_start = None
            self.radial_open = False

        return process

    def _update_cursor(self, cursor, cursor_idx_pinch):
        if cursor is None:
            return

        cf = cursor["fingers"]
        raw_tip = cursor["points"][8]

        # Si MediaPipe pega un salto grande, reancla en vez de mandar un tiron.
        if self.last_raw_tip is not None:
            if dist2(raw_tip, self.last_raw_tip) > float(CFG.get("max_camera_jump_px", 90)):
                self.filtered_tip = (float(raw_tip[0]), float(raw_tip[1]))
                self.last_filtered_tip = self.filtered_tip

        self.last_raw_tip = raw_tip

        ring_pinch = cursor["ratios"]["ring"] <= float(CFG.get("precision_ring_ratio", 0.33))
        self.precision = bool(ring_pinch and cf["Indice"])

        if self.filtered_tip is None:
            self.filtered_tip = (float(raw_tip[0]), float(raw_tip[1]))
        else:
            raw_speed = dist2(raw_tip, self.filtered_tip)
            ref = max(float(CFG.get("cursor_speed_reference", 28.0)), 1.0)
            t = clamp(raw_speed / ref, 0.0, 1.0)

            a_still = float(CFG.get("cursor_smoothing_still", 0.82))
            a_fast = float(CFG.get("cursor_smoothing_fast", 0.34))
            alpha = a_still + (a_fast - a_still) * t

            self.filtered_tip = (
                alpha*self.filtered_tip[0] + (1-alpha)*raw_tip[0],
                alpha*self.filtered_tip[1] + (1-alpha)*raw_tip[1],
            )

        if cursor_pose(cf) and not cursor_idx_pinch:
            self.gesture = "CURSOR PRECISION" if self.precision else "CURSOR"

            if self.last_filtered_tip is not None:
                dx_cam = self.filtered_tip[0] - self.last_filtered_tip[0]
                dy_cam = self.filtered_tip[1] - self.last_filtered_tip[1]

                speed = sqrt(dx_cam*dx_cam + dy_cam*dy_cam)
                accel = 1.0 + min(speed / 22.0, 0.95)

                gain = float(CFG.get("mouse_gain", 2.25))
                if self.precision:
                    gain *= float(CFG.get("precision_gain", 0.55))
                    accel = 1.0

                dx = int(dx_cam * gain * accel)
                dy = int(dy_cam * gain * accel)

                dynamic_dead = float(CFG.get("dead_zone_px", 1.4))
                if self.calibrator.jitter_px is not None:
                    dynamic_dead = max(
                        dynamic_dead,
                        min(self.calibrator.jitter_px * 0.45, 3.4)
                    )

                if abs(dx) < dynamic_dead:
                    dx = 0
                if abs(dy) < dynamic_dead:
                    dy = 0

                max_move = int(CFG.get("max_move", 62))
                dx = int(clamp(dx, -max_move, max_move))
                dy = int(clamp(dy, -max_move, max_move))

                if dx or dy:
                    self.link.send(f"MOVE,{dx},{dy}")

            self.last_filtered_tip = self.filtered_tip
            self.scroll_prev_y = None
            self.scroll_accum = 0.0

        elif scroll_pose(cf) and not cursor_idx_pinch:
            self.gesture = "SCROLL"
            midpoint_y = (cursor["points"][8][1] + cursor["points"][12][1]) / 2.0

            if self.scroll_prev_y is not None:
                self.scroll_accum += (
                    -(midpoint_y - self.scroll_prev_y)
                    * float(CFG.get("scroll_gain", 0.12))
                )
                wheel = int(self.scroll_accum)

                if wheel:
                    max_step = int(CFG.get("scroll_max_step", 6))
                    wheel = int(clamp(wheel, -max_step, max_step))
                    self.link.send(f"SCROLL,{wheel}")
                    self.scroll_accum -= wheel

            self.scroll_prev_y = midpoint_y
            self.last_filtered_tip = None

        else:
            self.last_filtered_tip = None
            self.scroll_prev_y = None

    def _update_action_hand(self, action, now):
        if action is None:
            return None

        af = action["fingers"]
        ratios = action["ratios"]

        press = float(CFG.get("pinch_press_ratio", 0.32))
        release = float(CFG.get("pinch_release_ratio", 0.40))
        margin = float(CFG.get("pinch_exclusive_margin", 0.045))

        p_index_raw = ratios["index"] <= press
        p_middle_raw = ratios["middle"] <= press
        ambiguous = (
            p_index_raw and p_middle_raw
            and abs(ratios["index"] - ratios["middle"]) < margin
        )

        if ambiguous and not self.primary_latch.active and not self.secondary_latch.active:
            primary = False
            secondary = False
        else:
            index_for_latch = ratios["index"]
            middle_for_latch = ratios["middle"]

            if p_index_raw and p_middle_raw:
                if ratios["index"] < ratios["middle"]:
                    middle_for_latch = release + 1.0
                else:
                    index_for_latch = release + 1.0

            primary = self.primary_latch.update(index_for_latch, press, release)
            secondary = self.secondary_latch.update(middle_for_latch, press, release)

        # Pinza principal: click al soltar / drag al mantener.
        if primary and not secondary:
            if not self.primary_prev:
                self.primary_started = now

            if self.profile in ("MOUSE", "BROWSER", "EDIT") and self.primary_started is not None:
                hold = float(CFG.get("drag_hold_seconds", 0.52))
                if not self.dragging and now - self.primary_started >= hold:
                    self.link.send("DRAG_START")
                    self.dragging = True

            self.gesture = "ARRASTRANDO" if self.dragging else "PINZA PRINCIPAL"

        else:
            if self.primary_prev:
                if self.dragging:
                    self.link.send("DRAG_END")
                    self.dragging = False
                else:
                    cooldown = float(CFG.get("click_cooldown", 0.34))
                    if now - self.last_primary_action >= cooldown:
                        self.dispatch("primary")
                        self.last_primary_action = now

            self.primary_started = None

        # Pinza secundaria solo en flanco.
        if secondary and not primary:
            self.gesture = "PINZA SECUNDARIA"
            if not self.secondary_prev:
                cooldown = float(CFG.get("click_cooldown", 0.34))
                if now - self.last_secondary_action >= cooldown:
                    self.dispatch("secondary")
                    self.last_secondary_action = now

        self.primary_prev = primary
        self.secondary_prev = secondary

        # Tres dedos con confirmacion temporal.
        three = three_fingers(af) and not primary and not secondary
        if three:
            if self.three_started is None:
                self.three_started = now
                self.three_fired = False

            hold = float(CFG.get("three_hold_seconds", 0.52))
            p = (now - self.three_started) / hold
            self.gesture = "3 DEDOS"
            self.gesture_progress = clamp(p, 0.0, 1.0)

            if not self.three_fired and p >= 1.0:
                self.dispatch("three")
                self.three_fired = True
        else:
            self.three_started = None
            self.three_fired = False

        # Palma: swipe si se desplaza; radial si se mantiene estable.
        open_palm = four_open(af) and not primary and not secondary
        radial_info = None

        if open_palm:
            center = action["center"]

            if self.radial_open:
                dx = center[0] - self.radial_center[0]
                dy = center[1] - self.radial_center[1]
                radius = sqrt(dx*dx + dy*dy)

                direction = None
                if radius >= float(CFG.get("radial_select_radius_px", 92)):
                    if abs(dx) > abs(dy):
                        direction = "right" if dx > 0 else "left"
                    else:
                        direction = "down" if dy > 0 else "up"

                if direction != self.radial_selected:
                    self.radial_selected = direction
                    self.radial_selected_at = now if direction else None

                select_progress = 0.0
                if direction and self.radial_selected_at:
                    select_hold = float(CFG.get("radial_select_hold_seconds", 0.28))
                    select_progress = (now - self.radial_selected_at) / select_hold

                    if select_progress >= 1.0:
                        items = CFG.get("radial_menu", {}).get(self.profile, {})
                        self.dispatch_direct(items.get(direction))
                        self.radial_open = False
                        self.radial_selected = None
                        self.radial_selected_at = None
                        self.swipe_start = None

                self.gesture = "MENU RADIAL"
                self.gesture_progress = clamp(select_progress, 0.0, 1.0)
                radial_info = {
                    "center": self.radial_center,
                    "items": CFG.get("radial_menu", {}).get(self.profile, {}),
                    "selected": self.radial_selected,
                    "progress": self.gesture_progress,
                }

            else:
                if self.swipe_start is None:
                    self.swipe_start = (center[0], center[1], now)
                else:
                    sx, sy, st = self.swipe_start
                    dx, dy = center[0]-sx, center[1]-sy
                    elapsed = max(now-st, 1e-4)
                    distance = sqrt(dx*dx + dy*dy)
                    speed = distance / elapsed

                    dynamic_swipe = float(CFG.get("swipe_min_px", 78))
                    if self.calibrator.palm_px:
                        dynamic_swipe = max(
                            dynamic_swipe,
                            self.calibrator.palm_px * 0.70
                        )

                    dir_ratio = float(CFG.get("swipe_direction_ratio", 1.35))
                    swipe_ok = (
                        distance >= dynamic_swipe
                        and speed >= float(CFG.get("swipe_min_speed", 155.0))
                        and now-self.last_swipe >= float(CFG.get("swipe_cooldown", 0.72))
                    )

                    if swipe_ok:
                        key = None
                        if abs(dx) >= abs(dy) * dir_ratio:
                            key = "swipe_right" if dx > 0 else "swipe_left"
                        elif abs(dy) >= abs(dx) * dir_ratio:
                            key = "swipe_down" if dy > 0 else "swipe_up"

                        if key:
                            self.dispatch(key)
                            self.last_swipe = now
                            self.swipe_start = None
                            self.gesture = key.replace("_", " ").upper()

                    if self.swipe_start is not None:
                        hold = float(CFG.get("radial_hold_seconds", 0.70))
                        stable_radius = min(dynamic_swipe * 0.42, 42.0)

                        if elapsed >= hold and distance <= stable_radius:
                            self.radial_open = True
                            self.radial_center = center
                            self.radial_selected = None
                            self.radial_selected_at = None
                            self.gesture = "MENU RADIAL"

                        elif elapsed > 1.35:
                            self.swipe_start = (center[0], center[1], now)

                if not self.radial_open and self.gesture == "MANOS LISTAS":
                    self.gesture = "PALMA"

        else:
            if self.radial_open:
                self.radial_open = False
                self.radial_selected = None
                self.radial_selected_at = None
            self.swipe_start = None

        return radial_info

    def update(self, hands, now):
        configured_cursor = hands.get(self.cursor_label)
        configured_action = hands.get(self.action_label)

        cursor = configured_cursor
        action = configured_action
        single_hand = False

        # HOTFIX V7.1:
        # Si solo hay una mano visible, esa mano puede hacer cursor + acciones.
        # Esto evita que HOLOTOUCH quede muerto si MediaPipe etiqueta la mano
        # distinta a la configurada o si el usuario quiere probar con una mano.
        visible = list(hands.values())
        if CFG.get("single_hand_fallback", True) and len(visible) == 1:
            cursor = visible[0]
            action = visible[0]
            single_hand = True

        self.gesture = "MANOS LISTAS"
        self.gesture_progress = 0.0

        # Calibracion en segundo plano. En V7 original esto bloqueaba TODO
        # hasta ver durante 2.2 s exactamente la mano configurada como CURSOR.
        # Ahora el control funciona desde el primer frame.
        self.calibrator.update(cursor, now)
        calibrating = not self.calibrator.done

        if calibrating and CFG.get("calibration_blocks_control", False):
            self.gesture = "CALIBRANDO"
            self.gesture_progress = self.calibrator.progress(now)
            return {
                "cursor": cursor,
                "action": action,
                "radial": None,
                "calibrating": True,
                "single_hand": single_hand,
            }

        # Frames de gracia para no resetear por una deteccion mala aislada.
        self.lost_cursor = self.lost_cursor + 1 if cursor is None else 0
        self.lost_action = self.lost_action + 1 if action is None else 0
        grace = int(CFG.get("lost_hand_grace_frames", 3))

        if self.lost_cursor > grace:
            self.filtered_tip = None
            self.last_filtered_tip = None
            self.last_raw_tip = None
            self.scroll_prev_y = None

        if self.lost_action > grace:
            if self.dragging:
                self.link.send("DRAG_END")
                self.dragging = False
            self.primary_latch.reset()
            self.secondary_latch.reset()
            self.primary_prev = False
            self.secondary_prev = False
            self.primary_started = None
            self.three_started = None
            self.three_fired = False
            self.swipe_start = None
            self.radial_open = False

        # Gestos de DOS manos solo si realmente son dos manos diferentes.
        two_real_hands = (
            cursor is not None
            and action is not None
            and cursor is not action
            and len(hands) >= 2
        )

        # Dos palmas abiertas mantenidas = lock/unlock.
        both_open = bool(
            two_real_hands
            and four_open(cursor["fingers"])
            and four_open(action["fingers"])
        )

        if both_open:
            if self.both_palms_started is None:
                self.both_palms_started = now
                self.both_palms_fired = False

            hold = float(CFG.get("both_palms_lock_seconds", 0.90))
            p = (now - self.both_palms_started) / hold
            self.gesture = "2 PALMAS: LOCK"
            self.gesture_progress = clamp(p, 0.0, 1.0)

            if not self.both_palms_fired and p >= 1.0:
                self.link.send("LOCK_TOGGLE")
                self.reset_transient()
                self.both_palms_started = now
                self.both_palms_fired = True

            return {
                "cursor": cursor,
                "action": action,
                "radial": None,
                "calibrating": calibrating,
                "single_hand": single_hand,
            }

        self.both_palms_started = None
        self.both_palms_fired = False

        # Puno en mano de acciones = fail-safe.
        fist_candidate = bool(
            action
            and is_fist(action["fingers"])
            and action["ratios"]["index"] > float(CFG.get("pinch_release_ratio", 0.40))
            and action["ratios"]["middle"] > float(CFG.get("pinch_release_ratio", 0.40))
        )

        if fist_candidate:
            if self.fist_started is None:
                self.fist_started = now
                self.fist_fired = False

            hold = float(CFG.get("fist_hold_seconds", 0.35))
            p = (now - self.fist_started) / hold
            self.gesture = "SAFE / PUNO"
            self.gesture_progress = clamp(p, 0.0, 1.0)

            if not self.fist_fired and p >= 1.0:
                self.link.send("ACT,CANCEL")
                self.dragging = False
                self.primary_latch.reset()
                self.secondary_latch.reset()
                self.primary_prev = False
                self.secondary_prev = False
                self.primary_started = None
                self.fist_fired = True

            self.safety_fist = True
            return {
                "cursor": cursor,
                "action": action,
                "radial": None,
                "calibrating": calibrating,
                "single_hand": single_hand,
            }

        self.safety_fist = False
        self.fist_started = None
        self.fist_fired = False

        if self.link.locked:
            self.gesture = "BLOQUEADO"
            return {
                "cursor": cursor,
                "action": action,
                "radial": None,
                "calibrating": calibrating,
                "single_hand": single_hand,
            }

        press = float(CFG.get("pinch_press_ratio", 0.32))
        cursor_idx_pinch = bool(cursor and cursor["ratios"]["index"] <= press)
        action_idx_pinch = bool(action and action["ratios"]["index"] <= press)

        # Zoom solo con dos manos reales.
        if two_real_hands and cursor_idx_pinch and action_idx_pinch:
            d = dist2(cursor["center"], action["center"])

            if not self.zoom_active:
                self.zoom_active = True
                self.zoom_anchor = d
            else:
                step = float(CFG.get("zoom_step_px", 34))
                if d - self.zoom_anchor >= step:
                    self.dispatch_direct("ZOOM_IN")
                    self.zoom_anchor = d
                elif self.zoom_anchor - d >= step:
                    self.dispatch_direct("ZOOM_OUT")
                    self.zoom_anchor = d

            self.gesture = "ZOOM 2 MANOS"
            return {
                "cursor": cursor,
                "action": action,
                "radial": None,
                "calibrating": calibrating,
                "single_hand": single_hand,
            }

        if self.zoom_active:
            self.zoom_active = False
            self.zoom_anchor = None
            self.zoom_suppress_until = now + 0.32
            self.primary_latch.reset()
            self.secondary_latch.reset()
            self.primary_prev = False
            self.secondary_prev = False
            self.primary_started = None

        self.precision = False
        self._update_cursor(cursor, cursor_idx_pinch)

        if now < self.zoom_suppress_until:
            radial = None
            self.gesture = "ZOOM LISTO"
        else:
            radial = self._update_action_hand(action, now)

        # Si sigue calibrando, no tapa el gesto actual: solo se muestra como estado.
        return {
            "cursor": cursor,
            "action": action,
            "radial": radial,
            "calibrating": calibrating,
            "single_hand": single_hand,
        }


# ============================================================
# MAIN
# ============================================================

if not MODEL_PATH.is_file():
    raise SystemExit(f"Falta el modelo: {MODEL_PATH}")

link = Esp32USB(CFG.get("serial_port", "AUTO"), CFG.get("serial_baud", 115200))
link.connect()

engine = GestureEngine(link)
engine.sync_roles()

cam_index = int(CFG.get("camera_index", 0))
cam = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
if not cam.isOpened():
    cam = cv2.VideoCapture(cam_index)

cam.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cam.isOpened():
    raise SystemExit("No se pudo abrir la camara. Cambia camera_index en config.json.")

options = mp.tasks.vision.HandLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
    running_mode=mp.tasks.vision.RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.76,
    min_hand_presence_confidence=0.76,
    min_tracking_confidence=0.78,
)

timestamp_ms = 0
last_frame_t = time.perf_counter()
fps_smooth = 0.0
last_status_t = 0.0
last_reconnect_t = 0.0
last_profile_check = 0.0
active_process = ""

show_help = False
fullscreen = False

try:
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
        while True:
            ok, frame = cam.read()
            if not ok:
                break

            now = time.monotonic()

            if CFG.get("mirror_camera", True):
                frame = cv2.flip(frame, 1)

            h, w = frame.shape[:2]

            # USB heartbeat / reconexion.
            if link.ser and now - last_status_t > 0.65:
                link.send("STATUS")
                last_status_t = now
            elif not link.ser and now - last_reconnect_t > 2.5:
                link.connect()
                engine.sync_roles()
                last_reconnect_t = now

            # Eventos del boton fisico.
            for event in link.pop_events():
                if event == "SWAP_ROLES":
                    engine.swap_roles()
                elif event == "MODE_NEXT":
                    engine.reset_transient()

            # Perfil automatico por app activa.
            if now - last_profile_check > 0.45:
                active_process = engine.update_profile()
                last_profile_check = now

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            timestamp_ms = max(timestamp_ms + 1, time.monotonic_ns() // 1_000_000)
            result = detector.detect_for_video(mp_image, timestamp_ms)

            hands = build_hands(result, w, h)
            state = engine.update(hands, now)

            # ---------------- HUD ----------------
            panel(frame, (0,0), (w,58), (8,13,18), 0.80)

            txt(frame, "HOLOTOUCH", (18,27), 0.76, WHITE, 2)
            txt(frame, "V7 PRO", (18,48), 0.42, ACCENT)

            chip(frame, f"USB {link.port or 'OFF'}", 150, 35, ACCENT if link.port else DANGER)
            chip(frame, f"MODE {link.mode}", 292, 35, ACCENT2)
            chip(frame, f"APP {engine.profile}", 420, 35, (190,150,255))
            chip(frame, "LOCK" if link.locked else "LIVE", 570, 35, DANGER if link.locked else ACCENT)
            chip(
                frame,
                f"{engine.cursor_label[0]}:CUR {engine.action_label[0]}:ACT",
                max(690, w-180),
                35,
                WHITE,
            )

            if state.get("single_hand") and state["cursor"]:
                draw_hand(frame, state["cursor"], "CURSOR+ACC")
            else:
                if state["cursor"]:
                    draw_hand(frame, state["cursor"], "CURSOR")
                if state["action"]:
                    draw_hand(frame, state["action"], "ACCIONES")

            if engine.filtered_tip:
                p = (int(engine.filtered_tip[0]), int(engine.filtered_tip[1]))
                cv2.circle(frame, p, 9, ACCENT, 2, cv2.LINE_AA)
                cv2.circle(frame, p, 2, WHITE, -1, cv2.LINE_AA)

            if state["calibrating"]:
                prog = engine.calibrator.progress(now)
                chip(frame, f"CAL {int(prog*100):02d}%", 18, 82, ACCENT2)

            if engine.gesture_progress > 0 and state["action"]:
                ring(
                    frame,
                    state["action"]["center"],
                    engine.gesture_progress,
                    ACCENT2,
                    34,
                )

            if state["radial"]:
                draw_radial(
                    frame,
                    state["radial"]["center"],
                    state["radial"]["items"],
                    state["radial"]["selected"],
                    state["radial"]["progress"],
                )

            # Barra inferior.
            panel(frame, (0,h-44), (w,h), (8,13,18), 0.78)

            gesture_color = DANGER if (
                "SAFE" in engine.gesture or "BLOQUE" in engine.gesture
            ) else ACCENT

            txt(frame, engine.gesture, (18,h-16), 0.58, gesture_color, 2)

            flags = []
            if engine.precision:
                flags.append("PRECISION")
            if engine.auto_profiles:
                flags.append("AUTO APP")
            if engine.radial_open:
                flags.append("RADIAL")
            if state.get("single_hand"):
                flags.append("1 MANO")
            if flags:
                txt(frame, " | ".join(flags), (235,h-16), 0.43, MUTED)

            dt = max(time.perf_counter()-last_frame_t, 1e-6)
            last_frame_t = time.perf_counter()
            fps = 1.0 / dt
            fps_smooth = fps if fps_smooth == 0 else fps_smooth*0.88 + fps*0.12
            txt(frame, f"{fps_smooth:4.1f} FPS", (w-95,h-16), 0.43, MUTED)

            if CFG.get("show_debug", False):
                y = 84
                txt(frame, f"Proceso: {active_process or '-'}", (15,y), 0.42, MUTED)
                y += 20
                if state["cursor"]:
                    txt(frame, f"CUR palm={state['cursor']['palm_px']:.1f}", (15,y), 0.42, MUTED)
                    y += 20
                if state["action"]:
                    rr = state["action"]["ratios"]
                    txt(
                        frame,
                        f"ACT pinza I={rr['index']:.2f} M={rr['middle']:.2f}",
                        (15,y),
                        0.42,
                        MUTED,
                    )

            if show_help:
                draw_help(frame, engine.profile)

            cv2.imshow("HOLOTOUCH V7 PRO", frame)

            if fullscreen:
                cv2.setWindowProperty(
                    "HOLOTOUCH V7 PRO",
                    cv2.WND_PROP_FULLSCREEN,
                    cv2.WINDOW_FULLSCREEN,
                )
            else:
                cv2.setWindowProperty(
                    "HOLOTOUCH V7 PRO",
                    cv2.WND_PROP_FULLSCREEN,
                    cv2.WINDOW_NORMAL,
                )

            key = cv2.waitKey(1) & 0xFF

            if key in (27, ord("q"), ord("Q")):
                break
            elif key in (ord("h"), ord("H")):
                show_help = not show_help
            elif key in (ord("d"), ord("D")):
                CFG["show_debug"] = not CFG.get("show_debug", False)
            elif key in (ord("x"), ord("X")):
                engine.swap_roles()
            elif key in (ord("c"), ord("C")):
                engine.calibrator.reset()
                engine.reset_transient()
            elif key in (ord("a"), ord("A")):
                engine.auto_profiles = not engine.auto_profiles
            elif key in (ord("r"), ord("R")):
                link.connect()
                engine.sync_roles()
            elif key in (ord("t"), ord("T")):
                # Prueba directa: si esto mueve el cursor, USB/HID esta perfecto.
                link.send("MOVE,45,0")
                time.sleep(0.08)
                link.send("MOVE,-45,0")
            elif key in (ord("f"), ord("F")):
                fullscreen = not fullscreen
            elif key == ord("1"):
                link.send("MODE,MOUSE")
            elif key == ord("2"):
                link.send("MODE,MEDIA")
            elif key == ord("3"):
                link.send("MODE,PRESENT")
            elif key == ord("4"):
                link.send("MODE,NAV")

finally:
    if engine.dragging:
        link.send("DRAG_END")
    link.send("ACT,CANCEL")
    cam.release()
    cv2.destroyAllWindows()
    link.close()
