# -*- coding: utf-8 -*-
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
    QDialog, QDialogButtonBox, QFormLayout, QSplitter, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray, QSize
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient, QIcon, QAction
)
from monitor import MonitorThread

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

# ---------- 授权相关常量 ----------
LICENSE_FILE = "license.dat"
SECRET_KEY = b"your-32-byte-secret-key-here!!"  # 请修改为您的32字节密钥

class LicenseManager:
    def __init__(self):
        self.machine_code = self._get_machine_code()

    def _get_machine_code(self):
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

    def save_license(self, activation_code):
        decrypted = self._decrypt_data(activation_code)
        if decrypted is None:
            raise ValueError("激活码无效")
        data = json.loads(decrypted)
        license_data = {
            "machine_code": self.machine_code,
            "activation_code": activation_code,
            "activated_at": datetime.now().isoformat(),
            "hour": data.get("hour", "")   # 存储生成时的小时标记
        }
        encrypted = self._encrypt_data(json.dumps(license_data))
        with open(LICENSE_FILE, "w") as f:
            f.write(encrypted)

    def load_license(self):
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
            # 验证小时有效性
            hour_str = data.get("hour", "")
            if hour_str:
                try:
                    # 格式: "YYYY-MM-DD HH" 例如 "2026-07-10 07"
                    valid_dt = datetime.strptime(hour_str, "%Y-%m-%d %H")
                    now = datetime.now()
                    # 比较日期和小时是否相同
                    if now.year == valid_dt.year and now.month == valid_dt.month and now.day == valid_dt.day and now.hour == valid_dt.hour:
                        pass  # 有效
                    else:
                        return None  # 不在有效小时内
                except:
                    return None
            return data
        except:
            return None

    def check(self):
        return self.load_license() is not None


class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件激活")
        self.setModal(True)
        self.setFixedSize(450, 300)
        layout = QVBoxLayout(self)

        lm = LicenseManager()
        machine_code = lm.machine_code
        lbl_machine = QLabel(f"机器码：{machine_code}")
        lbl_machine.setWordWrap(True)
        lbl_machine.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(lbl_machine)

        copy_btn = QPushButton("📋 复制机器码")
        copy_btn.clicked.connect(self._copy_machine_code)
        layout.addWidget(copy_btn)

        form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("请输入激活码")
        form.addRow("激活码：", self.code_input)
        layout.addLayout(form)

        # 小尾巴
        info = QLabel("小尾巴")
        info.setStyleSheet("color: #ffaa00; font-size: 11px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_machine_code(self):
        lm = LicenseManager()
        QApplication.clipboard().setText(lm.machine_code)
        QMessageBox.information(self, "复制成功", "机器码已复制到剪贴板")

    def get_activation_code(self):
        return self.code_input.text().strip()


# ========== 原有的辅助类 ==========
class AlarmSoundPlayer:
    def __init__(self):
        self.sound_file = None
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
                self.sound_file = "alarm.wav"  # 默认
            except:
                pass
        self.playing = False

    def play(self):
        if not PYGAME_AVAILABLE or not self.sound_file:
            return
        try:
            if not self.playing:
                pygame.mixer.music.load(self.sound_file)
                pygame.mixer.music.play(-1)
                self.playing = True
        except:
            pass

    def stop(self):
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.stop()
                self.playing = False
            except:
                pass

    def set_sound_file(self, path):
        if os.path.exists(path):
            self.sound_file = path
            if self.playing:
                self.stop()
                self.play()


class CoordinatePicker(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.start_pos = None
        self.end_pos = None
        self.picking = False
        self.setGeometry(0, 0, QApplication.primaryScreen().size().width(),
                         QApplication.primaryScreen().size().height())
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if self.start_pos and self.end_pos:
            rect = QRect(self.start_pos, self.end_pos).normalized()
            painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.end_pos = None
            self.picking = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.picking:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_pos and self.end_pos:
            self.picking = False
            rect = QRect(self.start_pos, self.end_pos).normalized()
            if rect.width() > 5 and rect.height() > 5:
                self.parent().set_coordinates(rect.x(), rect.y(), rect.width(), rect.height())
            self.close()


class MiniWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(200, 120)
        self.layout = QVBoxLayout(self)
        self.label = QLabel("监控中...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #4a9eff; font-size: 16px; background: rgba(30,30,46,200); border-radius: 10px; padding: 10px;")
        self.layout.addWidget(self.label)
        self.drag_pos = None
        self.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def update_value(self, text):
        self.label.setText(text)


class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self.max_points = 100
        self.setMinimumHeight(120)
        self.setStyleSheet("background: #1e1e2e; border-radius: 8px;")

    def add_point(self, value):
        self.history.append(value)
        if len(self.history) > self.max_points:
            self.history.pop(0)
        self.update()

    def clear(self):
        self.history.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(30, 30, 46))
        if len(self.history) < 2:
            return
        margin = 10
        w = rect.width() - 2 * margin
        h = rect.height() - 2 * margin
        if w <= 0 or h <= 0:
            return
        min_val = min(self.history)
        max_val = max(self.history)
        range_val = max_val - min_val
        if range_val == 0:
            range_val = 1
        points = []
        for i, val in enumerate(self.history):
            x = margin + (i / (len(self.history) - 1)) * w
            y = margin + h - ((val - min_val) / range_val) * h
            points.append((x, y))
        painter.setPen(QPen(QColor(74, 158, 255), 2))
        for i in range(len(points) - 1):
            painter.drawLine(int(points[i][0]), int(points[i][1]),
                             int(points[i+1][0]), int(points[i+1][1]))


# ========== 主窗口 ==========
class MainWindow(QMainWindow):
    def __init__(self):
        # ---------- 授权验证 ----------
        if not CRYPTO_AVAILABLE:
            QMessageBox.critical(None, "错误", "加密库未安装，请安装 pycryptodome")
            sys.exit(1)

        lm = LicenseManager()
        if not lm.check():
            dialog = ActivationDialog()
            while True:
                if dialog.exec() == QDialog.Accepted:
                    code = dialog.get_activation_code()
                    if not code:
                        QMessageBox.warning(None, "错误", "激活码不能为空")
                        continue
                    decrypted = lm._decrypt_data(code)
                    if decrypted is None:
                        QMessageBox.warning(None, "错误", "激活码无效")
                        continue
                    try:
                        data = json.loads(decrypted)
                        if data.get("machine_code") != lm.machine_code:
                            QMessageBox.warning(None, "错误", "激活码与本机不匹配")
                            continue
                        expiry_str = data.get("expiry", "")
                        if expiry_str:
                            today = datetime.now().date()
                            try:
                                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                                if today > expiry_date:
                                    QMessageBox.warning(None, "错误", "激活码已过期")
                                    continue
                            except:
                                QMessageBox.warning(None, "错误", "激活码日期格式错误")
                                continue
                        lm.save_license(code)
                        break
                    except:
                        QMessageBox.warning(None, "错误", "激活码格式错误")
                        continue
                else:
                    sys.exit(0)

        # ---------- 初始化UI ----------
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumSize(800, 600)
        self.resize(1200, 750)

        self.mini_window = None
        self.chart_visible = True
        self.test_reader = None
        self.reader_loading = False
        self.value_history_interval = {}
        self.value_history_change = {}
        self.last_recorded_value = {}
        self.record_timer = QTimer()
        self.record_timer.timeout.connect(self.record_interval_value)
        self.record_interval_minutes = 60
        self.display_mode = 'interval'

        # 监控状态
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

        # 设置样式
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

    # ---------- UI 构建 ----------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)

        # 顶部控制区
        top = QHBoxLayout()
        self.btn_start = QPushButton("▶ 启动监控")
        self.btn_start.setObjectName("btn_start_stop")
        self.btn_start.clicked.connect(self.toggle_monitor)
        top.addWidget(self.btn_start)

        self.btn_add = QPushButton("➕ 添加区域")
        self.btn_add.clicked.connect(self.add_monitor)
        top.addWidget(self.btn_add)

        self.btn_delete = QPushButton("🗑 删除选中")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_selected)
        top.addWidget(self.btn_delete)

        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        top.addWidget(self.btn_save)

        self.btn_load = QPushButton("📂 加载配置")
        self.btn_load.clicked.connect(self.load_config_from_file)
        top.addWidget(self.btn_load)

        self.btn_mini = QPushButton("📌 迷你窗口")
        self.btn_mini.setObjectName("btn_mini")
        self.btn_mini.clicked.connect(self.toggle_mini)
        top.addWidget(self.btn_mini)

        self.btn_chart = QPushButton("📊 趋势图")
        self.btn_chart.setObjectName("btn_chart_toggle")
        self.btn_chart.clicked.connect(self.toggle_chart)
        top.addWidget(self.btn_chart)

        self.btn_clear = QPushButton("🧹 清除历史")
        self.btn_clear.setObjectName("btn_clear_history")
        self.btn_clear.clicked.connect(self.clear_history)
        top.addWidget(self.btn_clear)

        main_layout.addLayout(top)

        # 参数栏
        params = QHBoxLayout()
        params.addWidget(QLabel("检测间隔(ms):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 5000)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.valueChanged.connect(self.on_interval_changed)
        params.addWidget(self.interval_spin)

        params.addWidget(QLabel("报警循环:"))
        self.loop_check = QCheckBox("启用")
        self.loop_check.setChecked(True)
        self.loop_check.stateChanged.connect(self.on_loop_changed)
        params.addWidget(self.loop_check)

        params.addWidget(QLabel("记录间隔(分钟):"))
        self.record_spin = QSpinBox()
        self.record_spin.setRange(1, 1440)
        self.record_spin.setValue(60)
        self.record_spin.valueChanged.connect(self.on_record_interval_changed)
        params.addWidget(self.record_spin)

        params.addWidget(QLabel("显示模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["间隔值", "变化量"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        params.addWidget(self.mode_combo)

        params.addStretch()
        main_layout.addLayout(params)

        # 表格 + 趋势图
        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "启用", "名称", "X", "Y", "宽度", "高度",
            "下限", "上限", "灵敏度", "状态"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        self.chart_widget = TrendChartWidget()
        splitter.addWidget(self.chart_widget)
        splitter.setSizes([500, 150])
        main_layout.addWidget(splitter)

        # 状态栏
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)

        # 初始化表格行数据
        self.current_row_data = []

    # ---------- 表格操作 ----------
    def add_monitor(self):
        picker = CoordinatePicker(self)
        picker.show()

    def set_coordinates(self, x, y, w, h):
        row = self.table.rowCount()
        self.table.insertRow(row)
        # 启用（复选框）
        chk = QCheckBox()
        chk.setChecked(True)
        chk.stateChanged.connect(lambda state, r=row: self._on_enable_changed(r, state))
        self.table.setCellWidget(row, 0, chk)
        # 名称
        self.table.setItem(row, 1, QTableWidgetItem(f"区域{row+1}"))
        # 坐标
        self.table.setItem(row, 2, QTableWidgetItem(str(x)))
        self.table.setItem(row, 3, QTableWidgetItem(str(y)))
        self.table.setItem(row, 4, QTableWidgetItem(str(w)))
        self.table.setItem(row, 5, QTableWidgetItem(str(h)))
        # 下限/上限
        self.table.setItem(row, 6, QTableWidgetItem("0"))
        self.table.setItem(row, 7, QTableWidgetItem("100"))
        # 灵敏度
        sens_spin = QSpinBox()
        sens_spin.setRange(1, 10)
        sens_spin.setValue(5)
        self.table.setCellWidget(row, 8, sens_spin)
        # 状态
        status_item = QTableWidgetItem("待启动")
        status_item.setForeground(QBrush(QColor(200, 200, 200)))
        self.table.setItem(row, 9, status_item)

        self.row_enabled[row] = True
        self.row_alarm[row] = False
        self.row_muted[row] = False
        self.row_sensitivity[row] = 5

    def delete_selected(self):
        rows = sorted(set([idx.row() for idx in self.table.selectedIndexes()]), reverse=True)
        if not rows:
            QMessageBox.information(self, "提示", "请先选择要删除的行")
            return
        for r in rows:
            self.table.removeRow(r)
            # 清理相关数据
            self.row_enabled.pop(r, None)
            self.row_alarm.pop(r, None)
            self.row_muted.pop(r, None)
            self.row_sensitivity.pop(r, None)
        # 重建映射（因为删除后行号变化，简单重建）
        self._rebuild_row_maps()

    def _rebuild_row_maps(self):
        # 根据当前表格重建映射
        self.row_enabled.clear()
        self.row_alarm.clear()
        self.row_muted.clear()
        self.row_sensitivity.clear()
        for r in range(self.table.rowCount()):
            chk = self.table.cellWidget(r, 0)
            if chk:
                self.row_enabled[r] = chk.isChecked()
            else:
                self.row_enabled[r] = True
            self.row_alarm[r] = False
            self.row_muted[r] = False
            sens = self.table.cellWidget(r, 8)
            if sens:
                self.row_sensitivity[r] = sens.value()
            else:
                self.row_sensitivity[r] = 5

    def _on_enable_changed(self, row, state):
        self.row_enabled[row] = (state == Qt.Checked)

    def _on_table_item_changed(self, item):
        row = item.row()
        col = item.column()
        if col in (6, 7):  # 下限/上限
            try:
                float(item.text())
            except:
                QMessageBox.warning(self, "错误", "请输入有效数字")
                item.setText("0")
        if col == 1:  # 名称
            pass

    def _on_selection_changed(self):
        # 选中行时更新趋势图显示
        selected = self.table.selectedItems()
        if selected:
            row = selected[0].row()
            if row in self.value_history_interval:
                self.chart_widget.history = self.value_history_interval[row].copy()
                self.chart_widget.update()
            else:
                self.chart_widget.clear()

    # ---------- 监控控制 ----------
    def toggle_monitor(self):
        if not self.monitoring:
            self.start_monitor()
        else:
            self.stop_monitor()

    def start_monitor(self):
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "错误", "请先添加监控区域")
            return

        # 构建监控列表
        monitors = []
        for r in range(self.table.rowCount()):
            try:
                name = self.table.item(r, 1).text()
                x = int(self.table.item(r, 2).text())
                y = int(self.table.item(r, 3).text())
                w = int(self.table.item(r, 4).text())
                h = int(self.table.item(r, 5).text())
                lower = float(self.table.item(r, 6).text())
                upper = float(self.table.item(r, 7).text())
                sens_widget = self.table.cellWidget(r, 8)
                sens = sens_widget.value() if sens_widget else 5
                monitors.append({
                    'row': r,
                    'name': name,
                    'x': x,
                    'y': y,
                    'width': w,
                    'height': h,
                    'lower': lower,
                    'upper': upper,
                    'sensitivity': sens
                })
            except Exception as e:
                QMessageBox.warning(self, "错误", f"第{r+1}行数据无效: {e}")
                return

        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.set_interval(self.detect_interval)
        self.monitor_thread.set_alarm_loop(self.loop_enabled)
        # 传递共享的OCR reader (如果已加载)
        if hasattr(self, 'reader') and self.reader:
            self.monitor_thread.set_reader(self.reader)

        # 连接信号
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.ocr_status.connect(self.on_ocr_status)
        self.monitor_thread.download_progress.connect(self.on_download_progress)

        # 设置获取启用状态的函数
        self.monitor_thread.get_row_enabled = lambda r: self.row_enabled.get(r, True)

        self.monitor_thread.start()
        self.monitoring = True
        self.btn_start.setText("⏹ 停止监控")
        self.btn_start.setObjectName("")
        self.btn_start.setStyleSheet("background: #b03a3a; color: white;")
        self.status_label.setText("监控运行中...")

        # 开启记录定时器
        self.record_timer.start(self.record_interval_minutes * 60 * 1000)

    def stop_monitor(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
            self.monitor_thread = None
        self.monitoring = False
        self.btn_start.setText("▶ 启动监控")
        self.btn_start.setObjectName("btn_start_stop")
        self.btn_start.setStyleSheet("")
        self.status_label.setText("已停止")
        self.record_timer.stop()
        # 清空报警状态
        for r in range(self.table.rowCount()):
            self.row_alarm[r] = False
            self._set_status_text(r, "已停止", QColor(200, 200, 200))

    # ---------- 信号处理 ----------
    def on_value_updated(self, row, value):
        # 更新表格显示当前值
        status_item = self.table.item(row, 9)
        if not status_item:
            return
        # 在状态栏显示值
        status_text = f"当前值: {value:.2f}"
        status_item.setText(status_text)
        status_item.setForeground(QBrush(QColor(100, 200, 255)))
        # 记录历史
        if row not in self.value_history_interval:
            self.value_history_interval[row] = []
        self.value_history_interval[row].append(value)
        if len(self.value_history_interval[row]) > 200:
            self.value_history_interval[row].pop(0)
        # 更新趋势图（如果选中该行）
        selected = self.table.selectedItems()
        if selected and selected[0].row() == row:
            self.chart_widget.add_point(value)

        # 记录变化量（与上次值比较）
        if row not in self.last_recorded_value:
            self.last_recorded_value[row] = value
        else:
            change = value - self.last_recorded_value[row]
            if row not in self.value_history_change:
                self.value_history_change[row] = []
            self.value_history_change[row].append(change)
            if len(self.value_history_change[row]) > 200:
                self.value_history_change[row].pop(0)
            self.last_recorded_value[row] = value

    def on_alarm_triggered(self, row, name, value, lower, upper):
        if self.row_muted.get(row, False):
            return
        # 播放报警音
        if not self.alarm_playing:
            self.alarm_player.play()
            self.alarm_playing = True
        # 更新状态
        self.row_alarm[row] = True
        self._set_status_text(row, f"⚠ 报警! 值={value:.2f}", QColor(255, 80, 80))
        # 可选：弹出提示
        if not self.mini_window:
            QMessageBox.information(self, "报警", f"区域 '{name}' 数值 {value:.2f} 超出范围 [{lower}, {upper}]")

    def on_status_updated(self, row, status):
        if status == 'normal':
            self.row_alarm[row] = False
            self._set_status_text(row, "正常", QColor(100, 255, 100))
        elif status == 'disabled':
            self._set_status_text(row, "已禁用", QColor(200, 200, 200))
        elif status == 'error':
            self._set_status_text(row, "识别错误", QColor(255, 200, 50))
        elif status == '监控中':
            self._set_status_text(row, "监控中", QColor(100, 200, 255))

    def _set_status_text(self, row, text, color):
        item = self.table.item(row, 9)
        if item:
            item.setText(text)
            item.setForeground(QBrush(color))

    def on_ocr_status(self, msg, ready):
        self.status_label.setText(msg)

    def on_download_progress(self, progress):
        pass  # 可选显示进度

    def _update_status_display(self):
        # 更新报警状态显示（如闪烁等）
        pass

    # ---------- 配置加载/保存 ----------
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                # 清空表格
                self.table.setRowCount(0)
                for mon in data.get('monitors', []):
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    # 启用
                    chk = QCheckBox()
                    chk.setChecked(mon.get('enabled', True))
                    chk.stateChanged.connect(lambda state, r=row: self._on_enable_changed(r, state))
                    self.table.setCellWidget(row, 0, chk)
                    # 名称
                    self.table.setItem(row, 1, QTableWidgetItem(mon.get('name', f"区域{row+1}")))
                    # 坐标
                    self.table.setItem(row, 2, QTableWidgetItem(str(mon.get('x', 0))))
                    self.table.setItem(row, 3, QTableWidgetItem(str(mon.get('y', 0))))
                    self.table.setItem(row, 4, QTableWidgetItem(str(mon.get('width', 100))))
                    self.table.setItem(row, 5, QTableWidgetItem(str(mon.get('height', 100))))
                    self.table.setItem(row, 6, QTableWidgetItem(str(mon.get('lower', 0))))
                    self.table.setItem(row, 7, QTableWidgetItem(str(mon.get('upper', 100))))
                    # 灵敏度
                    sens_spin = QSpinBox()
                    sens_spin.setRange(1, 10)
                    sens_spin.setValue(mon.get('sensitivity', 5))
                    self.table.setCellWidget(row, 8, sens_spin)
                    # 状态
                    self.table.setItem(row, 9, QTableWidgetItem("待启动"))
                self._rebuild_row_maps()
                # 其他设置
                self.interval_spin.setValue(data.get('interval', 1000))
                self.loop_check.setChecked(data.get('loop', True))
                self.record_spin.setValue(data.get('record_interval', 60))
                self.mode_combo.setCurrentIndex(data.get('display_mode', 0))
                self.alarm_file = data.get('alarm_file', '')
                if self.alarm_file:
                    self.alarm_player.set_sound_file(self.alarm_file)
            except Exception as e:
                QMessageBox.warning(self, "加载配置失败", str(e))

    def save_config(self):
        data = {}
        monitors = []
        for r in range(self.table.rowCount()):
            try:
                chk = self.table.cellWidget(r, 0)
                enabled = chk.isChecked() if chk else True
                name = self.table.item(r, 1).text()
                x = int(self.table.item(r, 2).text())
                y = int(self.table.item(r, 3).text())
                w = int(self.table.item(r, 4).text())
                h = int(self.table.item(r, 5).text())
                lower = float(self.table.item(r, 6).text())
                upper = float(self.table.item(r, 7).text())
                sens_widget = self.table.cellWidget(r, 8)
                sens = sens_widget.value() if sens_widget else 5
                monitors.append({
                    'enabled': enabled,
                    'name': name,
                    'x': x,
                    'y': y,
                    'width': w,
                    'height': h,
                    'lower': lower,
                    'upper': upper,
                    'sensitivity': sens
                })
            except:
                pass
        data['monitors'] = monitors
        data['interval'] = self.interval_spin.value()
        data['loop'] = self.loop_check.isChecked()
        data['record_interval'] = self.record_spin.value()
        data['display_mode'] = self.mode_combo.currentIndex()
        data['alarm_file'] = self.alarm_file
        try:
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def load_config_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择配置文件", "", "JSON (*.json)")
        if file_path:
            self.config_file = file_path
            self.load_config()

    # ---------- 其他控制 ----------
    def on_interval_changed(self, val):
        self.detect_interval = val
        if self.monitor_thread:
            self.monitor_thread.set_interval(val)

    def on_loop_changed(self, state):
        self.loop_enabled = (state == Qt.Checked)
        if self.monitor_thread:
            self.monitor_thread.set_alarm_loop(self.loop_enabled)

    def on_record_interval_changed(self, val):
        self.record_interval_minutes = val
        if self.record_timer.isActive():
            self.record_timer.start(val * 60 * 1000)

    def on_mode_changed(self, idx):
        self.display_mode = 'interval' if idx == 0 else 'change'
        # 更新趋势图显示
        selected = self.table.selectedItems()
        if selected:
            row = selected[0].row()
            if self.display_mode == 'interval':
                hist = self.value_history_interval.get(row, [])
            else:
                hist = self.value_history_change.get(row, [])
            self.chart_widget.history = hist.copy()
            self.chart_widget.update()

    def toggle_mini(self):
        if self.mini_window:
            self.mini_window.close()
            self.mini_window = None
        else:
            self.mini_window = MiniWindow(self)
            # 连接更新信号
            def update_mini(value):
                if self.mini_window:
                    self.mini_window.update_value(f"最新值: {value:.2f}")
            # 这里简单起见，每次更新时调用
            # 可以用一个槽函数

    def toggle_chart(self):
        self.chart_visible = not self.chart_visible
        self.chart_widget.setVisible(self.chart_visible)

    def clear_history(self):
        self.value_history_interval.clear()
        self.value_history_change.clear()
        self.last_recorded_value.clear()
        self.chart_widget.clear()
        QMessageBox.information(self, "提示", "历史数据已清除")

    def record_interval_value(self):
        # 定期记录当前值（可用于日志）
        pass

    def _init_ocr_reader(self):
        # 初始化OCR（可与monitor共享）
        try:
            import easyocr
            self.reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            self.status_label.setText("OCR加载成功")
        except Exception as e:
            self.reader = None
            self.status_label.setText(f"OCR加载失败: {e}")

    # 键盘事件
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.stop_monitor()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
