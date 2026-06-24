import time
import re
import numpy as np
from PySide6.QtCore import QThread, Signal
import cv2

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
        self.interval_ms = 500
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
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
    
    def _preprocess_image(self, img_np):
        """图像预处理 - 增强OCR识别率，支持黑底白字"""
        try:
            # 转为灰度图
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            # 1. 自适应直方图均衡化 - 增强对比度
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # 2. 检测是否黑底白字（计算平均亮度）
            avg_brightness = np.mean(enhanced)
            
            if avg_brightness < 80:
                # 黑底白字 - 反转颜色
                enhanced = 255 - enhanced
                # 再次增强对比度
                enhanced = clahe.apply(enhanced)
            
            # 3. 自适应二值化
            binary = cv2.adaptiveThreshold(
                enhanced, 255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 15, 3
            )
            
            # 4. 形态学操作 - 去噪
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
            
            # 5. 锐化
            kernel_sharpen = np.array([[-1, -1, -1],
                                       [-1,  9, -1],
                                       [-1, -1, -1]])
            sharpened = cv2.filter2D(cleaned, -1, kernel_sharpen)
            
            # 6. 放大图像（提高小数字识别率）
            if sharpened.shape[0] < 30 or sharpened.shape[1] < 30:
                scale = max(2, int(60 / min(sharpened.shape)))
                sharpened = cv2.resize(sharpened, None, fx=scale, fy=scale, 
                                       interpolation=cv2.INTER_CUBIC)
            
            return sharpened
            
        except Exception as e:
            print(f"预处理失败: {e}")
            return img_np
    
    def _capture_and_ocr(self, x, y, width, height):
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
            
            # 预处理图像
            processed = self._preprocess_image(img_np)
            
            # 尝试多种识别方式
            results = self.reader.readtext(
                processed,
                allowlist='0123456789.-',
                paragraph=False,
                width_ths=0.5,
                height_ths=0.5
            )
            
            for bbox, text, confidence in results:
                numbers = re.findall(r'-?\d+\.?\d*', text)
                if numbers and confidence > 0.2:
                    return float(numbers[0])
            
            # 如果第一次失败，尝试原始图像
            results2 = self.reader.readtext(
                img_np,
                allowlist='0123456789.-',
                paragraph=False
            )
            for bbox, text, confidence in results2:
                numbers = re.findall(r'-?\d+\.?\d*', text)
                if numbers and confidence > 0.3:
                    return float(numbers[0])
            
            return None
        except Exception as e:
            print(f"OCR识别错误: {e}")
            return None
    
    def run(self):
        if not self._init_ocr():
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
