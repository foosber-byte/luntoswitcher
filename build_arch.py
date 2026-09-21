#!/usr/bin/env python3
"""Builds dist/kbswitch-arch-<ver>.tar.gz: a ready-to-run PKGBUILD directory (makepkg -si)."""
import tarfile
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).parent

PKGBUILD = f"""# Maintainer: kbswitch
pkgname=kbswitch
pkgver={VERSION}
pkgrel=1
pkgdesc='Hotkey-only keyboard layout fixer (Punto Switcher style) for X11 and Wayland'
arch=('any')
license=('custom')
depends=('python' 'python-evdev' 'wl-clipboard' 'xclip' 'libx11' 'systemd')
install=kbswitch.install
source=('kbswitch.py' '70-kbswitch.rules' 'kbswitch.desktop' 'kbswitch-modules.conf'
        'README.md' 'config.example.toml')
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {{
  install -Dm755 kbswitch.py "$pkgdir/usr/bin/kbswitch"
  install -Dm644 70-kbswitch.rules "$pkgdir/usr/lib/udev/rules.d/70-kbswitch.rules"
  install -Dm644 kbswitch-modules.conf "$pkgdir/usr/lib/modules-load.d/kbswitch.conf"
  install -Dm644 kbswitch.desktop "$pkgdir/etc/xdg/autostart/kbswitch.desktop"
  install -Dm644 README.md "$pkgdir/usr/share/doc/kbswitch/README.md"
  install -Dm644 config.example.toml "$pkgdir/usr/share/doc/kbswitch/config.example.toml"
}}
"""

INSTALL = """post_install() {
    modprobe uinput 2>/dev/null || true
    udevadm control --reload 2>/dev/null || true
    udevadm trigger --subsystem-match=misc 2>/dev/null || true
    local u="${SUDO_USER:-}"
    if [ -n "$u" ] && [ "$u" != root ] && getent group input >/dev/null 2>&1; then
        usermod -aG input "$u" || true
        echo "kbswitch: user '$u' added to group 'input'. Log out and back in to activate."
    else
        echo "kbswitch: add your user to the 'input' group:  sudo usermod -aG input <user>  (then re-login)"
    fi
}

post_upgrade() {
    post_install
}

pre_remove() {
    pkill -f '/usr/bin/kbswitch' 2>/dev/null || true
}
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=kbswitch
Comment=Hotkey layout fixer (Pause / Shift+Pause / Alt+Pause)
Exec=sh -c 'mkdir -p "$HOME/.cache" && exec /usr/bin/kbswitch 2>>"$HOME/.cache/kbswitch.log"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def main():
    out = HERE / "dist" / f"kbswitch-arch-{VERSION}.tar.gz"
    out.parent.mkdir(exist_ok=True)
    root = f"kbswitch-arch-{VERSION}"
    text = {
        "PKGBUILD": PKGBUILD,
        "kbswitch.install": INSTALL,
        "kbswitch.desktop": DESKTOP,
        "kbswitch-modules.conf": "uinput\n",
    }
    copies = ["kbswitch.py", "70-kbswitch.rules", "README.md", "config.example.toml"]
    import io
    with tarfile.open(out, "w:gz") as tar:
        def add(name, data):
            data = data.replace(b"\r\n", b"\n")
            ti = tarfile.TarInfo(f"{root}/{name}")
            ti.size, ti.mode = len(data), 0o644
            tar.addfile(ti, io.BytesIO(data))
        for name, body in text.items():
            add(name, body.encode())
        for name in copies:
            add(name, (HERE / name).read_bytes())
    print("built", out)


if __name__ == "__main__":
    main()
