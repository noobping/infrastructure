#!/usr/bin/python3

from pathlib import Path
import shutil


REQUIRED_DESKTOP_FILES = (
    "/usr/share/applications/cinnamon-menu-editor.desktop",
    "/usr/share/applications/cinnamon-settings-screensaver.desktop",
    "/usr/share/applications/cinnamon-settings-user.desktop",
    "/usr/share/applications/cinnamon-settings-users.desktop",
)

OPTIONAL_DESKTOP_FILES = (
    "/usr/share/applications/org.freedesktop.MalcontentControl.desktop",
)

REMOVE_PATHS = (
    "/usr/bin/cinnamon-menu-editor",
    "/usr/share/cinnamon/cinnamon-settings/modules/cs_user.py",
    "/usr/share/cinnamon/cinnamon-settings-users",
    "/usr/bin/cinnamon-settings-users",
)

LOCK_AND_LOGOUT = (
    '//Lock screen button = new SystemButton(this, "xsi-lock-screen", '
    '_("Lock Screen"), _("Lock the screen")); '
    'button.actor.add_style_class_name("appmenu-system-button-lock"); '
    "button.activate = () => { this.menu.close(); Main.lockScreen(true); }; "
    "this.systemBox.add(button.actor, { y_align: St.Align.MIDDLE, y_fill: false }); "
    '//Logout button button = new SystemButton(this, "xsi-log-out", '
    '_("Log Out"), _("Leave the session")); '
    'button.actor.add_style_class_name("appmenu-system-button-logout"); '
    "button.activate = () => { this.menu.close(); this._session.LogoutRemote(0); }; "
    "this.systemBox.add(button.actor, { y_align: St.Align.MIDDLE, y_fill: false }); "
)

ACCOUNT_DETAILS = (
    "this.userIcon.set_reactive(true); "
    "this.userIcon.track_hover = true; "
    "this.userIcon.set_accessible_role(Atk.Role.BUTTON); "
    'this.userIcon.set_accessible_name(_("Account details")); '
    "this.userIcon.connect('button-press-event', () => { "
    'this.menu.toggle(); Util.spawnCommandLine("cinnamon-settings user"); });'
)


def ensure_desktop_key(path: Path, key: str, value: str) -> None:
    text = path.read_text()
    lines = text.splitlines()
    has_key = any(line.startswith(f"{key}=") for line in lines)
    updated = []
    inserted = False

    for line in lines:
        if line.startswith(f"{key}="):
            if not inserted:
                updated.append(f"{key}={value}")
                inserted = True
            continue

        updated.append(line)

        if not has_key and line.strip() == "[Desktop Entry]":
            updated.append(f"{key}={value}")
            inserted = True

    if not inserted:
        raise RuntimeError(f"{path} is missing a [Desktop Entry] section")

    path.write_text("\n".join(updated) + "\n")


def hide_desktop_file(path_str: str) -> None:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(path)

    ensure_desktop_key(path, "Hidden", "true")
    ensure_desktop_key(path, "NoDisplay", "true")


def hide_optional_desktop_file(path_str: str) -> None:
    path = Path(path_str)
    if path.exists():
        ensure_desktop_key(path, "Hidden", "true")
        ensure_desktop_key(path, "NoDisplay", "true")


def replace_or_fail(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not find {label} in Cinnamon menu applet")

    return text.replace(old, new, 1)


def patch_menu_applet(path: Path) -> None:
    text = path.read_text()
    text = replace_or_fail(text, LOCK_AND_LOGOUT, "", "lock/logout buttons")
    text = replace_or_fail(
        text,
        ACCOUNT_DETAILS,
        "this.userIcon.set_reactive(false); this.userIcon.track_hover = false;",
        "account details launcher",
    )
    path.write_text(text)


def remove_path(path_str: str) -> None:
    path = Path(path_str)
    if not path.exists():
        return

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def main() -> None:
    for path in REQUIRED_DESKTOP_FILES:
        hide_desktop_file(path)

    for path in OPTIONAL_DESKTOP_FILES:
        hide_optional_desktop_file(path)

    patch_menu_applet(Path("/usr/share/cinnamon/applets/menu@cinnamon.org/applet.js"))

    for path in REMOVE_PATHS:
        remove_path(path)


if __name__ == "__main__":
    main()
