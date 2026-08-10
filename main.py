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
    QDialog, QFormLayout, QDialogButtonBox, QComboBox
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
    from flask import Flask, jsonify, render_template_string, request
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


# ==================== 自定义无冗余 .00 的 SpinBox ====================
class CleanDoubleSpinBox(QDoubleSpinBox):
    """自动消除末尾 .00 / 冗余 0 的输入框"""
    def textFromValue(self, val):
        s = f"{val:.2f}"
        if s.endswith('.00'):
            return s[:-3]
        elif s.endswith('0') and '.' in s:
            return s[:-1]
        return s


# ==================== 全局 F12 键盘监听线程 ====================
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


# ==================== 报警声音播放器 ====================
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


# ==================== OCR 识别参数调整对话框 ====================
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


# ==================== 独立日志查看弹窗 ====================
class LogDialog(QDialog):
    def __init__(self, box, parent=None):
        super().__init__(parent)
        self.box = box
        self.setWindowTitle(f"📋 历史日志 - {box.name}")
        self.resize(380, 260)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #0088cc; color: white; border: none;
                border-radius: 4px; padding: 4px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #00a8ff; }
        """)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for i in range(box.list_widget.count()):
            self.list_widget.addItem(box.list_widget.item(i).text())
        layout.addWidget(self.list_widget)
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)


# ==================== 悬浮识别选框窗口 ====================
class OverlayRegionWidget(QWidget):
    delete_requested = Signal(object)
    alarm_cleared = Signal()
    mute_toggled = Signal()

    def __init__(self, box_id, x, y, w, h, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, mid_op=">", parent=None):
        super().__init__(None)
        self.box_id = box_id
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(1, w)
        self.capture_h = max(1, h)

        self.name = name
        self.lower = lower
        self.mid_val = mid_val  # 预警值
        self.mid_op = mid_op if mid_op in ('>', '<', '=') else '>'
        self.upper = upper
        self.decimal_places = decimal_places

        self.log_interval_min = 1.0
        self.last_log_time = 0.0
        self.max_log_count = 30
        self.history_records = []  # 记录 [(timestamp, val), ...] 用于对比

        self.is_alarm = False     # 真正异常报警 (超越上下限)
        self.is_warning = False   # 预警状态 (达到预警，框子变黄，不报警)
        self.user_cleared_alarm = False
        self.cleared_val = None

        self.is_editing = False
        self.is_muted = False
        self.panel_hidden = False
        self.rows12_collapsed = False  # 修改二：用于控制一二排折叠状态

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
        self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        panel_layout = QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)

        # 排列一: 名字与识别结果
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
        self.lbl_result.setMaximumWidth(60)
        self.lbl_result.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: bold; margin-left: 2px;")

        row1_layout.addWidget(self.lbl_title)
        row1_layout.addWidget(self.edit_title)
        row1_layout.addWidget(self.lbl_result)
        row1_layout.addStretch()
        panel_layout.addWidget(self.row1_container)

        # 排列二: 上下限调整与删除
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

        # 排列三: 预警值, 🚨 消除报警 及 修改二: 折叠按键
        self.row3_container = QWidget()
        row3_layout = QHBoxLayout(self.row3_container)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(3)

        self.lbl_mid = QLabel("预警:")
        self.lbl_mid.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")
        
        self.combo_mid_op = QComboBox()
        self.combo_mid_op.addItems([">", "<", "="])
        self.combo_mid_op.setCurrentText(self.mid_op)
        self.combo_mid_op.setFixedSize(32, 20)
        self.combo_mid_op.setStyleSheet("background-color: rgba(26, 26, 38, 0.8); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.combo_mid_op.currentTextChanged.connect(self._on_mid_op_changed)

        self.spin_mid = CleanDoubleSpinBox()
        self.spin_mid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_mid.setAlignment(Qt.AlignCenter)
        self.spin_mid.setRange(-99999.0, 99999.0)
        self.spin_mid.setValue(self.mid_val)
        self.spin_mid.setFixedSize(36, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        # 修改二：第三排末尾加上折叠一二排按钮
        self.btn_fold = QPushButton("▲")
        self.btn_fold.setFixedSize(20, 20)
        self.btn_fold.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_fold.clicked.connect(self._toggle_rows_fold)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.combo_mid_op)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addStretch()
        row3_layout.addWidget(self.btn_clear_alarm)
        row3_layout.addWidget(self.btn_fold)
        panel_layout.addWidget(self.row3_container)

        # 修改一：已全盘删除第四排 (row4_container)

        self.list_widget = QListWidget()

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _toggle_rows_fold(self):
        self.rows12_collapsed = not self.rows12_collapsed
        self.btn_fold.setText("▼" if self.rows12_collapsed else "▲")
        self._update_bar_visibility()
        self._update_geometry()

    def _on_lower_changed(self, val): self.lower = val
    def _on_mid_op_changed(self, text): self.mid_op = text
    def _on_mid_changed(self, val): self.mid_val = val
    def _on_upper_changed(self, val): self.upper = val
    def _on_dec_changed(self, val): self.decimal_places = val
    def _on_title_changed(self, text):
        self.name = text
        self.lbl_title.setText(text)

    def check_mid_condition(self, val):
        if val is None: return False
        if self.mid_op == '>': return val > self.mid_val
        elif self.mid_op == '<': return val < self.mid_val
        elif self.mid_op == '=': return abs(val - self.mid_val) < 1e-4
        return False

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            dp = getattr(self, 'decimal_places', 2)
            self.lbl_result.setText(f"{val:.{dp}f}")
            if val > self.upper or val < self.lower:
                self.lbl_result.setStyleSheet("color: #ff4d4d; font-size: 11px; font-weight: bold; margin-left: 2px;")
            elif self.check_mid_condition(val):
                self.lbl_result.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold; margin-left: 2px;")
            else:
                self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold; margin-left: 2px;")
        else:
            disp = f"({raw_text})" if raw_text else "--"
            self.lbl_result.setText(f"{disp}")
            self.lbl_result.setStyleSheet("color: #ff6666; font-size: 11px; font-weight: bold; margin-left: 2px;")

    def add_log_val(self, time_str, val, raw_text=""):
        now_ts = time.time()
        if val is not None:
            self.history_records.append((now_ts, val))
            if len(self.history_records) > 500:
                self.history_records.pop(0)

        if self.last_log_time == 0.0 or (now_ts - self.last_log_time >= self.log_interval_min * 60.0):
            self.last_log_time = now_ts
            dp = getattr(self, 'decimal_places', 2)
            msg = f"[{time_str}] {val:.{dp}f}" if val is not None else f"[{time_str}] ❌未检测到"
            self.list_widget.insertItem(0, msg)
            while self.list_widget.count() > self.max_log_count:
                self.list_widget.takeItem(self.max_log_count)

    def get_past_value(self, minutes_ago):
        if not self.history_records: return None
        target_ts = time.time() - (minutes_ago * 60.0)
        closest_rec = None
        min_diff = float('inf')
        for ts, val in self.history_records:
            diff = abs(ts - target_ts)
            if diff < min_diff:
                min_diff = diff
                closest_rec = val
        return closest_rec

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
                self.lbl_mid.setVisible(False)
                self.combo_mid_op.setVisible(False)
                self.spin_mid.setVisible(False)
                self.btn_clear_alarm.setVisible(True)
                self.btn_fold.setVisible(False)
            else:
                self.control_panel.setVisible(False)
        else:
            self.control_panel.setVisible(True)
            self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
            
            if self.rows12_collapsed:
                self.row1_container.setVisible(False)
                self.row2_container.setVisible(False)
            else:
                self.row1_container.setVisible(True)
                self.row2_container.setVisible(self.is_editing)

            self.row3_container.setVisible(True)

            self.lbl_mid.setVisible(self.is_editing)
            self.combo_mid_op.setVisible(self.is_editing)
            self.spin_mid.setVisible(self.is_editing)
            self.btn_clear_alarm.setVisible(self.is_alarm)
            self.btn_fold.setVisible(True)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        total_w = max(self.capture_w, 140)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
            if self.rows12_collapsed:
                panel_h = 28
            else:
                panel_h = 75 if self.is_editing else 50

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

    def set_warning_state(self, is_warning):
        if self.is_warning != is_warning:
            self.is_warning = is_warning
            self.update()

    def _on_clear_alarm(self):
        self.user_cleared_alarm = True
        try:
            self.cleared_val = float(self.lbl_result.text())
        except ValueError:
            self.cleared_val = None
        self.set_alarm_state(False)
        self.alarm_cleared.emit()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
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
        elif self.is_warning:
            pen = QPen(QColor(255, 215, 0), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 215, 0, 25))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 25))

        painter.drawRect(box_rect.adjusted(1, 1, -1, -1))


# ==================== 屏幕选区拾取器 ====================
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


# ==================== 后台识别线程 ====================
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
        if interval is not None: self.interval = max(0.1, interval)
        if ocr_params is not None: self.ocr_params = ocr_params
        if scale is not None: self.scale = scale

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
            if ch in mapping: res[i] = mapping[ch]
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
                                    except ValueError: pass
                            else:
                                nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)
                                if nums:
                                    try:
                                        found_val = float(nums[0])
                                        break
                                    except ValueError: pass

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


# ==================== Flask 网页/手机端 WEB 交互界面 ====================
MOBILE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link rel="shortcut icon" href="/favicon.ico" type="image/x-icon">
    <title>📱 中控数据面板</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #121218; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; }
        
        .container { max-width: 600px; margin: 0 auto; width: 100%; }

        .header { background: #1a1a26; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 8px; }
        
        .header-row1 { display: flex; justify-content: space-between; align-items: center; width: 100%; flex-wrap: wrap; gap: 6px; }
        .header-title-box { display: flex; align-items: center; gap: 6px; }
        .header-tools-box { display: flex; align-items: center; gap: 6px; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; }
        
        /* 修改四：名称右侧的折叠按钮样式调整，避免太亮眼 */
        .toggle-icon { cursor: pointer; font-size: 11px; color: #888888; font-weight: normal; user-select: none; padding: 1px 5px; border-radius: 3px; background: rgba(255, 255, 255, 0.08); margin-left: 6px; }
        .toggle-icon:hover { color: #cccccc; background: rgba(255, 255, 255, 0.18); }

        .header-row2 { display: flex; align-items: center; gap: 8px; width: 100%; font-size: 12px; }
        .header-row3 { display: flex; gap: 10px; width: 100%; margin-top: 2px; }
        
        .btn-top { flex: 1; background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 8px 12px; font-size: 13px; font-weight: bold; cursor: pointer; transition: background 0.2s; text-align: center; }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; }

        .btn-fold-tool { background: rgba(255,255,255,0.1); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; }

        .login-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 6px; width: 100%; font-size: 12px; }

        #cards-container { display: flex; flex-direction: column; gap: 10px; }

        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); transition: all 0.2s; user-select: none; }

        .card.alarm { border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); animation: blink 1s infinite alternate; }
        @keyframes blink { from { box-shadow: 0 0 5px rgba(255,77,77,0.3); } to { box-shadow: 0 0 15px rgba(255,77,77,0.8); } }

        .card.warning { border: 2px solid #ffaa00; background: rgba(255, 170, 0, 0.08); }

        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; width: 100%; }
        .card-title-box { display: flex; align-items: center; gap: 4px; flex-grow: 1; overflow: hidden; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .card-header-right { display: flex; align-items: center; gap: 8px; margin-left: auto; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .trend-up { color: #ff4d4d; font-weight: bold; font-size: 16px; margin-right: 2px; }
        .trend-down { color: #00ff8c; font-weight: bold; font-size: 16px; margin-right: 2px; }

        /* 修改三：误差值样式 */
        .diff-val { font-size: 11px; color: #aaaaaa; margin-right: 4px; font-family: monospace; }

        .val-container { display: flex; align-items: center; font-size: 18px; font-weight: bold; font-family: monospace; }
        .val-text { color: #00ff8c; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 48px; text-align: center; font-size: 11px; }

        .log-title { margin-top: 6px; font-size: 11px; color: #888; font-weight: bold; }
        .log-list { margin-top: 4px; background: rgba(0,0,0,0.4); border-radius: 6px; padding: 6px 8px; font-size: 11px; font-family: monospace; height: 110px; overflow-y: auto; color: #00ff8c; }
        .log-list::-webkit-scrollbar { width: 4px; }
        .log-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 2px; }
        .log-item { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); white-space: nowrap; }

        .modal-overlay { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }
        .modal-content { background: #1a1a26; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; width: 90%; max-width: 420px; padding: 16px; color: #e0e0e0; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; }
        .modal-close { cursor: pointer; color: #ff4d4d; font-weight: bold; font-size: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-row1">
                <div class="header-title-box">
                    <span class="title">📱 中控数据面板</span>
                </div>
                <div class="header-tools-box">
                    <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 声音</button>
                    <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                        <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
                    </div>
                    <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                        <span id="current-username" style="color:#00ff8c; font-size:11px; font-weight:bold;">👤</span>
                        <button class="btn-action" style="background:#e65100; color:white;" onclick="openUserMgmtModal()">⚙️ 用户</button>
                        <button class="btn-action" style="background:#555; color:white;" onclick="handleLogout()">🚪 退出</button>
                    </div>
                </div>
            </div>

            <div id="header-row2" class="header-row2" style="display: none;">
                <label style="color:#ffaa00; font-weight:bold;">对比(分钟):</label>
                <input id="compare-min-input" type="number" min="0" step="1" class="setting-input" style="width:60px;" value="5">
                <button class="btn-action" style="background:#0088cc; padding:4px 8px;" onclick="saveCompareMin()">保存</button>
            </div>

            <div id="header-row3" class="header-row3" style="display: none;">
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div id="cards-container"></div>
    </div>

    <!-- 登录弹窗 -->
    <div id="login-modal" class="modal-overlay">
        <div class="modal-content" style="max-width: 320px;">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">🔐 用户登录</span>
                <span class="modal-close" onclick="closeLoginModal()">✖</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 10px;">
                <input type="text" id="login-username" class="login-input" placeholder="用户名" />
                <input type="password" id="login-password" class="login-input" placeholder="密码" />
                <button class="btn-top" style="background:#0088cc; width:100%;" onclick="handleLogin()">登录</button>
            </div>
        </div>
    </div>

    <!-- 用户管理弹窗 -->
    <div id="user-modal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">⚙️ 用户管理</span>
                <span class="modal-close" onclick="closeUserModal()">✖</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 10px;">
                <input type="text" id="new-username" class="login-input" placeholder="新用户名" />
                <input type="password" id="new-password" class="login-input" placeholder="新密码" />
                <button class="btn-top" style="background:#2e9a58; width:100%;" onclick="handleAddUser()">添加/更新用户</button>
                <div id="users-list" style="margin-top: 10px; max-height: 150px; overflow-y: auto;"></div>
            </div>
        </div>
    </div>

    <script>
        let webSoundEnabled = false;
        let currentUser = localStorage.getItem('currentUser') || null;
        let cardExpandedState = {};

        function updateAuthUI() {
            if (currentUser) {
                document.getElementById('login-box').style.display = 'none';
                document.getElementById('user-box').style.display = 'inline-flex';
                document.getElementById('current-username').innerText = '👤 ' + currentUser;
                
                document.getElementById('header-row2').style.display = 'flex';
                document.getElementById('header-row3').style.display = 'flex';
            } else {
                document.getElementById('login-box').style.display = 'inline-flex';
                document.getElementById('user-box').style.display = 'none';

                document.getElementById('header-row2').style.display = 'none';
                document.getElementById('header-row3').style.display = 'none';

                cardExpandedState = {};
                document.querySelectorAll('.fold-body').forEach(el => {
                    el.style.display = 'none';
                });
            }
        }

        function openLoginModal() { document.getElementById('login-modal').style.display = 'flex'; }
        function closeLoginModal() { document.getElementById('login-modal').style.display = 'none'; }
        function openUserMgmtModal() { document.getElementById('user-modal').style.display = 'flex'; loadUsersList(); }
        function closeUserModal() { document.getElementById('user-modal').style.display = 'none'; }

        async function handleLogin() {
            const u = document.getElementById('login-username').value;
            const p = document.getElementById('login-password').value;
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: u, password: p})
                });
                if (res.ok) {
                    currentUser = u;
                    localStorage.setItem('currentUser', u);
                    updateAuthUI();
                    closeLoginModal();
                } else {
                    alert('登录失败，请检查账号密码');
                }
            } catch(e) { alert('请求异常: ' + e); }
        }

        function handleLogout() {
            currentUser = null;
            localStorage.removeItem('currentUser');
            updateAuthUI();
        }

        async function handleAddUser() {
            const u = document.getElementById('new-username').value;
            const p = document.getElementById('new-password').value;
            if(!u || !p) { alert('请输入用户名和密码'); return; }
            try {
                const res = await fetch('/api/users', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'add', username: u, password: p})
                });
                if (res.ok) {
                    alert('操作成功');
                    document.getElementById('new-username').value = '';
                    document.getElementById('new-password').value = '';
                    loadUsersList();
                }
            } catch(e) { alert('操作失败'); }
        }

        async function loadUsersList() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                const container = document.getElementById('users-list');
                container.innerHTML = '';
                if(data.users) {
                    for(let u in data.users) {
                        const div = document.createElement('div');
                        div.style.display = 'flex';
                        div.style.justifyContent = 'space-between';
                        div.style.padding = '4px 0';
                        div.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
                        div.innerHTML = `<span>${u}</span> ${u!=='admin'?`<button onclick="deleteUser('${u}')" style="color:#ff4d4d; background:none; border:none; cursor:pointer;">删除</button>`:''}`;
                        container.appendChild(div);
                    }
                }
            } catch(e){}
        }

        async function deleteUser(u) {
            if(!confirm('确定删除用户 '+u+' ?')) return;
            try {
                await fetch('/api/users', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'delete', username: u})
                });
                loadUsersList();
            } catch(e){}
        }

        function toggleSingleCard(boxId) {
            if (!currentUser) return;
            cardExpandedState[boxId] = !cardExpandedState[boxId];
            const foldBody = document.getElementById('fold-body-' + boxId);
            const icon = document.getElementById('toggle-icon-' + boxId);
            if (foldBody) {
                foldBody.style.display = cardExpandedState[boxId] ? 'block' : 'none';
            }
            if (icon) {
                icon.innerText = cardExpandedState[boxId] ? '▲' : '▼';
            }
        }

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            document.getElementById('btn-sound').innerText = webSoundEnabled ? '🔊 声音开' : '🔇 声音关';
        }

        async function postAction(action, boxId, data = {}) {
            try {
                await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action, box_id: boxId, data})
                });
                fetchStatus();
            } catch(e) {}
        }

        function updateLimits(boxId) {
            const lower = document.getElementById('lower-' + boxId).value;
            const mid_op = document.getElementById('mid_op-' + boxId).value;
            const mid_val = document.getElementById('mid-' + boxId).value;
            const upper = document.getElementById('upper-' + boxId).value;
            postAction('set_limits', boxId, {lower, mid_op, mid_val, upper});
        }

        function saveCompareMin() {
            const val = document.getElementById('compare-min-input').value;
            postAction('set_compare_min', -1, {compare_min: parseFloat(val)});
        }

        function checkMidCondition(val, op, mid_val) {
            if (val === null || val === undefined) return false;
            if (op === '>') return val > mid_val;
            if (op === '<') return val < mid_val;
            if (op === '=') return Math.abs(val - mid_val) < 1e-4;
            return false;
        }

        function renderCards(boxes) {
            const container = document.getElementById('cards-container');

            boxes.forEach(box => {
                let card = document.getElementById('card-' + box.id);
                if (!card) {
                    card = document.createElement('div');
                    card.id = 'card-' + box.id;
                    container.appendChild(card);
                }

                let cardClass = 'card';
                let valClass = 'val-text';
                if (box.is_alarm) {
                    cardClass += ' alarm';
                    valClass += ' alarm-text';
                } else if (checkMidCondition(box.val, box.mid_op, box.mid_val)) {
                    cardClass += ' warning';
                    valClass += ' warning-text';
                }
                card.className = cardClass;

                let trendHtml = '';
                if (box.trend === 'up') {
                    trendHtml = '<span class="trend-up">▲</span>';
                } else if (box.trend === 'down') {
                    trendHtml = '<span class="trend-down">▼</span>';
                }

                /* 修改三：在对比值上下图标左边显示误差值 */
                let diffHtml = '';
                if (box.diff !== null && box.diff !== undefined && box.trend !== 'none') {
                    let sign = box.diff > 0 ? '+' : '';
                    diffHtml = `<span class="diff-val">${sign}${box.diff.toFixed(2)}</span>`;
                }

                let header = card.querySelector('.card-header');
                const isExpanded = !!cardExpandedState[box.id];

                if (!header) {
                    const logsHtml = (box.logs || []).map(l => `<div class="log-item">${l}</div>`).join('');
                    card.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box">
                                <span class="card-title">${box.name}</span>
                                ${currentUser ? `<span id="toggle-icon-${box.id}" class="toggle-icon" onclick="toggleSingleCard(${box.id})">${isExpanded ? '▲' : '▼'}</span>` : ''}
                            </div>
                            <div class="card-header-right">
                                <div class="val-container">
                                    <span id="diff-${box.id}">${diffHtml}</span>
                                    <span id="trend-${box.id}">${trendHtml}</span>
                                    <span id="val-${box.id}" class="${valClass}">${box.val_text}</span>
                                </div>
                                <span id="alarm-btn-box-${box.id}">
                                    ${box.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${box.id})">🚨 消除</button>` : ''}
                                </span>
                                <button id="mute-btn-${box.id}" class="btn-action ${box.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}" onclick="postAction('toggle_mute', ${box.id})">${box.is_muted ? '🔇 静音' : '🔊 声音'}</button>
                            </div>
                        </div>
                        <div id="fold-body-${box.id}" class="fold-body" style="display: ${(currentUser && isExpanded) ? 'block' : 'none'};">
                            <div class="setting-row">
                                <label>下限:</label>
                                <input id="lower-${box.id}" type="number" step="0.1" class="setting-input" value="${box.lower}">
                                <label>预警:</label>
                                <select id="mid_op-${box.id}" class="setting-input" style="width:40px; padding:2px;">
                                    <option value=">" ${box.mid_op === '>' ? 'selected' : ''}>&gt;</option>
                                    <option value="<" ${box.mid_op === '<' ? 'selected' : ''}>&lt;</option>
                                    <option value="=" ${box.mid_op === '=' ? 'selected' : ''}>=</option>
                                </select>
                                <input id="mid-${box.id}" type="number" step="0.1" class="setting-input" value="${box.mid_val}">
                                <label>上限:</label>
                                <input id="upper-${box.id}" type="number" step="0.1" class="setting-input" value="${box.upper}">
                                <button class="btn-action" style="background:#0088cc; padding:2px 8px; margin-left:4px;" onclick="updateLimits(${box.id})">保存</button>
                            </div>
                            <div class="log-title">📊 历史日志</div>
                            <div id="logs-${box.id}" class="log-list">${logsHtml}</div>
                        </div>
                    `;
                } else {
                    const diffEl = document.getElementById('diff-' + box.id);
                    if (diffEl) diffEl.innerHTML = diffHtml;

                    const trendEl = document.getElementById('trend-' + box.id);
                    if (trendEl) trendEl.innerHTML = trendHtml;

                    const valEl = document.getElementById('val-' + box.id);
                    if (valEl) {
                        valEl.className = valClass;
                        valEl.innerText = box.val_text;
                    }

                    const alarmBox = document.getElementById('alarm-btn-box-' + box.id);
                    if (alarmBox) {
                        alarmBox.innerHTML = box.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${box.id})">🚨 消除</button>` : '';
                    }

                    const muteBtn = document.getElementById('mute-btn-' + box.id);
                    if (muteBtn) {
                        muteBtn.className = `btn-action ${box.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}`;
                        muteBtn.innerText = box.is_muted ? '🔇 静音' : '🔊 声音';
                    }

                    const lowerInput = document.getElementById('lower-' + box.id);
                    if (lowerInput && document.activeElement !== lowerInput) lowerInput.value = box.lower;

                    const midOpSelect = document.getElementById('mid_op-' + box.id);
                    if (midOpSelect && document.activeElement !== midOpSelect) midOpSelect.value = box.mid_op || '>';

                    const midInput = document.getElementById('mid-' + box.id);
                    if (midInput && document.activeElement !== midInput) midInput.value = box.mid_val;

                    const upperInput = document.getElementById('upper-' + box.id);
                    if (upperInput && document.activeElement !== upperInput) upperInput.value = box.upper;

                    const logsBox = document.getElementById('logs-' + box.id);
                    if (logsBox) {
                        logsBox.innerHTML = (box.logs || []).map(l => `<div class="log-item">${l}</div>`).join('');
                    }
                }
            });

            const currentIds = boxes.map(b => 'card-' + b.id);
            Array.from(container.children).forEach(child => {
                if (!currentIds.includes(child.id)) {
                    container.removeChild(child);
                }
            });
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const btnMon = document.getElementById('btn-monitor');
                if (btnMon) {
                    if (data.monitoring) {
                        btnMon.innerText = '⏹ 停止监控';
                        btnMon.classList.add('active');
                    } else {
                        btnMon.innerText = '▶ 开始监控';
                        btnMon.classList.remove('active');
                    }
                }

                const btnGri = document.getElementById('btn-grille');
                if (btnGri) {
                    if (data.grille) {
                        btnGri.innerText = '⏹ 停止操作';
                        btnGri.classList.add('active');
                    } else {
                        btnGri.innerText = '▶ 开始操作';
                        btnGri.classList.remove('active');
                    }
                }

                const compareMinInput = document.getElementById('compare-min-input');
                if (compareMinInput && document.activeElement !== compareMinInput) {
                    compareMinInput.value = data.compare_min || 5;
                }

                renderCards(data.boxes || []);
            } catch(e) {}
        }

        updateAuthUI();
        fetchStatus();
        setInterval(fetchStatus, 1000);
    </script>
</body>
</html>
"""


# ==================== Web 服务器线程 ====================
class WebServerThread(QThread):
    action_requested = Signal(str, int, dict)

    def __init__(self, main_win, host='0.0.0.0', port=5000):
        super().__init__()
        self.main_win = main_win
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self.server = None
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @self.app.route('/favicon.ico')
        def favicon():
            return "", 204

        @self.app.route('/api/status')
        def get_status():
            boxes_data = []
            compare_min = getattr(self.main_win, 'compare_interval_min', 5.0)

            for b in self.main_win.boxes:
                val_text = b.lbl_result.text()
                try:
                    val = float(val_text)
                except ValueError:
                    val = None

                past_val = b.get_past_value(compare_min)
                trend = 'none'
                diff = None
                if val is not None and past_val is not None:
                    diff = val - past_val
                    if val > past_val:
                        trend = 'up'
                    elif val < past_val:
                        trend = 'down'

                logs = []
                for i in range(b.list_widget.count()):
                    logs.append(b.list_widget.item(i).text())

                boxes_data.append({
                    'id': b.box_id,
                    'name': b.name,
                    'lower': b.lower,
                    'mid_op': getattr(b, 'mid_op', '>'),
                    'mid_val': b.mid_val,
                    'upper': b.upper,
                    'val': val,
                    'val_text': val_text,
                    'trend': trend,
                    'diff': diff,  # 修改三：向前端传回差值
                    'is_alarm': b.is_alarm,
                    'is_muted': b.is_muted,
                    'logs': logs
                })

            return jsonify({
                'monitoring': self.main_win.monitoring,
                'grille': getattr(self.main_win, 'operating', False),
                'compare_min': compare_min,
                'boxes': boxes_data,
                'users': self.main_win.users
            })

        @self.app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.get_json() or {}
            action = data.get('action')
            box_id = data.get('box_id', -1)
            payload = data.get('data', {})
            self.action_requested.emit(action, box_id, payload)
            return jsonify({'status': 'ok'})

        @self.app.route('/api/login', methods=['POST'])
        def login():
            data = request.get_json() or {}
            username = data.get('username')
            password = data.get('password')
            if self.main_win.users.get(username) == password:
                return jsonify({'status': 'ok', 'username': username})
            return jsonify({'status': 'error', 'message': '用户名或密码错误'}), 401

        @self.app.route('/api/users', methods=['POST'])
        def manage_users():
            data = request.get_json() or {}
            action = data.get('action')
            username = data.get('username')
            password = data.get('password')
            if action in ('add', 'update'):
                if username and password:
                    self.main_win.users[username] = password
                    self.main_win.save_users()
                    return jsonify({'status': 'ok'})
            elif action == 'delete':
                if username in self.main_win.users and username != 'admin':
                    del self.main_win.users[username]
                    self.main_win.save_users()
                    return jsonify({'status': 'ok'})
            return jsonify({'status': 'error', 'message': '操作失败'}), 400

    def run(self):
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        from werkzeug.serving import make_server
        self.server = make_server(self.host, self.port, self.app, threaded=True)
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.shutdown()


# ==================== OCR 异步初始化线程 ====================
class OCRInitThread(QThread):
    ocr_ready = Signal(object)

    def run(self):
        try:
            import ddddocr
            reader = ddddocr.DdddOcr(show_ad=False)
            self.ocr_ready.emit(reader)
        except Exception as e:
            print(f"ddddocr 初始化失败: {e}")
            self.ocr_ready.emit(None)


# ==================== 主控面板窗口 ====================
class GlobalControlPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("中控面板")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.boxes = []
        self.monitoring = False
        self.operating = False
        self.is_editing = False
        self.is_collapsed = False
        self.boxes_panel_hidden = False
        self.reader = None
        self.compare_interval_min = 5.0

        self.config_file = "monitor_config.json"
        self.users_file = "users_config.json"
        
        self.users = self.load_users()
        self.alarm_player = AlarmSoundPlayer()
        self.monitor_thread = None
        self.web_thread = None

        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self._drag_pos = None

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._on_f12_pressed)
        self.f12_listener.start()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.setMaximumWidth(520)

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
            QCheckBox { color: #00ff8c; font-weight: bold; font-size: 11px; }
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

        # ---------- 第 2 排：框体与配置管理 ----------
        self.row2_card = QFrame()
        self.row2_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        self.row2_layout = QHBoxLayout(self.row2_card)
        self.row2_layout.setContentsMargins(8, 5, 8, 5)
        self.row2_layout.setSpacing(6)

        self.btn_add_box = QPushButton("➕ 新增识别框")
        self.btn_add_box.clicked.connect(self._on_add_box_clicked)

        self.btn_edit_pos = QPushButton("✏️ 调整框位置")
        self.btn_edit_pos.setCheckable(True)
        self.btn_edit_pos.clicked.connect(self._toggle_edit_pos)

        self.btn_hide_boxes = QPushButton("🙈 隐藏所有框")
        self.btn_hide_boxes.clicked.connect(self._toggle_hide_boxes)

        self.btn_save_config = QPushButton("💾 保存配置")
        self.btn_save_config.clicked.connect(self.save_config)

        self.btn_load_config = QPushButton("📁 加载配置")
        self.btn_load_config.clicked.connect(self.load_config)

        self.row2_layout.addWidget(self.btn_add_box)
        self.row2_layout.addWidget(self.btn_edit_pos)
        self.row2_layout.addWidget(self.btn_hide_boxes)
        self.row2_layout.addWidget(self.btn_save_config)
        self.row2_layout.addWidget(self.btn_load_config)

        main_layout.addWidget(self.row2_card)

        # ---------- 第 3 排：核心控制 ----------
        self.row3_card = QFrame()
        self.row3_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        self.row3_layout = QHBoxLayout(self.row3_card)
        self.row3_layout.setContentsMargins(8, 5, 8, 5)
        self.row3_layout.setSpacing(6)

        self.btn_start_monitor = QPushButton("▶ 开始监控")
        self.btn_start_monitor.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")
        self.btn_start_monitor.clicked.connect(self._toggle_monitor)

        self.btn_start_grille = QPushButton("▶ 开始操作")
        self.btn_start_grille.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        self.btn_start_grille.clicked.connect(self._toggle_grille)

        self.chk_web = QCheckBox("网页端")
        self.chk_web.setChecked(True)
        self.chk_web.toggled.connect(self._on_web_chk_toggled)

        self.row3_layout.addWidget(self.btn_start_monitor)
        self.row3_layout.addWidget(self.btn_start_grille)
        self.row3_layout.addWidget(self.chk_web)

        main_layout.addWidget(self.row3_card)

        # ---------- 第 4 排：状态与折叠面板 ----------
        self.row4_card = QFrame()
        self.row4_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        self.row4_layout = QHBoxLayout(self.row4_card)
        self.row4_layout.setContentsMargins(8, 5, 8, 5)
        self.row4_layout.setSpacing(6)

        self.lbl_status = QLabel("状态: 就绪")
        self.lbl_status.setStyleSheet("color: #00ff8c; font-weight: bold;")

        self.lbl_f12_tip = QLabel("(按 F12 显示/隐藏面板)")
        self.lbl_f12_tip.setStyleSheet("color: #888888; font-size: 10px;")

        self.btn_collapse = QPushButton("▲ 折叠")
        self.btn_collapse.clicked.connect(self._toggle_collapse)

        self.row4_layout.addWidget(self.lbl_status)
        self.row4_layout.addWidget(self.lbl_f12_tip)
        self.row4_layout.addStretch()
        self.row4_layout.addWidget(self.btn_collapse)

        main_layout.addWidget(self.row4_card)

        # OCR 异步初始化
        self.ocr_init_thread = OCRInitThread()
        self.ocr_init_thread.ocr_ready.connect(self._on_ocr_ready)
        self.ocr_init_thread.start()

        self.load_config()

    def _on_ocr_ready(self, reader):
        self.reader = reader
        if reader:
            self.lbl_status.setText("状态: OCR 就绪")
        else:
            self.lbl_status.setText("状态: OCR 初始化失败")

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=val)

    def _on_count_changed(self, val):
        for box in self.boxes:
            box.set_max_log_count(val)

    def _on_log_interval_changed(self, val):
        for box in self.boxes:
            box.log_interval_min = val

    def _open_ocr_adjust_dialog(self):
        dlg = OCRAdjustDialog(self.ocr_params, self.reader, self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)

    def _on_add_box_clicked(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0: return
            new_id = len(self.boxes) + 1
            box = OverlayRegionWidget(new_id, x, y, w, h, name=f"区域 {new_id}")
            box.delete_requested.connect(self._on_delete_box)
            box.alarm_cleared.connect(self._check_global_alarm)
            box.mute_toggled.connect(self._check_global_alarm)
            box.set_edit_mode(self.is_editing)
            box.set_panel_hidden(self.boxes_panel_hidden)
            box.show()
            self.boxes.append(box)

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _on_delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self._check_global_alarm()

    def _toggle_edit_pos(self):
        self.is_editing = self.btn_edit_pos.isChecked()
        for box in self.boxes:
            box.set_edit_mode(self.is_editing)

    def _toggle_hide_boxes(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        self.btn_hide_boxes.setText("👀 显示所有框" if self.boxes_panel_hidden else "🙈 隐藏所有框")
        for box in self.boxes:
            box.set_panel_hidden(self.boxes_panel_hidden)

    def _toggle_monitor(self):
        if not self.monitoring:
            if not self.boxes:
                self.lbl_status.setText("状态: 无识别框")
                return
            self.monitoring = True
            self.btn_start_monitor.setText("⏹ 停止监控")
            self.btn_start_monitor.setStyleSheet("background-color: #b03a3a; color: white; font-weight: bold;")
            self.lbl_status.setText("状态: 正在监控")

            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(self.boxes, self.spin_interval.value(), self.ocr_params, scale)
            self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.start()
        else:
            self.monitoring = False
            self.btn_start_monitor.setText("▶ 开始监控")
            self.btn_start_monitor.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")
            self.lbl_status.setText("状态: 监控已停止")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None
            self.alarm_player.stop()

    def _toggle_grille(self):
        self.operating = not self.operating
        if self.operating:
            self.btn_start_grille.setText("⏹ 停止操作")
            self.btn_start_grille.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold;")
        else:
            self.btn_start_grille.setText("▶ 开始操作")
            self.btn_start_grille.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")

    def _on_web_chk_toggled(self, checked):
        if checked:
            if not self.web_thread:
                self.web_thread = WebServerThread(self)
                self.web_thread.action_requested.connect(self._handle_web_action)
                self.web_thread.start()
        else:
            if self.web_thread:
                self.web_thread.stop()
                self.web_thread.wait()
                self.web_thread = None

    def _handle_web_action(self, action, box_id, payload):
        if action == 'toggle_monitor':
            self._toggle_monitor()
        elif action == 'toggle_grille':
            self._toggle_grille()
        elif action == 'clear_alarm':
            for b in self.boxes:
                if b.box_id == box_id:
                    b._on_clear_alarm()
                    break
        elif action == 'toggle_mute':
            for b in self.boxes:
                if b.box_id == box_id:
                    b._toggle_mute()
                    break
        elif action == 'set_limits':
            for b in self.boxes:
                if b.box_id == box_id:
                    try:
                        b.spin_lower.setValue(float(payload.get('lower', b.lower)))
                        b.spin_mid.setValue(float(payload.get('mid_val', b.mid_val)))
                        b.spin_upper.setValue(float(payload.get('upper', b.upper)))
                        b.combo_mid_op.setCurrentText(payload.get('mid_op', b.mid_op))
                    except: pass
                    break
        elif action == 'set_compare_min':
            try:
                self.compare_interval_min = float(payload.get('compare_min', 5.0))
            except: pass

    def _on_f12_pressed(self):
        self.is_collapsed = not self.is_collapsed
        self.setVisible(not self.is_collapsed)

    def _toggle_collapse(self):
        self._on_f12_pressed()

    def _on_value_updated(self, box, time_str, val, raw_text):
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            if val > box.upper or val < box.lower:
                box.set_alarm_state(True)
                box.set_warning_state(False)
            elif box.check_mid_condition(val):
                box.set_alarm_state(False)
                box.set_warning_state(True)
            else:
                box.set_alarm_state(False)
                box.set_warning_state(False)
        else:
            box.set_alarm_state(False)
            box.set_warning_state(False)

        self._check_global_alarm()

    def _check_global_alarm(self):
        has_active_alarm = False
        for box in self.boxes:
            if box.is_alarm and not box.is_muted:
                has_active_alarm = True
                break

        if has_active_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def load_users(self):
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass
        return {"admin": "123456"}

    def save_users(self):
        try:
            with open(self.users_file, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except: pass

    def save_config(self):
        data = {
            'interval': self.spin_interval.value(),
            'log_count': self.spin_count.value(),
            'log_interval': self.spin_log_interval.value(),
            'ocr_params': self.ocr_params,
            'compare_interval_min': self.compare_interval_min,
            'boxes': []
        }
        for b in self.boxes:
            data['boxes'].append({
                'id': b.box_id,
                'x': b.capture_x,
                'y': b.capture_y,
                'w': b.capture_w,
                'h': b.capture_h,
                'name': b.name,
                'lower': b.lower,
                'mid_op': b.mid_op,
                'mid_val': b.mid_val,
                'upper': b.upper,
                'decimal_places': getattr(b, 'decimal_places', 0)
            })
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.lbl_status.setText("状态: 配置保存成功")
        except Exception as e:
            self.lbl_status.setText(f"状态: 保存失败({e})")

    def load_config(self):
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.spin_interval.setValue(data.get('interval', 1.0))
            self.spin_count.setValue(data.get('log_count', 30))
            self.spin_log_interval.setValue(data.get('log_interval', 1.0))
            self.ocr_params = data.get('ocr_params', self.ocr_params)
            self.compare_interval_min = data.get('compare_interval_min', 5.0)

            for b in list(self.boxes):
                b.close()
            self.boxes.clear()

            for b_data in data.get('boxes', []):
                box = OverlayRegionWidget(
                    b_data['id'],
                    b_data['x'], b_data['y'], b_data['w'], b_data['h'],
                    name=b_data.get('name', '区域'),
                    lower=b_data.get('lower', 0.0),
                    mid_val=b_data.get('mid_val', 50.0),
                    upper=b_data.get('upper', 100.0),
                    decimal_places=b_data.get('decimal_places', 0),
                    mid_op=b_data.get('mid_op', '>')
                )
                box.delete_requested.connect(self._on_delete_box)
                box.alarm_cleared.connect(self._check_global_alarm)
                box.mute_toggled.connect(self._check_global_alarm)
                box.set_edit_mode(self.is_editing)
                box.set_panel_hidden(self.boxes_panel_hidden)
                box.show()
                self.boxes.append(box)

            self.lbl_status.setText("状态: 配置加载成功")
        except Exception as e:
            self.lbl_status.setText(f"状态: 加载失败({e})")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def closeEvent(self, event):
        if self.f12_listener:
            self.f12_listener.stop()
            self.f12_listener.wait()
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        if self.web_thread:
            self.web_thread.stop()
            self.web_thread.wait()
        for box in self.boxes:
            box.close()
        event.accept()


# ==================== 主入口函数 ====================
def main():
    app = QApplication(sys.argv)
    panel = GlobalControlPanel()
    panel.move(100, 100)
    panel.show()

    if panel.chk_web.isChecked():
        panel._on_web_chk_toggled(True)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
