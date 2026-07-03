import time
import re
import os
import sys
from PySide6.QtCore import QThread, Signal
import cv2
import numpy as np
import mss
from PIL import Image

try:
    import easyocr
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("EasyOCR未安装")


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

    # 其余方法保持不变（此处省略，实际已包含在您的文件中）
    # 请确保您的 monitor.py 与此版本一致即可。
