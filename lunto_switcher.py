#!/usr/bin/env python3
"""Lunto Switcher: hotkey-only layout fixer (Punto Switcher style) for Linux, X11 and Wayland.

Pause          re-type the last word (up to the previous space) in the other layout
Shift+Pause    convert the selected text to the other layout
Alt+Pause      swap case of the last word (or of the selected text)

Reads keys from /dev/input (evdev), types through a uinput virtual keyboard, so it
works the same on X11 and Wayland. The clipboard is never touched: the selection is
read from PRIMARY.
"""
import fcntl
import json
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import evdev
from evdev import InputDevice, UInput, ecodes as e

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

VIRT_NAME = "lunto-switcher-virtual"

# key, en lower, en upper, ru lower, ru upper (physical key -> char per layout)
ROWS = [
    ("GRAVE", "`", "~", "ё", "Ё"), ("1", "1", "!", "1", "!"), ("2", "2", "@", "2", '"'),
    ("3", "3", "#", "3", "№"), ("4", "4", "$", "4", ";"), ("5", "5", "%", "5", "%"),
    ("6", "6", "^", "6", ":"), ("7", "7", "&", "7", "?"), ("8", "8", "*", "8", "*"),
    ("9", "9", "(", "9", "("), ("0", "0", ")", "0", ")"), ("MINUS", "-", "_", "-", "_"),
    ("EQUAL", "=", "+", "=", "+"),
    ("Q", "q", "Q", "й", "Й"), ("W", "w", "W", "ц", "Ц"), ("E", "e", "E", "у", "У"),
    ("R", "r", "R", "к", "К"), ("T", "t", "T", "е", "Е"), ("Y", "y", "Y", "н", "Н"),
    ("U", "u", "U", "г", "Г"), ("I", "i", "I", "ш", "Ш"), ("O", "o", "O", "щ", "Щ"),
    ("P", "p", "P", "з", "З"), ("LEFTBRACE", "[", "{", "х", "Х"),
    ("RIGHTBRACE", "]", "}", "ъ", "Ъ"), ("BACKSLASH", "\\", "|", "\\", "/"),
    ("A", "a", "A", "ф", "Ф"), ("S", "s", "S", "ы", "Ы"), ("D", "d", "D", "в", "В"),
    ("F", "f", "F", "а", "А"), ("G", "g", "G", "п", "П"), ("H", "h", "H", "р", "Р"),
    ("J", "j", "J", "о", "О"), ("K", "k", "K", "л", "Л"), ("L", "l", "L", "д", "Д"),
    ("SEMICOLON", ";", ":", "ж", "Ж"), ("APOSTROPHE", "'", '"', "э", "Э"),
    ("Z", "z", "Z", "я", "Я"), ("X", "x", "X", "ч", "Ч"), ("C", "c", "C", "с", "С"),
    ("V", "v", "V", "м", "М"), ("B", "b", "B", "и", "И"), ("N", "n", "N", "т", "Т"),
    ("M", "m", "M", "ь", "Ь"), ("COMMA", ",", "<", "б", "Б"), ("DOT", ".", ">", "ю", "Ю"),
    ("SLASH", "/", "?", ".", ","), ("SPACE", " ", " ", " ", " "),
]
LAYOUTS = ("en", "ru")
CHAR2POS = {l: {} for l in LAYOUTS}   # char -> (keycode, shift)
POS2CHAR = {l: {} for l in LAYOUTS}   # (keycode, shift) -> char
for name, *chars in ROWS:
    code = getattr(e, "KEY_" + name)
    for i, layout in enumerate(LAYOUTS):
        for shift, ch in ((False, chars[2 * i]), (True, chars[2 * i + 1])):
            CHAR2POS[layout].setdefault(ch, (code, shift))
            POS2CHAR[layout][(code, shift)] = ch
for layout in LAYOUTS:
    for ch, code in (("\n", e.KEY_ENTER), ("\t", e.KEY_TAB)):
        CHAR2POS[layout][ch] = (code, False)
        POS2CHAR[layout][(code, False)] = ch
CHAR_KEYS = {getattr(e, "KEY_" + r[0]) for r in ROWS}
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю"
RU_LETTERS = set(_RU + _RU.upper())

SHIFTS = {e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT}
CTRLS = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL}
ALTS = {e.KEY_LEFTALT, e.KEY_RIGHTALT}
METAS = {e.KEY_LEFTMETA, e.KEY_RIGHTMETA}
MODS = SHIFTS | CTRLS | ALTS | METAS
MOUSE_BTNS = {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE}
MAX_BUF = 64     # a "word" never needs more; less data held is less to leak


def log(*a):
    """Never pass typed or selected text here: the log file must stay free of user data."""
    print("lunto-switcher:", *a, file=sys.stderr, flush=True)


def acquire_lock():
    """Only one instance per user session: a second one exits immediately."""
    d = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}" or "/tmp")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path("/tmp")
    f = open(d / "lunto-switcher.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("lunto-switcher: already running")
    return f


def harden():
    """No core dumps, no ptrace / /proc/PID/mem reads by other processes, private files."""
    os.umask(0o077)
    try:
        import ctypes
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)   # PR_SET_DUMPABLE = 0
    except Exception as ex:
        log("hardening partly failed:", ex)


def other(layout):
    return "ru" if layout == "en" else "en"


def detect(text):
    return "ru" if any(c in RU_LETTERS for c in text) else "en"


def convert(text):
    src = detect(text)
    dst = other(src)
    out = []
    for ch in text:
        pos = CHAR2POS[src].get(ch)
        out.append(POS2CHAR[dst].get(pos, ch) if pos else ch)
    return "".join(out)


def typeable(text, layout):
    return all(ch in CHAR2POS[layout] for ch in text)


def run(cmd, **kw):
    kw.setdefault("timeout", 2)
    kw.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.run(cmd, stdout=subprocess.PIPE, **kw).stdout.decode("utf-8", "replace")


def parse_layout(name):
    n = (name or "").strip().lower()
    if n.startswith("ru") or "russian" in n or "рус" in n:
        return "ru"
    if n.startswith(("us", "en", "gb")) or "english" in n:
        return "en"
    return None


# --- environment detection: layout query / switch ---------------------------------------

def q_gnome():
    out = run(["gsettings", "get", "org.gnome.desktop.input-sources", "mru-sources"])
    m = re.search(r"'xkb', '([^']+)'", out)
    return m.group(1) if m else None


def q_sway():
    for i in json.loads(run(["swaymsg", "-t", "get_inputs", "-r"])):
        if i.get("xkb_active_layout_name"):
            return i["xkb_active_layout_name"]


def q_hypr():
    kbs = json.loads(run(["hyprctl", "devices", "-j"]))["keyboards"]
    kb = next((k for k in kbs if k.get("main")), kbs[0])
    return kb["active_keymap"]


KDE_KBD = ["busctl", "--user", "call", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts"]


def q_kde(order):
    return order[int(re.search(r"\d+", run(KDE_KBD + ["getLayout"])).group())]


class X11Xkb:
    """Reads/locks the XKB group straight through libX11 (no xkb-switch/xdotool needed)."""
    USE_CORE_KBD = 0x100

    def __init__(self):
        import ctypes
        self.ctypes = ctypes
        self.x = ctypes.CDLL("libX11.so.6")
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
        self.x.XkbLockGroup.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.dpy = self.x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("cannot open X display")

    def group(self):
        buf = self.ctypes.create_string_buffer(32)
        self.x.XkbGetState(self.dpy, self.USE_CORE_KBD, buf)
        return buf.raw[0]

    def lock(self, group):
        self.x.XkbLockGroup(self.dpy, self.USE_CORE_KBD, group)
        self.x.XFlush(self.dpy)


def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def auto_backend(order):
    """Returns (query, switch_cmd, switch_keys, switch_fn); any of them may be None."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if os.environ.get("SWAYSOCK"):
        return q_sway, ["swaymsg", "input", "type:keyboard", "xkb_switch_layout", "next"], None, None
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return q_hypr, ["hyprctl", "switchxkblayout", "all", "next"], None, None
    if "gnome" in desktop or "unity" in desktop:
        return q_gnome, None, ["KEY_LEFTMETA", "KEY_SPACE"], None
    if "kde" in desktop:
        return (lambda: q_kde(order)), KDE_KBD + ["switchToNextLayout"], None, None
    if not is_wayland():
        try:
            x, n = X11Xkb(), len(order)
            return (lambda: order[x.group() % n]), None, None, (lambda: x.lock((x.group() + 1) % n))
        except Exception as ex:
            log("X11 XKB unavailable:", ex)
    return None, None, ["KEY_LEFTMETA", "KEY_SPACE"], None


class Daemon:
    def __init__(self, cfg):
        g = cfg.get("general", {})
        sw = cfg.get("switch", {})
        hk = cfg.get("hotkeys", {})
        self.hotkey = getattr(e, hk.get("key", "KEY_PAUSE"))
        self.hotkey_mods = {getattr(e, m) for m in hk.get("mods", []) if hasattr(e, m)}
        self.capture = False   # tray asks the daemon for the next pressed key
        self.captured = None   # (frozenset(mods), keycode) once captured
        self.on_layout = None  # tray callback: called with the layout name on change
        self.tray_layout = None
        self.key_delay = g.get("key_delay", 0.004)
        self.switch_delay = sw.get("delay", 0.08)
        self.select_delay = g.get("select_delay", 0.08)
        self.layout = g.get("initial_layout", "en")
        self.ttl = g.get("buffer_ttl", 15)      # seconds of inactivity before the buffer is wiped
        self.last_key = time.monotonic()
        self.wayland = is_wayland()

        query, cmd, keys, fn = auto_backend(g.get("layouts", ["us", "ru"]))
        if sw.get("command"):
            cmd, keys, fn = sw["command"].split(), None, None
        if sw.get("keys"):
            keys, cmd, fn = sw["keys"], None, None
        if sw.get("query"):
            qcmd = sw["query"].split()
            query = lambda: run(qcmd)
        self.query, self.switch_cmd, self.switch_keys, self.switch_fn = query, cmd, keys, fn
        log("session=%s query=%s switch=%s" % ("wayland" if self.wayland else "x11", bool(query), cmd or keys or ("xkb" if fn else None)))

        self.ui = UInput({e.EV_KEY: list(range(1, 249))}, name=VIRT_NAME)
        time.sleep(0.5)  # let the compositor pick up the new device
        self.down = set()
        self.buf = []          # [(keycode, shift)] typed since the last reset
        self.pending = None    # (action, deadline): waits until modifiers are released
        self.devs = {}
        self.ignored = set()

    # ---- output -----------------------------------------------------------------------
    def emit(self, code, value):
        self.ui.write(e.EV_KEY, code, value)
        self.ui.syn()
        time.sleep(self.key_delay)

    def tap(self, code, shift=False):
        if shift:
            self.emit(e.KEY_LEFTSHIFT, 1)
        self.emit(code, 1)
        self.emit(code, 0)
        if shift:
            self.emit(e.KEY_LEFTSHIFT, 0)

    def chord(self, names):
        codes = [getattr(e, n) for n in names]
        for c in codes:
            self.emit(c, 1)
        for c in reversed(codes):
            self.emit(c, 0)

    # ---- layout -----------------------------------------------------------------------
    def current_layout(self):
        if self.query:
            try:
                l = parse_layout(self.query())
                if l:
                    self.layout = l
            except Exception as ex:
                log("layout query failed:", ex)
        return self.layout

    def switch_to(self, target):
        if self.current_layout() == target:
            return
        for _ in range(3):
            if self.switch_fn:
                self.switch_fn()
            elif self.switch_keys:
                self.chord(self.switch_keys)
            elif self.switch_cmd:
                run(self.switch_cmd)
            else:
                log("no way to switch layout configured")
                return
            time.sleep(self.switch_delay)
            if not self.query:
                self.layout = target   # cannot verify: trust the toggle
                return
            deadline = time.time() + 0.6
            while time.time() < deadline:
                if self.current_layout() == target:
                    return
                time.sleep(0.03)

    # ---- PRIMARY selection (the clipboard is never used) -------------------------------
    def read_primary(self):
        cmd = ["wl-paste", "-p", "-n"] if self.wayland else ["xclip", "-o", "-selection", "primary"]
        try:
            return run(cmd)
        except Exception:
            return ""

    def clear_primary(self):
        try:
            if self.wayland:
                run(["wl-copy", "-p", "--clear"])
            else:
                subprocess.run(["xclip", "-selection", "primary", "-i", "/dev/null"], timeout=2,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # ---- actions ----------------------------------------------------------------------
    def last_word(self):
        i = len(self.buf)
        while i > 0 and self.buf[i - 1][0] == e.KEY_SPACE:
            i -= 1
        trailing = len(self.buf) - i
        j = i
        while j > 0 and self.buf[j - 1][0] != e.KEY_SPACE:
            j -= 1
        return j, i, trailing

    def act_convert_word(self):
        j, i, trailing = self.last_word()
        if i == j:   # nothing tracked: fall back to selecting the word left of the caret
            return self.convert_selected(select_word=True)
        word = self.buf[j:i]
        target = other(self.current_layout())
        for _ in range(len(word) + trailing):
            self.tap(e.KEY_BACKSPACE)
        self.switch_to(target)
        for code, shift in word + [(e.KEY_SPACE, False)] * trailing:
            self.tap(code, shift)

    def act_case(self):
        j, i, trailing = self.last_word()
        if i == j:
            return self.case_selected()
        layout = self.current_layout()
        flipped = []
        for code, shift in self.buf[j:i]:
            ch = POS2CHAR[layout].get((code, False), "")
            flipped.append((code, (not shift) if ch.isalpha() else shift))
        for _ in range(len(flipped) + trailing):
            self.tap(e.KEY_BACKSPACE)
        for code, shift in flipped + [(e.KEY_SPACE, False)] * trailing:
            self.tap(code, shift)
        self.buf[j:i] = flipped

    def convert_selected(self, select_word=False):
        if select_word:
            self.clear_primary()
            self.chord(["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_LEFT"])
            time.sleep(self.select_delay)
        text = self.read_primary()
        if not text:
            return log("no selection")
        dst = other(detect(text))
        out = convert(text)
        if not typeable(out, dst):
            return log("selection has characters that cannot be typed")
        self.switch_to(dst)
        for ch in out:
            self.tap(*CHAR2POS[dst][ch])
        self.buf.clear()
        self.clear_primary()

    def case_selected(self):
        text = self.read_primary()
        if not text:
            return log("no selection")
        out = text.swapcase()
        lay = detect(text)
        if not typeable(out, lay):
            return log("selection has characters that cannot be typed")
        self.switch_to(lay)
        for ch in out:
            self.tap(*CHAR2POS[lay][ch])
        self.buf.clear()
        self.clear_primary()

    # ---- input ------------------------------------------------------------------------
    def expire(self):
        """Forget typed keys after a pause: the buffer only serves 'I just typed this'."""
        if self.buf and time.monotonic() - self.last_key > self.ttl:
            self.buf.clear()

    def on_key(self, code, value):
        if value == 0:
            self.down.discard(code)
            return
        self.expire()
        self.last_key = time.monotonic()
        if code in MOUSE_BTNS:
            self.buf.clear()
            return
        if value == 1:
            self.down.add(code)
        if self.capture and value == 1 and code not in MODS:
            self.captured = (frozenset(self.down & MODS), code)
            return
        if code == self.hotkey and self.hotkey_mods <= self.down:
            if value == 1:
                self.on_hotkey()
            return
        if code in MODS or code == e.KEY_CAPSLOCK:
            return
        if self.down & (CTRLS | ALTS | METAS):   # a shortcut, not typing
            self.buf.clear()
        elif code == e.KEY_BACKSPACE:
            if self.buf:
                self.buf.pop()
        elif code in CHAR_KEYS:
            self.buf.append((code, bool(self.down & SHIFTS)))
            del self.buf[:-MAX_BUF]
        else:                                     # arrows, Enter, Tab, Esc, Home, ...
            self.buf.clear()

    def on_hotkey(self):
        rest = self.down - self.hotkey_mods
        if rest & (CTRLS | METAS):
            return
        if rest & ALTS:
            action = self.act_case
        elif rest & SHIFTS:
            action = self.convert_selected
        else:
            action = self.act_convert_word
        # injected keys would combine with modifiers still held physically: wait for release
        self.pending = (action, time.time() + 2.0)

    def run_pending(self):
        if not self.pending:
            return
        action, deadline = self.pending
        if self.down & MODS:
            if time.time() > deadline:
                self.pending = None
            return
        self.pending = None
        try:
            action()
        except Exception as ex:
            log("action failed:", repr(ex))

    def scan(self):
        for path in evdev.list_devices():
            if path in self.devs or path in self.ignored:
                continue
            try:
                d = InputDevice(path)
                keys = d.capabilities().get(e.EV_KEY, [])
            except OSError:
                continue
            if d.name == VIRT_NAME or not (e.BTN_LEFT in keys or (e.KEY_A in keys and e.KEY_SPACE in keys)):
                self.ignored.add(path)
                d.close()
                continue
            self.devs[path] = d
            log("listening on", d.name)

    def loop(self):
        last_scan = 0
        last_layout = 0.0
        while True:
            if time.time() - last_scan > 3:
                self.scan()
                last_scan = time.time()
            if time.time() - last_layout > 1:
                last_layout = time.time()
                l = self.current_layout()
                if l != self.tray_layout:
                    self.tray_layout = l
                    if self.on_layout:
                        try:
                            self.on_layout(l)
                        except Exception as ex:
                            log("layout callback failed:", repr(ex))
            if not self.devs:
                time.sleep(1)
                continue
            fds = {d.fd: (p, d) for p, d in self.devs.items()}
            ready, _, _ = select.select(list(fds), [], [], 0.1 if self.pending else 3)
            for fd in ready:
                path, dev = fds[fd]
                try:
                    for ev in dev.read():
                        if ev.type == e.EV_KEY:
                            self.on_key(ev.code, ev.value)
                except OSError:      # unplugged
                    self.devs.pop(path, None)
                    self.down.clear()
            self.expire()
            self.run_pending()


def config_path():
    return Path(os.environ.get("LUNTO_SWITCHER_CONFIG") or Path.home() / ".config/lunto-switcher/config.toml")


def save_config(data):
    """Minimal TOML writer: sections of scalars / string lists only."""
    p = config_path()
    lines = []
    for sect, vals in data.items():
        if not isinstance(vals, dict):
            continue
        lines.append("[%s]" % sect)
        for k, v in vals.items():
            if isinstance(v, bool):
                lines.append("%s = %s" % (k, "true" if v else "false"))
            elif isinstance(v, (int, float)):
                lines.append("%s = %s" % (k, v))
            elif isinstance(v, list):
                lines.append("%s = [%s]" % (k, ", ".join(json.dumps(str(x)) for x in v)))
            else:
                lines.append("%s = %s" % (k, json.dumps(str(v))))
        lines.append("")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")


def hotkey_label(daemon):
    try:
        names = {c: n[4:] for c, n in evdev.ecodes.KEY.items() if isinstance(n, str) and n.startswith("KEY_")}
        mods = "+".join(names[m] for m in sorted(daemon.hotkey_mods))
        key = names.get(daemon.hotkey, "KEY_%d" % daemon.hotkey)
        return (mods + "+" + key) if mods else key
    except Exception:
        return "Pause"


class Tray:
    """Tray icon (StatusNotifier via AppIndicator): layout flag, hotkey change, exit."""

    def __init__(self, daemon):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3
        self.Gtk, self.GLib = Gtk, GLib
        self.App = AyatanaAppIndicator3
        self.daemon = daemon
        self.ind = AyatanaAppIndicator3.Indicator.new_with_path(
            "lunto-switcher", "lunto-en", AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            "/usr/share/icons")
        self.ind.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()
        self.layout_item = Gtk.MenuItem(label="Раскладка: EN")
        self.layout_item.set_sensitive(False)
        menu.append(self.layout_item)
        hk = Gtk.MenuItem(label="Сменить хоткей…")
        hk.connect("activate", self.ask_hotkey)
        menu.append(hk)
        quit_item = Gtk.MenuItem(label="Выход")
        quit_item.connect("activate", self.quit)
        menu.append(quit_item)
        menu.show_all()
        self.ind.set_menu(menu)

        daemon.on_layout = lambda l: GLib.idle_add(self.update_layout, l)
        self.update_layout(daemon.tray_layout or daemon.layout)
        self.update_title()

    def update_layout(self, layout):
        if layout not in LAYOUTS:
            return False
        self.ind.set_icon_full("lunto-" + layout, layout)
        self.layout_item.set_text("Раскладка: " + layout.upper())
        return False

    def update_title(self):
        combo = hotkey_label(self.daemon)
        self.ind.set_title("Lunto Switcher",
                           "Слово: %s | Выделение: Shift+%s | Регистр: Alt+%s" % (combo, combo, combo))

    def ask_hotkey(self, *_):
        Gtk, GLib = self.Gtk, self.GLib
        win = Gtk.Window(title="Lunto Switcher — новый хоткей")
        win.set_default_size(420, 140)
        win.set_keep_above(True)
        lbl = Gtk.Label(label="Нажмите новую клавишу или комбинацию.\nEsc — отмена.")
        lbl.set_margin_top(20)
        lbl.set_margin_bottom(20)
        win.add(lbl)
        self.daemon.capture = True
        self.daemon.captured = None
        win.show_all()

        def poll():
            if self.daemon.captured is None and win.is_visible():
                return True
            self.daemon.capture = False
            win.destroy()
            cap = self.daemon.captured
            if cap:
                mods, code = cap
                if code == e.KEY_ESCAPE and not mods:
                    return False
                try:
                    key = evdev.ecodes.KEY[code]
                    mods_names = sorted(evdev.ecodes.KEY[m] for m in mods)
                except (KeyError, IndexError):
                    return False
                data = {}
                if tomllib and config_path().exists():
                    with open(config_path(), "rb") as f:
                        data = tomllib.load(f)
                hk = data.setdefault("hotkeys", {})
                hk["key"] = key
                hk["mods"] = mods_names
                save_config(data)
                self.daemon.hotkey = code
                self.daemon.hotkey_mods = set(mods)
                self.update_title()
            return False

        GLib.timeout_add(50, poll)

    def quit(self, *_):
        try:
            self.ind.set_status(self.App.IndicatorStatus.PASSIVE)
        except Exception:
            pass
        self.GLib.idle_add(self.Gtk.main_quit)


def tray_available():
    if "--no-tray" in sys.argv:
        return False
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return False
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        return True
    except Exception:
        return False


def load_config():
    path = config_path()
    if tomllib and path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


if __name__ == "__main__":
    harden()
    _lock = acquire_lock()
    try:
        daemon = Daemon(load_config())
    except PermissionError as ex:
        sys.exit("lunto-switcher: no access to /dev/input or /dev/uinput (%s). See README: 'input' group + udev rule." % ex)
    if tray_available():
        try:
            Tray(daemon)
            threading.Thread(target=daemon.loop, daemon=True).start()
            from gi.repository import Gtk
            Gtk.main()
        except KeyboardInterrupt:
            pass
        except Exception as ex:
            log("tray unavailable, running headless:", repr(ex))
            try:
                daemon.loop()
            except KeyboardInterrupt:
                pass
    else:
        log("tray unavailable, running headless")
        try:
            daemon.loop()
        except KeyboardInterrupt:
            pass
