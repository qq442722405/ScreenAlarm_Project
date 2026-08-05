import sys
import json
import os
import time
import re
import threading
import ctypes
import socket
import urllib.request
from io import BytesIO
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
    from flask import Flask, jsonify, render_template_string, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


# ==================== 获取本机局域网所有 IPv4 地址 ====================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_all_local_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        addresses = socket.getaddrinfo(hostname, None)
        for addr in addresses:
            ip = addr[4][0]
            if ':' not in ip and not ip.startswith('127.'):
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    if not ips:
        default_ip = get_local_ip()
        if default_ip:
            ips.append(default_ip)
    if "127.0.0.1" not in ips:
        ips.append("127.0.0.1")
    return ips


# ==================== 二维码生成工具函数 ====================
def generate_qr_pixmap(url):
    """优先使用 qrcode 库生成二维码，若未安装则通过网络 API 或绘图备用生成"""
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=5, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format='PNG')
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        return pixmap
    except Exception:
        try:
            api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={url}"
            req = urllib.request.urlopen(api_url, timeout=3)
            data = req.read()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            return pixmap
        except Exception:
            pixmap = QPixmap(180, 180)
            pixmap.fill(Qt.white)
            painter = QPainter(pixmap)
            painter.setPen(Qt.black)
            font = QFont()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter | Qt.TextWordWrap, f"扫码访问:\n{url}")
            painter.end()
            return pixmap


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


# ==================== 日志独立弹窗对话框 ====================
class OverlayLogDialog(QDialog):
    def __init__(self, box_name, list_items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📜 记录日志 - {box_name}")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(260, 280)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 4px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 11px;
            }
            QListWidget::item { padding: 2px 4px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
        """)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for item in list_items:
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)


# ==================== 5. 悬浮识别选框窗口 ====================
class OverlayRegionWidget(QWidget):
    delete_requested = Signal(object)
    alarm_cleared = Signal()
    mute_toggled = Signal()
    config_changed = Signal()

    def __init__(self, box_id, x, y, w, h, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, warning_op=">", parent=None):
        super().__init__(None)
        self.box_id = box_id
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(1, w)
        self.capture_h = max(1, h)

        self.name = name
        self.lower = lower
        self.mid_val = mid_val  # 预警值
        self.warning_op = warning_op if warning_op in [">", "<", "="] else ">" # 需求一：预警运算符 (默认大于)
        self.upper = upper
        self.decimal_places = decimal_places

        self.log_interval_min = 1.0
        self.last_log_time = 0.0
        self.max_log_count = 30

        self.is_alarm = False
        self.is_warning = False  # 预警标记
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

        # ---------- 排版 1：标题与当前值 ----------
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

        # ---------- 排版 2：下限与上限 ----------
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

        # ---------- 排版 3：预警值与比较运算符 (需求一) ----------
        self.row3_container = QWidget()
        row3_layout = QHBoxLayout(self.row3_container)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(3)

        self.lbl_mid = QLabel("预警值:")
        self.lbl_mid.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold;")

        # 需求一：预警符号选择下拉框
        self.combo_op = QComboBox()
        self.combo_op.addItems([">", "<", "="])
        self.combo_op.setCurrentText(self.warning_op)
        self.combo_op.setFixedSize(38, 20)
        self.combo_op.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.combo_op.currentTextChanged.connect(self._on_op_changed)

        self.spin_mid = CleanDoubleSpinBox()
        self.spin_mid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_mid.setAlignment(Qt.AlignCenter)
        self.spin_mid.setRange(-99999.0, 99999.0)
        self.spin_mid.setValue(self.mid_val)
        self.spin_mid.setFixedSize(45, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px;")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.combo_op)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addStretch()
        panel_layout.addWidget(self.row3_container)

        # ---------- 排版 4：静音、小数点、日志按钮、消除报警 ----------
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
        self.btn_log.setFixedHeight(20)
        self.btn_log.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: #00ff8c; border: none; border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_log.clicked.connect(self._open_log_dialog)

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        row4_layout.addWidget(self.btn_mute)
        row4_layout.addWidget(self.lbl_dec)
        row4_layout.addWidget(self.spin_dec)
        row4_layout.addWidget(self.btn_log)
        row4_layout.addWidget(self.btn_clear_alarm)
        row4_layout.addStretch()
        panel_layout.addWidget(self.row4_container)

        self.list_widget = QListWidget()  # 内部存储日志数据
        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _open_log_dialog(self):
        items = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        dlg = OverlayLogDialog(self.name, items, parent=self)
        dlg.exec()

    def _on_lower_changed(self, val):
        self.lower = val
        self.config_changed.emit()

    def _on_op_changed(self, text):
        self.warning_op = text
        self.config_changed.emit()

    def _on_mid_changed(self, val):
        self.mid_val = val
        self.config_changed.emit()

    def _on_upper_changed(self, val):
        self.upper = val
        self.config_changed.emit()

    def _on_dec_changed(self, val):
        self.decimal_places = val
        self.config_changed.emit()

    def _on_title_changed(self, text):
        self.name = text
        self.lbl_title.setText(text)
        self.config_changed.emit()

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            dp = getattr(self, 'decimal_places', 2)
            self.lbl_result.setText(f"{val:.{dp}f}")
            if val > self.upper or val < self.lower:
                self.lbl_result.setStyleSheet("color: #ff4d4d; font-size: 11px; font-weight: bold; margin-left: 2px;")
                self.is_warning = False
            else:
                # 需求一：判断预警条件 (> < =)
                op = getattr(self, 'warning_op', '>')
                is_warn = False
                if op == '>' and val > self.mid_val:
                    is_warn = True
                elif op == '<' and val < self.mid_val:
                    is_warn = True
                elif op == '=' and abs(val - self.mid_val) < 1e-5:
                    is_warn = True

                self.is_warning = is_warn
                if is_warn:
                    self.lbl_result.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold; margin-left: 2px;")
                else:
                    self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold; margin-left: 2px;")
        else:
            disp = f"({raw_text})" if raw_text else "--"
            self.lbl_result.setText(f"{disp}")
            self.lbl_result.setStyleSheet("color: #ff6666; font-size: 11px; font-weight: bold; margin-left: 2px;")
            self.is_warning = False
        self.update()

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
            self.btn_log.setVisible(True)
            self.btn_clear_alarm.setVisible(self.is_alarm)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.combo_op.setEnabled(self.is_editing)
            self.spin_mid.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        total_w = max(self.capture_w, 210)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
            panel_h = 105

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
        self.config_changed.emit()

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

    def mouseReleaseEvent(self, event):
        if self.is_editing:
            self.config_changed.emit()

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
        elif self.is_warning:  # 预警状态变成黄色
            pen = QPen(QColor(255, 200, 0), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 200, 0, 25))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 25))

        painter.drawRect(box_rect.adjusted(1, 1, -1, -1))


# ==================== 网页服务与二维码配置对话框 (需求二：合并按钮，默认启动) ====================
class WebServiceDialog(QDialog):
    def __init__(self, main_panel, parent=None):
        super().__init__(parent)
        self.main_panel = main_panel
        self.setWindowTitle("🌐 网页服务与二维码设置")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(320, 360)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #e0e0e0; font-size: 12px; font-weight: bold; }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8); color: white;
                border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px;
                padding: 6px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
            QComboBox {
                background-color: rgba(26, 26, 38, 0.8); color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px;
                padding: 4px; font-weight: bold;
            }
        """)

        layout = QVBoxLayout(self)

        # 选择 IP
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("选择IP:"))
        self.combo_ip = QComboBox()
        self.combo_ip.addItems(get_all_local_ips())
        self.combo_ip.currentIndexChanged.connect(self._update_qr)
        ip_layout.addWidget(self.combo_ip)
        layout.addLayout(ip_layout)

        # 需求二：启动/停止服务合并为一个按钮
        btn_layout = QHBoxLayout()
        self.btn_toggle = QPushButton("▶ 启动服务")
        self.btn_toggle.setFixedHeight(34)
        self.btn_toggle.clicked.connect(self._toggle_service)
        btn_layout.addWidget(self.btn_toggle)
        layout.addLayout(btn_layout)

        # 二维码显示区
        self.lbl_qr = QLabel()
        self.lbl_qr.setFixedSize(180, 180)
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setStyleSheet("border: 1px solid rgba(255,255,255,0.2); background-color: white; border-radius: 6px;")
        
        qr_box = QHBoxLayout()
        qr_box.addStretch()
        qr_box.addWidget(self.lbl_qr)
        qr_box.addStretch()
        layout.addLayout(qr_box)

        # 访问链接显示
        self.lbl_url = QLabel("http://127.0.0.1:5000")
        self.lbl_url.setAlignment(Qt.AlignCenter)
        self.lbl_url.setStyleSheet("color: #00ff8c; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.lbl_url)

        self._update_status_ui()
        self._update_qr()

    def _toggle_service(self):
        is_running = self.main_panel.web_thread is not None and self.main_panel.web_thread.isRunning()
        if is_running:
            self.main_panel.stop_web_service()
        else:
            selected_ip = self.combo_ip.currentText() or "127.0.0.1"
            self.main_panel.start_web_service_with_ip(selected_ip)
        self._update_status_ui()
        self._update_qr()

    def _update_status_ui(self):
        is_running = self.main_panel.web_thread is not None and self.main_panel.web_thread.isRunning()
        if is_running:
            self.btn_toggle.setText("⏹ 停止服务")
            self.btn_toggle.setStyleSheet("background-color: #b03a3a; color: white;")
        else:
            self.btn_toggle.setText("▶ 启动服务")
            self.btn_toggle.setStyleSheet("background-color: #2e9a58; color: white;")

    def _update_qr(self):
        selected_ip = self.combo_ip.currentText() or "127.0.0.1"
        url = f"http://{selected_ip}:5000"
        self.lbl_url.setText(url)
        pixmap = generate_qr_pixmap(url)
        self.lbl_qr.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))


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


# ==================== 8. Flask 网页/手机端 WEB 交互界面 ====================
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

        .header { display: flex; flex-direction: column; padding: 10px 14px; background: #1a1a26; border-radius: 10px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); gap: 8px; }
        .header-top-row { display: flex; justify-content: space-between; align-items: center; width: 100%; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; }
        .status { font-size: 11px; color: #aaa; font-weight: bold; }

        .header-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; width: 100%; }
        .btn-top { background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }

        .btn-fold-tool { background: rgba(255,255,255,0.1); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }
        .btn-fold-tool:active { background: rgba(0,255,140,0.2); }

        .login-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 6px; width: 100%; font-size: 12px; }

        /* 卡片容器与视图模式 */
        #cards-container.list-view { display: flex; flex-direction: column; gap: 10px; }
        
        #cards-container.grid-view { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
        #cards-container.grid-view .card { margin-bottom: 0; height: 130px; display: flex; flex-direction: column; justify-content: space-between; padding: 10px; text-align: center; }
        #cards-container.grid-view .card .val-text { font-size: 26px; }
        #cards-container.grid-view .card .fold-body { display: none !important; }

        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); transition: all 0.2s; user-select: none; }
        .card.dragging { opacity: 0.4; border: 2px dashed #00ff8c; }
        .card[draggable="true"] { cursor: grab; }
        .card[draggable="true"]:active { cursor: grabbing; }

        .card.alarm { border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); animation: blink 1s infinite alternate; }
        @keyframes blink { from { box-shadow: 0 0 5px rgba(255,77,77,0.3); } to { box-shadow: 0 0 15px rgba(255,77,77,0.8); } }

        .card.warning { border: 2px solid #ffaa00; background: rgba(255, 170, 0, 0.08); }

        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; }
        .card-title-box { display: flex; align-items: center; gap: 8px; cursor: pointer; flex-grow: 1; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .value-box { text-align: center; margin: 8px 0; }
        .val-text { font-size: 32px; font-weight: bold; color: #00ff8c; font-family: monospace; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 45px; text-align: center; font-size: 11px; }

        .log-title { margin-top: 6px; font-size: 11px; color: #888; font-weight: bold; }
        .log-list { margin-top: 4px; background: rgba(0,0,0,0.4); border-radius: 6px; padding: 6px 8px; font-size: 11px; font-family: monospace; height: 110px; overflow-y: auto; color: #00ff8c; }
        .log-list::-webkit-scrollbar { width: 4px; }
        .log-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 2px; }
        .log-item { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); white-space: nowrap; }

        /* 需求三：微型排序图标 */
        .sort-btns { display: inline-flex; flex-direction: row; gap: 2px; opacity: 0.4; transition: opacity 0.2s; margin-left: 4px; }
        .sort-btns:hover { opacity: 1; }
        .sort-btn-item { cursor: pointer; color: #aaa; font-size: 10px; padding: 0 2px; user-select: none; }
        .sort-btn-item:hover { color: #00ff8c; }

        /* 模态框弹窗样式 */
        .modal-overlay { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }
        .modal-content { background: #1a1a26; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; width: 90%; max-width: 420px; padding: 16px; color: #e0e0e0; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; }
        .modal-close { cursor: pointer; color: #ff4d4d; font-weight: bold; font-size: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-top-row">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <div class="title">📱 中控数据面板</div>
                    <span id="header-fold-btn" onclick="toggleHeaderFold()" style="cursor: pointer; font-size: 14px; color: #00ff8c;" title="收起/展开控制区">🔼</span>
                </div>
                <div id="status" class="status">初始化...</div>
            </div>
            <div id="header-actions" class="header-actions">
                <button id="btn-toggle-all" class="btn-fold-tool" onclick="toggleCollapseAll()">📂 展开</button>
                <button id="btn-layout" class="btn-fold-tool" onclick="toggleLayoutView()">🔲 方块视图</button>

                <!-- 登录按钮 -->
                <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                    <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
                </div>
                <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                    <span id="current-username" style="color:#00ff8c; font-size:12px; font-weight:bold;">👤 已登录</span>
                    <button class="btn-sound" style="background:#e65100; color:white; border:none;" onclick="openUserMgmtModal()">⚙️ 用户管理</button>
                    <button class="btn-sound" style="background:#555; color:white; border:none;" onclick="handleLogout()">🚪 退出</button>
                </div>

                <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 声音</button>
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div id="cards-container" class="list-view"></div>
    </div>

    <!-- 登录弹窗 -->
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
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">🔑 修改当前密码 (<span id="modal-curr-user" style="color:#00ff8c;"></span>)</div>
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
        const collapsedMap = {};
        let isAllCollapsed = true;
        let isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
        let currentUser = localStorage.getItem('currentUser') || '';
        let lastLoggedInState = null;
        let webSoundEnabled = true;
        let audioCtx = null;
        let alarmTimer = null;
        let cachedBoxes = [];
        let isGridView = localStorage.getItem('isGridView') === 'true';
        let customBoxOrder = JSON.parse(localStorage.getItem('customBoxOrder') || '[]');
        let draggedItem = null;
        let isHeaderFolded = false;

        // 需求三：向上/下移动调整位置
        function moveBoxOrder(boxId, dir) {
            const container = document.getElementById('cards-container');
            const currentIds = Array.from(container.children).map(el => parseInt(el.id.replace('card-', '')));
            const idx = currentIds.indexOf(boxId);
            if (idx === -1) return;
            const targetIdx = idx + dir;
            if (targetIdx < 0 || targetIdx >= currentIds.length) return;

            const temp = currentIds[idx];
            currentIds[idx] = currentIds[targetIdx];
            currentIds[targetIdx] = temp;

            customBoxOrder = currentIds;
            localStorage.setItem('customBoxOrder', JSON.stringify(customBoxOrder));

            forceReRenderCards();
            refreshData();
        }

        function toggleHeaderFold() {
            isHeaderFolded = !isHeaderFolded;
            const actionsEl = document.getElementById('header-actions');
            const foldBtn = document.getElementById('header-fold-btn');
            if (isHeaderFolded) {
                if (actionsEl) actionsEl.style.display = 'none';
                if (foldBtn) foldBtn.innerText = '🔽';
            } else {
                if (actionsEl) actionsEl.style.display = 'flex';
                if (foldBtn) foldBtn.innerText = '🔼';
            }
        }

        function openLoginModal() {
            document.getElementById('login-modal').style.display = 'flex';
        }

        function closeLoginModal() {
            document.getElementById('login-modal').style.display = 'none';
        }

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

        function toggleLayoutView() {
            isGridView = !isGridView;
            localStorage.setItem('isGridView', isGridView);
            applyLayoutView();
        }

        function applyLayoutView() {
            const container = document.getElementById('cards-container');
            const btnLayout = document.getElementById('btn-layout');
            if (isGridView) {
                container.className = 'grid-view';
                btnLayout.innerText = '☰ 长条视图';
            } else {
                container.className = 'list-view';
                btnLayout.innerText = '🔲 方块视图';
            }
            refreshData();
        }

        async function handleLogin() {
            const u = document.getElementById('login-user').value.trim();
            const p = document.getElementById('login-pass').value.trim();
            if (!u || !p) {
                alert('请输入账号和密码！');
                return;
            }
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
            } catch(e) {
                alert('请求异常，请重试！');
            }
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

        function closeUserMgmtModal() {
            document.getElementById('user-modal').style.display = 'none';
        }

        async function handleChangePassword() {
            const oldP = document.getElementById('old-pass').value.trim();
            const newP = document.getElementById('new-pass').value.trim();
            if (!oldP || !newP) {
                alert('请填写旧密码和新密码！');
                return;
            }
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
            } catch(e) {
                alert('修改密码异常！');
            }
        }

        async function handleAddUser() {
            const u = document.getElementById('new-user-name').value.trim();
            const p = document.getElementById('new-user-pass').value.trim();
            if (!u || !p) {
                alert('请输入新账号和新密码！');
                return;
            }
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
            } catch(e) {
                alert('添加用户异常！');
            }
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
                if (data.success) {
                    loadUserList();
                }
            } catch(e) {
                alert('删除用户异常！');
            }
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
                            ${u !== 'admin' ? `<button class="btn-action" style="background:#ff4d4d; color:white;" onclick="handleDeleteUser('${u}')">删除</button>` : '<span style="color:#888; font-size:11px;">(默认管理员)</span>'}
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="color:#888; font-size:11px;">暂无其他用户</div>';
                }
            } catch(e) {
                console.error("加载用户列表失败:", e);
            }
        }

        function forceReRenderCards() {
            const container = document.getElementById('cards-container');
            if (container) container.innerHTML = '';
        }

        function initAudio() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
        }
        document.addEventListener('click', initAudio, { once: false });

        function toggleCollapseAll() {
            isAllCollapsed = !isAllCollapsed;
            cachedBoxes.forEach(b => {
                collapsedMap[b.id] = isAllCollapsed;
            });
            const btn = document.getElementById('btn-toggle-all');
            if (btn) {
                btn.innerText = isAllCollapsed ? "📂 展开" : "📁 收起";
            }
            refreshData();
        }

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            const btn = document.getElementById('btn-sound');
            if (webSoundEnabled) {
                btn.innerText = "🔊 声音";
                btn.style.color = "#00ff8c";
            } else {
                btn.innerText = "🔇 静音";
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
            } catch(e) {
                console.error("操作失败:", e);
            }
        }

        function toggleFold(boxId) {
            collapsedMap[boxId] = !collapsedMap[boxId];
            refreshData();
        }

        // 需求一：包含预警运算符保存
        function saveLimits(boxId) {
            const lowerVal = parseFloat(document.getElementById(`input-lower-${boxId}`).value);
            const midVal = parseFloat(document.getElementById(`input-mid-${boxId}`).value);
            const upperVal = parseFloat(document.getElementById(`input-upper-${boxId}`).value);
            const opVal = document.getElementById(`select-op-${boxId}`).value;
            if (!isNaN(lowerVal) && !isNaN(midVal) && !isNaN(upperVal)) {
                postAction('set_limits', boxId, { lower: lowerVal, mid_val: midVal, upper: upperVal, warning_op: opVal });
            } else {
                alert("请输入有效的数值！");
            }
        }

        function formatTwoHourCompare(b, currentTimeStr) {
            const currVal = parseFloat(b.value);
            const dp = b.decimal_places !== undefined ? b.decimal_places : 2;
            
            if (isNaN(currVal) || !b.logs || b.logs.length === 0 || !currentTimeStr) {
                return '<span style="font-size:11px; color:#666;">(--)</span>';
            }

            function timeToSec(tStr) {
                const p = tStr.split(':').map(Number);
                return (p[0] || 0) * 3600 + (p[1] || 0) * 60 + (p[2] || 0);
            }

            const nowSec = timeToSec(currentTimeStr);
            let bestVal = null;
            let minErr = Infinity;

            for (let log of b.logs) {
                const m = log.match(/\[(\d{2}:\d{2}:\d{2})\]\s*(-?\d+(?:\.\d+)?)/);
                if (m) {
                    const logSec = timeToSec(m[1]);
                    const logVal = parseFloat(m[2]);
                    if (isNaN(logVal)) continue;

                    let elapsed = nowSec - logSec;
                    if (elapsed < 0) elapsed += 86400;

                    const err = Math.abs(elapsed - 7200);
                    if (err < minErr && elapsed >= 900) {
                        minErr = err;
                        bestVal = logVal;
                    }
                }
            }

            if (bestVal === null) {
                return '<span style="font-size:11px; color:#666;">(--)</span>';
            }

            const diff = currVal - bestVal;
            let diffStr = (diff >= 0 ? '+' : '') + diff.toFixed(dp);
            let color = '#888';
            let arrow = '→';

            if (diff > 0) {
                color = '#ff4d4d';
                arrow = '↑';
            } else if (diff < 0) {
                color = '#00ff8c';
                arrow = '↓';
            }

            return `<span style="font-size:11px; color:#aaa;" title="历史数值对比 (${bestVal.toFixed(dp)})">` +
                   `${bestVal.toFixed(dp)} <span style="color:${color}; font-weight:bold;">(${arrow}${diffStr})</span>` +
                   `</span>`;
        }

        function attachDragEvents(cardEl, boxId) {
            if (!isLoggedIn) {
                cardEl.removeAttribute('draggable');
                cardEl.ondragstart = null;
                cardEl.ondragover = null;
                cardEl.ondrop = null;
                cardEl.ondragend = null;
                return;
            }

            cardEl.setAttribute('draggable', 'true');

            cardEl.ondragstart = (e) => {
                draggedItem = cardEl;
                cardEl.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            };

            cardEl.ondragover = (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            };

            cardEl.ondrop = (e) => {
                e.preventDefault();
                if (draggedItem && draggedItem !== cardEl) {
                    const container = document.getElementById('cards-container');
                    const children = Array.from(container.children);
                    const draggedIdx = children.indexOf(draggedItem);
                    const targetIdx = children.indexOf(cardEl);

                    if (draggedIdx < targetIdx) {
                        container.insertBefore(draggedItem, cardEl.nextSibling);
                    } else {
                        container.insertBefore(draggedItem, cardEl);
                    }

                    const newOrder = Array.from(container.children).map(el => parseInt(el.id.replace('card-', '')));
                    customBoxOrder = newOrder;
                    localStorage.setItem('customBoxOrder', JSON.stringify(customBoxOrder));
                }
            };

            cardEl.ondragend = () => {
                if (draggedItem) {
                    draggedItem.classList.remove('dragging');
                    draggedItem = null;
                }
            };
        }

        function renderCardDOM(cardEl, b, isCollapsed, isWarning, currentTimeStr) {
            const expectedState = isGridView ? 'grid' : String(isCollapsed);
            const currentFoldState = cardEl.getAttribute('data-collapsed');
            const stateChanged = (currentFoldState !== expectedState);

            let valColor = '#00ff8c';
            if (b.is_alarm) {
                valColor = '#ff4d4d';
            } else if (isWarning) {
                valColor = '#ffaa00';
            }

            const compareHtml = formatTwoHourCompare(b, currentTimeStr);
            attachDragEvents(cardEl, b.id);

            // 需求三：微型排序按钮 HTML
            const sortHtml = `<span class="sort-btns" onclick="event.stopPropagation();">
                <span class="sort-btn-item" onclick="moveBoxOrder(${b.id}, -1)" title="上移">▲</span>
                <span class="sort-btn-item" onclick="moveBoxOrder(${b.id}, 1)" title="下移">▼</span>
            </span>`;

            if (stateChanged) {
                cardEl.setAttribute('data-collapsed', expectedState);
                
                if (isGridView) {
                    cardEl.innerHTML = `
                        <div class="card-header" style="cursor:pointer; justify-content:space-between; width:100%;">
                            <span class="card-title" onclick="toggleFold(${b.id})" style="text-align:center; flex:1;">${b.name}</span>
                            ${sortHtml}
                        </div>
                        <div class="value-box" style="flex:1; display:flex; align-items:center; justify-content:center; margin:0;">
                            <div class="val-text" id="grid-val-${b.id}" style="font-size:26px; color:${valColor};">${b.value}</div>
                        </div>
                        <div style="text-align:center; font-size:11px;" id="grid-diff-${b.id}">
                            ${compareHtml}
                        </div>
                    `;
                    return;
                } else if (isCollapsed) {
                    cardEl.innerHTML = `
                        <div class="card-header" style="cursor:pointer; padding: 2px 0;">
                            <div class="card-title-box" onclick="toggleFold(${b.id})">
                                <span class="card-title">${b.name}</span>
                            </div>
                            <div style="display: flex; align-items: center; gap: 4px;">
                                <span id="collapsed-diff-${b.id}">${compareHtml}</span>
                                <span id="collapsed-val-${b.id}" style="font-size: 15px; font-weight: bold; font-family: monospace; color: ${valColor};">${b.value}</span>
                                ${sortHtml}
                                <span onclick="toggleFold(${b.id})" style="font-size:12px; color:#888;">▶</span>
                            </div>
                        </div>
                    `;
                    return;
                } else {
                    let logsHtml = (b.logs && b.logs.length > 0)
                        ? b.logs.map(l => `<div class="log-item">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';

                    cardEl.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box" onclick="toggleFold(${b.id})">
                                <span class="card-title">${b.name}</span>
                                ${sortHtml}
                                <span style="font-size:12px; color:#888;">▼</span>
                            </div>
                            <div style="display: flex; gap: 6px; align-items: center;" id="action-btns-${b.id}">
                            </div>
                        </div>
                        <div class="value-box">
                            <div class="val-text" id="val-text-${b.id}">${b.value}</div>
                        </div>
                        <div class="fold-body">
                            <div class="setting-row" id="setting-row-${b.id}">
                                <label>下限:</label>
                                <input id="input-lower-${b.id}" class="setting-input" type="number" step="0.1" value="${b.lower}">
                                <label>预警值:</label>
                                <select id="select-op-${b.id}" class="setting-input" style="width:36px; padding:0;">
                                    <option value=">" ${b.warning_op === '>' ? 'selected' : ''}>&gt;</option>
                                    <option value="<" ${b.warning_op === '<' ? 'selected' : ''}>&lt;</option>
                                    <option value="=" ${b.warning_op === '=' ? 'selected' : ''}>=</option>
                                </select>
                                <input id="input-mid-${b.id}" class="setting-input" type="number" step="0.1" value="${b.mid_val}">
                                <label>上限:</label>
                                <input id="input-upper-${b.id}" class="setting-input" type="number" step="0.1" value="${b.upper}">
                                <button class="btn-action" style="background:#0088cc; color:white; margin-left:auto;" onclick="saveLimits(${b.id})">💾 保存</button>
                            </div>
                            <div class="log-title">📜 历史日志:</div>
                            <div class="log-list" id="log-list-${b.id}">${logsHtml}</div>
                        </div>
                    `;
                }
            }

            if (isGridView) {
                const gValEl = document.getElementById(`grid-val-${b.id}`);
                if (gValEl) {
                    gValEl.innerText = b.value;
                    if (b.is_alarm) {
                        gValEl.className = 'val-text alarm-text';
                    } else if (isWarning) {
                        gValEl.className = 'val-text warning-text';
                    } else {
                        gValEl.className = 'val-text';
                    }
                }
                const gDiffEl = document.getElementById(`grid-diff-${b.id}`);
                if (gDiffEl) {
                    gDiffEl.innerHTML = compareHtml;
                }
            } else if (isCollapsed) {
                const cValEl = document.getElementById(`collapsed-val-${b.id}`);
                if (cValEl) {
                    cValEl.innerText = b.value;
                    cValEl.style.color = valColor;
                }
                const cDiffEl = document.getElementById(`collapsed-diff-${b.id}`);
                if (cDiffEl) {
                    cDiffEl.innerHTML = compareHtml;
                }
            } else {
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
                    const opSelect = document.getElementById(`select-op-${b.id}`);
                    const upperInput = document.getElementById(`input-upper-${b.id}`);

                    if (lowerInput && document.activeElement !== lowerInput) lowerInput.value = b.lower;
                    if (midInput && document.activeElement !== midInput) midInput.value = b.mid_val;
                    if (opSelect && document.activeElement !== opSelect) opSelect.value = b.warning_op || '>';
                    if (upperInput && document.activeElement !== upperInput) upperInput.value = b.upper;
                }

                const logListEl = document.getElementById(`log-list-${b.id}`);
                if (logListEl) {
                    let logsHtml = (b.logs && b.logs.length > 0)
                        ? b.logs.map(l => `<div class="log-item">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';
                    logListEl.innerHTML = logsHtml;
                }
            }
        }

        async function refreshData() {
            try {
                updateLoginUI();

                if (lastLoggedInState !== isLoggedIn) {
                    lastLoggedInState = isLoggedIn;
                    forceReRenderCards();
                }

                const res = await fetch('/api/data');
                const data = await res.json();

                const statusEl = document.getElementById('status');
                if (statusEl) statusEl.innerText = data.time;

                const btnMonitor = document.getElementById('btn-monitor');
                if (data.monitoring) {
                    btnMonitor.className = 'btn-top active';
                    btnMonitor.innerText = '⏹ 停止监控';
                } else {
                    btnMonitor.className = 'btn-top';
                    btnMonitor.innerText = '▶ 开始监控';
                }

                const btnGrille = document.getElementById('btn-grille');
                if (data.grille_running) {
                    btnGrille.className = 'btn-top btn-grille active';
                    const m = Math.floor(data.grille_cd / 60);
                    const s = Math.floor(data.grille_cd % 60);
                    const timeStr = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
                    btnGrille.innerText = `⏹ 停止操作 (${timeStr})`;
                } else {
                    btnGrille.className = 'btn-top btn-grille';
                    btnGrille.innerText = '▶ 开始操作';
                }

                const container = document.getElementById('cards-container');

                if (!data.boxes || data.boxes.length === 0) {
                    container.innerHTML = '<div style="text-align:center; padding: 40px; color: #666;">未添加监控选框</div>';
                    stopWebAlarmSound();
                    return;
                }

                cachedBoxes = data.boxes;
                
                let sortedBoxes = [...data.boxes];
                if (customBoxOrder && customBoxOrder.length > 0) {
                    sortedBoxes.sort((a, b) => {
                        let idxA = customBoxOrder.indexOf(a.id);
                        let idxB = customBoxOrder.indexOf(b.id);
                        if (idxA === -1) idxA = 999;
                        if (idxB === -1) idxB = 999;
                        return idxA - idxB;
                    });
                }

                let hasAnyWebAlarm = false;

                sortedBoxes.forEach(b => {
                    if (collapsedMap[b.id] === undefined) {
                        collapsedMap[b.id] = true;
                    }

                    if (b.is_alarm && !b.is_muted) {
                        hasAnyWebAlarm = true;
                    }

                    const numVal = parseFloat(b.value);
                    const op = b.warning_op || '>';
                    let isWarning = false;
                    if (!b.is_alarm && !isNaN(numVal)) {
                        if (op === '>' && numVal > b.mid_val) isWarning = true;
                        else if (op === '<' && numVal < b.mid_val) isWarning = true;
                        else if (op === '=' && Math.abs(numVal - b.mid_val) < 0.00001) isWarning = true;
                    }

                    let cardEl = document.getElementById(`card-${b.id}`);
                    if (!cardEl) {
                        cardEl = document.createElement('div');
                        cardEl.id = `card-${b.id}`;
                        container.appendChild(cardEl);
                    }

                    const isCollapsed = collapsedMap[b.id];
                    
                    if (b.is_alarm) {
                        cardEl.className = 'card alarm';
                    } else if (isWarning) {
                        cardEl.className = 'card warning';
                    } else {
                        cardEl.className = 'card';
                    }

                    renderCardDOM(cardEl, b, isCollapsed, isWarning, data.time);
                });

                triggerAlarmSoundLoop(hasAnyWebAlarm);

            } catch(e) {
                console.error("加载失败:", e);
            }
        }

        applyLayoutView();
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

        @app.route('/favicon.ico')
        def favicon():
            script_dir = os.path.dirname(os.path.abspath(__file__))
            return send_from_directory(script_dir, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

        @app.route('/api/login', methods=['POST'])
        def api_login():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            p = data.get('password', '').strip()
            users = self.main_panel.users
            if u in users and users[u] == p:
                return jsonify({'success': True, 'username': u})
            return jsonify({'success': False, 'message': '账号或密码错误！'})

        @app.route('/api/users/list', methods=['GET'])
        def api_users_list():
            return jsonify({'users': list(self.main_panel.users.keys())})

        @app.route('/api/users/add', methods=['POST'])
        def api_users_add():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            p = data.get('password', '').strip()
            if not u or not p:
                return jsonify({'success': False, 'message': '账号或密码不能为空！'})
            if u in self.main_panel.users:
                return jsonify({'success': False, 'message': '该账号已存在！'})
            self.main_panel.users[u] = p
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '新增用户成功！'})

        @app.route('/api/users/delete', methods=['POST'])
        def api_users_delete():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            if u not in self.main_panel.users:
                return jsonify({'success': False, 'message': '用户不存在！'})
            if u == 'admin':
                return jsonify({'success': False, 'message': '默认管理员 admin 不可删除！'})
            del self.main_panel.users[u]
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '用户已删除！'})

        @app.route('/api/users/change_password', methods=['POST'])
        def api_users_change_password():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            old_p = data.get('old_password', '').strip()
            new_p = data.get('new_password', '').strip()
            if u not in self.main_panel.users:
                return jsonify({'success': False, 'message': '用户不存在！'})
            if self.main_panel.users[u] != old_p:
                return jsonify({'success': False, 'message': '原密码错误！'})
            if not new_p:
                return jsonify({'success': False, 'message': '新密码不能为空！'})
            self.main_panel.users[u] = new_p
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '密码修改成功！'})

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
                    'warning_op': getattr(b, 'warning_op', '>'), # 需求一：返回预警运算符
                    'upper': b.upper,
                    'decimal_places': getattr(b, 'decimal_places', 2),
                    'is_alarm': b.is_alarm,
                    'is_muted': b.is_muted,
                    'logs': logs
                })

            grille_running = bool(self.main_panel.grille_thread and self.main_panel.grille_thread.isRunning())

            return jsonify({
                'monitoring': self.main_panel.monitoring,
                'monitor_cd': getattr(self.main_panel, 'curr_monitor_cd', 0.0),
                'grille_running': grille_running,
                'grille_cd': getattr(self.main_panel, 'curr_grille_cd', 0.0),
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
        self.btn_toggle_hide.clicked.connect(self._toggle_hide)
        row2_extra_layout.addWidget(self.btn_toggle_hide)

        self.btn_web_config = QPushButton("🌐 网页服务")
        self.btn_web_config.setFixedHeight(26)
        self.btn_web_config.setStyleSheet("background-color: rgba(0, 136, 204, 0.6); color: white; border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")
        self.btn_web_config.clicked.connect(self._open_web_service_dialog)
        row2_extra_layout.addWidget(self.btn_web_config)

        self.chk_edit = QCheckBox("✏ 编辑模式")
        self.chk_edit.stateChanged.connect(self._on_edit_toggled)
        row2_extra_layout.addWidget(self.chk_edit)

        self.btn_add_box = QPushButton("➕ 添加选框")
        self.btn_add_box.setFixedHeight(26)
        self.btn_add_box.clicked.connect(self._add_box)
        row2_extra_layout.addWidget(self.btn_add_box)

        row2_layout.addWidget(self.row2_extra_container)
        main_layout.addWidget(self.row2_card)

        # 加载配置
        self.load_config()
        self._init_ocr()

        # 需求二：程序启动默认启动网页服务
        QTimer.singleShot(600, self._auto_start_web_service)

    def _auto_start_web_service(self):
        """需求二：默认自动启动网页服务"""
        if self.web_thread is None or not self.web_thread.isRunning():
            default_ip = get_local_ip()
            self.start_web_service_with_ip(default_ip)

    def _init_ocr(self):
        def _load():
            try:
                import ddddocr
                self.reader = ddddocr.DdddOcr(show_ad=False)
                if self.monitor_thread:
                    self.monitor_thread.set_reader(self.reader)
            except Exception as e:
                print("OCR 初始化失败:", e)
        threading.Thread(target=_load, daemon=True).start()

    def load_users(self):
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"admin": "admin"}

    def save_users(self):
        try:
            with open(self.users_file, "w", encoding="utf-8") as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def start_web_service_with_ip(self, ip_addr):
        self.stop_web_service()
        self.web_thread = WebServerThread(self, host=ip_addr, port=5000)
        self.web_thread.action_requested.connect(self._handle_web_action)
        self.web_thread.start()

    def stop_web_service(self):
        if self.web_thread:
            self.web_thread.stop()
            self.web_thread.quit()
            self.web_thread.wait(1000)
            self.web_thread = None

    def _open_web_service_dialog(self):
        dlg = WebServiceDialog(self, parent=self)
        dlg.exec()

    def _handle_web_action(self, action, box_id, payload):
        if action == 'toggle_monitor':
            self._toggle_monitor()
        elif action == 'toggle_grille':
            self._toggle_grille()
        elif action == 'toggle_mute':
            box = self._find_box_by_id(box_id)
            if box: box._toggle_mute()
        elif action == 'clear_alarm':
            box = self._find_box_by_id(box_id)
            if box: box._on_clear_alarm()
        elif action == 'set_limits':
            box = self._find_box_by_id(box_id)
            if box:
                if 'lower' in payload:
                    box.lower = float(payload['lower'])
                    box.spin_lower.setValue(box.lower)
                if 'mid_val' in payload:
                    box.mid_val = float(payload['mid_val'])
                    box.spin_mid.setValue(box.mid_val)
                if 'warning_op' in payload: # 需求一：更新预警运算符
                    box.warning_op = str(payload['warning_op'])
                    box.combo_op.setCurrentText(box.warning_op)
                if 'upper' in payload:
                    box.upper = float(payload['upper'])
                    box.spin_upper.setValue(box.upper)
                self.save_config()

    def _find_box_by_id(self, box_id):
        for b in self.boxes:
            if b.box_id == box_id:
                return b
        return None

    def _toggle_hide(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        btn_txt = "👁 显示" if self.boxes_panel_hidden else "👁 隐藏"
        self.btn_toggle_hide.setText(btn_txt)
        for b in self.boxes:
            b.set_panel_hidden(self.boxes_panel_hidden)

    def _on_f12_pressed(self):
        QTimer.singleShot(0, self._toggle_collapse_all)

    def _toggle_collapse_all(self):
        self.is_collapsed = not self.is_collapsed
        self.row1_card.setVisible(not self.is_collapsed)
        self.row2_extra_container.setVisible(not self.is_collapsed)

    def _on_edit_toggled(self, state):
        self.is_editing = (state == Qt.Checked)
        for b in self.boxes:
            b.set_edit_mode(self.is_editing)

    def _add_box(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0: return
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            rx, ry, rw, rh = int(x / scale), int(y / scale), int(w / scale), int(h / scale)
            box_id = int(time.time() * 1000) % 100000
            name = f"区域 {len(self.boxes) + 1}"

            box = OverlayRegionWidget(box_id, rx, ry, rw, rh, name=name, warning_op=">")
            box.delete_requested.connect(self._remove_box)
            box.config_changed.connect(self.save_config)
            box.alarm_cleared.connect(self._check_global_alarm_state)
            box.set_edit_mode(self.is_editing)
            box.set_panel_hidden(self.boxes_panel_hidden)
            box.show()

            self.boxes.append(box)
            self.save_config()

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _remove_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self.save_config()
            self._check_global_alarm_state()

    def _toggle_monitor(self):
        self.monitoring = not self.monitoring
        if self.monitoring:
            self.btn_monitor.setText("⏹ 停止监控")
            self.btn_monitor.setStyleSheet("background-color: #b03a3a; color: white;")
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(
                self.boxes,
                interval=self.spin_interval.value(),
                ocr_params=self.ocr_params,
                scale=scale
            )
            if self.reader:
                self.monitor_thread.set_reader(self.reader)

            self.monitor_thread.value_updated.connect(self._on_ocr_result)
            self.monitor_thread.countdown_tick.connect(self._on_monitor_cd)
            self.monitor_thread.start()
        else:
            self.btn_monitor.setText("▶ 开始监控")
            self.btn_monitor.setStyleSheet("")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.quit()
                self.monitor_thread.wait(1000)
                self.monitor_thread = None
            self.curr_monitor_cd = 0.0

    def _on_monitor_cd(self, rem_sec):
        self.curr_monitor_cd = rem_sec

    def _on_ocr_result(self, box, time_str, val, raw_text):
        if box not in self.boxes: return
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            if val > box.upper or val < box.lower:
                if not box.user_cleared_alarm:
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.set_alarm_state(False)

        self._check_global_alarm_state()

    def _check_global_alarm_state(self):
        has_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if has_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def _toggle_grille(self):
        is_running = self.grille_thread and self.grille_thread.isRunning()
        if not is_running:
            self.btn_grille_start.setText("⏹ 停止操作")
            self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold;")
            self.grille_thread = FineGrilleThread(cycle_interval_min=2.0)
            self.grille_thread.countdown_tick.connect(self._on_grille_cd)
            self.grille_thread.start()
        else:
            self.btn_grille_start.setText("▶ 开始操作")
            self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
            if self.grille_thread:
                self.grille_thread.stop()
                self.grille_thread.quit()
                self.grille_thread.wait(1000)
                self.grille_thread = None
            self.curr_grille_cd = 0.0

    def _on_grille_cd(self, rem_sec):
        self.curr_grille_cd = rem_sec
        m = int(rem_sec // 60)
        s = int(rem_sec % 60)
        self.btn_grille_start.setText(f"⏹ 停止操作 ({m:02d}:{s:02d})")

    def _open_ocr_adjust_dialog(self):
        dlg = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)
            self.save_config()

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=val)
        self.save_config()

    def _on_count_changed(self, val):
        for b in self.boxes:
            b.set_max_log_count(val)
        self.save_config()

    def _on_log_interval_changed(self, val):
        for b in self.boxes:
            b.log_interval_min = val
        self.save_config()

    def save_config(self):
        box_data = []
        for b in self.boxes:
            box_data.append({
                'id': b.box_id,
                'x': b.capture_x,
                'y': b.capture_y,
                'w': b.capture_w,
                'h': b.capture_h,
                'name': b.name,
                'lower': b.lower,
                'mid_val': getattr(b, 'mid_val', 50.0),
                'warning_op': getattr(b, 'warning_op', '>'), # 需求一：保存预警运算符
                'upper': b.upper,
                'decimal_places': getattr(b, 'decimal_places', 0),
                'is_muted': b.is_muted
            })

        cfg = {
            'interval': self.spin_interval.value(),
            'log_count': self.spin_count.value(),
            'log_interval': self.spin_log_interval.value(),
            'ocr_params': self.ocr_params,
            'boxes': box_data,
            'pos': [self.x(), self.y()]
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存失败:", e)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            self.spin_interval.setValue(cfg.get('interval', 1.0))
            self.spin_count.setValue(cfg.get('log_count', 30))
            self.spin_log_interval.setValue(cfg.get('log_interval', 1.0))
            self.ocr_params = cfg.get('ocr_params', {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2})

            pos = cfg.get('pos')
            if pos and len(pos) == 2:
                self.move(pos[0], pos[1])

            for b_data in cfg.get('boxes', []):
                box = OverlayRegionWidget(
                    box_id=b_data.get('id', int(time.time()*1000)%100000),
                    x=b_data.get('x', 100),
                    y=b_data.get('y', 100),
                    w=b_data.get('w', 100),
                    h=b_data.get('h', 50),
                    name=b_data.get('name', '区域'),
                    lower=b_data.get('lower', 0.0),
                    mid_val=b_data.get('mid_val', 50.0),
                    upper=b_data.get('upper', 100.0),
                    decimal_places=b_data.get('decimal_places', 0),
                    warning_op=b_data.get('warning_op', '>') # 需求一：读取预警运算符
                )
                box.is_muted = b_data.get('is_muted', False)
                if box.is_muted:
                    box.btn_mute.setText("🔇")
                    box.btn_mute.setStyleSheet("QPushButton { background-color: #e65100; color: white; border: none; border-radius: 3px; font-size: 10px; }")

                box.set_max_log_count(self.spin_count.value())
                box.log_interval_min = self.spin_log_interval.value()
                box.delete_requested.connect(self._remove_box)
                box.config_changed.connect(self.save_config)
                box.alarm_cleared.connect(self._check_global_alarm_state)
                box.show()
                self.boxes.append(box)

        except Exception as e:
            print("加载配置失败:", e)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self.save_config()

    def close_app(self):
        self.save_config()
        self.f12_listener.stop()
        self.alarm_player.stop()

        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.quit()
            self.monitor_thread.wait(500)

        if self.grille_thread:
            self.grille_thread.stop()
            self.grille_thread.quit()
            self.grille_thread.wait(500)

        self.stop_web_service()

        for b in self.boxes:
            b.close()

        self.close()
        QApplication.quit()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec())
