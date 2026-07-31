import sys
import json
import os
import time
import re
import threading
import ctypes
from datetime import datetime

# 开启 Windows 高 DPI 屏幕兼容支持
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
    QListWidget, QCheckBox, QAbstractSpinBox, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QIcon
)

import mss
import numpy as np
import cv2

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# ==================== 1. 全局 F12 键盘监听线程 ====================
class GlobalF12Listener(QThread):
    f12_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        user32 = ctypes.windll.user32
        VK_F12 = 0x7B  # F12 键码
        was_pressed = False
        while self.running:
            state = user32.GetAsyncKeyState(VK_F12)
            is_pressed = bool(state & 0x8000)
            if is_pressed and not was_pressed:
                self.f12_triggered.emit()
            was_pressed = is_pressed
            self.msleep(50)


# ==================== 2. 报警声音播放器（支持即时停止） ====================
class AlarmSoundPlayer:
    def __init__(self):
        self.is_playing = False
        self.sound_file = None
        self.play_thread = None
        self.stop_flag = False
        self.lock = threading.Lock()
        self._load_sound()
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
                self.mixer_ready = True
            except: self.mixer_ready = False
        else: self.mixer_ready = False

    def _load_sound(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(script_dir, "警报声.mp3")
        if os.path.exists(sound_path):
            self.sound_file = sound_path

    def play(self):
        with self.lock:
            if self.is_playing: return
            self.stop_flag = False
            self.is_playing = True

        if PYGAME_AVAILABLE and self.mixer_ready and self.sound_file:
            self._play_with_pygame()
        else:
            self._play_beep()

    def _play_with_pygame(self):
        def play_loop():
            try:
                sound = pygame.mixer.Sound(self.sound_file)
                while True:
                    with self.lock:
                        if self.stop_flag: break
                    sound.play()
                    while pygame.mixer.get_busy():
                        with self.lock:
                            if self.stop_flag: 
                                pygame.mixer.stop()
                                break
                        time.sleep(0.05)
                    time.sleep(0.05)
            except: pass
            finally:
                with self.lock: self.is_playing = False
        self.play_thread = threading.Thread(target=play_loop, daemon=True)
        self.play_thread.start()

    def _play_beep(self):
        def beep_loop():
            try:
                import winsound
                while True:
                    with self.lock:
                        if self.stop_flag: break
                    winsound.Beep(800, 200)
                    time.sleep(0.1)
            except: pass
            finally:
                with self.lock: self.is_playing = False
        self.play_thread = threading.Thread(target=beep_loop, daemon=True)
        self.play_thread.start()

    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.is_playing = False
        if PYGAME_AVAILABLE and self.mixer_ready:
            try: pygame.mixer.stop()
            except: pass


# ==================== 3. 细格栅自动点击线程 ====================
class FineGrilleThread(QThread):
    def __init__(self, cycle_interval_min=2.0, parent=None):
        super().__init__(parent)
        self.cycle_interval_min = cycle_interval_min
        self.running = True

    def set_interval(self, minutes):
        self.cycle_interval_min = max(0.1, minutes)

    def stop(self):
        self.running = False

    def _safe_sleep(self, seconds):
        steps = int(seconds * 10)
        for _ in range(steps):
            if not self.running:
                return False
            self.msleep(100)
        return True

    def _click_matrix(self, start_x, start_y):
        rows = [(0, 5), (1, 5), (2, 4)]
        for row_idx, click_count in rows:
            curr_y = start_y + row_idx * 36
            curr_x = start_x
            for _ in range(click_count):
                if not self.running:
                    return False
                ctypes.windll.user32.SetCursorPos(curr_x, curr_y)
                ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                
                if not self._safe_sleep(0.5):
                    return False
                curr_x += 68
        return True

    def run(self):
        while self.running:
            if not self._click_matrix(19, 955): break
            if not self._safe_sleep(120): break
            if not self._click_matrix(51, 955): break

            wait_sec = max(1.0, self.cycle_interval_min * 60)
            if not self._safe_sleep(wait_sec): break


# ==================== 4. 独立日志悬浮窗口（90% 透明度） ====================
class StandaloneLogWindow(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle(f"数值历史 - {name}")
        self.resize(230, 260)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.lbl_title = QLabel(f"📋 {name}")
        self.lbl_title.setStyleSheet("font-weight: bold; color: #00ff8c; font-size: 12px;")
        layout.addWidget(self.lbl_title)

        self.list_widget = QListWidget()
        # 背景改为 90% 透明度 (10% 遮罩)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: rgba(18, 18, 28, 0.1);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 2px 4px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
        """)
        layout.addWidget(self.list_widget)
        self.max_count = 30

    def update_name(self, name):
        self.setWindowTitle(f"数值历史 - {name}")
        self.lbl_title.setText(f"📋 {name}")

    def set_max_count(self, count):
        self.max_count = count
        while self.list_widget.count() > self.max_count:
            self.list_widget.takeItem(self.list_widget.count() - 1)

    def add_log_str(self, msg):
        self.list_widget.insertItem(0, msg)
        while self.list_widget.count() > self.max_count:
            self.list_widget.takeItem(self.max_count)


# ==================== 5. 悬浮识别选框窗口（背景 90% 透明度） ====================
class OverlayRegionWidget(QWidget):
    delete_requested = Signal(object)
    alarm_cleared = Signal()
    mute_toggled = Signal()

    def __init__(self, box_id, x, y, w, h, name="区域", lower=0.0, upper=100.0, parent=None):
        super().__init__(None)
        self.box_id = box_id
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(80, w)
        self.capture_h = max(25, h)

        self.name = name
        self.lower = lower
        self.upper = upper

        self.log_interval_min = 1.0
        self.last_log_time = 0.0

        self.is_alarm = False
        self.user_cleared_alarm = False  # 是否已点击消除
        self.last_alarm_val = None       # 记录引发报警的数值

        self.is_editing = False
        self.is_muted = False
        self.panel_hidden = False        # 全局“隐藏框”状态

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._drag_pos = QPoint()
        self._resize_mode = None

        self.log_window = StandaloneLogWindow(self.name)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---------------- 1. 识别框区域占位 ----------------
        self.capture_spacer = QWidget()
        self.capture_spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        main_layout.addWidget(self.capture_spacer)

        # ---------------- 2. 下方控制面板（背景 90% 透明度） ----------------
        self.control_panel = QWidget()
        self.control_panel.setStyleSheet("background-color: rgba(18, 18, 28, 0.1); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        panel_layout = QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)

        # --- 第一排：名字 + 记录 + 静音 ---
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(4)

        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")

        self.edit_title = QLineEdit(self.name)
        self.edit_title.setStyleSheet("background-color: rgba(42, 42, 60, 0.3); color: #00ff8c; font-size: 11px; font-weight: bold; border: 1px solid #00ff8c; border-radius: 2px;")
        self.edit_title.setVisible(False)
        self.edit_title.textChanged.connect(self._on_title_changed)

        self.btn_toggle_log = QPushButton("📋 记录")
        self.btn_toggle_log.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: #00ff8c; border: none; border-radius: 3px; padding: 2px 5px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_toggle_log.clicked.connect(self._toggle_log_window)

        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedSize(22, 20)
        self.btn_mute.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_mute.clicked.connect(self._toggle_mute)

        row1_layout.addWidget(self.lbl_title)
        row1_layout.addWidget(self.edit_title)
        row1_layout.addStretch()
        row1_layout.addWidget(self.btn_toggle_log)
        row1_layout.addWidget(self.btn_mute)
        panel_layout.addLayout(row1_layout)

        # --- 第二排：上下限设置 / 报警消除 ---
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(4)

        self.lbl_lower = QLabel("下限:")
        self.lbl_lower.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_lower = QDoubleSpinBox()
        self.spin_lower.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_lower.setAlignment(Qt.AlignCenter)
        self.spin_lower.setRange(-99999.0, 99999.0)
        self.spin_lower.setValue(self.lower)
        self.spin_lower.setFixedSize(48, 20)
        self.spin_lower.setStyleSheet("background-color: rgba(26, 26, 38, 0.3); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_lower.valueChanged.connect(self._on_lower_changed)

        self.lbl_upper = QLabel("上限:")
        self.lbl_upper.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_upper = QDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setAlignment(Qt.AlignCenter)
        self.spin_upper.setRange(-99999.0, 99999.0)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedSize(48, 20)
        self.spin_upper.setStyleSheet("background-color: rgba(26, 26, 38, 0.3); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_upper.valueChanged.connect(self._on_upper_changed)

        self.btn_clear_alarm = QPushButton("🚨 消除报警")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        self.btn_delete = QPushButton("➖ 删除框")
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; padding: 2px 5px; font-weight: bold; font-size: 10px; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))

        row2_layout.addWidget(self.lbl_lower)
        row2_layout.addWidget(self.spin_lower)
        row2_layout.addWidget(self.lbl_upper)
        row2_layout.addWidget(self.spin_upper)
        row2_layout.addWidget(self.btn_clear_alarm)
        row2_layout.addStretch()
        row2_layout.addWidget(self.btn_delete)
        panel_layout.addLayout(row2_layout)

        # --- 第三排：实时识别结果显示 ---
        row3_layout = QHBoxLayout()
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(4)

        self.lbl_result = QLabel("🔍 识别结果: 等待检测...")
        self.lbl_result.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: bold;")
        row3_layout.addWidget(self.lbl_result)
        row3_layout.addStretch()

        panel_layout.addLayout(row3_layout)

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _on_lower_changed(self, val):
        self.lower = val

    def _on_upper_changed(self, val):
        self.upper = val

    def _on_title_changed(self, text):
        self.name = text
        self.lbl_title.setText(text)
        self.log_window.update_name(text)

    def _toggle_log_window(self):
        if self.log_window.isVisible():
            self.log_window.hide()
        else:
            box_w = max(self.capture_w, 200)
            self.log_window.move(self.capture_x + box_w + 8, self.capture_y)
            self.log_window.show()
            self.log_window.raise_()

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            self.lbl_result.setText(f"🔍 识别结果: {val:.2f}")
            self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")
        else:
            disp = f"未检测到 ({raw_text})" if raw_text else "未检测到数值"
            self.lbl_result.setText(f"🔍 {disp}")
            self.lbl_result.setStyleSheet("color: #ff6666; font-size: 11px; font-weight: bold;")

    def add_log_val(self, time_str, val, raw_text=""):
        # 需求二：历史记录中不显示 (原:xxx)
        now_ts = time.time()
        if self.last_log_time == 0.0 or (now_ts - self.last_log_time >= self.log_interval_min * 60.0):
            self.last_log_time = now_ts
            if val is not None:
                self.log_window.add_log_str(f"[{time_str}] {val:.2f}")
            else:
                self.log_window.add_log_str(f"[{time_str}] ❌未检测到")

    def set_max_log_count(self, count):
        self.log_window.set_max_count(count)

    def set_panel_hidden(self, hidden):
        self.panel_hidden = hidden
        if hidden:
            self.log_window.hide()
        self._update_bar_visibility()
        self._update_geometry()

    def _update_bar_visibility(self):
        # 需求一：即使在“隐藏框”模式下，一旦报警，面板和操作按钮也强制显示出来
        show_panel = (not self.panel_hidden) or self.is_alarm
        self.control_panel.setVisible(show_panel)

        self.btn_delete.setVisible(self.is_editing)
        self.spin_lower.setEnabled(self.is_editing)
        self.spin_upper.setEnabled(self.is_editing)
        self.lbl_title.setVisible(not self.is_editing)
        self.edit_title.setVisible(self.is_editing)
        self.btn_clear_alarm.setVisible(self.is_alarm)

    def _update_geometry(self):
        total_w = max(self.capture_w, 210)
        show_panel = (not self.panel_hidden) or self.is_alarm
        panel_h = 76 if show_panel else 0
        self.capture_spacer.setFixedHeight(self.capture_h)
        total_h = self.capture_h + panel_h
        self.setGeometry(self.capture_x, self.capture_y, total_w, total_h)

    def set_edit_mode(self, enabled):
        self.is_editing = enabled
        self._update_bar_visibility()
        self._update_geometry()
        self.update()

    def set_alarm_state(self, is_alarm):
        self.is_alarm = is_alarm
        self._update_bar_visibility()
        self._update_geometry()
        self.update()

    def _on_clear_alarm(self):
        # 需求四：标记为已手动消除
        self.user_cleared_alarm = True
        self.set_alarm_state(False)
        self.alarm_cleared.emit()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        btn_txt = "🔇" if self.is_muted else "🔊"
        btn_style = "QPushButton { background-color: #e65100; color: white; border: none; border-radius: 3px; font-size: 10px; }" if self.is_muted else "QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; }"
        self.btn_mute.setText(btn_txt)
        self.btn_mute.setStyleSheet(btn_style)
        self.mute_toggled.emit()

    def _get_hit_mode(self, pos):
        x, y = pos.x(), pos.y()
        m = 6
        ch = self.capture_h
        cw = self.capture_w
        if y <= ch:
            if y > ch - m and x > cw - m: return "BR"
            if y > ch - m: return "B"
            if x > cw - m: return "R"
            if x < m: return "L"
        return "MOVE"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_editing:
            self._drag_pos = event.globalPosition().toPoint() - QPoint(self.capture_x, self.capture_y)
            self._resize_mode = self._get_hit_mode(event.position().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_editing: return
        pos = event.position().toPoint()
        mode = self._get_hit_mode(pos)

        if mode == "BR": self.setCursor(Qt.SizeFDiagCursor)
        elif mode in ["R", "L"]: self.setCursor(Qt.SizeHorCursor)
        elif mode == "B": self.setCursor(Qt.SizeVerCursor)
        else: self.setCursor(Qt.SizeAllCursor)

        if event.buttons() & Qt.LeftButton:
            g_pos = event.globalPosition().toPoint()
            if self._resize_mode == "BR":
                self.capture_w = max(80, g_pos.x() - self.capture_x)
                self.capture_h = max(25, g_pos.y() - self.capture_y)
            elif self._resize_mode == "R":
                self.capture_w = max(80, g_pos.x() - self.capture_x)
            elif self._resize_mode == "B":
                self.capture_h = max(25, g_pos.y() - self.capture_y)
            elif self._resize_mode == "L":
                diff = self.capture_x - g_pos.x()
                if self.capture_w + diff >= 80:
                    self.capture_x = g_pos.x()
                    self.capture_w += diff
            elif self._resize_mode == "MOVE":
                new_p = g_pos - self._drag_pos
                self.capture_x = new_p.x()
                self.capture_y = new_p.y()

            self._update_geometry()
            self.update()

    def paintEvent(self, event):
        # 需求一与五：背景 90% 透明度（画笔 10% 遮罩 alpha=25），仅保留外边框线
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box_rect = QRect(0, 0, self.capture_w, self.capture_h)

        if self.is_editing:
            pen = QPen(QColor(255, 200, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 200, 0, 25))
        elif self.is_alarm:
            pen = QPen(QColor(255, 40, 40), 3, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 0, 0, 25))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 25))

        painter.drawRect(box_rect.adjusted(1, 1, -1, -1))

    def closeEvent(self, event):
        if hasattr(self, 'log_window'):
            self.log_window.close()
        event.accept()


# ==================== 6. 屏幕选区拾取器 ====================
class CoordinatePicker(QWidget):
    coord_selected = Signal(int, int, int, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setMouseTracking(True)
        screens = QApplication.screens()
        total_rect = screens[0].geometry()
        for s in screens[1:]:
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)

        self.screen_pixmap = QPixmap(total_rect.size())
        painter = QPainter(self.screen_pixmap)
        for screen in screens:
            painter.drawPixmap(screen.geometry().topLeft(), screen.grabWindow(0))
        painter.end()

        self.state = 0
        self.start_pos = QPoint()
        self.end_pos = QPoint()

        self.label = QLabel("🖱 点击左上角确定起点", self)
        self.label.setStyleSheet("color: white; background: rgba(0,0,0,220); padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: bold;")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.state >= 1 and not self.start_pos.isNull() and not self.end_pos.isNull():
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            w = abs(self.end_pos.x() - self.start_pos.x())
            h = abs(self.end_pos.y() - self.start_pos.y())
            painter.setPen(QPen(QColor(0, 255, 140), 2, Qt.DashLine))
            painter.drawRect(QRect(x, y, w, h))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.state == 0:
                self.start_pos = event.position().toPoint()
                self.end_pos = self.start_pos
                self.state = 1
                self.label.setText("🖱 点击右下角确定终点")
                self.label.adjustSize()
            elif self.state == 1:
                self.end_pos = event.position().toPoint()
                x = min(self.start_pos.x(), self.end_pos.x())
                y = min(self.start_pos.y(), self.end_pos.y())
                w = abs(self.end_pos.x() - self.start_pos.x())
                h = abs(self.end_pos.y() - self.start_pos.y())
                if w > 5 and h > 5:
                    self.coord_selected.emit(x, y, w, h)
                    self.close()

    def mouseMoveEvent(self, event):
        self.end_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()


# ==================== 7. 后台识别线程（带倒计时与按数据变化报警） ====================
class MonitorThread(QThread):
    value_updated = Signal(object, str, object, str)
    alarm_triggered = Signal(object, str, float)
    alarm_state_cleared = Signal()
    countdown_tick = Signal(float)  # 需求六：倒计时信号

    def __init__(self, boxes, interval=1.0, parent=None):
        super().__init__(parent)
        self.boxes = boxes
        self.interval = max(0.1, interval)
        self.running = True
        self.reader = None

    def set_reader(self, reader):
        self.reader = reader

    def update_interval(self, val):
        self.interval = max(0.1, val)

    def stop(self):
        self.running = False

    def _clean_digit_text(self, text):
        mapping = {
            'O': '0', 'o': '0', 'D': '0',
            'I': '1', 'l': '1', '|': '1', '!': '1',
            'Z': '2', 'z': '2',
            'S': '5', 's': '5',
            'B': '8',
        }
        res = list(text)
        for i, ch in enumerate(res):
            if ch in mapping:
                res[i] = mapping[ch]
        return "".join(res)

    def run(self):
        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio() if screen else 1.0

        with mss.mss() as sct:
            while self.running:
                if not self.reader:
                    self.msleep(200)
                    continue

                start_time = time.time()
                for box in list(self.boxes):
                    if not self.running: break
                    
                    x = int(box.capture_x * scale)
                    y = int(box.capture_y * scale)
                    w = int(box.capture_w * scale)
                    h = int(box.capture_h * scale)

                    if w <= 0 or h <= 0: continue

                    try:
                        bbox = {"top": y, "left": x, "width": w, "height": h}
                        sct_img = sct.grab(bbox)
                        img_np = np.array(sct_img)

                        if img_np.shape[2] == 4:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                        else:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                        target_h = 100
                        scale_factor = max(3.0, target_h / float(max(1, h)))
                        new_w, new_h = int(w * scale_factor), int(h * scale_factor)
                        scaled_bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

                        attempts = []

                        ok1, buf1 = cv2.imencode(".png", scaled_bgr)
                        if ok1: attempts.append(buf1.tobytes())

                        gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
                        ok2, buf2 = cv2.imencode(".png", gray)
                        if ok2: attempts.append(buf2.tobytes())

                        inverted = cv2.bitwise_not(gray)
                        ok3, buf3 = cv2.imencode(".png", inverted)
                        if ok3: attempts.append(buf3.tobytes())

                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)
                        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
                        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                        ok4, buf4 = cv2.imencode(".png", binary)
                        if ok4: attempts.append(buf4.tobytes())

                        found_val = None
                        last_raw_str = ""

                        for buf in attempts:
                            raw_text = str(self.reader.classification(buf))
                            if not raw_text: continue
                            last_raw_str = raw_text

                            clean_t = self._clean_digit_text(raw_text).replace(' ', '')
                            clean_t = re.sub(r'(?<=\d)[,::·\'`_\-*\°ae~,;–—.\s、]+(?=\d)', '.', clean_t)

                            nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)
                            if nums:
                                try:
                                    found_val = float(nums[0])
                                    break
                                except ValueError:
                                    pass

                        now_str = datetime.now().strftime("%H:%M:%S")
                        self.value_updated.emit(box, now_str, found_val, last_raw_str)

                        if found_val is not None:
                            is_out_of_bounds = (found_val < box.lower or found_val > box.upper)
                            
                            if is_out_of_bounds:
                                # 需求四：按“数据变化”来报警
                                val_changed = (box.last_alarm_val is None) or (abs(found_val - box.last_alarm_val) > 1e-4)
                                if val_changed:
                                    # 数据有了新变化，重置用户手动消除标记
                                    box.user_cleared_alarm = False
                                    box.last_alarm_val = found_val

                                if not box.user_cleared_alarm:
                                    self.alarm_triggered.emit(box, now_str, found_val)
                            else:
                                # 恢复正常值
                                box.user_cleared_alarm = False
                                box.last_alarm_val = None
                                if box.is_alarm:
                                    box.set_alarm_state(False)
                                    self.alarm_state_cleared.emit()

                    except Exception as e:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        self.value_updated.emit(box, now_str, None, f"异常:{e}")

                # 需求六：带实时倒计时的休眠循环
                elapsed = time.time() - start_time
                sleep_needed = max(0.05, self.interval - elapsed)
                end_time = time.time() + sleep_needed

                while self.running and time.time() < end_time:
                    rem = max(0.0, end_time - time.time())
                    self.countdown_tick.emit(rem)
                    self.msleep(50)


# ==================== 8. 全局控制面板（背景 90% 透明度 + 倒计时） ====================
class GlobalControlPanel(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.boxes = []
        self.monitoring = False
        self.is_editing = False
        self.is_collapsed = False
        self.boxes_panel_hidden = False
        self.reader = None
        self.config_file = "monitor_config.json"
        self.alarm_player = AlarmSoundPlayer()
        self.grille_thread = None

        self._drag_pos = None

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._on_f12_pressed)
        self.f12_listener.start()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.setStyleSheet("""
            QWidget { 
                border-radius: 6px; 
            }
            QLabel { 
                color: #e0e0e0; 
                font-size: 11px; 
                font-weight: bold; 
                background: transparent;
                border: none;
            }
            QPushButton { 
                background-color: rgba(43, 45, 66, 0.5); 
                color: #ffffff; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                padding: 0px 8px; 
                height: 26px;
                font-size: 11px; 
                font-weight: bold; 
            }
            QPushButton:hover { 
                background-color: rgba(61, 64, 91, 0.7); 
            }
            QPushButton:pressed { 
                background-color: rgba(26, 27, 38, 0.8); 
            }
            QDoubleSpinBox, QSpinBox { 
                background-color: rgba(26, 26, 38, 0.5); 
                color: #00ff8c; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                font-size: 11px; 
                font-weight: bold; 
                padding: 0px 2px;
                height: 26px;
            }
            QCheckBox { 
                color: #00ff8c; 
                font-size: 11px; 
                font-weight: bold; 
                background: transparent;
                border: none;
            }
            QCheckBox::indicator { 
                width: 14px; 
                height: 14px; 
                border-radius: 3px;
                border: 1px solid #00ff8c;
                background: rgba(26, 26, 38, 0.5);
            }
            QCheckBox::indicator:checked {
                background: #00ff8c;
            }
        """)

        # ---------- 第 0 排：添加选框栏 ----------
        self.row0_container = QWidget()
        row0_layout = QHBoxLayout(self.row0_container)
        row0_layout.setContentsMargins(0, 0, 0, 0)
        row0_layout.setSpacing(6)
        self.btn_add = QPushButton("➕ 添加选框")
        self.btn_add.setStyleSheet("background-color: #00a86b; color: white; height: 26px;")
        self.btn_add.clicked.connect(self._add_box_picker)
        row0_layout.addWidget(self.btn_add)
        row0_layout.addStretch()
        self.row0_container.setVisible(False)
        main_layout.addWidget(self.row0_container)

        # ---------- 第 1 排：识别监控控制栏 (卡片背景：90% 透明度) ----------
        self.row1_card = QFrame()
        self.row1_card.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
            }
        """)
        self.row1_layout = QHBoxLayout(self.row1_card)
        self.row1_layout.setContentsMargins(8, 5, 8, 5)
        self.row1_layout.setSpacing(6)

        self.left_container = QWidget()
        left_layout = QHBoxLayout(self.left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)

        left_layout.addWidget(QLabel("⏱ 识别间隔(s):"))
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        self.spin_interval.setFixedSize(42, 26)
        self.spin_interval.setRange(0.1, 10.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.valueChanged.connect(self._on_interval_changed)
        left_layout.addWidget(self.spin_interval)

        # 需求六：倒计时显示标签
        self.lbl_countdown = QLabel("⏳ 0.0s")
        self.lbl_countdown.setStyleSheet("color: #ffcc00; font-weight: bold; padding-right: 4px;")
        left_layout.addWidget(self.lbl_countdown)

        left_layout.addWidget(QLabel("📊 记录数:"))
        self.spin_count = QSpinBox()
        self.spin_count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_count.setAlignment(Qt.AlignCenter)
        self.spin_count.setFixedSize(40, 26)
        self.spin_count.setRange(5, 200)
        self.spin_count.setValue(30)
        self.spin_count.valueChanged.connect(self._on_count_changed)
        left_layout.addWidget(self.spin_count)

        left_layout.addWidget(QLabel("📝 记录间隔(分):"))
        self.spin_log_interval = QDoubleSpinBox()
        self.spin_log_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_log_interval.setAlignment(Qt.AlignCenter)
        self.spin_log_interval.setFixedSize(42, 26)
        self.spin_log_interval.setRange(0.0, 1440.0)
        self.spin_log_interval.setValue(1.0)
        self.spin_log_interval.setSingleStep(0.5)
        self.spin_log_interval.valueChanged.connect(self._on_log_interval_changed)
        left_layout.addWidget(self.spin_log_interval)

        # ⚙️ 调整 按钮
        self.btn_edit = QPushButton("⚙️ 调整")
        self.btn_edit.setFixedHeight(26)
        self.btn_edit.clicked.connect(self._toggle_edit)
        left_layout.addWidget(self.btn_edit)

        # 👁 隐藏/显示 按钮 (需求一：隐藏控制面板，保留框)
        self.btn_toggle_hide = QPushButton("👁 隐藏框")
        self.btn_toggle_hide.setFixedHeight(26)
        self.btn_toggle_hide.setStyleSheet("background-color: rgba(255,255,255,0.12); color: #00ff8c;")
        self.btn_toggle_hide.clicked.connect(self._toggle_hide_boxes)
        left_layout.addWidget(self.btn_toggle_hide)

        self.row1_layout.addWidget(self.left_container)

        self.btn_collapse = QPushButton("◀ 收起")
        self.btn_collapse.setFixedHeight(26)
        self.btn_collapse.clicked.connect(self._toggle_collapse)
        self.row1_layout.addWidget(self.btn_collapse)

        self.btn_monitor = QPushButton("▶ 开始监控")
        self.btn_monitor.setFixedHeight(26)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        self.row1_layout.addWidget(self.btn_monitor)

        self.btn_exit = QPushButton("❌ 退出")
        self.btn_exit.setFixedHeight(26)
        self.btn_exit.clicked.connect(self.close_app)
        self.row1_layout.addWidget(self.btn_exit)

        main_layout.addWidget(self.row1_card)

        # ---------- 第 2 排：细格栅自动点击栏 (卡片背景：90% 透明度) ----------
        self.grille_card = QFrame()
        self.grille_card.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
            }
        """)
        row2_layout = QHBoxLayout(self.grille_card)
        row2_layout.setContentsMargins(8, 5, 8, 5)
        row2_layout.setSpacing(6)

        self.chk_grille = QCheckBox("细格栅")
        row2_layout.addWidget(self.chk_grille)

        row2_layout.addWidget(QLabel("执行间隔(分):"))
        self.spin_grille_interval = QDoubleSpinBox()
        self.spin_grille_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_grille_interval.setAlignment(Qt.AlignCenter)
        self.spin_grille_interval.setFixedSize(48, 24)
        self.spin_grille_interval.setRange(0.1, 1440.0)
        self.spin_grille_interval.setValue(2.0)
        self.spin_grille_interval.setSingleStep(0.5)
        self.spin_grille_interval.valueChanged.connect(self._on_grille_interval_changed)
        row2_layout.addWidget(self.spin_grille_interval)

        self.btn_grille_start = QPushButton("▶ 开始操作")
        self.btn_grille_start.setFixedHeight(24)
        self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        self.btn_grille_start.clicked.connect(self._toggle_grille)
        row2_layout.addWidget(self.btn_grille_start)

        row2_layout.addStretch()
        main_layout.addWidget(self.grille_card)

        self._update_button_styles()
        self.adjustSize()
        self._position_top_right()

        self._init_ocr()
        self.load_config()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _update_button_styles(self):
        if self.is_collapsed:
            pad = "padding: 0px 4px; min-width: 32px; font-size: 10px; height: 26px;"
            self.btn_collapse.setText("▶ 展开")
        else:
            pad = "padding: 0px 8px; min-width: 50px; font-size: 11px; height: 26px;"
            self.btn_collapse.setText("◀ 收起")

        self.btn_collapse.setStyleSheet(f"background-color: rgba(255,255,255,0.1); color: #00ff8c; font-weight: bold; {pad}")
        self.btn_monitor.setStyleSheet(f"background-color: {'#b03a3a' if self.monitoring else '#2e9a58'}; color: white; font-weight: bold; {pad}")
        self.btn_exit.setStyleSheet(f"background-color: rgba(255, 255, 255, 0.15); color: white; font-weight: bold; {pad}")

    def _toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        self.left_container.setVisible(not self.is_collapsed)
        self._update_button_styles()
        self.adjustSize()

    def _toggle_hide_boxes(self):
        # 需求一：隐藏控制面板，但绝不隐藏屏幕上的识别选框
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        for box in self.boxes:
            box.set_panel_hidden(self.boxes_panel_hidden)

        self.btn_toggle_hide.setText("👁 显示框" if self.boxes_panel_hidden else "👁 隐藏框")
        self.btn_toggle_hide.setStyleSheet("background-color: #e65100; color: white;" if self.boxes_panel_hidden else "background-color: rgba(255,255,255,0.12); color: #00ff8c;")

    def _on_f12_pressed(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.stop_grille()

    def _on_grille_interval_changed(self, val):
        if self.grille_thread and self.grille_thread.isRunning():
            self.grille_thread.set_interval(val)

    def _toggle_grille(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.stop_grille()
        else:
            if not self.chk_grille.isChecked():
                return
            self.start_grille()

    def start_grille(self):
        self.grille_thread = FineGrilleThread(cycle_interval_min=self.spin_grille_interval.value())
        self.grille_thread.start()
        self.btn_grille_start.setText("⏹ 停止操作(F12)")
        self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold; height: 24px;")

    def stop_grille(self):
        if self.grille_thread:
            self.grille_thread.stop()
            self.grille_thread.wait()
            self.grille_thread = None
        self.btn_grille_start.setText("▶ 开始操作")
        self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold; height: 24px;")

    def _position_top_right(self):
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(screen_geo.width() - self.width() - 20, 20)

    def _init_ocr(self):
        class OCRLoader(QThread):
            loaded = Signal(object)
            def run(self):
                try:
                    import ddddocr
                    self.loaded.emit(ddddocr.DdddOcr(show_ad=False))
                except Exception:
                    self.loaded.emit(None)

        self.loader = OCRLoader()
        self.loader.loaded.connect(self._on_ocr_loaded)
        self.loader.start()

    def _on_ocr_loaded(self, reader):
        self.reader = reader

    def _on_interval_changed(self, val):
        if hasattr(self, 'monitor_thread') and self.monitor_thread:
            self.monitor_thread.update_interval(val)

    def _on_count_changed(self, val):
        for box in self.boxes:
            box.set_max_log_count(val)

    def _on_log_interval_changed(self, val):
        for box in self.boxes:
            box.log_interval_min = val

    def _toggle_edit(self):
        self.is_editing = not self.is_editing
        self.row0_container.setVisible(self.is_editing)
        if self.is_editing:
            self.btn_edit.setText("✅ 完成")
            self.btn_edit.setStyleSheet("background-color: #e6b84d; color: black; height: 26px; font-weight: bold;")
        else:
            self.btn_edit.setText("⚙️ 调整")
            self.btn_edit.setStyleSheet("background-color: rgba(43, 45, 66, 0.5); color: white; height: 26px; font-weight: bold;")
            self.save_config()

        for box in self.boxes:
            box.set_edit_mode(self.is_editing)
        self.adjustSize()

    def _add_box_picker(self):
        self.picker = CoordinatePicker()
        self.picker.coord_selected.connect(self._on_box_picked)
        self.picker.showFullScreen()

    def _on_box_picked(self, x, y, w, h):
        if w == 0 or h == 0: return
        box_id = len(self.boxes) + 1
        box = OverlayRegionWidget(box_id, x, y, w, h, name=f"区域{box_id}")
        box.delete_requested.connect(self._delete_box)
        box.alarm_cleared.connect(self.check_and_update_alarm_sound)
        box.mute_toggled.connect(self.check_and_update_alarm_sound)

        box.set_panel_hidden(self.boxes_panel_hidden)
        box.set_edit_mode(self.is_editing)
        box.set_max_log_count(self.spin_count.value())
        box.log_interval_min = self.spin_log_interval.value()
        box.show()
        self.boxes.append(box)

    def _delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self.check_and_update_alarm_sound()

    def _toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if not self.boxes: return
        self.monitor_thread = MonitorThread(self.boxes, interval=self.spin_interval.value())
        if self.reader:
            self.monitor_thread.set_reader(self.reader)
        self.monitor_thread.value_updated.connect(self._on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self._on_alarm_triggered)
        self.monitor_thread.alarm_state_cleared.connect(self.check_and_update_alarm_sound)
        self.monitor_thread.countdown_tick.connect(self._on_countdown_tick)
        self.monitor_thread.start()

        self.monitoring = True
        self.btn_monitor.setText("⏹ 停止监控")
        self._update_button_styles()

    def stop_monitor(self):
        if hasattr(self, 'monitor_thread') and self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        self.monitoring = False
        self.btn_monitor.setText("▶ 开始监控")
        self.lbl_countdown.setText("⏳ 0.0s")
        self._update_button_styles()
        self.alarm_player.stop()

    def _on_countdown_tick(self, rem):
        # 需求六：更新倒计时
        self.lbl_countdown.setText(f"⏳ {rem:.1f}s")

    def _on_value_updated(self, box, time_str, val, raw_text):
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

    def check_and_update_alarm_sound(self):
        # 需求四：只要有未静音且处于未消除报警状态的选框，就响铃；否则立即静音
        should_play = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if should_play:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def _on_alarm_triggered(self, box, time_str, val):
        box.set_alarm_state(True)
        self.check_and_update_alarm_sound()

    def save_config(self):
        data = {
            'interval': self.spin_interval.value(),
            'count': self.spin_count.value(),
            'log_interval': self.spin_log_interval.value(),
            'grille_interval': self.spin_grille_interval.value(),
            'grille_checked': self.chk_grille.isChecked(),
            'boxes': []
        }
        for b in self.boxes:
            data['boxes'].append({
                'name': b.name,
                'x': b.capture_x, 'y': b.capture_y,
                'w': b.capture_w, 'h': b.capture_h,
                'lower': b.lower, 'upper': b.upper
            })
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.spin_interval.setValue(data.get('interval', 1.0))
            self.spin_count.setValue(data.get('count', 30))
            self.spin_log_interval.setValue(data.get('log_interval', 1.0))
            self.spin_grille_interval.setValue(data.get('grille_interval', 2.0))
            self.chk_grille.setChecked(data.get('grille_checked', False))

            for item in data.get('boxes', []):
                box = OverlayRegionWidget(
                    box_id=len(self.boxes)+1,
                    x=item['x'], y=item['y'],
                    w=item['w'], h=item['h'],
                    name=item['name'],
                    lower=item.get('lower', 0.0), upper=item.get('upper', 100.0)
                )
                box.delete_requested.connect(self._delete_box)
                box.alarm_cleared.connect(self.check_and_update_alarm_sound)
                box.mute_toggled.connect(self.check_and_update_alarm_sound)

                box.set_max_log_count(self.spin_count.value())
                box.log_interval_min = self.spin_log_interval.value()
                box.show()
                self.boxes.append(box)
        except Exception:
            pass

    def close_app(self):
        if hasattr(self, 'f12_listener'):
            self.f12_listener.stop()
            self.f12_listener.wait()
        self.stop_monitor()
        self.stop_grille()
        self.save_config()
        for b in self.boxes:
            b.close()
        self.close()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec())
