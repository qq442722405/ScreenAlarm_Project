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
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"EasyOCR未安装: {e}")


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
        self.interval_ms = 500
        
        self.value_cache = {}
        self.cache_count = {}
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def stop(self):
        self.running = False
    
    def _init_ocr(self):
        """初始化EasyOCR - 自动下载模型到程序目录"""
        if not OCR_AVAILABLE:
            self.ocr_status.emit("EasyOCR未安装，请运行: pip install easyocr", False)
            return False
        
        try:
            # 模型存储到程序目录下的 ocr_models 文件夹
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            model_dir = os.path.join(base_dir, 'ocr_models')
            
            # 创建目录
            if not os.path.exists(model_dir):
                os.makedirs(model_dir, exist_ok=True)
            
            self.ocr_status.emit("正在下载/加载EasyOCR模型 (首次约200MB)...", False)
            
            # 创建Reader，自动下载模型到 model_dir
            self.reader = easyocr.Reader(
                ['en'],
                gpu=False,
                model_storage_directory=model_dir,
                download_enabled=True,  # 允许自动下载
                verbose=False
            )
            
            if self.reader is not None:
                self.ocr_ready = True
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
    
    def _preprocess_image(self, img_np):
        """图像预处理"""
        try:
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            # 增强对比度
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # 黑底白字修正
            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            # 高斯模糊
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 转为RGB（EasyOCR需要）
            rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
            return rgb
            
        except Exception as e:
            return img_np
    
    def _capture_and_ocr(self, x, y, width, height):
        """截图并识别"""
        if not self.ocr_ready or self.reader is None:
            return None
        if self.sct is None:
            self.sct = mss.mss()
        try:
            if width <= 0 or height <= 0:
                return None
            
            monitor = {"top": y, "left": x, "width": width, "height": height}
            screenshot = self.sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)
            
            # 预处理
            processed = self._preprocess_image(img_np)
            
            # EasyOCR识别 - 只识别数字
            result = self.reader.readtext(
                processed,
                allowlist='0123456789.-',
                paragraph=False,
                width_ths=0.5,
                height_ths=0.5
            )
            
            for bbox, text, confidence in result:
                if confidence > 0.3:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    if numbers:
                        return float(numbers[0])
            
            # 如果预处理失败，尝试原图
            result2 = self.reader.readtext(
                img_np,
                allowlist='0123456789.-',
                paragraph=False
            )
            for bbox, text, confidence in result2:
                if confidence > 0.3:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    if numbers:
                        return float(numbers[0])
            
            return None
            
        except Exception as e:
            print(f"识别异常: {e}")
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR加载失败，请检查网络后重启')
            return
        
        status = {}
        for m in self.monitors:
            status[m['row']] = {'alarm': False, 'count': 0}
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
                    self.value_updated.emit(row, float(value))
                    lower, upper = monitor['lower'], monitor['upper']
                    
                    if value < lower or value > upper:
                        if not status[row]['alarm']:
                            status[row]['alarm'] = True
                            self.alarm_triggered.emit(
                                row, monitor['name'], float(value), lower, upper
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
            
            time.sleep(max(0.05, interval_sec - 0.3))
        
        if self.sct:
            self.sct.close()
