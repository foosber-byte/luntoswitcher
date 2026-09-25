# Публикация в AUR (Arch User Repository)

## Подготовка

1. Создайте аккаунт на https://aur.archlinux.org/register
2. Добавьте SSH ключ в настройках AUR аккаунта
3. Установите необходимые пакеты:

```bash
sudo pacman -S base-devel git
```

## Создание PKGBUILD

Уже есть готовый `PKGBUILD` в архиве `lunto-switcher-arch-*.tar.gz`. Для AUR нужно адаптировать его:

```bash
# Создайте рабочую директорию
mkdir -p ~/aur/lunto-switcher
cd ~/aur/lunto-switcher

# Создайте PKGBUILD
cat > PKGBUILD << 'EOF'
# Maintainer: foosber <foosber@gmail.com>
pkgname=lunto-switcher
pkgver=0.1.0
pkgrel=1
pkgdesc="Hotkey-only keyboard layout fixer (Punto Switcher style) for Linux"
arch=('any')
url="https://github.com/foosber-byte/luntoswitcher"
license=('MIT')
depends=('python' 'python-evdev' 'wl-clipboard' 'xclip')
source=("$pkgname-$pkgver.tar.gz::https://github.com/foosber-byte/luntoswitcher/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')  # Замените на реальный SHA256 после создания релиза

build() {
    cd "$srcdir/luntoswitcher-$pkgver"
    # Nothing to build - pure Python
}

package() {
    cd "$srcdir/luntoswitcher-$pkgver"
    
    install -Dm755 lunto_switcher.py "$pkgdir/usr/bin/lunto-switcher"
    install -Dm644 70-lunto-switcher.rules "$pkgdir/usr/lib/udev/rules.d/70-lunto-switcher.rules"
    install -Dm644 config.example.toml "$pkgdir/usr/share/doc/$pkgname/config.example.toml"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
    
    # XDG autostart
    install -Dm644 /dev/stdin "$pkgdir/etc/xdg/autostart/lunto-switcher.desktop" << 'DESKTOP'
[Desktop Entry]
Type=Application
Name=Lunto Switcher
Comment=Hotkey layout fixer (Pause / Shift+Pause / Alt+Pause)
Exec=sh -c 'mkdir -p "$HOME/.cache" && exec /usr/bin/lunto-switcher 2>>"$HOME/.cache/lunto-switcher.log"'
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESKTOP
    
    # Module loading
    echo "uinput" > "$pkgdir/usr/lib/modules-load.d/lunto-switcher.conf"
    chmod 644 "$pkgdir/usr/lib/modules-load.d/lunto-switcher.conf"
}
EOF

# Создайте .SRCINFO
makepkg --printsrcinfo > .SRCINFO
```

## Обновление SHA256

После создания релиза v0.1.0 на GitHub:

```bash
# Скачайте архив и вычислите SHA256
wget https://github.com/foosber-byte/luntoswitcher/archive/refs/tags/v0.1.0.tar.gz
sha256sum v0.1.0.tar.gz

# Замените SKIP в PKGBUILD на полученный хэш
sed -i "s/sha256sums=('SKIP')/sha256sums=('полученный_хэш')/" PKGBUILD

# Пересоздайте .SRCINFO
makepkg --printsrcinfo > .SRCINFO
```

## Публикация в AUR

```bash
# Инициализируйте git-репозиторий
git init
git add PKGBUILD .SRCINFO

# Создайте коммит
git commit -m "Initial release: lunto-switcher 0.1.0"

# Добавьте AUR remote
git remote add aur ssh://aur@aur.archlinux.org/lunto-switcher.git

# Отправьте в AUR
git push -u aur master
```

## Обновление пакета

При выпуске новой версии:

1. Обновите `pkgver` в PKGBUILD
2. Скачайте новый архив и обновите `sha256sums`
3. Опционально увеличьте `pkgrel` (если изменения только в PKGBUILD без новой версии upstream)
4. Обновите `.SRCINFO`: `makepkg --printsrcinfo > .SRCINFO`
5. Закоммитьте и запушьте:

```bash
git add PKGBUILD .SRCINFO
git commit -m "Update to version X.Y.Z"
git push
```

## Проверка перед публикацией

```bash
# Проверьте PKGBUILD
namcap PKGBUILD

# Соберите и проверьте пакет
makepkg -si
namcap lunto-switcher-*.pkg.tar.zst

# Протестируйте установку
sudo pacman -U lunto-switcher-*.pkg.tar.zst
```

## После публикации

- Пакет появится на https://aur.archlinux.org/packages/lunto-switcher
- Пользователи смогут установить через AUR хелперы:
  - `yay -S lunto-switcher`
  - `paru -S lunto-switcher`
  - Или вручную: `git clone https://aur.archlinux.org/lunto-switcher.git && cd lunto-switcher && makepkg -si`

## Публикация в официальный Arch репозиторий

Для попадания в официальный репозиторий (community/extra):

1. Пакет должен быть популярен в AUR (много голосов/установок)
2. Нужен Trusted User (TU) или Developer, готовый его поддерживать
3. Пакет должен соответствовать [Packaging Guidelines](https://wiki.archlinux.org/title/Arch_package_guidelines)

Процесс:
1. Публикуйте в AUR и накапливайте базу пользователей
2. Когда пакет станет популярным, TU может предложить его включение
3. Или вы можете [подать заявку](https://wiki.archlinux.org/title/Trusted_Users#TU_application_process) стать TU

Реалистично рассчитывайте на AUR - попадание в официальный репозиторий требует времени и доказанной популярности.
