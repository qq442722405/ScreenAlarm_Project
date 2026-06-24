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
        
        # 数字识别缓存 - 提高稳定性
        self.value_cache = {}
        self.cache_count = {}
        
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
            # 使用更精确的配置
            self.reader = easyocr.Reader(
                ['en'], 
                gpu=False,
                model_storage_directory='./ocr_models',
                recog_network='en'  # 使用英文识别网络
            )
            self.ocr_ready = True
            self.ocr_status.emit("就绪", True)
            return True
        except Exception as e:
            self.ocr_status.emit(f"初始化失败: {str(e)[:30]}", False)
            return False
    
    def _preprocess_image(self, img_np):
        """图像预处理 - 专门针对数字优化"""
        try:
            # 转为灰度图
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np
            
            # 1. 自适应直方图均衡化 - 增强对比度
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            
            # 2. 检测是否黑底白字（计算平均亮度）
            avg_brightness = np.mean(enhanced)
            
            if avg_brightness < 80:
                # 黑底白字 - 反转颜色
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            # 3. 高斯模糊去噪（轻微）
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            
            # 4. 使用OTSU自适应二值化（比自适应阈值更稳定）
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 5. 形态学操作 - 去除小噪点，连接断裂数字
            kernel = np.ones((2, 2), np.uint8)
            
            # 先开运算去除噪点
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
            
            # 再闭运算连接断裂
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)
            
            # 6. 扩大数字区域（让小数字变大）
            if cleaned.shape[0] < 40 or cleaned.shape[1] < 40:
                scale = min(3, int(80 / max(cleaned.shape[0], cleaned.shape[1])))
                if scale > 1:
                    cleaned = cv2.resize(cleaned, None, fx=scale, fy=scale, 
                                       interpolation=cv2.INTER_CUBIC)
            
            # 7. 边缘增强 - 让数字更清晰
            kernel_sharpen = np.array([[0, -1, 0],
                                       [-1, 5, -1],
                                       [0, -1, 0]])
            sharpened = cv2.filter2D(cleaned, -1, kernel_sharpen)
            
            # 8. 再次二值化确保黑白分明
            _, final = cv2.threshold(sharpened, 127, 255, cv2.THRESH_BINARY)
            
            return final
            
        except Exception as e:
            print(f"预处理失败: {e}")
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
            
            # 截图
            monitor = {"top": y, "left": x, "width": width, "height": height}
            screenshot = self.sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)
            
            # 预处理图像
            processed = self._preprocess_image(img_np)
            
            # 方法1：使用EasyOCR识别
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
            
            # 提取所有数字
            all_numbers = []
            for bbox, text, confidence in results:
                # 提取数字和点号
                numbers = re.findall(r'-?\d+\.?\d*', text)
                for num_str in numbers:
                    try:
                        value = float(num_str)
                        # 根据置信度加权
                        weight = confidence if confidence > 0.2 else 0.2
                        all_numbers.append((value, weight, len(num_str)))
                    except ValueError:
                        continue
            
            # 方法2：如果方法1没有结果，使用原始图像直接识别
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
            
            # 如果没有识别到数字，返回None
            if len(all_numbers) == 0:
                return None
            
            # 选择最佳结果
            # 优先选择长度较长的数字（避免识别为1.0而不是100）
            # 按数字长度排序，取最长的
            all_numbers.sort(key=lambda x: (x[2], x[1]), reverse=True)
            
            # 取最高置信度且长度最长的
            best = all_numbers[0]
            best_value = best[0]
            
            # 特殊处理：如果数字是整数但识别为小数，尝试修正
            # 例如 1.0 -> 100 (如果原始数字应该是整数)
            if best_value % 1 == 0:
                # 已经是整数，直接返回
                return best_value
            else:
                # 可能是整数被识别为小数，检查是否有其他候选
                for value, weight, length in all_numbers:
                    if value % 1 == 0 and length >= best[2]:
                        return value
                return best_value
            
        except Exception as e:
            print(f"OCR识别错误: {e}")
            return None
    
    def run(self):
        if not self._init_ocr():
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
                    # 使用缓存平滑数值（防止偶尔识别错误）
                    cache_key = row
                    if cache_key in self.value_cache:
                        # 如果数值变化太大，可能是识别错误，使用缓存值
                        if abs(value - self.value_cache[cache_key]) > 50:
                            # 连续识别3次确认才更新
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
