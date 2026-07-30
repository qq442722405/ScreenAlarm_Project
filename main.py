import sys
import json
import os
import time
import re
import threading
import ctypes
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
    QListWidget, QCheckBox, QAbstractSpinBox, QFrame, QMessageBox
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
        VK_F12 = 0x7B
        was_pressed = False
        while self.running:
            state = user32.GetAsyncKeyState(VK_F12)
            is_pressed = bool(state & 0x8000)
            if is_pressed and not was_pressed:
                self.f12_triggered.emit()
            was_pressed = is_pressed
            self.msleep(50)


# ==================== 2. 报警声音播放器 ====================
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
        if self.is_playing: return
        with self.lock:
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
                while not self.stop_flag:
                    sound.play()
                    while pygame.mixer.get_busy() and not self.stop_flag:
                        pygame.time.wait(50)
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
                while not self.stop_flag:
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


# ==================== 4. 独立日志悬浮窗口 ====================
class StandaloneLogWindow(QWidget):
    def __init__(self, name, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle(f"数值历史 - {name}")
        self.resize(220, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.lbl_title = QLabel(f"📋 {name}")
        self.lbl_title.setStyleSheet("font-weight: bold; color: #00ff8c; font-size: 12px;")
        layout.addWidget(self.lbl_title)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: rgba(0, 0, 0, 0.5);
                color: #00ff8c;
                border: 1px solid #333333;
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 3px 5px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
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

    def add_log(self, time_str, val):
        self.list_widget.insertItem(0, f"[{time_str}]  {val:.2f}")
        while self.list_widget.count() > self.max_count:
            self.list_widget.takeItem(self.max_count)


# ==================== 5. 悬浮选框窗口 ====================
class OverlayRegionWidget(QWidget):
    delete_requested = Signal(object)
    alarm_cleared = Signal()

    def __init__(self, box_id, x, y, w, h, name="区域", lower=0.0, upper=100.0, parent=None):
        super().__init__(None)
        self.box_id = box_id
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(40, w)
        self.capture_h = max(20, h)
        self.bottom_bar_height = 80

        self.name = name
        self.lower = lower
        self.upper = upper
        self.last_log_time = 0.0

        self.is_alarm = False
        self.is_editing = False
        self.is_muted = False
        self.show_sub_controls = True

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._drag_pos = QPoint()
        self._resize_mode = None

        self.log_window = StandaloneLogWindow(self.name)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部：识别框占位区域
        self.capture_spacer = QWidget()
        self.capture_spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        main_layout.addWidget(self.capture_spacer)

        # 报警消除按钮
        self.btn_clear_alarm = QPushButton("🚨 消除", self)
        self.btn_clear_alarm.setStyleSheet("""
            QPushButton {
                background-color: #ff3333;
                color: white;
                border: 1px solid #ffffff;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
                padding: 1px 4px;
            }
            QPushButton:hover { background-color: #ff6666; }
        """)
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)
        self.btn_clear_alarm.hide()

        # 底部控制栏
        self.bottom_bar = QWidget()
        self.bottom_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bottom_bar.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 0.5);
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QLabel { color: #ffffff; border: none; background: transparent; }
            QPushButton {
                background-color: rgba(30, 30, 30, 0.7);
                color: white;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 2px 5px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: rgba(60, 60, 60, 0.8); }
            QDoubleSpinBox {
                background: rgba(0, 0, 0, 0.5);
                color: #00ff8c;
                border: 1px solid #00ff8c;
                font-size: 10px;
                border-radius: 2px;
            }
            QLineEdit {
                background-color: rgba(0, 0, 0, 0.5);
                color: #00ff8c;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #00ff8c;
                border-radius: 2px;
            }
        """)
        
        bottom_bar_layout = QHBoxLayout(self.bottom_bar)
        bottom_bar_layout.setContentsMargins(5, 5, 5, 5)
        bottom_bar_layout.setSpacing(4)

        # 控制组件面板
        self.ctrl_panel = QWidget()
        self.ctrl_panel.setStyleSheet("border: none; background: transparent;")
        ctrl_layout = QVBoxLayout(self.ctrl_panel)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(3)

        # 第一排：名称 & 删除按钮
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")
        row1_layout.addWidget(self.lbl_title)

        self.edit_title = QLineEdit(self.name)
        self.edit_title.setFixedHeight(20)
        self.edit_title.setVisible(False)
        self.edit_title.textChanged.connect(self._on_title_changed)
        row1_layout.addWidget(self.edit_title)

        row1_layout.addStretch()

        self.btn_delete = QPushButton("➖")
        self.btn_delete.setFixedSize(18, 18)
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 9px; font-weight: bold; font-size: 11px; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.setVisible(False)
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))
        row1_layout.addWidget(self.btn_delete)

        ctrl_layout.addLayout(row1_layout)

        # 第二排：记录与静音按钮
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(4)

        self.btn_toggle_log = QPushButton("📋 记录")
        self.btn_toggle_log.clicked.connect(self._toggle_log_window)
        row2_layout.addWidget(self.btn_toggle_log)

        self.btn_mute = QPushButton("🔊 静音")
        self.btn_mute.clicked.connect(self._toggle_mute)
        row2_layout.addWidget(self.btn_mute)

        row2_layout.addStretch()
        ctrl_layout.addLayout(row2_layout)

        # 第三排：上下限设置栏
        self.threshold_widget = QWidget()
        self.threshold_widget.setStyleSheet("border: none; background: transparent;")
        row3_layout = QHBoxLayout(self.threshold_widget)
        row3_layout.setContentsMargins(0, 2, 0, 0)
        row3_layout.setSpacing(4)

        lbl_low = QLabel("下限:")
        lbl_low.setStyleSheet("color: white; font-size: 10px;")
        row3_layout.addWidget(lbl_low)

        self.spin_lower = QDoubleSpinBox()
        self.spin_lower.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_lower.setRange(-99999, 99999)
        self.spin_lower.setValue(self.lower)
        self.spin_lower.setFixedWidth(38)
        self.spin_lower.valueChanged.connect(self._on_lower_changed)
        row3_layout.addWidget(self.spin_lower)

        lbl_up = QLabel("上限:")
        lbl_up.setStyleSheet("color: white; font-size: 10px;")
        row3_layout.addWidget(lbl_up)

        self.spin_upper = QDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setRange(-99999, 99999)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedWidth(38)
        self.spin_upper.valueChanged.connect(self._on_upper_changed)
        row3_layout.addWidget(self.spin_upper)

        self.threshold_widget.setVisible(False)
        ctrl_layout.addWidget(self.threshold_widget)

        # 第四行：显示实时识别结果
        row4_layout = QHBoxLayout()
        row4_layout.setContentsMargins(0, 2, 0, 0)
        
        self.lbl_result = QLabel("识别结果: --")
        self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")
        row4_layout.addWidget(self.lbl_result)
        row4_layout.addStretch()

        ctrl_layout.addLayout(row4_layout)
        bottom_bar_layout.addWidget(self.ctrl_panel, 1)

        main_layout.addWidget(self.bottom_bar)

        self._update_geometry()
        self.setMouseTracking(True)

    def set_result_val(self, val):
        if val is not None:
            self.lbl_result.setText(f"识别结果: {val:.2f}")
        else:
            self.lbl_result.setText("识别结果: --")

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
            self.log_window.show()
            self.log_window.raise_()

    def add_log_val(self, time_str, val):
        self.log_window.add_log(time_str, val)

    def set_max_log_count(self, count):
        self.log_window.set_max_count(count)

    def set_sub_controls_visible(self, visible):
        self.show_sub_controls = visible
        self._update_geometry()
        self.update()

    def _update_geometry(self):
        total_w = max(self.capture_w, 160)
        self.bottom_bar.adjustSize()
        self.bottom_bar_height = max(28, self.bottom_bar.sizeHint().height())
        
        if self.show_sub_controls:
            self.bottom_bar.setVisible(True)
            self.bottom_bar.setFixedHeight(self.bottom_bar_height)
            self.capture_spacer.setFixedHeight(self.capture_h)
            total_h = self.capture_h + self.bottom_bar_height
        else:
            self.bottom_bar.setVisible(False)
            self.capture_spacer.setFixedHeight(self.capture_h)
            total_h = self.capture_h

        self.setGeometry(self.capture_x, self.capture_y, total_w, total_h)

        btn_w, btn_h = 52, 22
        btn_x = max(5, self.capture_w - btn_w - 4)
        btn_y = 4
        self.btn_clear_alarm.setGeometry(btn_x, btn_y, btn_w, btn_h)
        if self.is_alarm:
            self.btn_clear_alarm.show()
            self.btn_clear_alarm.raise_()
        else:
            self.btn_clear_alarm.hide()

    def set_edit_mode(self, enabled):
        self.is_editing = enabled
        self.btn_delete.setVisible(enabled)
        self.lbl_title.setVisible(not enabled)
        self.edit_title.setVisible(enabled)
        self.threshold_widget.setVisible(enabled)
        self._update_geometry()
        self.update()

    def set_alarm_state(self, is_alarm):
        self.is_alarm = is_alarm
        if is_alarm:
            self.btn_clear_alarm.show()
            self.btn_clear_alarm.raise_()
        else:
            self.btn_clear_alarm.hide()
        self._update_geometry()
        self.update()

    def _on_clear_alarm(self):
        self.set_alarm_state(False)
        self.alarm_cleared.emit()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        self.btn_mute.setText("🔇 静音" if self.is_muted else "🔊 静音")
        self.btn_mute.setStyleSheet("QPushButton { background-color: #e65100; color: white; border: none; border-radius: 3px; padding: 2px 5px; font-size: 10px; }" if self.is_muted else "QPushButton { background-color: rgba(30, 30, 30, 0.7); color: white; border: 1px solid #444; border-radius: 3px; padding: 2px 5px; font-size: 10px; }")

    def _get_hit_mode(self, pos):
        x, y = pos.x(), pos.y()
        m = 6
        if y <= self.capture_h + m:
            cy = y
            ch = self.capture_h
            cw = self.capture_w
            if cy > ch - m and x > cw - m: return "BR"
            if cy > ch - m: return "B"
            if x > cw - m: return "R"
            if x < m: return "L"
            if cy < m: return "T"
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
        elif mode in ["B", "T"]: self.setCursor(Qt.SizeVerCursor)
        else: self.setCursor(Qt.SizeAllCursor)

        if event.buttons() & Qt.LeftButton:
            g_pos = event.globalPosition().toPoint()
            if self._resize_mode == "BR":
                self.capture_w = max(40, g_pos.x() - self.capture_x)
                self.capture_h = max(20, g_pos.y() - self.capture_y)
            elif self._resize_mode == "R":
                self.capture_w = max(40, g_pos.x() - self.capture_x)
            elif self._resize_mode == "B":
                self.capture_h = max(20, g_pos.y() - self.capture_y)
            elif self._resize_mode == "L":
                diff = self.capture_x - g_pos.x()
                if self.capture_w + diff >= 40:
                    self.capture_x = g_pos.x()
                    self.capture_w += diff
            elif self._resize_mode == "T":
                diff = self.capture_y - g_pos.y()
                if self.capture_h + diff >= 20:
                    self.capture_y = g_pos.y()
                    self.capture_h += diff
            elif self._resize_mode == "MOVE":
                new_p = g_pos - self._drag_pos
                self.capture_x = new_p.x()
                self.capture_y = new_p.y()

            self._update_geometry()
            self.update()

    def paintEvent(self, event):
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
            painter.setBrush(QColor(255, 0, 0, 45))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            # 【修复】正常监控时背景不填充绿光，防止截图中带有遮罩干扰OCR
            painter.setBrush(Qt.NoBrush)

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


# ==================== 7. 后台识别线程 (DPI缩放/多层容错OCR) ====================
class MonitorThread(QThread):
    value_updated = Signal(object, str, float)
    alarm_triggered = Signal(object, str, float)
    result_updated = Signal(object, object)
    countdown_signal = Signal(float)

    def __init__(self, boxes, interval=1.0, log_interval=1.0, dpr=1.0, parent=None):
        super().__init__(parent)
        self.boxes = boxes
        self.interval = max(0.1, interval)
        self.log_interval = max(0.1, log_interval)
        self.dpr = max(1.0, dpr) # 屏幕缩放比例
        self.running = True
        self.reader = None

    def set_reader(self, reader):
        self.reader = reader

    def update_params(self, interval, log_interval):
        self.interval = max(0.1, interval)
        self.log_interval = max(0.1, log_interval)

    def stop(self):
        self.running = False

    # 替换将容易混淆字母转为数字的容错工具
    def _clean_digit_text(self, text):
        tr = str.maketrans({
            'O': '0', 'o': '0', 'Q': '0', 'D': '0',
            'I': '1', 'l': '1', 'i': '1', '|': '1', '!': '1',
            'Z': '2', 'z': '2',
            'S': '5', 's': '5',
            'B': '8',
            'G': '6', 'g': '9', 'q': '9'
        })
        return text.translate(tr)

    def _recognize_number(self, img_np):
        if not self.reader:
            return None

        try:
            bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            h, w = bgr.shape[:2]
            if h <= 0 or w <= 0: return None

            # 小图平滑放大
            if h < 40 or w < 40:
                scale = max(2, int(80 / min(h, w)))
                scaled_bgr = cv2.resize(bgr, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
            else:
                scaled_bgr = bgr

            nums = []

            # --- 方案 1: 原始彩色平滑图像直接识别 ---
            ok1, buf1 = cv2.imencode(".png", scaled_bgr)
            if ok1:
                raw_text = str(self.reader.classification(buf1.tobytes()))
                clean_t = self._clean_digit_text(raw_text).replace(' ', '')
                clean_t = re.sub(r'(?<=\d)[\,\:\·\'\`\_\-\*\°\o\O\a\e\~]+(?=\d)', '.', clean_t)
                nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)

            # --- 方案 2: 降噪/灰度对比度强化 ---
            if not nums:
                gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
                norm_gray = cv2.normalize(gray, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)
                ok2, buf2 = cv2.imencode(".png", norm_gray)
                if ok2:
                    raw_text2 = str(self.reader.classification(buf2.tobytes()))
                    clean_t2 = self._clean_digit_text(raw_text2).replace(' ', '')
                    clean_t2 = re.sub(r'(?<=\d)[\,\:\·\'\`\_\-\*\°\o\O\a\e\~]+(?=\d)', '.', clean_t2)
                    nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t2)

            # --- 方案 3: 二值化翻转 ---
            if not nums:
                gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                ok3, buf3 = cv2.imencode(".png", thresh)
                if ok3:
                    raw_text3 = str(self.reader.classification(buf3.tobytes()))
                    clean_t3 = self._clean_digit_text(raw_text3).replace(' ', '')
                    clean_t3 = re.sub(r'(?<=\d)[\,\:\·\'\`\_\-\*\°\o\O\a\e\~]+(?=\d)', '.', clean_t3)
                    nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t3)

            # 包含小数点的数值优先输出
            if nums and '.' in nums[0]:
                try: return float(nums[0])
                except ValueError: pass

            # 若仅识别为整数，则尝试通过轮廓寻找丢失的小数点
            if nums:
                gray_c = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
                _, bin_img = cv2.threshold(gray_c, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                if np.mean(bin_img) > 127: bin_img = cv2.bitwise_not(bin_img)

                contours, _ = cv2.findContours(bin_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                boxes_c = [cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2]*cv2.boundingRect(c)[3] >= 4]

                if boxes_c:
                    boxes_c.sort(key=lambda b: b[0])
                    max_h = max(b[3] for b in boxes_c) if boxes_c else 0
                    if max_h > 0:
                        digit_boxes = [b for b in boxes_c if b[3] >= 0.35 * max_h]
                        dot_boxes = [b for b in boxes_c if b[3] < 0.35 * max_h and b[2] < 0.35 * max_h]

                        raw_num_str = nums[0].replace('.', '')
                        if len(raw_num_str) == len(digit_boxes) and len(digit_boxes) > 1:
                            for dot in dot_boxes:
                                dot_center_x = dot[0] + dot[2] / 2.0
                                for i in range(len(digit_boxes) - 1):
                                    d1_right = digit_boxes[i][0] + digit_boxes[i][2]
                                    d2_left = digit_boxes[i+1][0]
                                    if d1_right - 10 <= dot_center_x <= d2_left + 10:
                                        fixed_str = raw_num_str[:i+1] + '.' + raw_num_str[i+1:]
                                        return float(fixed_str)

                try: return float(nums[0])
                except ValueError: pass

        except Exception:
            pass

        return None

    def run(self):
        with mss.mss() as sct:
            while self.running:
                boxes_snapshot = list(self.boxes)
                
                # 图像截图与 OCR 识别
                if boxes_snapshot and self.reader:
                    for box in boxes_snapshot:
                        if not self.running: break

                        # 【核心修复】：应用高 DPI 缩放换算物理像素，向内裁切 2 像素避开边框
                        x = int((box.capture_x + 2) * self.dpr)
                        y = int((box.capture_y + 2) * self.dpr)
                        w = int(max(10, box.capture_w - 4) * self.dpr)
                        h = int(max(10, box.capture_h - 4) * self.dpr)

                        if w > 0 and h > 0:
                            try:
                                bbox = {"top": y, "left": x, "width": w, "height": h}
                                sct_img = sct.grab(bbox)
                                img_np = np.array(sct_img)

                                val = self._recognize_number(img_np)
                                now_time = time.time()
                                now_str = datetime.now().strftime("%H:%M:%S")

                                self.result_updated.emit(box, val)

                                if val is not None:
                                    if now_time - getattr(box, 'last_log_time', 0.0) >= self.log_interval * 60:
                                        box.last_log_time = now_time
                                        self.value_updated.emit(box, now_str, val)

                                    if val < box.lower or val > box.upper:
                                        self.alarm_triggered.emit(box, now_str, val)
                                    else:
                                        box.set_alarm_state(False)
                            except Exception: pass

                        self.msleep(100)

                # 倒计时逻辑
                wait_sec = max(0.1, self.interval)
                steps = max(1, int(wait_sec * 10))
                for step in range(steps, 0, -1):
                    if not self.running: break
                    self.countdown_signal.emit(step / 10.0)
                    self.msleep(100)
                
                if self.running:
                    self.countdown_signal.emit(0.0)


# ==================== 8. 全局控制面板 (添加文字按钮与识别排查) ====================
class GlobalControlPanel(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setObjectName("MainPanel")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.boxes = []
        self.monitoring = False
        self.is_editing = False
        self.is_collapsed = False
        self.sub_controls_visible = True
        self.reader = None
        self.ocr_loading = True
        self.ocr_error_msg = ""
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

        # 样式定义
        self.setStyleSheet("""
            QWidget#MainPanel { 
                background-color: rgba(13, 13, 13, 0.85); 
                border-radius: 8px; 
                border: 1px solid #333333;
            }
            QLabel { 
                color: #ffffff; 
                font-size: 11px; 
                font-weight: bold; 
                background: transparent;
                border: none;
            }
            QPushButton { 
                background-color: rgba(30, 30, 30, 0.8); 
                color: #ffffff; 
                border: 1px solid #444444; 
                border-radius: 4px; 
                padding: 0px 8px; 
                height: 26px;
                font-size: 11px; 
                font-weight: bold; 
            }
            QPushButton:hover { 
                background-color: rgba(60, 60, 60, 0.9); 
                border: 1px solid #666666;
            }
            QDoubleSpinBox, QSpinBox { 
                background-color: rgba(0, 0, 0, 0.5); 
                color: #00ff8c; 
                border: 1px solid #00ff8c; 
                border-radius: 3px; 
                font-size: 11px; 
                font-weight: bold; 
                padding: 0px 2px;
                height: 22px;
            }
            QCheckBox { 
                color: #ffffff; 
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
                background: rgba(0, 0, 0, 0.5);
            }
            QCheckBox::indicator:checked {
                background: #00ff8c;
            }
        """)

        # 50% 黑色卡片工厂
        def make_black_card(widgets):
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: rgba(0, 0, 0, 0.5);
                    border: 1px solid #333333;
                    border-radius: 5px;
                }
                QLabel { border: none; background: transparent; color: #ffffff; }
            """)
            layout = QHBoxLayout(card)
            layout.setContentsMargins(6, 3, 6, 3)
            layout.setSpacing(5)
            for w in widgets:
                layout.addWidget(w)
            return card

        # ---------- 排版 1：顶部主控制栏 ----------
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(5)

        self.btn_monitor = QPushButton("▶ 开始监控")
        self.btn_monitor.setFixedHeight(26)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        top_bar_layout.addWidget(self.btn_monitor)

        # 倒计时显示
        self.lbl_countdown = QLabel("⏳ 0.0s")
        self.lbl_countdown.setStyleSheet("color: #00ff8c; font-size: 12px; font-weight: bold; padding: 0 4px;")
        top_bar_layout.addWidget(self.lbl_countdown)

        # 【需求一】：按钮增加文字 (控制栏显示/隐藏)
        self.btn_toggle_sub = QPushButton("👁 隐藏控制栏")
        self.btn_toggle_sub.setFixedHeight(26)
        self.btn_toggle_sub.setToolTip("显示/隐藏所有选框下方的操作控制栏")
        self.btn_toggle_sub.clicked.connect(self._toggle_sub_controls)
        top_bar_layout.addWidget(self.btn_toggle_sub)

        # 【需求一】：按钮增加文字 (面板折叠/展开)
        self.btn_collapse = QPushButton("▲ 收起面板")
        self.btn_collapse.setFixedHeight(26)
        self.btn_collapse.setToolTip("展开/收起下方参数设置面板")
        self.btn_collapse.clicked.connect(self._toggle_collapse)
        top_bar_layout.addWidget(self.btn_collapse)

        self.btn_exit = QPushButton("❌")
        self.btn_exit.setFixedSize(26, 26)
        self.btn_exit.setToolTip("退出程序")
        self.btn_exit.clicked.connect(self.close_app)
        top_bar_layout.addWidget(self.btn_exit)

        main_layout.addLayout(top_bar_layout)

        # ---------- 排版 2：配置面板 ----------
        self.config_panel = QWidget()
        config_panel_layout = QVBoxLayout(self.config_panel)
        config_panel_layout.setContentsMargins(0, 2, 0, 0)
        config_panel_layout.setSpacing(5)

        # 第一排：【间隔】/【记录间隔】/【记录数】
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(5)

        # 1. 间隔
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        self.spin_interval.setFixedSize(48, 22)
        self.spin_interval.setRange(0.1, 99999.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.valueChanged.connect(self._on_params_changed)
        card_interval = make_black_card([QLabel("⏱ 间隔(s):"), self.spin_interval])
        row1_layout.addWidget(card_interval)

        # 2. 记录间隔
        self.spin_log_interval = QDoubleSpinBox()
        self.spin_log_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_log_interval.setAlignment(Qt.AlignCenter)
        self.spin_log_interval.setFixedSize(48, 22)
        self.spin_log_interval.setRange(0.1, 1440.0)
        self.spin_log_interval.setValue(1.0)
        self.spin_log_interval.setSingleStep(0.5)
        self.spin_log_interval.valueChanged.connect(self._on_params_changed)
        card_log_interval = make_black_card([QLabel("📝 记录间隔(分):"), self.spin_log_interval])
        row1_layout.addWidget(card_log_interval)

        # 3. 记录数
        self.spin_count = QSpinBox()
        self.spin_count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_count.setAlignment(Qt.AlignCenter)
        self.spin_count.setFixedSize(40, 22)
        self.spin_count.setRange(5, 500)
        self.spin_count.setValue(30)
        self.spin_count.valueChanged.connect(self._on_count_changed)
        card_count = make_black_card([QLabel("📊 记录数:"), self.spin_count])
        row1_layout.addWidget(card_count)

        self.btn_edit = QPushButton("⚙️ 调整")
        self.btn_edit.setFixedHeight(26)
        self.btn_edit.clicked.connect(self._toggle_edit)
        row1_layout.addWidget(self.btn_edit)

        self.btn_add = QPushButton("➕ 添加选框")
        self.btn_add.setStyleSheet("background-color: #008855; color: white; height: 26px; font-weight: bold;")
        self.btn_add.setVisible(False)
        self.btn_add.clicked.connect(self._add_box_picker)
        row1_layout.addWidget(self.btn_add)

        config_panel_layout.addLayout(row1_layout)

        # 第二排：【细格栅】/【执行间隔】
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(5)

        # 4. 细格栅
        self.chk_grille = QCheckBox("细格栅")
        card_grille = make_black_card([self.chk_grille])
        row2_layout.addWidget(card_grille)

        # 5. 执行间隔
        self.spin_grille_interval = QDoubleSpinBox()
        self.spin_grille_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_grille_interval.setAlignment(Qt.AlignCenter)
        self.spin_grille_interval.setFixedSize(48, 22)
        self.spin_grille_interval.setRange(0.1, 1440.0)
        self.spin_grille_interval.setValue(2.0)
        self.spin_grille_interval.setSingleStep(0.5)
        self.spin_grille_interval.valueChanged.connect(self._on_grille_interval_changed)
        card_grille_interval = make_black_card([QLabel("执行间隔(分):"), self.spin_grille_interval])
        row2_layout.addWidget(card_grille_interval)

        self.btn_grille_start = QPushButton("▶ 开始操作")
        self.btn_grille_start.setFixedHeight(26)
        self.btn_grille_start.setStyleSheet("background-color: #0066cc; color: white; font-weight: bold;")
        self.btn_grille_start.clicked.connect(self._toggle_grille)
        row2_layout.addWidget(self.btn_grille_start)

        row2_layout.addStretch()
        config_panel_layout.addLayout(row2_layout)

        main_layout.addWidget(self.config_panel)

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
        self.btn_collapse.setText("▼ 展开面板" if self.is_collapsed else "▲ 收起面板")
        self.btn_toggle_sub.setText("👁 隐藏控制栏" if self.sub_controls_visible else "👁 显示控制栏")
        self.btn_monitor.setStyleSheet(f"background-color: {'#cc3333' if self.monitoring else '#008855'}; color: white; font-weight: bold; height: 26px;")

    def _toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        self.config_panel.setVisible(not self.is_collapsed)
        self._update_button_styles()
        self.adjustSize()

    def _toggle_sub_controls(self):
        self.sub_controls_visible = not self.sub_controls_visible
        for box in self.boxes:
            box.set_sub_controls_visible(self.sub_controls_visible)
        self._update_button_styles()

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
                QMessageBox.warning(self, "提示", "请先勾选【细格栅】选项！")
                return
            self.start_grille()

    def start_grille(self):
        self.grille_thread = FineGrilleThread(cycle_interval_min=self.spin_grille_interval.value())
        self.grille_thread.start()
        self.btn_grille_start.setText("⏹ 停止操作(F12)")
        self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold; height: 26px;")

    def stop_grille(self):
        if self.grille_thread:
            self.grille_thread.stop()
            self.grille_thread.wait()
            self.grille_thread = None
        self.btn_grille_start.setText("▶ 开始操作")
        self.btn_grille_start.setStyleSheet("background-color: #0066cc; color: white; font-weight: bold; height: 26px;")

    def _position_top_right(self):
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(screen_geo.width() - self.width() - 20, 20)

    def _init_ocr(self):
        class OCRLoader(QThread):
            loaded = Signal(object, str)
            def run(self):
                try:
                    import ddddocr
                    reader = ddddocr.DdddOcr(show_ad=False)
                    self.loaded.emit(reader, "")
                except Exception as e:
                    self.loaded.emit(None, str(e))

        self.ocr_loading = True
        self.loader = OCRLoader()
        self.loader.loaded.connect(self._on_ocr_loaded)
        self.loader.start()

    def _on_ocr_loaded(self, reader, err_msg):
        self.reader = reader
        self.ocr_loading = False
        self.ocr_error_msg = err_msg
        if hasattr(self, 'monitor_thread') and self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.set_reader(reader)

    def _on_params_changed(self):
        if hasattr(self, 'monitor_thread') and self.monitor_thread:
            self.monitor_thread.update_params(
                interval=self.spin_interval.value(),
                log_interval=self.spin_log_interval.value()
            )

    def _on_count_changed(self, val):
        for box in self.boxes:
            box.set_max_log_count(val)

    def _toggle_edit(self):
        self.is_editing = not self.is_editing
        self.btn_add.setVisible(self.is_editing)
        if self.is_editing:
            self.btn_edit.setText("✅ 完成调整")
            self.btn_edit.setStyleSheet("background-color: #e6b800; color: black; height: 26px; font-weight: bold;")
        else:
            self.btn_edit.setText("⚙️ 调整")
            self.btn_edit.setStyleSheet("background-color: rgba(30, 30, 30, 0.8); color: white; height: 26px; font-weight: bold;")
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
        box.alarm_cleared.connect(self.alarm_player.stop)
        box.set_edit_mode(self.is_editing)
        box.set_sub_controls_visible(self.sub_controls_visible)
        box.set_max_log_count(self.spin_count.value())
        box.show()
        self.boxes.append(box)

    def _delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()

    def _toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            if not self.boxes:
                QMessageBox.warning(self, "提示", "请先点击【⚙️ 调整】->【➕ 添加选框】创建识别区域！")
                return

            if not self.reader:
                if self.ocr_loading:
                    QMessageBox.information(self, "提示", "OCR 识别引擎正在加载中，监控与倒计时已开启，加载完成后会自动显示结果。")
                else:
                    QMessageBox.critical(self, "OCR 引擎加载失败", f"无法使用识别功能！未检测到 ddddocr 库或依赖缺失。\n\n具体错误：{self.ocr_error_msg}\n\n解决办法：请打开 CMD 命令行执行 pip install ddddocr 重新安装。")

            self.start_monitor()

    def start_monitor(self):
        # 获得主屏幕高 DPI 缩放比例，解决多倍缩放屏幕截图位置偏移
        dpr = QApplication.primaryScreen().devicePixelRatio()
        
        self.monitor_thread = MonitorThread(
            self.boxes, 
            interval=self.spin_interval.value(),
            log_interval=self.spin_log_interval.value(),
            dpr=dpr
        )
        if self.reader:
            self.monitor_thread.set_reader(self.reader)
            
        self.monitor_thread.value_updated.connect(self._on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self._on_alarm_triggered)
        self.monitor_thread.result_updated.connect(self._on_result_updated)
        self.monitor_thread.countdown_signal.connect(self._on_countdown_updated)
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

    def _on_countdown_updated(self, remaining):
        self.lbl_countdown.setText(f"⏳ {remaining:.1f}s")

    def _on_value_updated(self, box, time_str, val):
        box.add_log_val(time_str, val)

    def _on_alarm_triggered(self, box, time_str, val):
        box.set_alarm_state(True)
        if not box.is_muted:
            self.alarm_player.play()

    def _on_result_updated(self, box, val):
        box.set_result_val(val)

    def save_config(self):
        data = {
            'panel_x': self.x(),
            'panel_y': self.y(),
            'interval': self.spin_interval.value(),
            'log_interval': self.spin_log_interval.value(),
            'count': self.spin_count.value(),
            'grille_interval': self.spin_grille_interval.value(),
            'grille_checked': self.chk_grille.isChecked(),
            'boxes': []
        }
        for b in self.boxes:
            data['boxes'].append({
                'name': b.name,
                'x': b.capture_x, 'y': b.capture_y,
                'w': b.capture_w, 'h': b.capture_h,
                'bottom_bar_height': b.bottom_bar_height,
                'lower': b.lower, 'upper': b.upper
            })
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'panel_x' in data and 'panel_y' in data:
                self.move(data['panel_x'], data['panel_y'])

            self.spin_interval.setValue(data.get('interval', 1.0))
            self.spin_log_interval.setValue(data.get('log_interval', 1.0))
            self.spin_count.setValue(data.get('count', 30))
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
                box.bottom_bar_height = item.get('bottom_bar_height', 80)
                box._update_geometry()
                box.delete_requested.connect(self._delete_box)
                box.alarm_cleared.connect(self.alarm_player.stop)
                box.set_sub_controls_visible(self.sub_controls_visible)
                box.set_max_log_count(self.spin_count.value())
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
