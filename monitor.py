import time
import re
import os
import sys
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
import mss
from PIL import Image

# --- 数字模板生成器 ---
# 程序启动时，自动生成 0-9 的数字模板（使用OpenCV绘制）
class DigitTemplateGenerator:
    """在内存中生成数字模板，无需外部文件"""
    _templates = None

    @classmethod
    def get_templates(cls):
        if cls._templates is not None:
            return cls._templates

        templates = {}
        # 创建画布，白色背景，黑色文字
        for digit in range(10):
            # 创建一个200x300的白色画布，用于绘制高质量数字
            img = np.ones((200, 150), dtype=np.uint8) * 255
            # 绘制数字
            cv2.putText(img, str(digit), (15, 170), 
                        cv2.FONT_HERSHEY_SIMPLEX, 6, (0, 0, 0), 6, cv2.LINE_AA)
            # 裁剪掉多余白边，缩小模板
            coords = cv2.findNonZero(255 - img)
            if coords is not None:
                x, y, w, h = cv2.boundingRect(coords)
                # 添加一些边距
                margin = 5
                x = max(0, x - margin)
                y = max(0, y - margin)
                w = min(img.shape[1] - x, w + 2 * margin)
                h = min(img.shape[0] - y, h + 2 * margin)
                template = img[y:y+h, x:x+w]
                # 归一化到统一高度 (40像素)
                template = cv2.resize(template, (int(template.shape[1] * 40 / template.shape[0]), 40))
                templates[digit] = template
            else:
                # 极端情况，生成一个简单的备用模板
                template = np.ones((40, 30), dtype=np.uint8) * 255
                cv2.putText(template, str(digit), (2, 32), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2, cv2.LINE_AA)
                templates[digit] = template

        cls._templates = templates
        return templates


class MonitorThread(QThread):
    """监控线程 - 基于模板匹配的数字识别"""
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)  # 保持与原有UI兼容

    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.interval_ms = 500
        self.digit_templates = None
        self.ocr_ready = False

        # 值缓存，用于平滑识别结果
        self.value_cache = {}
        self.cache_count = {}

    def set_interval(self, ms):
        self.interval_ms = max(100, ms)

    def stop(self):
        self.running = False

    def _init_ocr(self):
        """初始化模板匹配引擎"""
        self.ocr_status.emit("正在生成数字模板...", False)
        try:
            self.digit_templates = DigitTemplateGenerator.get_templates()
            if self.digit_templates and len(self.digit_templates) == 10:
                self.ocr_ready = True
                self.ocr_status.emit("就绪 ✅ (模板匹配)", True)
                return True
            else:
                self.ocr_status.emit("模板生成失败", False)
                return False
        except Exception as e:
            self.ocr_status.emit(f"初始化失败: {str(e)[:50]}", False)
            return False

    def _preprocess_image(self, img_np):
        """图像预处理: 转为灰度图, 增强对比度, 二值化"""
        try:
            if len(img_np.shape) == 3:
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_np

            # 自适应直方图均衡化 (CLAHE) 增强对比度
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            # 自动检测并修正黑底白字
            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)

            # 高斯模糊去噪
            blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)
            # OTSU 二值化
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # 形态学操作，去除小噪点，连接断裂
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            return cleaned

        except Exception as e:
            print(f"预处理异常: {e}")
            return img_np

    def _extract_digits_from_image(self, processed_img):
        """从预处理图像中提取并识别所有数字"""
        if not self.ocr_ready or self.digit_templates is None:
            return None

        # 寻找轮廓
        contours, _ = cv2.findContours(processed_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        recognized_chars = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # 过滤掉太小的噪点
            if w < 8 or h < 12:
                continue
            
            # 提取候选区域，并添加边距
            margin = 2
            roi = processed_img[max(0, y-margin):min(processed_img.shape[0], y+h+margin), 
                                max(0, x-margin):min(processed_img.shape[1], x+w+margin)]
            if roi.size == 0:
                continue

            # 调整候选区域大小以匹配模板
            roi_height = 40
            roi_width = int(roi.shape[1] * (40 / roi.shape[0]))
            if roi_width < 10:  # 太窄，忽略
                continue
            roi_resized = cv2.resize(roi, (roi_width, roi_height))

            best_match = None
            best_score = 0.5  # 最低匹配阈值

            # 逐个模板匹配
            for digit, template in self.digit_templates.items():
                # 模板匹配
                method = cv2.TM_CCOEFF_NORMED
                # 如果候选区域比模板宽，滑动匹配
                if roi_resized.shape[1] >= template.shape[1]:
                    res = cv2.matchTemplate(roi_resized, template, method)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score:
                        best_score = max_val
                        best_match = digit
                else:
                    # 候选区域较窄时，尝试缩放模板或使用更宽松的阈值
                    # 简单处理：直接比较平均像素
                    roi_resized_small = cv2.resize(roi_resized, (template.shape[1], template.shape[0]))
                    res = cv2.matchTemplate(roi_resized_small, template, method)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    if max_val > best_score:
                        best_score = max_val
                        best_match = digit

            if best_match is not None:
                recognized_chars.append((x, best_match))  # 按x坐标排序

        # 按x坐标排序，组合数字
        if recognized_chars:
            recognized_chars.sort(key=lambda item: item[0])
            # 提取连续的数字序列
            number_str = ''.join([str(digit) for _, digit in recognized_chars])
            # 尝试提取最长的连续数字序列
            matches = re.findall(r'\d+', number_str)
            if matches:
                longest_match = max(matches, key=len)
                # 如果识别到 100，但 split 成了 1,0,0，拼接后为 "100"
                return int(longest_match) if longest_match else None
        return None

    def _capture_and_recognize(self, x, y, width, height):
        """截图并识别数字"""
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
            # 数字识别
            recognized_value = self._extract_digits_from_image(processed)
            return recognized_value

        except Exception as e:
            print(f"识别异常: {e}")
            return None

    def run(self):
        if not self._init_ocr():
            self.status_updated.emit(-1, '引擎初始化失败')
            return

        # 初始化状态
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
                    # 可选：缓存平滑（避免小波动）
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
                
                time.sleep(0.05)  # 小延迟，避免CPU占用过高

            time.sleep(max(0.05, interval_sec - 0.3))

        if self.sct:
            self.sct.close()
