import time
import re
import numpy as np
import os
import sys
from PySide6.QtCore import QThread, Signal
import cv2

try:
    from paddleocr import PaddleOCR
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
    download_progress = Signal(int)
    
    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.ocr = None
        self.ocr_ready = False
        self.interval_ms = 500
        
        self.value_cache = {}
        self.cache_count = {}
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def stop(self):
        self.running = False
    
    def _init_ocr(self):
        """初始化OCR - 使用PaddleOCR，自动下载模型"""
        if not OCR_AVAILABLE:
            self.ocr_status.emit("PaddleOCR未安装", False)
            return False
        
        try:
            import warnings
            warnings.filterwarnings("ignore")
            
            self.ocr_status.emit("正在加载PaddleOCR (首次使用自动下载模型)...", False)
            self.download_progress.emit(0)
            
            # 创建PaddleOCR实例 - 使用正确的参数
            self.ocr = PaddleOCR(
                lang='en',           # 英文
                use_angle_cls=False, # 不使用角度分类
                use_gpu=False,       # 不使用GPU
                show_log=False,      # 不显示日志
                enable_mkldnn=False  # 不使用MKLDNN
            )
            
            # 如果初始化成功，标记就绪
            self.ocr_ready = True
            self.download_progress.emit(100)
            self.ocr_status.emit("就绪 ✅", True)
            return True
            
        except Exception as e:
            error_msg = str(e)
            if "Connection" in error_msg or "timeout" in error_msg.lower():
                self.ocr_status.emit("网络连接失败，请检查网络后点击「重新加载OCR」", False)
            else:
                self.ocr_status.emit(f"加载失败: {error_msg[:50]}", False)
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
            
            # 转为RGB（PaddleOCR需要）
            rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
            
            return rgb
            
        except Exception as e:
            return img_np
    
    def _capture_and_ocr(self, x, y, width, height):
        """捕获屏幕并识别数字 - 使用PaddleOCR"""
        if not self.ocr_ready or self.ocr is None:
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
            
            # PaddleOCR识别
            # 只检测文字，不进行检测和角度分类
            result = self.ocr.ocr(processed, cls=False)
            
            if result and len(result) > 0:
                # 遍历所有识别结果
                for line in result:
                    if line:
                        for word_info in line:
                            # word_info 格式: [bbox, (text, confidence)]
                            if len(word_info) >= 2:
                                text = word_info[1][0] if isinstance(word_info[1], tuple) else word_info[1]
                                # 提取数字
                                numbers = re.findall(r'-?\d+\.?\d*', text)
                                if numbers:
                                    return float(numbers[0])
            
            return None
            
        except Exception as e:
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR加载失败，请检查网络后点击「重新加载OCR」')
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
