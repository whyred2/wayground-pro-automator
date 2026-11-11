"""Native per-user locations shared by the browser, desktop and frozen launcher."""

import os
from pathlib import Path
import sys


def _xdg_directory(variable, default):
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / default


def app_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "WaygroundAutomator"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WaygroundAutomator"
    return _xdg_directory("XDG_DATA_HOME", ".local/share") / "wayground-automator"


def app_config_dir():
    if sys.platform in ("win32", "darwin"):
        return app_data_dir()
    return _xdg_directory("XDG_CONFIG_HOME", ".config") / "wayground-automator"


def playwright_cache_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return _xdg_directory("XDG_CACHE_HOME", ".cache") / "ms-playwright"


def executable_directory(executable=None):
    """A personal .env belongs beside the .app bundle, not inside Contents/MacOS."""
    directory = Path(executable or sys.executable).resolve().parent
    if (directory.name == "MacOS" and directory.parent.name == "Contents"
            and directory.parent.parent.suffix == ".app"):
        return directory.parent.parent.parent
    return directory
