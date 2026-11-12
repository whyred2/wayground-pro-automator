# Development

[← README](../README.md) · [Contributing](../CONTRIBUTING.md) · [Platform support](platform-support.md)

## Setup

Install the Python dependencies using the [source setup instructions](platform-support.md#running-from-source). The desktop connector uses an installed Edge, Chrome or Chromium browser; standalone CLI mode and local browser checks also need:

```console
python -m playwright install chromium
```

Run all commands below from the repository root.

## Project structure

```
src/
├── main.py          # Desktop/CLI entry point
├── desktop.py       # Native startup, panel, strip, settings and Boss key
├── desktop_backend.py # Background browser worker and verified preparation
├── desktop_engines.py # Immutable AI presets and real availability probes
├── runtime_control.py # Cooperative pause, single-answer step and stop
├── session_binding.py # Selected game/document identity checks
├── config.py        # Constants, selectors, timing, colors, AI settings
├── ai_setup.py      # AI selection and availability checks
├── ai_solver.py     # AI real-time solver (OpenAI SDK / Groq / Qwen, text & vision)
├── answer_db.py     # Separate records for each question and answer key
├── answer_tabs.py   # Existing CheatNetwork tabs and fallback ownership
├── ui.py            # Logging, Spinner, banners
├── browser.py       # Edge/Chrome detection & launch
├── api.py           # Network interception, Wayground API
├── quizit.py        # Optional Quizit Standard browser sign-in/result flow
├── scraper.py       # CheatNetwork parsing (lazy fallback)
├── matching.py      # Exact / substring / fuzzy matching
├── automation.py    # Test automation loop, highlights, results
└── tabs.py          # Tab picker (attach mode)

tests/               # Python regression checks and Node.js gateway tests
cloudflare-worker/   # AI gateway implementation and deployment configuration
```

## Tests

From the project root with the Python dependencies installed:

```powershell
python -m unittest discover -s tests
```

Gateway tests additionally require Node.js:

```powershell
node --test tests/test_gateway.mjs
```

Commit `tests/` with the source changes. These regression checks are not included in the standalone `.exe`.

Native UI interaction checks run offline with the other Python tests. For full automation checks against local fixture pages in a fresh headless Edge browser, run `python tests/browser_desktop_check.py`. This does not connect to or answer a live game.

## Native builds

Install build dependencies in the same Python environment as the project requirements:

```console
python -m pip install -r requirements-build.txt
python scripts/build_desktop.py --dry-run
```

To build the windowed executable on Windows, run `python scripts/build_windows.py`. The file is written to `dist/<version>/WaygroundAutomator.exe`. This build isolates DLL lookup from unrelated tools on PATH; `--console` produces a diagnostic build under `scratch/gui-debug`.

For native Linux/macOS builds, use `python scripts/build_desktop.py` on that OS; `--dry-run` previews the command. See [platform support](platform-support.md) for build dependencies, `.app` output, shortcut limitations and CI checks. The **Native desktop builds** workflow produces tested downloads for Windows, Linux x86_64 and macOS Intel/Apple Silicon.
