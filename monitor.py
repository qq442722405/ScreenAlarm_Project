import time
import re
import numpy as np
import os
import sys
import urllib.request
import zipfile
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
    download_progress = Signal(int)
    
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
    
    def _download_model(self, url, dest_path):
        """下载模型文件"""
        try:
            def report_progress(block_num, block_size, total_size):
                if total_size > 0:
                    progress = int(block_num * block_size / total_size * 100)
                    self.download_progress.emit(min(progress, 100))
                    if progress % 10 == 0:
                        self.ocr_status.emit(f"下载中... {progress}%", False)
            
            urllib.request.urlretrieve(url, dest_path, report_progress)
            return True
        except Exception as e:
            return False
    
    def _init_ocr(self):
        """初始化OCR - 自动下载模型到用户目录"""
        if not OCR_AVAILABLE:
            self.ocr_status.emit("EasyOCR未安装", False)
            return False
        
        # 用户数据目录
        user_data_dir = os.path.join(os.path.expanduser("~"), ".screen_monitor")
        model_dir = os.path.join(user_data_dir, "ocr_models")
        
        if not os.path.exists(model_dir):
            try:
                os.makedirs(model_dir, exist_ok=True)
            except:
                pass
        
        os.environ['EASYOCR_MODULE_PATH'] = model_dir
        
        # 检查模型是否存在
        model_file = os.path.join(model_dir, "english_g2.pth")
        model_zip = os.path.join(model_dir, "english_g2.zip")
        
        if not os.path.exists(model_file):
            self.ocr_status.emit("首次运行，正在下载OCR模型 (~200MB)...", False)
            self.download_progress.emit(0)
            
            url = "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/english_g2.zip"
            if not self._download_model(url, model_zip):
                self.ocr_status.emit("模型下载失败，请检查网络后重启", False)
                return False
            
            # 解压
            try:
                with zipfile.ZipFile(model_zip, 'r') as zip_ref:
                    zip_ref.extractall(model_dir)
                os.remove(model_zip)
                self.ocr_status.emit("模型解压完成", False)
            except Exception as e:
                self.ocr_status.emit(f"解压失败: {str(e)[:30]}", False)
                return False
        
        # 加载模型
        try:
            import warnings
            warnings.filterwarnings("ignore")
            
            self.reader = easyocr.Reader(
                ['en'], 
                gpu=False,
                model_storage_directory=model_dir,
                recog_network='en',
                download_enabled=False,
                verbose=False
            )
            
            if self.reader is not None:
                self.ocr_ready = True
                self.ocr_status.emit("就绪 ✅", True)
                return True
            else:
                self.ocr_status.emit("加载失败", False)
                return False
                
        except Exception as e:
            self.ocr_status.emit(f"加载失败: {str(e)[:30]}", False)
            return False
    
    def _preprocess_image(self, img_np):
        """图像预处理"""
        try:
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            
            avg_brightness = np.mean(enhanced)
            if avg_brightness < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)
            
            if cleaned.shape[0] < 40 or cleaned.shape[1] < 40:
                scale = min(3, int(80 / max(cleaned.shape[0], cleaned.shape[1])))
                if scale > 1:
                    cleaned = cv2.resize(cleaned, None, fx=scale, fy=scale, 
                                       interpolation=cv2.INTER_CUBIC)
            
            kernel_sharpen = np.array([[0, -1, 0],
                                       [-1, 5, -1],
                                       [0, -1, 0]])
            sharpened = cv2.filter2D(cleaned, -1, kernel_sharpen)
            _, final = cv2.threshold(sharpened, 127, 255, cv2.THRESH_BINARY)
            
            return final
            
        except Exception as e:
            return img_np
    
    def _capture_and_ocr(self, x, y, width, height):
        """捕获屏幕并识别数字"""
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
            
            results = self.reader.readtext(
                processed,
                allowlist='0123456789.-',
                paragraph=False,
                width_ths=0.3,
                height_ths=0.3,
                text_threshold=0.5,
                low_text=0.2,
                link_threshold=0.3,
                canvas_size=2560,
                mag_ratio=2.0
            )
            
            all_numbers = []
            for bbox, text, confidence in results:
                numbers = re.findall(r'-?\d+\.?\d*', text)
                for num_str in numbers:
                    try:
                        value = float(num_str)
                        weight = confidence if confidence > 0.2 else 0.2
                        all_numbers.append((value, weight, len(num_str)))
                    except ValueError:
                        continue
            
            if len(all_numbers) == 0:
                results2 = self.reader.readtext(
                    img_np,
                    allowlist='0123456789.-',
                    paragraph=False,
                    text_threshold=0.4,
                    low_text=0.2,
                )
                for bbox, text, confidence in results2:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    for num_str in numbers:
                        try:
                            value = float(num_str)
                            weight = confidence if confidence > 0.2 else 0.2
                            all_numbers.append((value, weight, len(num_str)))
                        except ValueError:
                            continue
            
            if len(all_numbers) == 0:
                return None
            
            all_numbers.sort(key=lambda x: (x[2], x[1]), reverse=True)
            best = all_numbers[0]
            best_value = best[0]
            
            for value, weight, length in all_numbers:
                if value % 1 == 0 and length >= best[2]:
                    return value
            
            return best_value
            
        except Exception as e:
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR加载失败，请检查网络后重启')
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
