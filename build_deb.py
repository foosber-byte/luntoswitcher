#!/usr/bin/env python3
"""Builds dist/lunto-switcher_<ver>_all.deb without dpkg-deb (pure Python: ar + tar.gz)."""
import gzip
import hashlib
import io
import tarfile
import time
from pathlib import Path

VERSION = "0.2.3"
HERE = Path(__file__).parent
NOW = int(time.time())

CONTROL = f"""Package: lunto-switcher
Version: {VERSION}
Architecture: all
Section: utils
Priority: optional
Depends: python3 (>= 3.11), python3-evdev, python3-gi, gir1.2-ayatanaappindicator3-0.1, gir1.2-gtk-3.0, wl-clipboard, xclip, systemd | udev
Recommends: python3-tomli
Maintainer: Lunto Switcher <noreply@localhost>
Installed-Size: {{size}}
Description: hotkey-only keyboard layout fixer (Punto Switcher style)
 Pause re-types the last word in the other layout, Shift+Pause converts the
 selection, Alt+Pause swaps case. Works on X11 and Wayland through evdev/uinput.
 The clipboard is never touched. No automatic switching.
"""

POSTINST = """#!/bin/sh
set -e
if [ "$1" = configure ]; then
    modprobe uinput 2>/dev/null || true
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload 2>/dev/null || true
        udevadm trigger --subsystem-match=misc 2>/dev/null || true
    fi
    u="${SUDO_USER:-}"
    if [ -n "$u" ] && [ "$u" != root ] && getent group input >/dev/null 2>&1; then
        usermod -aG input "$u" || true
        echo "lunto-switcher: user '$u' added to group 'input'. Log out and back in to activate."
    else
        echo "lunto-switcher: add your user to the 'input' group:  sudo usermod -aG input <user>  (then re-login)"
    fi
    if [ -n "$u" ] && [ "$u" != root ]; then
        uid=$(id -u "$u" 2>/dev/null || :)
        if [ -n "$uid" ] && [ -S "/run/user/$uid/bus" ]; then
            runuser -u "$u" -- env XDG_RUNTIME_DIR=/run/user/$uid \
                DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \
                sh -c 'pkill -f "python3 /usr/bin/lunto-switcher" 2>/dev/null; systemctl --user daemon-reload; systemctl --user enable --now lunto-switcher.service' || true
            echo "lunto-switcher: daemon (re)started via systemd --user"
        else
            echo "lunto-switcher: will start automatically at the next login"
        fi
    fi
fi
exit 0
"""

PRERM = """#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = upgrade ]; then
    pkill -f '/usr/bin/lunto-switcher' 2>/dev/null || true
fi
exit 0
"""

UDEV = 'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"\n'

DESKTOP = """[Desktop Entry]
Type=Application
Name=Lunto Switcher
Comment=Hotkey layout fixer (Pause / Shift+Pause / Alt+Pause)
Exec=sh -c 'mkdir -p "$HOME/.cache" && exec /usr/bin/lunto-switcher 2>>"$HOME/.cache/lunto-switcher.log"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""

MODULES = "uinput\n"

SERVICE = """[Unit]
Description=Lunto Switcher hotkey layout fixer
After=graphical-session.target

[Service]
ExecStart=/usr/bin/lunto-switcher
Restart=on-failure

[Install]
WantedBy=graphical-session.target
"""


def copyright_file():
    lic = (HERE / "LICENSE").read_text().strip().splitlines()
    body = "\n".join((" ." if not ln.strip() else " " + ln) for ln in lic)
    return ("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: lunto-switcher\n"
            "Source: https://github.com/foosber-byte/luntoswitcher\n\n"
            "Files: *\n"
            "Copyright: 2026 foosber-byte\n"
            "License: MIT\n" + body + "\n").encode()


def files():
    """(path in package, bytes, mode)"""
    return [
        ("usr/bin/lunto-switcher", (HERE / "lunto_switcher.py").read_bytes(), 0o755),
        ("lib/udev/rules.d/70-lunto-switcher.rules", UDEV.encode(), 0o644),
        ("usr/lib/modules-load.d/lunto-switcher.conf", MODULES.encode(), 0o644),
        ("etc/xdg/autostart/lunto-switcher.desktop", DESKTOP.encode(), 0o644),
        ("usr/lib/systemd/user/lunto-switcher.service", SERVICE.encode(), 0o644),
        ("usr/share/doc/lunto-switcher/copyright", copyright_file(), 0o644),
        ("usr/share/doc/lunto-switcher/README.md", (HERE / "README.md").read_bytes(), 0o644),
        ("usr/share/doc/lunto-switcher/config.example.toml", (HERE / "config.example.toml").read_bytes(), 0o644),
        ("usr/share/icons/hicolor/scalable/apps/lunto-en.svg", (HERE / "lunto-en.svg").read_bytes(), 0o644),
        ("usr/share/icons/hicolor/scalable/apps/lunto-ru.svg", (HERE / "lunto-ru.svg").read_bytes(), 0o644),
    ]


def make_tar(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        dirs = set()
        for name, _, _ in members:
            parts = name.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        for d in sorted(dirs):
            ti = tarfile.TarInfo("./" + d)
            ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, NOW
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            tar.addfile(ti)
        for name, data, mode in members:
            ti = tarfile.TarInfo("./" + name)
            ti.size, ti.mode, ti.mtime = len(data), mode, NOW
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            tar.addfile(ti, io.BytesIO(data))
    return gzip.compress(buf.getvalue(), mtime=0)


def ar_member(name, data):
    hdr = f"{name:<16}{NOW:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
    return hdr + data + (b"\n" if len(data) % 2 else b"")


def main():
    data_files = files()
    data_tgz = make_tar(data_files)
    size_kb = sum(len(d) for _, d, _ in data_files) // 1024 + 1
    md5s = "".join(f"{hashlib.md5(d).hexdigest()}  {n}\n" for n, d, _ in data_files)
    control_files = [
        ("control", CONTROL.format(size=size_kb).encode(), 0o644),
        ("md5sums", md5s.encode(), 0o644),
        ("postinst", POSTINST.encode(), 0o755),
        ("prerm", PRERM.encode(), 0o755),
    ]
    # control.tar entries live at the root ("./control"), so build without the dir prefix logic
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in control_files:
            ti = tarfile.TarInfo("./" + name)
            ti.size, ti.mode, ti.mtime = len(data), mode, NOW
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            tar.addfile(ti, io.BytesIO(data))
    control_tgz = gzip.compress(buf.getvalue(), mtime=0)

    out = HERE / "dist" / f"lunto-switcher_{VERSION}_all.deb"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(
        b"!<arch>\n"
        + ar_member("debian-binary", b"2.0\n")
        + ar_member("control.tar.gz", control_tgz)
        + ar_member("data.tar.gz", data_tgz)
    )
    print("built", out)


if __name__ == "__main__":
    main()
