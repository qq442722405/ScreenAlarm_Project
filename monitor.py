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
        self.is_row_muted = None
        self.alarm_loop_enabled = True
        
        self.alarm_status = {}
        self.manual_clear = False
        
        self.value_history = {}
        self.smooth_count = 5
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def set_alarm_loop(self, enabled):
        self.alarm_loop_enabled = enabled
    
    def stop(self):
        self.running = False
    
    def reset_all_alarms(self):
        self.manual_clear = True
        for row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
        for row in self.alarm_status:
            self.status_updated.emit(row, 'normal')
    
    def _is_enabled(self, row):
        if self.get_row_enabled:
            try:
                return self.get_row_enabled(row)
            except:
                return True
        return True
    
    def _is_muted(self, row):
        if self.is_row_muted:
            try:
                return self.is_row_muted(row)
            except:
                return False
        return False
    
    def _smooth_value(self, row, raw_value):
        if row not in self.value_history:
            self.value_history[row] = []
        
        self.value_history[row].append(raw_value)
        
        if len(self.value_history[row]) > self.smooth_count:
            self.value_history[row].pop(0)
        
        if len(self.value_history[row]) >= 2:
            sorted_vals = sorted(self.value_history[row])
            if len(sorted_vals) >= 3:
                trimmed = sorted_vals[1:-1]
                if trimmed:
                    return sum(trimmed) / len(trimmed)
            return sum(self.value_history[row]) / len(self.value_history[row])
        else:
            return raw_value
    
    def _init_ocr(self):
        if not OCR_AVAILABLE:
            self.ocr_status.emit("EasyOCR未安装，请运行: pip install easyocr", False)
            return False
        
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            model_dir = os.path.join(base_dir, 'ocr_models')
            
            if not os.path.exists(model_dir):
                os.makedirs(model_dir, exist_ok=True)
            
            self.ocr_status.emit("正在下载/加载EasyOCR模型 (首次约200MB)...", False)
            self.download_progress.emit(0)
            
            self.reader = easyocr.Reader(
                ['en'],
                gpu=False,
                model_storage_directory=model_dir,
                download_enabled=True,
                verbose=False
            )
            
            if self.reader is not None:
                self.ocr_ready = True
                self.download_progress.emit(100)
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
        try:
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
            return rgb
            
        except Exception as e:
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
            
            processed = self._preprocess_image(img_np)
            
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
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR加载失败，请检查网络后重启')
            return
        
        for m in self.monitors:
            self.alarm_status[m['row']] = {
                'alarm': False, 
                'count': 0,
                'last_alarm_time': 0
            }
            self.status_updated.emit(m['row'], '监控中')
        
        interval_sec = self.interval_ms / 1000.0
        
        while self.running:
            for monitor in self.monitors:
                if not self.running:
                    break
                row = monitor['row']
                
                if not self._is_enabled(row):
                    self.status_updated.emit(row, 'disabled')
                    self.alarm_status[row]['alarm'] = False
                    continue
                
                raw_value = self._capture_and_ocr(
                    monitor['x'], monitor['y'],
                    monitor['width'], monitor['height']
                )
                
                if raw_value is not None:
                    smooth_value = self._smooth_value(row, raw_value)
                    
                    self.value_updated.emit(row, float(smooth_value))
                    lower, upper = monitor['lower'], monitor['upper']
                    
                    if smooth_value < lower or smooth_value > upper:
                        now = time.time()
                        last_time = self.alarm_status[row]['last_alarm_time']
                        
                        if not self.alarm_status[row]['alarm']:
                            # 首次报警
                            self.alarm_status[row]['alarm'] = True
                            self.alarm_status[row]['last_alarm_time'] = now
                            self.alarm_triggered.emit(
                                row, monitor['name'], float(smooth_value), lower, upper
                            )
                        elif self.alarm_loop_enabled:
                            # 循环报警：每10秒重新触发
                            if now - last_time > 10:
                                self.alarm_status[row]['last_alarm_time'] = now
                                self.alarm_triggered.emit(
                                    row, monitor['name'], float(smooth_value), lower, upper
                            )
                        self.status_updated.emit(row, '报警')
                    else:
                        if not self.manual_clear:
                            self.alarm_status[row]['alarm'] = False
                            self.status_updated.emit(row, '正常')
                        else:
                            self.alarm_status[row]['alarm'] = False
                    self.alarm_status[row]['count'] = 0
                else:
                    self.alarm_status[row]['count'] += 1
                    if self.alarm_status[row]['count'] >= 3:
                        self.status_updated.emit(row, '识别失败')
                
                time.sleep(0.05)
            
            time.sleep(max(0.05, interval_sec - 0.3))
        
        if self.sct:
            self.sct.close()
