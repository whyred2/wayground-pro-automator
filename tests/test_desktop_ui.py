"""Offline interaction checks for the startup, panel, strip and settings windows."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionButton, QTableWidget
from desktop import DesktopWindow, Preferences
from desktop_smoke import MemoryPreferences, OfflineBackend, prepared_event


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            font = Path("C:/Windows/Fonts") / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.window = DesktopWindow(OfflineBackend, prefs=MemoryPreferences(), native_hotkeys=False)
        self.window.show()
        self.window.on_event({"type": "browser", "connected": True, "message": "Connected"})
        self.window.on_event({"type": "tabs", "tabs": [
            {"id": "first", "title": "Test one", "pin": "12345678", "total": 46},
            {"id": "second", "title": "Test two", "pin": "87654321", "total": 51},
        ], "answer_tabs": [{"id": "answers", "title": "CheatNetwork answers"}]})
        self.window.target.setCurrentIndex(1)
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()

    def ready(self):
        self.window.on_event(prepared_event())

    def running(self):
        self.ready()
        self.window.on_event({"type": "started", "name": "Test", "pin": "12345678", "total": 46,
                              "mode": "keys", "engine_id": "gateway"})
        self.app.processEvents()

    def test_switching_target_invalidates_keys_and_start(self):
        self.ready()
        self.assertTrue(self.window.start_button.isEnabled())
        self.window.target.setCurrentIndex(2)
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertFalse(self.window.view_keys.isEnabled())
        self.assertEqual(self.window.pin.text(), "87654321")
        self.assertEqual(self.window.backend.commands[-1], ("select", {"tab_id": "second"}))

    def test_prepare_uses_target_and_distinct_answer_tab(self):
        self.window.answer_tab.setCurrentIndex(1)
        QTest.mouseClick(self.window.prepare_button, Qt.MouseButton.LeftButton)
        name, arguments = self.window.backend.commands[-1]
        self.assertEqual(name, "prepare")
        self.assertEqual(arguments["tab_id"], "first")
        self.assertEqual(arguments["answer_tab_id"], "answers")
        self.assertEqual(arguments["pin"], "12345678")

    def test_busy_check_disables_start_and_allows_cancellation(self):
        self.ready()
        self.window.on_event({"type": "busy", "busy": True, "operation": "prepare"})
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertFalse(self.window.target.isEnabled())
        self.assertTrue(self.window.cancel_check.isVisible())
        QTest.mouseClick(self.window.cancel_check, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.backend.commands[-1][0], "stop")

    def test_manual_and_missing_rows_have_distinct_labels(self):
        event = prepared_event()
        event["questions"].append({"question": "Unresolved", "answers": [], "manual": False})
        self.window.on_event(event)
        self.window.show_keys()
        table = self.window.keys_dialog.findChild(QTableWidget)
        self.assertEqual(table.rowCount(), 47)
        self.assertIn("own response", table.item(45, 1).text())
        self.assertEqual(table.item(46, 1).text(), "No verified key found")

    def test_compact_settings_switch_engine_without_blocking_panel(self):
        self.running()
        self.assertTrue(self.window.isVisible())
        QTest.mouseClick(self.window.collapse, Qt.MouseButton.LeftButton)
        QTest.mouseClick(self.window.gear, Qt.MouseButton.LeftButton)
        self.assertTrue(self.window.drawer.isVisible())
        self.window.drawer.engine.setCurrentIndex(self.window.drawer.engine.findData("groq-120b"))
        self.assertEqual(self.window.backend.commands[-1], ("check_engine", {"engine_id": "groq-120b", "live": True}))
        self.assertTrue(self.window.running)

    def test_settings_matches_rounded_surface_and_has_no_system_titlebar(self):
        self.running()
        self.window.show_settings()
        QTest.qWait(30)
        drawer = self.window.drawer
        self.assertTrue(drawer.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(drawer.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(drawer.surface.objectName(), self.window.surface.objectName())
        self.assertEqual(drawer.header_title.font().pixelSize(), self.window.brand.font().pixelSize())
        image = drawer.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(0, image.height() // 2).alpha(), 0)
        self.assertNotEqual(image.pixelColor(0, image.height() // 2), image.pixelColor(4, image.height() // 2))

    def test_settings_light_theme_preserves_transparent_corners(self):
        self.window.setting(dark=False)
        self.window.show_settings()
        QTest.qWait(30)
        image = self.window.drawer.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(4, image.height() // 2).lightness(), 240)

    def test_settings_close_and_done_only_hide_settings_and_keep_run_state(self):
        self.running()
        self.window.toggle_compact()
        self.window.show_settings()
        commands = list(self.window.backend.commands)
        QTest.mouseClick(self.window.drawer.close_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.drawer.isVisible())
        self.assertTrue(self.window.running)
        self.assertTrue(self.window.compact)
        self.window.show_settings()
        QTest.mouseClick(self.window.drawer.done_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.drawer.isVisible())
        self.assertTrue(self.window.running)
        self.assertEqual(self.window.backend.commands, commands)

    def test_settings_header_can_drag_without_triggering_controls(self):
        self.window.show_settings()
        drawer = self.window.drawer
        start = drawer.pos()
        local = QPoint(36, 12)
        origin = drawer.header.mapToGlobal(local)
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(local), QPointF(origin),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(origin + QPoint(35, 20)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(local), QPointF(origin + QPoint(35, 20)),
                              Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        commands = list(self.window.backend.commands)
        self.app.sendEvent(drawer.header, press)
        self.app.sendEvent(drawer.header, move)
        self.app.sendEvent(drawer.header, release)
        self.assertEqual(drawer.pos(), start + QPoint(35, 20))
        self.assertIsNone(drawer._drag)
        self.assertEqual(self.window.backend.commands, commands)

    def test_settings_uses_body_scroll_on_small_screen_and_keeps_header_done_visible(self):
        screen = Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 500, 400)
        with patch.object(self.window, "screen", return_value=screen):
            self.window.show_settings()
            QTest.qWait(30)
        drawer = self.window.drawer
        self.assertLessEqual(drawer.height(), 384)
        self.assertGreater(drawer.scroll.verticalScrollBar().maximum(), 0)
        self.assertFalse(drawer.scroll.isAncestorOf(drawer.done_button))
        self.assertFalse(drawer.scroll.isAncestorOf(drawer.close_button))
        self.assertTrue(drawer.rect().contains(drawer.close_button.mapTo(drawer, drawer.close_button.rect().center())))
        self.assertTrue(drawer.rect().contains(drawer.done_button.mapTo(drawer, drawer.done_button.rect().center())))

    def test_settings_has_no_scrollbar_when_content_fits_available_screen(self):
        self.window.show_settings()
        QTest.qWait(50)
        if self.window.screen().availableGeometry().height() >= 750:
            self.assertEqual(self.window.drawer.scroll.verticalScrollBar().maximum(), 0)

    def test_checkbox_indicator_colors_follow_checked_unchecked_and_disabled_states(self):
        self.window.show_settings()
        checkbox = self.window.drawer.highlight
        def indicator_color():
            option = QStyleOptionButton()
            checkbox.initStyleOption(option)
            rect = checkbox.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox)
            return checkbox.grab().toImage().pixelColor(rect.left() + 4, rect.top() + 4).name()
        for dark, blue, hovered, unchecked, disabled in [
            (True, "#346adb", "#2557c7", "#161e29", "#253143"),
            (False, "#245cd6", "#1a4ab8", "#ffffff", "#dde5ef"),
        ]:
            self.window.setting(dark=dark)
            checkbox.setEnabled(True)
            checkbox.setChecked(True)
            QTest.qWait(20)
            self.assertIn(indicator_color(), (blue, hovered))
            checkbox.setChecked(False)
            self.assertEqual(indicator_color(), unchecked)
            checkbox.setChecked(True)
            checkbox.setEnabled(False)
            self.assertEqual(indicator_color(), disabled)

    def test_settings_controls_still_apply_immediately_from_compact_panel(self):
        self.running()
        self.window.toggle_compact()
        self.window.show_settings()
        drawer = self.window.drawer
        drawer.wrong.setValue(2)
        self.assertEqual(self.window.backend.commands[-1], ("settings", {"wrong_limit": 2}))
        drawer.highlight.setChecked(False)
        self.assertEqual(self.window.backend.commands[-1], ("settings", {"highlight": False}))
        drawer.boss.setCurrentText("F8")
        self.assertEqual(self.window.prefs.values["boss"], "F8")
        QTest.mouseClick(drawer.stop, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.backend.commands[-1][0], "stop")

    def test_deliberate_limit_accepts_zero_before_any_mistake(self):
        self.running()
        self.window.show_settings()
        self.window.drawer.wrong.setValue(2)
        self.window.drawer.wrong.setValue(0)
        self.assertEqual(self.window.backend.commands[-1], ("settings", {"wrong_limit": 0}))
        self.assertEqual(self.window.drawer.wrong.minimum(), 0)
        self.assertEqual(self.window.wrong_used, 0)
        self.assertEqual(self.window.mistakes.text(), "Deliberate wrong answers: 0 · Limit: 0")

    def test_deliberate_limit_accepts_keyboard_zero_after_a_mistake_and_on_reopen(self):
        self.running()
        self.window.on_event({"type": "submitted", "number": 1, "wrong_used": 1, "wrong_limit": 3})
        self.window.show_settings()
        self.assertEqual(self.window.drawer.wrong.minimum(), 0)
        edit = self.window.drawer.wrong.lineEdit()
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(edit, "0")
        QTest.keyClick(edit, Qt.Key.Key_Return)
        self.assertEqual(self.window.backend.commands[-1], ("settings", {"wrong_limit": 0}))
        self.assertEqual(self.window.wrong_used, 1)
        self.window.on_event({"type": "settings", "wrong_used": 1, "wrong_limit": 0})
        self.assertEqual(self.window.drawer.wrong.value(), 0)
        self.assertEqual(self.window.mistakes.text(), "Deliberate wrong answers: 1 · Limit: 0")
        self.window.drawer.hide()
        self.window.show_settings()
        self.assertEqual(self.window.drawer.wrong.minimum(), 0)
        self.assertEqual(self.window.drawer.wrong.value(), 0)
        self.assertEqual(self.window.wrong_used, 1)

    def test_new_run_resets_wrong_history_and_preserves_configured_zero_limit(self):
        self.running()
        self.window.on_event({"type": "settings", "wrong_used": 2, "wrong_limit": 0})
        self.window.on_event({"type": "started", "name": "Next test", "pin": "87654321", "total": 51,
                              "mode": "keys", "engine_id": "gateway"})
        self.window.show_settings()
        self.assertEqual(self.window.wrong_used, 0)
        self.assertEqual(self.window.drawer.wrong.minimum(), 0)
        self.assertEqual(self.window.drawer.wrong.value(), 0)
        self.assertEqual(self.window.prefs.values["wrong_limit"], 0)
        self.assertEqual(self.window.mistakes.text(), "Deliberate wrong answers: 0 · Limit: 0")

    def test_delay_controls_explain_variable_minimum_and_use_ten_seconds_by_default(self):
        self.assertEqual(self.window.start_delay.value(), 10.0)
        self.assertEqual(self.window.live_delay.value(), 10.0)
        self.assertEqual(self.window.start_delay_label.text(), "Min delay")
        self.assertEqual(self.window.live_delay_label.text(), "Min delay")
        for widget in (self.window.start_delay, self.window.live_delay, self.window.start_delay_label, self.window.live_delay_label):
            self.assertIn("at least this minimum", widget.toolTip())
            self.assertIn("question length", widget.toolTip())
            self.assertIn("random variation", widget.toolTip())
            self.assertIn("0 skips automatic waiting", widget.toolTip())
        self.window.start_delay.setValue(12.5)
        self.assertEqual(self.window.live_delay.value(), 12.5)
        self.assertEqual(self.window.backend.commands[-1], ("settings", {"delay": 12.5}))

    def test_boss_key_preserves_running_and_compact_state(self):
        self.running()
        self.window.toggle_compact()
        before = list(self.window.backend.commands)
        self.window.toggle_hidden()
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window.running)
        self.window.toggle_hidden()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.compact)
        self.assertEqual(self.window.backend.commands, before)

    def test_answer_predictions_never_set_accuracy(self):
        self.running()
        self.window.on_event({"type": "resolved", "source": "AI", "verified": False, "latency": 1.2})
        self.window.on_event({"type": "answer", "answers": ["Predicted"], "can_wrong": False, "deliberate": False})
        self.assertEqual(self.window.accuracy, "—")
        self.assertIn("AI prediction", self.window.source_label.text())
        self.assertIn("1.2s", self.window.source_label.text())
        self.window.on_event({"type": "results", "stats": {"accuracy": "84%"}})
        self.assertEqual(self.window.accuracy, "84%")

    def test_manual_response_disables_answer_and_wrong_buttons(self):
        self.running()
        self.window.on_event({"type": "manual", "message": "Enter your own response"})
        self.assertFalse(self.window.now_button.isEnabled())
        self.assertFalse(self.window.wrong_button.isEnabled())
        self.assertEqual(self.window.answer_text.text(), "Your written response is required")

    def test_lost_session_disables_start_with_explanation(self):
        self.ready()
        self.window.on_event({"type": "session_lost", "message": "The game changed"})
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertEqual(self.window.notice.text(), "The game changed")

    def test_unavailable_probe_does_not_change_active_engine(self):
        self.running()
        original = self.window.engine_label.text()
        self.window.on_event({"type": "provider_check", "id": "groq-120b", "available": False,
                              "pending": False, "detail": "No answer", "live": True})
        self.assertEqual(self.window.engine_label.text(), original)
        self.assertIn("Unavailable", self.window.drawer.provider_status.text())

    def test_successful_drawer_probe_updates_startup_availability(self):
        self.window.on_event({"type": "provider_check", "id": "groq-120b", "available": True,
                              "pending": False, "detail": "Test answer received", "live": False})
        self.assertEqual(self.window.engine.currentData(), "groq-120b")
        self.assertIn("Available", self.window.provider_status.text())

    def test_window_has_transparent_rounded_corners_and_visible_outline(self):
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertIn("border-radius: 12px", self.window.styleSheet())
        image = self.window.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(image.pixelColor(0, image.height() // 2).alpha(), 0)
        self.assertNotEqual(image.pixelColor(0, image.height() // 2), image.pixelColor(4, image.height() // 2))

    def test_compact_strip_has_no_header_divider(self):
        self.running()
        self.window.toggle_compact()
        self.assertFalse(self.window.header_divider.isVisible())
        self.assertEqual(self.window.header_pause.text(), "")
        self.window.toggle_compact()
        self.assertTrue(self.window.header_divider.isVisible())
        self.assertEqual(self.window.header_pause.text(), "Pause")

    def test_compact_status_dot_is_centered_and_unknown_accuracy_is_omitted(self):
        self.running()
        self.window.current, self.window.total = 3, 10
        self.window.toggle_compact()
        QTest.qWait(30)
        self.assertEqual(self.window.mini_stats.text(), "Q 3/10")
        dot_center = self.window.dot.geometry().center().y()
        pause_center = self.window.header_pause.geometry().center().y()
        self.assertLessEqual(abs(dot_center - pause_center), 1)
        self.assertEqual(self.window.dot.size().width(), 8)
        self.assertEqual(self.window.dot.size().height(), 8)
        self.window.on_event({"type": "results", "stats": {"accuracy": "84%"}})
        self.assertEqual(self.window.mini_stats.text(), "Q 3/10 • 84%")

    def test_engine_remains_on_one_line_beside_actual_latency(self):
        self.running()
        self.window.on_event({"type": "engine_active", "label": "Qwen 3.8 27B · Groq"})
        self.window.on_event({"type": "resolved", "source": "Groq", "verified": False, "latency": 1.6})
        QTest.qWait(30)
        self.assertFalse(self.window.engine_label.wordWrap())
        self.assertIn("Qwen 3.8 27B · Groq · Available", self.window.engine_label.text())
        self.assertGreaterEqual(self.window.engine_label.width(), self.window.engine_label.fontMetrics().horizontalAdvance(self.window.engine_label.text()))
        self.assertLess(self.window.engine_label.geometry().right(), self.window.last_ai_time.geometry().left())

    def test_shared_icon_buttons_have_explicit_gap_and_fit_dynamic_labels(self):
        self.running()
        self.window.on_event({"type": "answer", "answers": ["Answer"], "can_wrong": True, "deliberate": True})
        self.window.on_event({"type": "countdown", "remaining": 120.0})
        QTest.qWait(30)
        for widget in (self.window.header_pause, self.window.collapse, self.window.wrong_button, self.window.now_button):
            icon_rect, text_rect = widget.content_rects()
            self.assertEqual(text_rect.left() - icon_rect.right() - 1, widget.ICON_TEXT_GAP)
            self.assertEqual(widget.ICON_TEXT_GAP, 6)
            self.assertTrue(widget.rect().contains(icon_rect))
            self.assertTrue(widget.rect().contains(text_rect))
            self.assertEqual(widget.text(), widget.text().strip())
        self.assertEqual(self.window.wrong_button.text(), "Undo wrong")
        self.assertIn("120.0s", self.window.now_button.text())

    def test_icon_button_native_palette_preserves_primary_danger_disabled_states(self):
        self.running()
        self.window.on_event({"type": "answer", "answers": ["Answer"], "can_wrong": True, "deliberate": False})
        QTest.qWait(30)
        def has_text_color(widget, rgb):
            _, text_rect = widget.content_rects()
            image = widget.grab().toImage()
            expected = tuple(int(rgb[index:index + 2], 16) for index in (1, 3, 5))
            return any(max(abs(channel - wanted) for channel, wanted in zip(
                (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue()), expected)) <= 8
                for x in range(max(0, text_rect.left()), min(image.width(), text_rect.right() + 1))
                for y in range(max(0, text_rect.top()), min(image.height(), text_rect.bottom() + 1)))
        self.assertTrue(has_text_color(self.window.now_button, "#ffffff"))
        self.assertTrue(has_text_color(self.window.wrong_button, "#ffabb4"))
        self.window.wrong_button.setEnabled(False)
        self.assertTrue(has_text_color(self.window.wrong_button, "#8e9eb5"))

    def test_icon_buttons_preserve_keyboard_and_mouse_commands(self):
        self.running()
        self.window.on_event({"type": "answer", "answers": ["Answer"], "can_wrong": True, "deliberate": False})
        self.window.now_button.setFocus()
        QTest.keyClick(self.window.now_button, Qt.Key.Key_Space)
        self.assertEqual(self.window.backend.commands[-1][0], "answer_now")
        QTest.mouseClick(self.window.wrong_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.backend.commands[-1][0], "wrong")

    def test_game_pin_or_link_is_visible_and_preserved_when_refreshing_same_tab(self):
        self.assertTrue(self.window.pin.isVisible())
        game_url = "https://wayground.com/join?gc=12345678&source=liveDashboard"
        self.window.pin.setText(game_url)
        self.window.invalidate()
        self.window.on_event({"type": "tabs", "tabs": [
            {"id": "first", "title": "Running test", "pin": "", "total": 46},
        ], "answer_tabs": []})
        self.window.select_tab()
        self.assertEqual(self.window.pin.text(), game_url)
        self.window.prepare()
        self.assertEqual(self.window.backend.commands[-1][1]["pin"], game_url)

    def test_start_button_remains_visible_while_preparation_content_scrolls(self):
        self.ready()
        QTest.qWait(30)
        position = self.window.start_button.mapTo(self.window, self.window.start_button.rect().center())
        self.assertTrue(self.window.rect().contains(position))
        self.assertFalse(self.window.startup_scroll.isAncestorOf(self.window.start_button))
        notice_bottom = self.window.notice.mapTo(self.window, self.window.notice.rect().bottomLeft()).y()
        self.assertLess(notice_bottom, self.window.height() - 12)
        self.window.startup_scroll.verticalScrollBar().setValue(self.window.startup_scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(self.window.rect().contains(self.window.start_button.mapTo(self.window, self.window.start_button.rect().center())))

    def test_ai_only_start_checks_engine_then_starts_without_answer_keys(self):
        self.window.mode.setCurrentIndex(self.window.mode.findData("ai"))
        self.assertTrue(self.window.start_button.isEnabled())
        self.window.start_run()
        self.assertEqual(self.window.backend.commands[-1][0], "prepare")
        self.assertEqual(self.window.backend.commands[-1][1]["mode"], "ai")
        self.window.on_event({"type": "busy", "busy": True, "operation": "prepare"})
        event = prepared_event()
        event.update(mode="ai", pin="", total=0, key_count=0, manual_count=0,
                     questions=[], source="AI only", complete=False)
        self.window.on_event(event)
        self.assertNotIn("verified keys", self.window.review.text())
        self.assertNotEqual(self.window.backend.commands[-1][0], "start_run")
        self.window.on_event({"type": "busy", "busy": False, "operation": "prepare"})
        self.assertEqual(self.window.backend.commands[-1][0], "start_run")
        started = sum(name == "start_run" for name, _ in self.window.backend.commands)
        self.window.on_event({"type": "busy", "busy": False, "operation": "prepare"})
        self.assertEqual(sum(name == "start_run" for name, _ in self.window.backend.commands), started)

    def test_cancelled_ai_only_start_does_not_start_when_late_preparation_finishes(self):
        self.window.mode.setCurrentIndex(self.window.mode.findData("ai"))
        self.window.start_run()
        self.window.on_event({"type": "busy", "busy": True, "operation": "prepare"})
        self.window.command("stop")
        event = prepared_event()
        event.update(mode="ai", key_count=0, manual_count=0, questions=[], source="AI only")
        self.window.on_event(event)
        self.window.on_event({"type": "busy", "busy": False, "operation": "prepare"})
        self.assertFalse(any(name == "start_run" for name, _ in self.window.backend.commands))

    def test_changed_target_cancels_pending_ai_start(self):
        self.window.mode.setCurrentIndex(self.window.mode.findData("ai"))
        self.window.start_run()
        self.window.target.setCurrentIndex(2)
        event = prepared_event()
        event.update(mode="ai", key_count=0, manual_count=0, questions=[], source="AI only")
        self.window.on_event(event)
        self.window.on_event({"type": "busy", "busy": False, "operation": "prepare"})
        self.assertFalse(any(name == "start_run" for name, _ in self.window.backend.commands))

    def test_answer_card_preserves_long_text_and_scrolls_without_overlapping_metadata(self):
        self.running()
        answer = "Longanswerwithoutspaces" * 130 + "\n" + "A second answer option " * 30
        self.window.on_event({"type": "resolved", "source": "A provider name " * 20,
                              "verified": False, "latency": 1.2})
        self.window.on_event({"type": "answer", "answers": [answer], "can_wrong": False, "deliberate": False})
        QTest.qWait(30)
        text = self.window.answer_text
        self.assertEqual(text.text(), answer)
        self.assertGreater(text.verticalScrollBar().maximum(), 0)
        badge_top = self.window.badge_verified.mapTo(self.window.answer_card, self.window.badge_verified.rect().topLeft()).y()
        text_bottom = text.mapTo(self.window.answer_card, text.rect().bottomLeft()).y()
        self.assertGreater(badge_top, text_bottom)
        self.assertGreaterEqual(self.window.badge_verified.height(), self.window.badge_verified.sizeHint().height())
        self.assertLessEqual(text_bottom, self.window.answer_card.height())
        self.assertLessEqual(badge_top + self.window.badge_verified.height(), self.window.answer_card.height())

    def test_long_answer_grows_window_to_keep_controls_visible_when_screen_allows(self):
        self.running()
        self.window.on_event({"type": "resolved", "source": "Wayground Quiz API", "verified": True, "latency": None})
        self.window.on_event({"type": "answer", "answers": ["A long verified response with punctuation, parentheses and repeated phrases that must wrap correctly. " * 20], "can_wrong": False, "deliberate": False})
        QTest.qWait(50)
        if self.window.screen().availableGeometry().height() >= 750:
            self.assertGreater(self.window.height(), 440)
            self.assertEqual(self.window.runtime_scroll.verticalScrollBar().maximum(), 0)
            control_bottom = self.window.now_button.mapTo(self.window.runtime_scroll.viewport(), self.window.now_button.rect().bottomLeft()).y()
            self.assertLessEqual(control_bottom, self.window.runtime_scroll.viewport().height())

    def test_long_answer_then_short_answer_restores_compact_panel_height(self):
        self.running()
        self.window.on_event({"type": "resolved", "source": "Wayground Quiz API", "verified": True, "latency": None})
        self.window.on_event({"type": "answer", "answers": ["A long verified response with punctuation, parentheses and repeated phrases that must wrap correctly. " * 20], "can_wrong": False, "deliberate": False})
        QTest.qWait(50)
        tall_height = self.window.height()
        self.window.on_event({"type": "engine_active", "label": "Qwen 3.8 27B · Groq"})
        self.window.on_event({"type": "resolved", "source": "qwen/qwen3.8-27b", "verified": False, "latency": 0.4})
        self.window.on_event({"type": "answer", "answers": ["False"], "can_wrong": False, "deliberate": False})
        QTest.qWait(50)
        self.assertEqual(self.window.answer_text.text(), "False")
        self.assertLess(self.window.height(), tall_height)
        self.assertLessEqual(self.window.height(), 450)

    def test_short_answer_has_only_normal_footer_padding_and_no_panel_scrollbar(self):
        self.running()
        self.window.on_event({"type": "engine_active", "label": "Qwen 3.8 27B · Groq"})
        self.window.on_event({"type": "resolved", "source": "qwen/qwen3.8-27b", "verified": False, "latency": 0.4})
        self.window.on_event({"type": "answer", "answers": ["False"], "can_wrong": False, "deliberate": False})
        QTest.qWait(50)
        self.assertLess(self.window.height(), 440)
        self.assertEqual(self.window.runtime_scroll.verticalScrollBar().maximum(), 0)
        footer_bottom = self.window.right_status.mapTo(self.window, self.window.right_status.rect().bottomLeft()).y()
        self.assertGreaterEqual(self.window.height() - 1 - footer_bottom, 14)
        self.assertLessEqual(self.window.height() - 1 - footer_bottom, 20)

    def test_finished_panel_expands_for_choose_test_button_without_extra_blank_space(self):
        self.running()
        self.window.on_event({"type": "finished", "complete": False})
        QTest.qWait(40)
        self.assertTrue(self.window.new_test.isVisible())
        bottom = self.window.new_test.mapTo(self.window, self.window.new_test.rect().bottomLeft()).y()
        self.assertGreaterEqual(self.window.height() - 1 - bottom, 14)
        self.assertLessEqual(self.window.height() - 1 - bottom, 20)
        self.assertEqual(self.window.runtime_scroll.verticalScrollBar().maximum(), 0)

    def test_full_unknown_accuracy_omits_placeholder_and_results_keep_actual_percent(self):
        self.running()
        self.assertEqual(self.window.accuracy_label.text(), "Confirmed correct: 0 / 0")
        self.window.on_event({"type": "results", "stats": {"accuracy": "84%"}})
        self.assertIn("84%", self.window.accuracy_label.text())

    def test_waiting_state_does_not_fabricate_source_or_latency(self):
        self.running()
        self.assertFalse(self.window.badge_verified.isVisible())
        self.assertFalse(self.window.last_ai_time.isVisible())
        self.assertEqual(self.window.source_label.text(), "")
        self.assertEqual(self.window.answer_text.text(), "Waiting for an answer")

    def test_ai_unknown_total_shows_dash_and_keeps_current_question(self):
        self.window.on_event({"type": "started", "name": "Running game", "pin": "", "total": 0,
                              "current": 14, "mode": "ai", "engine_id": "gateway"})
        self.assertEqual(self.window.progress_text.text(), "Question 14 of —")
        self.window.toggle_compact()
        self.assertIn("Q 14/—", self.window.mini_stats.text())

    def test_submission_does_not_invent_confirmed_correct_answers(self):
        self.running()
        self.window.on_event({"type": "submitted", "number": 1, "wrong_used": 0, "wrong_limit": 0})
        self.assertEqual(self.window.accuracy, "—")
        self.assertEqual(self.window.accuracy_label.text(), "Confirmed correct: 0 / 0")

    def test_session_loss_keeps_a_visible_way_to_reprepare(self):
        self.running()
        self.window.on_event({"type": "session_lost", "message": "The game changed"})
        self.window.on_event({"type": "finished", "complete": False})
        self.assertTrue(self.window.new_test.isVisible())
        QTest.mouseClick(self.window.new_test, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertTrue(self.window.pin.isVisible())


class PreferencesTests(unittest.TestCase):
    def test_new_delay_default_is_ten_but_saved_minimum_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            self.assertEqual(Preferences(path).values["delay"], 10.0)
            Preferences(path).set(delay=3.5)
            self.assertEqual(Preferences(path).values["delay"], 3.5)

    def test_preferences_exclude_account_and_game_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.json"
            prefs = Preferences(path)
            prefs.set(delay=5.0, boss="F8", api_key="secret", pin="12345678", answers=["A"])
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", text)
            self.assertNotIn("12345678", text)
            loaded = Preferences(path)
            self.assertEqual(loaded.values["delay"], 5.0)
            self.assertEqual(loaded.values["boss"], "F8")


if __name__ == "__main__":
    unittest.main()
