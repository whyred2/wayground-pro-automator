# Desktop platform support

Version 4.1 adds platform-aware browser discovery, persistent directories, window behavior and native build commands for Windows, Linux and macOS.

| Platform | Current validation | Native build output |
| --- | --- | --- |
| Windows | Source tests and local Edge integration verified | `dist/4.1/WaygroundAutomator.exe` |
| Linux | Platform branches tested on Windows; native validation pending | `dist/4.1/linux-<architecture>/WaygroundAutomator` |
| macOS | Platform branches tested on Windows; native validation pending | `dist/4.1/macos-<architecture>/WaygroundAutomator.app` |

Linux and macOS support is experimental until the native checks pass. No v4.1 binaries have been built. macOS signing and notarization are not configured, and builds target the host architecture rather than a universal binary.

## Running from source

Use Python 3.10 or newer and a desktop OS supported by the installed [Qt](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html) and [Playwright](https://playwright.dev/python/docs/intro#system-requirements) versions. The desktop connector requires an installed Edge, Chrome or Chromium browser. On macOS, system-wide and user-local application bundles are detected; on Linux, browser commands are searched on `PATH`.

Linux and macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python src/main.py
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
python src/main.py
```

Linux needs a graphical desktop and Qt's system libraries. See [Qt for Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html) for your distribution. Browser system dependencies can be installed with `python -m playwright install-deps chromium` on Playwright-supported Linux distributions.

For a nonstandard browser installation, set `WAYGROUND_BROWSER` to an executable path or command, without browser arguments. Paths containing spaces are supported. On macOS, point it to the binary inside the application bundle, such as `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

The CLI's standalone-browser mode and browser integration checks additionally need `python -m playwright install chromium`. Browser automation uses the same Playwright/CDP implementation on all platforms.

## Persistent locations

| Platform | UI preferences | Dedicated browser profile |
| --- | --- | --- |
| Windows | `%LOCALAPPDATA%/WaygroundAutomator/ui.json` | `%LOCALAPPDATA%/WaygroundAutomator/BrowserProfile` |
| Linux | `$XDG_CONFIG_HOME/wayground-automator/ui.json` | `$XDG_DATA_HOME/wayground-automator/BrowserProfile` |
| macOS | `~/Library/Application Support/WaygroundAutomator/ui.json` | `~/Library/Application Support/WaygroundAutomator/BrowserProfile` |

Linux defaults to `~/.config` and `~/.local/share` when the respective XDG variables are unset or relative. Frozen applications use Playwright's native cache directory for their platform, honoring an explicit `PLAYWRIGHT_BROWSERS_PATH` override.

Personal API settings entered in the UI remain session-only. A persistent `.env` can be placed in the project root for source runs, beside the executable on Windows/Linux, or beside `WaygroundAutomator.app` on macOS.

## Window controls

The Windows Boss key remains global. On Linux and macOS, the shortcut works while the application is focused; use **Show overlay** in the tray menu to restore a hidden panel. Without a tray, the shortcut minimizes the panel so it can be restored from the taskbar or Dock. Automation and pause state are preserved.

Wayland dragging uses Qt's system-window-move API. Window placement and always-on-top behavior depend on the desktop compositor. Tray availability depends on the desktop environment; see [Qt's system tray support](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html).

## Native build preparation

Install build tools and inspect the command without compiling:

```bash
python -m pip install -r requirements-build.txt
python scripts/build_desktop.py --dry-run
```

When a build is wanted, use `python scripts/build_desktop.py` on the target OS. PyInstaller [does not cross-compile between operating systems](https://pyinstaller.org/en/stable/). Windows keeps its `.exe`, icon, version metadata and isolated DLL lookup; Linux produces a native executable; macOS produces an `.app` bundle. Pillow is included in the build requirements for macOS icon conversion. `--console` creates a diagnostic executable and `--distpath` overrides the output directory. The existing Windows entry point, `python scripts/build_windows.py`, remains available.

The **Desktop platform checks** GitHub Actions workflow is manual (`workflow_dispatch`). It installs dependencies and a test browser, runs the unit/UI suite, checks desktop startup and runs local browser fixtures on Windows, Ubuntu and macOS. It does not build or publish binaries.
