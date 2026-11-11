# Desktop platform support

Version 4.1 adds platform-aware browser discovery, persistent directories, window behavior and native build commands for Windows, Linux and macOS.

| Platform | Current validation | Native build output |
| --- | --- | --- |
| Windows x86_64 | 342 native tests, 45 compiled-app checks; 15 local Edge checks | `.exe` |
| Linux x86_64 | 342 native tests and 45 compiled-app checks using XCB under Xvfb on Ubuntu 24.04 | `.tar.gz` containing an executable |
| macOS x86_64 | 342 native tests and 45 compiled-app checks on an Intel runner | `.zip` containing an `.app` |
| macOS arm64 | 342 native tests and 45 compiled-app checks on an Apple Silicon runner | `.zip` containing an `.app` |

Linux and macOS support remains experimental: the automated checks do not cover every desktop environment or a live account session. Native v4.1 binaries have been built and checked in GitHub Actions. macOS bundles are ad-hoc signed; Developer ID signing and notarization are not configured. Intel and Apple Silicon downloads are separate.

## Using the downloads

- **Windows:** open `WaygroundAutomator-v4.1-windows-x86_64.exe`.
- **Linux:** extract `WaygroundAutomator-v4.1-linux-x86_64.tar.gz` and run `./WaygroundAutomator` in a graphical desktop. The archive preserves executable permissions. This build targets Ubuntu 24.04; older distributions may require a native build. Qt's system libraries and an installed browser are required.
- **macOS:** extract the ZIP for your processor, move `WaygroundAutomator.app` to Applications and open it. The app is not notarized; macOS may require an explicit allowance in **System Settings → Privacy & Security**.

An installed Edge, Chrome or Chromium browser is required for the desktop connector on every platform. Python does not need to be installed to use the packaged app.

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

The **Native desktop builds** workflow runs on `codex/build-v*` branch pushes or manually. It runs the native test suite, builds with Python 3.12, checks the compiled app and uploads downloads for Windows x86_64, Ubuntu 24.04 x86_64 and macOS Intel/Apple Silicon. Artifacts are retained for 14 days; this workflow does not create a GitHub Release.
