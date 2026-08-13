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
    QDialog, QFormLayout, QDialogButtonBox, QComboBox, QTableWidget,
    QHeaderView, QMenu, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QIcon, QImage, QAction
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


# ==================== Windows 模拟鼠标点击 ====================
def perform_click(x, y):
    try:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.02)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    except Exception as e:
        print(f"点击指令执行失败: {e}")


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


# ==================== 自动化脚本后台执行线程 ====================
class ScriptRunnerThread(QThread):
    def __init__(self, script, parent=None):
        super().__init__(parent)
        self.script = script
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        steps = self.script.get("steps", [])
        if not steps:
            return

        idx = 0
        while self.running:
            if idx < 0 or idx >= len(steps):
                break

            step = steps[idx]
            stype = step.get("type", None)

            if stype is None:
                x = step.get("x", -1)
                y = step.get("y", -1)
                delay = step.get("delay", 1.0)
                jump = step.get("jump", 0)

                if x >= 0 and y >= 0 and self.running:
                    perform_click(x, y)

                end_time = time.time() + max(0.01, delay)
                while self.running and time.time() < end_time:
                    self.msleep(50)

                if not self.running: break

                if jump > 0 and jump <= len(steps):
                    idx = jump - 1
                else:
                    idx += 1
            else:
                if stype == "click":
                    x = step.get("x", -1)
                    y = step.get("y", -1)
                    if x >= 0 and y >= 0 and self.running:
                        perform_click(x, y)
                    time.sleep(0.05)
                    idx += 1
                elif stype == "delay":
                    delay = step.get("delay", 1.0)
                    end_time = time.time() + max(0.01, delay)
                    while self.running and time.time() < end_time:
                        self.msleep(50)
                    idx += 1
                elif stype == "jump":
                    jump = step.get("jump", 1)
                    if 1 <= jump <= len(steps):
                        idx = jump - 1
                    else:
                        idx += 1
                else:
                    idx += 1


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
        self.picker = None

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
        self.setWindowOpacity(0.0)
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.setWindowOpacity(1.0)
            self.activateWindow()
            self.raise_()
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


# ==================== 单点点击位置拾取器 ====================
class SingleCoordPicker(QWidget):
    coord_selected = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        screens = QApplication.screens()
        total_rect = screens[0].geometry()
        for s in screens[1:]:
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)

        self.screen_pixmap = QPixmap(total_rect.size())
        painter = QPainter(self.screen_pixmap)
        for screen in screens:
            painter.drawPixmap(screen.geometry().topLeft() - total_rect.topLeft(), screen.grabWindow(0))
        painter.end()

        self.label = QLabel("🎯 单击鼠标左键拾取点击坐标 (ESC 取消)", self)
        self.label.setStyleSheet("color: white; background: rgba(0,0,0,220); padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: bold;")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.globalPosition().toPoint()
            self.coord_selected.emit(pos.x(), pos.y())
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(-1, -1)
            self.close()


# ==================== 详细脚本配置弹窗 ====================
class ScriptEditorDialog(QDialog):
    def __init__(self, script_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ 详细脚本配置")
        self.resize(560, 380)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; }
            QLineEdit {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px;
                font-weight: bold;
            }
            QTableWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: white;
                gridline-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: rgba(43, 45, 66, 0.8);
                color: #00ff8c;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
            QComboBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
            }
        """)

        self.script_data = script_data or {"name": "新脚本", "steps": []}
        self.picker = None

        layout = QVBoxLayout(self)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("📝 脚本名字:"))
        self.edit_name = QLineEdit(self.script_data.get("name", "新脚本"))
        name_layout.addWidget(self.edit_name)
        layout.addLayout(name_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["步骤", "步骤类型", "详细参数与操作", "删除"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加步骤 ▾")
        self.btn_add.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        
        self.add_menu = QMenu(self)
        act_click = self.add_menu.addAction("🎯 点击拾取")
        act_delay = self.add_menu.addAction("⏱️ 延迟")
        act_jump = self.add_menu.addAction("🔀 跳转")

        act_click.triggered.connect(lambda: self._add_step_row({"type": "click"}))
        act_delay.triggered.connect(lambda: self._add_step_row({"type": "delay"}))
        act_jump.triggered.connect(lambda: self._add_step_row({"type": "jump"}))

        self.btn_add.setMenu(self.add_menu)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        steps = self.script_data.get("steps", [])
        if steps:
            for s in steps:
                self._add_step_row(s)
        else:
            self._add_step_row({"type": "click"})

    def _add_step_row(self, step=None):
        if step is None or not isinstance(step, dict):
            step = {"type": "click", "x": -1, "y": -1}

        stype = step.get("type", "click")
        row = self.table.rowCount()
        self.table.insertRow(row)

        lbl_step = QLabel(f"第 {row + 1} 步")
        lbl_step.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(row, 0, lbl_step)

        combo_type = QComboBox()
        combo_type.addItems(["点击拾取", "延迟", "跳转"])
        type_map = {"click": 0, "delay": 1, "jump": 2}
        combo_type.setCurrentIndex(type_map.get(stype, 0))
        self.table.setCellWidget(row, 1, combo_type)

        param_widget = QWidget()
        param_layout = QHBoxLayout(param_widget)
        param_layout.setContentsMargins(2, 2, 2, 2)
        param_layout.setSpacing(4)
        self.table.setCellWidget(row, 2, param_widget)

        def setup_param_ui(selected_text, current_step=None):
            while param_layout.count():
                child = param_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            if selected_text == "点击拾取":
                x_val = current_step.get("x", -1) if current_step else -1
                y_val = current_step.get("y", -1) if current_step else -1
                coord_str = f"({x_val}, {y_val})" if x_val >= 0 and y_val >= 0 else "未位置"
                lbl_coord = QLabel(coord_str)
                lbl_coord.setAlignment(Qt.AlignCenter)
                lbl_coord.setStyleSheet("color: #00ff8c; font-weight: bold;")

                btn_pick = QPushButton("🎯 拾取")
                btn_pick.setFixedHeight(22)
                btn_pick.clicked.connect(lambda _, l=lbl_coord: self._pick_coord_for_label(l))

                param_layout.addWidget(lbl_coord)
                param_layout.addWidget(btn_pick)

            elif selected_text == "延迟":
                lbl_t = QLabel("时长(秒):")
                spin_delay = CleanDoubleSpinBox()
                spin_delay.setRange(0.01, 9999.0)
                spin_delay.setValue(current_step.get("delay", 1.0) if current_step else 1.0)
                spin_delay.setAlignment(Qt.AlignCenter)
                param_layout.addWidget(lbl_t)
                param_layout.addWidget(spin_delay)

            elif selected_text == "跳转":
                lbl_t = QLabel("跳转至第:")
                spin_jump = QSpinBox()
                spin_jump.setRange(1, 999)
                spin_jump.setValue(current_step.get("jump", 1) if current_step else 1)
                spin_jump.setAlignment(Qt.AlignCenter)
                lbl_unit = QLabel("步")
                param_layout.addWidget(lbl_t)
                param_layout.addWidget(spin_jump)
                param_layout.addWidget(lbl_unit)

        setup_param_ui(combo_type.currentText(), step)
        combo_type.currentTextChanged.connect(lambda text: setup_param_ui(text, None))

        btn_del = QPushButton("❌")
        btn_del.setFixedSize(26, 22)
        btn_del.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; font-weight: bold; } QPushButton:hover { background-color: #ff6666; }")
        btn_del.clicked.connect(lambda _, b=btn_del: self._del_step_row_by_btn(b))
        self.table.setCellWidget(row, 3, btn_del)

        self._update_row_indices()

    def _pick_coord_for_label(self, label_widget):
        self.setWindowOpacity(0.0)
        time.sleep(0.2)
        self.picker = SingleCoordPicker()

        def on_selected(x, y):
            self.setWindowOpacity(1.0)
            self.activateWindow()
            self.raise_()
            if x >= 0 and y >= 0:
                label_widget.setText(f"({x}, {y})")

        self.picker.coord_selected.connect(on_selected)
        self.picker.showFullScreen()

    def _del_step_row_by_btn(self, btn):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 3) == btn:
                self.table.removeRow(r)
                break
        self._update_row_indices()

    def _update_row_indices(self):
        for r in range(self.table.rowCount()):
            lbl = self.table.cellWidget(r, 0)
            if lbl:
                lbl.setText(f"第 {r + 1} 步")

    def _on_accept(self):
        name = self.edit_name.text().strip()
        if not name:
            name = "未命名脚本"

        steps = []
        for r in range(self.table.rowCount()):
            combo_type = self.table.cellWidget(r, 1)
            param_widget = self.table.cellWidget(r, 2)

            if not combo_type or not param_widget:
                continue

            stype_text = combo_type.currentText()
            param_layout = param_widget.layout()

            if stype_text == "点击拾取":
                x_val, y_val = -1, -1
                if param_layout and param_layout.count() > 0:
                    lbl_coord = param_layout.itemAt(0).widget()
                    if lbl_coord and isinstance(lbl_coord, QLabel):
                        coord_text = lbl_coord.text()
                        if "(" in coord_text and ")" in coord_text:
                            try:
                                pts = coord_text.replace("(", "").replace(")", "").split(",")
                                x_val = int(pts[0].strip())
                                y_val = int(pts[1].strip())
                            except: pass
                steps.append({"type": "click", "x": x_val, "y": y_val})

            elif stype_text == "延迟":
                delay_val = 1.0
                if param_layout and param_layout.count() > 1:
                    spin_delay = param_layout.itemAt(1).widget()
                    if spin_delay and isinstance(spin_delay, QDoubleSpinBox):
                        delay_val = spin_delay.value()
                steps.append({"type": "delay", "delay": delay_val})

            elif stype_text == "跳转":
                jump_val = 1
                if param_layout and param_layout.count() > 1:
                    spin_jump = param_layout.itemAt(1).widget()
                    if spin_jump and isinstance(spin_jump, QSpinBox):
                        jump_val = spin_jump.value()
                steps.append({"type": "jump", "jump": jump_val})

        self.script_data = {
            "name": name,
            "steps": steps
        }
        self.accept()

    def get_script_data(self):
        return self.script_data


# ==================== 独立日志查看弹窗 ====================
class LogDialog(QDialog):
    def __init__(self, box, parent=None):
        super().__init__(parent)
        self.box = box
        self.setWindowTitle(f"📋 记录 - {box.name}")
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
        self.mid_val = mid_val
        self.mid_op = mid_op if mid_op in ('>', '<', '=') else '>'
        self.upper = upper
        self.decimal_places = decimal_places

        self.log_interval_min = 1.0
        self.last_log_time = 0.0
        self.max_log_count = 30
        self.history_records = []

        self.is_alarm = False
        self.is_warning = False
        self.user_cleared_alarm = False
        self.cleared_val = None

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
        self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        panel_layout = QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)

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

        self.row3_container = QWidget()
        self.row3_layout = QHBoxLayout(self.row3_container)
        self.row3_layout.setContentsMargins(0, 0, 0, 0)
        self.row3_layout.setSpacing(3)

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

        self.row3_layout.addWidget(self.lbl_mid)
        self.row3_layout.addWidget(self.combo_mid_op)
        self.row3_layout.addWidget(self.spin_mid)
        self.row3_layout.addStretch(1)
        self.row3_layout.addWidget(self.btn_clear_alarm)
        self.row3_layout.addStretch(0)
        panel_layout.addWidget(self.row3_container)

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
        self.spin_dec.setFixedSize(24, 20)
        self.spin_dec.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #00ff8c; border: 1px solid #00ff8c; font-size: 10px; border-radius: 2px;")
        self.spin_dec.valueChanged.connect(self._on_dec_changed)

        self.btn_show_log = QPushButton("📋 记录")
        self.btn_show_log.setFixedSize(65, 20)
        self.btn_show_log.setStyleSheet("QPushButton { background-color: rgba(0, 136, 204, 0.8); color: white; border: none; border-radius: 3px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #0088cc; }")
        self.btn_show_log.clicked.connect(self._open_log_dialog)

        row4_layout.addWidget(self.btn_mute)
        row4_layout.addWidget(self.lbl_dec)
        row4_layout.addWidget(self.spin_dec)
        row4_layout.addWidget(self.btn_show_log)
        row4_layout.addStretch()
        panel_layout.addWidget(self.row4_container)

        self.list_widget = QListWidget()

        main_layout.addWidget(self.control_panel)

        self._update_bar_visibility()
        self._update_geometry()
        self.setMouseTracking(True)

    def _open_log_dialog(self):
        dlg = LogDialog(self, self)
        dlg.exec()

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
                self.row4_container.setVisible(False)
                self.lbl_mid.setVisible(False)
                self.combo_mid_op.setVisible(False)
                self.spin_mid.setVisible(False)
                self.btn_clear_alarm.setVisible(True)
                self.row3_layout.setStretch(3, 1)
                self.row3_layout.setStretch(5, 1)
            else:
                self.control_panel.setVisible(False)
        else:
            self.control_panel.setVisible(True)
            self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
            self.row3_layout.setStretch(3, 1)
            self.row3_layout.setStretch(5, 0)
            self.row1_container.setVisible(True)
            self.row2_container.setVisible(self.is_editing)
            self.row3_container.setVisible(True)
            self.row4_container.setVisible(True)

            self.lbl_mid.setVisible(self.is_editing)
            self.combo_mid_op.setVisible(self.is_editing)
            self.spin_mid.setVisible(self.is_editing)
            self.btn_clear_alarm.setVisible(self.is_alarm)

            self.btn_mute.setVisible(True)
            self.lbl_dec.setVisible(self.is_editing)
            self.spin_dec.setVisible(self.is_editing)
            self.btn_show_log.setVisible(True)

            self.btn_delete.setVisible(self.is_editing)
            self.spin_lower.setEnabled(self.is_editing)
            self.spin_upper.setEnabled(self.is_editing)
            self.lbl_title.setVisible(not self.is_editing)
            self.edit_title.setVisible(self.is_editing)

    def _update_geometry(self):
        if self.panel_hidden:
            total_w = max(self.capture_w, 60)
            panel_h = 28 if self.is_alarm else 0
        else:
            total_w = max(self.capture_w, 140)
            panel_h = 95 if self.is_editing else 52

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
            painter.drawPixmap(screen.geometry().topLeft() - total_rect.topLeft(), screen.grabWindow(0))
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
                self.start_pos = event.globalPosition().toPoint()
                self.end_pos = self.start_pos
                self.state = 1
                self.label.setText("🖱 点击右下角确定终点")
                self.label.adjustSize()
            elif self.state == 1:
                self.end_pos = event.globalPosition().toPoint()
                x = min(self.start_pos.x(), self.end_pos.x())
                y = min(self.start_pos.y(), self.end_pos.y())
                w = abs(self.end_pos.x() - self.start_pos.x())
                h = abs(self.end_pos.y() - self.start_pos.y())
                if w > 0 and h > 0:
                    self.coord_selected.emit(x, y, w, h)
                    self.close()

    def mouseMoveEvent(self, event):
        if self.state == 1:
            self.end_pos = event.globalPosition().toPoint()
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
        .toggle-icon { cursor: pointer; font-size: 13px; color: #888888; font-weight: bold; user-select: none; padding: 2px 6px; border-radius: 4px; background: rgba(255, 255, 255, 0.08); margin-left: 6px; }
        .toggle-icon:hover { color: #aaaaaa; background: rgba(255, 255, 255, 0.15); }

        .header-row2 { display: flex; align-items: center; justify-content: flex-end; gap: 8px; width: 100%; font-size: 12px; }
        .header-row3 { display: flex; gap: 8px; width: 100%; margin-top: 2px; align-items: center; }
        
        .btn-top {
            flex: 1;
            background: #2e9a58;
            color: #fff;
            border: none;
            border-radius: 6px;
            padding: 0 12px;
            height: 36px;
            font-size: 13px;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.2s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            box-sizing: border-box;
        }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-top.btn-exit {
            flex: 0 0 36px;
            width: 36px;
            padding: 0;
            background: #ff3333;
            font-size: 13px;
        }
        .btn-top.btn-exit:hover { background: #ff6666; }

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

        .trend-up {
            color: #ff4d4d;
            background: rgba(255, 77, 77, 0.15);
            border: 1px solid rgba(255, 77, 77, 0.35);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 12px;
            font-weight: bold;
            margin-right: 4px;
            display: inline-flex;
            align-items: center;
            line-height: 1;
            box-shadow: 0 0 5px rgba(255, 77, 77, 0.25);
        }
        .trend-down {
            color: #00ff8c;
            background: rgba(0, 255, 140, 0.15);
            border: 1px solid rgba(0, 255, 140, 0.35);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 12px;
            font-weight: bold;
            margin-right: 4px;
            display: inline-flex;
            align-items: center;
            line-height: 1;
            box-shadow: 0 0 5px rgba(0, 255, 140, 0.25);
        }

        .val-container { display: flex; align-items: center; font-size: 18px; font-weight: bold; font-family: monospace; }
        .val-text { color: #00ff8c; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 42px; text-align: center; font-size: 11px; }

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
            <div id="header-top-panel">
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
                    <label style="color:#ffaa00; font-weight:bold;">对比(分):</label>
                    <input id="compare-min-input" type="number" min="0" step="1" class="setting-input" style="width:60px;" value="5">
                    <button class="btn-action" style="background:#0088cc; padding:4px 8px;" onclick="saveCompareMin()">保存</button>
                </div>
            </div>

            <div id="header-row3" class="header-row3" style="display: none;">
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
                <button id="btn-app-exit" class="btn-top btn-exit" onclick="exitApp()" title="退出所有进程">❌</button>
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
                <button class="btn-top" style="background:#0088cc; width:100%; height:32px;" onclick="handleLogin()">登录</button>
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
                <button class="btn-top" style="background:#2e9a58; width:100%; height:32px;" onclick="handleAddUser()">添加/更新用户</button>
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
                document.querySelectorAll('.toggle-icon').forEach(el => el.style.display = 'inline-block');
            } else {
                document.getElementById('login-box').style.display = 'inline-flex';
                document.getElementById('user-box').style.display = 'none';

                document.getElementById('header-row2').style.display = 'none';
                document.getElementById('header-row3').style.display = 'none';

                cardExpandedState = {};
                document.querySelectorAll('.fold-body').forEach(el => {
                    el.style.display = 'none';
                });
                document.querySelectorAll('.toggle-icon').forEach(el => el.style.display = 'none');
            }
        }

        function exitApp() {
            if (confirm('确定要退出所有进程吗？')) {
                postAction('exit_app', -1);
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
            const decimal_places = document.getElementById('dec-' + boxId).value;
            postAction('set_limits', boxId, {lower, mid_op, mid_val, upper, decimal_places});
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
                let diffHtml = '';
                if (box.diff_text) {
                    diffHtml = `<span class="diff-text" style="font-size: 12px; color: #a0a0a0; margin-right: 3px;">${box.diff_text}</span>`;
                }

                if (box.trend === 'up') {
                    trendHtml = '<span class="trend-up">⬆</span>';
                } else if (box.trend === 'down') {
                    trendHtml = '<span class="trend-down">⬇</span>';
                }

                let header = card.querySelector('.card-header');
                const isExpanded = !!cardExpandedState[box.id];

                if (!header) {
                    const logsHtml = (box.logs || []).map(l => `<div class="log-item">${l}</div>`).join('');
                    card.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box">
                                <span class="card-title">${box.name}</span>
                                <span id="toggle-icon-${box.id}" class="toggle-icon" style="display: ${currentUser ? 'inline-block' : 'none'};" onclick="toggleSingleCard(${box.id})">${isExpanded ? '▲' : '▼'}</span>
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
                                <label>小数点:</label>
                                <input id="dec-${box.id}" type="number" min="0" max="4" step="1" class="setting-input" value="${box.decimal_places || 0}">
                                <button class="btn-action" style="background:#0088cc; padding:2px 8px; margin-left:4px;" onclick="updateLimits(${box.id})">保存</button>
                            </div>
                            <div class="log-title">📊 记录</div>
                            <div id="logs-${box.id}" class="log-list">${logsHtml}</div>
                        </div>
                    `;
                } else {
                    const toggleIcon = document.getElementById('toggle-icon-' + box.id);
                    if (toggleIcon) {
                        toggleIcon.style.display = currentUser ? 'inline-block' : 'none';
                        toggleIcon.innerText = isExpanded ? '▲' : '▼';
                    }

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

                    const decInput = document.getElementById('dec-' + box.id);
                    if (decInput && document.activeElement !== decInput) decInput.value = box.decimal_places || 0;

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
                diff_text = ''
                if val is not None and past_val is not None:
                    if val > past_val:
                        trend = 'up'
                    elif val < past_val:
                        trend = 'down'
                    diff_val = abs(val - past_val)
                    dp = getattr(b, 'decimal_places', 0)
                    diff_text = f"{diff_val:.{dp}f}"

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
                    'decimal_places': getattr(b, 'decimal_places', 0),
                    'val': val,
                    'val_text': val_text,
                    'trend': trend,
                    'diff_text': diff_text,
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
        self.scripts = []  # 自动化脚本列表
        self.active_script_threads = {}

        self.monitoring = False
        self.operating = False
        self.is_editing = False
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

        self.setMaximumWidth(600)

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

        self.main_card = QFrame()
        self.main_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.85); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 8px; }")
        card_layout = QVBoxLayout(self.main_card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(8)

        # ---------- 第 1 排：识别监控配置栏 ----------
        self.row1_layout = QHBoxLayout()
        self.row1_layout.setContentsMargins(0, 0, 0, 0)
        self.row1_layout.setSpacing(6)

        self.row1_layout.addWidget(QLabel("⏱ 识别（秒）:"))
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

        self.row1_layout.addWidget(QLabel("📝 记录（分）:"))
        self.spin_log_interval = CleanDoubleSpinBox()
        self.spin_log_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_log_interval.setAlignment(Qt.AlignCenter)
        self.spin_log_interval.setFixedSize(42, 26)
        self.spin_log_interval.setRange(0.0, 1440.0)
        self.spin_log_interval.setValue(1.0)
        self.spin_log_interval.setSingleStep(0.5)
        self.spin_log_interval.valueChanged.connect(self._on_log_interval_changed)
        self.row1_layout.addWidget(self.spin_log_interval)

        self.btn_ocr_adjust = QPushButton("⚙️ 识别")
        self.btn_ocr_adjust.setFixedHeight(26)
        self.btn_ocr_adjust.clicked.connect(self._open_ocr_adjust_dialog)
        self.row1_layout.addWidget(self.btn_ocr_adjust)

        card_layout.addLayout(self.row1_layout)

        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setStyleSheet("border-top: 1px solid rgba(255, 255, 255, 0.1); border-bottom: none;")
        card_layout.addWidget(line1)

        # ---------- 第 2 排：框体与配置管理（修改按钮名称） ----------
        self.row2_layout = QHBoxLayout()
        self.row2_layout.setContentsMargins(0, 0, 0, 0)
        self.row2_layout.setSpacing(6)

        self.btn_add_box = QPushButton("➕ 图标新增")
        self.btn_add_box.clicked.connect(self._add_new_box)

        self.btn_edit_pos = QPushButton("✏️ 图标编辑")
        self.btn_edit_pos.clicked.connect(self._toggle_edit_positions)

        self.btn_hide_boxes = QPushButton("👁️ 图标隐藏")
        self.btn_hide_boxes.clicked.connect(self._toggle_hide_boxes)

        self.btn_save_config = QPushButton("💾 图标保存")
        self.btn_save_config.clicked.connect(self._save_config)

        self.btn_load_config = QPushButton("📂 图标加载")
        self.btn_load_config.clicked.connect(self._load_config)

        self.row2_layout.addWidget(self.btn_add_box)
        self.row2_layout.addWidget(self.btn_edit_pos)
        self.row2_layout.addWidget(self.btn_hide_boxes)
        self.row2_layout.addWidget(self.btn_save_config)
        self.row2_layout.addWidget(self.btn_load_config)

        card_layout.addLayout(self.row2_layout)

        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("border-top: 1px solid rgba(255, 255, 255, 0.1); border-bottom: none;")
        card_layout.addWidget(line2)

        # ---------- 底部主控按钮排 ----------
        self.row_ctrl_layout = QHBoxLayout()
        self.row_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        self.row_ctrl_layout.setSpacing(6)

        self.btn_toggle_monitor = QPushButton("▶ 开始监控")
        self.btn_toggle_monitor.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")
        self.btn_toggle_monitor.clicked.connect(self._toggle_monitoring)

        self.btn_toggle_grille = QPushButton("▶ 开始操作")
        self.btn_toggle_grille.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        self.btn_toggle_grille.clicked.connect(self._toggle_operation)

        self.btn_exit = QPushButton("❌")
        self.btn_exit.setFixedWidth(36)
        self.btn_exit.setStyleSheet("background-color: #ff3333; color: white; font-weight: bold;")
        self.btn_exit.clicked.connect(QApplication.quit)

        self.row_ctrl_layout.addWidget(self.btn_toggle_monitor)
        self.row_ctrl_layout.addWidget(self.btn_toggle_grille)
        self.row_ctrl_layout.addWidget(self.btn_exit)

        card_layout.addLayout(self.row_ctrl_layout)

        main_layout.addWidget(self.main_card)

        # 异步初始化 OCR
        self.ocr_init_thread = OCRInitThread()
        self.ocr_init_thread.ocr_ready.connect(self._on_ocr_ready)
        self.ocr_init_thread.start()

        # 自动加载配置
        self._load_config()

        # 启动 Web 服务器
        if FLASK_AVAILABLE:
            self.web_thread = WebServerThread(self)
            self.web_thread.action_requested.connect(self._handle_web_action)
            self.web_thread.start()

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
        dlg = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)

    def _add_new_box(self):
        picker = CoordinatePicker()
        def on_picked(x, y, w, h):
            if w <= 0 or h <= 0:
                return
            box_id = len(self.boxes) + 1
            box_name = f"区域{box_id}"
            box = OverlayRegionWidget(box_id, x, y, w, h, name=box_name)
            box.delete_requested.connect(self._delete_box)
            box.set_max_log_count(self.spin_count.value())
            box.log_interval_min = self.spin_log_interval.value()
            box.set_edit_mode(self.is_editing)
            box.set_panel_hidden(self.boxes_panel_hidden)
            box.show()
            self.boxes.append(box)
        picker.coord_selected.connect(on_picked)
        picker.showFullScreen()

    def _delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            box.deleteLater()

    def _toggle_edit_positions(self):
        self.is_editing = not self.is_editing
        btn_text = "✏️ 取消编辑" if self.is_editing else "✏️ 图标编辑"
        self.btn_edit_pos.setText(btn_text)
        for box in self.boxes:
            box.set_edit_mode(self.is_editing)

    def _toggle_hide_boxes(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        btn_text = "👁️ 显示框体" if self.boxes_panel_hidden else "👁️ 图标隐藏"
        self.btn_hide_boxes.setText(btn_text)
        for box in self.boxes:
            box.set_panel_hidden(self.boxes_panel_hidden)

    def _save_config(self):
        data = {
            "interval": self.spin_interval.value(),
            "log_count": self.spin_count.value(),
            "log_interval": self.spin_log_interval.value(),
            "ocr_params": self.ocr_params,
            "compare_interval_min": self.compare_interval_min,
            "boxes": []
        }
        for b in self.boxes:
            data["boxes"].append({
                "box_id": b.box_id,
                "x": b.capture_x,
                "y": b.capture_y,
                "w": b.capture_w,
                "h": b.capture_h,
                "name": b.name,
                "lower": b.lower,
                "mid_val": b.mid_val,
                "mid_op": b.mid_op,
                "upper": b.upper,
                "decimal_places": b.decimal_places
            })
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _load_config(self):
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.spin_interval.setValue(data.get("interval", 1.0))
            self.spin_count.setValue(data.get("log_count", 30))
            self.spin_log_interval.setValue(data.get("log_interval", 1.0))
            self.ocr_params = data.get("ocr_params", self.ocr_params)
            self.compare_interval_min = data.get("compare_interval_min", 5.0)

            for b in list(self.boxes):
                b.close()
                b.deleteLater()
            self.boxes.clear()

            for bdata in data.get("boxes", []):
                box = OverlayRegionWidget(
                    bdata.get("box_id", 1),
                    bdata.get("x", 100),
                    bdata.get("y", 100),
                    bdata.get("w", 100),
                    bdata.get("h", 50),
                    name=bdata.get("name", "区域"),
                    lower=bdata.get("lower", 0.0),
                    mid_val=bdata.get("mid_val", 50.0),
                    upper=bdata.get("upper", 100.0),
                    decimal_places=bdata.get("decimal_places", 0),
                    mid_op=bdata.get("mid_op", ">")
                )
                box.delete_requested.connect(self._delete_box)
                box.set_max_log_count(self.spin_count.value())
                box.log_interval_min = self.spin_log_interval.value()
                box.set_edit_mode(self.is_editing)
                box.set_panel_hidden(self.boxes_panel_hidden)
                box.show()
                self.boxes.append(box)
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _toggle_monitoring(self):
        if not self.monitoring:
            self.monitoring = True
            self.btn_toggle_monitor.setText("⏹ 停止监控")
            self.btn_toggle_monitor.setStyleSheet("background-color: #b03a3a; color: white; font-weight: bold;")
            
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(
                self.boxes,
                interval=self.spin_interval.value(),
                ocr_params=self.ocr_params,
                scale=scale
            )
            self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.start()
        else:
            self.monitoring = False
            self.btn_toggle_monitor.setText("▶ 开始监控")
            self.btn_toggle_monitor.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")
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
                if not box.user_cleared_alarm or (box.cleared_val is not None and abs(val - box.cleared_val) > 1e-4):
                    box.user_cleared_alarm = False
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.set_alarm_state(False)

            is_warn = box.check_mid_condition(val)
            box.set_warning_state(is_warn)
        else:
            box.set_alarm_state(False)
            box.set_warning_state(False)

        any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if any_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def _toggle_operation(self):
        self.operating = not self.operating
        if self.operating:
            self.btn_toggle_grille.setText("⏹ 停止操作")
            self.btn_toggle_grille.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold;")
        else:
            self.btn_toggle_grille.setText("▶ 开始操作")
            self.btn_toggle_grille.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")

    def _on_f12_pressed(self):
        if self.monitoring:
            self._toggle_monitoring()
        if self.operating:
            self._toggle_operation()
        self.alarm_player.stop()

    def _handle_web_action(self, action, box_id, payload):
        if action == "toggle_monitor":
            self._toggle_monitoring()
        elif action == "toggle_grille":
            self._toggle_operation()
        elif action == "exit_app":
            QApplication.quit()
        elif action == "set_compare_min":
            self.compare_interval_min = float(payload.get("compare_min", 5.0))
        elif action == "clear_alarm":
            for b in self.boxes:
                if b.box_id == box_id:
                    b._on_clear_alarm()
                    break
        elif action == "toggle_mute":
            for b in self.boxes:
                if b.box_id == box_id:
                    b._toggle_mute()
                    break
        elif action == "set_limits":
            for b in self.boxes:
                if b.box_id == box_id:
                    try:
                        b.spin_lower.setValue(float(payload.get("lower", b.lower)))
                        b.combo_mid_op.setCurrentText(str(payload.get("mid_op", b.mid_op)))
                        b.spin_mid.setValue(float(payload.get("mid_val", b.mid_val)))
                        b.spin_upper.setValue(float(payload.get("upper", b.upper)))
                        b.spin_dec.setValue(int(payload.get("decimal_places", b.decimal_places)))
                    except Exception as e:
                        print(f"设置边界失败: {e}")
                    break

    def _on_ocr_ready(self, reader):
        self.reader = reader
        if self.monitor_thread:
            self.monitor_thread.set_reader(reader)

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
        except Exception as e:
            print(f"保存用户配置失败: {e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def closeEvent(self, event):
        if self.f12_listener:
            self.f12_listener.stop()
        if self.monitor_thread:
            self.monitor_thread.stop()
        if self.web_thread:
            self.web_thread.stop()
        self.alarm_player.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec())
