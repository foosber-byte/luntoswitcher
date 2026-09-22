#!/usr/bin/env python3
"""Builds dist/lunto-switcher-arch-<ver>.tar.gz: a ready-to-run PKGBUILD directory (makepkg -si)."""
import tarfile
from pathlib import Path

VERSION = "0.1.0"
HERE = Path(__file__).parent

PKGBUILD = f"""# Maintainer: Lunto Switcher
pkgname=lunto-switcher
pkgver={VERSION}
pkgrel=1
pkgdesc='Hotkey-only keyboard layout fixer (Punto Switcher style) for X11 and Wayland'
arch=('any')
license=('custom')
depends=('python' 'python-evdev' 'wl-clipboard' 'xclip' 'libx11' 'systemd')
install=lunto-switcher.install
source=('lunto_switcher.py' '70-lunto-switcher.rules' 'lunto-switcher.desktop' 'lunto-switcher-modules.conf'
        'README.md' 'config.example.toml')
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {{
  install -Dm755 lunto_switcher.py "$pkgdir/usr/bin/lunto-switcher"
  install -Dm644 70-lunto-switcher.rules "$pkgdir/usr/lib/udev/rules.d/70-lunto-switcher.rules"
  install -Dm644 lunto-switcher-modules.conf "$pkgdir/usr/lib/modules-load.d/lunto-switcher.conf"
  install -Dm644 lunto-switcher.desktop "$pkgdir/etc/xdg/autostart/lunto-switcher.desktop"
  install -Dm644 README.md "$pkgdir/usr/share/doc/lunto-switcher/README.md"
  install -Dm644 config.example.toml "$pkgdir/usr/share/doc/lunto-switcher/config.example.toml"
}}
"""

INSTALL = """post_install() {
    modprobe uinput 2>/dev/null || true
    udevadm control --reload 2>/dev/null || true
    udevadm trigger --subsystem-match=misc 2>/dev/null || true
    local u="${SUDO_USER:-}"
    if [ -n "$u" ] && [ "$u" != root ] && getent group input >/dev/null 2>&1; then
        usermod -aG input "$u" || true
        echo "lunto-switcher: user '$u' added to group 'input'. Log out and back in to activate."
    else
        echo "lunto-switcher: add your user to the 'input' group:  sudo usermod -aG input <user>  (then re-login)"
    fi
}

post_upgrade() {
    post_install
}

pre_remove() {
    pkill -f '/usr/bin/lunto-switcher' 2>/dev/null || true
}
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Lunto Switcher
Comment=Hotkey layout fixer (Pause / Shift+Pause / Alt+Pause)
Exec=sh -c 'mkdir -p "$HOME/.cache" && exec /usr/bin/lunto-switcher 2>>"$HOME/.cache/lunto-switcher.log"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def main():
    out = HERE / "dist" / f"lunto-switcher-arch-{VERSION}.tar.gz"
    out.parent.mkdir(exist_ok=True)
    root = f"lunto-switcher-arch-{VERSION}"
    text = {
        "PKGBUILD": PKGBUILD,
        "lunto-switcher.install": INSTALL,
        "lunto-switcher.desktop": DESKTOP,
        "lunto-switcher-modules.conf": "uinput\n",
    }
    copies = ["lunto_switcher.py", "70-lunto-switcher.rules", "README.md", "config.example.toml"]
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
