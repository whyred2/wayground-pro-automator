"""Capture documentation images from the actual UI using offline demo data."""

import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop import DesktopWindow
from desktop_smoke import MemoryPreferences, OfflineBackend


def main():
    output = ROOT / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    prefs = MemoryPreferences()
    prefs.set(mode="auto", wrong_limit=3, delay=10.0)
    window = DesktopWindow(OfflineBackend, prefs=prefs, native_hotkeys=False)
    window.show()

    def capture(widget, name):
        app.processEvents()
        QTest.qWait(80)
        if not widget.grab().save(str(output / name)):
            raise RuntimeError(f"Could not save {name}")

    window.on_event({"type": "browser", "connected": True, "message": "Automator browser connected"})
    window.on_event({"type": "tabs", "tabs": [
        {"id": "demo", "title": "Writing Practice · Demo", "pin": "12345678", "total": 30}
    ], "answer_tabs": []})
    window.target.setCurrentIndex(1)
    window.on_event({"type": "provider_check", "id": "gateway", "available": True,
                     "pending": False, "detail": "Test answer received", "live": False})
    window.on_event({"type": "status", "message": "Check the selected test before starting."})
    # Show the answer-method controls inside the normal scrollable startup window.
    app.processEvents()
    window.startup_scroll.verticalScrollBar().setValue(window.startup_scroll.verticalScrollBar().maximum())
    capture(window, "startup.png")

    window.on_event({"type": "started", "name": "Writing Practice · Demo", "pin": "12345678",
                     "total": 30, "current": 14, "mode": "auto", "engine_id": "gateway"})
    window.on_event({"type": "question", "key": "demo-q14", "number": 14, "total": 30,
                     "text": "Which sentence uses punctuation correctly?", "submitted": 13,
                     "wrong_used": 2, "wrong_limit": 3})
    window.on_event({"type": "resolved", "source": "Cloudflare Workers AI", "verified": False, "latency": 0.8})
    window.on_event({"type": "answer", "answers": ["Although it was raining, we went outside."],
                     "can_wrong": False, "deliberate": False})
    window.on_event({"type": "countdown", "remaining": 12.4})
    capture(window, "live-panel.png")
    window.toggle_compact()
    capture(window, "compact-strip.png")
    window.show_settings()
    capture(window.drawer, "settings-dark.png")
    window.drawer.dark.setChecked(False)
    capture(window.drawer, "settings-light.png")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
