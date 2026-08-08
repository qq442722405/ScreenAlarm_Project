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
    QDialog, QFormLayout, QDialogButtonBox, QTextEdit
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

try:
    import ddddocr
    DDDDOCR_AVAILABLE = True
except ImportError:
    DDDDOCR_AVAILABLE = False


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
        self.log_visible = False

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._drag_pos = QPoint()
        self._resize_mode = None

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

        # 排版第 1 排：标题与当前值
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
        self.lbl_result.setMaximumWidth(45)
        self.lbl_result.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: bold; margin-left: 2px;")

        row1_layout.addWidget(self.lbl_title)
        row1_layout.addWidget(self.edit_title)
        row1_layout.addWidget(self.lbl_result)
        row1_layout.addStretch()
        panel_layout.addWidget(self.row1_container)

        # 排版第 2 排：下限、上限、删除按钮
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
        self.spin_lower.setFixedSize(36, 20)
        self.spin_lower.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_lower.valueChanged.connect(self._on_lower_changed)

        self.lbl_upper = QLabel("上限:")
        self.lbl_upper.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_upper = CleanDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setAlignment(Qt.AlignCenter)
        self.spin_upper.setRange(-99999.0, 99999.0)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedSize(36, 20)
        self.spin_upper.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_upper.valueChanged.connect(self._on_upper_changed)

        self.btn_delete = QPushButton("❌")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 10px; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))

        row2_layout.addWidget(self.lbl_lower)
        row2_layout.addWidget(self.spin_lower)
        row2_layout.addWidget(self.lbl_upper)
        row2_layout.addWidget(self.spin_upper)
        row2_layout.addStretch()
        row2_layout.addWidget(self.btn_delete)
        panel_layout.addWidget(self.row2_container)

        # 排版第 3 排：预警值
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
        self.spin_mid.setFixedSize(36, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addStretch()
        panel_layout.addWidget(self.row3_container)

        # 排版第 4 排：静音、小数点、消除报警、日志按钮
        self.row4_container = QWidget()
        row4_layout = QHBoxLayout(self.row4_container)
        row4_layout.setContentsMargins(0, 0, 0, 0)
        row4_layout.setSpacing(4)

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

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        self.btn_log = QPushButton("📜 日志")
        self.btn_log.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; padding: 2px 6px; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_log.clicked.connect(self._toggle_log)

        row4_layout.addWidget(self.btn_mute)
        row4_layout.addWidget(self.lbl_dec)
        row4_layout.addWidget(self.spin_dec)
        row4_layout.addWidget(self.btn_clear_alarm)
        row4_layout.addWidget(self.btn_log)
        row4_layout.addStretch()
        panel_layout.addWidget(self.row4_container)

        # 日志容器
        self.log_container = QWidget()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(0, 3, 0, 0)
        log_layout.setSpacing(0)

        self.list_widget = QListWidget()
        self.list_widget.setFixedHeight(100)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: rgba(10, 10, 15, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10px;
            }
            QListWidget::item {
                padding: 1px 3px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
        """)
        # 【修改项 2】日志点击后再弹出新窗口显示
        self.list_widget.itemClicked.connect(self._show_log_detail_dialog)

        log_layout.addWidget(self.list_widget)
        self.log_container.setVisible(False)
        panel_layout.addWidget(self.log_container)

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    # 【修改项 2】识别框日志项被点击后弹窗呈现详情
    def _show_log_detail_dialog(self, item):
        log_text = item.text()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📜 日志详情 - {self.name}")
        dialog.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        dialog.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #00ff8c; font-size: 12px; font-weight: bold; }
            QTextEdit {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 13px;
                padding: 6px;
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
        layout = QVBoxLayout(dialog)
        lbl = QLabel("📍 选中日志记录详情:")
        layout.addWidget(lbl)
        
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(log_text)
        layout.addWidget(txt)
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)
        
        dialog.resize(340, 180)
        dialog.exec()

    def _toggle_log(self):
        self.log_visible = not getattr(self, 'log_visible', False)
        self.log_container.setVisible(self.log_visible)
        btn_style = "QPushButton { background-color: #0088cc; color: white; border: none; border-radius: 3px; font-size: 10px; padding: 2px 6px; font-weight: bold; }" if self.log_visible else "QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; padding: 2px 6px; }"
        self.btn_log.setStyleSheet(btn_style)
        self._update_geometry()

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

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            self.lbl_result.setText(f"{val:.2f}")
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
            msg = f"[{time_str}] {val:.2f}" if val is not None else f"[{time_str}] ❌未检测到"
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
                self.row3_container.setVisible(False)
                self.row4_container.setVisible(True)
                self.log_container.setVisible(False)
                self.btn_mute.setVisible(False)
                self.lbl_dec.setVisible(False)
                self.spin_dec.setVisible(False)
                self.btn_log.setVisible(False)
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
            self.log_container.setVisible(getattr(self, 'log_visible', False))

            self.btn_mute.setVisible(True)
            self.lbl_dec.setVisible(self.is_editing)
            self.spin_dec.setVisible(self.is_editing)
            self.btn_clear_alarm.setVisible(self.is_alarm)
            self.btn_log.setVisible(True)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.spin_mid.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        total_w = max(self.capture_w, 210)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
            base_h = 98
            log_h = 103 if (hasattr(self, 'log_container') and self.log_container.isVisible()) else 0
            panel_h = base_h + log_h

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
            painter.setBrush(QColor(0, 255, 140, 15))

        painter.drawRect(box_rect)


# ==================== 6. 鼠标框选工具 ====================
class CoordinatePicker(QWidget):
    coord_selected = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self.start_pos = None
        self.end_pos = None
        self.is_selecting = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.position().toPoint()
            self.end_pos = self.start_pos
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.position().toPoint()

            x1, y1 = self.start_pos.x(), self.start_pos.y()
            x2, y2 = self.end_pos.x(), self.end_pos.y()

            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x1 - x2), abs(y1 - y2)

            self.coord_selected.emit(rx, ry, rw, rh)
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        if self.start_pos and self.end_pos:
            x1, y1 = self.start_pos.x(), self.start_pos.y()
            x2, y2 = self.end_pos.x(), self.end_pos.y()
            rect = QRect(min(x1, x2), min(y1, y2), abs(x1 - x2), abs(y1 - y2))

            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)

            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(0, 255, 140), 2, Qt.SolidLine))
            painter.drawRect(rect)

            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawText(rect.x() + 5, rect.y() + 18, f"{rect.width()} x {rect.height()}")


# ==================== 7. OCR 后台检测线程 ====================
class MonitorThread(QThread):
    batch_result_signal = Signal(dict)

    # 【修改项 1】识别间隔默认 10 秒
    def __init__(self, boxes, interval=10.0, ocr_params=None, scale=1.0, parent=None):
        super().__init__(parent)
        self.boxes = boxes
        self.interval = max(0.1, interval)
        self.scale = scale
        self.running = True

        self.ocr_params = {
            'scale': 3.0,
            'clahe': 2.0,
            'thresh_block': 11,
            'thresh_c': 2
        }
        if ocr_params:
            self.ocr_params.update(ocr_params)

        self.ocr_reader = None
        if DDDDOCR_AVAILABLE:
            try:
                self.ocr_reader = ddddocr.DdddOcr(show_ad=False)
            except: pass

    def set_interval(self, sec):
        self.interval = max(0.1, sec)

    def update_params(self, params):
        self.ocr_params.update(params)

    def stop(self):
        self.running = False

    def _preprocess_crop(self, img_bgr):
        scale_factor = max(1.0, float(self.ocr_params.get('scale', 3.0)))
        h, w = img_bgr.shape[:2]
        new_w, new_h = max(1, int(w * scale_factor)), max(1, int(h * scale_factor))

        scaled = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)

        clahe_clip = float(self.ocr_params.get('clahe', 2.0))
        if clahe_clip > 0:
            clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
        else:
            enhanced = gray

        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))

        block = int(self.ocr_params.get('thresh_block', 11))
        if block % 2 == 0:
            block += 1
        c_val = int(self.ocr_params.get('thresh_c', 2))

        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, c_val)
        return binary

    def run(self):
        with mss.mss() as sct:
            while self.running:
                start_t = time.time()
                results = {}

                for box in list(self.boxes):
                    if not self.running: break
                    rx = int(box.capture_x * self.scale)
                    ry = int(box.capture_y * self.scale)
                    rw = int(box.capture_w * self.scale)
                    rh = int(box.capture_h * self.scale)

                    if rw <= 0 or rh <= 0: continue

                    try:
                        sct_img = sct.grab({"top": ry, "left": rx, "width": rw, "height": rh})
                        img_np = np.array(sct_img)

                        if img_np.shape[2] == 4:
                            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                        else:
                            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                        binary_img = self._preprocess_crop(img_bgr)
                        val, raw_text = None, ""

                        if self.ocr_reader:
                            ok, buf = cv2.imencode(".png", binary_img)
                            if ok:
                                raw_text = str(self.ocr_reader.classification(buf.tobytes()))
                                text_clean = raw_text.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')

                                match = re.search(r'[-+]?\d*\.?\d+', text_clean)
                                if match:
                                    try:
                                        val = float(match.group())
                                        if box.decimal_places > 0:
                                            val = round(val, box.decimal_places)
                                    except: pass

                        results[box.box_id] = (val, raw_text)
                    except:
                        results[box.box_id] = (None, "抓取错误")

                self.batch_result_signal.emit(results)

                elapsed = time.time() - start_t
                wait_t = max(0.05, self.interval - elapsed)
                steps = int(wait_t / 0.05)
                for _ in range(steps):
                    if not self.running: break
                    self.msleep(50)


# ==================== 8. 网页端 手机触控 HTML 模板 ====================
# 【修改项 3】删除网页端收起展开，删除时间显示
MOBILE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>📱 网页中控终端</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; -webkit-user-select: none; }
        body { background-color: #0d0e15; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 8px; font-size: 13px; }

        .header { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; background: rgba(255,255,255,0.05); border-radius: 8px; margin-bottom: 8px; border: 1px solid rgba(255,255,255,0.1); }
        .header-title-box { display: flex; align-items: center; gap: 6px; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; }
        .header-actions { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }

        .btn-top { border: none; border-radius: 4px; padding: 5px 8px; font-size: 11px; font-weight: bold; color: white; cursor: pointer; background: #0088cc; }
        .btn-grille { background: #6c5ce7; }
        .btn-sound { background: #00b894; }
        .btn-sound.muted { background: #d63031; }

        .btn-fold-tool { font-size: 11px; padding: 3px 6px; border-radius: 4px; cursor: pointer; font-weight: bold; }

        /* 卡片常规列表 (长条模式) */
        .cards-list { display: flex; flex-direction: column; gap: 6px; }
        .card { background: rgba(26, 26, 38, 0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px; transition: all 0.2s; }
        .card.alarm { border-color: #ff4d4d; background: rgba(255, 77, 77, 0.15); }
        .card.warning { border-color: #ffaa00; background: rgba(255, 170, 0, 0.15); }

        .card-header { display: flex; justify-content: space-between; align-items: center; }
        .card-title-box { display: flex; align-items: center; gap: 6px; }
        .card-title { font-size: 14px; font-weight: bold; color: #00ff8c; }

        .value-box { display: flex; align-items: baseline; justify-content: flex-end; gap: 6px; margin: 4px 0; }
        .val-text { font-size: 24px; font-weight: bold; color: #00ff8c; font-family: Consolas, monospace; }
        .alarm-text { color: #ff4d4d; }
        .warning-text { color: #ffaa00; }

        .diff-text { font-size: 11px; font-weight: bold; padding: 2px 4px; border-radius: 3px; font-family: Consolas, monospace; }
        .diff-up { color: #ff4d4d; background: rgba(255,77,77,0.15); }
        .diff-down { color: #00ff8c; background: rgba(0,255,140,0.15); }
        .diff-equal { color: #888; background: rgba(255,255,255,0.05); }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-top: 4px; background: rgba(0,0,0,0.2); padding: 4px; border-radius: 4px; }
        .setting-row label { font-size: 10px; color: #ffaa00; }
        .setting-input { width: 42px; background: rgba(26, 26, 38, 0.8); border: 1px solid rgba(255,255,255,0.2); border-radius: 3px; color: #00ff8c; text-align: center; font-size: 11px; padding: 2px; }

        .btn-action { border: none; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; }
        .btn-clear { background: #ff4d4d; color: white; }
        .btn-alarm-on { background: rgba(255,255,255,0.15); color: white; }
        .btn-alarm-off { background: #e65100; color: white; }

        .log-title { font-size: 10px; color: #888; margin-top: 4px; }
        .log-list { background: rgba(10,10,15,0.5); border-radius: 4px; padding: 4px; max-height: 50px; overflow-y: auto; font-family: Consolas, monospace; font-size: 10px; color: #00ff8c; border: 1px solid rgba(255,255,255,0.05); margin-top: 2px; }
        .log-item { padding: 1px 0; border-bottom: 1px dashed rgba(255,255,255,0.05); }

        /* 正方形大网格模式 */
        .cards-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
        .square-card { aspect-ratio: 1 / 1; display: flex; flex-direction: column; justify-content: space-between; padding: 8px; border-radius: 8px; background: rgba(26, 26, 38, 0.9); border: 1px solid rgba(255,255,255,0.15); text-align: center; }
        .sq-row1 { font-size: 13px; font-weight: bold; color: #00ff8c; }
        .sq-row2 { font-size: 26px; font-weight: bold; color: #00ff8c; font-family: Consolas, monospace; }
        .sq-row3 { font-size: 11px; font-weight: bold; }

        /* 模态框统一样式 */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); justify-content: center; align-items: center; z-index: 1000; }
        .modal-content { background: #1a1a26; padding: 15px; border-radius: 8px; width: 85%; max-width: 320px; border: 1px solid rgba(255,255,255,0.2); }
        .modal-title { font-size: 14px; font-weight: bold; color: #00ff8c; margin-bottom: 10px; text-align: center; }
        .modal-form { display: flex; flex-direction: column; gap: 8px; }
        .modal-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: white; padding: 6px; font-size: 12px; }
        .modal-btns { display: flex; justify-content: flex-end; gap: 6px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-title-box">
            <div class="title">📱 中控数据面板</div>
        </div>
        <div class="header-actions">
            <div style="display: flex; align-items: center; gap: 4px; font-size: 11px; color: #aaa; background: rgba(255,255,255,0.05); padding: 2px 4px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.1);">
                <span>对比:</span>
                <input type="number" id="compare-mins" value="5" min="1" style="width: 32px; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 3px; color: #00ff8c; font-weight: bold; text-align: center; padding: 1px;" onchange="refreshData()">
                <span>分</span>
            </div>
            <button id="btn-mode-toggle" class="btn-top" style="background: #6c5ce7;" onclick="toggleDisplayMode()">📱 长条模式</button>

            <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
            </div>
            <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                <span id="current-username" style="color:#00ff8c; font-size:11px; font-weight:bold;">👤 已登录</span>
                <button class="btn-fold-tool" style="background:#e65100; color:white; border:none;" onclick="openUserMgmtModal()">⚙️ 用户管理</button>
                <button class="btn-fold-tool" style="background:#555; color:white; border:none;" onclick="handleLogout()">🚪 退出</button>
            </div>

            <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 网页声音</button>
            <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
            <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
        </div>
    </div>

    <!-- 卡片区域 -->
    <div id="cards-container" class="cards-list"></div>

    <!-- 登录模态框 -->
    <div id="login-modal" class="modal">
        <div class="modal-content">
            <div class="modal-title">🔐 用户登录</div>
            <div class="modal-form">
                <input type="text" id="login-user" class="modal-input" placeholder="账号">
                <input type="password" id="login-pass" class="modal-input" placeholder="密码">
            </div>
            <div class="modal-btns">
                <button class="btn-action" style="background:#555; color:white;" onclick="closeModal('login-modal')">取消</button>
                <button class="btn-action" style="background:#0088cc; color:white;" onclick="handleLogin()">登录</button>
            </div>
        </div>
    </div>

    <!-- 用户管理模态框 -->
    <div id="user-mgmt-modal" class="modal">
        <div class="modal-content">
            <div class="modal-title">⚙️ 用户管理</div>
            <div style="margin-bottom:10px;">
                <div style="font-size:11px; color:#aaa; margin-bottom:4px;">修改密码:</div>
                <div class="modal-form">
                    <input type="password" id="old-pass" class="modal-input" placeholder="旧密码">
                    <input type="password" id="new-pass" class="modal-input" placeholder="新密码">
                    <button class="btn-action" style="background:#0088cc; color:white; width:100%;" onclick="handleChangePassword()">确认修改</button>
                </div>
            </div>
            <div id="admin-add-user-box" style="display:none; border-top:1px solid rgba(255,255,255,0.1); padding-top:10px;">
                <div style="font-size:11px; color:#aaa; margin-bottom:4px;">添加新账号:</div>
                <div class="modal-form">
                    <input type="text" id="new-user-name" class="modal-input" placeholder="新账号">
                    <input type="password" id="new-user-pass" class="modal-input" placeholder="新密码">
                    <button class="btn-action" style="background:#00b894; color:white; width:100%;" onclick="handleAddUser()">添加用户</button>
                </div>
            </div>
            <div class="modal-btns">
                <button class="btn-action" style="background:#555; color:white;" onclick="closeModal('user-mgmt-modal')">关闭</button>
            </div>
        </div>
    </div>

    <script>
        let isAudioAllowed = False;
        let webSoundMuted = False;
        let audioCtx = null;

        let displayMode = 'list'; // 'list' 或 'square'
        let historyData = {}; // 存储历史数值，用于比对 { boxId: [{ time: ts, val: num }] }

        let isLoggedIn = False;
        let currentUser = "";

        function initAudio() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
            isAudioAllowed = true;
        }

        function playWebBeep() {
            if (!isAudioAllowed || webSoundMuted) return;
            try {
                initAudio();
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, audioCtx.currentTime);
                gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + 0.15);
            } catch(e){}
        }

        function toggleWebSound() {
            initAudio();
            webSoundMuted = !webSoundMuted;
            const btn = document.getElementById('btn-sound');
            if (webSoundMuted) {
                btn.innerText = '🔇 网页静音';
                btn.className = 'btn-sound muted';
            } else {
                btn.innerText = '🔊 网页声音';
                btn.className = 'btn-sound';
            }
        }

        function toggleDisplayMode() {
            displayMode = (displayMode === 'list') ? 'square' : 'list';
            const btn = document.getElementById('btn-mode-toggle');
            const container = document.getElementById('cards-container');
            if (displayMode === 'square') {
                btn.innerText = '📱 正方形模式';
                container.className = 'cards-grid';
            } else {
                btn.innerText = '📱 长条模式';
                container.className = 'cards-list';
            }
            refreshData();
        }

        function postAction(act, boxId, extraData = {}) {
            fetch('/api/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: act, id: boxId, data: extraData })
            }).then(() => refreshData());
        }

        function saveLimits(boxId) {
            const lower = parseFloat(document.getElementById(`input-lower-${boxId}`).value);
            const mid = parseFloat(document.getElementById(`input-mid-${boxId}`).value);
            const upper = parseFloat(document.getElementById(`input-upper-${boxId}`).value);
            postAction('set_limits', boxId, { lower: lower, mid_val: mid, upper: upper });
        }

        // 记录和比对数据
        function trackHistory(boxId, valStr) {
            const num = parseFloat(valStr);
            if (isNaN(num)) return;
            const now = Date.now();
            if (!historyData[boxId]) historyData[boxId] = [];

            historyData[boxId].push({ time: now, val: num });
            // 清理超过30分钟的数据
            historyData[boxId] = historyData[boxId].filter(d => now - d.time <= 30 * 60 * 1000);
        }

        function getCompareDiff(boxId, currentValStr) {
            const currentNum = parseFloat(currentValStr);
            if (isNaN(currentNum) || !historyData[boxId] || historyData[boxId].length === 0) {
                return { text: '--', cls: 'diff-equal' };
            }

            const mins = parseInt(document.getElementById('compare-mins').value) || 5;
            const targetTime = Date.now() - (mins * 60 * 1000);

            // 寻找最接近 targetTime 的历史数据
            let closest = historyData[boxId][0];
            for (let d of historyData[boxId]) {
                if (Math.abs(d.time - targetTime) < Math.abs(closest.time - targetTime)) {
                    closest = d;
                }
            }

            const diff = currentNum - closest.val;
            if (Math.abs(diff) < 0.001) {
                return { text: '0.0', cls: 'diff-equal' };
            } else if (diff > 0) {
                return { text: `+${diff.toFixed(1)}`, cls: 'diff-up' };
            } else {
                return { text: `${diff.toFixed(1)}`, cls: 'diff-down' };
            }
        }

        function refreshData() {
            fetch('/api/data')
                .then(r => r.json())
                .then(data => {
                    const btnMon = document.getElementById('btn-monitor');
                    if (data.monitoring) {
                        btnMon.innerText = '⏸ 停止监控';
                        btnMon.style.background = '#d63031';
                    } else {
                        btnMon.innerText = '▶ 开始监控';
                        btnMon.style.background = '#0088cc';
                    }

                    const btnGri = document.getElementById('btn-grille');
                    if (data.grille_running) {
                        btnGri.innerText = `⏸ 细格栅 (${Math.ceil(data.grille_cd)}s)`;
                        btnGri.style.background = '#d63031';
                    } else {
                        btnGri.innerText = '▶ 开始细格栅';
                        btnGri.style.background = '#6c5ce7';
                    }

                    const container = document.getElementById('cards-container');
                    let hasAlarm = false;

                    data.boxes.forEach(b => {
                        trackHistory(b.id, b.value);

                        let card = document.getElementById(`card-${b.id}`);
                        if (!card) {
                            card = document.createElement('div');
                            card.id = `card-${b.id}`;
                            container.appendChild(card);
                        }

                        const numVal = parseFloat(b.value);
                        let isWarning = (!isNaN(numVal) && numVal > b.mid_val && numVal <= b.upper);

                        if (b.is_alarm) hasAlarm = true;

                        renderCardDOM(card, b, isWarning);
                    });

                    if (hasAlarm) playWebBeep();
                });
        }

        function renderCardDOM(cardEl, b, isWarning) {
            let valColor = '#00ff8c';
            if (b.is_alarm) {
                valColor = '#ff4d4d';
            } else if (isWarning) {
                valColor = '#ffaa00';
            }

            const diff = getCompareDiff(b.id, b.value);

            if (displayMode === 'square') {
                cardEl.className = `card square-card ${b.is_alarm ? 'alarm' : (isWarning ? 'warning' : '')}`;
                cardEl.innerHTML = `
                    <div class="sq-row1">${b.name}</div>
                    <div class="sq-row2" style="color: ${valColor};">${b.value}</div>
                    <div class="sq-row3 diff-text ${diff.cls}">${diff.text}</div>
                `;
                return;
            }

            // 【修改项 3】长条模式渲染：无收起展开，直接全部展示，日志清除时间显示
            let logsHtml = (b.logs && b.logs.length > 0)
                ? b.logs.map(l => {
                    let cleanLog = l.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
                    return `<div class="log-item">${cleanLog}</div>`;
                  }).join('')
                : '<div class="log-item">无历史记录</div>';

            cardEl.className = `card ${b.is_alarm ? 'alarm' : (isWarning ? 'warning' : '')}`;
            cardEl.innerHTML = `
                <div class="card-header">
                    <div class="card-title-box">
                        <span class="card-title">${b.name}</span>
                    </div>
                    <div style="display: flex; gap: 6px; align-items: center;" id="action-btns-${b.id}">
                    </div>
                </div>
                <div class="value-box">
                    <span id="diff-tag-${b.id}" class="diff-text ${diff.cls}">${diff.text}</span>
                    <div class="val-text" id="val-text-${b.id}">${b.value}</div>
                </div>
                <div class="fold-body">
                    <div class="setting-row" id="setting-row-${b.id}">
                        <label>下限:</label>
                        <input id="input-lower-${b.id}" class="setting-input" type="number" step="0.1" value="${b.lower}">
                        <label>预警值:</label>
                        <input id="input-mid-${b.id}" class="setting-input" type="number" step="0.1" value="${b.mid_val}">
                        <label>上限:</label>
                        <input id="input-upper-${b.id}" class="setting-input" type="number" step="0.1" value="${b.upper}">
                        <button class="btn-action" style="background:#0088cc; color:white; margin-left:auto;" onclick="saveLimits(${b.id})">💾 保存</button>
                    </div>
                    <div class="log-title">📜 历史日志:</div>
                    <div class="log-list" id="log-list-${b.id}">${logsHtml}</div>
                </div>
            `;

            const actionBtns = document.getElementById(`action-btns-${b.id}`);
            if (actionBtns) {
                if (isLoggedIn) {
                    actionBtns.innerHTML = `
                        ${b.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${b.id})">🚨 消除报警</button>` : ''}
                        <button class="btn-action ${b.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}" onclick="postAction('toggle_mute', ${b.id})">
                            ${b.is_muted ? '🔕 报警关' : '🔔 报警开'}
                        </button>
                    `;
                } else {
                    actionBtns.innerHTML = '';
                }
            }

            const settingRow = document.getElementById(`setting-row-${b.id}`);
            if (settingRow) {
                settingRow.style.display = isLoggedIn ? 'flex' : 'none';
            }

            const valEl = document.getElementById(`val-text-${b.id}`);
            if (valEl) {
                valEl.innerText = b.value;
                if (b.is_alarm) {
                    valEl.className = 'val-text alarm-text';
                } else if (isWarning) {
                    valEl.className = 'val-text warning-text';
                } else {
                    valEl.className = 'val-text';
                }
            }

            if (isLoggedIn) {
                const lowerInput = document.getElementById(`input-lower-${b.id}`);
                const midInput = document.getElementById(`input-mid-${b.id}`);
                const upperInput = document.getElementById(`input-upper-${b.id}`);

                if (lowerInput && document.activeElement !== lowerInput) lowerInput.value = b.lower;
                if (midInput && document.activeElement !== midInput) midInput.value = b.mid_val;
                if (upperInput && document.activeElement !== upperInput) upperInput.value = b.upper;
            }
        }

        // 模态框逻辑
        function openLoginModal() { document.getElementById('login-modal').style.display = 'flex'; }
        function openUserMgmtModal() {
            document.getElementById('user-mgmt-modal').style.display = 'flex';
            document.getElementById('admin-add-user-box').style.display = (currentUser === 'admin') ? 'block' : 'none';
        }
        function closeModal(id) { document.getElementById(id).style.display = 'none'; }

        function handleLogin() {
            const u = document.getElementById('login-user').value;
            const p = document.getElementById('login-pass').value;
            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: u, password: p })
            }).then(r => r.json()).then(res => {
                if (res.success) {
                    isLoggedIn = true;
                    currentUser = res.username;
                    document.getElementById('login-box').style.display = 'none';
                    document.getElementById('user-box').style.display = 'inline-flex';
                    document.getElementById('current-username').innerText = `👤 ${currentUser}`;
                    closeModal('login-modal');
                    refreshData();
                } else {
                    alert(res.message);
                }
            });
        }

        function handleLogout() {
            isLoggedIn = false;
            currentUser = "";
            document.getElementById('login-box').style.display = 'inline-flex';
            document.getElementById('user-box').style.display = 'none';
            refreshData();
        }

        function handleChangePassword() {
            const oldP = document.getElementById('old-pass').value;
            const newP = document.getElementById('new-pass').value;
            fetch('/api/users/change_password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: currentUser, old_password: oldP, new_password: newP })
            }).then(r => r.json()).then(res => {
                alert(res.message);
                if (res.success) closeModal('user-mgmt-modal');
            });
        }

        function handleAddUser() {
            const u = document.getElementById('new-user-name').value;
            const p = document.getElementById('new-user-pass').value;
            fetch('/api/users/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: u, password: p })
            }).then(r => r.json()).then(res => {
                alert(res.message);
                if (res.success) {
                    document.getElementById('new-user-name').value = '';
                    document.getElementById('new-user-pass').value = '';
                }
            });
        }

        document.body.addEventListener('click', initAudio, { once: true });
        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""


# ==================== 9. Web 服务线程 ====================
class WebServerThread(QThread):
    action_requested = Signal(str, int, dict)

    def __init__(self, main_panel, host='0.0.0.0', port=5000, parent=None):
        super().__init__(parent)
        self.main_panel = main_panel
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self.setup_routes()

    def setup_routes(self):
        app = self.app

        @app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @app.route('/favicon.ico')
        def favicon():
            return "", 204

        @app.route('/api/data')
        def get_data():
            boxes_data = []
            for box in self.main_panel.boxes:
                logs = [box.list_widget.item(i).text() for i in range(box.list_widget.count())]
                val_str = box.lbl_result.text()
                boxes_data.append({
                    'id': box.box_id,
                    'name': box.name,
                    'value': val_str,
                    'is_alarm': box.is_alarm,
                    'is_muted': box.is_muted,
                    'lower': box.lower,
                    'mid_val': box.mid_val,
                    'upper': box.upper,
                    'logs': logs
                })
            return jsonify({
                'monitoring': self.main_panel.is_monitoring,
                'grille_running': self.main_panel.grille_thread.isRunning() if self.main_panel.grille_thread else False,
                'grille_cd': getattr(self.main_panel, 'grille_countdown', 0.0),
                'boxes': boxes_data
            })

        @app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.get_json() or {}
            act = data.get('action')
            box_id = data.get('id', -1)
            extra = data.get('data', {})
            self.action_requested.emit(act, box_id, extra)
            return jsonify({'success': True})

        @app.route('/api/login', methods=['POST'])
        def login():
            data = request.get_json() or {}
            username = data.get('username')
            password = data.get('password')
            users = self.main_panel.users
            if username in users and users[username] == password:
                return jsonify({'success': True, 'username': username})
            return jsonify({'success': False, 'message': '账号或密码错误！'})

        @app.route('/api/users/list')
        def user_list():
            return jsonify({'users': list(self.main_panel.users.keys())})

        @app.route('/api/users/add', methods=['POST'])
        def add_user():
            data = request.get_json() or {}
            u = data.get('username')
            p = data.get('password')
            if not u or not p:
                return jsonify({'success': False, 'message': '账号密码不能为空！'})
            if u in self.main_panel.users:
                return jsonify({'success': False, 'message': '用户已存在！'})
            self.main_panel.users[u] = p
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '用户添加成功！'})

        @app.route('/api/users/delete', methods=['POST'])
        def delete_user():
            data = request.get_json() or {}
            u = data.get('username')
            if u == 'admin':
                return jsonify({'success': False, 'message': '默认管理员不能删除！'})
            if u in self.main_panel.users:
                del self.main_panel.users[u]
                self.main_panel.save_users()
                return jsonify({'success': True, 'message': '用户删除成功！'})
            return jsonify({'success': False, 'message': '用户不存在！'})

        @app.route('/api/users/change_password', methods=['POST'])
        def change_pass():
            data = request.get_json() or {}
            u = data.get('username')
            old_p = data.get('old_password')
            new_p = data.get('new_password')
            if u in self.main_panel.users and self.main_panel.users[u] == old_p:
                self.main_panel.users[u] = new_p
                self.main_panel.save_users()
                return jsonify({'success': True, 'message': '密码修改成功！'})
            return jsonify({'success': False, 'message': '旧密码错误！'})

    def run(self):
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)


# ==================== 10. 主控台 GUI 界面 ====================
class MainPanelWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.boxes = []
        self.next_box_id = 1
        self.is_monitoring = False
        self.is_editing_mode = False
        self.panels_hidden = False

        self.ocr_params = {
            'scale': 3.0,
            'clahe': 2.0,
            'thresh_block': 11,
            'thresh_c': 2
        }

        self.users = {'admin': 'admin888'}
        self.load_users()

        self.sound_player = AlarmSoundPlayer()
        self.monitor_thread = None

        self.grille_thread = FineGrilleThread()
        self.grille_thread.countdown_tick.connect(self._on_grille_tick)
        self.grille_countdown = 0.0

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._toggle_edit_mode)
        self.f12_listener.start()

        self.setWindowTitle("🖥️ 数字识别与监控主控台")
        self.resize(360, 480)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self.setStyleSheet("""
            QWidget { background-color: #1a1a26; color: white; font-family: "Microsoft YaHei", sans-serif; }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 5px;
                padding: 6px 10px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; }
            QDoubleSpinBox, QSpinBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
            }
        """)

        # 头部功能按钮区
        btn_layout = QHBoxLayout()
        self.btn_add_box = QPushButton("➕ 添加识别选框")
        self.btn_add_box.clicked.connect(self._add_new_box)
        self.btn_add_box.setStyleSheet("background-color: #0088cc;")

        self.btn_toggle_monitor = QPushButton("▶ 开始监控")
        self.btn_toggle_monitor.clicked.connect(self._toggle_monitor)
        self.btn_toggle_monitor.setStyleSheet("background-color: #00b894;")

        btn_layout.addWidget(self.btn_add_box)
        btn_layout.addWidget(self.btn_toggle_monitor)
        main_layout.addLayout(btn_layout)

        btn_layout2 = QHBoxLayout()
        self.btn_toggle_grille = QPushButton("▶ 开始细格栅操作")
        self.btn_toggle_grille.clicked.connect(self._toggle_grille)
        self.btn_toggle_grille.setStyleSheet("background-color: #6c5ce7;")

        self.btn_ocr_config = QPushButton("⚙️ OCR 预处理设置")
        self.btn_ocr_config.clicked.connect(self._open_ocr_dialog)

        btn_layout2.addWidget(self.btn_toggle_grille)
        btn_layout2.addWidget(self.btn_ocr_config)
        main_layout.addLayout(btn_layout2)

        # 全局参数设置区
        form = QFormLayout()

        # 【修改项 1】识别间隔默认 10 秒
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 3600.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.setValue(10.0)
        self.spin_interval.valueChanged.connect(self._on_interval_changed)

        self.spin_log_count = QSpinBox()
        self.spin_log_count.setRange(5, 500)
        self.spin_log_count.setValue(30)
        self.spin_log_count.valueChanged.connect(self._on_max_log_count_changed)

        self.spin_grille_interval = QDoubleSpinBox()
        self.spin_grille_interval.setRange(0.1, 1440.0)
        self.spin_grille_interval.setValue(2.0)
        self.spin_grille_interval.setSuffix(" 分钟")
        self.spin_grille_interval.valueChanged.connect(self._on_grille_interval_changed)

        form.addRow("识别间隔 (秒):", self.spin_interval)
        form.addRow("日志最大保留数:", self.spin_log_count)
        form.addRow("细格栅周期:", self.spin_grille_interval)
        main_layout.addLayout(form)

        # 悬浮面板与模式控制
        mode_layout = QHBoxLayout()
        self.btn_toggle_panels = QPushButton("👁️ 隐藏选框控制面板")
        self.btn_toggle_panels.clicked.connect(self._toggle_panel_visibility)

        self.lbl_edit_status = QLabel("快捷键 F12: 锁定模式")
        self.lbl_edit_status.setAlignment(Qt.AlignCenter)
        self.lbl_edit_status.setStyleSheet("color: #ffaa00;")

        mode_layout.addWidget(self.btn_toggle_panels)
        mode_layout.addWidget(self.lbl_edit_status)
        main_layout.addLayout(mode_layout)

        # 局域网 Web 服务展示
        local_ip = get_local_ip()
        self.lbl_web_ip = QLabel(f"🌐 手机网页控制端地址:\nhttp://{local_ip}:5000")
        self.lbl_web_ip.setAlignment(Qt.AlignCenter)
        self.lbl_web_ip.setStyleSheet("color: #00ff8c; background: rgba(0,0,0,0.4); padding: 8px; border-radius: 6px;")
        main_layout.addWidget(self.lbl_web_ip)

        main_layout.addStretch()

        self.load_config()

        if FLASK_AVAILABLE:
            self.web_thread = WebServerThread(self)
            self.web_thread.action_requested.connect(self._handle_web_action)
            self.web_thread.start()

    def _add_new_box(self, x=100, y=100, w=150, h=40, name=None, lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0):
        box_id = self.next_box_id
        self.next_box_id += 1
        box_name = name if name else f"区域{box_id}"

        box = OverlayRegionWidget(box_id, x, y, w, h, box_name, lower, mid_val, upper, decimal_places)
        box.set_max_log_count(self.spin_log_count.value())
        box.set_edit_mode(self.is_editing_mode)
        box.set_panel_hidden(self.panels_hidden)

        box.delete_requested.connect(self._remove_box)
        box.alarm_cleared.connect(self._check_global_alarm_sound)
        box.mute_toggled.connect(self._check_global_alarm_sound)
        box.show()

        self.boxes.append(box)
        return box

    def _remove_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self._check_global_alarm_sound()

    def _toggle_monitor(self):
        if self.is_monitoring:
            self.is_monitoring = False
            self.btn_toggle_monitor.setText("▶ 开始监控")
            self.btn_toggle_monitor.setStyleSheet("background-color: #00b894;")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None
            self.sound_player.stop()
        else:
            self.is_monitoring = True
            self.btn_toggle_monitor.setText("⏸ 停止监控")
            self.btn_toggle_monitor.setStyleSheet("background-color: #d63031;")

            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(self.boxes, self.spin_interval.value(), self.ocr_params, scale)
            self.monitor_thread.batch_result_signal.connect(self._on_ocr_batch_results)
            self.monitor_thread.start()

    def _toggle_grille(self):
        if self.grille_thread.isRunning():
            self.grille_thread.stop()
            self.grille_thread.wait()
            self.btn_toggle_grille.setText("▶ 开始细格栅操作")
            self.btn_toggle_grille.setStyleSheet("background-color: #6c5ce7;")
        else:
            self.grille_thread.set_interval(self.spin_grille_interval.value())
            self.grille_thread.start()
            self.btn_toggle_grille.setText("⏸ 停止细格栅操作")
            self.btn_toggle_grille.setStyleSheet("background-color: #d63031;")

    def _on_grille_tick(self, rem_sec):
        self.grille_countdown = rem_sec

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.set_interval(val)

    def _on_max_log_count_changed(self, val):
        for box in self.boxes:
            box.set_max_log_count(val)

    def _on_grille_interval_changed(self, val):
        if self.grille_thread:
            self.grille_thread.set_interval(val)

    def _toggle_panel_visibility(self):
        self.panels_hidden = not self.panels_hidden
        btn_txt = "👁️ 显示选框控制面板" if self.panels_hidden else "👁️ 隐藏选框控制面板"
        self.btn_toggle_panels.setText(btn_txt)
        for box in self.boxes:
            box.set_panel_hidden(self.panels_hidden)

    def _toggle_edit_mode(self):
        self.is_editing_mode = not self.is_editing_mode
        txt = "快捷键 F12: 编辑模式" if self.is_editing_mode else "快捷键 F12: 锁定模式"
        clr = "#00ff8c" if self.is_editing_mode else "#ffaa00"
        self.lbl_edit_status.setText(txt)
        self.lbl_edit_status.setStyleSheet(f"color: {clr};")
        for box in self.boxes:
            box.set_edit_mode(self.is_editing_mode)

    def _open_ocr_dialog(self):
        reader = self.monitor_thread.ocr_reader if self.monitor_thread else None
        dlg = OCRAdjustDialog(self.ocr_params, reader=reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(self.ocr_params)

    def _on_ocr_batch_results(self, results):
        now_str = datetime.now().strftime("%H:%M:%S")
        any_alarm = False

        for box in list(self.boxes):
            if box.box_id in results:
                val, raw_text = results[box.box_id]
                box.update_result_display(val, raw_text)
                box.add_log_val(now_str, val, raw_text)

                if val is not None:
                    if val > box.upper or val < box.lower:
                        if box.last_alarm_val != val:
                            box.user_cleared_alarm = False
                            box.last_alarm_val = val

                        if not box.user_cleared_alarm:
                            box.set_alarm_state(True)
                            if not box.is_muted:
                                any_alarm = True
                        else:
                            box.set_alarm_state(False)
                    else:
                        box.user_cleared_alarm = False
                        box.last_alarm_val = None
                        box.set_alarm_state(False)

        if any_alarm:
            self.sound_player.play()
        else:
            self.sound_player.stop()

    def _check_global_alarm_sound(self):
        any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if any_alarm:
            self.sound_player.play()
        else:
            self.sound_player.stop()

    def _handle_web_action(self, act, box_id, extra):
        if act == 'toggle_monitor':
            self._toggle_monitor()
        elif这里是根据您的需求修改并补全后的完整 Python 代码文件。

### 修改说明：
1. **识别间隔默认 10 秒**：在控制面板和后台识别线程 `MonitorThread` 中将默认识别间隔统一调整为 `10.0` 秒。
2. **识别框日志弹窗显示**：识别框（悬浮框）上的“📜 日志”按钮点击后不再展开内部视图，而是直接弹出独立的 **新窗口（QDialog）** 显示历史日志及详情，保持识别选框轻量不遮挡界面。
3. **网页端移除收起展开与时间显示/对比**：
   - 彻底删除了网页端的展开/收起（Fold/Collapse）逻辑与按钮，所有卡片均直接完整展示。
   - 删除了网页端顶部的时间对比输入框、差值计算逻辑（`getCompareDiff`）以及时间标签显示。

```python
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
    QDialog, QFormLayout, QDialogButtonBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView
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

try:
    import ddddocr
    DDDDOCR_AVAILABLE = True
except ImportError:
    DDDDOCR_AVAILABLE = False


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


# ==================== 5. 独立日志查看弹窗 【修改项 2】 ====================
class LogWindowDialog(QDialog):
    """【修改项 2】点击日志按钮后弹出的独立新窗口"""
    def __init__(self, title, logs, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📜 日志记录 - {title}")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(320, 240)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #00ff8c; font-size: 12px; font-weight: bold; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QListWidget::item { padding: 4px; border-bottom: 1px solid rgba(255,255,255,0.05); }
            QListWidget::item:hover { background-color: rgba(0, 255, 140, 0.1); }
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
        layout = QVBoxLayout(self)
        lbl = QLabel(f"📍 {title} 历史测量日志:")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        if logs:
            for l in logs:
                self.list_widget.addItem(l)
        else:
            self.list_widget.addItem("暂无日志记录")

        self.list_widget.itemClicked.connect(self._show_detail)
        layout.addWidget(self.list_widget)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)

    def _show_detail(self, item):
        log_text = item.text()
        dialog = QDialog(self)
        dialog.setWindowTitle("📜 日志详情")
        dialog.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        dialog.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #00ff8c; font-size: 12px; font-weight: bold; }
            QTextEdit {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 12px;
                padding: 6px;
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: bold;
            }
        """)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("📍 选中的记录数据:"))

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(log_text)
        layout.addWidget(txt)

        btn = QPushButton("关闭")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)

        dialog.resize(300, 140)
        dialog.exec()


# ==================== 6. 悬浮识别选框窗口 ====================
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
        self.logs_history = []  # 存储日志列表字符串

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

        # 排版第 1 排：标题与当前值
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
        self.lbl_result.setMaximumWidth(45)
        self.lbl_result.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: bold; margin-left: 2px;")

        row1_layout.addWidget(self.lbl_title)
        row1_layout.addWidget(self.edit_title)
        row1_layout.addWidget(self.lbl_result)
        row1_layout.addStretch()
        panel_layout.addWidget(self.row1_container)

        # 排版第 2 排：下限、上限、删除按钮
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
        self.spin_lower.setFixedSize(36, 20)
        self.spin_lower.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_lower.valueChanged.connect(self._on_lower_changed)

        self.lbl_upper = QLabel("上限:")
        self.lbl_upper.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        self.spin_upper = CleanDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setAlignment(Qt.AlignCenter)
        self.spin_upper.setRange(-99999.0, 99999.0)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedSize(36, 20)
        self.spin_upper.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_upper.valueChanged.connect(self._on_upper_changed)

        self.btn_delete = QPushButton("❌")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 10px; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))

        row2_layout.addWidget(self.lbl_lower)
        row2_layout.addWidget(self.spin_lower)
        row2_layout.addWidget(self.lbl_upper)
        row2_layout.addWidget(self.spin_upper)
        row2_layout.addStretch()
        row2_layout.addWidget(self.btn_delete)
        panel_layout.addWidget(self.row2_container)

        # 排版第 3 排：预警值
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
        self.spin_mid.setFixedSize(36, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addStretch()
        panel_layout.addWidget(self.row3_container)

        # 排版第 4 排：静音、小数点、消除报警、日志按钮
        self.row4_container = QWidget()
        row4_layout = QHBoxLayout(self.row4_container)
        row4_layout.setContentsMargins(0, 0, 0, 0)
        row4_layout.setSpacing(4)

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

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        # 【修改项 2】点击日志弹出新窗口
        self.btn_log = QPushButton("📜 日志")
        self.btn_log.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; padding: 2px 6px; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_log.clicked.connect(self._open_log_window)

        row4_layout.addWidget(self.btn_mute)
        row4_layout.addWidget(self.lbl_dec)
        row4_layout.addWidget(self.spin_dec)
        row4_layout.addWidget(self.btn_clear_alarm)
        row4_layout.addWidget(self.btn_log)
        row4_layout.addStretch()
        panel_layout.addWidget(self.row4_container)

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _open_log_window(self):
        """【修改项 2】弹出新窗口显示日志"""
        dlg = LogWindowDialog(self.name, self.logs_history, self)
        dlg.exec()

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

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            self.lbl_result.setText(f"{val:.2f}")
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
            msg = f"[{time_str}] {val:.2f}" if val is not None else f"[{time_str}] ❌未检测到"
            self.logs_history.insert(0, msg)
            if len(self.logs_history) > self.max_log_count:
                self.logs_history = self.logs_history[:self.max_log_count]

    def set_max_log_count(self, count):
        self.max_log_count = count
        if len(self.logs_history) > self.max_log_count:
            self.logs_history = self.logs_history[:self.max_log_count]

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
                self.row3_container.setVisible(False)
                self.row4_container.setVisible(True)
                self.btn_mute.setVisible(False)
                self.lbl_dec.setVisible(False)
                self.spin_dec.setVisible(False)
                self.btn_log.setVisible(False)
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

            self.btn_mute.setVisible(True)
            self.lbl_dec.setVisible(self.is_editing)
            self.spin_dec.setVisible(self.is_editing)
            self.btn_clear_alarm.setVisible(self.is_alarm)
            self.btn_log.setVisible(True)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.spin_mid.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        total_w = max(self.capture_w, 210)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
            panel_h = 98

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


# ==================== 7. 屏幕选区拾取器 ====================
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
                if w > 0 and h > 0:
                    self.coord_selected.emit(x, y, w, h)
                    self.close()

    def mouseMoveEvent(self, event):
        self.end_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()


# ==================== 8. 后台识别线程 ====================
class MonitorThread(QThread):
    value_updated = Signal(object, str, object, str)
    countdown_tick = Signal(float)

    # 【修改项 1】识别间隔默认 10 秒
    def __init__(self, boxes, interval=10.0, ocr_params=None, scale=1.0, parent=None):
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


# ==================== 9. Flask 网页 WEB 交互界面 【修改项 3】 ====================
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

        .header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #1a1a26; border-radius: 10px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); flex-wrap: wrap; gap: 8px; }
        .header-title-box { display: flex; flex-direction: column; gap: 2px; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; display: flex; align-items: center; gap: 6px; }
        .status { font-size: 11px; color: #aaa; font-weight: bold; }

        .header-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .btn-top { background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }

        .btn-fold-tool { background: rgba(255,255,255,0.1); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }

        .login-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 6px; width: 100%; font-size: 12px; }

        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); transition: all 0.3s; }
        
        .card.alarm { border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); animation: blink 1s infinite alternate; }
        @keyframes blink { from { box-shadow: 0 0 5px rgba(255,77,77,0.3); } to { box-shadow: 0 0 15px rgba(255,77,77,0.8); } }

        .card.warning { border: 2px solid #ffaa00; background: rgba(255, 170, 0, 0.08); }

        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .value-box { text-align: center; margin: 8px 0; display: flex; align-items: center; justify-content: center; gap: 10px; }
        .val-text { font-size: 32px; font-weight: bold; color: #00ff8c; font-family: monospace; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .card-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 50px; text-align: center; font-size: 11px; }

        .log-title { margin-top: 6px; font-size: 11px; color: #888; font-weight: bold; }
        .log-list { margin-top: 4px; background: rgba(0,0,0,0.4); border-radius: 6px; padding: 6px 8px; font-size: 11px; font-family: monospace; height: 110px; overflow-y: auto; color: #00ff8c; }

        /* 模态框弹窗样式 */
        .modal-overlay { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }
        .modal-content { background: #1a1a26; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; width: 90%; max-width: 420px; padding: 16px; color: #e0e0e0; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; }
        .modal-close { cursor: pointer; color: #ff4d4d; font-weight: bold; font-size: 16px; }

        /* 布局容器 */
        #cards-container.strip-mode { display: flex; flex-direction: column; gap: 10px; }
        #cards-container.square-mode { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; }

        .square-card { text-align: center; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 14px 8px; }
        .square-card .sq-row1 { font-size: 14px; font-weight: bold; color: #ffffff; margin-bottom: 4px; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .square-card .sq-row2 { font-size: 30px; font-weight: bold; font-family: monospace; color: #00ff8c; margin: 4px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-title-box">
                <div class="title">📱 中控数据面板</div>
                <div id="status" class="status">初始化...</div>
            </div>
            <div class="header-actions">
                <button id="btn-mode-toggle" class="btn-top" style="background: #6c5ce7;" onclick="toggleDisplayMode()">📱 长条模式</button>

                <!-- 登录按钮 -->
                <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                    <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
                </div>
                <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                    <span id="current-username" style="color:#00ff8c; font-size:12px; font-weight:bold;">👤 已登录</span>
                    <button class="btn-fold-tool" style="background:#e65100; color:white; border:none;" onclick="openUserMgmtModal()">⚙️ 用户管理</button>
                    <button class="btn-fold-tool" style="background:#555; color:white; border:none;" onclick="handleLogout()">🚪 退出</button>
                </div>

                <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 网页声音</button>
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div id="cards-container" class="strip-mode"></div>
    </div>

    <!-- 登录界面弹窗 -->
    <div id="login-modal" class="modal-overlay">
        <div class="modal-content" style="max-width: 320px;">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">🔐 用户登录</span>
                <span class="modal-close" onclick="closeLoginModal()">✖</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 8px;">
                <div>
                    <label style="font-size:12px; color:#aaa; font-weight:bold; display:block; margin-bottom:4px;">账号：</label>
                    <input type="text" id="login-user" placeholder="请输入账号" class="login-input" style="height: 32px; padding: 4px 8px;">
                </div>
                <div>
                    <label style="font-size:12px; color:#aaa; font-weight:bold; display:block; margin-bottom:4px;">密码：</label>
                    <input type="password" id="login-pass" placeholder="请输入密码" class="login-input" style="height: 32px; padding: 4px 8px;">
                </div>
                <button class="btn-action" style="background:#0088cc; color:white; height: 34px; margin-top: 6px; font-size: 13px;" onclick="handleLogin()">登录</button>
            </div>
        </div>
    </div>

    <!-- 用户管理模态框 -->
    <div id="user-modal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">⚙️ 用户管理面板</span>
                <span class="modal-close" onclick="closeUserMgmtModal()">✖</span>
            </div>
            
            <div style="margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px dashed rgba(255,255,255,0.1);">
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">🔑 修改密码 (<span id="modal-curr-user" style="color:#00ff8c;"></span>)</div>
                <div class="setting-row">
                    <input type="password" id="old-pass" placeholder="旧密码" class="setting-input" style="width:85px;">
                    <input type="password" id="new-pass" placeholder="新密码" class="setting-input" style="width:85px;">
                    <button class="btn-action" style="background:#0088cc; color:white; margin-left: auto;" onclick="handleChangePassword()">修改密码</button>
                </div>
            </div>

            <div>
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">➕ 新增用户</div>
                <div class="setting-row" style="margin-bottom:10px;">
                    <input type="text" id="new-user-name" placeholder="新账号" class="setting-input" style="width:85px;">
                    <input type="password" id="new-user-pass" placeholder="新密码" class="setting-input" style="width:85px;">
                    <button class="btn-action" style="background:#2e9a58; color:white; margin-left: auto;" onclick="handleAddUser()">添加用户</button>
                </div>

                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">👥 用户账号列表</div>
                <div id="user-list-container" style="max-height: 120px; overflow-y: auto; background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px;">
                </div>
            </div>
        </div>
    </div>

    <script>
        let isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
        let currentUser = localStorage.getItem('currentUser') || '';
        let webSoundEnabled = true;
        let audioCtx = null;
        let alarmTimer = null;
        let displayMode = localStorage.getItem('displayMode') || 'strip'; // 'strip' 或 'square'

        function toggleDisplayMode() {
            displayMode = (displayMode === 'strip') ? 'square' : 'strip';
            localStorage.setItem('displayMode', displayMode);
            updateDisplayModeUI();
            forceReRenderCards();
            refreshData();
        }

        function updateDisplayModeUI() {
            const btn = document.getElementById('btn-mode-toggle');
            const container = document.getElementById('cards-container');
            if (btn) btn.innerText = (displayMode === 'strip') ? '📱 长条模式' : '🔳 正方形模式';
            if (container) container.className = (displayMode === 'square') ? 'square-mode' : 'strip-mode';
        }

        function openLoginModal() { document.getElementById('login-modal').style.display = 'flex'; }
        function closeLoginModal() { document.getElementById('login-modal').style.display = 'none'; }

        function updateLoginUI() {
            const loginBox = document.getElementById('login-box');
            const userBox = document.getElementById('user-box');
            const usernameDisplay = document.getElementById('current-username');
            const btnMonitor = document.getElementById('btn-monitor');
            const btnGrille = document.getElementById('btn-grille');

            if (isLoggedIn) {
                if (loginBox) loginBox.style.display = 'none';
                if (userBox) userBox.style.display = 'inline-flex';
                if (usernameDisplay) usernameDisplay.innerText = `👤 ${currentUser}`;
                if (btnMonitor) btnMonitor.style.display = 'inline-block';
                if (btnGrille) btnGrille.style.display = 'inline-block';
            } else {
                if (loginBox) loginBox.style.display = 'inline-flex';
                if (userBox) userBox.style.display = 'none';
                if (btnMonitor) btnMonitor.style.display = 'none';
                if (btnGrille) btnGrille.style.display = 'none';
            }
        }

        async function handleLogin() {
            const u = document.getElementById('login-user').value.trim();
            const p = document.getElementById('login-pass').value.trim();
            if (!u || !p) { alert('请输入账号和密码！'); return; }
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: u, password: p })
                });
                const data = await res.json();
                if (data.success) {
                    isLoggedIn = true;
                    currentUser = data.username;
                    localStorage.setItem('isLoggedIn', 'true');
                    localStorage.setItem('currentUser', currentUser);
                    closeLoginModal();
                    document.getElementById('login-user').value = '';
                    document.getElementById('login-pass').value = '';
                    updateLoginUI();
                    forceReRenderCards();
                    refreshData();
                } else {
                    alert(data.message || '登录失败！');
                }
            } catch(e) { alert('请求异常！'); }
        }

        function handleLogout() {
            isLoggedIn = false;
            currentUser = '';
            localStorage.setItem('isLoggedIn', 'false');
            localStorage.removeItem('currentUser');
            updateLoginUI();
            forceReRenderCards();
            refreshData();
        }

        function openUserMgmtModal() {
            document.getElementById('user-modal').style.display = 'flex';
            document.getElementById('modal-curr-user').innerText = currentUser;
            loadUserList();
        }
        function closeUserMgmtModal() { document.getElementById('user-modal').style.display = 'none'; }

        async function handleChangePassword() {
            const oldP = document.getElementById('old-pass').value.trim();
            const newP = document.getElementById('new-pass').value.trim();
            if (!oldP || !newP) { alert('请填写旧密码和新密码！'); return; }
            try {
                const res = await fetch('/api/users/change_password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: currentUser, old_password: oldP, new_password: newP })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    document.getElementById('old-pass').value = '';
                    document.getElementById('new-pass').value = '';
                }
            } catch(e) { alert('修改密码异常！'); }
        }

        async function handleAddUser() {
            const u = document.getElementById('new-user-name').value.trim();
            const p = document.getElementById('new-user-pass').value.trim();
            if (!u || !p) { alert('请输入新账号和新密码！'); return; }
            try {
                const res = await fetch('/api/users/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: u, password: p })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    document.getElementById('new-user-name').value = '';
                    document.getElementById('new-user-pass').value = '';
                    loadUserList();
                }
            } catch(e) { alert('添加用户异常！'); }
        }

        async function handleDeleteUser(username) {
            if (!confirm(`确定要删除用户 "${username}" 吗？`)) return;
            try {
                const res = await fetch('/api/users/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) loadUserList();
            } catch(e) { alert('删除用户异常！'); }
        }

        async function loadUserList() {
            try {
                const res = await fetch('/api/users/list');
                const data = await res.json();
                const container = document.getElementById('user-list-container');
                if (data.users && data.users.length > 0) {
                    container.innerHTML = data.users.map(u => `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size:12px;">
                            <span>👤 ${u}</span>
                            ${u !== 'admin' ? `<button class="btn-action" style="background:#ff4d4d; color:white;" onclick="handleDeleteUser('${u}')">删除</button>` : '<span style="color:#888; font-size:11px;">(管理员)</span>'}
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="color:#888; font-size:11px;">暂无用户</div>';
                }
            } catch(e) {}
        }

        function forceReRenderCards() {
            const container = document.getElementById('cards-container');
            if (container) container.innerHTML = '';
        }

        function initAudio() {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (audioCtx.state === 'suspended') audioCtx.resume();
        }
        document.addEventListener('click', initAudio, { once: false });

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            const btn = document.getElementById('btn-sound');
            if (webSoundEnabled) {
                btn.innerText = "🔊 网页声音";
                btn.style.color = "#00ff8c";
            } else {
                btn.innerText = "🔇 网页静音";
                btn.style.color = "#aaa";
                stopWebAlarmSound();
            }
        }

        function triggerAlarmSoundLoop(play) {
            if (play && webSoundEnabled) {
                if (!alarmTimer) {
                    alarmTimer = setInterval(() => {
                        if (!webSoundEnabled) return;
                        try {
                            initAudio();
                            const osc = audioCtx.createOscillator();
                            const gain = audioCtx.createGain();
                            osc.type = 'sawtooth';
                            osc.frequency.setValueAtTime(850, audioCtx.currentTime);
                            gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
                            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.25);
                            osc.connect(gain);
                            gain.connect(audioCtx.destination);
                            osc.start();
                            osc.stop(audioCtx.currentTime + 0.25);
                        } catch(e) {}
                    }, 400);
                }
            } else {
                stopWebAlarmSound();
            }
        }

        function stopWebAlarmSound() {
            if (alarmTimer) {
                clearInterval(alarmTimer);
                alarmTimer = null;
            }
        }

        async function postAction(action, boxId, data = {}) {
            try {
                await fetch('/api/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action, id: boxId, data })
                });
                refreshData();
            } catch(e) { console.error("操作失败:", e); }
        }

        function saveLimits(boxId) {
            const lowerVal = parseFloat(document.getElementById(`input-lower-${boxId}`).value);
            const midVal = parseFloat(document.getElementById(`input-mid-${boxId}`).value);
            const upperVal = parseFloat(document.getElementById(`input-upper-${boxId}`).value);
            if (!isNaN(lowerVal) && !isNaN(midVal) && !isNaN(upperVal)) {
                postAction('set_limits', boxId, { lower: lowerVal, mid_val: midVal, upper: upperVal });
            } else {
                alert("请输入有效的数值！");
            }
        }

        function renderCardDOM(cardEl, b, isWarning) {
            let valColor = '#00ff8c';
            if (b.is_alarm) valColor = '#ff4d4d';
            else if (isWarning) valColor = '#ffaa00';

            // 【修改项 3】正方形模式卡片
            if (displayMode === 'square') {
                cardEl.className = `card square-card ${b.is_alarm ? 'alarm' : (isWarning ? 'warning' : '')}`;
                cardEl.innerHTML = `
                    <div class="sq-row1">${b.name}</div>
                    <div class="sq-row2" style="color: ${valColor};">${b.value}</div>
                `;
                return;
            }

            // 【修改项 3】长条模式卡片（完整列出，无收起展开功能）
            cardEl.className = `card ${b.is_alarm ? 'alarm' : (isWarning ? 'warning' : '')}`;
            
            let logsHtml = (b.logs && b.logs.length > 0)
                ? b.logs.map(l => `<div class="log-item">${l}</div>`).join('')
                : '<div class="log-item">无历史记录</div>';

            cardEl.innerHTML = `
                <div class="card-header">
                    <span class="card-title">${b.name}</span>
                    <div style="display: flex; gap: 6px; align-items: center;" id="action-btns-${b.id}"></div>
                </div>
                <div class="value-box">
                    <div class="val-text" id="val-text-${b.id}" style="color: ${valColor}">${b.value}</div>
                </div>
                <div class="card-body">
                    <div class="setting-row" id="setting-row-${b.id}">
                        <label>下限:</label>
                        <input id="input-lower-${b.id}" class="setting-input" type="number" step="0.1" value="${b.lower}">
                        <label>预警值:</label>
                        <input id="input-mid-${b.id}" class="setting-input" type="number" step="0.1" value="${b.mid_val}">
                        <label>上限:</label>
                        <input id="input-upper-${b.id}" class="setting-input" type="number" step="0.1" value="${b.upper}">
                        <button class="btn-action" style="background:#0088cc; color:white; margin-left:auto;" onclick="saveLimits(${b.id})">💾 保存</button>
                    </div>
                    <div class="log-title">📜 历史日志:</div>
                    <div class="log-list" id="log-list-${b.id}">${logsHtml}</div>
                </div>
            `;

            const actionBtns = cardEl.querySelector(`#action-btns-${b.id}`);
            if (actionBtns) {
                if (isLoggedIn) {
                    actionBtns.innerHTML = `
                        ${b.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${b.id})">🚨 消除报警</button>` : ''}
                        <button class="btn-action ${b.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}" onclick="postAction('toggle_mute', ${b.id})">
                            ${b.is_muted ? '🔕 报警关' : '🔔 报警开'}
                        </button>
                    `;
                } else { actionBtns.innerHTML = ''; }
            }

            const settingRow = cardEl.querySelector(`#setting-row-${b.id}`);
            if (settingRow) settingRow.style.display = isLoggedIn ? 'flex' : 'none';
        }

        async function refreshData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();

                updateLoginUI();
                updateDisplayModeUI();

                const statusEl = document.getElementById('status');
                if (statusEl) {
                    statusEl.innerText = `监控: ${data.monitoring ? '运行中' : '停止'} | 操作: ${data.grille_active ? '运行中' : '停止'}`;
                }

                const btnMonitor = document.getElementById('btn-monitor');
                if (btnMonitor) {
                    btnMonitor.innerText = data.monitoring ? "⏹ 停止监控" : "▶ 开始监控";
                    btnMonitor.className = data.monitoring ? "btn-top active" : "btn-top";
                }

                const btnGrille = document.getElementById('btn-grille');
                if (btnGrille) {
                    btnGrille.innerText = data.grille_active ? "⏹ 停止操作" : "▶ 开始操作";
                    btnGrille.className = data.grille_active ? "btn-top btn-grille active" : "btn-top btn-grille";
                }

                let hasAnyAlarm = false;
                const container = document.getElementById('cards-container');

                data.boxes.forEach(b => {
                    const numVal = parseFloat(b.value);
                    const isWarning = (!isNaN(numVal) && !b.is_alarm && numVal > b.mid_val);

                    if (b.is_alarm && !b.is_muted) hasAnyAlarm = true;

                    let cardEl = document.getElementById(`card-${b.id}`);
                    if (!cardEl) {
                        cardEl = document.createElement('div');
                        cardEl.id = `card-${b.id}`;
                        container.appendChild(cardEl);
                    }
                    renderCardDOM(cardEl, b, isWarning);
                });

                triggerAlarmSoundLoop(hasAnyAlarm);

            } catch(e) { console.error("刷新数据失败:", e); }
        }

        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""


# ==================== 10. Flask 服务器管理线程 ====================
class FlaskServerThread(QThread):
    def __init__(self, main_win, host="0.0.0.0", port=5000):
        super().__init__()
        self.main_win = main_win
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @self.app.route('/favicon.ico')
        def favicon():
            return "", 204

        @self.app.route('/api/data')
        def get_data():
            boxes_data = []
            for b in self.main_win.boxes:
                val_display = "--"
                if hasattr(b, 'last_val') and b.last_val is not None:
                    val_display = f"{b.last_val:.2f}"
                elif hasattr(b, 'last_raw_str') and b.last_raw_str:
                    val_display = f"({b.last_raw_str})"

                boxes_data.append({
                    "id": b.box_id,
                    "name": b.name,
                    "value": val_display,
                    "lower": b.lower,
                    "mid_val": b.mid_val,
                    "upper": b.upper,
                    "is_alarm": b.is_alarm,
                    "is_muted": b.is_muted,
                    "logs": getattr(b, 'logs_history', [])
                })

            return jsonify({
                "monitoring": self.main_win.is_monitoring,
                "grille_active": self.main_win.grille_thread is not None and self.main_win.grille_thread.isRunning(),
                "boxes": boxes_data
            })

        @self.app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.json or {}
            action = data.get('action')
            box_id = data.get('id')
            extra = data.get('data', {})

            if action == 'toggle_monitor':
                self.main_win.toggle_monitor()
            elif action == 'toggle_grille':
                self.main_win.toggle_grille()
            else:
                box = next((b for b in self.main_win.boxes if b.box_id == box_id), None)
                if box:
                    if action == 'clear_alarm':
                        box._on_clear_alarm()
                    elif action == 'toggle_mute':
                        box._toggle_mute()
                    elif action == 'set_limits':
                        if 'lower' in extra: box.spin_lower.setValue(extra['lower'])
                        if 'mid_val' in extra: box.spin_mid.setValue(extra['mid_val'])
                        if 'upper' in extra: box.spin_upper.setValue(extra['upper'])

            return jsonify({"status": "ok"})

        @self.app.route('/api/login', methods=['POST'])
        def login():
            data = request.json or {}
            u = data.get('username')
            p = data.get('password')
            if u in self.main_win.users_db and self.main_win.users_db[u] == p:
                return jsonify({"success": True, "username": u})
            return jsonify({"success": False, "message": "账号或密码错误"})

        @self.app.route('/api/users/list')
        def list_users():
            return jsonify({"users": list(self.main_win.users_db.keys())})

        @self.app.route('/api/users/add', methods=['POST'])
        def add_user():
            data = request.json or {}
            u = data.get('username')
            p = data.get('password')
            if not u or not p:
                return jsonify({"success": False, "message": "信息不完整"})
            if u in self.main_win.users_db:
                return jsonify({"success": False, "message": "用户已存在"})
            self.main_win.users_db[u] = p
            self.main_win.save_config()
            return jsonify({"success": True, "message": "添加用户成功"})

        @self.app.route('/api/users/change_password', methods=['POST'])
        def change_pass():
            data = request.json or {}
            u = data.get('username')
            old_p = data.get('old_password')
            new_p = data.get('new_password')
            if u in self.main_win.users_db and self.main_win.users_db[u] == old_p:
                self.main_win.users_db[u] = new_p
                self.main_win.save_config()
                return jsonify({"success": True, "message": "修改密码成功"})
            return jsonify({"success": False, "message": "旧密码错误"})

        @self.app.route('/api/users/delete', methods=['POST'])
        def delete_user():
            data = request.json or {}
            u = data.get('username')
            if u == 'admin':
                return jsonify({"success": False, "message": "默认管理员不能删除"})
            if u in self.main_win.users_db:
                del self.main_win.users_db[u]
                self.main_win.save_config()
                return jsonify({"success": True, "message": "删除成功"})
            return jsonify({"success": False, "message": "用户不存在"})

    def run(self):
        if FLASK_AVAILABLE:
            import logging
            log = logging.getLogger('werkzeug')
            log.setLevel(logging.ERROR)
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)


# ==================== 11. 主控制面板 GUI ====================
class MainControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🖥️ 多区域 OCR 监控与中控台")
        self.resize(520, 360)

        self.boxes = []
        self.next_box_id = 1
        self.is_monitoring = False
        self.ocr_reader = None

        self.users_db = {"admin": "admin123"}
        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}

        self.alarm_player = AlarmSoundPlayer()
        self.monitor_thread = None
        self.grille_thread = None

        self._init_ocr()
        self._setup_ui()
        self._load_config()

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self.toggle_monitor)
        self.f12_listener.start()

        if FLASK_AVAILABLE:
            self.flask_thread = FlaskServerThread(self)
            self.flask_thread.start()

    def _init_ocr(self):
        if DDDDOCR_AVAILABLE:
            try:
                self.ocr_reader = ddddocr.DdddOcr(show_ad=False)
            except: self.ocr_reader = None

    def _setup_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #121218; color: #e0e0e0; font-family: Microsoft YaHei, sans-serif; }
            QLabel { font-weight: bold; font-size: 12px; color: #a0a0a0; }
            QPushButton {
                background-color: #2a2a3c; color: white; border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; padding: 6px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a52; }
            QSpinBox, QDoubleSpinBox {
                background-color: #1a1a26; color: #00ff8c; border: 1px solid rgba(255,255,255,0.2);
                border-radius: 4px; padding: 3px 6px; font-weight: bold;
            }
        """)

        main_layout = QVBoxLayout(self)

        # 头部与 IP
        top_box = QHBoxLayout()
        lbl_title = QLabel("🖥️ 多区域数字 OCR 监控系统")
        lbl_title.setStyleSheet("color: #00ff8c; font-size: 16px; font-weight: bold;")
        top_box.addWidget(lbl_title)
        top_box.addStretch()

        ip = get_local_ip()
        lbl_web = QLabel(f"🌐 手机Web端: http://{ip}:5000")
        lbl_web.setStyleSheet("color: #0088cc; font-size: 11px;")
        top_box.addWidget(lbl_web)
        main_layout.addLayout(top_box)

        # 设置参数行
        param_layout = QHBoxLayout()
        
        # 【修改项 1】识别间隔默认设置为 10 秒
        param_layout.addWidget(QLabel("识别间隔(秒):"))
        self.spin_interval = CleanDoubleSpinBox()
        self.spin_interval.setRange(0.1, 3600.0)
        self.spin_interval.setValue(10.0)
        self.spin_interval.valueChanged.connect(self._on_param_changed)
        param_layout.addWidget(self.spin_interval)

        param_layout.addWidget(QLabel("格栅循环(分):"))
        self.spin_grille_min = CleanDoubleSpinBox()
        self.spin_grille_min.setRange(0.1, 1440.0)
        self.spin_grille_min.setValue(2.0)
        param_layout.addWidget(self.spin_grille_min)

        main_layout.addLayout(param_layout)

        # 操作按钮组
        btn_layout = QHBoxLayout()

        self.btn_add_box = QPushButton("📐 添加识别框 (选区)")
        self.btn_add_box.setStyleSheet("background-color: #0088cc;")
        self.btn_add_box.clicked.connect(self.add_new_box_by_pick)
        btn_layout.addWidget(self.btn_add_box)

        self.btn_adjust_ocr = QPushButton("⚙️ OCR 预处理微调")
        self.btn_adjust_ocr.clicked.connect(self.open_ocr_adjust_dialog)
        btn_layout.addWidget(self.btn_adjust_ocr)

        self.btn_toggle_monitor = QPushButton("▶ 开始监控 (F12)")
        self.btn_toggle_monitor.setStyleSheet("background-color: #2e9a58;")
        self.btn_toggle_monitor.clicked.connect(self.toggle_monitor)
        btn_layout.addWidget(self.btn_toggle_monitor)

        self.btn_toggle_grille = QPushButton("⚡ 细格栅自动点击")
        self.btn_toggle_grille.clicked.connect(self.toggle_grille)
        btn_layout.addWidget(self.btn_toggle_grille)

        main_layout.addLayout(btn_layout)

        # 区域选框管理列表
        main_layout.addWidget(QLabel("📋 识别区域列表:"))
        self.table_boxes = QTableWidget(0, 5)
        self.table_boxes.setHorizontalHeaderLabels(["ID", "名称", "坐标尺寸", "报警阈值", "操作"])
        self.table_boxes.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_boxes.setStyleSheet("""
            QTableWidget { background-color: #1a1a26; border: 1px solid rgba(255,255,255,0.1); font-size: 11px; }
            QHeaderView::section { background-color: #2a2a3c; color: #00ff8c; font-weight: bold; border: none; padding: 4px; }
        """)
        main_layout.addWidget(self.table_boxes)

    def _on_param_changed(self):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=self.spin_interval.value())

    def add_new_box_by_pick(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0: return

            box_id = self.next_box_id
            self.next_box_id += 1

            box = OverlayRegionWidget(box_id, x, y, w, h, name=f"区域 {box_id}")
            box.delete_requested.connect(self.remove_box)
            box.alarm_cleared.connect(self._check_global_alarm)
            box.mute_toggled.connect(self._check_global_alarm)
            box.set_edit_mode(True)
            box.show()

            self.boxes.append(box)
            self.update_boxes_table()
            self.save_config()

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def remove_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self.update_boxes_table()
            self._check_global_alarm()
            self.save_config()

    def update_boxes_table(self):
        self.table_boxes.setRowCount(len(self.boxes))
        for idx, b in enumerate(self.boxes):
            self.table_boxes.setItem(idx, 0, QTableWidgetItem(str(b.box_id)))
            self.table_boxes.setItem(idx, 1, QTableWidgetItem(b.name))
            self.table_boxes.setItem(idx, 2, QTableWidgetItem(f"{b.capture_x},{b.capture_y} {b.capture_w}x{b.capture_h}"))
            self.table_boxes.setItem(idx, 3, QTableWidgetItem(f"[{b.lower}, {b.upper}] 预警:{b.mid_val}"))

            btn_del = QPushButton("删除")
            btn_del.setStyleSheet("background-color: #ff3333; padding: 2px 4px; font-size: 10px;")
            btn_del.clicked.connect(lambda _, box=b: self.remove_box(box))
            self.table_boxes.setCellWidget(idx, 4, btn_del)

    def open_ocr_adjust_dialog(self):
        dlg = OCRAdjustDialog(self.ocr_params, reader=self.ocr_reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)
            self.save_config()

    def toggle_monitor(self):
        if not self.is_monitoring:
            if not self.boxes: return
            self.is_monitoring = True
            self.btn_toggle_monitor.setText("⏹ 停止监控 (F12)")
            self.btn_toggle_monitor.setStyleSheet("background-color: #ff3333;")

            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            for b in self.boxes:
                b.set_edit_mode(False)

            self.monitor_thread = MonitorThread(self.boxes, interval=self.spin_interval.value(), ocr_params=self.ocr_params, scale=scale)
            self.monitor_thread.set_reader(self.ocr_reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.start()
        else:
            self.is_monitoring = False
            self.btn_toggle_monitor.setText("▶ 开始监控 (F12)")
            self.btn_toggle_monitor.setStyleSheet("background-color: #2e9a58;")

            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None

            for b in self.boxes:
                b.set_edit_mode(True)

            self.alarm_player.stop()

    def _on_value_updated(self, box, time_str, val, raw_text):
        box.last_val = val
        box.last_raw_str = raw_text
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        is_alarm = False
        if val is not None:
            if val > box.upper or val < box.lower:
                is_alarm = True

        if is_alarm:
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

    def toggle_grille(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.grille_thread.stop()
            self.grille_thread.wait()
            self.grille_thread = None
            self.btn_toggle_grille.setText("⚡ 细格栅自动点击")
            self.btn_toggle_grille.setStyleSheet("background-color: #2a2a3c;")
        else:
            self.grille_thread = FineGrilleThread(cycle_interval_min=self.spin_grille_min.value())
            self.grille_thread.start()
            self.btn_toggle_grille.setText("⏹ 停止细格栅")
            self.btn_toggle_grille.setStyleSheet("background-color: #cc3333;")

    def _load_config(self):
        if not os.path.exists("config.json"): return
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                self.spin_interval.setValue(data.get("interval", 10.0))
                self.spin_grille_min.setValue(data.get("grille_min", 2.0))
                self.ocr_params = data.get("ocr_params", self.ocr_params)
                self.users_db = data.get("users_db", self.users_db)

                for bdata in data.get("boxes", []):
                    box_id = bdata.get("id", self.next_box_id)
                    self.next_box_id = max(self.next_box_id, box_id + 1)
                    box = OverlayRegionWidget(
                        box_id, bdata["x"], bdata["y"], bdata["w"], bdata["h"],
                        name=bdata.get("name", "区域"),
                        lower=bdata.get("lower", 0.0),
                        mid_val=bdata.get("mid_val", 50.0),
                        upper=bdata.get("upper", 100.0),
                        decimal_places=bdata.get("decimal_places", 0)
                    )
                    box.delete_requested.connect(self.remove_box)
                    box.alarm_cleared.connect(self._check_global_alarm)
                    box.mute_toggled.connect(self._check_global_alarm)
                    box.set_edit_mode(True)
                    box.show()
                    self.boxes.append(box)

                self.update_boxes_table()
        except Exception as e:
            print("配置文件加载失败:", e)

    def save_config(self):
        data = {
            "interval": self.spin_interval.value(),
            "grille_min": self.spin_grille_min.value(),
            "ocr_params": self.ocr_params,
            "users_db": self.users_db,
            "boxes": [
                {
                    "id": b.box_id,
                    "name": b.name,
                    "x": b.capture_x, "y": b.capture_y,
                    "w": b.capture_w, "h": b.capture_h,
                    "lower": b.lower, "mid_val": b.mid_val, "upper": b.upper,
                    "decimal_places": b.decimal_places
                } for b in self.boxes
            ]
        }
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存配置失败:", e)

    def closeEvent(self, event):
        self.save_config()
        if self.f12_listener: self.f12_listener.stop()
        if self.monitor_thread: self.monitor_thread.stop()
        if self.grille_thread: self.grille_thread.stop()
        for b in self.boxes: b.close()
        event.accept()


# ==================== 主入口程序 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    main_win = MainControlPanel()
    main_win.show()

    sys.exit(app.exec())
