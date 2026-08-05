import sys, os, json, time, re, threading, ctypes, socket, urllib.request
from io import BytesIO
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import mss
import numpy as np
import cv2

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



