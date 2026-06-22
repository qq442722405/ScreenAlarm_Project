import time
import re
import threading
import numpy as np
from PySide6.QtCore import QObject, Signal, QThread

try:
    import easyocr
    import mss
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"警告: 依赖库未安装: {e}")
    print("请运行: pip install easyocr mss pillow")


class MonitorThread(QThread):
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)
    
    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.reader = None
        self.ocr_ready = False
        
    def stop(self):
        self.running = False
    
    def _init_ocr(self):
        if not OCR_AVAILABLE:
            self.ocr_status.emit("EasyOCR库未安装", False)
            return False
        try:
            self.ocr_status.emit("正在加载EasyOCR模型... (首次运行需下载)", False)
            self.reader = easyocr.Reader(['en'], gpu=False, model_storage_directory='./ocr_models')
            self.ocr_ready = True
            self.ocr_status.emit("EasyOCR加载完成", True)
            return True
        except Exception as e:
            self.ocr_status.emit(f"OCR初始化失败: {str(e)}", False)
            print(f"OCR初始化失败: {e}")
            return False
    
    def _capture_and_ocr(self, x, y, width, height):
        if not self.ocr_ready or self.reader is None:
            return None
        if self.sct is None:
            self.sct = mss.mss()
        try:
            monitor = {"top": y, "left": x, "width": width, "height": height}
            screenshot = self.sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)
            results = self.reader.readtext(
                img_np,
                allowlist='0123456789.-',
                paragraph=False,
                width_ths=0.7,
                height_ths=0.7
            )
            for bbox, text, confidence in results:
                numbers = re.findall(r'-?\d+\.?\d*', text)
                if numbers:
                    try:
                        value = float(numbers[0])
                        if confidence > 0.3:
                            return value
                    except ValueError:
                        continue
            return None
        except Exception as e:
            print(f"OCR识别错误: {e}")
            return None
    
    def run(self):
        if not self._init_ocr():
            self.ocr_status.emit("OCR初始化失败，无法开始监控", False)
            return
        monitor_status = {}
        for m in self.monitors:
            monitor_status[m['row']] = {
                'alarm': False,
                'last_value': None,
                'error_count': 0
            }
        for m in self.monitors:
            self.status_updated.emit(m['row'], '监控中...')
        while self.running:
            for monitor in self.monitors:
                if not self.running:
                    break
                row = monitor['row']
                name = monitor['name']
                value = self._capture_and_ocr(
                    monitor['x'], monitor['y'],
                    monitor['width'], monitor['height']
                )
                if value is not None:
                    self.value_updated.emit(row, value)
                    lower = monitor['lower']
                    upper = monitor['upper']
                    if value < lower or value > upper:
                        if not monitor_status[row]['alarm']:
                            monitor_status[row]['alarm'] = True
                            self.alarm_triggered.emit(row, name, value, lower, upper)
                        self.status_updated.emit(row, 'alarm')
                    else:
                        monitor_status[row]['alarm'] = False
                        self.status_updated.emit(row, 'normal')
                    monitor_status[row]['error_count'] = 0
                else:
                    monitor_status[row]['error_count'] += 1
                    if monitor_status[row]['error_count'] >= 3:
                        self.status_updated.emit(row, 'error')
                    else:
                        self.status_updated.emit(row, '识别中...')
                time.sleep(0.05)
            time.sleep(0.3)
        if self.sct:
            self.sct.close()
