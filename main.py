import time
import re
import os
import sys
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QProgressBar)
from PySide6.QtGui import QColor, QFont

try:
    import cv2
    import numpy as np
    import mss
    from PIL import Image
    import easyocr
    OCR_AVAILABLE = True
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"依赖库未完全安装: {e}")


# =====================================================================
# 后台监控线程（完全保留您原有的业务逻辑，未做任何内部逻辑优化）
# =====================================================================
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
        if not OCR_AVAILABLE:
            self.ocr_status.emit("EasyOCR或相关依赖未安装，请检查 requirements.txt", False)
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
            height, width = img_np.shape[:2]
            scaled = cv2.resize(img_np, (width * 3, height * 3), interpolation=cv2.INTER_LINEAR)
            if len(scaled.shape) == 3:
                gray = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
            else:
                gray = scaled
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            if np.mean(enhanced) < 80:
                enhanced = 255 - enhanced
                enhanced = clahe.apply(enhanced)
            kernel_sharpen = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
            sharpened = cv2.filter2D(enhanced, -1, kernel_sharpen)
            binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            kernel = np.ones((2,2), np.uint8)
            cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
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
                height_ths=0.5,
                text_threshold=0.4,
                low_text=0.2
            )
            all_numbers = []
            for bbox, text, confidence in result:
                if confidence > 0.25:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    for num_str in numbers:
                        try:
                            val = float(num_str)
                            all_numbers.append((val, confidence, len(num_str)))
                        except:
                            pass
            if len(all_numbers) == 0:
                result2 = self.reader.readtext(
                    img_np,
                    allowlist='0123456789.-',
                    paragraph=False
                )
                for bbox, text, confidence in result2:
                    if confidence > 0.25:
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
                    value = float(raw_value)
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


# =====================================================================
# 重新设计的现代化精简小窗口 (GUI 控制台)
# =====================================================================
class MiniMonitorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("数值监控")
        self.setFixedSize(480, 280)  # 精简尺寸，适合挂载在屏幕边缘
        self.setWindowFlags(Qt.WindowStaysOnTopHint) # 默认置顶，方便悬浮观看
        
        # 扁平化无边框现代质感样式表
        self.setStyleSheet("""
            QWidget { background-color: #1e1e24; color: #f5f5f5; font-family: 'Segoe UI', 'Microsoft YaHei'; }
            QPushButton { border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold; font-size: 12px; }
            QPushButton#btnStart { background-color: #2ed573; color: white; }
            QPushButton#btnStart:hover { background-color: #26af5f; }
            QPushButton#btnStop { background-color: #ff4757; color: white; }
            QPushButton#btnStop:hover { background-color: #d63c4b; }
            QPushButton#btnClear { background-color: #ffa502; color: white; }
            QPushButton#btnClear:hover { background-color: #e09202; }
            QTableWidget { background-color: #26262b; border: 1px solid #3a3a42; border-radius: 6px; gridline-color: #32323a; }
            QHeaderView::section { background-color: #32323a; color: #a4b0be; font-size: 11px; font-weight: bold; border: none; padding: 4px; }
            QProgressBar { border: 1px solid #3a3a42; border-radius: 3px; background-color: #26262b; text-align: center; color: white; font-size: 10px; }
            QProgressBar::chunk { background-color: #1e90ff; }
        """)

        # 预设的监控配置示例 (您可以自行修改坐标 x, y, width, height 以及判定区间)
        self.monitors_config = [
            {'row': 0, 'name': '监控区 1', 'x': 200, 'y': 200, 'width': 100, 'height': 30, 'lower': 10.0, 'upper': 90.0},
            {'row': 1, 'name': '监控区 2', 'x': 200, 'y': 250, 'width': 100, 'height': 30, 'lower': 20.0, 'upper': 80.0},
        ]
        
        self.thread = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 顶部：OCR状态条与进度条
        top_layout = QHBoxLayout()
        self.lbl_ocr_status = QLabel("系统就绪，等待启动...")
        self.lbl_ocr_status.setStyleSheet("color: #a4b0be; font-size: 12px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setVisible(False)
        top_layout.addWidget(self.lbl_ocr_status, 3)
        top_layout.addWidget(self.progress_bar, 2)
        layout.addLayout(top_layout)

        # 中部：核心监测网格视图
        self.table = QTableWidget(len(self.monitors_config), 4)
        self.table.setHorizontalHeaderLabels(["监控名称", "当前数值", "判定范围", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)

        for m in self.monitors_config:
            row = m['row']
            self.table.setItem(row, 0, QTableWidgetItem(m['name']))
            self.table.setItem(row, 1, QTableWidgetItem("- -"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{m['lower']}~{m['upper']}"))
            
            status_item = QTableWidgetItem("待机")
            status_item.setForeground(QColor("#a4b0be"))
            self.table.setItem(row, 3, status_item)
            
        layout.addWidget(self.table)

        # 底部：简洁排列的控制按钮
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始监控")
        self.btn_start.setObjectName("btnStart")
        self.btn_stop = QPushButton("关闭")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton("复位警报")
        self.btn_clear.setObjectName("btnClear")

        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_stop.clicked.connect(self.stop_monitoring)
        self.btn_clear.clicked.connect(self.clear_all_alarms)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

    def start_monitoring(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.thread = MonitorThread(self.monitors_config)
        
        # 信号槽对接
        self.thread.value_updated.connect(self.on_value_updated)
        self.thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.thread.status_updated.connect(self.on_status_updated)
        self.thread.ocr_status.connect(self.on_ocr_status)
        self.thread.download_progress.connect(self.on_download_progress)
        
        self.thread.start()

    def stop_monitoring(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_ocr_status.setText("监控已关闭")
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 3)
            if item:
                item.setText("已停止")
                item.setBackground(QColor(0, 0, 0, 0))
                item.setForeground(QColor("#a4b0be"))

    def clear_all_alarms(self):
        if self.thread:
            self.thread.reset_all_alarms()

    # --- 槽函数实现 ---
    def on_value_updated(self, row, value):
        val_item = self.table.item(row, 1)
        if val_item:
            val_item.setText(f"{value:.2f}")

    def on_alarm_triggered(self, row, name, value, lower, upper):
        status_item = self.table.item(row, 3)
        if status_item:
            status_item.setText("🚨 越界警报")
            status_item.setBackground(QColor("#ff4757"))
            status_item.setForeground(QColor("white"))

    def on_status_updated(self, row, status):
        if row == -1:
            self.lbl_ocr_status.setText(status)
            return
            
        status_item = self.table.item(row, 3)
        if not status_item:
            return
            
        if status == 'normal':
            status_item.setText("正常")
            status_item.setBackground(QColor("#2ed573"))
            status_item.setForeground(QColor("white"))
        elif status == 'error':
            status_item.setText("识别失败")
            status_item.setBackground(QColor("#ffa502"))
            status_item.setForeground(QColor("white"))
        elif status == 'disabled':
            status_item.setText("已禁用")
            status_item.setBackground(QColor("#747d8c"))
            status_item.setForeground(QColor("white"))
        elif status == '监控中':
            status_item.setText("检测中...")
            status_item.setBackground(QColor(0, 0, 0, 0))
            status_item.setForeground(QColor("#2ed573"))

    def on_ocr_status(self, msg, is_ready):
        self.lbl_ocr_status.setText(msg)
        if is_ready:
            self.progress_bar.setVisible(False)

    def on_download_progress(self, progress):
        if progress < 100:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(progress)
        else:
            self.progress_bar.setVisible(False)

    def closeEvent(self, event):
        self.stop_monitoring()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MiniMonitorWindow()
    window.show()
    sys.exit(app.exec())
