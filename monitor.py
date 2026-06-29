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
except ImportError:
    OCR_AVAILABLE = False
    print("EasyOCR未安装")


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
        self.alarm_loop_enabled = True
        self.alarm_status = {}
        self.manual_clear = False

    def set_interval(self, ms):
        self.interval_ms = max(100, ms)

    def set_alarm_loop(self, enabled):
        self.alarm_loop_enabled = enabled

    def set_reader(self, reader):
        self.reader = reader
        if reader is not None:
            self.ocr_ready = True
            self.ocr_status.emit("就绪 ✅", True)

    def stop(self):
        self.running = False

    def reset_row_alarm(self, row):
        if row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
            self.alarm_status[row]['last_alarm_time'] = 0

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

    def _init_ocr(self):
        if self.reader is not None:
            return True
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
            self.reader = easyocr.Reader(['en'], gpu=False, model_storage_directory=model_dir, download_enabled=True, verbose=False)
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

    def _hex_to_hsv(self, hex_color):
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return None
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        r, g, b = r/255.0, g/255.0, b/255.0
        maxc = max(r, g, b)
        minc = min(r, g, b)
        diff = maxc - minc
        if diff == 0:
            h = 0
        elif maxc == r:
            h = ((g - b) / diff) % 6
        elif maxc == g:
            h = 2 + (b - r) / diff
        else:
            h = 4 + (r - g) / diff
        h = h * 60
        if h < 0:
            h += 360
        h = h / 2
        s = ((maxc - minc) / maxc) * 255 if maxc != 0 else 0
        v = maxc * 255
        return np.array([h, s, v], dtype=np.float32)

    def _color_match(self, img_np, target_hex, tolerance):
        try:
            hsv = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
            mean_hsv = np.mean(hsv, axis=(0, 1))
            target_hsv = self._hex_to_hsv(target_hex)
            if target_hsv is None:
                return False
            diff_h = abs(mean_hsv[0] - target_hsv[0])
            if diff_h > 180:
                diff_h = 360 - diff_h
            diff_s = abs(mean_hsv[1] - target_hsv[1])
            diff_v = abs(mean_hsv[2] - target_hsv[2])
            total_diff = diff_h/180 * 100 + diff_s/255 * 100 + diff_v/255 * 100
            return total_diff <= tolerance
        except:
            return False

    def _preprocess_image(self, img_np, sensitivity):
        try:
            sens = sensitivity
            h, w = img_np.shape[:2]
            max_dim = max(h, w)

            if max_dim < 100:
                scale = 3.0
            elif max_dim < 200:
                scale = 2.0
            elif max_dim < 400:
                scale = 1.5
            else:
                scale = 1.0

            if scale != 1.0:
                new_w = int(w * scale)
                new_h = int(h * scale)
                scaled = cv2.resize(img_np, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            else:
                scaled = img_np

            if len(scaled.shape) == 3:
                gray = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
            else:
                gray = scaled

            clip_limit = 1.0 + (sens / 10.0) * 2.0
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)

            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)

            kernel_sharpen = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
            sharpened = cv2.filter2D(enhanced, -1, kernel_sharpen)

            if max_dim > 300:
                block_size = max(3, int(3 + (10 - sens) * 0.8))
            else:
                block_size = max(3, int(5 + (10 - sens) * 1.5))
            if block_size % 2 == 0:
                block_size += 1
            c_value = max(1, int(2 + (10 - sens) * 0.3))

            binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, block_size, c_value)
            kernel = np.ones((2,2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
            return rgb
        except Exception:
            return img_np

    def _capture_and_ocr(self, monitor):
        if not self.ocr_ready or self.reader is None:
            return None
        if self.sct is None:
            self.sct = mss.mss()
        try:
            x, y, w, h = monitor['x'], monitor['y'], monitor['width'], monitor['height']
            if w <= 0 or h <= 0:
                return None
            monitor_region = {"top": y, "left": x, "width": w, "height": h}
            screenshot = self.sct.grab(monitor_region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img_np = np.array(img)

            # 检查备注是否包含颜色配置
            remark = monitor.get('remark', '')
            color_match = re.match(r'#([0-9A-Fa-f]{6})\s*,\s*(\d+)', remark.strip())
            if color_match:
                hex_color = '#' + color_match.group(1)
                tolerance = int(color_match.group(2))
                if self._color_match(img_np, hex_color, tolerance):
                    return 'color_match', hex_color
                else:
                    return None
            else:
                # 数字模式
                sens = monitor.get('sensitivity', 5)
                processed = self._preprocess_image(img_np, sens)
                text_thr = 0.2 + (10 - sens) * 0.04

                result = self.reader.readtext(processed, allowlist='0123456789.-',
                                              paragraph=False, width_ths=0.5, height_ths=0.5,
                                              text_threshold=text_thr, low_text=0.2)
                all_numbers = []
                for bbox, text, confidence in result:
                    if confidence > 0.2:
                        numbers = re.findall(r'-?\d+\.?\d*', text)
                        for num_str in numbers:
                            try:
                                val = float(num_str)
                                all_numbers.append((val, confidence, len(num_str)))
                            except:
                                pass
                if len(all_numbers) == 0:
                    result2 = self.reader.readtext(img_np, allowlist='0123456789.-', paragraph=False,
                                                   text_threshold=text_thr)
                    for bbox, text, confidence in result2:
                        if confidence > 0.2:
                            numbers = re.findall(r'-?\d+\.?\d*', text)
                            for num_str in numbers:
                                try:
                                    val = float(num_str)
                                    all_numbers.append((val, confidence, len(num_str)))
                                except:
                                    pass
                if len(all_numbers) == 0:
                    return None
                all_numbers.sort(key=lambda x: (1 if '.' in str(x[0]) else 0, x[2]), reverse=True)
                best = all_numbers[0][0]
                return best
        except Exception:
            return None

    def run(self):
        if self.reader is None:
            if not self._init_ocr():
                self.status_updated.emit(-1, 'OCR加载失败，请检查网络后重启')
                return
        else:
            self.ocr_ready = True
            self.ocr_status.emit("就绪 ✅ (共用)", True)

        for m in self.monitors:
            self.alarm_status[m['row']] = {'alarm': False, 'count': 0, 'last_alarm_time': 0}
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
                result = self._capture_and_ocr(monitor)
                if result is not None:
                    if isinstance(result, tuple) and result[0] == 'color_match':
                        color = result[1]
                        self.alarm_status[row]['alarm'] = True
                        self.alarm_triggered.emit(row, f"颜色匹配 {color}", 0, 0, 0)
                        self.value_updated.emit(row, 0)
                        self.status_updated.emit(row, '报警')
                    else:
                        value = float(result)
                        self.value_updated.emit(row, value)
                        lower, upper = monitor['lower'], monitor['upper']
                        if value < lower or value > upper:
                            now = time.time()
                            last_time = self.alarm_status[row]['last_alarm_time']
                            if not self.alarm_status[row]['alarm']:
                                self.alarm_status[row]['alarm'] = True
                                self.alarm_status[row]['last_alarm_time'] = now
                                self.alarm_triggered.emit(row, monitor['name'], value, lower, upper)
                            elif self.alarm_loop_enabled:
                                if now - last_time > 10:
                                    self.alarm_status[row]['last_alarm_time'] = now
                                    self.alarm_triggered.emit(row, monitor['name'], value, lower, upper)
                        else:
                            if not self.manual_clear:
                                self.alarm_status[row]['alarm'] = False
                                self.status_updated.emit(row, 'normal')
                            else:
                                self.alarm_status[row]['alarm'] = False
                    self.alarm_status[row]['count'] = 0
                else:
                    self.alarm_status[row]['count'] += 1
                    if self.alarm_status[row]['count'] >= 3:
                        self.status_updated.emit(row, 'error')
                time.sleep(0.05)
            time.sleep(max(0.05, interval_sec - 0.3))
        if self.sct:
            self.sct.close()
