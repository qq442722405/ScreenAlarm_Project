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
    QDialog, QFormLayout, QDialogButtonBox, QComboBox, QMenu
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

try:
    import ddddocr
    DDDDOCR_AVAILABLE = True
except ImportError:
    DDDDOCR_AVAILABLE = False


# ==================== 路径配置 ====================
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_JSON_PATH = os.path.join(ROOT_DIR, "脚本自定义添加脚本.json")
CONFIG_JSON_PATH = os.path.join(ROOT_DIR, "config.json")
USERS_JSON_PATH = os.path.join(ROOT_DIR, "users.json")


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
        sound_path = os.path.join(ROOT_DIR, "警报声.mp3")
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
            QDialog { background-color: #1a1a26; color: white; font-family: "Microsoft YaHei", "微软雅黑"; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; font-family: "Microsoft YaHei", "微软雅黑"; }
            QDoubleSpinBox, QSpinBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
                font-family: "Microsoft YaHei", "微软雅黑";
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: bold;
                font-family: "Microsoft YaHei", "微软雅黑";
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
        self.btn_pick.setStyleSheet("background-color: #0088cc; color: white; font-size: 12px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
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
        self.lbl_ocr_result.setStyleSheet("color: #00ff8c; font-size: 13px; font-weight: bold; background: rgba(0,0,0,0.4); padding: 6px; border-radius: 4px; font-family: 'Microsoft YaHei', '微软雅黑';")
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
        self.resize(320, 240)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; font-family: "Microsoft YaHei", "微软雅黑"; }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.9);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                font-family: "Microsoft YaHei", "微软雅黑", Consolas, monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #0088cc; color: white; border: none;
                border-radius: 4px; padding: 4px 12px; font-weight: bold; font-family: "Microsoft YaHei", "微软雅黑";
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


# ==================== 单点位置选择器 ====================
class SinglePointPicker(QWidget):
    point_selected = Signal(int, int)

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

        self.label = QLabel("🖱 请点击屏幕选择目标点击位置 (Esc 取消)", self)
        self.label.setStyleSheet("color: white; background: rgba(0,0,0,220); padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            self.point_selected.emit(pos.x(), pos.y())
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


# ==================== 自定义脚本编辑弹窗 ====================
class AddScriptDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("➕ 自定义添加脚本")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a26; color: white; font-family: "Microsoft YaHei", "微软雅黑"; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; font-family: "Microsoft YaHei", "微软雅黑"; }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: rgba(26, 26, 38, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 3px;
                font-weight: bold;
                font-family: "Microsoft YaHei", "微软雅黑";
            }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.8);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-family: "Microsoft YaHei", "微软雅黑";
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.9); }
            QListWidget {
                background-color: rgba(10, 10, 15, 0.8);
                color: #00ff8c;
                border: 1px solid rgba(255,255,255,0.2);
                border-radius: 4px;
                font-family: "Microsoft YaHei", "微软雅黑";
            }
        """)

        self.steps = []  # [{type: 'click', x, y}, {type: 'delay', seconds}]

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.edit_name = QLineEdit("自定义脚本")
        
        # 需求五：循环次数设为 -1 到 99999，填入 -1 即无限循环
        self.spin_loop = QSpinBox()
        self.spin_loop.setRange(-1, 99999)
        self.spin_loop.setValue(1)
        self.spin_loop.setToolTip("-1 表示无限循环")

        form_layout.addRow("脚本名称:", self.edit_name)
        form_layout.addRow("循环次数 (-1无限):", self.spin_loop)
        layout.addLayout(form_layout)

        layout.addWidget(QLabel("📋 步骤列表:"))
        self.list_steps = QListWidget()
        layout.addWidget(self.list_steps)

        btn_layout1 = QHBoxLayout()
        self.btn_add_click = QPushButton("📍 添加点击位置")
        self.btn_add_click.clicked.connect(self._add_click_step)

        self.spin_delay_sec = CleanDoubleSpinBox()
        self.spin_delay_sec.setRange(0.1, 3600.0)
        self.spin_delay_sec.setValue(1.0)
        self.spin_delay_sec.setFixedWidth(50)

        self.btn_add_delay = QPushButton("⏱️ 添加延迟(秒)")
        self.btn_add_delay.clicked.connect(self._add_delay_step)

        btn_layout1.addWidget(self.btn_add_click)
        btn_layout1.addWidget(self.spin_delay_sec)
        btn_layout1.addWidget(self.btn_add_delay)
        layout.addLayout(btn_layout1)

        btn_layout2 = QHBoxLayout()
        self.btn_del_step = QPushButton("🗑️ 删除选中")
        self.btn_del_step.clicked.connect(self._del_selected_step)

        self.btn_clear_steps = QPushButton("🧹 清空步骤")
        self.btn_clear_steps.clicked.connect(self._clear_all_steps)

        btn_layout2.addWidget(self.btn_del_step)
        btn_layout2.addWidget(self.btn_clear_steps)
        layout.addLayout(btn_layout2)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _add_click_step(self):
        self.hide()
        time.sleep(0.2)
        self.picker = SinglePointPicker()

        def on_point(x, y):
            self.show()
            step = {'type': 'click', 'x': x, 'y': y}
            self.steps.append(step)
            self.list_steps.addItem(f"🖱️ 点击坐标: ({x}, {y})")

        self.picker.point_selected.connect(on_point)
        self.picker.showFullScreen()

    def _add_delay_step(self):
        sec = self.spin_delay_sec.value()
        step = {'type': 'delay', 'seconds': sec}
        self.steps.append(step)
        self.list_steps.addItem(f"⏱️ 延迟等待: {sec} 秒")

    def _del_selected_step(self):
        row = self.list_steps.currentRow()
        if 0 <= row < len(self.steps):
            self.list_steps.takeItem(row)
            self.steps.pop(row)

    def _clear_all_steps(self):
        self.list_steps.clear()
        self.steps.clear()

    def get_script_data(self):
        return {
            'name': self.edit_name.text().strip() or "未命名脚本",
            'loop': self.spin_loop.value(),
            'steps': self.steps
        }


# ==================== 脚本自动执行线程 ====================
class ScriptRunnerThread(QThread):
    def __init__(self, scripts, parent=None):
        super().__init__(parent)
        self.scripts = scripts
        self.running = True

    def stop(self):
        self.running = False

    def _exec_step(self, user32, step):
        stype = step.get('type')
        if stype == 'click':
            cx, cy = step.get('x', 0), step.get('y', 0)
            user32.SetCursorPos(int(cx), int(cy))
            time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
            time.sleep(0.05)
            user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
        elif stype == 'delay':
            sec = step.get('seconds', 1.0)
            end_t = time.time() + sec
            while self.running and time.time() < end_t:
                self.msleep(50)

    def run(self):
        user32 = ctypes.windll.user32
        while self.running:
            for script in self.scripts:
                if not self.running: break
                if not script.get('enabled', True): continue

                loop_cnt = script.get('loop', 1)
                steps = script.get('steps', [])

                # 需求五：支持 -1 无限循环
                if loop_cnt == -1:
                    while self.running and script.get('enabled', True):
                        for step in steps:
                            if not self.running or not script.get('enabled', True): break
                            self._exec_step(user32, step)
                else:
                    for l in range(loop_cnt):
                        if not self.running or not script.get('enabled', True): break
                        for step in steps:
                            if not self.running or not script.get('enabled', True): break
                            self._exec_step(user32, step)

            self.msleep(100)


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
        self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; font-family: 'Microsoft YaHei', '微软雅黑';")
        panel_layout = QVBoxLayout(self.control_panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(3)

        self.row1_container = QWidget()
        row1_layout = QHBoxLayout(self.row1_container)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(4)

        self.lbl_title = QLabel(self.name)
        self.lbl_title.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")

        self.edit_title = QLineEdit(self.name)
        self.edit_title.setStyleSheet("background-color: rgba(42, 42, 60, 0.5); color: #00ff8c; font-size: 11px; font-weight: bold; border: 1px solid #00ff8c; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.edit_title.setVisible(False)
        self.edit_title.textChanged.connect(self._on_title_changed)

        self.lbl_result = QLabel("--")
        self.lbl_result.setMaximumWidth(60)
        self.lbl_result.setStyleSheet("color: #a0a0a0; font-size: 11px; font-weight: bold; margin-left: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")

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
        self.lbl_lower.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_lower = CleanDoubleSpinBox()
        self.spin_lower.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_lower.setAlignment(Qt.AlignCenter)
        self.spin_lower.setRange(-99999.0, 99999.0)
        self.spin_lower.setValue(self.lower)
        self.spin_lower.setFixedSize(36, 20)
        self.spin_lower.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_lower.valueChanged.connect(self._on_lower_changed)

        self.lbl_upper = QLabel("上限:")
        self.lbl_upper.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_upper = CleanDoubleSpinBox()
        self.spin_upper.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_upper.setAlignment(Qt.AlignCenter)
        self.spin_upper.setRange(-99999.0, 99999.0)
        self.spin_upper.setValue(self.upper)
        self.spin_upper.setFixedSize(36, 20)
        self.spin_upper.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_upper.valueChanged.connect(self._on_upper_changed)

        self.btn_delete = QPushButton("❌")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet("QPushButton { background-color: #ff3333; color: white; border: none; border-radius: 3px; font-weight: bold; font-size: 10px; font-family: 'Microsoft YaHei', '微软雅黑'; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self))

        row2_layout.addWidget(self.lbl_lower)
        row2_layout.addWidget(self.spin_lower)
        row2_layout.addWidget(self.lbl_upper)
        row2_layout.addWidget(self.spin_upper)
        row2_layout.addStretch()
        row2_layout.addWidget(self.btn_delete)
        panel_layout.addWidget(self.row2_container)

        self.row3_container = QWidget()
        row3_layout = QHBoxLayout(self.row3_container)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(3)

        self.lbl_mid = QLabel("预警:")
        self.lbl_mid.setStyleSheet("color: #ffaa00; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
        
        self.combo_mid_op = QComboBox()
        self.combo_mid_op.addItems([">", "<", "="])
        self.combo_mid_op.setCurrentText(self.mid_op)
        self.combo_mid_op.setFixedSize(32, 20)
        self.combo_mid_op.setStyleSheet("background-color: rgba(26, 26, 38, 0.8); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.combo_mid_op.currentTextChanged.connect(self._on_mid_op_changed)

        self.spin_mid = CleanDoubleSpinBox()
        self.spin_mid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_mid.setAlignment(Qt.AlignCenter)
        self.spin_mid.setRange(-99999.0, 99999.0)
        self.spin_mid.setValue(self.mid_val)
        self.spin_mid.setFixedSize(36, 20)
        self.spin_mid.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #ffaa00; border: 1px solid #ffaa00; font-size: 10px; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_mid.valueChanged.connect(self._on_mid_changed)

        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑'; } QPushButton:hover { background-color: #ff6666; }")
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        row3_layout.addWidget(self.lbl_mid)
        row3_layout.addWidget(self.combo_mid_op)
        row3_layout.addWidget(self.spin_mid)
        row3_layout.addStretch()
        row3_layout.addWidget(self.btn_clear_alarm)
        panel_layout.addWidget(self.row3_container)

        self.row4_container = QWidget()
        row4_layout = QHBoxLayout(self.row4_container)
        row4_layout.setContentsMargins(0, 0, 0, 0)
        row4_layout.setSpacing(3)

        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedSize(22, 20)
        self.btn_mute.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; font-family: 'Microsoft YaHei', '微软雅黑'; } QPushButton:hover { background-color: rgba(255,255,255,0.3); }")
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.lbl_dec = QLabel("小数点:")
        self.lbl_dec.setStyleSheet("color: #a0a0a0; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_dec = QSpinBox()
        self.spin_dec.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_dec.setAlignment(Qt.AlignCenter)
        self.spin_dec.setRange(0, 4)
        self.spin_dec.setValue(self.decimal_places)
        self.spin_dec.setFixedSize(24, 20)
        self.spin_dec.setStyleSheet("background-color: rgba(26, 26, 38, 0.5); color: #00ff8c; border: 1px solid #00ff8c; font-size: 10px; border-radius: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        self.spin_dec.valueChanged.connect(self._on_dec_changed)

        self.btn_show_log = QPushButton("📋 日志")
        self.btn_show_log.setFixedSize(40, 20)
        self.btn_show_log.setStyleSheet("QPushButton { background-color: rgba(0, 136, 204, 0.8); color: white; border: none; border-radius: 3px; font-size: 10px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑'; } QPushButton:hover { background-color: #0088cc; }")
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

    def _on_lower_changed(self, val):
        self.lower = val

    def _on_mid_op_changed(self, text):
        self.mid_op = text

    def _on_mid_changed(self, val):
        self.mid_val = val

    def _on_upper_changed(self, val):
        self.upper = val

    def _on_dec_changed(self, val):
        self.decimal_places = val

    def _on_title_changed(self, text):
        self.name = text
        self.lbl_title.setText(text)

    def check_mid_condition(self, val):
        if val is None: return False
        if self.mid_op == '>':
            return val > self.mid_val
        elif self.mid_op == '<':
            return val < self.mid_val
        elif self.mid_op == '=':
            return abs(val - self.mid_val) < 1e-4
        return False

    def update_result_display(self, val, raw_text=""):
        if val is not None:
            dp = getattr(self, 'decimal_places', 2)
            self.lbl_result.setText(f"{val:.{dp}f}")
            if val > self.upper or val < self.lower:
                self.lbl_result.setStyleSheet("color: #ff4d4d; font-size: 11px; font-weight: bold; margin-left: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
            elif self.check_mid_condition(val):
                self.lbl_result.setStyleSheet("color: #ffaa00; font-size: 11px; font-weight: bold; margin-left: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
            else:
                self.lbl_result.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold; margin-left: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")
        else:
            disp = f"({raw_text})" if raw_text else "--"
            self.lbl_result.setText(f"{disp}")
            self.lbl_result.setStyleSheet("color: #ff6666; font-size: 11px; font-weight: bold; margin-left: 2px; font-family: 'Microsoft YaHei', '微软雅黑';")

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
        if not self.history_records:
            return None
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
                self.control_panel.setStyleSheet("background-color: transparent; border: none; font-family: 'Microsoft YaHei', '微软雅黑';")
                self.row1_container.setVisible(False)
                self.row2_container.setVisible(False)
                self.row3_container.setVisible(True)
                self.row4_container.setVisible(False)
                self.lbl_mid.setVisible(False)
                self.combo_mid_op.setVisible(False)
                self.spin_mid.setVisible(False)
                self.btn_clear_alarm.setVisible(True)
            else:
                self.control_panel.setVisible(False)
        else:
            self.control_panel.setVisible(True)
            self.control_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.85); border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; font-family: 'Microsoft YaHei', '微软雅黑';")
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
        total_w = max(self.capture_w, 140)
        if self.panel_hidden:
            panel_h = 28 if self.is_alarm else 0
        else:
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
        self.set_alarm_state(False)
        self.alarm_cleared.emit()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        btn_txt = "🔇" if self.is_muted else "🔊"
        btn_style = "QPushButton { background-color: #e65100; color: white; border: none; border-radius: 3px; font-size: 10px; font-family: 'Microsoft YaHei', '微软雅黑'; }" if self.is_muted else "QPushButton { background-color: rgba(255,255,255,0.15); color: white; border: none; border-radius: 3px; font-size: 10px; font-family: 'Microsoft YaHei', '微软雅黑'; }"
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
        self.label.setStyleSheet("color: white; background: rgba(0,0,0,220); padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑';")
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


# ==================== Flask 网页/手机端 WEB 交互界面 ====================
# 需求三 & 需求四：改字体为微软雅黑，并删除对比（分钟）相关设置与行
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
        body { background: #121218; color: #e0e0e0; font-family: "Microsoft YaHei", "微软雅黑", sans-serif; padding: 12px; }
        
        .container { max-width: 600px; margin: 0 auto; width: 100%; }

        .header { background: #1a1a26; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; gap: 8px; }
        
        .header-row1 { display: flex; justify-content: space-between; align-items: center; width: 100%; flex-wrap: wrap; gap: 6px; }
        .header-title-box { display: flex; align-items: center; gap: 6px; }
        .header-tools-box { display: flex; align-items: center; gap: 6px; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; }
        .toggle-icon { cursor: pointer; font-size: 13px; color: #00ff8c; font-weight: bold; user-select: none; padding: 2px 6px; border-radius: 4px; background: rgba(0,255,140,0.1); }
        .toggle-icon:hover { background: rgba(0,255,140,0.2); }

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
        .card-title-box { display: flex; align-items: center; gap: 8px; flex-grow: 1; overflow: hidden; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .card-header-right { display: flex; align-items: center; gap: 8px; margin-left: auto; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .trend-up { color: #ff4d4d; font-weight: bold; font-size: 13px; margin-right: 6px; }
        .trend-down { color: #00ff8c; font-weight: bold; font-size: 13px; margin-right: 6px; }
        .trend-flat { color: #aaaaaa; font-weight: bold; font-size: 13px; margin-right: 6px; }

        .val-container { display: flex; align-items: center; font-size: 18px; font-weight: bold; font-family: monospace, "Microsoft YaHei", "微软雅黑"; }
        .val-text { color: #00ff8c; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 48px; text-align: center; font-size: 11px; }

        .log-title { margin-top: 6px; font-size: 11px; color: #888; font-weight: bold; }
        .log-list { margin-top: 4px; background: rgba(0,0,0,0.4); border-radius: 6px; padding: 6px 8px; font-size: 11px; font-family: monospace, "Microsoft YaHei", "微软雅黑"; height: 110px; overflow-y: auto; color: #00ff8c; }
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
                    <span id="btn-toggle-all" class="toggle-icon" onclick="toggleCollapseAll()">▼</span>
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

            <div id="header-row3" class="header-row3" style="display: none;">
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div id="cards-container"></div>
    </div>

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
        let isExpanded = false;
        let webSoundEnabled = false;
        let currentUser = localStorage.getItem('currentUser') || null;

        function updateAuthUI() {
            if (currentUser) {
                document.getElementById('login-box').style.display = 'none';
                document.getElementById('user-box').style.display = 'inline-flex';
                document.getElementById('current-username').innerText = '👤 ' + currentUser;
                
                document.getElementById('btn-toggle-all').style.display = 'inline-block';
                document.getElementById('header-row3').style.display = 'flex';
            } else {
                document.getElementById('login-box').style.display = 'inline-flex';
                document.getElementById('user-box').style.display = 'none';

                document.getElementById('btn-toggle-all').style.display = 'none';
                document.getElementById('header-row3').style.display = 'none';

                isExpanded = false;
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

        function toggleCollapseAll() {
            if (!currentUser) return;
            isExpanded = !isExpanded;
            document.getElementById('btn-toggle-all').innerText = isExpanded ? '▲' : '▼';
            document.querySelectorAll('.fold-body').forEach(el => {
                el.style.display = isExpanded ? 'block' : 'none';
            });
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

                let diffHtml = '';
                if (box.trend === 'up') {
                    diffHtml = `<span class="trend-up">▲ ${box.diff_str}</span>`;
                } else if (box.trend === 'down') {
                    diffHtml = `<span class="trend-down">▼ ${box.diff_str}</span>`;
                } else if (box.diff_str) {
                    diffHtml = `<span class="trend-flat">▬ ${box.diff_str}</span>`;
                }

                let header = card.querySelector('.card-header');
                if (!header) {
                    const logsHtml = (box.logs || []).map(l => `<div class="log-item">${l}</div>`).join('');
                    card.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box">
                                <span class="card-title">${box.name}</span>
                            </div>
                            <div class="card-header-right">
                                <div class="val-container">
                                    <span id="diff-${box.id}">${diffHtml}</span>
                                    <span id="val-${box.id}" class="${valClass}">${box.val_text}</span>
                                </div>
                                <span id="alarm-btn-box-${box.id}">
                                    ${box.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${box.id})">🚨 消除</button>` : ''}
                                </span>
                                <button id="mute-btn-${box.id}" class="btn-action ${box.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}" onclick="postAction('toggle_mute', ${box.id})">${box.is_muted ? '🔇 静音' : '🔊 声音'}</button>
                            </div>
                        </div>
                        <div class="fold-body" style="display: ${(currentUser && isExpanded) ? 'block' : 'none'};">
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
            compare_min = 5.0

            for b in self.main_win.boxes:
                val_text = b.lbl_result.text()
                try:
                    val = float(val_text)
                except ValueError:
                    val = None

                past_val = b.get_past_value(compare_min)
                diff_val = None
                diff_str = ""
                trend = 'none'

                if val is not None and past_val is not None:
                    diff_val = val - past_val
                    dp = getattr(b, 'decimal_places', 0)
                    if diff_val > 0:
                        trend = 'up'
                        diff_str = f"+{diff_val:.{dp}f}"
                    elif diff_val < 0:
                        trend = 'down'
                        diff_str = f"{diff_val:.{dp}f}"
                    else:
                        trend = 'flat'
                        diff_str = f"0.{'0'*dp}" if dp > 0 else "0"

                logs = []
                for i in range(b.list_widget.count()):
                    logs.append(b.list_widget.item(i).text())

                boxes_data.append({
                    'id': b.box_id,
                    'name': b.name,
                    'lower': b.lower,
                    'mid_op': getattr(b, 'mid_op', '>'),
                    'mid_val': getattr(b, 'mid_val', 50.0),
                    'upper': b.upper,
                    'val_text': val_text,
                    'val': val,
                    'is_alarm': b.is_alarm,
                    'is_muted': b.is_muted,
                    'diff_str': diff_str,
                    'trend': trend,
                    'logs': logs
                })

            return jsonify({
                'monitoring': getattr(self.main_win, 'is_monitoring', False),
                'grille': getattr(self.main_win, 'is_script_running', False),
                'boxes': boxes_data,
                'users': getattr(self.main_win, 'user_db', {})
            })

        @self.app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.get_json() or {}
            action = data.get('action')
            box_id = data.get('box_id', -1)
            req_data = data.get('data', {})

            self.action_requested.emit(action, box_id, req_data)
            return jsonify({'status': 'ok'})

        @self.app.route('/api/login', methods=['POST'])
        def handle_login():
            data = request.get_json() or {}
            username = data.get('username')
            password = data.get('password')
            users = getattr(self.main_win, 'user_db', {'admin': '123456'})
            if username in users and users[username] == password:
                return jsonify({'status': 'ok'})
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

        @self.app.route('/api/users', methods=['POST'])
        def handle_users():
            data = request.get_json() or {}
            act = data.get('action')
            username = data.get('username')
            password = data.get('password')

            if act == 'add' and username and password:
                self.main_win.user_db[username] = password
                self.main_win.save_user_db()
                return jsonify({'status': 'ok'})
            elif act == 'delete' and username:
                if username != 'admin' and username in self.main_win.user_db:
                    del self.main_win.user_db[username]
                    self.main_win.save_user_db()
                    return jsonify({'status': 'ok'})
            return jsonify({'status': 'error'}), 400

    def run(self):
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)


# ==================== 主悬浮窗控制面板窗口 ====================
class MainWindow(QWidget):
    def __init__(self, reader=None):
        super().__init__()
        self.reader = reader
        self.boxes = []
        self.next_box_id = 1

        self.is_monitoring = False
        self.is_editing = False
        self.is_script_running = False
        self.panels_hidden = False

        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self.alarm_player = AlarmSoundPlayer()

        self.user_db = {'admin': '123456'}
        self.load_user_db()

        # 需求六：自定义添加脚本，保存在根目录 脚本自定义添加脚本.json
        self.scripts = self.load_scripts()

        self.monitor_thread = None
        self.script_thread = None

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._init_ui()

        # 加载区域配置
        self.load_config()

        # 初始化 F12 热键监听
        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._on_f12_pressed)
        self.f12_listener.start()

        # 启动 Web 服务器
        if FLASK_AVAILABLE:
            self.web_thread = WebServerThread(self)
            self.web_thread.action_requested.connect(self._handle_web_action)
            self.web_thread.start()

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget { font-family: "Microsoft YaHei", "微软雅黑"; }
            QLabel { color: #ffffff; font-size: 11px; font-weight: bold; }
            QPushButton {
                background-color: rgba(43, 45, 66, 0.85);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                padding: 3px 8px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.95); }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)

        self.bg_panel = QWidget()
        self.bg_panel.setStyleSheet("background-color: rgba(20, 20, 30, 0.9); border-radius: 8px; border: 1px solid rgba(255,255,255,0.15);")
        bg_layout = QVBoxLayout(self.bg_panel)
        bg_layout.setContentsMargins(6, 6, 6, 6)
        bg_layout.setSpacing(4)

        # ------------------- 第一排 -------------------
        self.row1_container = QWidget()
        row1_layout = QHBoxLayout(self.row1_container)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(4)

        self.lbl_main_title = QLabel("🔍 智能识别中控")
        self.lbl_main_title.setStyleSheet("color: #00ff8c; font-size: 12px; font-weight: bold;")

        self.btn_toggle_monitor = QPushButton("▶ 开始监控")
        self.btn_toggle_monitor.setStyleSheet("QPushButton { background-color: #2e9a58; color: white; border: none; } QPushButton:hover { background-color: #3fb950; }")
        self.btn_toggle_monitor.clicked.connect(self._toggle_monitoring)

        self.btn_toggle_script = QPushButton("▶ 开始操作")
        self.btn_toggle_script.setStyleSheet("QPushButton { background-color: #0088cc; color: white; border: none; } QPushButton:hover { background-color: #00a8ff; }")
        self.btn_toggle_script.clicked.connect(self._toggle_script_runner)

        # 需求一：悬浮窗 删除框选区域 点击编辑后 原来的编辑变成两个按钮一个是框选一个是完成，并且这两个按钮在一起和编辑一样大小
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_edit.setFixedSize(70, 26)
        self.btn_edit.clicked.connect(self._toggle_edit_mode)

        self.container_edit_tools = QWidget()
        self.container_edit_tools.setFixedSize(70, 26)
        edit_tools_layout = QHBoxLayout(self.container_edit_tools)
        edit_tools_layout.setContentsMargins(0, 0, 0, 0)
        edit_tools_layout.setSpacing(2)

        self.btn_sub_pick = QPushButton("框选")
        self.btn_sub_pick.setStyleSheet("QPushButton { background-color: #0088cc; color: white; border: none; border-radius: 3px; font-size: 11px; } QPushButton:hover { background-color: #00a8ff; }")
        self.btn_sub_pick.clicked.connect(self._start_pick_region)

        self.btn_sub_done = QPushButton("完成")
        self.btn_sub_done.setStyleSheet("QPushButton { background-color: #2e9a58; color: white; border: none; border-radius: 3px; font-size: 11px; } QPushButton:hover { background-color: #3fb950; }")
        self.btn_sub_done.clicked.connect(self._toggle_edit_mode)

        edit_tools_layout.addWidget(self.btn_sub_pick)
        edit_tools_layout.addWidget(self.btn_sub_done)
        self.container_edit_tools.setVisible(False)

        row1_layout.addWidget(self.lbl_main_title)
        row1_layout.addStretch()
        row1_layout.addWidget(self.btn_toggle_monitor)
        row1_layout.addWidget(self.btn_toggle_script)
        row1_layout.addWidget(self.btn_edit)
        row1_layout.addWidget(self.container_edit_tools)
        bg_layout.addWidget(self.row1_container)

        # ------------------- 第二排 -------------------
        self.row2_container = QWidget()
        row2_layout = QHBoxLayout(self.row2_container)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(4)

        self.btn_ocr_adjust = QPushButton("⚙️ 识别调整")
        self.btn_ocr_adjust.clicked.connect(self._open_ocr_adjust)

        self.lbl_interval = QLabel("间隔(秒):")
        self.spin_interval = CleanDoubleSpinBox()
        self.spin_interval.setRange(0.1, 60.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.setFixedWidth(45)

        self.btn_hide_panels = QPushButton("👁️ 隐藏面板")
        self.btn_hide_panels.clicked.connect(self._toggle_hide_panels)

        self.lbl_ip_info = QLabel(f"🌐 http://{get_local_ip()}:5000")
        self.lbl_ip_info.setStyleSheet("color: #00ff8c; font-size: 10px;")

        row2_layout.addWidget(self.btn_ocr_adjust)
        row2_layout.addWidget(self.lbl_interval)
        row2_layout.addWidget(self.spin_interval)
        row2_layout.addWidget(self.btn_hide_panels)
        row2_layout.addStretch()
        row2_layout.addWidget(self.lbl_ip_info)
        bg_layout.addWidget(self.row2_container)

        # ------------------- 第三排 -------------------
        # 需求二：悬浮窗 第三排的➕脚本 确定后 在➕后面显示保存的带勾选的脚本
        self.row3_container = QWidget()
        row3_layout = QHBoxLayout(self.row3_container)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.setSpacing(4)

        self.btn_add_script = QPushButton("➕脚本")
        self.btn_add_script.setFixedHeight(24)
        self.btn_add_script.setStyleSheet("QPushButton { background-color: rgba(0, 136, 204, 0.8); color: white; border: none; border-radius: 3px; font-weight: bold; } QPushButton:hover { background-color: #0088cc; }")
        self.btn_add_script.clicked.connect(self._open_add_script)
        row3_layout.addWidget(self.btn_add_script)

        self.scripts_container = QWidget()
        self.scripts_layout = QHBoxLayout(self.scripts_container)
        self.scripts_layout.setContentsMargins(0, 0, 0, 0)
        self.scripts_layout.setSpacing(6)
        row3_layout.addWidget(self.scripts_container)

        row3_layout.addStretch()
        bg_layout.addWidget(self.row3_container)

        main_layout.addWidget(self.bg_panel)

        self.move(100, 100)
        self._refresh_script_ui()

    # ==================== 脚本管理逻辑 (需求二 & 六) ====================
    def load_scripts(self):
        if os.path.exists(SCRIPT_JSON_PATH):
            try:
                with open(SCRIPT_JSON_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print("读取脚本文件失败:", e)
        return []

    def save_scripts(self):
        try:
            with open(SCRIPT_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.scripts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存脚本文件失败:", e)

    def _open_add_script(self):
        dlg = AddScriptDialog(self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_script_data()
            data['enabled'] = True
            self.scripts.append(data)
            self.save_scripts()
            self._refresh_script_ui()

    def _refresh_script_ui(self):
        while self.scripts_layout.count():
            child = self.scripts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for idx, script in enumerate(self.scripts):
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)

            chk = QCheckBox(script.get('name', '脚本'))
            chk.setChecked(script.get('enabled', True))
            chk.setStyleSheet("QCheckBox { color: #00ff8c; font-size: 11px; font-weight: bold; font-family: 'Microsoft YaHei', '微软雅黑'; }")
            chk.toggled.connect(lambda checked, s=script: self._on_script_toggled(s, checked))

            btn_del = QPushButton("×")
            btn_del.setFixedSize(16, 16)
            btn_del.setStyleSheet("QPushButton { background-color: rgba(255, 51, 51, 0.6); color: white; border: none; border-radius: 8px; font-size: 10px; font-weight: bold; } QPushButton:hover { background-color: #ff3333; }")
            btn_del.clicked.connect(lambda _, i=idx: self._delete_script(i))

            item_layout.addWidget(chk)
            item_layout.addWidget(btn_del)
            self.scripts_layout.addWidget(item_widget)

    def _on_script_toggled(self, script, checked):
        script['enabled'] = checked
        self.save_scripts()

    def _delete_script(self, index):
        if 0 <= index < len(self.scripts):
            self.scripts.pop(index)
            self.save_scripts()
            self._refresh_script_ui()

    # ==================== 用户配置管理 ====================
    def load_user_db(self):
        if os.path.exists(USERS_JSON_PATH):
            try:
                with open(USERS_JSON_PATH, 'r', encoding='utf-8') as f:
                    self.user_db = json.load(f)
            except: pass

    def save_user_db(self):
        try:
            with open(USERS_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.user_db, f, ensure_ascii=False, indent=2)
        except: pass

    # ==================== 编辑模式与框选逻辑 ====================
    def _toggle_edit_mode(self):
        self.is_editing = not self.is_editing
        self.btn_edit.setVisible(not self.is_editing)
        self.container_edit_tools.setVisible(self.is_editing)

        for box in self.boxes:
            box.set_edit_mode(self.is_editing)

        if not self.is_editing:
            self.save_config()

    def _start_pick_region(self):
        self.hide()
        time.sleep(0.2)
        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            if w <= 0 or h <= 0: return
            self._add_box_widget(x, y, w, h)
            self.save_config()

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _add_box_widget(self, x, y, w, h, name=None, lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, mid_op=">", box_id=None):
        if box_id is None:
            box_id = self.next_box_id
            self.next_box_id += 1
        else:
            self.next_box_id = max(self.next_box_id, box_id + 1)

        if name is None:
            name = f"区域 {box_id}"

        box = OverlayRegionWidget(box_id, x, y, w, h, name, lower, mid_val, upper, decimal_places, mid_op)
        box.delete_requested.connect(self._remove_box_widget)
        box.alarm_cleared.connect(self._check_global_alarm)
        box.mute_toggled.connect(self._check_global_alarm)
        box.set_edit_mode(self.is_editing)
        box.set_panel_hidden(self.panels_hidden)
        box.show()

        self.boxes.append(box)
        return box

    def _remove_box_widget(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self.save_config()
            self._check_global_alarm()

    # ==================== 监控与脚本线程控制 ====================
    def _toggle_monitoring(self):
        if not self.is_monitoring:
            self.is_monitoring = True
            self.btn_toggle_monitor.setText("⏹ 停止监控")
            self.btn_toggle_monitor.setStyleSheet("QPushButton { background-color: #b03a3a; color: white; border: none; } QPushButton:hover { background-color: #cc4444; }")

            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(self.boxes, interval=self.spin_interval.value(), ocr_params=self.ocr_params, scale=scale)
            self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.start()
        else:
            self.is_monitoring = False
            self.btn_toggle_monitor.setText("▶ 开始监控")
            self.btn_toggle_monitor.setStyleSheet("QPushButton { background-color: #2e9a58; color: white; border: none; } QPushButton:hover { background-color: #3fb950; }")

            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread.wait()
                self.monitor_thread = None

    def _toggle_script_runner(self):
        if not self.is_script_running:
            self.is_script_running = True
            self.btn_toggle_script.setText("⏹ 停止操作")
            self.btn_toggle_script.setStyleSheet("QPushButton { background-color: #cc3333; color: white; border: none; } QPushButton:hover { background-color: #ff4d4d; }")

            self.script_thread = ScriptRunnerThread(self.scripts)
            self.script_thread.start()
        else:
            self.is_script_running = False
            self.btn_toggle_script.setText("▶ 开始操作")
            self.btn_toggle_script.setStyleSheet("QPushButton { background-color: #0088cc; color: white; border: none; } QPushButton:hover { background-color: #00a8ff; }")

            if self.script_thread:
                self.script_thread.stop()
                self.script_thread.wait()
                self.script_thread = None

    def _on_value_updated(self, box, time_str, val, raw_text):
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            is_alarm = (val > box.upper or val < box.lower)
            if is_alarm and not box.user_cleared_alarm:
                box.set_alarm_state(True)
            elif not is_alarm:
                box.user_cleared_alarm = False
                box.set_alarm_state(False)

            is_warn = box.check_mid_condition(val)
            box.set_warning_state(is_warn)

        self._check_global_alarm()

    def _check_global_alarm(self):
        any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if any_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def _open_ocr_adjust(self):
        dlg = OCRAdjustDialog(self.ocr_params, self.reader, self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)

    def _toggle_hide_panels(self):
        self.panels_hidden = not self.panels_hidden
        self.btn_hide_panels.setText("👁️ 显示面板" if self.panels_hidden else "👁️ 隐藏面板")
        for box in self.boxes:
            box.set_panel_hidden(self.panels_hidden)

    def _on_f12_pressed(self):
        self._toggle_monitoring()

    def _handle_web_action(self, action, box_id, data):
        if action == 'toggle_monitor':
            self._toggle_monitoring()
        elif action == 'toggle_grille':
            self._toggle_script_runner()
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
                        b.lower = float(data.get('lower', b.lower))
                        b.spin_lower.setValue(b.lower)
                        b.mid_op = data.get('mid_op', b.mid_op)
                        b.combo_mid_op.setCurrentText(b.mid_op)
                        b.mid_val = float(data.get('mid_val', b.mid_val))
                        b.spin_mid.setValue(b.mid_val)
                        b.upper = float(data.get('upper', b.upper))
                        b.spin_upper.setValue(b.upper)
                        self.save_config()
                    except: pass
                    break

    # ==================== 配置文件保存与加载 ====================
    def save_config(self):
        boxes_cfg = []
        for b in self.boxes:
            boxes_cfg.append({
                'id': b.box_id,
                'x': b.capture_x,
                'y': b.capture_y,
                'w': b.capture_w,
                'h': b.capture_h,
                'name': b.name,
                'lower': b.lower,
                'mid_val': b.mid_val,
                'upper': b.upper,
                'decimal_places': b.decimal_places,
                'mid_op': getattr(b, 'mid_op', '>')
            })
        cfg = {
            'next_id': self.next_box_id,
            'ocr_params': self.ocr_params,
            'boxes': boxes_cfg
        }
        try:
            with open(CONFIG_JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存配置文件失败:", e)

    def load_config(self):
        if not os.path.exists(CONFIG_JSON_PATH):
            return
        try:
            with open(CONFIG_JSON_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            self.next_box_id = cfg.get('next_id', 1)
            self.ocr_params = cfg.get('ocr_params', self.ocr_params)

            for bcfg in cfg.get('boxes', []):
                self._add_box_widget(
                    bcfg['x'], bcfg['y'], bcfg['w'], bcfg['h'],
                    name=bcfg.get('name', '区域'),
                    lower=bcfg.get('lower', 0.0),
                    mid_val=bcfg.get('mid_val', 50.0),
                    upper=bcfg.get('upper', 100.0),
                    decimal_places=bcfg.get('decimal_places', 0),
                    mid_op=bcfg.get('mid_op', '>'),
                    box_id=bcfg.get('id', None)
                )
        except Exception as e:
            print("加载配置文件失败:", e)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def closeEvent(self, event):
        if self.f12_listener:
            self.f12_listener.stop()
            self.f12_listener.wait()

        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()

        if self.script_thread:
            self.script_thread.stop()
            self.script_thread.wait()

        for box in self.boxes:
            box.close()

        self.save_config()
        self.save_scripts()
        event.accept()


# ==================== 程序主入口 ====================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 需求三：设置应用全局微软雅黑字体
    app.setFont(QFont("Microsoft YaHei", 9))

    ocr_reader = None
    if DDDDOCR_AVAILABLE:
        try:
            ocr_reader = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            print("ddddocr 初始化失败:", e)

    main_win = MainWindow(reader=ocr_reader)
    main_win.show()

    sys.exit(app.exec())
