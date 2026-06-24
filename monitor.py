import time
import re
import numpy as np
import os
import sys
from PySide6.QtCore import QThread, Signal
import cv2
import pytesseract
from PIL import Image

try:
    import mss
    OCR_AVAILABLE = True
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"依赖库未安装: {e}")

# 设置 Tesseract 路径（Windows）
if sys.platform == 'win32':
    tesseract_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]
    for path in tesseract_paths:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            break


class MonitorThread(QThread):
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)
    download_progress = Signal(int)  # 保留用于兼容
    
    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.ocr_ready = False
        self.interval_ms = 500
        
        self.value_cache = {}
        self.cache_count = {}
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def stop(self):
        self.running = False
    
    def _init_ocr(self):
        """初始化OCR - 使用Tesseract"""
        try:
            # 测试 Tesseract 是否可用
            version = pytesseract.get_tesseract_version()
            self.ocr_ready = True
            self.ocr_status.emit(f"就绪 ✅ (Tesseract {version})", True)
            return True
        except Exception as e:
            self.ocr_status.emit(
                "Tesseract未安装，请安装Tesseract OCR引擎\n"
                "下载地址: https://github.com/UB-Mannheim/tesseract/wiki\n"
                "安装后重启程序", 
                False
            )
            return False
    
    def _preprocess_image(self, img_np):
        """图像预处理 - 针对数字优化"""
        try:
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            # 增强对比度
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # 检测黑底白字
            avg_brightness = np.mean(enhanced)
            if avg_brightness < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            # 高斯模糊去噪
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            
            # OTSU二值化
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 形态学操作
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            
            # 如果图像太小，放大
            if cleaned.shape[0] < 40 or cleaned.shape[1] < 40:
                scale = min(3, int(80 / max(cleaned.shape[0], cleaned.shape[1])))
                if scale > 1:
                    cleaned = cv2.resize(cleaned, None, fx=scale, fy=scale, 
                                       interpolation=cv2.INTER_CUBIC)
            
            return cleaned
            
        except Exception as e:
            return img_np
    
    def _capture_and_ocr(self, x, y, width, height):
        """捕获屏幕并识别数字 - 使用Tesseract"""
        if not self.ocr_ready:
            return None
        if self.sct is None:
            self.sct = mss.mss()
        try:
            if width <= 0 or height <= 0:
                return None
            
            # 截图
            monitor = {"top": y, "left": x, "width": width, "height": height}
            screenshot = self.sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)
            
            # 预处理
            processed = self._preprocess_image(img_np)
            
            # 只识别数字（白名单）
            custom_config = r'--psm 8 -c tessedit_char_whitelist=0123456789.'
            
            # 识别
            text = pytesseract.image_to_string(processed, config=custom_config)
            
            # 提取数字
            numbers = re.findall(r'-?\d+\.?\d*', text)
            if numbers:
                return float(numbers[0])
            
            # 如果第一次失败，尝试原始图像
            text2 = pytesseract.image_to_string(img_np, config=custom_config)
            numbers2 = re.findall(r'-?\d+\.?\d*', text2)
            if numbers2:
                return float(numbers2[0])
            
            return None
            
        except Exception as e:
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR初始化失败，请安装Tesseract')
            return
        
        status = {}
        for m in self.monitors:
            status[m['row']] = {'alarm': False, 'count': 0, 'last_value': None}
            self.status_updated.emit(m['row'], '监控中')
        
        interval_sec = self.interval_ms / 1000.0
        
        while self.running:
            for monitor in self.monitors:
                if not self.running:
                    break
                row = monitor['row']
                value = self._capture_and_ocr(
                    monitor['x'], monitor['y'],
                    monitor['width'], monitor['height']
                )
                
                if value is not None:
                    cache_key = row
                    if cache_key in self.value_cache:
                        if abs(value - self.value_cache[cache_key]) > 50:
                            if cache_key not in self.cache_count:
                                self.cache_count[cache_key] = 0
                            self.cache_count[cache_key] += 1
                            if self.cache_count[cache_key] >= 2:
                                self.value_cache[cache_key] = value
                                self.cache_count[cache_key] = 0
                            else:
                                value = self.value_cache[cache_key]
                        else:
                            self.value_cache[cache_key] = value
                            self.cache_count[cache_key] = 0
                    else:
                        self.value_cache[cache_key] = value
                        self.cache_count[cache_key] = 0
                    
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
            
            time.sleep(max(0.1, interval_sec - 0.3))
        
        if self.sct:
            self.sct.close()
