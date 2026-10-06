"""Offline GUI/build verification. Does not connect a browser or submit answers."""

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase

from desktop import DesktopWindow, Preferences


class OfflineBackend:
    def __init__(self, emit):
        self.emit = emit
        self.commands = []

    def start(self):
        pass

    def request(self, name, **arguments):
        self.commands.append((name, arguments))
        if name == "shutdown":
            self.emit({"type": "closed"})

    def clean(self, text):
        return str(text)


class MemoryPreferences:
    def __init__(self):
        from desktop import DEFAULTS
        self.values = dict(DEFAULTS)

    def set(self, **values):
        self.values.update(values)


def prepared_event():
    return {"type": "prepared", "name": "Technical Writing Quiz", "pin": "12345678",
            "total": 46, "current": 1, "key_count": 45, "manual_count": 1,
            "complete": True, "can_start": True, "mode": "keys", "engine_id": "gateway",
            "source": "Wayground Quiz API (verified)", "issue": "",
            "questions": [{"question": f"Question {index + 1}", "answers": ["Verified answer"], "manual": False}
                          for index in range(45)] + [{"question": "Write your own response", "answers": [], "manual": True}]}


def run_smoke(output):
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The offscreen Qt platform does not enumerate Windows system fonts.
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    window = DesktopWindow(OfflineBackend, prefs=MemoryPreferences(), native_hotkeys=False)
    checks = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    window.show()
    app.processEvents()
    QTest.qWait(30)
    surface = window.grab().toImage()
    check("rounded window has transparent corners", surface.pixelColor(0, 0).alpha() < 32)
    check("window has visible outline", surface.pixelColor(0, surface.height() // 2) != surface.pixelColor(4, surface.height() // 2))
    check("startup requires preparation", not window.start_button.isEnabled())
    window.on_event({"type": "browser", "connected": True, "message": "Automator browser connected"})
    window.on_event({"type": "tabs", "tabs": [{"id": "test-tab", "title": "Technical Writing Quiz", "pin": "12345678", "total": 46}], "answer_tabs": []})
    window.target.setCurrentIndex(1)
    check("PIN/link entry is visible", window.pin.isVisible() and window.pin.isEnabled())
    window.on_event(prepared_event())
    check("verified preparation enables start", window.start_button.isEnabled())
    app.processEvents()
    QTest.qWait(30)
    check("wrapped startup notice stays inside window", window.rect().contains(window.notice.mapTo(window, window.notice.rect().bottomRight())))
    window.grab().save(str(destination / "startup.png"))
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    check("start delegates to browser worker", window.backend.commands[-1][0] == "start_run")
    window.on_event({"type": "started", "name": "Technical Writing Quiz", "pin": "12345678", "total": 46, "mode": "keys", "engine_id": "gateway"})
    window.on_event({"type": "question", "key": "q20", "number": 20, "total": 46, "text": "Choose the correctly punctuated sentence.", "submitted": 19, "wrong_used": 0, "wrong_limit": 0})
    window.on_event({"type": "resolved", "source": "Wayground Quiz API", "verified": True, "latency": None})
    window.on_event({"type": "answer", "answers": ["Although I like chips, I like chocolate more."], "can_wrong": False, "deliberate": False})
    check("predictions do not fabricate accuracy", window.accuracy == "—")
    check("confirmed accuracy omits unknown suffix", "·" not in window.accuracy_label.text() and "—" not in window.accuracy_label.text())
    QTest.mouseClick(window.header_pause, Qt.MouseButton.LeftButton)
    check("pause reaches worker", window.backend.commands[-1] == ("pause", {"paused": True}))
    window.on_event({"type": "paused", "paused": True})
    check("pause updates panel", window.header_pause.text() == "Resume")
    app.processEvents()
    QTest.qWait(30)
    window.grab().save(str(destination / "panel.png"))
    long_answer = "\n".join([
        "Although I like chips, I like chocolate more.",
        "This is a longer verified response with commas, parentheses, and repeated phrases that must wrap correctly.",
        "The final line remains readable and can be copied in full.",
    ] * 5)
    window.on_event({"type": "answer", "answers": [long_answer], "can_wrong": False, "deliberate": False})
    app.processEvents()
    QTest.qWait(30)
    check("answer text is preserved without truncation", window.answer_text.text() == long_answer)
    check("long answer scrolls instead of clipping", window.answer_text.verticalScrollBar().maximum() > 0)
    answer_bottom = window.answer_text.mapTo(window.answer_card, window.answer_text.rect().bottomLeft()).y()
    badge_top = window.badge_verified.mapTo(window.answer_card, window.badge_verified.rect().topLeft()).y()
    check("answer metadata stays below the text", badge_top > answer_bottom)
    viewport = window.runtime_scroll.viewport()
    check("long answer card remains visible", viewport.rect().contains(window.answer_card.mapTo(viewport, window.answer_card.rect().bottomRight())))
    check("long answer keeps runtime controls visible", viewport.rect().contains(window.now_button.mapTo(viewport, window.now_button.rect().bottomRight())))
    long_panel_height = window.height()
    window.grab().save(str(destination / "long-answer.png"))
    window.on_event({"type": "engine_active", "label": "Qwen 3.8 27B · Groq"})
    window.on_event({"type": "resolved", "source": "qwen/qwen3.8-27b", "verified": False, "latency": 0.4})
    window.on_event({"type": "answer", "answers": ["False"], "can_wrong": False, "deliberate": False})
    app.processEvents()
    QTest.qWait(30)
    check("engine fits a single line beside latency", not window.engine_label.wordWrap() and window.engine_label.width() >= window.engine_label.fontMetrics().horizontalAdvance(window.engine_label.text()))
    check("short answer restores panel height", window.height() < long_panel_height)
    footer_bottom = max(widget.mapTo(window, widget.rect().bottomLeft()).y() for widget in (window.runtime_notice, window.right_status))
    check("short answer has only normal bottom padding", 10 <= window.height() - 1 - footer_bottom <= 24)
    check("short answer panel needs no extra scrollbar", window.runtime_scroll.verticalScrollBar().maximum() == 0)
    window.grab().save(str(destination / "ai-panel.png"))
    QTest.mouseClick(window.collapse, Qt.MouseButton.LeftButton)
    check("strip preserves current game", window.compact and "Q 20/46" in window.mini_stats.text())
    check("compact strip has no header divider", not window.header_divider.isVisible())
    app.processEvents()
    QTest.qWait(30)
    check("compact status indicator is vertically centered", abs(window.dot.geometry().center().y() - window.header_pause.geometry().center().y()) <= 1)
    check("compact strip omits unknown accuracy", window.mini_stats.text() == "Q 20/46")
    window.grab().save(str(destination / "strip.png"))
    QTest.mouseClick(window.gear, Qt.MouseButton.LeftButton)
    check("settings work in compact mode", window.drawer.isVisible())
    window.drawer.wrong.setValue(3)
    check("mistake setting reaches worker", window.backend.commands[-1] == ("settings", {"wrong_limit": 3}))
    window.on_event({"type": "settings", "wrong_used": 1, "wrong_limit": 1})
    window.drawer.wrong.setValue(0)
    check("zero mistake limit reaches worker after an earlier mistake", window.backend.commands[-1] == ("settings", {"wrong_limit": 0}))
    check("zero limit preserves previous mistake history", window.wrong_used == 1 and "Limit: 0" in window.mistakes.text())
    window.drawer.dark.setChecked(True)
    app.processEvents()
    QTest.qWait(30)
    settings_image = window.drawer.grab().toImage()
    check("settings uses a custom frameless header", bool(window.drawer.windowFlags() & Qt.WindowType.FramelessWindowHint))
    check("settings has transparent rounded corners", settings_image.pixelColor(0, 0).alpha() < 32)
    check("settings has a visible outline", settings_image.pixelColor(0, settings_image.height() // 2) != settings_image.pixelColor(4, settings_image.height() // 2))
    window.drawer.grab().save(str(destination / "settings-dark.png"))
    window.drawer.dark.setChecked(False)
    app.processEvents()
    QTest.qWait(30)
    light_settings = window.drawer.grab().toImage()
    check("settings follows the selected appearance", light_settings.pixelColor(4, light_settings.height() // 2) != settings_image.pixelColor(4, settings_image.height() // 2) and light_settings.pixelColor(0, 0).alpha() < 32)
    window.drawer.grab().save(str(destination / "settings-light.png"))
    window.drawer.dark.setChecked(True)
    QTest.keyClick(window.drawer, Qt.Key.Key_Escape)
    check("closing settings leaves the running test paused", not window.drawer.isVisible() and window.running and window.paused)
    window.toggle_hidden()
    check("boss key hides without pause", not window.isVisible() and window.paused)
    window.toggle_hidden()
    check("boss key restores same strip", window.isVisible() and window.compact)
    window.on_event({"type": "manual", "message": "Enter and submit your own written response in the test tab."})
    check("written response cannot be auto submitted", not window.now_button.isEnabled() and not window.wrong_button.isEnabled())
    window.on_event({"type": "results", "stats": {"accuracy": "84%"}})
    check("accuracy comes from Wayground results", window.accuracy == "84%")
    check("compact strip shows known accuracy", window.mini_stats.text() == "Q 20/46 • 84%")
    window.on_event({"type": "finished", "complete": False})
    window.return_start()
    check("new run requires fresh preparation", not window.start_button.isEnabled())
    window.mode.setCurrentIndex(window.mode.findData("ai"))
    check("AI-only can start without prepared keys", window.start_button.isEnabled())
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    check("AI-only start first checks selected test and AI", window.backend.commands[-1][0] == "prepare" and window.backend.commands[-1][1]["mode"] == "ai")
    window.on_event({"type": "busy", "busy": True, "operation": "prepare"})
    ai_event = prepared_event()
    ai_event.update(mode="ai", total=0, key_count=0, manual_count=0, complete=False,
                    source="AI only", questions=[], issue="Question count will update from the test.")
    window.on_event(ai_event)
    check("AI start waits for availability preparation to finish", window.backend.commands[-1][0] == "prepare")
    window.on_event({"type": "busy", "busy": False, "operation": "prepare"})
    check("checked AI-only starts without keys or count", window.backend.commands[-1][0] == "start_run")
    window.close()
    app.processEvents()
    check("close disconnects through worker", window.backend.commands[-1][0] == "shutdown")
    report = {"passed": len(checks), "checks": checks, "browser_requests": 0}
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
