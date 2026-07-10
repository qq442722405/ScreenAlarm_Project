import sys
import json
import os
import time
import re
import threading
import hashlib
import base64
import uuid
import platform
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QLineEdit,
    QGroupBox, QSlider, QProgressBar, QCheckBox, QSpinBox, QComboBox,
    QDialog, QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient, QIcon
)

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# ========== 新的激活机制 ==========
# 1. 设备码（与之前一致，但为了显示，保留原机器码）
# 2. 激活码 = HMAC-SHA256(设备码, 日期YYYYMMDD) 取前8位大写
# 3. 永久激活：保存加密的激活状态文件

LICENSE_FILE = "license.dat"
# 请修改此密钥（必须32字节），并妥善保管，不要公开
SECRET_KEY = b"your-32-byte-secret-key-here!!"  # 务必替换为您自己的32字节密钥

class LicenseManager:
    def __init__(self):
        self.machine_code = self._get_machine_code()

    def _get_machine_code(self):
        """生成唯一机器码（基于硬件信息）"""
        mac = uuid.getnode()
        mac_str = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
        try:
            disk = subprocess.check_output("wmic diskdrive get serialnumber", shell=True).decode()
            disk_serial = re.search(r"(\w+)", disk.splitlines()[-1].strip())
            disk_serial = disk_serial.group(1) if disk_serial else "UNKNOWN"
        except:
            disk_serial = "UNKNOWN"
        try:
            board = subprocess.check_output("wmic baseboard get product", shell=True).decode()
            board_id = board.splitlines()[-1].strip() if board else "UNKNOWN"
        except:
            board_id = "UNKNOWN"
        raw = f"{mac_str}|{disk_serial}|{board_id}|{platform.processor()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # 加密解密方法（用于保存激活状态）
    def _encrypt_data(self, data):
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC)
        ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
        iv = base64.b64encode(cipher.iv).decode('utf-8')
        ct = base64.b64encode(ct_bytes).decode('utf-8')
        return iv + ":" + ct

    def _decrypt_data(self, encrypted):
        try:
            iv, ct = encrypted.split(":")
            iv = base64.b64decode(iv)
            ct = base64.b64decode(ct)
            cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
            pt = unpad(cipher.decrypt(ct), AES.block_size).decode('utf-8')
            return pt
        except:
            return None

    # ---------- 新激活逻辑 ----------
    def generate_activation_code(self, date_str=None):
        """根据设备码和日期生成激活码（8位大写）"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m%d")
        key = self.machine_code.encode()
        msg = date_str.encode()
        h = hashlib.pbkdf2_hmac('sha256', key, msg, 10000)  # 或直接 HMAC，我们使用标准 HMAC
        # 更标准： hmac.new(key, msg, hashlib.sha256).hexdigest()
        import hmac
        h = hmac.new(key, msg, hashlib.sha256).hexdigest()
        return h[:8].upper()

    def check_activation(self, input_code):
        """验证激活码是否等于今日激活码"""
        today_code = self.generate_activation_code()
        return input_code.upper() == today_code

    def save_license(self):
        """保存激活状态（加密）"""
        data = {
            "machine_code": self.machine_code,
            "activated": True,
            "activated_at": datetime.now().isoformat()
        }
        encrypted = self._encrypt_data(json.dumps(data))
        with open(LICENSE_FILE, "w") as f:
            f.write(encrypted)

    def load_license(self):
        """加载并验证许可（检查机器码是否匹配）"""
        if not os.path.exists(LICENSE_FILE):
            return None
        try:
            with open(LICENSE_FILE, "r") as f:
                encrypted = f.read()
            decrypted = self._decrypt_data(encrypted)
            if decrypted is None:
                return None
            data = json.loads(decrypted)
            if data.get("machine_code") != self.machine_code:
                return None
            if data.get("activated") is True:
                return data
            return None
        except:
            return None

    def is_activated(self):
        return self.load_license() is not None


class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件激活")
        self.setModal(True)
        self.setFixedSize(450, 250)

        layout = QVBoxLayout(self)

        lm = LicenseManager()
        self.machine_code = lm.machine_code

        # 显示设备码（完整）
        device_label = QLabel("设备码：")
        device_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(device_label)

        code_layout = QHBoxLayout()
        self.code_display = QLineEdit(self.machine_code)
        self.code_display.setReadOnly(True)
        self.code_display.setStyleSheet("background-color: #2a2a42; color: #e0e0f0; border: 1px solid #4a4a6a;")
        code_layout.addWidget(self.code_display)

        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self.copy_device_code)
        code_layout.addWidget(copy_btn)
        layout.addLayout(code_layout)

        # 激活码输入
        form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("请输入激活码")
        form.addRow("激活码：", self.code_input)
        layout.addLayout(form)

        self.info_label = QLabel("请联系管理员获取今日激活码")
        self.info_label.setStyleSheet("color: #ffaa00;")
        layout.addWidget(self.info_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def copy_device_code(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.machine_code)
        QMessageBox.information(self, "已复制", "设备码已复制到剪贴板")

    def get_activation_code(self):
        return self.code_input.text().strip()


# ========== 以下为原有类定义（占位，请您替换为本地完整实现） ==========
# 由于您的原代码中省略了这些类的具体内容，这里提供最小占位以保证编译通过。
# 请将您本地的完整类定义粘贴到此处（AlarmSoundPlayer, CoordinatePicker, MiniWindow, TrendChartWidget）

class AlarmSoundPlayer:
    def __init__(self):
        self.sound_file = ""
        if PYGAME_AVAILABLE:
            pygame.mixer.init()
    def play(self):
        pass
    def stop(self):
        pass

class CoordinatePicker(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(0,0,0,0);")
    def showEvent(self, event):
        pass

class MiniWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
    def update_data(self, data):
        pass
    def clear(self):
        pass

# ========== 监控线程（从原 monitor.py 移入） ==========
class MonitorThread(QThread):
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)
    download_progress = Signal(int)

    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.reader = None
        self.ocr_ready = False
        self.interval_ms = 500
        self.get_row_enabled = None
        self.alarm_loop_enabled = True
        self.alarm_status = {}
        self.manual_clear = False

    def set_interval(self, ms):
        self.interval_ms = max(100, ms)

    def set_alarm_loop(self, enabled):
        self.alarm_loop_enabled = enabled

    def set_reader(self, reader):
        self.reader = reader
        if reader is not None:
            self.ocr_ready = True
            self.ocr_status.emit("就绪 ✅", True)

    def stop(self):
        self.running = False

    def reset_row_alarm(self, row):
        if row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
            self.alarm_status[row]['last_alarm_time'] = 0

    def reset_all_alarms(self):
        self.manual_clear = True
        for row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
        for row in self.alarm_status:
            self.status_updated.emit(row, 'normal')

    def _is_enabled(self, row):
        if self.get_row_enabled:
            try:
                return self.get_row_enabled(row)
            except:
                return True
        return True

    def _init_ocr(self):
        if self.reader is not None:
            return True
        try:
            import easyocr
            OCR_AVAILABLE = True
        except ImportError:
            OCR_AVAILABLE = False
            self.ocr_status.emit("EasyOCR未安装，请运行: pip install easyocr", False)
            return False
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            model_dir = os.path.join(base_dir, 'ocr_models')
            if not os.path.exists(model_dir):
                os.makedirs(model_dir, exist_ok=True)
            self.ocr_status.emit("正在下载/加载EasyOCR模型 (首次约200MB)...", False)
            self.download_progress.emit(0)
            self.reader = easyocr.Reader(['en'], gpu=False, model_storage_directory=model_dir, download_enabled=True, verbose=False)
            if self.reader is not None:
                self.ocr_ready = True
                self.download_progress.emit(100)
                self.ocr_status.emit("就绪 ✅", True)
                return True
            else:
                self.ocr_status.emit("创建OCR对象失败", False)
                return False
        except Exception as e:
            error_msg = str(e)
            if "Connection" in error_msg or "timeout" in error_msg.lower():
                self.ocr_status.emit("网络连接失败，请检查网络后重启", False)
            else:
                self.ocr_status.emit(f"加载失败: {error_msg[:80]}", False)
            return False

    def _preprocess_image(self, img_np, sensitivity):
        try:
            import cv2
            import numpy as np
            sens = sensitivity
            h, w = img_np.shape[:2]
            max_dim = max(h, w)

            if max_dim < 100:
                scale = 3.0
            elif max_dim < 200:
                scale = 2.0
            elif max_dim < 400:
                scale = 1.5
            else:
                scale = 1.0

            if scale != 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                scaled = cv2.resize(img_np, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            else:
                scaled = img_np

            if len(scaled.shape) == 3:
                gray = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
            else:
                gray = scaled

            clip_limit = 1.0 + (sens / 10.0) * 2.0
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)

            kernel_sharpen = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
            sharpened = cv2.filter2D(enhanced, -1, kernel_sharpen)

            if max_dim > 300:
                block_size = max(3, int(3 + (10 - sens) * 0.8))
            else:
                block_size = max(3, int(5 + (10 - sens) * 1.5))
            if block_size % 2 == 0:
                block_size += 1
            c_value = max(1, int(2 + (10 - sens) * 0.3))

            binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, block_size, c_value)
            kernel = np.ones((2,2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
            return rgb
        except Exception:
            return img_np

    def _capture_and_ocr(self, monitor):
        if not self.ocr_ready or self.reader is None:
            return None
        if self.sct is None:
            import mss
            self.sct = mss.mss()
        try:
            import cv2
            import numpy as np
            from PIL import Image
            x, y, w, h = monitor['x'], monitor['y'], monitor['width'], monitor['height']
            if w <= 0 or h <= 0:
                return None
            monitor_region = {"top": y, "left": x, "width": w, "height": h}
            screenshot = self.sct.grab(monitor_region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)

            sens = monitor.get('sensitivity', 5)
            processed = self._preprocess_image(img_np, sens)
            text_thr = 0.2 + (10 - sens) * 0.04

            result = self.reader.readtext(processed, allowlist='0123456789.-',
                                          paragraph=False, width_ths=0.5, height_ths=0.5,
                                          text_threshold=text_thr, low_text=0.2)
            all_numbers = []
            for bbox, text, confidence in result:
                if confidence > 0.2:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    for num_str in numbers:
                        try:
                            val = float(num_str)
                            all_numbers.append((val, confidence, len(num_str)))
                        except:
                            pass
            if len(all_numbers) == 0:
                result2 = self.reader.readtext(img_np, allowlist='0123456789.-', paragraph=False,
                                               text_threshold=text_thr)
                for bbox, text, confidence in result2:
                    if confidence > 0.2:
                        numbers = re.findall(r'-?\d+\.?\d*', text)
                        for num_str in numbers:
                            try:
                                val = float(num_str)
                                all_numbers.append((val, confidence, len(num_str)))
                            except:
                                pass
            if len(all_numbers) == 0:
                return None
            all_numbers.sort(key=lambda x: (1 if '.' in str(x[0]) else 0, x[2]), reverse=True)
            best = all_numbers[0][0]
            return best
        except Exception:
            return None

    def run(self):
        if self.reader is None:
            if not self._init_ocr():
                self.status_updated.emit(-1, 'OCR加载失败，请检查网络后重启')
                return
        else:
            self.ocr_ready = True
            self.ocr_status.emit("就绪 ✅ (共用)", True)

        for m in self.monitors:
            self.alarm_status[m['row']] = {'alarm': False, 'count': 0, 'last_alarm_time': 0}
            self.status_updated.emit(m['row'], '监控中')

        interval_sec = self.interval_ms / 1000.0
        while self.running:
            for monitor in self.monitors:
                if not self.running:
                    break
                row = monitor['row']
                if not self._is_enabled(row):
                    self.status_updated.emit(row, 'disabled')
                    self.alarm_status[row]['alarm'] = False
                    continue
                raw_value = self._capture_and_ocr(monitor)
                if raw_value is not None:
                    value = float(raw_value)
                    self.value_updated.emit(row, value)
                    lower, upper = monitor['lower'], monitor['upper']
                    if value < lower or value > upper:
                        now = time.time()
                        last_time = self.alarm_status[row]['last_alarm_time']
                        if not self.alarm_status[row]['alarm']:
                            self.alarm_status[row]['alarm'] = True
                            self.alarm_status[row]['last_alarm_time'] = now
                            self.alarm_triggered.emit(row, monitor['name'], value, lower, upper)
                        elif self.alarm_loop_enabled:
                            if now - last_time > 10:
                                self.alarm_status[row]['last_alarm_time'] = now
                                self.alarm_triggered.emit(row, monitor['name'], value, lower, upper)
                    else:
                        if not self.manual_clear:
                            self.alarm_status[row]['alarm'] = False
                            self.status_updated.emit(row, 'normal')
                        else:
                            self.alarm_status[row]['alarm'] = False
                    self.alarm_status[row]['count'] = 0
                else:
                    self.alarm_status[row]['count'] += 1
                    if self.alarm_status[row]['count'] >= 3:
                        self.status_updated.emit(row, 'error')
                time.sleep(0.05)
            time.sleep(max(0.05, interval_sec - 0.3))
        if self.sct:
            self.sct.close()


# ========== 主窗口（保留您原有所有方法，只修改 __init__ 中的授权部分） ==========
class MainWindow(QMainWindow):
    def __init__(self):
        # ---------- 新的授权验证 ----------
        if not CRYPTO_AVAILABLE:
            QMessageBox.critical(None, "错误", "加密库未安装，请安装 pycryptodome")
            sys.exit(1)

        lm = LicenseManager()
        if not lm.is_activated():
            dialog = ActivationDialog()
            while True:
                if dialog.exec() == QDialog.Accepted:
                    code = dialog.get_activation_code()
                    if not code:
                        QMessageBox.warning(None, "错误", "激活码不能为空")
                        continue
                    if lm.check_activation(code):
                        lm.save_license()
                        break
                    else:
                        QMessageBox.warning(None, "错误", "激活码无效，请检查是否输入正确或今日日期")
                        continue
                else:
                    sys.exit(0)

        # ---------- 原有初始化 ----------
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumSize(800, 600)
        self.resize(1200, 750)
        self.mini_window = None
        self.chart_visible = True

        self.test_reader = None
        self.reader_loading = False

        # 两种记录数据
        self.value_history_interval = {}
        self.value_history_change = {}
        self.last_recorded_value = {}

        self.record_timer = QTimer()
        self.record_timer.timeout.connect(self.record_interval_value)
        self.record_interval_minutes = 60

        self.display_mode = 'interval'   # 'interval' 或 'change'

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QLabel { color: #e0e0f0; font-family: "Microsoft YaHei"; }
            QTableWidget {
                background-color: #1e1e2e;
                alternate-background-color: #27273d;
                color: #e0e0f0;
                gridline-color: #33334a;
                selection-background-color: #4a9eff;
                selection-color: #ffffff;
                border: 1px solid #33334a;
                border-radius: 8px;
            }
            QTableWidget::item { padding: 6px; text-align: center; }
            QHeaderView::section {
                background-color: #2a2a42;
                color: #e0e0f0;
                padding: 8px;
                border: none;
                border-right: 1px solid #33334a;
                border-bottom: 1px solid #33334a;
                font-weight: bold;
            }
            QPushButton {
                background-color: #363650;
                color: #e0e0f0;
                border: none;
                border-radius: 8px;
                padding: 9px 20px;
                font-weight: bold;
                font-family: "Microsoft YaHei";
                min-height: 22px;
            }
            QPushButton:hover { background-color: #464668; }
            QPushButton#btn_start_stop {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2e9a58, stop:1 #258048);
                color: white;
            }
            QPushButton#btn_start_stop:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38ad64, stop:1 #2d9052); }
            QPushButton#btn_start_stop:disabled {
                background-color: #3a3a50;
                color: #7a7a9a;
            }
            QPushButton#btn_delete { background-color: #b03a3a; }
            QPushButton#btn_delete:hover { background-color: #c44a4a; }
            QPushButton#btn_save { background-color: #2a5a9a; }
            QPushButton#btn_save:hover { background-color: #356ab0; }
            QPushButton#btn_mini { background-color: #4a6a8a; }
            QPushButton#btn_mini:hover { background-color: #5a7a9a; }
            QPushButton#btn_chart_toggle { background-color: #4a4a6a; }
            QPushButton#btn_chart_toggle:hover { background-color: #5a5a7a; }
            QPushButton#btn_clear_history {
                background-color: #7a5a4a;
            }
            QPushButton#btn_clear_history:hover { background-color: #9a6a5a; }
            QSlider::groove:horizontal {
                height: 6px;
                background: #363650;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #4a9eff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #4a9eff;
                border-radius: 3px;
            }
            QSpinBox {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 20px;
            }
            QSpinBox:hover { border-color: #4a9eff; }
            QComboBox {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 20px;
            }
            QComboBox:hover { border-color: #4a9eff; }
            QComboBox QAbstractItemView {
                background-color: #2a2a42;
                color: #e0e0f0;
                selection-background-color: #4a9eff;
            }
            QProgressBar {
                background-color: #27273d;
                border: 1px solid #33334a;
                border-radius: 6px;
                text-align: center;
                color: #e0e0f0;
                height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4a9eff, stop:1 #6ab4ff);
                border-radius: 6px;
            }
            QCheckBox { color: #e0e0f0; font-family: "Microsoft YaHei"; font-size: 13px; }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border-radius: 4px;
                background-color: #363650;
                border: 1px solid #505070;
            }
            QCheckBox::indicator:checked {
                background-color: #4a9eff;
                border-color: #4a9eff;
            }
            QGroupBox {
                color: #e0e0f0;
                font-weight: bold;
                font-family: "Microsoft YaHei";
                border: 1px solid #33334a;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #c0c0e0;
            }
            QLineEdit {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 4px;
                padding: 2px 6px;
            }
            QLineEdit:focus { border-color: #4a9eff; }
        """)

        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.loop_enabled = True
        self.detect_interval = 1000
        self.current_row_data = []

        self.alarm_player = AlarmSoundPlayer()
        self.alarm_file = self.alarm_player.sound_file or ""
        self.alarm_playing = False

        self.row_enabled = {}
        self.row_alarm = {}
        self.row_muted = {}
        self.row_sensitivity = {}

        self._setup_ui()
        self.load_config()

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)

        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        QTimer.singleShot(200, self._init_ocr_reader)

    # ========== 以下所有方法请保留您原有的完整实现（复制您本地的全部方法） ==========
    # 由于此处省略了 _setup_ui, _init_ocr_reader, load_config, save_config,
    # start_monitor, stop_monitor, on_value_updated, record_interval_value,
    # _update_status_display, _on_table_item_changed, _on_selection_changed,
    # create_sensitivity_widget, keyPressEvent 等等，您需要从原 main.py 中复制这些方法。
    # 我在此处仅放置占位，请务必替换为您的完整代码。

    def _setup_ui(self):
        # 请将您原有的 _setup_ui 完整代码粘贴到这里
        pass

    def _init_ocr_reader(self):
        # 请将您原有的 _init_ocr_reader 完整代码粘贴到这里
        pass

    def load_config(self):
        # 请将您原有的 load_config 完整代码粘贴到这里
        pass

    def save_config(self):
        # 请将您原有的 save_config 完整代码粘贴到这里
        pass

    def start_monitor(self):
        # 请将您原有的 start_monitor 完整代码粘贴到这里
        pass

    def stop_monitor(self):
        # 请将您原有的 stop_monitor 完整代码粘贴到这里
        pass

    def on_value_updated(self, row, value):
        # 请将您原有的 on_value_updated 完整代码粘贴到这里
        pass

    def record_interval_value(self):
        # 请将您原有的 record_interval_value 完整代码粘贴到这里
        pass

    def _update_status_display(self):
        # 请将您原有的 _update_status_display 完整代码粘贴到这里
        pass

    def _on_table_item_changed(self, item):
        # 请将您原有的 _on_table_item_changed 完整代码粘贴到这里
        pass

    def _on_selection_changed(self):
        # 请将您原有的 _on_selection_changed 完整代码粘贴到这里
        pass

    def create_sensitivity_widget(self, row):
        # 请将您原有的 create_sensitivity_widget 完整代码粘贴到这里
        pass

    def keyPressEvent(self, event):
        # 请将您原有的 keyPressEvent 完整代码粘贴到这里
        pass

    # 其他您自定义的方法也请一并保留


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
