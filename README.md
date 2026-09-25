# Lunto Switcher

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub release](https://img.shields.io/github/v/release/foosber-byte/luntoswitcher)](https://github.com/foosber-byte/luntoswitcher/releases)

Аналог Punto Switcher для Linux (X11 и Wayland), только по горячим клавишам.

| Клавиша | Действие |
|---|---|
| Pause | последнее набранное слово (до пробела слева) перепечатывается в другой раскладке, раскладка переключается |
| Shift+Pause | то же для выделенного текста |
| Alt+Pause | инверсия регистра последнего слова или выделения |

Повторный Pause возвращает слово обратно. Буфер обмена не используется: выделение читается из PRIMARY.

## Установка (Manjaro/Arch)

```bash
tar xf lunto-switcher-arch-0.1.0.tar.gz && cd lunto-switcher-arch-0.1.0
makepkg -si     # подтянет python-evdev, wl-clipboard, xclip
# затем перелогиниться
```

## Установка (Debian/Ubuntu, .deb)

```bash
sudo apt install ./lunto-switcher_0.1.0_all.deb   # подтянет python3-evdev, wl-clipboard, xclip
# затем перелогиниться: пакет добавит вас в группу input, демон стартует автоматически
# лог: ~/.cache/lunto-switcher.log
```

## Установка (Fedora/RHEL, .rpm)

```bash
sudo dnf install ./lunto-switcher-0.1.0-1*.rpm   # подтянет python3-evdev, wl-clipboard, xclip
# затем перелогиниться: пакет добавит вас в группу input, демон стартует автоматически
# лог: ~/.cache/lunto-switcher.log
```

## Установка вручную

```bash
sudo apt install python3-evdev wl-clipboard xclip     # Fedora: python3-evdev wl-clipboard xclip
# нужен Python 3.11+ для config.toml (без него работают умолчания)

sudo usermod -aG input "$USER"                        # затем перелогиниться
sudo cp 70-lunto-switcher.rules /etc/udev/rules.d/
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo modprobe uinput && sudo udevadm control --reload && sudo udevadm trigger

install -Dm755 lunto_switcher.py ~/.local/bin/lunto-switcher
install -Dm644 lunto-switcher.service ~/.config/systemd/user/lunto-switcher.service
systemctl --user enable --now lunto-switcher
journalctl --user -u lunto-switcher -f                # логи
```

На X11 раскладка читается и переключается напрямую через libX11 (порядок групп берётся
из `layouts` в конфиге). Для GNOME/Wayland демон шлёт Super+Space:
в Settings → Keyboard должна стоять эта комбинация для смены источника ввода.

## Ограничения

- Буфер слова сбрасывается по стрелкам, Enter, Tab, клику мыши и шорткатам. Смену
  окна по Alt+Tab он тоже видит как шорткат, а по клику на панели задач сбросит клик.
  Если слово набрано до запуска демона или после ручного перемещения курсора,
  Pause выделит слово слева через Ctrl+Shift+Left (в терминалах не работает).
- Границу слова в этом запасном пути определяет приложение (знаки препинания
  могут отрезать часть слова).
- Shift+Pause читает PRIMARY: если ничего не выделено, но осталось старое выделение
  с прошлого раза, будет вставлен его перевод.
- Раскладки `us` и `ru` (таблица `ROWS` в начале скрипта).
- Если текущую раскладку нельзя узнать (`query`), демон ведёт учёт сам; ручная смена
  раскладки без него может сбить направление. Задайте `query` в конфиге.
- Wayland на GNOME: `wl-paste` может не работать без `ext-data-control` (GNOME 48+).

## Безопасность

Демон по природе видит все нажатия, поэтому:

- Буфер хранит только сканкоды текущего слова (до 64), только в памяти, и стирается
  через 15 с бездействия (`buffer_ttl` в конфиге), по Enter, Tab, стрелкам, клику
  мыши и любому шорткату (в том числе Alt+Tab).
- Ни набранный, ни выделенный текст не пишется ни в лог, ни на диск, ни в буфер обмена.
  PRIMARY после использования очищается.
- Процесс запрещает core dump и чтение своей памяти другими процессами
  (`PR_SET_DUMPABLE=0`), файлы создаются с `umask 077`.
- Поля с паролями демон не отличает. Защита от утечки в них: буфер живёт секунды
  и никуда не уходит. Не нажимайте Pause внутри парольного поля.
- Остаточный риск: доступ к `/dev/input` даёт группа `input`, а значит и любой
  процесс вашего пользователя, добавленный в эту группу, может читать клавиатуру.
  Это свойство самой группы, а не демона; на многопользовательской машине
  подумайте, кого в неё включать.
- Сетевого кода в демоне нет; проверить это можно чтением скрипта (~400 строк).

## Лицензия

MIT License - см. [LICENSE](LICENSE)

## Публикация в AUR

См. [AUR_PUBLISHING.md](AUR_PUBLISHING.md) для инструкций по публикации пакета в Arch User Repository.
