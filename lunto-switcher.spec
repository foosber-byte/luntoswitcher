Name:           lunto-switcher
Version:        0.1.0
Release:        1%{?dist}
Summary:        Hotkey-only keyboard layout fixer (Punto Switcher style)

License:        Custom
URL:            https://github.com/foosber-byte/luntoswitcher
Source0:        lunto_switcher.py
Source1:        70-lunto-switcher.rules
Source2:        config.example.toml
Source3:        README.md

BuildArch:      noarch
Requires:       python3 >= 3.8
Requires:       python3-evdev
Requires:       wl-clipboard
Requires:       xclip
Requires:       systemd

%description
Pause re-types the last word (up to the previous space) in the other layout,
Shift+Pause converts the selection, Alt+Pause swaps case. Works on X11 and
Wayland through evdev/uinput. The clipboard is never touched, no automatic
switching.

%prep
# nothing to unpack: sources are plain files, copied in %install

%build
# pure Python, nothing to compile

%install
rm -rf %{buildroot}
install -Dm755 %{SOURCE0} %{buildroot}%{_bindir}/lunto-switcher
install -Dm644 %{SOURCE1} %{buildroot}%{_prefix}/lib/udev/rules.d/70-lunto-switcher.rules
install -Dm644 %{SOURCE2} %{buildroot}%{_datadir}/doc/lunto-switcher/config.example.toml
install -Dm644 %{SOURCE3} %{buildroot}%{_datadir}/doc/lunto-switcher/README.md

mkdir -p %{buildroot}%{_sysconfdir}/xdg/autostart
cat > %{buildroot}%{_sysconfdir}/xdg/autostart/lunto-switcher.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Lunto Switcher
Comment=Hotkey layout fixer (Pause / Shift+Pause / Alt+Pause)
Exec=sh -c 'mkdir -p "$HOME/.cache" && exec /usr/bin/lunto-switcher 2>>"$HOME/.cache/lunto-switcher.log"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESKTOP
chmod 644 %{buildroot}%{_sysconfdir}/xdg/autostart/lunto-switcher.desktop

mkdir -p %{buildroot}%{_prefix}/lib/modules-load.d
echo uinput > %{buildroot}%{_prefix}/lib/modules-load.d/lunto-switcher.conf
chmod 644 %{buildroot}%{_prefix}/lib/modules-load.d/lunto-switcher.conf

%files
%{_bindir}/lunto-switcher
%{_prefix}/lib/udev/rules.d/70-lunto-switcher.rules
%{_sysconfdir}/xdg/autostart/lunto-switcher.desktop
%{_prefix}/lib/modules-load.d/lunto-switcher.conf
%doc %{_datadir}/doc/lunto-switcher/README.md
%{_datadir}/doc/lunto-switcher/config.example.toml

%post
modprobe uinput 2>/dev/null || :
udevadm control --reload 2>/dev/null || :
udevadm trigger --subsystem-match=misc 2>/dev/null || :
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != root ] && getent group input >/dev/null 2>&1; then
    usermod -aG input "$SUDO_USER" || :
    echo "lunto-switcher: user '$SUDO_USER' added to group 'input'. Log out and back in to activate."
else
    echo "lunto-switcher: add your user to the 'input' group:  sudo usermod -aG input <user>  (then re-login)"
fi

%preun
if [ "$1" = 0 ]; then
    pkill -f '%{_bindir}/lunto-switcher' 2>/dev/null || :
fi

%changelog
* Mon Sep 21 2026 Lunto Switcher <noreply@localhost> - 0.1.0-1
- Initial release
