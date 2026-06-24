import time
import re
import cv2
import numpy as np
import mss
from PIL import Image
from PySide6.QtCore import QThread, Signal


class DigitRecognizer:
    """纯 Python 数字识别器，无需任何外部引擎"""
    
    def __init__(self):
        self.templates = self._generate_templates()
        self.char_templates = self._generate_char_templates()
    
    def _generate_templates(self):
        """在内存中生成数字模板 (多种字体变体)"""
        templates = {}
        
        # 为每个数字生成多种尺寸和字体变体
        for digit in range(10):
            template_list = []
            
            # 标准字体
            for size in range(28, 52, 4):  # 不同字号
                for thickness in range(2, 5):  # 不同粗细
                    img = np.ones((100, 80), dtype=np.uint8) * 255
                    cv2.putText(img, str(digit), (8, 75), 
                               cv2.FONT_HERSHEY_SIMPLEX, size/20, (0, 0, 0), thickness, cv2.LINE_AA)
                    
                    # 裁剪
                    coords = cv2.findNonZero(255 - img)
                    if coords is not None:
                        x, y, w, h = cv2.boundingRect(coords)
                        if w > 5 and h > 8:
                            template = img[y:y+h, x:x+w]
                            template = cv2.resize(template, (30, 40))
                            template_list.append(template)
            
            # 数字7的特殊处理 (有些7带横杠)
            if digit == 7:
                img = np.ones((100, 80), dtype=np.uint8) * 255
                cv2.putText(img, "7", (8, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 3, cv2.LINE_AA)
                # 加横杠
                cv2.line(img, (15, 30), (35, 30), (0, 0, 0), 2)
                coords = cv2.findNonZero(255 - img)
                if coords is not None:
                    x, y, w, h = cv2.boundingRect(coords)
                    template = img[y:y+h, x:x+w]
                    template = cv2.resize(template, (30, 40))
                    template_list.append(template)
            
            if template_list:
                templates[digit] = template_list
            else:
                # 备用模板
                img = np.ones((40, 30), dtype=np.uint8) * 255
                cv2.putText(img, str(digit), (2, 32), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2, cv2.LINE_AA)
                templates[digit] = [img]
        
        return templates
    
    def _generate_char_templates(self):
        """生成字符模板（用于处理粘连数字）"""
        templates = {}
        chars = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
        for i, char in enumerate(chars):
            img = np.ones((60, 40), dtype=np.uint8) * 255
            cv2.putText(img, char, (2, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3, cv2.LINE_AA)
            coords = cv2.findNonZero(255 - img)
            if coords is not None:
                x, y, w, h = cv2.boundingRect(coords)
                template = img[y:y+h, x:x+w]
                template = cv2.resize(template, (25, 35))
                templates[i] = template
        return templates
    
    def _match_template(self, roi, templates):
        """匹配单个数字"""
        best_match = None
        best_score = 0.35
        
        for digit, template_list in templates.items():
            for template in template_list:
                try:
                    # 调整大小匹配
                    if roi.shape[0] > template.shape[0] * 1.5 or roi.shape[1] > template.shape[1] * 1.5:
                        roi_resized = cv2.resize(roi, (template.shape[1], template.shape[0]))
                        result = cv2.matchTemplate(roi_resized, template, cv2.TM_CCOEFF_NORMED)
                    elif roi.shape[0] < template.shape[0] * 0.6 or roi.shape[1] < template.shape[1] * 0.6:
                        template_resized = cv2.resize(template, (roi.shape[1], roi.shape[0]))
                        result = cv2.matchTemplate(roi, template_resized, cv2.TM_CCOEFF_NORMED)
                    else:
                        result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
                    
                    _, max_val, _, _ = cv2.minMaxLoc(result)
                    if max_val > best_score:
                        best_score = max_val
                        best_match = digit
                except:
                    continue
        
        return best_match, best_score
    
    def _recognize_digit(self, roi):
        """识别单个数字区域"""
        # 先用大模板匹配
        digit, score = self._match_template(roi, self.templates)
        
        # 如果置信度不够，尝试用字符模板
        if score < 0.45:
            digit2, score2 = self._match_template(roi, self.char_templates)
            if score2 > score:
                digit, score = digit2, score2
        
        return digit, score
    
    def _split_connected_digits(self, binary, x, y, w, h):
        """尝试分割粘连的数字"""
        roi = binary[y:y+h, x:x+w]
        if roi.shape[1] < 10:
            return [(x, y, w, h)]
        
        # 垂直投影
        projection = np.sum(roi == 0, axis=0)
        threshold = np.max(projection) * 0.3
        
        splits = []
        start = 0
        in_gap = False
        gap_start = 0
        
        for i, val in enumerate(projection):
            if val < threshold:
                if not in_gap:
                    in_gap = True
                    gap_start = i
            else:
                if in_gap and i - gap_start > 3:
                    # 找到分割点
                    if i - start > 8:  # 最小宽度
                        splits.append((start, i))
                    start = i
                    in_gap = False
        
        if start < len(projection) - 1:
            splits.append((start, len(projection)))
        
        result = []
        for s, e in splits:
            if e - s > 5:
                result.append((x + s, y, e - s, h))
        return result
    
    def _extract_digits(self, binary):
        """从二值图像中提取并识别所有数字"""
        # 膨胀操作，连接断裂的数字
        kernel = np.ones((2, 2), np.uint8)
        dilated = cv2.dilate(binary, kernel, iterations=1)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        digit_regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 6 or h < 10:
                continue
            if w > h * 3:  # 可能是多个数字粘连
                split_regions = self._split_connected_digits(binary, x, y, w, h)
                digit_regions.extend(split_regions)
            else:
                digit_regions.append((x, y, w, h))
        
        # 合并重叠区域
        digit_regions.sort(key=lambda r: r[0])
        merged = []
        for region in digit_regions:
            if not merged:
                merged.append(region)
            else:
                last = merged[-1]
                if region[0] - (last[0] + last[2]) < 3:
                    # 合并
                    new_w = region[0] + region[2] - last[0]
                    merged[-1] = (last[0], min(last[1], region[1]), new_w, max(last[3], region[3]))
                else:
                    merged.append(region)
        
        # 识别每个区域
        recognized = []
        for x, y, w, h in merged:
            if w < 6 or h < 10:
                continue
            roi = binary[y:y+h, x:x+w]
            # 添加边距
            margin = 2
            roi = roi[max(0, y):min(binary.shape[0], y+h), max(0, x-margin):min(binary.shape[1], x+w+margin)]
            if roi.size == 0:
                continue
            
            # 调整大小
            roi_resized = cv2.resize(roi, (min(30, roi.shape[1]*2), min(40, roi.shape[0]*2)))
            
            digit, score = self._recognize_digit(roi_resized)
            if digit is not None and score > 0.35:
                recognized.append((x, digit, score))
        
        return recognized
    
    def recognize(self, image):
        """识别图像中的数字"""
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            else:
                gray = image
            
            # 自适应增强
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # 黑底白字检测
            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            
            # 高斯模糊
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            
            # OTSU二值化
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # 形态学去噪
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            
            # 提取数字
            recognized = self._extract_digits(cleaned)
            
            if recognized:
                # 按位置排序
                recognized.sort(key=lambda r: r[0])
                
                # 构建数字字符串
                number_str = ''.join(str(r[1]) for r in recognized)
                
                # 提取连续数字
                numbers = re.findall(r'\d+', number_str)
                if numbers:
                    # 选择最长的数字序列
                    longest = max(numbers, key=len)
                    if len(longest) >= 2:
                        return int(longest)
                    elif len(longest) == 1:
                        return int(longest)
            return None
            
        except Exception as e:
            print(f"识别异常: {e}")
            return None


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
        self.recognizer = None
        self.ocr_ready = False
        self.interval_ms = 500
        
        self.value_cache = {}
        self.cache_count = {}
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def stop(self):
        self.running = False
    
    def _init_ocr(self):
        """初始化纯Python数字识别器"""
        try:
            self.recognizer = DigitRecognizer()
            self.ocr_ready = True
            self.ocr_status.emit("就绪 ✅ (纯Python数字识别)", True)
            return True
        except Exception as e:
            self.ocr_status.emit(f"初始化失败: {str(e)[:50]}", False)
            return False
    
    def _preprocess_image(self, img_np):
        """图像预处理"""
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
            
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            
            return cleaned
        except Exception as e:
            return img_np
    
    def _capture_and_recognize(self, x, y, width, height):
        """截图并识别数字"""
        if not self.ocr_ready or self.recognizer is None:
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
            result = self.recognizer.recognize(processed)
            return result
            
        except Exception as e:
            print(f"识别异常: {e}")
            return None
    
    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, 'OCR初始化失败')
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
                value = self._capture_and_recognize(
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
