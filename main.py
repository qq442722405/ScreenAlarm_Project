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
    QHeaderView, QMenu, QScrollArea, QMessageBox
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
        targets = []
        curr = self
        while curr:
            targets.append(curr)
            curr = curr.parent()

        for t in targets:
            if hasattr(t, 'setWindowOpacity'):
                t.setWindowOpacity(0.0)

        QApplication.processEvents()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            for t in targets:
                if hasattr(t, 'setWindowOpacity'):
                    t.setWindowOpacity(1.0)
            self.activateWindow()
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
        self.picker.raise_()
        self.picker.activateWindow()

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
            painter.drawPixmap(screen.geometry().topLeft(), screen.grabWindow(0))
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
            pos = event.position().toPoint()
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
        # 递归隐藏自身及所有父窗口（如 ScriptManagerDialog），防止窗口挡住拾取蒙版
        targets = []
        curr = self
        while curr:
            targets.append(curr)
            curr = curr.parent()

        for t in targets:
            if hasattr(t, 'setWindowOpacity'):
                t.setWindowOpacity(0.0)

        QApplication.processEvents()
        time.sleep(0.2)
        self.picker = SingleCoordPicker()

        def on_selected(x, y):
            for t in targets:
                if hasattr(t, 'setWindowOpacity'):
                    t.setWindowOpacity(1.0)
            self.activateWindow()
            if x >= 0 and y >= 0:
                label_widget.setText(f"({x}, {y})")

        self.picker.coord_selected.connect(on_selected)
        self.picker.showFullScreen()
        self.picker.raise_()
        self.picker.activateWindow()

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


# ==================== 自动化脚本管理弹窗 ====================
class ScriptManagerDialog(QDialog):
    def __init__(self, scripts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📜 自动化脚本管理")
        self.resize(400, 300)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
        """)

        self.scripts = scripts
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 新建脚本")
        self.btn_add.clicked.connect(self._add_script)
        self.btn_edit = QPushButton("✏️ 编辑脚本")
        self.btn_edit.clicked.connect(self._edit_script)
        self.btn_del = QPushButton("❌ 删除脚本")
        self.btn_del.clicked.connect(self._del_script)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_edit)
        btn_layout.addWidget(self.btn_del)
        layout.addLayout(btn_layout)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)

    def refresh_list(self):
        self.list_widget.clear()
        for s in self.scripts:
            name = s.get("name", "未命名")
            steps_cnt = len(s.get("steps", []))
            self.list_widget.addItem(f"📜 {name} ({steps_cnt} 个步骤)")

    def _add_script(self):
        dlg = ScriptEditorDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_script_data()
            self.scripts.append(data)
            self.refresh_list()
            if self.parent():
                self.parent().save_config()

    def _edit_script(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.scripts):
            return
        dlg = ScriptEditorDialog(script_data=self.scripts[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_script_data()
            self.scripts[row] = data
            self.refresh_list()
            if self.parent():
                self.parent().save_config()

    def _del_script(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.scripts):
            return
        del self.scripts[row]
        self.refresh_list()
        if self.parent():
            self.parent().save_config()


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
                } else {
                    const data = await res.json();
                    alert('操作失败: ' + (data.message || '未知错误'));
                }
            } catch(e) { alert('请求异常: ' + e); }
        }

        async function loadUsersList() {
            try {
                const res = await fetch('/api/users');
                if (res.ok) {
                    const users = await res.json();
                    const container = document.getElementById('users-list');
                    container.innerHTML = '';
                    users.forEach(u => {
                        const div = document.createElement('div');
                        div.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.1); font-size:12px;';
                        div.innerHTML = `<span>👤 ${u}</span> ${u !== 'admin' ? `<button class="btn-action" style="background:#ff3333; padding:2px 6px;" onclick="handleDeleteUser('${u}')">删除</button>` : '<span style="color:#888;">管理员</span>'}`;
                        container.appendChild(div);
                    });
                }
            } catch(e) {}
        }

        async function handleDeleteUser(username) {
            if (!confirm(`确定删除用户 ${username} 吗？`)) return;
            try {
                const res = await fetch('/api/users', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'delete', username: username})
                });
                if (res.ok) {
                    loadUsersList();
                } else {
                    alert('删除失败');
                }
            } catch(e) { alert('请求异常: ' + e); }
        }

        async function postAction(action, boxId = -1, extraData = {}) {
            try {
                await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: action, box_id: boxId, ...extraData})
                });
                fetchData();
            } catch(e) {}
        }

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            const btn = document.getElementById('btn-sound');
            btn.innerText = webSoundEnabled ? '🔊 开启' : '🔇 静音';
            btn.style.color = webSoundEnabled ? '#00ff8c' : '#888';
        }

        async function saveCompareMin() {
            const val = parseInt(document.getElementById('compare-min-input').value) || 0;
            postAction('set_compare_min', -1, {compare_min: val});
        }

        function toggleCardExpand(boxId) {
            if (!currentUser) return;
            cardExpandedState[boxId] = !cardExpandedState[boxId];
            const body = document.getElementById(`fold-body-${boxId}`);
            const icon = document.getElementById(`toggle-icon-${boxId}`);
            if (body) {
                body.style.display = cardExpandedState[boxId] ? 'block' : 'none';
            }
            if (icon) {
                icon.innerText = cardExpandedState[boxId] ? '▲' : '▼';
            }
        }

        async function saveBoxParams(boxId) {
            const lower = parseFloat(document.getElementById(`input-lower-${boxId}`).value) || 0;
            const upper = parseFloat(document.getElementById(`input-upper-${boxId}`).value) || 0;
            const mid = parseFloat(document.getElementById(`input-mid-${boxId}`).value) || 0;
            const midOp = document.getElementById(`select-mid-op-${boxId}`).value;
            const dec = parseInt(document.getElementById(`input-dec-${boxId}`).value) || 0;
            const name = document.getElementById(`input-title-${boxId}`).value;
            postAction('update_box', boxId, {
                lower: lower, upper: upper, mid: mid, mid_op: midOp, decimal_places: dec, name: name
            });
        }

        async function fetchData() {
            try {
                const res = await fetch('/api/data');
                if (!res.ok) return;
                const data = await res.json();

                const btnMon = document.getElementById('btn-monitor');
                if (btnMon) {
                    btnMon.innerText = data.monitoring ? '⏸ 停止监控' : '▶ 开始监控';
                    if (data.monitoring) btnMon.classList.add('active'); else btnMon.classList.remove('active');
                }
                const btnGri = document.getElementById('btn-grille');
                if (btnGri) {
                    btnGri.innerText = data.script_running ? '⏸ 停止操作' : '▶ 开始操作';
                    if (data.script_running) btnGri.classList.add('active'); else btnGri.classList.remove('active');
                }

                const container = document.getElementById('cards-container');
                let html = '';
                let hasAlarm = false;

                data.boxes.forEach(box => {
                    if (box.is_alarm) hasAlarm = true;

                    let cardClass = 'card';
                    if (box.is_alarm) cardClass += ' alarm';
                    else if (box.is_warning) cardClass += ' warning';

                    let valClass = 'val-text';
                    if (box.is_alarm) valClass += ' alarm-text';
                    else if (box.is_warning) valClass += ' warning-text';

                    let trendHtml = '';
                    if (box.diff_text) {
                        if (box.diff_text.startsWith('+')) {
                            trendHtml = `<span style="color:#ff4d4d; font-size:12px; font-weight:bold; margin-right:4px;">▲ ${box.diff_text}</span>`;
                        } else if (box.diff_text.startsWith('-')) {
                            trendHtml = `<span style="color:#00ff8c; font-size:12px; font-weight:bold; margin-right:4px;">▼ ${box.diff_text}</span>`;
                        } else {
                            trendHtml = `<span style="color:#888; font-size:12px; margin-right:4px;">${box.diff_text}</span>`;
                        }
                    }

                    const isExpanded = !!cardExpandedState[box.id];
                    const toggleDisplay = currentUser ? 'inline-block' : 'none';
                    const bodyDisplay = (currentUser && isExpanded) ? 'block' : 'none';
                    const iconChar = isExpanded ? '▲' : '▼';

                    html += `
                    <div class="${cardClass}">
                        <div class="card-header">
                            <div class="card-title-box">
                                <span class="card-title">${box.name}</span>
                                <span id="toggle-icon-${box.id}" class="toggle-icon" style="display:${toggleDisplay};" onclick="toggleCardExpand(${box.id})">${iconChar}</span>
                            </div>
                            <div class="card-header-right">
                                ${box.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${box.id})">🚨 消除</button>` : ''}
                            </div>
                        </div>

                        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
                            <div class="val-container">
                                ${trendHtml}
                                <span class="${valClass}">${box.val_str}</span>
                            </div>
                            <span style="font-size:11px; color:#888;">${box.last_time || ''}</span>
                        </div>

                        <div id="fold-body-${box.id}" class="fold-body" style="display:${bodyDisplay};">
                            <div class="setting-row">
                                <label>名称:</label>
                                <input type="text" id="input-title-${box.id}" value="${box.name}" class="setting-input" style="width:80px; text-align:left;">
                                <label>下限:</label>
                                <input type="number" step="any" id="input-lower-${box.id}" value="${box.lower}" class="setting-input">
                                <label>上限:</label>
                                <input type="number" step="any" id="input-upper-${box.id}" value="${box.upper}" class="setting-input">
                            </div>
                            <div class="setting-row">
                                <label>预警:</label>
                                <select id="select-mid-op-${box.id}" style="background:rgba(0,0,0,0.5); color:#ffaa00; border:1px solid rgba(255,255,255,0.2); border-radius:4px; font-size:11px;">
                                    <option value=">" ${box.mid_op === '>' ? 'selected' : ''}>></option>
                                    <option value="<" ${box.mid_op === '<' ? 'selected' : ''}><</option>
                                    <option value="=" ${box.mid_op === '=' ? 'selected' : ''}>=</option>
                                </select>
                                <input type="number" step="any" id="input-mid-${box.id}" value="${box.mid_val}" class="setting-input">
                                <label>小数位:</label>
                                <input type="number" id="input-dec-${box.id}" value="${box.decimal_places}" class="setting-input" style="width:30px;">
                                <button class="btn-action" style="background:#0088cc; padding:2px 8px; margin-left:auto;" onclick="saveBoxParams(${box.id})">保存</button>
                            </div>
                            <div class="log-title">📋 历史记录</div>
                            <div class="log-list">
                                ${(box.logs || []).map(l => `<div class="log-item">${l}</div>`).join('')}
                            </div>
                        </div>
                    </div>`;
                });

                container.innerHTML = html;

                if (hasAlarm && webSoundEnabled) {
                    playWebBeep();
                }

            } catch(e) {}
        }

        function playWebBeep() {
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(800, ctx.currentTime);
                osc.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + 0.2);
            } catch(e) {}
        }

        updateAuthUI();
        fetchData();
        setInterval(fetchData, 1000);
    </script>
</body>
</html>
"""


# ==================== 主控窗口 ====================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🖥️ OCR 悬浮监控与自动化中控")
        self.resize(320, 180)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        self.boxes = []
        self.scripts = []
        self.users = {"admin": "admin123"}
        self.check_interval = 1.0
        self.compare_minutes = 5
        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        
        self.monitoring = False
        self.script_running = False
        self.edit_mode = False
        self.panel_hidden = False

        self.sound_player = AlarmSoundPlayer()
        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self.toggle_script_running)
        self.f12_listener.start()

        self.reader = None
        self._init_ddddocr()

        self.monitor_thread = None
        self.script_thread = None

        self.load_config()
        self.init_ui()

        if FLASK_AVAILABLE:
            self.start_flask_server()

    def _init_ddddocr(self):
        def _load():
            try:
                import ddddocr
                self.reader = ddddocr.DdddOcr(show_ad=False)
                if self.monitor_thread:
                    self.monitor_thread.set_reader(self.reader)
            except Exception as e:
                print(f"ddddocr 初始化失败: {e}")
        threading.Thread(target=_load, daemon=True).start()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { background-color: #1a1a26; color: white; font-family: "Segoe UI", sans-serif; }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8); color: white; border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px; padding: 5px 8px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
            QPushButton.active { background-color: #ff3333; color: white; }
            QLabel { font-size: 11px; font-weight: bold; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("🤖 自动化及数据监控中控台")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #00ff8c; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        r1 = QHBoxLayout()
        btn_add = QPushButton("➕ 新增区域")
        btn_add.clicked.connect(self._add_new_box)
        btn_pick = QPushButton("📐 选区拾取")
        btn_pick.clicked.connect(self._pick_screen_region)
        self.btn_edit = QPushButton("✏️ 批量编辑")
        self.btn_edit.clicked.connect(self.toggle_edit_mode)
        r1.addWidget(btn_add)
        r1.addWidget(btn_pick)
        r1.addWidget(self.btn_edit)
        layout.addLayout(r1)

        r2 = QHBoxLayout()
        btn_script_mgr = QPushButton("📜 脚本管理")
        btn_script_mgr.clicked.connect(self._open_script_manager)
        self.btn_mon = QPushButton("▶ 开始监控")
        self.btn_mon.setStyleSheet("background-color: #2e9a58; color: white;")
        self.btn_mon.clicked.connect(self.toggle_monitor)
        
        self.btn_script_run = QPushButton("▶ 开始操作")
        self.btn_script_run.setStyleSheet("background-color: #0088cc; color: white;")
        self.btn_script_run.clicked.connect(self.toggle_script_running)

        r2.addWidget(btn_script_mgr)
        r2.addWidget(self.btn_mon)
        r2.addWidget(self.btn_script_run)
        layout.addLayout(r2)

        r3 = QHBoxLayout()
        btn_ocr_adjust = QPushButton("⚙️ OCR 调整")
        btn_ocr_adjust.clicked.connect(self._open_ocr_adjust)
        btn_web_ip = QPushButton("📱 手机中控")
        btn_web_ip.clicked.connect(self._show_web_info)
        self.btn_hide_panel = QPushButton("👁 隐藏面板")
        self.btn_hide_panel.clicked.connect(self.toggle_panel_hidden)
        
        r3.addWidget(btn_ocr_adjust)
        r3.addWidget(btn_web_ip)
        r3.addWidget(self.btn_hide_panel)
        layout.addLayout(r3)

    def _open_script_manager(self):
        dlg = ScriptManagerDialog(self.scripts, parent=self)
        dlg.exec()

    def _open_ocr_adjust(self):
        dlg = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)
            self.save_config()

    def _show_web_info(self):
        ip = get_local_ip()
        msg = f"📱 局域网 Web 中控访问地址:\n\nhttp://{ip}:5000\n\n请使用手机或同局域网设备浏览器访问。"
        QMessageBox.information(self, "📱 手机中控地址", msg)

    def _add_new_box(self):
        self.create_box(100, 100, 150, 50, name=f"区域{len(self.boxes)+1}")

    def _pick_screen_region(self):
        self.setWindowOpacity(0.0)
        QApplication.processEvents()
        time.sleep(0.2)
        picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.setWindowOpacity(1.0)
            self.activateWindow()
            if w > 0 and h > 0:
                self.create_box(x, y, w, h, name=f"区域{len(self.boxes)+1}")

        picker.coord_selected.connect(on_picked)
        picker.showFullScreen()

    def create_box(self, x, y, w, h, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, mid_op=">", box_id=None):
        if box_id is None:
            existing_ids = [b.box_id for b in self.boxes]
            box_id = max(existing_ids) + 1 if existing_ids else 0

        box = OverlayRegionWidget(box_id, x, y, w, h, name=name, lower=lower, mid_val=mid_val, upper=upper, decimal_places=decimal_places, mid_op=mid_op)
        box.delete_requested.connect(self.delete_box)
        box.alarm_cleared.connect(self._check_all_alarms)
        box.mute_toggled.connect(self._check_all_alarms)
        box.set_edit_mode(self.edit_mode)
        box.set_panel_hidden(self.panel_hidden)
        box.show()
        self.boxes.append(box)
        self.save_config()

    def delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self._check_all_alarms()
            self.save_config()

    def toggle_edit_mode(self):
        self.edit_mode = not self.edit_mode
        self.btn_edit.setText("✔️ 完成编辑" if self.edit_mode else "✏️ 批量编辑")
        for box in self.boxes:
            box.set_edit_mode(self.edit_mode)

    def toggle_panel_hidden(self):
        self.panel_hidden = not self.panel_hidden
        self.btn_hide_panel.setText("👁 显示面板" if self.panel_hidden else "👁 隐藏面板")
        for box in self.boxes:
            box.set_panel_hidden(self.panel_hidden)

    def toggle_monitor(self):
        if not self.monitoring:
            self.monitoring = True
            self.btn_mon.setText("⏸ 停止监控")
            self.btn_mon.setStyleSheet("background-color: #ff3333; color: white;")
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(self.boxes, interval=self.check_interval, ocr_params=self.ocr_params, scale=scale)
            if self.reader:
                self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self.update_monitor_data)
            self.monitor_thread.start()
        else:
            self.monitoring = False
            self.btn_mon.setText("▶ 开始监控")
            self.btn_mon.setStyleSheet("background-color: #2e9a58; color: white;")
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None

    def update_monitor_data(self, box, time_str, val, raw_text):
        if box not in self.boxes: return

        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            if val > box.upper or val < box.lower:
                if box.user_cleared_alarm and box.cleared_val == val:
                    box.set_alarm_state(False)
                else:
                    box.user_cleared_alarm = False
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.cleared_val = None
                box.set_alarm_state(False)

            is_warn = box.check_mid_condition(val)
            box.set_warning_state(is_warn)
        else:
            box.set_alarm_state(False)
            box.set_warning_state(False)

        self._check_all_alarms()

    def _check_all_alarms(self):
        has_active_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if has_active_alarm:
            self.sound_player.play()
        else:
            self.sound_player.stop()

    def toggle_script_running(self):
        if not self.script_running:
            if not self.scripts:
                QMessageBox.warning(self, "提示", "请先在【脚本管理】中创建自动化脚本！")
                return
            self.script_running = True
            self.btn_script_run.setText("⏸ 停止操作")
            self.btn_script_run.setStyleSheet("background-color: #ff3333; color: white;")
            self.script_thread = ScriptRunnerThread(self.scripts[0])
            self.script_thread.start()
        else:
            self.script_running = False
            self.btn_script_run.setText("▶ 开始操作")
            self.btn_script_run.setStyleSheet("background-color: #0088cc; color: white;")
            if self.script_thread:
                self.script_thread.stop()
                self.script_thread.wait()
                self.script_thread = None

    def start_flask_server(self):
        app = Flask(__name__)

        @app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @app.route('/api/data')
        def get_data():
            boxes_data = []
            for box in self.boxes:
                past_val = box.get_past_value(self.compare_minutes)
                diff_text = ""
                try:
                    curr_val = float(box.lbl_result.text())
                    if past_val is not None:
                        diff = curr_val - past_val
                        dp = box.decimal_places
                        diff_text = f"{diff:+.{dp}f}"
                except ValueError:
                    diff_text = ""

                logs = [box.list_widget.item(i).text() for i in range(box.list_widget.count())]

                boxes_data.append({
                    'id': box.box_id,
                    'name': box.name,
                    'lower': box.lower,
                    'upper': box.upper,
                    'mid_val': box.mid_val,
                    'mid_op': box.mid_op,
                    'decimal_places': box.decimal_places,
                    'is_alarm': box.is_alarm,
                    'is_warning': box.is_warning,
                    'val_str': box.lbl_result.text(),
                    'last_time': logs[0].split(']')[0].replace('[', '') if logs else '',
                    'logs': logs,
                    'diff_text': diff_text
                })

            return jsonify({
                'monitoring': self.monitoring,
                'script_running': self.script_running,
                'boxes': boxes_data
            })

        @app.route('/api/login', methods=['POST'])
        def login():
            req = request.json or {}
            u, p = req.get('username'), req.get('password')
            if u in self.users and self.users[u] == p:
                return jsonify({'status': 'ok'})
            return jsonify({'status': 'error'}), 401

        @app.route('/api/users', methods=['GET', 'POST'])
        def users_mgmt():
            if request.method == 'GET':
                return jsonify(list(self.users.keys()))
            req = request.json or {}
            action = req.get('action')
            username = req.get('username')
            password = req.get('password')
            if action == 'add':
                if not username or not password: return jsonify({'message': '无效参数'}), 400
                self.users[username] = password
                self.save_config()
                return jsonify({'status': 'ok'})
            elif action == 'delete':
                if username in self.users and username != 'admin':
                    del self.users[username]
                    self.save_config()
                    return jsonify({'status': 'ok'})
                return jsonify({'message': '无法删除管理员账户'}), 400
            return jsonify({'message': '无效操作'}), 400

        @app.route('/api/action', methods=['POST'])
        def handle_action():
            req = request.json or {}
            action = req.get('action')
            box_id = req.get('box_id', -1)

            if action == 'toggle_monitor':
                QTimer.singleShot(0, self.toggle_monitor)
            elif action == 'toggle_grille':
                QTimer.singleShot(0, self.toggle_script_running)
            elif action == 'exit_app':
                QTimer.singleShot(100, QApplication.quit)
            elif action == 'set_compare_min':
                cmin = req.get('compare_min', 5)
                self.compare_minutes = cmin
                self.save_config()
            elif action == 'clear_alarm' and box_id >= 0:
                for b in self.boxes:
                    if b.box_id == box_id:
                        QTimer.singleShot(0, b._on_clear_alarm)
                        break
            elif action == 'update_box' and box_id >= 0:
                for b in self.boxes:
                    if b.box_id == box_id:
                        b._on_lower_changed(float(req.get('lower', b.lower)))
                        b._on_upper_changed(float(req.get('upper', b.upper)))
                        b._on_mid_changed(float(req.get('mid', b.mid_val)))
                        b._on_mid_op_changed(req.get('mid_op', b.mid_op))
                        b._on_dec_changed(int(req.get('decimal_places', b.decimal_places)))
                        b._on_title_changed(req.get('name', b.name))
                        self.save_config()
                        break

            return jsonify({'status': 'ok'})

        def run_flask():
            app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

        t = threading.Thread(target=run_flask, daemon=True)
        t.start()

    def load_config(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.check_interval = data.get("check_interval", 1.0)
                    self.compare_minutes = data.get("compare_minutes", 5)
                    self.ocr_params = data.get("ocr_params", {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2})
                    self.scripts = data.get("scripts", [])
                    self.users = data.get("users", {"admin": "admin123"})
                    
                    boxes_data = data.get("boxes", [])
                    for b in boxes_data:
                        self.create_box(
                            b.get("x", 100), b.get("y", 100), b.get("w", 150), b.get("h", 50),
                            name=b.get("name", "区域"),
                            lower=b.get("lower", 0.0),
                            mid_val=b.get("mid_val", 50.0),
                            upper=b.get("upper", 100.0),
                            decimal_places=b.get("decimal_places", 0),
                            mid_op=b.get("mid_op", ">"),
                            box_id=b.get("id", None)
                        )
            except Exception as e:
                print(f"读取配置失败: {e}")

    def save_config(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.json")
        boxes_data = []
        for box in self.boxes:
            boxes_data.append({
                "id": box.box_id,
                "x": box.capture_x,
                "y": box.capture_y,
                "w": box.capture_w,
                "h": box.capture_h,
                "name": box.name,
                "lower": box.lower,
                "mid_val": box.mid_val,
                "upper": box.upper,
                "decimal_places": box.decimal_places,
                "mid_op": box.mid_op
            })
        data = {
            "check_interval": self.check_interval,
            "compare_minutes": self.compare_minutes,
            "ocr_params": self.ocr_params,
            "scripts": self.scripts,
            "users": self.users,
            "boxes": boxes_data
        }
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def closeEvent(self, event):
        self.f12_listener.stop()
        self.sound_player.stop()
        if self.monitor_thread:
            self.monitor_thread.stop()
        if self.script_thread:
            self.script_thread.stop()
        for b in self.boxes:
            b.close()
        self.save_config()
        event.accept()


# ==================== 程序主入口 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
