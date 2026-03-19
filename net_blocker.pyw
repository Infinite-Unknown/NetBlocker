# ============================================================================
#  Net Blocker — Selective app internet blocker with lagswitch & spacebar spam
#  Copyright (c) 2026 Infinite
#  GitHub: https://github.com/Infinite-Unknown
# ============================================================================

import ctypes
import ctypes.wintypes
import sys
import os
import subprocess
import hashlib
import threading
import atexit
import signal
import json
import time
import random
import webbrowser

import psutil
import customtkinter as ctk
from pynput import mouse, keyboard as kb

__version__ = "1.1.0"
__author__ = "Infinite"
__github__ = "https://github.com/Infinite-Unknown"


# --- Config ---
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net_blocker_configs")
os.makedirs(CONFIG_DIR, exist_ok=True)


# --- Admin Elevation ---
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if not is_admin():
    exe = sys.executable
    if exe.endswith("python.exe"):
        exe = exe.replace("python.exe", "pythonw.exe")
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, f'"{os.path.abspath(sys.argv[0])}"', None, 1
    )
    sys.exit(0)


# --- Firewall Manager ---
class FirewallManager:
    RULE_PREFIX = "NetBlocker_"
    _CREATE_NO_WINDOW = 0x08000000

    def __init__(self):
        self._active_rules: set[str] = set()

    def _rule_name(self, exe_path: str) -> str:
        short_hash = hashlib.md5(exe_path.lower().encode()).hexdigest()[:8]
        return f"{self.RULE_PREFIX}{os.path.basename(exe_path)}_{short_hash}"

    def block(self, exe_path: str):
        rule_name = self._rule_name(exe_path)
        if rule_name in self._active_rules:
            return
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={rule_name}", "dir=out", "action=block",
             f"program={exe_path}", "enable=yes"],
            capture_output=True, creationflags=self._CREATE_NO_WINDOW,
        )
        self._active_rules.add(rule_name)

    def unblock(self, exe_path: str):
        rule_name = self._rule_name(exe_path)
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule",
             f"name={rule_name}"],
            capture_output=True, creationflags=self._CREATE_NO_WINDOW,
        )
        self._active_rules.discard(rule_name)

    def cleanup_all(self):
        for rule_name in list(self._active_rules):
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "delete", "rule",
                 f"name={rule_name}"],
                capture_output=True, creationflags=self._CREATE_NO_WINDOW,
            )
        self._active_rules.clear()

    def cleanup_orphaned(self):
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=all", "dir=out"],
            capture_output=True, text=True,
            creationflags=self._CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Rule Name:"):
                name = line.split(":", 1)[1].strip()
                if name.startswith(self.RULE_PREFIX):
                    subprocess.run(
                        ["netsh", "advfirewall", "firewall", "delete", "rule",
                         f"name={name}"],
                        capture_output=True,
                        creationflags=self._CREATE_NO_WINDOW,
                    )


# --- Hotkey Manager (supports keyboard + mouse buttons) ---

MOUSE_BUTTON_NAMES = {
    mouse.Button.left: "Mouse Left",
    mouse.Button.right: "Mouse Right",
    mouse.Button.middle: "Mouse Middle",
}
try:
    MOUSE_BUTTON_NAMES[mouse.Button.x1] = "Mouse 4 (Back)"
    MOUSE_BUTTON_NAMES[mouse.Button.x2] = "Mouse 5 (Forward)"
except AttributeError:
    pass

MOUSE_NAME_TO_BUTTON = {v: k for k, v in MOUSE_BUTTON_NAMES.items()}


def _key_display_name(key) -> str:
    if isinstance(key, kb.Key):
        return key.name.replace("_", " ").title()
    elif isinstance(key, kb.KeyCode):
        if key.char:
            return key.char.upper()
        if key.vk is not None:
            return f"VK {key.vk}"
    return str(key)


class HotkeyManager:
    def __init__(self, on_activate, on_deactivate):
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._is_active = False
        self._capturing = False

        self._bound_key = None
        self._bound_mouse_btn = None
        self._display_name = "F9"

        self._kb_listener = None
        self._mouse_listener = None
        self._capture_callback = None

        self._bound_key = kb.Key.f9

    @property
    def display_name(self):
        return self._display_name

    def set_from_display_name(self, name: str):
        self._display_name = name
        if name in MOUSE_NAME_TO_BUTTON:
            self._bound_mouse_btn = MOUSE_NAME_TO_BUTTON[name]
            self._bound_key = None
        else:
            self._bound_mouse_btn = None
            try:
                self._bound_key = kb.Key[name.lower().replace(" ", "_")]
            except (KeyError, AttributeError):
                self._bound_key = kb.KeyCode.from_char(name.lower()) if len(name) == 1 else kb.Key.f9

    def start_listeners(self):
        self._kb_listener = kb.Listener(
            on_press=self._on_kb_press,
            on_release=self._on_kb_release,
        )
        self._kb_listener.daemon = True
        self._kb_listener.start()

        self._mouse_listener = mouse.Listener(
            on_click=self._on_mouse_click,
        )
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def stop_listeners(self):
        if self._kb_listener:
            self._kb_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()

    def start_capture(self, callback):
        self._capturing = True
        self._capture_callback = callback

    def _finish_capture(self, display_name):
        self._capturing = False
        self._display_name = display_name
        cb = self._capture_callback
        self._capture_callback = None
        if cb:
            cb(display_name)

    def _on_kb_press(self, key):
        if self._capturing:
            self._bound_key = key
            self._bound_mouse_btn = None
            self._finish_capture(_key_display_name(key))
            return
        if self._bound_key is not None and self._keys_match(key, self._bound_key):
            if not self._is_active:
                self._is_active = True
                self._on_activate()

    def _on_kb_release(self, key):
        if self._bound_key is not None and self._keys_match(key, self._bound_key):
            if self._is_active:
                self._is_active = False
                self._on_deactivate()

    def _keys_match(self, a, b):
        if isinstance(a, kb.Key) and isinstance(b, kb.Key):
            return a == b
        if isinstance(a, kb.KeyCode) and isinstance(b, kb.KeyCode):
            if a.vk is not None and b.vk is not None:
                return a.vk == b.vk
            return a.char == b.char
        return False

    def _on_mouse_click(self, x, y, button, pressed):
        if self._capturing:
            if pressed:
                self._bound_mouse_btn = button
                self._bound_key = None
                name = MOUSE_BUTTON_NAMES.get(button, str(button))
                self._finish_capture(name)
            return
        if self._bound_mouse_btn is not None and button == self._bound_mouse_btn:
            if pressed and not self._is_active:
                self._is_active = True
                self._on_activate()
            elif not pressed and self._is_active:
                self._is_active = False
                self._on_deactivate()


# --- Config Save/Load ---
def save_config(name: str, data: dict):
    path = os.path.join(CONFIG_DIR, f"{name}.json")
    data["name"] = name
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_config(name: str) -> dict | None:
    path = os.path.join(CONFIG_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def list_configs() -> list[str]:
    configs = []
    for fname in os.listdir(CONFIG_DIR):
        if fname.endswith(".json"):
            configs.append(fname[:-5])
    configs.sort()
    return configs


def delete_config(name: str):
    path = os.path.join(CONFIG_DIR, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)


# --- Overlay Window ---
class OverlayWindow:
    DEFAULT_SETTINGS = {
        "label_size": 18,
        "timer_size": 14,
        "on_color": "#F44336",
        "off_color": "#4CAF50",
        "timer_active_color": "#F44336",
        "timer_idle_color": "#888888",
        "bg_color": "#1a1a1a",
        "opacity": 85,
        "width": 200,
        "height": 70,
        "pos_x": 20,
        "pos_y": 20,
    }

    def __init__(self, root, on_pos_changed=None):
        self._root = root
        self._win = None
        self._label = None
        self._timer_label = None
        self._content_frame = None
        self._visible = False
        self._blocking = False
        self._block_start = 0.0
        self._timer_after_id = None
        self._settings = dict(self.DEFAULT_SETTINGS)
        self._on_pos_changed = on_pos_changed

    @property
    def settings(self):
        # Capture current position if visible
        if self._win is not None:
            try:
                self._settings["pos_x"] = self._win.winfo_x()
                self._settings["pos_y"] = self._win.winfo_y()
            except Exception:
                pass
        return dict(self._settings)

    def update_settings(self, **kwargs):
        # Capture current position so non-position changes don't reset it
        self._capture_pos()
        self._settings.update(kwargs)
        self._apply_live()

    def apply_all_settings(self, settings: dict):
        self._capture_pos()
        self._settings.update(settings)
        self._apply_live()

    def _capture_pos(self):
        """Read current window position into settings."""
        if self._win is not None:
            try:
                self._settings["pos_x"] = self._win.winfo_x()
                self._settings["pos_y"] = self._win.winfo_y()
            except Exception:
                pass

    def _apply_live(self):
        """Apply settings to an already-visible overlay."""
        if self._win is None:
            return
        s = self._settings
        self._win.configure(fg_color=s["bg_color"])
        self._win.attributes("-alpha", s["opacity"] / 100.0)
        w, h = s["width"], s["height"]
        x, y = s["pos_x"], s["pos_y"]
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        if self._label:
            color = s["on_color"] if self._blocking else s["off_color"]
            self._label.configure(
                font=ctk.CTkFont(size=s["label_size"], weight="bold"),
                text_color=color,
            )
        if self._timer_label:
            tcolor = s["timer_active_color"] if self._blocking else s["timer_idle_color"]
            self._timer_label.configure(
                font=ctk.CTkFont(size=s["timer_size"]),
                text_color=tcolor,
            )

    def show(self):
        if self._win is not None:
            return
        s = self._settings
        self._win = ctk.CTkToplevel(self._root)
        self._win.title("")
        self._win.geometry(f"{s['width']}x{s['height']}+{s['pos_x']}+{s['pos_y']}")
        self._win.resizable(False, False)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-alpha", s["opacity"] / 100.0)
        self._win.configure(fg_color=s["bg_color"])

        # Content frame centered in window
        self._content_frame = ctk.CTkFrame(self._win, fg_color="transparent")
        self._content_frame.place(relx=0.5, rely=0.5, anchor="center")

        self._label = ctk.CTkLabel(
            self._content_frame, text="Lagswitch: Off",
            font=ctk.CTkFont(size=s["label_size"], weight="bold"),
            text_color=s["off_color"],
        )
        self._label.pack()

        self._timer_label = ctk.CTkLabel(
            self._content_frame, text="0 ms",
            font=ctk.CTkFont(size=s["timer_size"]),
            text_color=s["timer_idle_color"],
        )
        self._timer_label.pack()

        for w in (self._win, self._content_frame, self._label, self._timer_label):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        self._visible = True

    def hide(self):
        self._capture_pos()
        if self._timer_after_id is not None:
            self._root.after_cancel(self._timer_after_id)
            self._timer_after_id = None
        if self._win is not None:
            self._win.destroy()
            self._win = None
            self._label = None
            self._timer_label = None
            self._content_frame = None
            self._visible = False

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    @property
    def visible(self):
        return self._visible

    def set_blocking(self, blocking: bool):
        self._blocking = blocking
        s = self._settings
        if self._label is None:
            return
        if blocking:
            self._block_start = time.perf_counter()
            self._label.configure(text="Lagswitch: On", text_color=s["on_color"])
            if self._timer_after_id is None:
                self._tick_timer()
        else:
            if self._timer_after_id is not None:
                self._root.after_cancel(self._timer_after_id)
                self._timer_after_id = None
            elapsed_ms = int((time.perf_counter() - self._block_start) * 1000)
            self._label.configure(text="Lagswitch: Off", text_color=s["off_color"])
            if self._timer_label:
                self._timer_label.configure(text=f"{elapsed_ms} ms", text_color=s["timer_idle_color"])

    def _tick_timer(self):
        if not self._blocking or self._timer_label is None:
            return
        elapsed_ms = int((time.perf_counter() - self._block_start) * 1000)
        self._timer_label.configure(text=f"{elapsed_ms} ms", text_color=self._settings["timer_active_color"])
        self._timer_after_id = self._root.after(16, self._tick_timer)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        if self._win is None:
            return
        x = self._win.winfo_x() + event.x - self._drag_x
        y = self._win.winfo_y() + event.y - self._drag_y
        self._win.geometry(f"+{x}+{y}")
        self._settings["pos_x"] = x
        self._settings["pos_y"] = y
        if self._on_pos_changed:
            self._on_pos_changed(x, y)


# --- Spacebar Spammer (ctypes SendInput + low-level hook) ---

# KBDLLHOOKSTRUCT for the low-level keyboard hook
class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

# SendInput structures — all three union members needed for correct struct size (40 bytes on x64)
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]

class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _INPUT_UNION)]

# Proper hook callback type: LRESULT CALLBACK(int nCode, WPARAM wParam, LPARAM lParam)
_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM,   # LRESULT return
    ctypes.c_int,             # nCode
    ctypes.wintypes.WPARAM,   # wParam
    ctypes.wintypes.LPARAM,   # lParam
)


class SpacebarSpammer:
    VK_SPACE = 0x20
    SCAN_SPACE = 0x39
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    LLKHF_INJECTED = 0x00000010

    def __init__(self, on_start=None, on_stop=None):
        self._running = False
        self._thread = None
        self._hook_thread = None
        self._hook_id = None
        self.press_delay_ms = 50
        self.release_delay_ms = 50
        self._hold_delay_ms = 0
        self._activated = False
        self._enabled = False
        self._on_start = on_start
        self._on_stop = on_stop
        # Randomize mode
        self.randomize = False
        self.press_min_ms = 10
        self.press_max_ms = 80
        self.release_min_ms = 10
        self.release_max_ms = 80
        self.hold_min_ms = 0
        self.hold_max_ms = 500
        # Store callback ref to prevent GC
        self._hook_proc_ref = _HOOKPROC(self._ll_keyboard_proc)

    def _send_key(self, up=False):
        flags = self.KEYEVENTF_SCANCODE
        if up:
            flags |= self.KEYEVENTF_KEYUP
        inp = _INPUT(type=1)
        inp.ii.ki.wVk = self.VK_SPACE
        inp.ii.ki.wScan = self.SCAN_SPACE
        inp.ii.ki.dwFlags = flags
        inp.ii.ki.time = 0
        inp.ii.ki.dwExtraInfo = ULONG_PTR(0)
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(_INPUT))

    def _ll_keyboard_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and self._enabled:
            hook_struct = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            is_injected = bool(hook_struct.flags & self.LLKHF_INJECTED)

            if hook_struct.vkCode == self.VK_SPACE and not is_injected:
                if wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                    if not self._running:
                        self.start()
                    return 1  # suppress physical press
                elif wParam in (self.WM_KEYUP, self.WM_SYSKEYUP):
                    self.stop()
                    return 1  # suppress physical release

        return ctypes.windll.user32.CallNextHookEx(
            self._hook_id, nCode,
            ctypes.wintypes.WPARAM(wParam),
            ctypes.wintypes.LPARAM(lParam),
        )

    def _hook_loop(self):
        self._hook_id = ctypes.windll.user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._hook_proc_ref, None, 0
        )
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    def start_hook(self):
        """Start the low-level keyboard hook thread."""
        if self._hook_thread is not None:
            return
        self._hook_thread = threading.Thread(target=self._hook_loop, daemon=True)
        self._hook_thread.start()

    def stop_hook(self):
        if self._hook_id:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self.stop()

    def _spam_loop(self):
        # Activation delay
        if self.randomize:
            hold_ms = random.randint(self.hold_min_ms, max(self.hold_min_ms, self.hold_max_ms))
        else:
            hold_ms = self._hold_delay_ms
        if hold_ms > 0:
            deadline = time.perf_counter() + hold_ms / 1000.0
            while self._running and time.perf_counter() < deadline:
                time.sleep(0.005)
            if not self._running:
                return
        self._activated = True
        if self._on_start:
            self._on_start()
        while self._running:
            self._send_key(up=False)   # press
            if self.randomize:
                p = random.randint(self.press_min_ms, max(self.press_min_ms, self.press_max_ms))
            else:
                p = self.press_delay_ms
            time.sleep(p / 1000.0)
            self._send_key(up=True)    # release
            if self.randomize:
                r = random.randint(self.release_min_ms, max(self.release_min_ms, self.release_max_ms))
            else:
                r = self.release_delay_ms
            time.sleep(r / 1000.0)
        self._activated = False
        if self._on_stop:
            self._on_stop()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._spam_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False


# --- App ---
class NetBlockerApp:
    def __init__(self):
        self.firewall = FirewallManager()
        self.firewall.cleanup_orphaned()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Net Blocker")
        self.root.geometry("650x550")
        self.root.minsize(500, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self.processes: list[dict] = []
        self.checkboxes: list[tuple[ctk.CTkCheckBox, ctk.BooleanVar, dict]] = []
        self._all_processes: list[dict] = []

        self.overlay = OverlayWindow(self.root, on_pos_changed=self._on_overlay_pos_changed)
        self.spammer = SpacebarSpammer(
            on_start=self._on_spammer_started,
            on_stop=self._on_spammer_stopped,
        )
        self.spammer.start_hook()
        self._refresh_after_id = None
        self._gap_after_id = None
        self._hotkey_held = False
        self._toggle_active = False  # for toggle mode

        self._build_ui()

        self.hotkey_mgr = HotkeyManager(self._on_block, self._on_unblock)
        self.hotkey_mgr.start_listeners()

        atexit.register(self._cleanup)
        signal.signal(signal.SIGTERM, lambda s, f: self._cleanup_and_exit())
        signal.signal(signal.SIGINT, lambda s, f: self._cleanup_and_exit())

        self._refresh_processes()
        self._load_first_config()

    def _load_first_config(self):
        configs = list_configs()
        if configs:
            data = load_config(configs[0])
            if data:
                self._apply_config(data)

    def _build_ui(self):
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=12)

        self.tab_main = self.tabview.add("Blocker")
        self.tab_configs = self.tabview.add("Configs")
        self.tab_overlay = self.tabview.add("Overlay")
        self.tab_misc = self.tabview.add("Misc")

        self._build_main_tab()
        self._build_configs_tab()
        self._build_overlay_tab()
        self._build_misc_tab()

        # Footer with copyright
        footer = ctk.CTkFrame(self.root, fg_color="transparent", height=24)
        footer.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(footer, text=f"v{__version__}  |  Created by {__author__}  |",
                      font=ctk.CTkFont(size=11), text_color="#888888").pack(side="left")

        github_link = ctk.CTkLabel(footer, text="GitHub",
                                    font=ctk.CTkFont(size=11, underline=True),
                                    text_color="#4A9EDF", cursor="hand2")
        github_link.pack(side="left", padx=(4, 0))
        github_link.bind("<Button-1>", lambda e: webbrowser.open(__github__))

    # --- Main Tab ---
    def _build_main_tab(self):
        top = ctk.CTkFrame(self.tab_main)
        top.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(top, text="Refresh", width=80,
                       command=self._refresh_processes).pack(side="left", padx=(6, 4), pady=6)

        self.overlay_btn = ctk.CTkButton(top, text="Show Overlay", width=110,
                                          command=self._toggle_overlay)
        self.overlay_btn.pack(side="left", padx=4, pady=6)

        self.hotkey_btn = ctk.CTkButton(top, text="Set Hotkey", width=90,
                                         command=self._start_hotkey_capture)
        self.hotkey_btn.pack(side="right", padx=(4, 6), pady=6)

        self.hotkey_label = ctk.CTkLabel(top, text="Hotkey: F9",
                                          font=ctk.CTkFont(size=13))
        self.hotkey_label.pack(side="right", padx=4, pady=6)

        # Mode + Status bar
        mode_frame = ctk.CTkFrame(self.tab_main)
        mode_frame.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(mode_frame, text="Mode:",
                      font=ctk.CTkFont(size=13)).pack(side="left", padx=(10, 4), pady=6)

        self._hotkey_mode = ctk.StringVar(value="Hold")
        self._mode_selector = ctk.CTkSegmentedButton(
            mode_frame, values=["Hold", "Toggle"],
            variable=self._hotkey_mode, width=160,
            font=ctk.CTkFont(size=13),
            command=self._on_mode_change,
        )
        self._mode_selector.pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(mode_frame, text="Status:",
                      font=ctk.CTkFont(size=14)).pack(side="left", padx=(16, 4), pady=6)
        self.status_label = ctk.CTkLabel(mode_frame, text="INACTIVE",
                                          text_color="#4CAF50",
                                          font=ctk.CTkFont(size=14, weight="bold"))
        self.status_label.pack(side="left", pady=6)

        # Auto-refresh section
        refresh_frame = ctk.CTkFrame(self.tab_main)
        refresh_frame.pack(fill="x", pady=(0, 6))

        self._auto_refresh_enabled = ctk.BooleanVar(value=False)
        self._auto_refresh_btn = ctk.CTkSwitch(
            refresh_frame, text="Auto Refresh",
            variable=self._auto_refresh_enabled,
            font=ctk.CTkFont(size=13),
        )
        self._auto_refresh_btn.pack(side="left", padx=(10, 8), pady=6)

        self._auto_refresh_ms = ctk.IntVar(value=500)
        self._refresh_slider = ctk.CTkSlider(
            refresh_frame, from_=1, to=999,
            variable=self._auto_refresh_ms, width=200,
            command=self._on_slider_change,
        )
        self._refresh_slider.pack(side="left", padx=4, pady=6)

        self._refresh_ms_label = ctk.CTkLabel(
            refresh_frame, text="500 ms",
            font=ctk.CTkFont(size=13), width=70,
        )
        self._refresh_ms_label.pack(side="left", padx=4, pady=6)

        # Scrollable process list
        self.scroll_frame = ctk.CTkScrollableFrame(self.tab_main, label_text="Running Applications")
        self.scroll_frame.pack(fill="both", expand=True, pady=(0, 6))

        # Hint
        ctk.CTkLabel(self.tab_main,
                      text="Select apps above. Hold mode: hold key to block. Toggle mode: press to start/stop.",
                      text_color="gray",
                      font=ctk.CTkFont(size=12)).pack(pady=(0, 4))

    # --- Configs Tab ---
    def _build_configs_tab(self):
        save_frame = ctk.CTkFrame(self.tab_configs)
        save_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(save_frame, text="Save Current Selection",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))

        row = ctk.CTkFrame(save_frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 8))

        self.config_name_entry = ctk.CTkEntry(row, placeholder_text="Config name...", width=250)
        self.config_name_entry.pack(side="left", padx=(0, 6))

        ctk.CTkButton(row, text="Save", width=70,
                       command=self._save_config).pack(side="left")

        ctk.CTkLabel(self.tab_configs, text="Saved Configs",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(0, 4))

        self.configs_scroll = ctk.CTkScrollableFrame(self.tab_configs)
        self.configs_scroll.pack(fill="both", expand=True, padx=0, pady=(0, 6))

        self._refresh_configs_list()

    def _refresh_configs_list(self):
        for widget in self.configs_scroll.winfo_children():
            widget.destroy()

        configs = list_configs()
        if not configs:
            ctk.CTkLabel(self.configs_scroll, text="No saved configs yet.",
                          text_color="gray").pack(pady=20)
            return

        for cfg_name in configs:
            data = load_config(cfg_name)
            if not data:
                continue

            row = ctk.CTkFrame(self.configs_scroll)
            row.pack(fill="x", padx=6, pady=3)

            app_count = len(data.get("exe_paths", []))
            hotkey = data.get("hotkey", "?")
            info_text = f"{cfg_name}   |   {app_count} app(s)   |   Hotkey: {hotkey}"
            ctk.CTkLabel(row, text=info_text, font=ctk.CTkFont(size=12),
                          anchor="w").pack(side="left", padx=8, pady=6, fill="x", expand=True)

            ctk.CTkButton(row, text="Load", width=60, fg_color="#2B7A2B", hover_color="#236B23",
                           command=lambda n=cfg_name: self._load_config(n)).pack(side="right", padx=4, pady=4)

            ctk.CTkButton(row, text="Save", width=60, fg_color="#1B6AAA", hover_color="#155A8A",
                           command=lambda n=cfg_name: self._save_config_overwrite(n)).pack(side="right", padx=4, pady=4)

            ctk.CTkButton(row, text="Delete", width=60, fg_color="#8B0000", hover_color="#6B0000",
                           command=lambda n=cfg_name: self._delete_config(n)).pack(side="right", padx=4, pady=4)

    # --- Overlay Tab ---
    def _build_overlay_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_overlay)
        scroll.pack(fill="both", expand=True)

        ctk.CTkLabel(scroll, text="Overlay Customization",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(6, 8))

        defaults = OverlayWindow.DEFAULT_SETTINGS

        # --- Font Sizes ---
        font_frame = ctk.CTkFrame(scroll)
        font_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(font_frame, text="Label Font Size:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_label_size = ctk.IntVar(value=defaults["label_size"])
        ctk.CTkSlider(font_frame, from_=10, to=40, variable=self._ov_label_size,
                       width=180, command=lambda v: self._on_overlay_setting("label_size", v)
                       ).pack(side="left", padx=4, pady=6)
        self._ov_label_size_lbl = ctk.CTkLabel(font_frame, text=str(defaults["label_size"]),
                                                 font=ctk.CTkFont(size=13), width=40)
        self._ov_label_size_lbl.pack(side="left", padx=4, pady=6)

        timer_font_frame = ctk.CTkFrame(scroll)
        timer_font_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(timer_font_frame, text="Timer Font Size:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_timer_size = ctk.IntVar(value=defaults["timer_size"])
        ctk.CTkSlider(timer_font_frame, from_=8, to=32, variable=self._ov_timer_size,
                       width=180, command=lambda v: self._on_overlay_setting("timer_size", v)
                       ).pack(side="left", padx=4, pady=6)
        self._ov_timer_size_lbl = ctk.CTkLabel(timer_font_frame, text=str(defaults["timer_size"]),
                                                 font=ctk.CTkFont(size=13), width=40)
        self._ov_timer_size_lbl.pack(side="left", padx=4, pady=6)

        # --- Colors ---
        ctk.CTkLabel(scroll, text="Colors",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))

        color_defs = [
            ("On Color:", "on_color", defaults["on_color"]),
            ("Off Color:", "off_color", defaults["off_color"]),
            ("Timer Active:", "timer_active_color", defaults["timer_active_color"]),
            ("Timer Idle:", "timer_idle_color", defaults["timer_idle_color"]),
            ("Background:", "bg_color", defaults["bg_color"]),
        ]
        self._ov_color_entries = {}
        for label_text, key, default_val in color_defs:
            row = ctk.CTkFrame(scroll)
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(size=13),
                          width=110, anchor="w").pack(side="left", padx=(10, 4), pady=4)
            entry = ctk.CTkEntry(row, width=100, placeholder_text=default_val)
            entry.insert(0, default_val)
            entry.pack(side="left", padx=4, pady=4)
            self._ov_color_entries[key] = entry
            preview = ctk.CTkLabel(row, text="  ", width=24, height=24,
                                    fg_color=default_val, corner_radius=4)
            preview.pack(side="left", padx=4, pady=4)
            # Bind to update preview and overlay on Enter or focus out
            entry.bind("<Return>", lambda e, k=key, p=preview: self._on_color_entry(k, p))
            entry.bind("<FocusOut>", lambda e, k=key, p=preview: self._on_color_entry(k, p))

        # --- Opacity ---
        ctk.CTkLabel(scroll, text="Appearance",
                      font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))

        opacity_frame = ctk.CTkFrame(scroll)
        opacity_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(opacity_frame, text="Opacity:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_opacity = ctk.IntVar(value=defaults["opacity"])
        ctk.CTkSlider(opacity_frame, from_=20, to=100, variable=self._ov_opacity,
                       width=180, command=lambda v: self._on_overlay_setting("opacity", v)
                       ).pack(side="left", padx=4, pady=6)
        self._ov_opacity_lbl = ctk.CTkLabel(opacity_frame, text=f"{defaults['opacity']}%",
                                              font=ctk.CTkFont(size=13), width=50)
        self._ov_opacity_lbl.pack(side="left", padx=4, pady=6)

        # --- Size ---
        size_frame = ctk.CTkFrame(scroll)
        size_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(size_frame, text="Width:",
                      font=ctk.CTkFont(size=13), width=60,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_width = ctk.IntVar(value=defaults["width"])
        ctk.CTkSlider(size_frame, from_=120, to=500, variable=self._ov_width,
                       width=130, command=lambda v: self._on_overlay_setting("width", v)
                       ).pack(side="left", padx=4, pady=6)
        self._ov_width_lbl = ctk.CTkLabel(size_frame, text=str(defaults["width"]),
                                            font=ctk.CTkFont(size=13), width=40)
        self._ov_width_lbl.pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(size_frame, text="Height:",
                      font=ctk.CTkFont(size=13), width=60,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_height = ctk.IntVar(value=defaults["height"])
        ctk.CTkSlider(size_frame, from_=40, to=300, variable=self._ov_height,
                       width=130, command=lambda v: self._on_overlay_setting("height", v)
                       ).pack(side="left", padx=4, pady=6)
        self._ov_height_lbl = ctk.CTkLabel(size_frame, text=str(defaults["height"]),
                                             font=ctk.CTkFont(size=13), width=40)
        self._ov_height_lbl.pack(side="left", padx=4, pady=6)

        # --- Position ---
        pos_frame = ctk.CTkFrame(scroll)
        pos_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(pos_frame, text="X:",
                      font=ctk.CTkFont(size=13), width=30,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_pos_x = ctk.IntVar(value=defaults["pos_x"])
        self._ov_pos_x_slider = ctk.CTkSlider(
            pos_frame, from_=0, to=3840, variable=self._ov_pos_x,
            width=150, command=lambda v: self._on_overlay_setting("pos_x", v))
        self._ov_pos_x_slider.pack(side="left", padx=4, pady=6)
        self._ov_pos_x_lbl = ctk.CTkLabel(pos_frame, text=str(defaults["pos_x"]),
                                            font=ctk.CTkFont(size=13), width=50)
        self._ov_pos_x_lbl.pack(side="left", padx=4, pady=6)

        ctk.CTkLabel(pos_frame, text="Y:",
                      font=ctk.CTkFont(size=13), width=30,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._ov_pos_y = ctk.IntVar(value=defaults["pos_y"])
        self._ov_pos_y_slider = ctk.CTkSlider(
            pos_frame, from_=0, to=2160, variable=self._ov_pos_y,
            width=150, command=lambda v: self._on_overlay_setting("pos_y", v))
        self._ov_pos_y_slider.pack(side="left", padx=4, pady=6)
        self._ov_pos_y_lbl = ctk.CTkLabel(pos_frame, text=str(defaults["pos_y"]),
                                            font=ctk.CTkFont(size=13), width=50)
        self._ov_pos_y_lbl.pack(side="left", padx=4, pady=6)

        # --- Reset button ---
        ctk.CTkButton(scroll, text="Reset to Defaults", width=140,
                       fg_color="#555555", hover_color="#444444",
                       command=self._reset_overlay_settings).pack(anchor="w", padx=10, pady=(10, 6))

    def _on_overlay_setting(self, key, value):
        v = int(value)
        self.overlay.update_settings(**{key: v})
        # Update labels
        if key == "label_size":
            self._ov_label_size_lbl.configure(text=str(v))
        elif key == "timer_size":
            self._ov_timer_size_lbl.configure(text=str(v))
        elif key == "opacity":
            self._ov_opacity_lbl.configure(text=f"{v}%")
        elif key == "width":
            self._ov_width_lbl.configure(text=str(v))
        elif key == "height":
            self._ov_height_lbl.configure(text=str(v))
        elif key == "pos_x":
            self._ov_pos_x_lbl.configure(text=str(v))
        elif key == "pos_y":
            self._ov_pos_y_lbl.configure(text=str(v))

    def _on_overlay_pos_changed(self, x, y):
        """Called when overlay is dragged — sync sliders."""
        self._ov_pos_x.set(x)
        self._ov_pos_x_lbl.configure(text=str(x))
        self._ov_pos_y.set(y)
        self._ov_pos_y_lbl.configure(text=str(y))

    def _on_color_entry(self, key, preview_label):
        entry = self._ov_color_entries[key]
        color = entry.get().strip()
        if not color.startswith("#") or len(color) not in (4, 7):
            return
        try:
            preview_label.configure(fg_color=color)
            self.overlay.update_settings(**{key: color})
        except Exception:
            pass

    def _reset_overlay_settings(self):
        defaults = OverlayWindow.DEFAULT_SETTINGS
        self.overlay.apply_all_settings(defaults)
        # Update all UI controls
        self._ov_label_size.set(defaults["label_size"])
        self._ov_label_size_lbl.configure(text=str(defaults["label_size"]))
        self._ov_timer_size.set(defaults["timer_size"])
        self._ov_timer_size_lbl.configure(text=str(defaults["timer_size"]))
        self._ov_opacity.set(defaults["opacity"])
        self._ov_opacity_lbl.configure(text=f"{defaults['opacity']}%")
        self._ov_width.set(defaults["width"])
        self._ov_width_lbl.configure(text=str(defaults["width"]))
        self._ov_height.set(defaults["height"])
        self._ov_height_lbl.configure(text=str(defaults["height"]))
        self._ov_pos_x.set(defaults["pos_x"])
        self._ov_pos_x_lbl.configure(text=str(defaults["pos_x"]))
        self._ov_pos_y.set(defaults["pos_y"])
        self._ov_pos_y_lbl.configure(text=str(defaults["pos_y"]))
        for key, entry in self._ov_color_entries.items():
            entry.delete(0, "end")
            entry.insert(0, defaults[key])
            # Update preview
            row = entry.master
            for child in row.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child.cget("width") == 24:
                    try:
                        child.configure(fg_color=defaults[key])
                    except Exception:
                        pass

    # --- Misc Tab ---
    def _build_misc_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_misc)
        scroll.pack(fill="both", expand=True)

        # Spacebar Spammer section
        ctk.CTkLabel(scroll, text="Spacebar Spammer",
                      font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=10, pady=(6, 8))

        # Enable toggle + status
        toggle_frame = ctk.CTkFrame(scroll)
        toggle_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._spammer_enabled = ctk.BooleanVar(value=False)
        self._spammer_switch = ctk.CTkSwitch(
            toggle_frame, text="Enable",
            variable=self._spammer_enabled,
            command=self._on_spammer_toggle,
            font=ctk.CTkFont(size=13),
        )
        self._spammer_switch.pack(side="left", padx=10, pady=8)

        self._spammer_status = ctk.CTkLabel(
            toggle_frame, text="OFF", text_color="#888888",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._spammer_status.pack(side="right", padx=10, pady=8)

        # Mode selector: Accurate / Random
        mode_frame = ctk.CTkFrame(scroll)
        mode_frame.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(mode_frame, text="Mode:",
                      font=ctk.CTkFont(size=13)).pack(side="left", padx=(10, 4), pady=6)

        self._spammer_mode = ctk.StringVar(value="Accurate")
        self._spammer_mode_selector = ctk.CTkSegmentedButton(
            mode_frame, values=["Accurate", "Random"],
            variable=self._spammer_mode, width=180,
            font=ctk.CTkFont(size=13),
            command=self._on_spammer_mode_change,
        )
        self._spammer_mode_selector.pack(side="left", padx=4, pady=6)

        # --- Accurate mode frame ---
        self._accurate_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._accurate_frame.pack(fill="x", padx=0, pady=0)

        # Press delay
        press_frame = ctk.CTkFrame(self._accurate_frame)
        press_frame.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(press_frame, text="Press Delay:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._press_delay_var = ctk.IntVar(value=50)
        self._press_slider = ctk.CTkSlider(
            press_frame, from_=0, to=100,
            variable=self._press_delay_var, width=200,
            command=lambda v: self._on_spammer_slider("press", v),
        )
        self._press_slider.pack(side="left", padx=4, pady=6)
        self._press_delay_label = ctk.CTkLabel(
            press_frame, text="50 ms", font=ctk.CTkFont(size=13), width=60)
        self._press_delay_label.pack(side="left", padx=4, pady=6)

        # Release delay
        release_frame = ctk.CTkFrame(self._accurate_frame)
        release_frame.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(release_frame, text="Release Delay:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._release_delay_var = ctk.IntVar(value=50)
        self._release_slider = ctk.CTkSlider(
            release_frame, from_=0, to=100,
            variable=self._release_delay_var, width=200,
            command=lambda v: self._on_spammer_slider("release", v),
        )
        self._release_slider.pack(side="left", padx=4, pady=6)
        self._release_delay_label = ctk.CTkLabel(
            release_frame, text="50 ms", font=ctk.CTkFont(size=13), width=60)
        self._release_delay_label.pack(side="left", padx=4, pady=6)

        # Activation delay
        hold_frame = ctk.CTkFrame(self._accurate_frame)
        hold_frame.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(hold_frame, text="Activation Delay:",
                      font=ctk.CTkFont(size=13), width=120,
                      anchor="w").pack(side="left", padx=(10, 4), pady=6)
        self._hold_delay_var = ctk.IntVar(value=0)
        self._hold_slider = ctk.CTkSlider(
            hold_frame, from_=0, to=2000,
            variable=self._hold_delay_var, width=200,
            command=lambda v: self._on_spammer_slider("hold", v),
        )
        self._hold_slider.pack(side="left", padx=4, pady=6)
        self._hold_delay_label = ctk.CTkLabel(
            hold_frame, text="0 ms", font=ctk.CTkFont(size=13), width=60)
        self._hold_delay_label.pack(side="left", padx=4, pady=6)

        # --- Random mode frame ---
        self._random_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        # Hidden by default (not packed)

        def _rand_row(parent, label_text, min_val, max_val, min_default, max_default, key_prefix):
            frame = ctk.CTkFrame(parent)
            frame.pack(fill="x", padx=10, pady=(0, 4))
            ctk.CTkLabel(frame, text=label_text,
                          font=ctk.CTkFont(size=13), width=120,
                          anchor="w").pack(side="left", padx=(10, 4), pady=6)
            ctk.CTkLabel(frame, text="Min:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(4, 2), pady=6)
            min_var = ctk.IntVar(value=min_default)
            min_slider = ctk.CTkSlider(frame, from_=min_val, to=max_val, variable=min_var, width=100,
                                        command=lambda v, k=key_prefix: self._on_rand_slider(k, "min", v))
            min_slider.pack(side="left", padx=2, pady=6)
            min_lbl = ctk.CTkLabel(frame, text=str(min_default), font=ctk.CTkFont(size=12), width=40)
            min_lbl.pack(side="left", padx=2, pady=6)
            ctk.CTkLabel(frame, text="Max:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(6, 2), pady=6)
            max_var_tk = ctk.IntVar(value=max_default)
            max_slider = ctk.CTkSlider(frame, from_=min_val, to=max_val, variable=max_var_tk, width=100,
                                        command=lambda v, k=key_prefix: self._on_rand_slider(k, "max", v))
            max_slider.pack(side="left", padx=2, pady=6)
            max_lbl = ctk.CTkLabel(frame, text=str(max_default), font=ctk.CTkFont(size=12), width=40)
            max_lbl.pack(side="left", padx=2, pady=6)
            return min_var, min_slider, min_lbl, max_var_tk, max_slider, max_lbl

        (self._rp_min_var, self._rp_min_slider, self._rp_min_lbl,
         self._rp_max_var, self._rp_max_slider, self._rp_max_lbl) = _rand_row(
            self._random_frame, "Press Delay:", 0, 100, 10, 80, "press")

        (self._rr_min_var, self._rr_min_slider, self._rr_min_lbl,
         self._rr_max_var, self._rr_max_slider, self._rr_max_lbl) = _rand_row(
            self._random_frame, "Release Delay:", 0, 100, 10, 80, "release")

        (self._rh_min_var, self._rh_min_slider, self._rh_min_lbl,
         self._rh_max_var, self._rh_max_slider, self._rh_max_lbl) = _rand_row(
            self._random_frame, "Activation Delay:", 0, 2000, 0, 500, "hold")

        # Hint
        ctk.CTkLabel(scroll,
                      text="Hold spacebar to spam. Physical press is intercepted, synthetic presses are sent.",
                      text_color="gray",
                      font=ctk.CTkFont(size=12), wraplength=500,
                      justify="left").pack(anchor="w", padx=10, pady=(8, 0))

    def _on_spammer_mode_change(self, value):
        self.spammer.randomize = (value == "Random")
        if value == "Accurate":
            self._random_frame.pack_forget()
            self._accurate_frame.pack(fill="x", padx=0, pady=0)
        else:
            self._accurate_frame.pack_forget()
            self._random_frame.pack(fill="x", padx=0, pady=0)

    def _on_rand_slider(self, key_prefix, which, value):
        v = int(value)
        attr = f"{key_prefix}_{which}_ms"
        setattr(self.spammer, attr, v)
        # Update label
        lbl_map = {
            ("press", "min"): self._rp_min_lbl, ("press", "max"): self._rp_max_lbl,
            ("release", "min"): self._rr_min_lbl, ("release", "max"): self._rr_max_lbl,
            ("hold", "min"): self._rh_min_lbl, ("hold", "max"): self._rh_max_lbl,
        }
        lbl = lbl_map.get((key_prefix, which))
        if lbl:
            lbl.configure(text=str(v))

    def _on_spammer_slider(self, which, value):
        v = int(value)
        if which == "press":
            self._press_delay_label.configure(text=f"{v} ms")
            self.spammer.press_delay_ms = v
        elif which == "release":
            self._release_delay_label.configure(text=f"{v} ms")
            self.spammer.release_delay_ms = v
        elif which == "hold":
            self._hold_delay_label.configure(text=f"{v} ms")
            self.spammer._hold_delay_ms = v

    def _on_spammer_toggle(self):
        enabled = self._spammer_enabled.get()
        self.spammer.set_enabled(enabled)
        if enabled:
            self._spammer_status.configure(text="READY", text_color="#FFA500")
        else:
            self._spammer_status.configure(text="OFF", text_color="#888888")

    def _on_spammer_started(self):
        self.root.after(0, lambda: self._spammer_status.configure(
            text="SPAMMING", text_color="#F44336"))

    def _on_spammer_stopped(self):
        self.root.after(0, lambda: self._spammer_status.configure(
            text="READY" if self._spammer_enabled.get() else "OFF",
            text_color="#FFA500" if self._spammer_enabled.get() else "#888888"))

    # --- Process List ---
    def _refresh_processes(self):
        seen: set[str] = set()
        procs = []
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                exe = proc.info['exe']
                if exe and exe not in seen:
                    seen.add(exe)
                    procs.append({'name': proc.info['name'], 'exe': exe})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda p: p['name'].lower())
        self._all_processes = procs
        self._render_process_list(procs)

    def _render_process_list(self, procs: list[dict]):
        selected_exes = {p['exe'] for _, var, p in self.checkboxes if var.get()}

        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.checkboxes.clear()
        self.processes = procs

        for p in procs:
            var = ctk.BooleanVar(value=(p['exe'] in selected_exes))
            cb = ctk.CTkCheckBox(self.scroll_frame, text=f"{p['name']}   —   {p['exe']}",
                                  variable=var, font=ctk.CTkFont(size=12))
            cb.pack(anchor="w", padx=8, pady=2)
            self.checkboxes.append((cb, var, p))

    def _get_selected_exes(self) -> list[str]:
        return [p['exe'] for _, var, p in self.checkboxes if var.get()]

    # --- Hotkey ---
    def _start_hotkey_capture(self):
        self.hotkey_label.configure(text="Press any key or mouse button...")
        self.hotkey_mgr.start_capture(self._on_hotkey_captured)

    def _on_hotkey_captured(self, display_name):
        self.root.after(0, lambda: self.hotkey_label.configure(
            text=f"Hotkey: {display_name}"
        ))

    # --- Overlay ---
    def _toggle_overlay(self):
        self.overlay.toggle()
        if self.overlay.visible:
            self.overlay_btn.configure(text="Hide Overlay")
        else:
            self.overlay_btn.configure(text="Show Overlay")

    # --- Slider ---
    def _on_slider_change(self, value):
        self._refresh_ms_label.configure(text=f"{int(value)} ms")

    # --- Block / Unblock ---
    def _do_block(self):
        exes = self._get_selected_exes()
        for exe in exes:
            self.firewall.block(exe)
        self.status_label.configure(text="BLOCKING", text_color="#F44336")
        self.overlay.set_blocking(True)

        # Schedule auto-refresh if enabled
        is_active = self._hotkey_held or self._toggle_active
        if self._auto_refresh_enabled.get() and is_active:
            ms = self._auto_refresh_ms.get()
            self._refresh_after_id = self.root.after(ms, self._auto_refresh)

    def _do_unblock(self):
        self.firewall.cleanup_all()
        self.status_label.configure(text="INACTIVE", text_color="#4CAF50")
        self.overlay.set_blocking(False)

    def _is_blocking_active(self):
        return self._hotkey_held or self._toggle_active

    def _auto_refresh(self):
        if not self._is_blocking_active():
            return
        self._do_unblock()
        self._gap_after_id = self.root.after(50, self._auto_refresh_reblock)

    def _auto_refresh_reblock(self):
        if not self._is_blocking_active():
            return
        self._do_block()

    def _cancel_refresh_timers(self):
        if self._refresh_after_id is not None:
            self.root.after_cancel(self._refresh_after_id)
            self._refresh_after_id = None
        if self._gap_after_id is not None:
            self.root.after_cancel(self._gap_after_id)
            self._gap_after_id = None

    def _on_mode_change(self, value):
        # If switching modes while active, clean up
        if self._toggle_active:
            self._toggle_active = False
            self._hotkey_held = False
            self._cancel_refresh_timers()
            self._do_unblock()

    def _on_block(self):
        if self._hotkey_mode.get() == "Toggle":
            # Toggle mode: press once to activate, press again to deactivate
            if self._toggle_active:
                # Second press — turn off
                self._toggle_active = False
                self._hotkey_held = False
                self.root.after(0, self._cancel_refresh_timers)
                self.root.after(0, self._do_unblock)
            else:
                # First press — turn on
                self._toggle_active = True
                self._hotkey_held = True
                self.root.after(0, self._do_block)
        else:
            # Hold mode
            self._hotkey_held = True
            self.root.after(0, self._do_block)

    def _on_unblock(self):
        if self._hotkey_mode.get() == "Toggle":
            # In toggle mode, release does nothing
            return
        # Hold mode — release turns off
        self._hotkey_held = False
        self.root.after(0, self._cancel_refresh_timers)
        self.root.after(0, self._do_unblock)

    # --- Config Actions ---
    def _gather_config_data(self) -> dict:
        return {
            "exe_paths": self._get_selected_exes(),
            "hotkey": self.hotkey_mgr.display_name,
            "hotkey_mode": self._hotkey_mode.get(),
            "auto_refresh_enabled": self._auto_refresh_enabled.get(),
            "auto_refresh_ms": self._auto_refresh_ms.get(),
            "overlay_visible": self.overlay.visible,
            "overlay_settings": self.overlay.settings,
            "spammer_enabled": self._spammer_enabled.get(),
            "spammer_mode": self._spammer_mode.get(),
            "spammer_press_ms": self._press_delay_var.get(),
            "spammer_release_ms": self._release_delay_var.get(),
            "spammer_hold_ms": self._hold_delay_var.get(),
            "spammer_rand_press_min": self._rp_min_var.get(),
            "spammer_rand_press_max": self._rp_max_var.get(),
            "spammer_rand_release_min": self._rr_min_var.get(),
            "spammer_rand_release_max": self._rr_max_var.get(),
            "spammer_rand_hold_min": self._rh_min_var.get(),
            "spammer_rand_hold_max": self._rh_max_var.get(),
        }

    def _save_config(self):
        name = self.config_name_entry.get().strip()
        if not name:
            return
        save_config(name, self._gather_config_data())
        self.config_name_entry.delete(0, "end")
        self._refresh_configs_list()

    def _save_config_overwrite(self, name: str):
        save_config(name, self._gather_config_data())
        self._refresh_configs_list()

    def _apply_config(self, data: dict):
        # Hotkey
        hotkey = data.get("hotkey", "F9")
        self.hotkey_mgr.set_from_display_name(hotkey)
        self.hotkey_label.configure(text=f"Hotkey: {hotkey}")

        # Hotkey mode
        mode = data.get("hotkey_mode", "Hold")
        self._hotkey_mode.set(mode)

        # Selected apps
        saved_exes = set(data.get("exe_paths", []))
        for _, var, p in self.checkboxes:
            var.set(p['exe'] in saved_exes)

        # Auto-refresh
        self._auto_refresh_enabled.set(data.get("auto_refresh_enabled", False))
        ar_ms = data.get("auto_refresh_ms", 500)
        self._auto_refresh_ms.set(ar_ms)
        self._refresh_slider.set(ar_ms)
        self._refresh_ms_label.configure(text=f"{ar_ms} ms")

        # Overlay settings
        ov_settings = data.get("overlay_settings")
        if ov_settings:
            self.overlay.apply_all_settings(ov_settings)
            # Sync UI controls
            self._ov_label_size.set(ov_settings.get("label_size", 18))
            self._ov_label_size_lbl.configure(text=str(ov_settings.get("label_size", 18)))
            self._ov_timer_size.set(ov_settings.get("timer_size", 14))
            self._ov_timer_size_lbl.configure(text=str(ov_settings.get("timer_size", 14)))
            self._ov_opacity.set(ov_settings.get("opacity", 85))
            self._ov_opacity_lbl.configure(text=f"{ov_settings.get('opacity', 85)}%")
            self._ov_width.set(ov_settings.get("width", 200))
            self._ov_width_lbl.configure(text=str(ov_settings.get("width", 200)))
            self._ov_height.set(ov_settings.get("height", 70))
            self._ov_height_lbl.configure(text=str(ov_settings.get("height", 70)))
            self._ov_pos_x.set(ov_settings.get("pos_x", 20))
            self._ov_pos_x_lbl.configure(text=str(ov_settings.get("pos_x", 20)))
            self._ov_pos_y.set(ov_settings.get("pos_y", 20))
            self._ov_pos_y_lbl.configure(text=str(ov_settings.get("pos_y", 20)))
            for key, entry in self._ov_color_entries.items():
                if key in ov_settings:
                    entry.delete(0, "end")
                    entry.insert(0, ov_settings[key])
                    row = entry.master
                    for child in row.winfo_children():
                        if isinstance(child, ctk.CTkLabel) and child.cget("width") == 24:
                            try:
                                child.configure(fg_color=ov_settings[key])
                            except Exception:
                                pass

        # Overlay visibility
        if data.get("overlay_visible", False):
            if not self.overlay.visible:
                self.overlay.show()
                self.overlay_btn.configure(text="Hide Overlay")
        else:
            if self.overlay.visible:
                self.overlay.hide()
                self.overlay_btn.configure(text="Show Overlay")

        # Spammer
        sp_enabled = data.get("spammer_enabled", False)
        self._spammer_enabled.set(sp_enabled)
        self.spammer.set_enabled(sp_enabled)
        if sp_enabled:
            self._spammer_status.configure(text="READY", text_color="#FFA500")
        else:
            self._spammer_status.configure(text="OFF", text_color="#888888")

        press_ms = data.get("spammer_press_ms", 50)
        release_ms = data.get("spammer_release_ms", 50)
        hold_ms = data.get("spammer_hold_ms", 0)

        self._press_delay_var.set(press_ms)
        self._press_slider.set(press_ms)
        self._press_delay_label.configure(text=f"{press_ms} ms")
        self.spammer.press_delay_ms = press_ms

        self._release_delay_var.set(release_ms)
        self._release_slider.set(release_ms)
        self._release_delay_label.configure(text=f"{release_ms} ms")
        self.spammer.release_delay_ms = release_ms

        self._hold_delay_var.set(hold_ms)
        self._hold_slider.set(hold_ms)
        self._hold_delay_label.configure(text=f"{hold_ms} ms")
        self.spammer._hold_delay_ms = hold_ms

        # Spammer mode
        sp_mode = data.get("spammer_mode", "Accurate")
        self._spammer_mode.set(sp_mode)
        self._on_spammer_mode_change(sp_mode)

        # Random settings
        rand_vals = {
            "press_min": ("_rp_min_var", "_rp_min_slider", "_rp_min_lbl", "press_min_ms", 10),
            "press_max": ("_rp_max_var", "_rp_max_slider", "_rp_max_lbl", "press_max_ms", 80),
            "release_min": ("_rr_min_var", "_rr_min_slider", "_rr_min_lbl", "release_min_ms", 10),
            "release_max": ("_rr_max_var", "_rr_max_slider", "_rr_max_lbl", "release_max_ms", 80),
            "hold_min": ("_rh_min_var", "_rh_min_slider", "_rh_min_lbl", "hold_min_ms", 0),
            "hold_max": ("_rh_max_var", "_rh_max_slider", "_rh_max_lbl", "hold_max_ms", 500),
        }
        for cfg_suffix, (var_name, slider_name, lbl_name, spammer_attr, default) in rand_vals.items():
            val = data.get(f"spammer_rand_{cfg_suffix}", default)
            getattr(self, var_name).set(val)
            getattr(self, slider_name).set(val)
            getattr(self, lbl_name).configure(text=str(val))
            setattr(self.spammer, spammer_attr, val)

    def _load_config(self, name: str):
        data = load_config(name)
        if not data:
            return
        self._apply_config(data)
        self.tabview.set("Blocker")

    def _delete_config(self, name: str):
        delete_config(name)
        self._refresh_configs_list()

    # --- Quit / Cleanup ---
    def _on_quit(self):
        self._cleanup()
        self.spammer.stop()
        self.spammer.stop_hook()
        self.hotkey_mgr.stop_listeners()
        self.root.destroy()

    def _cleanup(self):
        self.firewall.cleanup_all()

    def _cleanup_and_exit(self):
        self._cleanup()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    import traceback, logging
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "net_blocker.log")
    logging.basicConfig(filename=log_path, level=logging.ERROR,
                        format="%(asctime)s %(message)s")
    try:
        app = NetBlockerApp()
        app.run()
    except Exception:
        logging.error(traceback.format_exc())
        raise
