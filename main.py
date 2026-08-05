import sys
import json
import os
import time
import re
import threading
import ctypes
import socket
from datetime import datetime

# 开启 Windows 高 DPI 屏幕兼容支持
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QSpinBox,
    QListWidget, QCheckBox, QAbstractSpinBox, QFrame, QSizePolicy,
    QDialog, QFormLayout, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QIcon, QImage
)

import mss
import numpy as np
import cv2

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

try:
    from flask import Flask, jsonify, render_template_string, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


# ==================== 获取本机局域网 IP ====================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ==================== 0. 自定义无冗余 .00 的 SpinBox ====================
class CleanDoubleSpinBox(QDoubleSpinBox):
    """自动消除末尾 .00 / 冗余 0 的输入框"""
    def textFromValue(self, val):
        s = f"{val:.2f}"
        if s.endswith('.00'):
            return s[:-3]
        elif s.endswith('0') and '.' in s:
            return s[:-1]
        return s


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
    countdown_tick = Signal(float)

    def __init__(self, cycle_interval_min=2.0, parent=None):
        super().__init__(parent)
        self.cycle_interval_min = cycle_interval_min
        self.running = True

    def set_interval(self, minutes):
        self.cycle_interval_min = max(0.1, minutes)

    def stop(self):
        self.running = False

    def _safe_sleep(self, seconds):
        start_t = time.time()
        while self.running and (time.time() - start_t < seconds):
            rem = max(0.0, seconds - (time.time() - start_t))
            self.countdown_tick.emit(rem)
            self.msleep(100)
        return self.running

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


# ==================== 3.5 自定义点击脚本执行线程 ====================
class ScriptRunnerThread(QThread):
    finished_signal = Signal()

    def __init__(self, targets, delay, parent=None):
        super().__init__(parent)
        self.targets = targets
        self.delay = max(0.01, float(delay))

    def run(self):
        user32 = ctypes.windll.user32
        for t in self.targets:
            x, y = int(t['x']), int(t['y'])
            user32.SetCursorPos(x, y)
            time.sleep(0.02)
            user32.mouse_event(2, 0, 0, 0, 0) # Down
            user32.mouse_event(4, 0, 0, 0, 0) # Up
            time.sleep(self.delay)
        self.finished_signal.emit()


# ==================== 3.6 点击脚本编辑弹窗 ====================
class ScriptEditDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("➕ 添加点击脚本")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(320, 380)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; }
            QLineEdit, QDoubleSpinBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
        """)

        self.targets = []

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("例如: 自动连点脚本1")

        self.spin_delay = CleanDoubleSpinBox()
        self.spin_delay.setRange(0.01, 60.0)
        self.spin_delay.setValue(0.5)
        self.spin_delay.setSingleStep(0.1)

        form.addRow("脚本名称:", self.edit_name)
        form.addRow("统一延迟(秒):", self.spin_delay)
        layout.addLayout(form)

        layout.addWidget(QLabel("🎯 点击目标列表:"))

        self.list_targets = QListWidget()
        self.list_targets.setStyleSheet("background: rgba(0,0,0,0.5); color: #00ff8c; font-size: 11px; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px;")
        layout.addWidget(self.list_targets)

        btn_box = QHBoxLayout()
        self.btn_pick = QPushButton("🎯 抓取目标")
        self.btn_pick.setStyleSheet("background-color: #0088cc; color: white;")
        self.btn_pick.clicked.connect(self._pick_target)

        self.btn_del_target = QPushButton("🗑 删除目标")
        self.btn_del_target.clicked.connect(self._del_target)

        btn_box.addWidget(self.btn_pick)
        btn_box.addWidget(self.btn_del_target)
        layout.addLayout(btn_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_target(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()
        def on_picked(x, y, w, h):
            self.show()
            if w == 0 and h == 0 and x == 0 and y == 0:
                return
            cx = x + w // 2 if w > 0 else x
            cy = y + h // 2 if h > 0 else y
            self.targets.append({"x": cx, "y": cy})
            self._update_list()

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _del_target(self):
        row = self.list_targets.currentRow()
        if 0 <= row < len(self.targets):
            self.targets.pop(row)
            self._update_list()

    def _update_list(self):
        self.list_targets.clear()
        for i, t in enumerate(self.targets):
            self.list_targets.addItem(f"目标 {i+1}: (X={t['x']}, Y={t['y']})")

    def _on_accept(self):
        if not self.edit_name.text().strip():
            return
        if not self.targets:
            return
        self.accept()

    def get_data(self):
        return {
            "id": int(time.time() * 1000) % 1000000,
            "name": self.edit_name.text().strip(),
            "delay": self.spin_delay.value(),
            "targets": self.targets
        }


# ==================== 4. OCR 识别参数调整对话框 ====================
class OCRAdjustDialog(QDialog):
    def __init__(self, params, reader=None, parent=None):
        super().__init__(parent)
        self.params = params.copy()
        self.reader = reader
        self.crop_bgr = None

        self.setWindowTitle("⚙️ 识别图像预处理与预览调整")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; }
            QDoubleSpinBox, QSpinBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
        """)

        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        form = QFormLayout()

        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(1.0, 10.0)
        self.spin_scale.setSingleStep(0.5)
        self.spin_scale.setValue(self.params.get('scale', 3.0))

        self.spin_clahe = QDoubleSpinBox()
        self.spin_clahe.setRange(0.0, 20.0)
        self.spin_clahe.setSingleStep(0.5)
        self.spin_clahe.setValue(self.params.get('clahe', 2.0))

        self.spin_block = QSpinBox()
        self.spin_block.setRange(3, 99)
        self.spin_block.setSingleStep(2)
        self.spin_block.setValue(self.params.get('thresh_block', 11))

        self.spin_c = QSpinBox()
        self.spin_c.setRange(0, 50)
        self.spin_c.setValue(self.params.get('thresh_c', 2))

        self.spin_scale.valueChanged.connect(self.update_preview)
        self.spin_clahe.valueChanged.connect(self.update_preview)
        self.spin_block.valueChanged.connect(self.update_preview)
        self.spin_c.valueChanged.connect(self.update_preview)

        form.addRow("放大倍数:", self.spin_scale)
        form.addRow("对比度增强 (CLAHE):", self.spin_clahe)
        form.addRow("二值化块大小 (奇数):", self.spin_block)
        form.addRow("二值化常数 C:", self.spin_c)

        top_layout.addLayout(form)

        self.btn_pick = QPushButton("📐 识别框选")
        self.btn_pick.setFixedHeight(40)
        self.btn_pick.setStyleSheet("background-color: #0088cc; color: white; font-size: 12px; font-weight: bold;")
        self.btn_pick.clicked.connect(self._pick_preview_area)
        top_layout.addWidget(self.btn_pick)

        main_layout.addLayout(top_layout)

        img_layout = QHBoxLayout()

        box_orig = QVBoxLayout()
        lbl_title_orig = QLabel("📷 原始截取图")
        lbl_title_orig.setAlignment(Qt.AlignCenter)
        box_orig.addWidget(lbl_title_orig)
        self.lbl_orig_img = QLabel("未框选区域")
        self.lbl_orig_img.setAlignment(Qt.AlignCenter)
        self.lbl_orig_img.setFixedSize(220, 130)
        self.lbl_orig_img.setStyleSheet("border: 1px dashed rgba(255,255,255,0.3); background-color: rgba(0,0,0,0.5); border-radius: 4px;")
        box_orig.addWidget(self.lbl_orig_img)

        box_proc = QVBoxLayout()
        lbl_title_proc = QLabel("⚡ 调整后二值图")
        lbl_title_proc.setAlignment(Qt.AlignCenter)
        box_proc.addWidget(lbl_title_proc)
        self.lbl_proc_img = QLabel("未框选区域")
        self.lbl_proc_img.setAlignment(Qt.AlignCenter)
        self.lbl_proc_img.setFixedSize(220, 130)
        self.lbl_proc_img.setStyleSheet("border: 1px dashed rgba(255,255,255,0.3); background-color: rgba(0,0,0,0.5); border-radius: 4px;")
        box_proc.addWidget(self.lbl_proc_img)

        img_layout.addLayout(box_orig)
        img_layout.addLayout(box_proc)
        main_layout.addLayout(img_layout)

        self.lbl_ocr_result = QLabel("🔍 识别结果: --")
        self.lbl_ocr_result.setAlignment(Qt.AlignCenter)
        self.lbl_ocr_result.setStyleSheet("color: #00ff8c; font-size: 13px; font-weight: bold; background: rgba(0,0,0,0.4); padding: 6px; border-radius: 4px;")
        main_layout.addWidget(self.lbl_ocr_result)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    def _pick_preview_area(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0:
                return
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0
            rx, ry, rw, rh = int(x * scale), int(y * scale), int(w * scale), int(h * scale)

            with mss.mss() as sct:
                sct_img = sct.grab({"top": ry, "left": rx, "width": rw, "height": rh})
                img_np = np.array(sct_img)
                if img_np.shape[2] == 4:
                    self.crop_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                else:
                    self.crop_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            self.update_preview()

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def update_preview(self):
        if self.crop_bgr is None:
            return

        p = self.get_params()
        scale_factor = max(1.0, float(p['scale']))
        h, w = self.crop_bgr.shape[:2]
        new_w, new_h = max(1, int(w * scale_factor)), max(1, int(h * scale_factor))

        scaled_bgr = cv2.resize(self.crop_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        orig_rgb = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2RGB)
        qimg_orig = QImage(orig_rgb.data, new_w, new_h, new_w * 3, QImage.Format_RGB888)
        pix_orig = QPixmap.fromImage(qimg_orig)
        self.lbl_orig_img.setPixmap(pix_orig.scaled(self.lbl_orig_img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
        clahe_clip = float(p['clahe'])
        if clahe_clip > 0:
            clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
        else:
            enhanced = gray

        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
        block = int(p['thresh_block'])
        if block % 2 == 0:
            block += 1
        c_val = int(p['thresh_c'])

        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, c_val)

        qimg_proc = QImage(binary.data, new_w, new_h, new_w, QImage.Format_Grayscale8)
        pix_proc = QPixmap.fromImage(qimg_proc)
        self.lbl_proc_img.setPixmap(pix_proc.scaled(self.lbl_proc_img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        if self.reader:
            try:
                ok, buf = cv2.imencode(".png", binary)
                if ok:
                    raw_text = str(self.reader.classification(buf.tobytes()))
                    self.lbl_ocr_result.setText(f"🔍 识别结果: {raw_text if raw_text else '(未识别到文本)'}")
                else:
                    self.lbl_ocr_result.setText("🔍 识别结果: 图像编码失败")
            except Exception as e:
                self.lbl_ocr_result.setText(f"🔍 识别结果: 识别异常 ({e})")
        else:
            self.lbl_ocr_result.setText("🔍 识别结果: (OCR引擎未准备就绪)")

    def get_params(self):
        block = self.spin_block.value()
        if block % 2 == 0:
            block += 1
        return {
            'scale': self.spin_scale.value(),
            'clahe': self.spin_clahe.value(),
            'thresh_block': block,
            'thresh_c': self.spin_c.value()
        }


# ==================== 5. 悬浮识别选框窗口 ====================
class OverlayRegionWidget(QWidget):
    delete_requested = Signal(object)
    alarm_cleared = Signal()
    mute_toggled = Signal()

    def __init__(self, box_id, x, y, w, h, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, parent=None):
        super().__init__(None)
        self.box_id = box_id
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(1, w)
        self.capture_h = max(1, h)

        self.name = name
        self.lower = lower
        self.mid_val = mid_val  # 预警值
        self.upper = upper
        self.decimal_places = decimal_places

        self.log_interval_min = 1.0
        self.last_log_time = 0.0
        self.max_log_count = 30

        self.is_alarm = False
        self.user_cleared_alarm = False
        self.last_alarm_val = None

        self.is_editing = False
        self.is_muted = False
        self.panel_hidden = False

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._drag_pos = QPoint()
        self._resize_mode = None

        # ---------------- 日志独立小弹窗 ----------------
        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle(f"📜 识别日志 - {self.name}")
        self.log_dialog.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.log_dialog.setFixedSize(280, 220)
        self.log_dialog.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
        """)
        log_dialog_layout = QVBoxLayout(self.log_dialog)
        self.list_widget = QListWidget()
        log_dialog_layout.addWidget(self.list_widget)

        # ---------------- 主悬浮窗口布局 ----------------
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.capture_spacer = QWidget()
        self.capture_spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        main_layout.addWidget(self.capture_spacer)

        self.control_panel = QWidget()
        self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.8); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        panel_layout = QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)

        # ====== 第一排：标题 / 识别结果 / 删除 ======
        self.row1_container = QWidget()
        row1_layout = QHBoxLayout(self.row1_container)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(4)

        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")

        self.edit_title = QLineEdit(self.name)
        self.edit_title.setStyleSheet("background-color: rgba(42, 42, 60, 0.5); color: #00ff8c; font-size: 11px; font-weight: bold; border: 1px solid #00ff8c; border-radius: 2px;")
        self.edit_title.setVisible(False)
        self.edit_title.textChanged.connect(self._on_title_changed)

        self.lbl_result = QLabel("--")
        self.lbl_result.setMaximumWidth(55)
        self.lbl_result.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: bold; margin-left: 2px;")

        self.btn_delete = QPushButton("❌")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 10px; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))

        row1_layout.addWidget(self.lbl_title)
        row1_layout.addWidget(self.edit_title)
        row1_layout.addWidget(self.lbl_result)
        row1_layout.addStretch()
        row1_layout.addWidget(self.btn_delete)
        panel_layout.addWidget(self.row1_container)

        # ====== 第二排：下限 / 上限 ======
        self.row2_container = QWidget()
        row2_layout = QHBoxLayout(self.row2_container)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(3)

        self.lbl_lower = QLabel("下限:")
        self.lbl_lower.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_lower = CleanDoubleSpinBox()
        self.spin_lower.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_lower.setAlignment(Qt.AlignCenter)
        self.spin_lower.setRange(-99999.0, 99999.0)
        self.spin_lower.setValue(self.lower)
        self.spin_lower.setFixedSize(40, 20)
        self.spin_lower.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_lower.valueChanged.connect(self._on_lower_changed)

        self.lbl_upper = QLabel("上限:")
        self.lbl_upper.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_upper = CleanDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setAlignment(Qt.AlignCenter)
        self.spin_upper.setRange(-99999.0, 99999.0)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedSize(40, 20)
        self.spin_upper.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_upper.valueChanged.connect(self._on_upper_changed)

        row2_layout.addWidget(self.lbl_lower)
        row2_layout.addWidget(self.spin_lower)
        row2_layout.addSpacing(6)
        row2_layout.addWidget(self.lbl_upper)
        row2_layout.addWidget(self.spin_upper)
        row2_layout.addStretch()
        panel_layout.addWidget(self.row2_container)

        # ====== 第三排：预警值 / 🚨 消除报警 ======
        self.row3_container = QWidget()
        row3_layout = QHBoxLayout(self.row3_container)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(3)

        self.lbl_mid = QLabel("预警值:")
        self.lbl_mid.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_mid = CleanDoubleSpinBox()
        self.spin_mid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_mid.setAlignment(Qt.AlignCenter)
        self.spin_mid.setRange(-99999.0, 99999.0)
        self.spin_mid.setValue(self.mid_val)
        self.spin_mid.setFixedSize(40, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addSpacing(6)
        row3_layout.addWidget(self.btn_clear_alarm)
        row3_layout.addStretch()
        panel_layout.addWidget(self.row3_container)

        # ====== 第四排：静音 / 小数点 / 📜 日志 ======
        self.row4_container = QWidget()
        row4_layout = QHBoxLayout(self.row4_container)
        row4_layout.setContentsMargins(0, 0, 0, 0)
        row4_layout.setSpacing(3)

        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedSize(22, 20)
        self.btn_mute.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.lbl_dec = QLabel("小数点:")
        self.lbl_dec.setStyleSheet("color: #a0a0a0; font-size: 10px; font-weight: bold;")
        self.spin_dec = QSpinBox()
        self.spin_dec.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_dec.setAlignment(Qt.AlignCenter)
        self.spin_dec.setRange(0, 4)
        self.spin_dec.setValue(self.decimal_places)
        self.spin_dec.setFixedSize(26, 20)
        self.spin_dec.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #00ff8c; border: 1px solid #00ff8c; font-size: 10px; border-radius: 2px;")
        self.spin_dec.valueChanged.connect(self._on_dec_changed)

        self.btn_log = QPushButton("📜 日志")
        self.btn_log.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: rgba(0,255,140,0.2); }")
        self.btn_log.clicked.connect(self._show_log_dialog)

        row4_layout.addWidget(self.btn_mute)
        row4_layout.addSpacing(4)
        row4_layout.addWidget(self.lbl_dec)
        row4_layout.addWidget(self.spin_dec)
        row4_layout.addSpacing(4)
        row4_layout.addWidget(self.btn_log)
        row4_layout.addStretch()
        panel_layout.addWidget(self.row4_container)

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _show_log_dialog(self):
        self.log_dialog.setWindowTitle(f"📜 识别日志 - {self.name}")
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    def _on_lower_changed(self, val):
        self.lower = val

    def _on_mid_changed(self, val):
        self.mid_val = val

    def _on_upper_changed(self, val):
        self.upper = val

    def _on_dec_changed(self, val):
        self.decimal_places = val

    def _on_title_changed(self, text):
        self.name = text
        self.lbl_title.setText(text)
        self.log_dialog.setWindowTitle(f"📜 识别日志 - {text}")

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            dp = getattr(self, 'decimal_places', 2)
            self.lbl_result.setText(f"{val:.{dp}f}")
            if val > self.upper or val < self.lower:
                self.lbl_result.setStyleSheet("color: #ff4d4d; font-size: 11px; font-weight: bold; margin-left: 2px;")
            elif val > self.mid_val:
                self.lbl_result.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold; margin-left: 2px;")
            else:
                self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold; margin-left: 2px;")
        else:
            disp = f"({raw_text})" if raw_text else "--"
            self.lbl_result.setText(f"{disp}")
            self.lbl_result.setStyleSheet("color: #ff6666; font-size: 11px; font-weight: bold; margin-left: 2px;")

    def add_log_val(self, time_str, val, raw_text=""):
        now_ts = time.time()
        if self.last_log_time == 0.0 or (now_ts - self.last_log_time >= self.log_interval_min * 60.0):
            self.last_log_time = now_ts
            dp = getattr(self, 'decimal_places', 2)
            msg = f"[{time_str}] {val:.{dp}f}" if val is not None else f"[{time_str}] ❌未检测到"
            self.list_widget.insertItem(0, msg)
            while self.list_widget.count() > self.max_log_count:
                self.list_widget.takeItem(self.max_log_count)

    def set_max_log_count(self, count):
        self.max_log_count = count
        while self.list_widget.count() > self.max_log_count:
            self.list_widget.takeItem(self.list_widget.count() - 1)

    def set_panel_hidden(self, hidden):
        self.panel_hidden = hidden
        self._update_bar_visibility()
        self._update_geometry()

    def _update_bar_visibility(self):
        if self.panel_hidden:
            if self.is_alarm:
                self.control_panel.setVisible(True)
                self.control_panel.setStyleSheet("background-color: transparent; border: none;")
                self.row1_container.setVisible(False)
                self.row2_container.setVisible(False)
                self.row3_container.setVisible(True)
                self.row4_container.setVisible(False)
                self.lbl_mid.setVisible(False)
                self.spin_mid.setVisible(False)
                self.btn_clear_alarm.setVisible(True)
            else:
                self.control_panel.setVisible(False)
        else:
            self.control_panel.setVisible(True)
            self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.8); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
            self.row1_container.setVisible(True)
            self.row2_container.setVisible(True)
            self.row3_container.setVisible(True)
            self.row4_container.setVisible(True)

            self.lbl_mid.setVisible(True)
            self.spin_mid.setVisible(True)
            self.btn_mute.setVisible(True)
            self.btn_log.setVisible(True)

            self.lbl_dec.setVisible(self.is_editing)
            self.spin_dec.setVisible(self.is_editing)
            self.btn_clear_alarm.setVisible(self.is_alarm)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.spin_mid.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        total_w = max(self.capture_w, 200)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
            panel_h = 102

        self.capture_spacer.setFixedHeight(self.capture_h)
        total_h = self.capture_h + panel_h
        self.setGeometry(self.capture_x, self.capture_y, total_w, total_h)

    def set_edit_mode(self, enabled):
        self.is_editing = enabled
        self._update_bar_visibility()
        self._update_geometry()
        self.update()

    def set_alarm_state(self, is_alarm):
        if self.is_alarm != is_alarm:
            self.is_alarm = is_alarm
            self._update_bar_visibility()
            self._update_geometry()
            self.update()

    def _on_clear_alarm(self):
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
                self.capture_w = max(1, g_pos.x() - self.capture_x)
                self.capture_h = max(1, g_pos.y() - self.capture_y)
            elif self._resize_mode == "R":
                self.capture_w = max(1, g_pos.x() - self.capture_x)
            elif self._resize_mode == "B":
                self.capture_h = max(1, g_pos.y() - self.capture_y)
            elif self._resize_mode == "L":
                diff = self.capture_x - g_pos.x()
                if self.capture_w + diff >= 1:
                    self.capture_x = g_pos.x()
                    self.capture_w += diff
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
            painter.setBrush(QColor(255, 0, 0, 25))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 25))

        painter.drawRect(box_rect.adjusted(1, 1, -1, -1))


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

        self.label = QLabel("🖱 点击左上角确定起点 (也可直接单击抓取坐标)", self)
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
                self.coord_selected.emit(x, y, w, h)
                self.close()

    def mouseMoveEvent(self, event):
        self.end_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()


# ==================== 7. 后台识别线程 ====================
class MonitorThread(QThread):
    value_updated = Signal(object, str, object, str)
    countdown_tick = Signal(float)

    def __init__(self, boxes, interval=1.0, ocr_params=None, scale=1.0, parent=None):
        super().__init__(parent)
        self.boxes = boxes
        self.interval = max(0.1, interval)
        self.ocr_params = ocr_params or {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self.scale = scale
        self.running = True
        self.reader = None

    def set_reader(self, reader):
        self.reader = reader

    def update_params(self, interval=None, ocr_params=None, scale=None):
        if interval is not None:
            self.interval = max(0.1, interval)
        if ocr_params is not None:
            self.ocr_params = ocr_params
        if scale is not None:
            self.scale = scale

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
        scale = self.scale

        with mss.mss() as sct:
            while self.running:
                if not self.reader:
                    self.msleep(200)
                    continue

                start_time = time.time()
                box_list = list(self.boxes)

                for box in box_list:
                    if not self.running: break
                    
                    capture_x = getattr(box, 'capture_x', 0)
                    capture_y = getattr(box, 'capture_y', 0)
                    capture_w = getattr(box, 'capture_w', 0)
                    capture_h = getattr(box, 'capture_h', 0)
                    dp = getattr(box, 'decimal_places', 0)

                    x = int(capture_x * scale)
                    y = int(capture_y * scale)
                    w = int(capture_w * scale)
                    h = int(capture_h * scale)

                    if w <= 0 or h <= 0: continue

                    try:
                        bbox = {"top": y, "left": x, "width": w, "height": h}
                        sct_img = sct.grab(bbox)
                        img_np = np.array(sct_img)

                        if img_np.shape[2] == 4:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                        else:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                        scale_factor = max(1.0, float(self.ocr_params.get('scale', 3.0)))
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

                        clahe_clip = float(self.ocr_params.get('clahe', 2.0))
                        if clahe_clip > 0:
                            clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
                            enhanced = clahe.apply(gray)
                        else:
                            enhanced = gray

                        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
                        
                        block = int(self.ocr_params.get('thresh_block', 11))
                        c_val = int(self.ocr_params.get('thresh_c', 2))
                        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, c_val)
                        ok4, buf4 = cv2.imencode(".png", binary)
                        if ok4: attempts.append(buf4.tobytes())

                        found_val = None
                        last_raw_str = ""

                        for buf in attempts:
                            if not self.running: break
                            raw_text = str(self.reader.classification(buf))
                            if not raw_text: continue
                            last_raw_str = raw_text

                            clean_t = self._clean_digit_text(raw_text).replace(' ', '')
                            clean_t = re.sub(r'(?<=\d)[,::·\'`_\-*\°ae~,;–—.\s、]+(?=\d)', '.', clean_t)

                            if dp > 0:
                                digits = re.sub(r'\D', '', clean_t)
                                if digits:
                                    if len(digits) > dp:
                                        val_str = digits[:-dp] + '.' + digits[-dp:]
                                    else:
                                        val_str = "0." + digits.zfill(dp)
                                    try:
                                        found_val = float(val_str)
                                        break
                                    except ValueError:
                                        pass
                            else:
                                nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)
                                if nums:
                                    try:
                                        found_val = float(nums[0])
                                        break
                                    except ValueError:
                                        pass

                        now_str = datetime.now().strftime("%H:%M:%S")
                        if self.running:
                            self.value_updated.emit(box, now_str, found_val, last_raw_str)

                    except Exception as e:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        if self.running:
                            self.value_updated.emit(box, now_str, None, f"异常:{e}")

                elapsed = time.time() - start_time
                sleep_needed = max(0.05, self.interval - elapsed)
                end_time = time.time() + sleep_needed

                while self.running and time.time() < end_time:
                    rem = max(0.0, end_time - time.time())
                    self.countdown_tick.emit(rem)
                    self.msleep(50)


# ==================== 8. Flask 网页 WEB 交互界面 ====================
MOBILE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📱 中控数据面板</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #121218; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; }
        .container { max-width: 600px; margin: 0 auto; width: 100%; }
        .header { display: flex; flex-direction: column; padding: 10px 14px; background: #1a1a26; border-radius: 10px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); gap: 8px; }
        .header-top-row { display: flex; justify-content: space-between; align-items: center; width: 100%; user-select: none; cursor: pointer; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; display: flex; align-items: center; gap: 6px; }
        .status { font-size: 11px; color: #aaa; font-weight: bold; }
        .header-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; width: 100%; margin-top: 4px; }
        .btn-top { background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: bold; cursor: pointer; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }
        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); }
        .card.alarm { border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); }
        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; }
        .val-text { font-size: 32px; font-weight: bold; color: #00ff8c; font-family: monospace; text-align: center; margin: 8px 0; }
        .val-text.alarm-text { color: #ff4d4d; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-top-row">
                <div class="title">📱 中控数据面板</div>
                <div id="status" class="status">初始化...</div>
            </div>
        </div>
        <div id="cards-container"></div>
    </div>
    <script>
        async function refreshData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                document.getElementById('status').innerText = data.time;
                const container = document.getElementById('cards-container');
                if (!data.boxes || data.boxes.length === 0) {
                    container.innerHTML = '<div style="text-align:center; padding: 40px; color: #666;">未添加监控选框</div>';
                    return;
                }
                container.innerHTML = data.boxes.map(b => `
                    <div class="card ${b.is_alarm ? 'alarm' : ''}">
                        <div class="card-header"><span class="card-title">${b.name}</span></div>
                        <div class="val-text ${b.is_alarm ? 'alarm-text' : ''}">${b.value}</div>
                    </div>
                `).join('');
            } catch(e) {}
        }
        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""

class WebServerThread(QThread):
    action_requested = Signal(str, int, dict)

    def __init__(self, main_panel, host='0.0.0.0', port=5000, parent=None):
        super().__init__(parent)
        self.main_panel = main_panel
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        if not FLASK_AVAILABLE:
            return

        app = Flask(__name__)

        @app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @app.route('/api/data')
        def get_data():
            boxes_data = []
            for b in self.main_panel.boxes:
                logs = []
                for i in range(min(30, b.list_widget.count())):
                    logs.append(b.list_widget.item(i).text())

                boxes_data.append({
                    'id': b.box_id,
                    'name': b.name,
                    'value': b.lbl_result.text(),
                    'lower': b.lower,
                    'mid_val': getattr(b, 'mid_val', 50.0),
                    'upper': b.upper,
                    'decimal_places': getattr(b, 'decimal_places', 2),
                    'is_alarm': b.is_alarm,
                    'is_muted': b.is_muted,
                    'logs': logs
                })

            grille_running = bool(self.main_panel.grille_thread and self.main_panel.grille_thread.isRunning())

            return jsonify({
                'monitoring': self.main_panel.monitoring,
                'grille_running': grille_running,
                'time': datetime.now().strftime("%H:%M:%S"),
                'boxes': boxes_data
            })

        @app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.get_json() or {}
            action = data.get('action')
            box_id = data.get('id')
            payload = data.get('data', {})

            if action:
                self.action_requested.emit(action, box_id if box_id is not None else -1, payload)
                return jsonify({'status': 'ok'})
            return jsonify({'status': 'error', 'message': 'Invalid parameters'}), 400

        from werkzeug.serving import make_server
        try:
            self.server = make_server(self.host, self.port, app, threaded=True)
            self.server.serve_forever()
        except Exception as e:
            print("Web Server Error:", e)

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass


# ==================== 9. 全局控制面板 ====================
class GlobalControlPanel(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.boxes = []
        self.custom_scripts = []
        self.active_script_threads = []

        self.monitoring = False
        self.is_editing = False
        self.is_collapsed = False
        self.boxes_panel_hidden = False
        self.reader = None
        self.config_file = "monitor_config.json"
        self.users_file = "users_config.json"
        
        self.users = self.load_users()
        self.alarm_player = AlarmSoundPlayer()
        self.grille_thread = None
        self.monitor_thread = None
        self.web_thread = None

        self.curr_monitor_cd = 0.0
        self.curr_grille_cd = 0.0

        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self._drag_pos = None

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._on_f12_pressed)
        self.f12_listener.start()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.setMaximumWidth(580)

        self.setStyleSheet("""
            QWidget { border-radius: 6px; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; background: transparent; border: none; }
            QPushButton { 
                background-color: rgba(43, 45, 66, 0.6); 
                color: #ffffff; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                padding: 0px 8px; 
                height: 26px;
                font-size: 11px; 
                font-weight: bold; 
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.8); }
            QPushButton:pressed { background-color: rgba(26, 27, 38, 0.9); }
            QDoubleSpinBox, QSpinBox { 
                background-color: rgba(26, 26, 38, 0.8); 
                color: #00ff8c; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                font-size: 11px; 
                font-weight: bold; 
                padding: 0px 2px;
                height: 26px;
            }
            QCheckBox { color: #00ff8c; font-size: 11px; font-weight: bold; background: transparent; border: none; }
            QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #00ff8c; background: rgba(26, 26, 38, 0.8); }
            QCheckBox::indicator:checked { background: #00ff8c; }
        """)

        # ---------- 第 1 排：识别监控配置栏 ----------
        self.row1_card = QFrame()
        self.row1_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        self.row1_layout = QHBoxLayout(self.row1_card)
        self.row1_layout.setContentsMargins(8, 5, 8, 5)
        self.row1_layout.setSpacing(6)

        self.row1_layout.addWidget(QLabel("⏱ 识别间隔(秒):"))
        self.spin_interval = CleanDoubleSpinBox()
        self.spin_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        self.spin_interval.setFixedSize(42, 26)
        self.spin_interval.setRange(0.1, 10.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.valueChanged.connect(self._on_interval_changed)
        self.row1_layout.addWidget(self.spin_interval)

        self.row1_layout.addWidget(QLabel("📊 记录数:"))
        self.spin_count = QSpinBox()
        self.spin_count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_count.setAlignment(Qt.AlignCenter)
        self.spin_count.setFixedSize(40, 26)
        self.spin_count.setRange(5, 200)
        self.spin_count.setValue(30)
        self.spin_count.valueChanged.connect(self._on_count_changed)
        self.row1_layout.addWidget(self.spin_count)

        self.row1_layout.addWidget(QLabel("📝 记录间隔(分):"))
        self.spin_log_interval = CleanDoubleSpinBox()
        self.spin_log_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_log_interval.setAlignment(Qt.AlignCenter)
        self.spin_log_interval.setFixedSize(42, 26)
        self.spin_log_interval.setRange(0.0, 1440.0)
        self.spin_log_interval.setValue(1.0)
        self.spin_log_interval.setSingleStep(0.5)
        self.spin_log_interval.valueChanged.connect(self._on_log_interval_changed)
        self.row1_layout.addWidget(self.spin_log_interval)

        self.btn_ocr_adjust = QPushButton("⚙️ 识别调整")
        self.btn_ocr_adjust.setFixedHeight(26)
        self.btn_ocr_adjust.clicked.connect(self._open_ocr_adjust_dialog)
        self.row1_layout.addWidget(self.btn_ocr_adjust)

        main_layout.addWidget(self.row1_card)

        # ---------- 第 2 排：核心操作栏 ----------
        self.row2_card = QFrame()
        self.row2_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        row2_layout = QHBoxLayout(self.row2_card)
        row2_layout.setContentsMargins(8, 5, 8, 5)
        row2_layout.setSpacing(6)

        self.btn_monitor = QPushButton("▶ 开始监控")
        self.btn_monitor.setFixedHeight(26)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        row2_layout.addWidget(self.btn_monitor)

        self.btn_grille_start = QPushButton("▶ 开始操作")
        self.btn_grille_start.setFixedHeight(26)
        self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        self.btn_grille_start.clicked.connect(self._toggle_grille)
        row2_layout.addWidget(self.btn_grille_start)

        self.btn_exit = QPushButton("❌ 退出")
        self.btn_exit.setFixedHeight(26)
        self.btn_exit.clicked.connect(self.close_app)
        row2_layout.addWidget(self.btn_exit)

        self.row2_extra_container = QWidget()
        row2_extra_layout = QHBoxLayout(self.row2_extra_container)
        row2_extra_layout.setContentsMargins(0, 0, 0, 0)
        row2_extra_layout.setSpacing(6)

        self.btn_toggle_hide = QPushButton("👁 隐藏")
        self.btn_toggle_hide.setFixedHeight(26)
        self.btn_toggle_hide.setStyleSheet("background-color: rgba(255,255,255,0.12); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")
        self.btn_toggle_hide.clicked.connect(self._toggle_hide_boxes)
        row2_extra_layout.addWidget(self.btn_toggle_hide)

        self.btn_edit = QPushButton("⚙️ 调整窗口")
        self.btn_edit.setFixedSize(90, 26)
        self.btn_edit.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.12); color: #ffffff; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 4px; font-size: 11px; font-weight: bold; } QPushButton:hover { background-color: rgba(61, 64, 91, 0.8); }")
        self.btn_edit.clicked.connect(self._toggle_edit)
        row2_extra_layout.addWidget(self.btn_edit)

        self.widget_edit_tools = QWidget()
        self.widget_edit_tools.setFixedSize(90, 26)
        edit_tools_layout = QHBoxLayout(self.widget_edit_tools)
        edit_tools_layout.setContentsMargins(0, 0, 0, 0)
        edit_tools_layout.setSpacing(4)

        self.btn_finish = QPushButton("✅ 完成")
        self.btn_finish.setFixedSize(60, 26)
        self.btn_finish.setStyleSheet("QPushButton { background-color: #e6b84d; color: black; border-radius: 4px; padding: 0px 4px; font-size: 11px; font-weight: bold; }")
        self.btn_finish.clicked.connect(self._toggle_edit)

        self.btn_add = QPushButton("➕")
        self.btn_add.setFixedSize(26, 26)
        self.btn_add.setStyleSheet("QPushButton { background-color: #00a86b; color: white; border-radius: 4px; padding: 0px 0px; font-size: 11px; font-weight: bold; }")
        self.btn_add.clicked.connect(self._add_box_picker)

        edit_tools_layout.addWidget(self.btn_finish)
        edit_tools_layout.addWidget(self.btn_add)
        self.widget_edit_tools.setVisible(False)

        row2_extra_layout.addWidget(self.widget_edit_tools)
        row2_layout.addWidget(self.row2_extra_container)

        self.spacer_widget = QWidget()
        self.spacer_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2_layout.addWidget(self.spacer_widget)

        self.btn_collapse = QPushButton("◀")
        self.btn_collapse.setFixedSize(26, 26)
        self.btn_collapse.clicked.connect(self._toggle_collapse)
        row2_layout.addWidget(self.btn_collapse)

        main_layout.addWidget(self.row2_card)

        # ---------- 第 3 排：Web 服务扩展与细格栅 ----------
        self.grille_card = QFrame()
        self.grille_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        row3_layout = QHBoxLayout(self.grille_card)
        row3_layout.setContentsMargins(8, 5, 8, 5)
        row3_layout.setSpacing(6)

        self.chk_grille = QCheckBox("细格栅")
        row3_layout.addWidget(self.chk_grille)

        row3_layout.addWidget(QLabel("执行间隔(分):"))
        self.spin_grille_interval = CleanDoubleSpinBox()
        self.spin_grille_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_grille_interval.setAlignment(Qt.AlignCenter)
        self.spin_grille_interval.setFixedSize(48, 24)
        self.spin_grille_interval.setRange(0.1, 1440.0)
        self.spin_grille_interval.setValue(2.0)
        self.spin_grille_interval.setSingleStep(0.5)
        self.spin_grille_interval.valueChanged.connect(self._on_grille_interval_changed)
        row3_layout.addWidget(self.spin_grille_interval)

        self.lbl_grille_countdown = QLabel("⏳ --")
        self.lbl_grille_countdown.setStyleSheet("color: #ffcc00; font-weight: bold; padding-left: 4px;")
        row3_layout.addWidget(self.lbl_grille_countdown)

        row3_layout.addSpacing(10)

        # 网页服务复选框（已移除右侧所有地址显示）
        self.chk_web = QCheckBox("🌐 网页服务")
        self.chk_web.toggled.connect(self._toggle_web_service)
        row3_layout.addWidget(self.chk_web)

        row3_layout.addStretch()
        main_layout.addWidget(self.grille_card)

        self.load_config()

    def load_users(self):
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception: pass
        return {"admin": "123456"}

    def save_users(self):
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception: pass

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.spin_interval.setValue(data.get("interval", 1.0))
            self.spin_count.setValue(data.get("max_log_count", 30))
            self.spin_log_interval.setValue(data.get("log_interval_min", 1.0))
            self.spin_grille_interval.setValue(data.get("grille_interval", 2.0))
            self.chk_grille.setChecked(data.get("grille_enabled", False))
            self.chk_web.setChecked(data.get("web_enabled", False))
            self.ocr_params = data.get("ocr_params", self.ocr_params)

            for b_data in data.get("boxes", []):
                box = OverlayRegionWidget(
                    b_data["id"], b_data["x"], b_data["y"], b_data["w"], b_data["h"],
                    name=b_data.get("name", "区域"),
                    lower=b_data.get("lower", 0.0),
                    mid_val=b_data.get("mid_val", 50.0),
                    upper=b_data.get("upper", 100.0),
                    decimal_places=b_data.get("decimal_places", 0)
                )
                box.delete_requested.connect(self._remove_box)
                box.alarm_cleared.connect(self._check_global_alarm)
                box.mute_toggled.connect(self._check_global_alarm)
                box.show()
                self.boxes.append(box)
        except Exception as e:
            print("加载配置错误:", e)

    def save_config(self):
        boxes_data = []
        for b in self.boxes:
            boxes_data.append({
                "id": b.box_id, "x": b.capture_x, "y": b.capture_y, "w": b.capture_w, "h": b.capture_h,
                "name": b.name, "lower": b.lower, "mid_val": b.mid_val, "upper": b.upper,
                "decimal_places": b.decimal_places
            })
        data = {
            "interval": self.spin_interval.value(),
            "max_log_count": self.spin_count.value(),
            "log_interval_min": self.spin_log_interval.value(),
            "grille_interval": self.spin_grille_interval.value(),
            "grille_enabled": self.chk_grille.isChecked(),
            "web_enabled": self.chk_web.isChecked(),
            "ocr_params": self.ocr_params,
            "boxes": boxes_data
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存配置错误:", e)

    def _on_f12_pressed(self):
        self._toggle_monitor()

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=val)

    def _on_count_changed(self, val):
        for b in self.boxes:
            b.set_max_log_count(val)

    def _on_log_interval_changed(self, val):
        for b in self.boxes:
            b.log_interval_min = val

    def _on_grille_interval_changed(self, val):
        if self.grille_thread:
            self.grille_thread.set_interval(val)

    def _toggle_monitor(self):
        if not self.monitoring:
            if not self.boxes:
                QMessageBox.warning(self, "提示", "请先添加识别选框！")
                return
            self.monitoring = True
            self.btn_monitor.setText("⏹ 停止监控")
            self.btn_monitor.setStyleSheet("background-color: #cc3333; color: white;")

            if not self.reader:
                try:
                    import ddddocr
                    self.reader = ddddocr.DdddOcr(show_ad=False)
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"初始化 ddddocr 失败: {e}")
                    self.monitoring = False
                    self.btn_monitor.setText("▶ 开始监控")
                    self.btn_monitor.setStyleSheet("")
                    return

            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(self.boxes, interval=self.spin_interval.value(), ocr_params=self.ocr_params, scale=scale)
            self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.start()
        else:
            self.monitoring = False
            self.btn_monitor.setText("▶ 开始监控")
            self.btn_monitor.setStyleSheet("")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None
            self.alarm_player.stop()

    def _on_value_updated(self, box, time_str, val, raw_text):
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            if val > box.upper or val < box.lower:
                if not box.user_cleared_alarm or box.last_alarm_val != val:
                    box.user_cleared_alarm = False
                    box.last_alarm_val = val
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.last_alarm_val = None
                box.set_alarm_state(False)

        self._check_global_alarm()

    def _check_global_alarm(self):
        any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if any_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def _toggle_grille(self):
        if not self.grille_thread or not self.grille_thread.isRunning():
            self.grille_thread = FineGrilleThread(self.spin_grille_interval.value())
            self.grille_thread.countdown_tick.connect(self._on_grille_tick)
            self.grille_thread.start()
            self.btn_grille_start.setText("⏹ 停止操作")
            self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white;")
        else:
            self.grille_thread.stop()
            self.grille_thread.wait()
            self.grille_thread = None
            self.btn_grille_start.setText("▶ 开始操作")
            self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white;")
            self.lbl_grille_countdown.setText("⏳ --")

    def _on_grille_tick(self, rem_sec):
        m = int(rem_sec // 60)
        s = int(rem_sec % 60)
        self.lbl_grille_countdown.setText(f"⏳ {m:02d}:{s:02d}")

    def _toggle_web_service(self, checked):
        if checked:
            if not FLASK_AVAILABLE:
                QMessageBox.warning(self, "提示", "未检测到 Flask 依赖，无法启动网页服务！")
                self.chk_web.setChecked(False)
                return
            if not self.web_thread:
                self.web_thread = WebServerThread(self)
                self.web_thread.action_requested.connect(self._handle_web_action)
                self.web_thread.start()
        else:
            if self.web_thread:
                self.web_thread.stop()
                self.web_thread = None

    def _handle_web_action(self, action, box_id, payload):
        if action == "toggle_monitor":
            self._toggle_monitor()
        elif action == "toggle_grille":
            self._toggle_grille()
        elif action == "clear_alarm":
            for b in self.boxes:
                if b.box_id == box_id:
                    b._on_clear_alarm()
        elif action == "toggle_mute":
            for b in self.boxes:
                if b.box_id == box_id:
                    b._toggle_mute()
        elif action == "set_limits":
            for b in self.boxes:
                if b.box_id == box_id:
                    if 'lower' in payload: b.spin_lower.setValue(float(payload['lower']))
                    if 'mid_val' in payload: b.spin_mid.setValue(float(payload['mid_val']))
                    if 'upper' in payload: b.spin_upper.setValue(float(payload['upper']))

    def _toggle_edit(self):
        self.is_editing = not self.is_editing
        self.btn_edit.setVisible(not self.is_editing)
        self.widget_edit_tools.setVisible(self.is_editing)
        for b in self.boxes:
            b.set_edit_mode(self.is_editing)

    def _add_box_picker(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0: return
            b_id = int(time.time() * 1000) % 1000000
            box = OverlayRegionWidget(
                b_id, x, y, w, h,
                name=f"区域{len(self.boxes)+1}",
                lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0
            )
            box.delete_requested.connect(self._remove_box)
            box.alarm_cleared.connect(self._check_global_alarm)
            box.mute_toggled.connect(self._check_global_alarm)
            box.set_edit_mode(self.is_editing)
            box.set_panel_hidden(self.boxes_panel_hidden)
            box.show()
            self.boxes.append(box)

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _remove_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self._check_global_alarm()

    def _toggle_hide_boxes(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        self.btn_toggle_hide.setText("👁 显示" if self.boxes_panel_hidden else "👁 隐藏")
        for b in self.boxes:
            b.set_panel_hidden(self.boxes_panel_hidden)

    def _toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        self.btn_collapse.setText("▶" if self.is_collapsed else "◀")
        self.row1_card.setVisible(not self.is_collapsed)
        self.grille_card.setVisible(not self.is_collapsed)
        self.row2_extra_container.setVisible(not self.is_collapsed)
        self.adjustSize()

    def _open_ocr_adjust_dialog(self):
        if not self.reader:
            try:
                import ddddocr
                self.reader = ddddocr.DdddOcr(show_ad=False)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"初始化 ddddocr 失败: {e}")
                return

        dlg = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def close_app(self):
        self.save_config()
        self.save_users()
        if self.f12_listener: self.f12_listener.stop()
        if self.monitor_thread: self.monitor_thread.stop()
        if self.grille_thread: self.grille_thread.stop()
        if self.web_thread: self.web_thread.stop()
        self.alarm_player.stop()

        for b in self.boxes:
            b.close()
        self.close()
        QApplication.quit()


# ==================== 主入口程序 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    panel = GlobalControlPanel()
    panel.show()
    panel.move(100, 100)
    sys.exit(app.exec())
