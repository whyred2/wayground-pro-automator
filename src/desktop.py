"""Native desktop windows. Browser work stays on the backend's asyncio thread."""

import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import re
import sys

from PySide6.QtCore import (
    QAbstractNativeEventFilter, QObject, QPoint, QRect, QSize, Qt, QLocale, QTimer, Signal,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QShortcut, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QSizePolicy, QTextEdit, QStyle, QStyleOptionButton, QStylePainter,
)

import config
from desktop_backend import DesktopBackend
from desktop_engines import engine_catalog


ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets"

DEFAULTS = {
    "engine": "gateway", "mode": "keys", "delay": 10.0, "wrong_limit": 0,
    "highlight": True, "boss": "F2", "top": True, "dark": True,
    "cheatnetwork": True, "quizit": False,
}

MIN_DELAY_TOOLTIP = (
    "The actual delay is at least this minimum and also depends on question length, "
    "with a small random variation. 0 skips automatic waiting."
)


def load_icon(name: str, dark: bool = True) -> QIcon:
    suffix = "_dark" if dark else "_light"
    themed = ASSETS_DIR / f"{name}{suffix}.svg"
    if themed.exists():
        return QIcon(str(themed))
    path = ASSETS_DIR / f"{name}.svg"
    if path.exists():
        return QIcon(str(path))
    return QIcon()


class Preferences:
    """Only display/runtime preferences; never account secrets, keys or game data."""
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "WaygroundAutomator" / "ui.json"
        self.values = dict(DEFAULTS)
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            for key, default in DEFAULTS.items():
                if key in values and type(values[key]) is type(default):
                    self.values[key] = values[key]
        except (OSError, ValueError, TypeError):
            pass
        self.values["delay"] = min(120.0, max(0.0, self.values["delay"]))
        self.values["wrong_limit"] = min(999, max(0, self.values["wrong_limit"]))
        if self.values["boss"] not in ("F2", "F8", "Ctrl+Shift+H", "Disabled"):
            self.values["boss"] = "F2"
        if self.values["mode"] not in ("keys", "auto", "ai"):
            self.values["mode"] = "keys"

    def set(self, **values):
        self.values.update({key: value for key, value in values.items() if key in DEFAULTS})
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
            temp.replace(self.path)
        except OSError:
            pass


class EventHub(QObject):
    event = Signal(dict)


class LogStream:
    encoding = "utf-8"
    def __init__(self, emit, clean):
        self.emit, self.clean = emit, clean

    def write(self, value):
        text = self.clean(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(value)))
        if text.strip():
            self.emit({"type": "log", "message": text.strip()})
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


class BossKey(QAbstractNativeEventFilter):
    HOTKEY_ID = 0x5747
    CODES = {"F2": (0, 0x71), "F8": (0, 0x77), "Ctrl+Shift+H": (0x2 | 0x4, 0x48)}

    def __init__(self, window, enabled=True):
        super().__init__()
        self.window, self.enabled, self.current = window, enabled, "Disabled"
        self.shortcut = None
        QApplication.instance().installNativeEventFilter(self)

    def configure(self, choice):
        previous = self.current
        if self.enabled and sys.platform == "win32":
            user32 = ctypes.windll.user32
            if previous != "Disabled":
                user32.UnregisterHotKey(None, self.HOTKEY_ID)
            if choice != "Disabled":
                modifiers, key = self.CODES[choice]
                if not user32.RegisterHotKey(None, self.HOTKEY_ID, modifiers | 0x4000, key):
                    if previous != "Disabled":
                        modifiers, key = self.CODES[previous]
                        user32.RegisterHotKey(None, self.HOTKEY_ID, modifiers | 0x4000, key)
                    return False
        elif self.enabled:
            if self.shortcut:
                self.shortcut.setEnabled(False)
                self.shortcut.deleteLater()
            if choice != "Disabled":
                self.shortcut = QShortcut(QKeySequence(choice), self.window)
                self.shortcut.activated.connect(self.window.toggle_hidden)
        self.current = choice
        return True

    def nativeEventFilter(self, event_type, message):
        if self.enabled and sys.platform == "win32" and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x312 and msg.wParam == self.HOTKEY_ID:
                self.window.toggle_hidden()
                return True, 0
        return False, 0

    def close(self):
        if self.enabled and sys.platform == "win32" and self.current != "Disabled":
            ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)
        QApplication.instance().removeNativeEventFilter(self)


def label(text="", *, style="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if style:
        widget.setObjectName(style)
    return widget


class SpacedButton(QPushButton):
    """Preserve native button behavior with a consistent gap beside a named icon."""

    ICON_TEXT_GAP = 6

    def _option(self):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        return option

    def _content_size(self, option):
        text_size = option.fontMetrics.size(Qt.TextFlag.TextShowMnemonic, option.text)
        return QSize(option.iconSize.width() + self.ICON_TEXT_GAP + text_size.width(),
                     max(option.iconSize.height(), text_size.height()))

    def content_rects(self, option=None):
        option = option or self._option()
        available = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        group = QStyle.alignedRect(option.direction, Qt.AlignmentFlag.AlignCenter,
                                  self._content_size(option), available)
        icon_x = group.right() - option.iconSize.width() + 1 if option.direction == Qt.LayoutDirection.RightToLeft else group.left()
        icon_rect = QRect(icon_x, group.center().y() - option.iconSize.height() // 2 + 1,
                          option.iconSize.width(), option.iconSize.height())
        text_rect = QRect(group)
        if option.direction == Qt.LayoutDirection.RightToLeft:
            text_rect.setRight(icon_rect.left() - self.ICON_TEXT_GAP - 1)
        else:
            text_rect.setLeft(icon_rect.right() + self.ICON_TEXT_GAP + 1)
        return icon_rect, text_rect

    def sizeHint(self):
        native = super().sizeHint()
        if self.icon().isNull() or not self.text():
            return native
        option = self._option()
        styled = self.style().sizeFromContents(QStyle.ContentsType.CT_PushButton, option,
                                              self._content_size(option), self)
        return native.expandedTo(styled)

    def paintEvent(self, event):
        if self.icon().isNull() or not self.text():
            super().paintEvent(event)
            return
        option = self._option()
        painter = QStylePainter(self)
        frame = QStyleOptionButton(option)
        frame.text, frame.icon = "", QIcon()
        painter.drawControl(QStyle.ControlElement.CE_PushButton, frame)
        icon_rect, text_rect = self.content_rects(option)
        icon = QStyleOptionButton(option)
        icon.rect, icon.text = icon_rect, ""
        text = QStyleOptionButton(option)
        text.rect, text.icon = text_rect, QIcon()
        # Native labels apply the stylesheet's font/colors and pressed/disabled states.
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, icon)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, text)


def button(text="", callback=None, *, primary=False, danger=False, icon=None, icon_size=14):
    widget = SpacedButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback:
        widget.clicked.connect(callback)
    if icon:
        ico = load_icon(icon) if isinstance(icon, str) else icon
        widget.setIcon(ico)
        widget.setIconSize(QSize(icon_size, icon_size))
    if primary:
        widget.setObjectName("primary")
    elif danger:
        widget.setObjectName("danger")
    return widget


def divider():
    line = QFrame()
    line.setObjectName("divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedHeight(1)
    return line


def step_badge(number_str):
    badge = QLabel(number_str)
    badge.setObjectName("step_badge")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setFixedSize(22, 22)
    return badge


def section_header(num: int, title: str, extra_widget=None):
    container = QWidget()
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    badge = step_badge(str(num))
    h.addWidget(badge)
    title_label = label(title, style="step_title")
    h.addWidget(title_label)
    h.addStretch()
    if extra_widget:
        h.addWidget(extra_widget)
    return container


class RoundedProgressBar(QProgressBar):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self._is_dark = is_dark
        self.setFixedHeight(7)
        self.setTextVisible(False)

    def set_dark(self, dark: bool):
        self._is_dark = dark
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = h / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        track_color = QColor("#253143" if self._is_dark else "#dde5ef")
        painter.setBrush(track_color)
        painter.drawRoundedRect(0, 0, w, h, r, r)
        total = self.maximum() - self.minimum()
        if total > 0 and self.value() > self.minimum():
            ratio = max(0.0, min(1.0, (self.value() - self.minimum()) / total))
            fill_w = max(h, w * ratio)
            fill_color = QColor("#346adb" if self._is_dark else "#245cd6")
            painter.setBrush(fill_color)
            painter.drawRoundedRect(0, 0, fill_w, h, r, r)


class StatusDot(QLabel):
    """A centered status indicator whose position is independent of font metrics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dot")
        self.setFixedSize(8, 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(self.foregroundRole()))
        painter.drawEllipse(self.rect().adjusted(0, 0, -1, -1))


class AnswerText(QTextEdit):
    """Plain answer text that grows with its lines and scrolls for long answers."""

    height_changed = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setObjectName("answer_headline")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_lines)
        self.setText(text)

    def setText(self, text):
        self.setPlainText(text)
        self._fit_lines()

    def text(self):
        return self.toPlainText()

    def _fit_lines(self, *_):
        height = math.ceil(self.document().documentLayout().documentSize().height()) + 4
        height = min(220, max(self.fontMetrics().height() + 4, height))
        if height != self.height() or self.minimumHeight() != height:
            self.setFixedHeight(height)
            self.height_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_lines()


def engine_combo(engines):
    combo = QComboBox()
    for spec in engines.values():
        combo.addItem(spec.label, spec.id)
    return combo


class SettingsDrawer(QDialog):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self._drag = None
        self._fit_pending = False
        self.setWindowTitle("Settings")
        self.setObjectName("settings_window")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        outside = QVBoxLayout(self)
        outside.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame()
        self.surface.setObjectName("window_surface")
        outside.addWidget(self.surface)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)

        self.header = QWidget()
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(18, 18)
        self.header_title = label("Settings", style="brand")
        self.close_button = button("", self.hide, icon="x", icon_size=14)
        self.close_button.setObjectName("win_close")
        self.close_button.setToolTip("Close settings")
        self.close_button.setFixedSize(32, 32)
        header.addWidget(self.header_icon)
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(self.close_button)
        for widget in (self.header, self.header_icon, self.header_title):
            widget.installEventFilter(self)
        layout.addWidget(self.header)
        layout.addWidget(divider())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        ai = QVBoxLayout()
        ai.setSpacing(8)
        ai.addWidget(label("AI engine", style="step_title"))
        self.engine = engine_combo(owner.engines)
        self.engine.setCurrentIndex(max(0, self.engine.findData(owner.prefs.values["engine"])))
        self.engine.currentIndexChanged.connect(self.switch_engine)
        ai.addWidget(self.engine)
        self.provider_check = button("Check / apply engine", self.switch_engine)
        ai.addWidget(self.provider_check)
        self.provider_status = label("Checked with a real test request", style="muted", wrap=True)
        ai.addWidget(self.provider_status)
        body.addLayout(ai)
        body.addWidget(divider())

        automation = QVBoxLayout()
        automation.setSpacing(8)
        automation.addWidget(label("Automation", style="step_title"))
        wrong_row = QHBoxLayout()
        wrong_row.addWidget(label("Deliberate mistakes limit"))
        wrong_row.addStretch()
        self.wrong = QSpinBox()
        self.wrong.setRange(0, 999)
        self.wrong.setValue(owner.prefs.values["wrong_limit"])
        self.wrong.setFixedWidth(88)
        self.wrong.valueChanged.connect(lambda value: owner.setting(wrong_limit=value))
        wrong_row.addWidget(self.wrong)
        automation.addLayout(wrong_row)
        self.highlight = QCheckBox("Highlight verified correct options")
        self.highlight.setChecked(owner.prefs.values["highlight"])
        self.highlight.toggled.connect(lambda checked: owner.setting(highlight=checked))
        automation.addWidget(self.highlight)
        automation.addWidget(label("Hide / show overlay", style="muted"))
        self.boss = QComboBox()
        self.boss.addItems(["F2", "F8", "Ctrl+Shift+H", "Disabled"])
        self.boss.setCurrentText(owner.prefs.values["boss"])
        self.boss.currentTextChanged.connect(owner.set_boss_key)
        automation.addWidget(self.boss)
        automation.addWidget(label("Hiding keeps automation running.", style="muted", wrap=True))
        body.addLayout(automation)
        body.addWidget(divider())

        appearance = QVBoxLayout()
        appearance.setSpacing(8)
        appearance.addWidget(label("Appearance", style="step_title"))
        self.top = QCheckBox("Keep the panel on top")
        self.top.setChecked(owner.prefs.values["top"])
        self.top.toggled.connect(owner.set_on_top)
        appearance.addWidget(self.top)
        self.dark = QCheckBox("Dark appearance")
        self.dark.setChecked(owner.prefs.values["dark"])
        self.dark.toggled.connect(lambda checked: owner.setting(dark=checked))
        appearance.addWidget(self.dark)
        body.addLayout(appearance)
        body.addWidget(divider())

        tools_row = QHBoxLayout()
        tools_row.addWidget(button("Open test tab", lambda: owner.command("open_tab")))
        tools_row.addWidget(button("Activity log", owner.logs_dialog.show))
        body.addLayout(tools_row)
        self.stop = button("Stop automation", lambda: owner.command("stop"), danger=True)
        body.addWidget(self.stop)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(divider())
        self.done_button = button("Done", self.hide, primary=True)
        layout.addWidget(self.done_button)
        self.surface.installEventFilter(self)
        self.body.installEventFilter(self)

    def apply_theme(self):
        dark = self.owner.prefs.values["dark"]
        self.header_icon.setPixmap(load_icon("gear", dark).pixmap(18, 18))
        self.close_button.setIcon(load_icon("x", dark))

    def fit_to_screen(self):
        self.apply_theme()
        self.ensurePolished()
        self.body.ensurePolished()
        self.surface.layout().activate()
        available = self.owner.screen().availableGeometry()
        width = min(380, max(1, available.width() - 16))
        self.setMinimumWidth(min(348, width))
        content_width = max(1, width - 38)
        body_height = self.body.layout().heightForWidth(content_width)
        if body_height < 0:
            body_height = self.body.sizeHint().height()
        # Measure the actual styled header/footer and padding rather than guessing them.
        overhead = self.surface.sizeHint().height() - self.scroll.sizeHint().height()
        height = body_height + overhead
        self.resize(width, min(max(360, height), max(1, available.height() - 16)))
        if self.isVisible():
            self.move(max(available.left() + 8, min(self.x(), available.right() - self.width() - 8)),
                      max(available.top() + 8, min(self.y(), available.bottom() - self.height() - 8)))

    def _schedule_fit(self):
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._settle_size)

    def _settle_size(self):
        self._fit_pending = False
        if self.isVisible():
            self.fit_to_screen()

    def switch_engine(self, *_):
        if self.owner.busy:
            self.provider_status.setText("Wait for the current check to finish.")
            return
        engine_id = self.engine.currentData()
        self.owner.command("check_engine", engine_id=engine_id, live=self.owner.running)

    def showEvent(self, event):
        self.stop.setEnabled(self.owner.running or self.owner.busy)
        self.wrong.setMinimum(0)
        self.wrong.setMaximum(max(self.owner.wrong_used, self.owner.total or 999))
        super().showEvent(event)
        self._schedule_fit()

    def eventFilter(self, watched, event):
        if event.type() == event.Type.LayoutRequest:
            self._schedule_fit()
        if watched in (self.header, self.header_icon, self.header_title):
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == event.Type.MouseMove and self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag)
            elif event.type() == event.Type.MouseButtonRelease:
                self._drag = None
        return super().eventFilter(watched, event)


class DesktopWindow(QMainWindow):
    def __init__(self, backend_factory=DesktopBackend, *, prefs=None, native_hotkeys=True, capture_logs=False):
        super().__init__()
        self.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        self.setWindowTitle(f"Wayground Pro v{config.VERSION}")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.ico")))
        self.prefs = prefs or Preferences()
        self.engines = engine_catalog()
        self.hub = EventHub(self)
        self.hub.event.connect(self.on_event)
        self.backend = backend_factory(self.hub.event.emit)
        self.busy = self.running = self.paused = self.compact = self.closing = self.allow_close = False
        self.connected = False
        self.prepared = None
        self._pending_start = None
        self._launch_pending = False
        self._runtime_fit_pending = False
        self._last_target_id = ""
        self.tabs = {}
        self.current = self.total = self.wrong_used = self.submitted_count = 0
        self.accuracy = "—"
        self._drag = None
        self._streams = None
        self.keys_dialog = None
        self.logs_dialog = QDialog(self)
        self.logs_dialog.setWindowTitle("Activity")
        self.logs_dialog.resize(780, 400)
        logs_layout = QVBoxLayout(self.logs_dialog)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1500)
        logs_layout.addWidget(self.logs)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        root = QFrame()
        root.setObjectName("window_surface")
        self.surface = root
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)

        # ── Global Top Header ────────────────────────────────
        self.header = QWidget()
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(18, 18)
        self.brand_icon.setScaledContents(True)

        self.dot = StatusDot()
        self.dot.hide()

        self.brand = label("Wayground Pro", style="brand")
        self.brand_ver = label(f"v{config.VERSION}", style="brand_version")
        self.mini_stats = label("", style="muted")

        header.addWidget(self.brand_icon)
        header.addWidget(self.dot)
        header.addWidget(self.brand)
        header.addWidget(self.brand_ver)
        header.addWidget(self.mini_stats)
        header.addStretch()

        self.header_prep_label = label("Prepare your test", style="muted")
        self.header_pause = button("Pause", self.toggle_pause, icon="pause", icon_size=13)
        self.gear = button("", self.show_settings, icon="gear", icon_size=16)
        self.gear.setToolTip("Settings")
        self.gear.setFixedSize(32, 32)
        self.collapse = button("Minimize", self.toggle_compact, icon="minus", icon_size=13)
        self.win_min = button("", self.showMinimized, icon="minus", icon_size=13)
        self.win_min.setObjectName("win_min")
        self.win_min.setToolTip("Minimize to taskbar")
        self.win_min.setFixedSize(32, 32)
        self.win_close = button("", self.close, icon="x", icon_size=14)
        self.win_close.setObjectName("win_close")
        self.win_close.setToolTip("Close")
        self.win_close.setFixedSize(32, 32)

        self.header_pause.hide()
        self.collapse.hide()

        header.addWidget(self.header_prep_label)
        header.addWidget(self.header_pause)
        header.addWidget(self.gear)
        header.addWidget(self.collapse)
        header.addWidget(self.win_min)
        header.addWidget(self.win_close)

        self.header.installEventFilter(self)
        self.brand.installEventFilter(self)
        self.brand_icon.installEventFilter(self)
        self.brand_ver.installEventFilter(self)
        self.mini_stats.installEventFilter(self)
        layout.addWidget(self.header)
        self.header_divider = divider()
        layout.addWidget(self.header_divider)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._build_startup()
        self._build_runtime()

        self.drawer = SettingsDrawer(self)
        self.hotkey = BossKey(self, enabled=native_hotkeys)
        if not self.hotkey.configure(self.prefs.values["boss"]):
            self.hotkey.current = "Disabled"
            self.notice.setText("Boss key is already used by another app. Choose another shortcut in Settings.")
        self.tray = None
        if native_hotkeys and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip("Wayground Pro — show overlay")
            menu = QMenu(self)
            menu.addAction("Show overlay", self.show_overlay)
            menu.addAction("Exit", self.close)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.show_overlay() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

        self.apply_theme()
        self.set_on_top(self.prefs.values["top"], save=False)
        self.resize(580, 540)

        # Apply dark titlebar on Windows
        if sys.platform == "win32":
            try:
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                hwnd = int(self.winId())
                val = ctypes.c_int(2 if self.prefs.values["dark"] else 0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))
            except Exception:
                pass

        if capture_logs:
            self._streams = (sys.stdout, sys.stderr)
            sys.stdout = sys.stderr = LogStream(self.hub.event.emit, self.backend.clean)
        self.backend.start()

    def _build_startup(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Title: Choose a test to automate
        page_title = label("Choose a test to automate", style="page_title")
        layout.addWidget(page_title)

        # ── Section 1: Connect browser ────────────────────────
        sec1_w = QWidget()
        sec1_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sec1 = QVBoxLayout(sec1_w)
        sec1.setContentsMargins(0, 0, 0, 0)
        sec1.setSpacing(8)
        sec1.addWidget(section_header(1, "Connect browser"))
        row1 = QHBoxLayout()
        self.browser_status = label("Not connected", style="muted")
        self.connect_button = button("Connect browser", lambda: self.command("connect"), primary=True)
        row1.addWidget(self.browser_status)
        row1.addStretch()
        row1.addWidget(self.connect_button)
        sec1.addLayout(row1)
        layout.addWidget(sec1_w)
        layout.addWidget(divider())

        # ── Section 2: Select test tab ────────────────────────
        sec2_w = QWidget()
        sec2_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sec2 = QVBoxLayout(sec2_w)
        sec2.setContentsMargins(0, 0, 0, 0)
        sec2.setSpacing(6)
        self.refresh = button("Refresh tabs", lambda: self.command("refresh"), icon="refresh", icon_size=13)
        self.refresh.setObjectName("link_button")
        sec2.addWidget(section_header(2, "Select test tab", self.refresh))

        sec2.addWidget(label("Wayground game tab", style="muted"))

        self.target = QComboBox()
        self.target.setMinimumContentsLength(25)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.currentIndexChanged.connect(self.select_tab)
        sec2.addWidget(self.target)

        self.tab_hint = label("No game tabs found. Open a Wayground game tab in the browser.", style="muted", wrap=True)
        sec2.addWidget(self.tab_hint)

        sec2.addWidget(label("Game PIN or game link", style="muted"))
        self.pin = QLineEdit()
        self.pin.setPlaceholderText("Enter a PIN or paste this game's Wayground link")
        self.pin.setClearButtonEnabled(True)
        self.pin.textEdited.connect(self.invalidate)
        sec2.addWidget(self.pin)

        layout.addWidget(sec2_w)
        layout.addWidget(divider())

        # ── Section 3: Prepare answers ────────────────────────
        sec3_w = QWidget()
        sec3_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sec3 = QVBoxLayout(sec3_w)
        sec3.setContentsMargins(0, 0, 0, 0)
        sec3.setSpacing(8)
        sec3.addWidget(section_header(3, "Prepare answers"))

        grid = QHBoxLayout()
        grid.setSpacing(16)

        col_left = QVBoxLayout()
        col_left.setSpacing(4)
        col_left.addWidget(label("Answer method", style="muted"))
        self.mode = QComboBox()
        for text, key in [("Verified answer keys only", "keys"), ("Keys + AI fallback", "auto"), ("AI only", "ai")]:
            self.mode.addItem(text, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.prefs.values["mode"])))
        self.mode.currentIndexChanged.connect(self.change_mode)
        col_left.addWidget(self.mode)
        grid.addLayout(col_left, 1)

        col_right = QVBoxLayout()
        col_right.setSpacing(4)
        col_right.addWidget(label("AI engine", style="muted"))
        self.engine = engine_combo(self.engines)
        self.engine.setCurrentIndex(max(0, self.engine.findData(self.prefs.values["engine"])))
        self.engine.currentIndexChanged.connect(self.startup_engine_changed)
        col_right.addWidget(self.engine)
        grid.addLayout(col_right, 1)

        sec3.addLayout(grid)

        row3 = QHBoxLayout()
        self.provider_status = label("AI disabled" if self.mode.currentData() == "keys" else "Not checked", style="muted")
        self.cancel_check = button("Cancel check", lambda: self.command("stop"))
        self.cancel_check.hide()
        self.prepare_button = button("Check test and answers", self.prepare)
        self.probe_button = button("Check availability", lambda: self.command("check_engine", engine_id=self.engine.currentData()))
        self.probe_button.hide()
        row3.addWidget(self.provider_status)
        row3.addWidget(self.cancel_check)
        row3.addStretch()
        row3.addWidget(self.prepare_button)
        sec3.addLayout(row3)

        # Review card & view keys button (shown after prepared)
        self.review = label("Select a game tab to check its answer keys.", style="review", wrap=True)
        self.review.hide()
        sec3.addWidget(self.review)

        self.view_keys = button("View question keys", self.show_keys)
        self.view_keys.hide()
        sec3.addWidget(self.view_keys)

        # Advanced sources (hidden container)
        self.advanced_toggle = QPushButton("Answer sources ▸")
        self.advanced_toggle.setObjectName("link_button")
        self.advanced_toggle.clicked.connect(self.toggle_advanced)
        sec3.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        advanced = QFormLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setVerticalSpacing(8)
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("Optional Wayground teacher quiz URL")
        self.source_url.textEdited.connect(self.invalidate)
        advanced.addRow("Source quiz URL", self.source_url)
        self.answer_tab = QComboBox()
        self.answer_tab.addItem("Auto-detect existing answer tab", "")
        self.answer_tab.currentIndexChanged.connect(self.invalidate)
        advanced.addRow("CheatNetwork tab", self.answer_tab)
        self.cheatnetwork = QCheckBox("Use CheatNetwork when direct lookup has no keys")
        self.cheatnetwork.setChecked(self.prefs.values["cheatnetwork"])
        self.quizit = QCheckBox("Try Quizit Standard (may require its own sign-in)")
        self.quizit.setChecked(self.prefs.values["quizit"])
        self.cheatnetwork.toggled.connect(self.invalidate)
        self.quizit.toggled.connect(self.invalidate)
        advanced.addRow(self.cheatnetwork)
        advanced.addRow(self.quizit)
        self.advanced.hide()
        sec3.addWidget(self.advanced)

        layout.addWidget(sec3_w)
        layout.addStretch(1)

        # ── Footer ────────────────────────────────────────────
        footer_w = QWidget()
        footer_w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        footer = QHBoxLayout(footer_w)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        self.notice = label("Choose a game tab.", style="muted", wrap=True)
        footer.addWidget(self.notice, 1)

        self.start_delay_label = label("Min delay", style="muted")
        self.start_delay_label.setToolTip(MIN_DELAY_TOOLTIP)
        footer.addWidget(self.start_delay_label)
        self.start_delay = self.delay_spin()
        footer.addWidget(self.start_delay)

        self.start_button = button("Start automation", self.start_run, primary=True)
        footer.addWidget(self.start_button)
        scroll.setWidget(content)
        self.startup_scroll = scroll
        startup = QWidget()
        startup_layout = QVBoxLayout(startup)
        startup_layout.setContentsMargins(0, 0, 0, 0)
        startup_layout.setSpacing(12)
        startup_layout.addWidget(scroll, 1)
        startup_layout.addWidget(divider())
        startup_layout.addWidget(footer_w)
        self.stack.addWidget(startup)
        self._startup_enabled()

    def _build_runtime(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.runtime_scroll = scroll
        panel = QWidget()
        self.runtime_panel = panel
        panel.installEventFilter(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(12)

        # 1. Info Subheader: Engine & Request time
        info_row = QHBoxLayout()
        self.game_name = label("", style="brand", wrap=True)
        self.game_name.hide()
        self.engine_label = label("Engine: awaiting selection", style="muted")
        self.engine_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.last_ai_time = label("", style="muted")
        self.last_ai_time.hide()
        info_row.addWidget(self.engine_label, 1)
        info_row.addWidget(self.last_ai_time)
        layout.addLayout(info_row)

        # 2. Question progress row
        prog_row = QHBoxLayout()
        self.progress_text = label("Question — of —", style="page_title")
        self.progress_percent = label("0%", style="semi_muted")
        prog_row.addWidget(self.progress_text)
        prog_row.addStretch()
        prog_row.addWidget(self.progress_percent)
        layout.addLayout(prog_row)

        # 3. Slim Rounded Progress bar
        self.progress = RoundedProgressBar(self, is_dark=self.prefs.values["dark"])
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # 4. Confirmed correct & Deliberate mistakes metrics
        metrics = QHBoxLayout()
        self.accuracy_label = label("Confirmed correct: 0 / 0", style="muted")
        self.mistakes = label("Deliberate wrong answers: 0 · Limit: 0", style="muted")
        metrics.addWidget(self.accuracy_label)
        metrics.addStretch()
        metrics.addWidget(self.mistakes)
        layout.addLayout(metrics)

        # 5. Answer Card (QFrame#card)
        card = QFrame()
        self.answer_card = card
        card.installEventFilter(self)
        card.setObjectName("card")
        answers = QVBoxLayout(card)
        answers.setContentsMargins(16, 15, 16, 15)
        answers.setSpacing(8)

        card_title = label("Current answer", style="muted")
        answers.addWidget(card_title)

        self.question_text = label("Reading the current question…", style="muted", wrap=True)
        self.question_text.hide()
        answers.addWidget(self.question_text)

        self.answer_text = AnswerText("Waiting for an answer")
        self.answer_text.height_changed.connect(self._schedule_runtime_fit)
        answers.addWidget(self.answer_text)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        self.badge_verified = label("", style="badge_verified")
        self.badge_verified.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.badge_verified.hide()
        self.source_label = label("", style="semi_muted", wrap=True)
        self.source_label.setMinimumWidth(0)
        source_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        source_policy.setHeightForWidth(True)
        self.source_label.setSizePolicy(source_policy)
        self.source_label.hide()
        badge_row.addWidget(self.badge_verified)
        badge_row.addWidget(self.source_label, 1)
        answers.addLayout(badge_row)
        layout.addWidget(card)

        # 6. Horizontal Divider below card
        layout.addWidget(divider())

        # 7. Controls row
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.wrong_button = button("Wrong answer here", lambda: self.command("wrong"), danger=True, icon="circle_x", icon_size=14)
        self.now_button = button("Answer now", lambda: self.command("answer_now"), primary=True, icon="fast_forward", icon_size=14)
        controls.addWidget(self.wrong_button)
        controls.addWidget(self.now_button)
        controls.addStretch()
        self.live_delay_label = label("Min delay", style="muted")
        self.live_delay_label.setToolTip(MIN_DELAY_TOOLTIP)
        controls.addWidget(self.live_delay_label)
        self.live_delay = self.delay_spin()
        controls.addWidget(self.live_delay)
        layout.addLayout(controls)

        # 8. Status footer
        status_row = QHBoxLayout()
        self.runtime_notice = label("Waiting to submit…", style="muted", wrap=True)
        notice_policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        notice_policy.setHeightForWidth(True)
        self.runtime_notice.setSizePolicy(notice_policy)
        self.right_status = label("Results confirmed by the test", style="muted")
        status_row.addWidget(self.runtime_notice, 1)
        status_row.addWidget(self.right_status)
        layout.addLayout(status_row)

        # Retain hidden buttons for test / command compatibility
        self.stop_button = QPushButton(panel)
        self.stop_button.setText("Stop")
        self.stop_button.clicked.connect(lambda: self.command("stop"))
        self.stop_button.hide()

        self.new_test = button("Choose / check test", self.return_start)
        layout.addWidget(self.new_test)
        self.new_test.hide()

        layout.addStretch(1)
        scroll.setWidget(panel)
        self.stack.addWidget(scroll)
        self.wrong_button.setEnabled(False)
        self.now_button.setEnabled(False)


    def delay_spin(self):
        spin = QDoubleSpinBox()
        spin.setRange(0, 120)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setSuffix(" s")
        spin.setToolTip(MIN_DELAY_TOOLTIP)
        spin.setValue(self.prefs.values["delay"])
        spin.valueChanged.connect(lambda value: self.setting(delay=value))
        spin.setFixedWidth(102)
        return spin

    def command(self, name, **arguments):
        if not self.closing:
            if name in ("stop", "shutdown"):
                self._pending_start = None
                self._launch_pending = False
            self.backend.request(name, **arguments)

    def setting(self, **values):
        self.prefs.set(**values)
        self.command("settings", **values)
        if "delay" in values:
            for spin in (self.start_delay, self.live_delay):
                spin.blockSignals(True)
                spin.setValue(values["delay"])
                spin.blockSignals(False)
        if "dark" in values:
            self.apply_theme()
            if sys.platform == "win32":
                try:
                    hwnd = int(self.winId())
                    val = ctypes.c_int(2 if values["dark"] else 0)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
                except Exception:
                    pass
        if "wrong_limit" in values:
            self.mistakes.setText(f"Deliberate wrong answers: {self.wrong_used} · Limit: {values['wrong_limit']}")

    def apply_theme(self):
        dark = self.prefs.values["dark"]
        suffix = "_dark.svg" if dark else "_light.svg"
        chevron_down_url = (ASSETS_DIR / f"chevron_down{suffix}").resolve().as_posix()
        spin_up_url = (ASSETS_DIR / f"spin_up{suffix}").resolve().as_posix()
        spin_down_url = (ASSETS_DIR / f"spin_down{suffix}").resolve().as_posix()
        check_url = (ASSETS_DIR / "check.svg").resolve().as_posix()

        self.gear.setIcon(load_icon("gear", dark))
        self.header_pause.setIcon(load_icon("play" if self.paused else "pause", dark))
        self.collapse.setIcon(load_icon("maximize" if self.compact else "minus", dark))
        self.refresh.setIcon(load_icon("refresh", dark))
        self.wrong_button.setIcon(load_icon("circle_x", dark))
        self.now_button.setIcon(load_icon("fast_forward", dark))
        if hasattr(self, "brand_icon"):
            self.brand_icon.setPixmap(load_icon("layers", dark).pixmap(18, 18))
        if hasattr(self, "win_min"):
            self.win_min.setIcon(load_icon("minus", dark))
        if hasattr(self, "win_close"):
            self.win_close.setIcon(load_icon("x", dark))
        if hasattr(self, "progress") and hasattr(self.progress, "set_dark"):
            self.progress.set_dark(dark)

        if dark:
            bg = "#1b2431"
            card = "#253143"
            input_bg = "#161e29"
            fg = "#edf2fa"
            muted = "#8e9eb5"
            semi_muted = "#b0bdd0"
            edge = "#3b485c"
            card_edge = "#3b485c"
            primary = "#346adb"
            primary_hover = "#2557c7"
            primary_disabled = "#253143"
            danger = "#ffabb4"
            danger_bg = "#422733"
            badge_bg = "#253c30"
            badge_border = "#3a5947"
            badge_fg = "#87dfaa"
            badge_ai_bg = "#22314a"
            badge_ai_border = "#3d5580"
            badge_ai_fg = "#85b0ff"
            spin_btn_hover = "#344761"
        else:
            bg = "#ffffff"
            card = "#f3f6fa"
            input_bg = "#ffffff"
            fg = "#1c2940"
            muted = "#58677c"
            semi_muted = "#58677c"
            edge = "#dde5ef"
            card_edge = "#dde5ef"
            primary = "#245cd6"
            primary_hover = "#1a4ab8"
            primary_disabled = "#dde5ef"
            danger = "#aa3542"
            danger_bg = "#fff1f3"
            badge_bg = "#edf7f0"
            badge_border = "#c4e7cf"
            badge_fg = "#267449"
            badge_ai_bg = "#eff5ff"
            badge_ai_border = "#c2d8ff"
            badge_ai_fg = "#245cd6"
            spin_btn_hover = "#e2e8f0"

        self.setStyleSheet(f"""
            QWidget {{
                font-family: 'Segoe UI';
                font-size: 13px;
                color: {fg};
            }}
            QMainWindow {{
                background: transparent;
            }}
            QFrame#window_surface {{
                background-color: {bg};
                border: 1px solid {edge};
                border-radius: 12px;
            }}
            QDialog, QScrollArea, QScrollArea > QWidget > QWidget {{
                background-color: {bg};
            }}
            QDialog#settings_window {{
                background: transparent;
            }}
            QLabel {{
                background: transparent;
                color: {fg};
            }}
            QLabel#page_title {{
                font-size: 20px;
                font-weight: 700;
                color: {fg};
            }}
            QLabel#step_title {{
                font-size: 14px;
                font-weight: 600;
                color: {fg};
            }}
            QLabel#step_badge {{
                background-color: {edge};
                color: {semi_muted};
                font-size: 11px;
                font-weight: 700;
                border-radius: 11px;
            }}
            QLabel#brand {{
                font-size: 15px;
                font-weight: 700;
                color: {fg};
            }}
            QLabel#brand_version {{
                font-size: 13px;
                font-weight: 400;
                color: {muted};
            }}
            QLabel#dot {{
                color: #87dfaa;
                font-size: 16px;
            }}
            QLabel#muted {{
                color: {muted};
                font-size: 12px;
            }}
            QLabel#semi_muted {{
                color: {semi_muted};
                font-size: 12px;
            }}
            QLabel#connected_green {{
                color: #87dfaa;
                font-size: 13px;
                font-weight: 500;
            }}
            QLabel#badge_verified {{
                background-color: {badge_bg};
                border: 1px solid {badge_border};
                color: {badge_fg};
                font-size: 11px;
                font-weight: 600;
                border-radius: 4px;
                padding: 2px 7px;
            }}
            QLabel#badge_ai {{
                background-color: {badge_ai_bg};
                border: 1px solid {badge_ai_border};
                color: {badge_ai_fg};
                font-size: 11px;
                font-weight: 600;
                border-radius: 4px;
                padding: 2px 7px;
            }}
            QTextEdit#answer_headline {{
                background: transparent;
                border: none;
                font-size: 17px;
                font-weight: 500;
                padding: 0;
                color: {fg};
            }}
            QLabel#review {{
                background-color: {card};
                border: 1px solid {card_edge};
                border-radius: 8px;
                padding: 12px;
                color: {fg};
            }}
            QFrame#card {{
                background-color: {card};
                border: 1px solid {card_edge};
                border-radius: 8px;
            }}
            QFrame#divider {{
                background-color: {edge};
                border: none;
                max-height: 1px;
            }}
            QPushButton {{
                background-color: {card};
                border: 1px solid {card_edge};
                border-radius: 6px;
                padding: 8px 12px;
                color: {fg};
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                border-color: #85b0ff;
            }}
            QPushButton:disabled {{
                color: {muted};
                background-color: {bg};
                border-color: {edge};
            }}
            QPushButton#primary {{
                background-color: {primary};
                border: 1px solid {primary};
                color: #ffffff;
                font-weight: 600;
            }}
            QPushButton#primary:hover {{
                background-color: {primary_hover};
                border-color: {primary_hover};
            }}
            QPushButton#primary:disabled {{
                background-color: {primary_disabled};
                border-color: {primary_disabled};
                color: {muted};
            }}
            QPushButton#secondary {{
                background-color: {card};
                border: 1px solid {card_edge};
                color: {fg};
            }}
            QPushButton#secondary:hover {{
                border-color: #85b0ff;
            }}
            QPushButton#win_min, QPushButton#win_close {{
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px;
            }}
            QPushButton#win_min:hover {{
                background-color: {card};
            }}
            QPushButton#win_close:hover {{
                background-color: #dc2626;
            }}
            QPushButton#link_button {{
                background: transparent;
                border: none;
                color: #85b0ff;
                font-weight: 500;
                font-size: 12px;
                padding: 2px 6px;
            }}
            QPushButton#link_button:hover {{
                color: #b8d2ff;
                text-decoration: underline;
            }}
            QPushButton#danger {{
                background-color: {card};
                border: 1px solid {card_edge};
                color: {danger};
            }}
            QPushButton#danger:hover {{
                border-color: {danger};
                background-color: {danger_bg};
            }}
            QPushButton#danger:disabled {{
                color: {muted};
                border-color: {edge};
            }}
            QComboBox {{
                background-color: {input_bg};
                border: 1px solid {edge};
                border-radius: 6px;
                padding: 7px 10px;
                padding-right: 28px;
                color: {fg};
                font-size: 12px;
                min-height: 18px;
            }}
            QComboBox:hover {{
                border-color: #85b0ff;
            }}
            QComboBox:focus {{
                border-color: #85b0ff;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url({chevron_down_url});
                width: 12px;
                height: 12px;
            }}
            QComboBox QAbstractItemView, QTableWidget, QPlainTextEdit {{
                background-color: {card};
                color: {fg};
                selection-background-color: {primary};
                selection-color: #ffffff;
                border: 1px solid {edge};
                border-radius: 6px;
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 26px;
                padding: 4px 8px;
                border-radius: 4px;
                color: {fg};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {primary};
                color: #ffffff;
            }}
            QLineEdit {{
                background-color: {input_bg};
                border: 1px solid {edge};
                border-radius: 6px;
                padding: 7px 10px;
                color: {fg};
                font-size: 12px;
                min-height: 18px;
            }}
            QLineEdit:hover {{
                border-color: #60728c;
            }}
            QLineEdit:focus {{
                border-color: #85b0ff;
            }}
            QSpinBox, QDoubleSpinBox {{
                background-color: {input_bg};
                border: 1px solid {edge};
                border-radius: 6px;
                padding: 6px 10px;
                padding-right: 24px;
                color: {fg};
                font-size: 12px;
                min-height: 18px;
            }}
            QSpinBox:hover, QDoubleSpinBox:hover {{
                border-color: #85b0ff;
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{
                border-color: #85b0ff;
            }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 18px;
                height: 14px;
                border-left: 1px solid {edge};
                border-bottom: 1px solid {edge};
                background: {card};
                border-top-right-radius: 5px;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
                background: {spin_btn_hover};
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: url({spin_up_url});
                width: 9px;
                height: 7px;
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 18px;
                height: 14px;
                border-left: 1px solid {edge};
                background: {card};
                border-bottom-right-radius: 5px;
            }}
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {spin_btn_hover};
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: url({spin_down_url});
                width: 9px;
                height: 7px;
            }}
            QProgressBar {{
                background-color: {card};
                border: none;
                border-radius: 4px;
                height: 7px;
            }}
            QProgressBar::chunk {{
                background-color: {primary};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {edge};
                min-height: 28px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #85b0ff;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
                background: transparent;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                height: 0px;
            }}
            QCheckBox {{
                spacing: 8px;
                color: {fg};
            }}
            QCheckBox:disabled {{
                color: {muted};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                background-color: {input_bg};
                border: 1px solid {edge};
                border-radius: 4px;
            }}
            QCheckBox::indicator:hover {{
                border-color: {primary};
            }}
            QCheckBox::indicator:checked {{
                background-color: {primary};
                border-color: {primary};
                image: url('{check_url}');
            }}
            QCheckBox::indicator:checked:hover {{
                background-color: {primary_hover};
                border-color: {primary_hover};
            }}
            QCheckBox::indicator:disabled {{
                background-color: {card};
                border-color: {edge};
            }}
            QCheckBox::indicator:checked:disabled {{
                background-color: {primary_disabled};
                border-color: {edge};
            }}
            QHeaderView::section {{
                background-color: {bg};
                color: {fg};
                padding: 8px;
                border: 1px solid {edge};
            }}
        """)
        self.drawer.apply_theme()

    def invalidate(self, *_):
        self._pending_start = None
        self._launch_pending = False
        self.prepared = None
        self.start_button.setEnabled(False)
        self.view_keys.setEnabled(False)
        self.review.setText("Settings changed. Check answers for the selected test again.")
        if not self.running:
            self.command("select", tab_id=self.target.currentData() or "")

    def select_tab(self, *_):
        tab_id = self.target.currentData() or ""
        row = self.tabs.get(tab_id, {})
        if tab_id != self._last_target_id:
            self.pin.setText(row.get("pin", ""))
            self._last_target_id = tab_id
        self.invalidate()
        self._startup_enabled()

    def change_mode(self, *_):
        self.prefs.set(mode=self.mode.currentData())
        mode = self.mode.currentData()
        self.engine.setEnabled(mode != "keys")
        if mode == "keys":
            self.provider_status.setText("AI disabled")
        else:
            self.provider_status.setText("Not checked")
        self.prepare_button.setText("Check AI and test" if mode == "ai" else "Check test and answers")
        self.invalidate()
        self._startup_enabled()

    def startup_engine_changed(self, *_):
        self.prefs.set(engine=self.engine.currentData())
        self.provider_status.setText("Not checked")
        if self.mode.currentData() != "keys":
            self.invalidate()
        if hasattr(self, "drawer"):
            self.drawer.engine.blockSignals(True)
            self.drawer.engine.setCurrentIndex(self.drawer.engine.findData(self.engine.currentData()))
            self.drawer.engine.blockSignals(False)

    def toggle_advanced(self):
        visible = not self.advanced.isVisible()
        self.advanced.setVisible(visible)
        self.advanced_toggle.setText("Answer sources ▾" if visible else "Answer sources ▸")

    def _startup_enabled(self):
        idle = not self.busy and not self.running and not self._launch_pending
        self.connect_button.setEnabled(idle)
        if self.connected:
            self.connect_button.setText("Browser connected")
            self.connect_button.setObjectName("secondary")
            self.browser_status.setText("Automator browser connected")
            self.browser_status.setObjectName("connected_green")
        else:
            self.connect_button.setText("Connect browser")
            self.connect_button.setObjectName("primary")
            self.browser_status.setText("Not connected")
            self.browser_status.setObjectName("muted")
        self.browser_status.style().unpolish(self.browser_status)
        self.browser_status.style().polish(self.browser_status)
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)

        self.refresh.setEnabled(idle and self.connected)
        for widget in (self.target, self.pin, self.mode, self.engine, self.source_url, self.answer_tab, self.cheatnetwork, self.quizit):
            widget.setEnabled(idle)
        if self.mode.currentData() == "keys":
            self.engine.setEnabled(False)
        self.prepare_button.setEnabled(idle and self.connected and bool(self.target.currentData()))
        self.probe_button.setEnabled(idle)
        ai_start = self.mode.currentData() == "ai" and self.connected and bool(self.target.currentData())
        self.start_button.setEnabled(idle and (ai_start or bool(self.prepared and self.prepared.get("can_start"))))
        self.view_keys.setEnabled(bool(self.prepared and self.prepared.get("questions")) and idle)
        self.cancel_check.setVisible(self.busy)

    def prepare(self, *, start_after=False):
        self._pending_start = self._startup_signature() if start_after else None
        self.prepared = None
        self.busy = True
        self.drawer.provider_check.setEnabled(False)
        self._startup_enabled()
        self.prefs.set(cheatnetwork=self.cheatnetwork.isChecked(), quizit=self.quizit.isChecked())
        self.command("prepare", tab_id=self.target.currentData(), pin=self.pin.text(),
                     mode=self.mode.currentData(), engine_id=self.engine.currentData(),
                     source_url=self.source_url.text(), answer_tab_id=self.answer_tab.currentData(),
                     cheatnetwork=self.cheatnetwork.isChecked(), quizit=self.quizit.isChecked())

    def start_run(self):
        if not self.prepared or not self.prepared.get("can_start"):
            if self.mode.currentData() == "ai" and self.connected and self.target.currentData():
                self.notice.setText("Checking AI availability before starting…")
                self.prepare(start_after=True)
            return
        self._pending_start = None
        self._launch_pending = True
        self.command("start_run", delay=self.prefs.values["delay"],
                     wrong_limit=self.prefs.values["wrong_limit"], highlight=self.prefs.values["highlight"])
        self._startup_enabled()

    def _startup_signature(self):
        return (self.target.currentData(), self.pin.text().strip(), self.mode.currentData(), self.engine.currentData())

    def _start_when_ready(self):
        if not self._pending_start or self.busy:
            return
        if self._pending_start != self._startup_signature():
            self._pending_start = None
            return
        if self.prepared:
            self._pending_start = None
            if self.prepared.get("can_start"):
                self.start_run()

    def show_keys(self):
        if not self.prepared:
            return
        if self.keys_dialog:
            self.keys_dialog.close()
        dialog = QDialog(self)
        dialog.setWindowTitle("Question keys — selected test")
        dialog.resize(930, 580)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(self.prepared["source"], style="muted", wrap=True))
        rows = self.prepared.get("questions", [])
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["Question", "Answer / status"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for index, record in enumerate(rows):
            answer = "Written response required — enter your own response" if record["manual"] else " · ".join(record["answers"]) or "No verified key found"
            table.setItem(index, 0, QTableWidgetItem(record["question"]))
            table.setItem(index, 1, QTableWidgetItem(answer))
        table.resizeRowsToContents()
        layout.addWidget(table)
        layout.addWidget(button("Close", dialog.close))
        self.keys_dialog = dialog
        dialog.show()

    def toggle_pause(self):
        self.command("pause", paused=not self.paused)

    def toggle_compact(self):
        self.compact = not self.compact
        self.stack.setVisible(not self.compact)
        self.header_divider.setVisible(not self.compact)
        self.brand_ver.setVisible(not self.compact)
        self.collapse.setText("Expand" if self.compact else "Minimize")
        self.collapse.setIcon(load_icon("maximize" if self.compact else "minus", self.prefs.values["dark"]))
        self.surface.layout().setContentsMargins(*(14, 10, 14, 10) if self.compact else (18, 14, 18, 16))
        self.setMinimumSize(0, 0)
        self.resize(540 if self.compact else 620, 52 if self.compact else self.height())
        self.update_mini()
        self._fit_runtime_window()
        if self.drawer.isVisible():
            self.show_settings()

    def update_mini(self):
        current, total = self.current or "—", self.total or "—"
        accuracy = f" • {self.accuracy}" if self.accuracy != "—" else ""
        self.mini_stats.setText(f"Q {current}/{total}{accuracy}" if self.compact else "")
        self.header_pause.setText("" if self.compact else ("Resume" if self.paused else "Pause"))
        self.header_pause.setToolTip("Resume" if self.paused else "Pause")
        self.header_pause.setIcon(load_icon("play" if self.paused else "pause", self.prefs.values["dark"]))

    def show_settings(self):
        self.drawer.fit_to_screen()
        point = self.mapToGlobal(QPoint(max(0, self.width() - self.drawer.width()), self.header.geometry().bottom() + 18))
        area = self.screen().availableGeometry()
        point.setX(max(area.left() + 8, min(point.x(), area.right() - self.drawer.width() - 8)))
        point.setY(max(area.top() + 8, min(point.y(), area.bottom() - self.drawer.height() - 8)))
        self.drawer.move(point)
        self.drawer.show()
        self.drawer.raise_()

    def set_boss_key(self, choice):
        if self.hotkey.configure(choice):
            self.prefs.set(boss=choice)
        else:
            self.drawer.boss.blockSignals(True)
            self.drawer.boss.setCurrentText(self.hotkey.current)
            self.drawer.boss.blockSignals(False)
            self.drawer.provider_status.setText("This shortcut is already used. Choose another Boss key.")

    def set_on_top(self, enabled, save=True):
        if save:
            self.prefs.set(top=bool(enabled))
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:
            self.show()

    def toggle_hidden(self):
        if self.isVisible():
            self.drawer.hide()
            self.logs_dialog.hide()
            if self.keys_dialog:
                self.keys_dialog.hide()
            self.hide()
        else:
            self.show_overlay()

    def show_overlay(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def return_start(self):
        if self.compact:
            self.toggle_compact()
        self.stack.setCurrentIndex(0)
        self.brand_icon.show()
        self.dot.hide()
        self.header_prep_label.show()
        self.header_pause.hide()
        self.collapse.hide()
        self.win_min.show()
        self.prepared = None
        self._pending_start = None
        self._launch_pending = False
        if self.connected:
            self.command("refresh")
        self.review.setText("Check the selected test again before starting.")
        self.review.hide()
        self.view_keys.hide()
        self.resize(580, 540)
        self._startup_enabled()

    def _fit_runtime_window(self):
        if self.closing or self.compact or self.stack.currentIndex() != 1:
            return
        self.runtime_panel.layout().activate()
        content_height = self.runtime_panel.layout().heightForWidth(self.runtime_scroll.viewport().width())
        content_height = max(content_height, self.runtime_panel.minimumSizeHint().height())
        overhead = self.surface.sizeHint().height() - self.stack.sizeHint().height()
        required = content_height + overhead
        available = self.screen().availableGeometry().height() - 24
        self.resize(max(620, self.width()), min(required, available))

    def _schedule_runtime_fit(self):
        if not self._runtime_fit_pending:
            self._runtime_fit_pending = True
            QTimer.singleShot(0, self._settle_runtime_size)

    def _settle_runtime_size(self):
        self._runtime_fit_pending = False
        self._fit_runtime_window()

    def on_event(self, event):
        kind = event["type"]
        if kind == "log":
            self.logs.appendPlainText(event.get("message", ""))
            return
        if kind == "busy":
            self.busy = event["busy"]
            self.drawer.provider_check.setEnabled(not self.busy)
        elif kind == "browser":
            self.connected = event["connected"]
            if self.connected:
                self.browser_status.setText("Automator browser connected")
                self.browser_status.setObjectName("connected_green")
                self.connect_button.setText("Browser connected")
            else:
                self.browser_status.setText(event["message"])
                self.browser_status.setObjectName("muted")
                self.connect_button.setText("Connect browser")
                self.prepared = None
                self.notice.setText(event["message"])
            self.browser_status.style().unpolish(self.browser_status)
            self.browser_status.style().polish(self.browser_status)
        elif kind == "tabs":
            prior = self.target.currentData()
            self.tabs = {row["id"]: row for row in event["tabs"]}
            self.target.blockSignals(True)
            self.target.clear()
            self.target.addItem("Select a game...", "")
            for row in event["tabs"]:
                suffix = f" · PIN {row['pin']}" if row["pin"] else ""
                suffix += f" · {row['total']} questions" if row["total"] else ""
                self.target.addItem(row["title"] + suffix, row["id"])
            self.target.setCurrentIndex(max(0, self.target.findData(prior)))
            self.target.blockSignals(False)
            count = len(event["tabs"])
            if count == 1:
                self.tab_hint.setText("1 game tab found. Choose the one you want to run.")
            elif count > 1:
                self.tab_hint.setText(f"{count} game tabs found. Choose the one you want to run.")
            else:
                self.tab_hint.setText("No game tabs found. Open a Wayground game tab in the browser.")
            answer_prior = self.answer_tab.currentData()
            self.answer_tab.blockSignals(True)
            self.answer_tab.clear()
            self.answer_tab.addItem("Auto-detect existing answer tab", "")
            for row in event["answer_tabs"]:
                self.answer_tab.addItem(row["title"], row["id"])
            self.answer_tab.setCurrentIndex(max(0, self.answer_tab.findData(answer_prior)))
            self.answer_tab.blockSignals(False)
            if prior and prior not in self.tabs:
                self.invalidate()
            if not event["tabs"]:
                self.notice.setText("Open a game in the Automator browser, then refresh tabs.")
        elif kind == "invalidated":
            self.prepared = None
            self.review.hide()
            self.view_keys.hide()
            self.view_keys.setEnabled(False)
        elif kind in ("status", "browser_action", "attention", "error", "session_lost"):
            message = event.get("message", "")
            self.notice.setText(message)
            self.runtime_notice.setText(message)
            self.logs.appendPlainText(message)
            if kind in ("attention", "session_lost"):
                self.wrong_button.setEnabled(False)
                self.now_button.setEnabled(False)
            if kind == "session_lost":
                self.prepared = None
                self.new_test.show()
            if kind == "error" and event.get("operation") == "prepare":
                self.prepared = None
            if kind in ("error", "session_lost"):
                self._pending_start = None
                self._launch_pending = False
        elif kind == "provider_check":
            if event.get("pending"):
                text = "Checking…"
            else:
                text = ("Available: " if event.get("available") else "Unavailable: ") + event.get("detail", "")
            self.drawer.provider_status.setText(text)
            if event["id"] == self.engine.currentData():
                self.provider_status.setText(text)
            if event.get("available") and event.get("live"):
                self.prefs.set(engine=event["id"])
                self.engine.blockSignals(True)
                self.engine.setCurrentIndex(self.engine.findData(event["id"]))
                self.engine.blockSignals(False)
                self.provider_status.setText(text)
            elif event.get("available") and not self.running:
                self.prefs.set(engine=event["id"])
                self.engine.blockSignals(True)
                self.engine.setCurrentIndex(self.engine.findData(event["id"]))
                self.engine.blockSignals(False)
                self.provider_status.setText(text)
                if self.mode.currentData() != "keys" and self.prepared and self.prepared["engine_id"] != event["id"]:
                    self.invalidate()
        elif kind == "engine_active":
            self.engine_label.setText(f"Engine: {event['label']} · Available")
        elif kind == "prepared":
            self.prepared = event
            self.total = event["total"]
            pin_text = f" · PIN {event['pin']}" if event["pin"] else ""
            if event.get("mode", self.mode.currentData()) == "ai":
                summary = f"AI only · {event['total']} questions" if event["total"] else "AI only · question count will be read from the test"
            else:
                summary = f"{event['key_count']} verified keys / {event['total']} questions"
            self.review.setText(f"{event['name']}{pin_text}\n{summary}\nSource: {event['source']}")
            self.review.show()
            self.view_keys.show()
            self.notice.setText(event["issue"] + (f"\n{event['manual_count']} written response(s) need your own answer in the test tab." if event["manual_count"] else ""))
            self._startup_enabled()
        elif kind == "started":
            self._launch_pending = False
            self.running = True
            self.paused = False
            self.wrong_used = self.submitted_count = 0
            self.current = event.get("current", 0)
            self.total = event["total"]
            self.accuracy = "—"
            self.mistakes.setText(f"Deliberate wrong answers: 0 · Limit: {self.prefs.values['wrong_limit']}")
            self.accuracy_label.setText("Confirmed correct: 0 / 0")
            self.game_name.setText(event["name"] + (f" · PIN {event['pin']}" if event["pin"] else ""))
            engine_name = self.engines[event["engine_id"]].label if event["engine_id"] in self.engines else event["engine_id"]
            self.engine_label.setText("Verified keys only" if event["mode"] == "keys" else f"Engine: {engine_name} · Available")
            self.progress.setValue(0)
            self.progress_percent.setText("0%")
            self.progress_text.setText(f"Question {self.current or '—'} of {self.total or '—'}")
            self.answer_text.setText("Waiting for an answer")
            self.source_label.clear()
            self.source_label.hide()
            self.badge_verified.hide()
            self.last_ai_time.clear()
            self.last_ai_time.hide()
            self.runtime_notice.setText("Reading the selected test…")
            self.stack.setCurrentIndex(1)
            self.brand_icon.hide()
            self.dot.show()
            self.header_prep_label.hide()
            self.header_pause.show()
            self.header_pause.setEnabled(True)
            self.collapse.show()
            self.win_min.hide()
            self.stop_button.hide()
            self.new_test.hide()
            self.resize(620, self.height())
        elif kind == "question":
            self.current, self.total = event["number"], event["total"]
            self.question_text.setText(event["text"][:1000])
            self.answer_text.setText("Reading an answer…")
            self.source_label.setText("")
            self.source_label.hide()
            self.badge_verified.hide()
            self.runtime_notice.setText("")
            self.wrong_button.setEnabled(False)
            self.now_button.setEnabled(False)
            self.update_progress(event["submitted"])
        elif kind == "resolved":
            self.source_label.show()
            latency = f" · {event['latency']:.1f}s" if event.get("latency") is not None else ""
            if event["verified"]:
                self.source_label.setText(f"{event['source']}{latency}")
                self.badge_verified.setText("Verified key")
                self.badge_verified.setObjectName("badge_verified")
            else:
                self.source_label.setText(f"AI prediction · {event['source']}{latency}")
                self.badge_verified.setText("AI Solved")
                self.badge_verified.setObjectName("badge_ai")
            self.badge_verified.style().unpolish(self.badge_verified)
            self.badge_verified.style().polish(self.badge_verified)
            self.badge_verified.show()
            if event.get("latency") is not None:
                self.last_ai_time.setText(f"Last AI request · {event['latency']:.1f} s")
                self.last_ai_time.show()
        elif kind == "answer":
            self.answer_text.setText("\n".join(event["answers"]))
            self.wrong_button.setEnabled(self.running and event["can_wrong"])
            self.wrong_button.setText("Undo wrong" if event["deliberate"] else "Wrong answer here")
            self.now_button.setEnabled(self.running)
            self.now_button.setText("Answer now")
            if event["deliberate"]:
                self.runtime_notice.setText("A deliberate wrong answer is scheduled for this question.")
            elif self.runtime_notice.text().startswith("A deliberate wrong answer"):
                self.runtime_notice.setText("")
        elif kind == "countdown":
            self.now_button.setText(f"Answer now · {event['remaining']:.1f}s")
            self.runtime_notice.setText(f"Waiting to submit · {event['remaining']:.1f} s")
        elif kind == "submitting":
            self.wrong_button.setEnabled(False)
            self.now_button.setEnabled(False)
            self.runtime_notice.setText("Submitting answer…")
        elif kind in ("submitted", "settings"):
            self.wrong_used = event.get("wrong_used", self.wrong_used)
            limit = event.get("wrong_limit", self.prefs.values["wrong_limit"])
            self.prefs.set(wrong_limit=limit)
            self.mistakes.setText(f"Deliberate wrong answers: {self.wrong_used} · Limit: {limit}")
            self.drawer.wrong.blockSignals(True)
            self.drawer.wrong.setMinimum(0)
            self.drawer.wrong.setValue(limit)
            self.drawer.wrong.blockSignals(False)
            if kind == "submitted":
                self.submitted_count = event.get("number", self.submitted_count + 1)
                self.update_progress(event["number"])
                self.runtime_notice.setText("Waiting for next question…")
        elif kind == "manual":
            self.answer_text.setText("Your written response is required")
            self.badge_verified.setText("Manual")
            self.badge_verified.setObjectName("badge_ai")
            self.badge_verified.style().unpolish(self.badge_verified)
            self.badge_verified.style().polish(self.badge_verified)
            self.badge_verified.show()
            self.source_label.setText("No fixed answer key")
            self.source_label.show()
            self.runtime_notice.setText(event["message"])
            self.now_button.setEnabled(False)
            self.wrong_button.setEnabled(False)
        elif kind == "paused":
            self.paused = event["paused"]
            self.runtime_notice.setText("Paused before submission" if self.paused else "Resumed")
            self.header_pause.setText("Resume" if self.paused else "Pause")
            self.header_pause.setIcon(load_icon("play" if self.paused else "pause", self.prefs.values["dark"]))
            self.dot.setStyleSheet("color: #f3c678;" if self.paused or not self.connected else "color: #87dfaa;")
        elif kind == "results":
            accuracy = str(event["stats"].get("accuracy") or "")
            if re.fullmatch(r"\d+(?:\.\d+)?\s*%", accuracy.strip()):
                self.accuracy = accuracy.strip()
                self.accuracy_label.setText(f"Accuracy: {self.accuracy} · Wayground results")
        elif kind == "finished":
            self._launch_pending = False
            self.running = False
            self.paused = False
            self.header_pause.setEnabled(False)
            self.now_button.setEnabled(False)
            self.wrong_button.setEnabled(False)
            self.stop_button.hide()
            self.new_test.show()
            if event["complete"]:
                self.runtime_notice.setText("Test completed. Results above are from Wayground.")
                self.update_progress(self.total)
            elif not self.runtime_notice.text() or self.runtime_notice.text().startswith(("Waiting", "Submitting", "Paused", "Resumed")):
                self.runtime_notice.setText("Automation stopped. The browser remains open.")
        elif kind == "closed":
            self.allow_close = True
            self.hotkey.close()
            if self.tray:
                self.tray.hide()
            if self._streams:
                sys.stdout, sys.stderr = self._streams
                self._streams = None
            self.close()
        self.dot.setStyleSheet("color: #f3c678;" if self.paused or not self.connected else "color: #87dfaa;")
        self.update_mini()
        self._fit_runtime_window()
        self._schedule_runtime_fit()
        self._startup_enabled()
        self._start_when_ready()

    def update_progress(self, submitted):
        self.submitted_count = submitted
        value = min(100, int(100 * submitted / self.total)) if self.total else 0
        self.progress_text.setText(f"Question {self.current or '—'} of {self.total or '—'}")
        self.progress_percent.setText(f"{submitted} submitted · {value}%")
        self.progress.setValue(value)

    def eventFilter(self, watched, event):
        if watched in (getattr(self, "runtime_panel", None), getattr(self, "answer_card", None)) and event.type() == event.Type.LayoutRequest:
            self._schedule_runtime_fit()
        if watched in (self.header, self.brand, self.brand_icon, self.brand_ver, self.mini_stats):
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == event.Type.MouseMove and self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag)
            elif event.type() == event.Type.MouseButtonRelease:
                self._drag = None
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        if not self.closing:
            self.closing = True
            self.hotkey.close()
            self.drawer.hide()
            self.setEnabled(False)
            self.setWindowTitle("Wayground Pro — stopping…")
            self.backend.request("shutdown")


def run_desktop():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Wayground Pro")
    app.setOrganizationName("WaygroundAutomator")
    window = DesktopWindow(capture_logs=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_desktop())
