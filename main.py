import sys
import os
import re
import time
import cv2
import numpy as np
from PIL import ImageGrab
import ddddocr

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit, QGroupBox, QSpinBox,
    QDoubleSpinBox, QMessageBox, QFrame, QSplitter
)
from PyQt5.QtGui import QPixmap, QImage, QColor, QPainter, QPen, QBrush, QFont

# ==================== 1. 屏幕框选遮罩层 ====================
class ROISelector(QWidget):
    region_selected = pyqtSignal(tuple) # 发送 (x, y, w, h)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowOpacity(0.3)
        self.setCursor(Qt.CrossCursor)
        
        self.begin = QPoint()
        self.end = QPoint()
        self.is_selecting = False

    def paintEvent(self, event):
        if self.is_selecting:
            painter = QPainter(self)
            painter.setPen(QPen(Qt.red, 2, Qt.SolidLine))
            painter.setBrush(QBrush(QColor(255, 0, 0, 50)))
            rect = QRect(self.begin, self.end).normalized()
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.begin = event.pos()
            self.end = event.pos()
            self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            rect = QRect(self.begin, self.end).normalized()
            self.hide()
            if rect.width() > 5 and rect.height() > 5:
                # 获取屏幕缩放比例转换后的物理像素坐标
                screen = QApplication.primaryScreen()
                scale = screen.devicePixelRatio()
                x = int(rect.x() * scale)
                y = int(rect.y() * scale)
                w = int(rect.width() * scale)
                h = int(rect.height() * scale)
                self.region_selected.emit((x, y, w, h))

# ==================== 2. 后台实时监控线程 ====================
class MonitorThread(QThread):
    result_signal = pyqtSignal(object, str, np.ndarray) # 数值, 原始识别文本, 截图图像

    def __init__(self, region, interval, panel_ref):
        super().__init__()
        self.region = region  # (x, y, w, h)
        self.interval = interval
        self.is_running = True
        self.panel = panel_ref

    def run(self):
        x, y, w, h = self.region
        bbox = (x, y, x + w, y + h)

        while self.is_running:
            try:
                # 高速抓屏
                img_pil = ImageGrab.grab(bbox=bbox)
                img_np = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

                # 调用主窗口的识别算法
                val, raw_text = self.panel._recognize_number(img_np)
                self.result_signal.emit(val, raw_text, img_np)

            except Exception as e:
                self.result_signal.emit(None, f"截图失败:{e}", None)

            time.sleep(self.interval)

    def stop(self):
        self.is_running = False
        self.wait()

# ==================== 3. 主控制面板 ====================
class GlobalControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字 OCR 监控仪表盘 v2.0")
        self.resize(750, 500)

        # 区域与OCR初始化
        self.region = (100, 100, 200, 80)
        self.reader = None
        self.monitor_thread = None
        self.selector = None

        self._init_ocr()
        self._init_ui()

    def _init_ocr(self):
        try:
            # 初始化 ddddocr (隐藏广告)
            self.reader = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"OCR引擎加载失败: {e}")

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # 左侧控制面板
        left_box = QGroupBox("控制参数")
        left_layout = QVBoxLayout(left_box)

        # 区域显示
        self.lbl_region = QLabel(f"当前监控区域: X={self.region[0]}, Y={self.region[1]}, W={self.region[2]}, H={self.region[3]}")
        left_layout.addWidget(self.lbl_region)

        self.btn_select = QPushButton("⚙️ 重新框选屏幕区域")
        self.btn_select.clicked.connect(self._start_selection)
        left_layout.addWidget(self.btn_select)

        # 监控间隔设置
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("刷新间隔 (秒):"))
        self.spn_interval = QDoubleSpinBox()
        self.spn_interval.setRange(0.1, 10.0)
        self.spn_interval.setValue(1.0)
        self.spn_interval.setSingleStep(0.5)
        interval_layout.addWidget(self.spn_interval)
        left_layout.addLayout(interval_layout)

        # 启动/停止按钮
        self.btn_toggle = QPushButton("▶️ 开始监控")
        self.btn_toggle.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_toggle.clicked.connect(self._toggle_monitor)
        left_layout.addWidget(self.btn_toggle)

        # 识别结果大屏展示
        left_layout.addWidget(QLabel("最新识别数值:"))
        self.lbl_result = QLabel("---")
        self.lbl_result.setFont(QFont("Arial", 28, QFont.Bold))
        self.lbl_result.setAlignment(Qt.AlignCenter)
        self.lbl_result.setStyleSheet("color: #2196F3; border: 2px solid #ddd; background: #f9f9f9; padding: 10px;")
        left_layout.addWidget(self.lbl_result)

        left_layout.addStretch()
        layout.addWidget(left_box, 1)

        # 右侧预览与日志
        right_box = QGroupBox("实时预览与调试日志")
        right_layout = QVBoxLayout(right_box)

        right_layout.addWidget(QLabel("裁剪图像预览 (自动放大与增强):"))
        self.lbl_preview = QLabel("无图像")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(120)
        self.lbl_preview.setStyleSheet("border: 1px dashed #ccc; background: #333; color: #fff;")
        right_layout.addWidget(self.lbl_preview)

        right_layout.addWidget(QLabel("系统运行日志:"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        right_layout.addWidget(self.txt_log)

        layout.addWidget(right_box, 1)

    # ---------------- 核心 OCR 增强识别算法 ----------------
    def _recognize_number(self, img_np):
        if not self.reader:
            return None, "OCR引擎未加载"

        try:
            bgr = img_np
            h, w = bgr.shape[:2]
            if h <= 0 or w <= 0: return None, "区域尺寸无效"

            # 1. 图像放大 4 倍
            target_h = 120
            scale = max(4.0, target_h / float(h))
            new_w, new_h = int(w * scale), int(h * scale)
            scaled_bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            # 🛠️ 保存截图到磁盘供用户排查错位问题
            cv2.imwrite("debug_crop.png", scaled_bgr)

            attempts = []

            # 尝试 1：原始放大彩图
            ok1, buf1 = cv2.imencode(".png", scaled_bgr)
            if ok1: attempts.append(buf1.tobytes())

            # 尝试 2：灰度图
            gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
            ok2, buf2 = cv2.imencode(".png", gray)
            if ok2: attempts.append(buf2.tobytes())

            # 尝试 3：图像反色（解决黑底白字/暗背景识别不到问题）
            inverted = cv2.bitwise_not(gray)
            ok3, buf3 = cv2.imencode(".png", inverted)
            if ok3: attempts.append(buf3.tobytes())

            # 尝试 4：自适应对比度增强 (CLAHE)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            gray_clahe = clahe.apply(gray)
            ok4, buf4 = cv2.imencode(".png", gray_clahe)
            if ok4: attempts.append(buf4.tobytes())

            last_raw_str = ""

            for buf in attempts:
                raw_text = str(self.reader.classification(buf))
                if not raw_text: continue
                last_raw_str = raw_text

                # 清理并容错替换常见符号为小数点
                clean_t = self._clean_digit_text(raw_text).replace(' ', '')
                clean_t = re.sub(r'(?<=\d)[\,\:\·\'\`\_\-\*\°\o\O\a\e\~\,\;\–\—\.\s\、]+(?=\d)', '.', clean_t)

                # 正则匹配数字（含负数和小数）
                nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)

                # 优先匹配带小数点的数值
                if nums and '.' in nums[0]:
                    try: return float(nums[0]), raw_text
                    except ValueError: pass

                # 若仅识别出纯整数，直接输出
                if nums:
                    try: return float(nums[0]), raw_text
                    except ValueError: pass

            return None, last_raw_str if last_raw_str else "无文本"

        except Exception as e:
            return None, f"识别异常:{e}"

    def _clean_digit_text(self, text):
        """ 替换 OCR 常见误识别字符 """
        mapping = {
            'O': '0', 'o': '0', 'D': '0',
            'I': '1', 'l': '1', '|': '1', '!': '1',
            'Z': '2', 'z': '2',
            'S': '5', 's': '5',
            'B': '8',
        }
        res = list(text)
        for i, ch in enumerate(res):
            if ch in mapping:
                res[i] = mapping[ch]
        return "".join(res)

    # ---------------- 交互逻辑 ----------------
    def _start_selection(self):
        self.selector = ROISelector()
        self.selector.region_selected.connect(self._on_region_selected)
        self.selector.show()

    def _on_region_selected(self, region):
        self.region = region
        self.lbl_region.setText(f"当前监控区域: X={region[0]}, Y={region[1]}, W={region[2]}, H={region[3]}")
        self._log(f"已更新区域: {region}")

    def _toggle_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            # 停止监控
            self.monitor_thread.stop()
            self.monitor_thread = None
            self.btn_toggle.setText("▶️ 开始监控")
            self.btn_toggle.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white; padding: 10px;")
            self.spn_interval.setEnabled(True)
            self.btn_select.setEnabled(True)
            self._log("监控已停止")
        else:
            # 开启监控
            interval = self.spn_interval.value()
            self.monitor_thread = MonitorThread(self.region, interval, self)
            self.monitor_thread.result_signal.connect(self._update_display)
            self.monitor_thread.start()

            self.btn_toggle.setText("⏹️ 停止监控")
            self.btn_toggle.setStyleSheet("font-weight: bold; background-color: #f44336; color: white; padding: 10px;")
            self.spn_interval.setEnabled(False)
            self.btn_select.setEnabled(False)
            self._log("监控已启动...")

    def _update_display(self, val, raw_text, img_np):
        # 1. 更新数值
        if val is not None:
            self.lbl_result.setText(str(val))
            self._log(f"成功识别: {val} (原始: '{raw_text}')")
        else:
            self.lbl_result.setText("识别失败")
            self._log(f"未匹配到数字, 原始文本: '{raw_text}'")

        # 2. 更新右侧预览图
        if img_np is not None:
            h, w, ch = img_np.shape
            bytes_per_line = ch * w
            q_img = QImage(img_np.data, w, h, bytes_per_line, QImage.Format_BGR888)
            pixmap = QPixmap.fromImage(q_img)
            self.lbl_preview.setPixmap(pixmap.scaled(
                self.lbl_preview.width(), self.lbl_preview.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def _log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{timestamp}] {msg}")


# ==================== 4. 程序入口 (高 DPI 兼容) ====================
if __name__ == "__main__":
    # Windows 高 DPI 屏幕缩放兼容设置
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setStyle("Fusion")

    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec_())
