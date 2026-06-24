import time
import re
import numpy as np
from PySide6.QtCore import QThread, Signal

try:
    import easyocr
    import mss
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"依赖库未安装: {e}")


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
            self.ocr_status.emit("EasyOCR未安装", False)
            return False
        try:
            self.ocr_status.emit("加载模型中...", False)
            self.reader = easyocr.Reader(['en'], gpu=False)
            self.ocr_ready = True
            self.ocr_status.emit("就绪", True)
            return True
        except Exception as e:
            self.ocr_status.emit(f"初始化失败: {str(e)[:30]}", False)
            return False
    
    def _capture_and_ocr(self, x1, y1, x2, y2):
        if not self.ocr_ready or self.reader is None:
            return None
        if self.sct is None:
            self.sct = mss.mss()
        try:
            width = x2 - x1
            height = y2 - y1
            if width <= 0 or height <= 0:
                return None
            monitor = {"top": y1, "left": x1, "width": width, "height": height}
            screenshot = self.sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)
            
            results = self.reader.readtext(
                img_np,
                allowlist='0123456789.-',
                paragraph=False
            )
            for bbox, text, confidence in results:
                numbers = re.findall(r'-?\d+\.?\d*', text)
                if numbers and confidence > 0.3:
                    return float(numbers[0])
            return None
        except Exception as e:
            return None
    
    def run(self):
        if not self._init_ocr():
            return
        
        status = {}
        for m in self.monitors:
            status[m['row']] = {'alarm': False, 'count': 0}
            self.status_updated.emit(m['row'], '监控中')
        
        while self.running:
            for monitor in self.monitors:
                if not self.running:
                    break
                row = monitor['row']
                value = self._capture_and_ocr(
                    monitor['x1'], monitor['y1'],
                    monitor['x2'], monitor['y2']
                )
                
                if value is not None:
                    self.value_updated.emit(row, value)
                    lower, upper = monitor['lower'], monitor['upper']
                    
                    if value < lower or value > upper:
                        if not status[row]['alarm']:
                            status[row]['alarm'] = True
                            self.alarm_triggered.emit(
                                row, monitor['name'], value, lower, upper
                            )
                        self.status_updated.emit(row, '报警')
                    else:
                        status[row]['alarm'] = False
                        self.status_updated.emit(row, '正常')
                    status[row]['count'] = 0
                else:
                    status[row]['count'] += 1
                    if status[row]['count'] >= 3:
                        self.status_updated.emit(row, '识别失败')
                
                time.sleep(0.05)
            time.sleep(0.3)
        
        if self.sct:
            self.sct.close()
