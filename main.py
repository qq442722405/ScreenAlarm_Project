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
    QGroupBox, QSlider, QProgressBar, QCheckBox, QSpinBox,
    QDialog, QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient, QIcon
)
from monitor import MonitorThread

# 引入加密库
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("请安装 pycryptodome: pip install pycryptodome")

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# ---------- 授权相关常量 ----------
LICENSE_FILE = "license.dat"
# 请自行修改此密钥（32字节），并妥善保管，不要公开
SECRET_KEY = b"your-32-byte-secret-key-here!!"  # 必须32字节


# ---------- 授权管理类 ----------
class LicenseManager:
    def __init__(self):
        self.machine_code = self._get_machine_code()

    def _get_machine_code(self):
        """生成唯一机器码"""
        # 获取 MAC 地址
        mac = uuid.getnode()
        mac_str = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
        # 获取硬盘序列号
        try:
            disk = subprocess.check_output("wmic diskdrive get serialnumber", shell=True).decode()
            disk_serial = re.search(r"(\w+)", disk.splitlines()[-1].strip())
            disk_serial = disk_serial.group(1) if disk_serial else "UNKNOWN"
        except:
            disk_serial = "UNKNOWN"
        # 获取主板ID
        try:
            board = subprocess.check_output("wmic baseboard get product", shell=True).decode()
            board_id = board.splitlines()[-1].strip() if board else "UNKNOWN"
        except:
            board_id = "UNKNOWN"
        raw = f"{mac_str}|{disk_serial}|{board_id}|{platform.processor()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _encrypt_data(self, data):
        """AES加密"""
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC)
        ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
        iv = base64.b64encode(cipher.iv).decode('utf-8')
        ct = base64.b64encode(ct_bytes).decode('utf-8')
        return iv + ":" + ct

    def _decrypt_data(self, encrypted):
        """AES解密"""
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
        """保存许可文件"""
        data = {
            "machine_code": self.machine_code,
            "activation_code": activation_code,
            "activated_at": datetime.now().isoformat()
        }
        encrypted = self._encrypt_data(json.dumps(data))
        with open(LICENSE_FILE, "w") as f:
            f.write(encrypted)

    def load_license(self):
        """加载并验证许可"""
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
            return data
        except:
            return None

    def check(self):
        """检查许可是否有效"""
        return self.load_license() is not None


# ---------- 激活对话框 ----------
class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("软件激活")
        self.setModal(True)
        self.setFixedSize(400, 200)
        layout = QVBoxLayout(self)

        # 显示机器码
        lm = LicenseManager()
        self.machine_label = QLabel(f"机器码：{lm.machine_code[:16]}...")
        self.machine_label.setWordWrap(True)
        layout.addWidget(self.machine_label)

        form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("请输入激活码")
        form.addRow("激活码：", self.code_input)
        layout.addLayout(form)

        self.info_label = QLabel("请联系开发者获取激活码")
        self.info_label.setStyleSheet("color: #ffaa00;")
        layout.addWidget(self.info_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_activation_code(self):
        return self.code_input.text().strip()


# ---------- 主窗口（修改 __init__ 增加授权检查） ----------
class MainWindow(QMainWindow):
    def __init__(self):
        # ---------- 先进行授权验证 ----------
        if not CRYPTO_AVAILABLE:
            QMessageBox.critical(None, "错误", "加密库未安装，请安装 pycryptodome")
            sys.exit(1)

        lm = LicenseManager()
        if not lm.check():
            # 弹出激活对话框
            dialog = ActivationDialog()
            while True:
                if dialog.exec() == QDialog.Accepted:
                    code = dialog.get_activation_code()
                    if not code:
                        QMessageBox.warning(None, "错误", "激活码不能为空")
                        continue
                    # 验证激活码（解密后检查机器码是否匹配）
                    # 此处我们直接保存，但实际应验证激活码是否包含本机机器码
                    # 为简化，我们将激活码视为一个任意字符串，但为了安全，建议使用对称加密或RSA
                    # 这里我们采用简单方式：激活码是机器码的加密形式（由开发者工具生成）
                    # 我们解密激活码并与当前机器码比对
                    decrypted = lm._decrypt_data(code)
                    if decrypted is None:
                        QMessageBox.warning(None, "错误", "激活码无效")
                        continue
                    try:
                        data = json.loads(decrypted)
                        if data.get("machine_code") == lm.machine_code:
                            # 激活成功，保存许可
                            lm.save_license(code)
                            break
                        else:
                            QMessageBox.warning(None, "错误", "激活码与本机不匹配")
                            continue
                    except:
                        QMessageBox.warning(None, "错误", "激活码格式错误")
                        continue
                else:
                    sys.exit(0)

        # ---------- 正常初始化主窗口 ----------
        super().__init__()
        # ... 原有 __init__ 代码（从 self.setWindowTitle 开始，直到末尾）
        # 为避免重复，此处省略原有代码，您需要将原 MainWindow 的 __init__ 内容完整粘贴到此处。
        # 我们将在完整文件中提供全部代码。
