import sys
import os
import re
import time
import numpy as np
import cv2
import mss
import pygame

from PySide6.QtCore import Qt, QThread, Signal, QRect, QPoint
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton,
    QTextEdit, QGroupBox, QMessageBox
)
from PySide6.QtGui import QIcon, QPainter, QPen, QColor
from paddleocr import PaddleOCR


def get_resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境与 PyInstaller 打包环境"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class SnippingWidget(QWidget):
    """屏幕区域框选遮罩组件"""
    area_selected = Signal(int, int, int, int)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        
        self.begin = QPoint()
        self.end = QPoint()
        self.is_drawing = False

    def show_full_screen(self):
        # 覆盖所有显示器
        screen_geometry = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geometry)
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        # 半透明黑色遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        if self.is_drawing:
            pen = QPen(QColor(0, 255, 0), 2, Qt.SolidLine)
            painter.setPen(pen)
            # 选区高亮透亮
            rect = QRect(self.begin, self.end).normalized()
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.begin = event.pos()
            self.end = event.pos()
            self.is_drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.is_drawing = False
            rect = QRect(self.begin, self.end).normalized()
            self.hide()
            if rect.width() > 5 and rect.height() > 5:
                # 发送选中坐标：x, y, width, height
                self.area_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()


class MonitorThread(QThread):
    """后台监控与 OCR 识别线程"""
    log_signal = Signal(str)

    def __init__(self, region, threshold, condition, interval, parent=None):
        super().__init__(parent)
        self.region = region  # {"top": y, "left": x, "width": w, "height": h}
        self.threshold = threshold
        self.condition = condition
        self.interval = interval
        self.running = True

    def run(self):
        self.log_signal.emit("⏳ 正在初始化 PaddleOCR 引擎，请稍候...")
        
        # 拼接本地离线模型路径
        det_path = get_resource_path('models/ch_PP-OCRv4_det_infer')
        rec_path = get_resource_path('models/ch_PP-OCRv4_rec_infer')
        cls_path = get_resource_path('models/ch_ppocr_mobile_v2.0_cls_infer')

        kwargs = {'use_angle_cls': False, 'lang': 'ch', 'show_log': False}
        
        # 检查离线模型是否存在，若存在则使用本地模型
        if os.path.exists(det_path) and os.path.exists(rec_path):
            kwargs['det_model_dir'] = det_path
            kwargs['rec_model_dir'] = rec_path
            if os.path.exists(cls_path):
                kwargs['cls_model_dir'] = cls_path
            self.log_signal.emit("✅ 成功加载本地离线 OCR 模型！")
        else:
            self.log_signal.emit("⚠️ 未检测到完整离线模型文件夹，将使用在线默认模式...")

        try:
            ocr = PaddleOCR(**kwargs)
        except Exception as e:
            self.log_signal.emit(f"❌ OCR 引擎初始化失败: {str(e)}")
            return

        # 初始化音频播放组件
        try:
            pygame.mixer.init()
        except Exception:
            pass

        self.log_signal.emit("🚀 监控已启动！")

        with mss.mss() as sct:
            while self.running:
                try:
                    # 截图区域
                    sct_img = sct.grab(self.region)
                    img_np = np.array(sct_img)
                    img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGRA2RGB)

                    # 执行识别
                    result = ocr.ocr(img_rgb, cls=False)
                    text_list = []
                    if result and result[0]:
                        for line in result[0]:
                            text_list.append(line[1][0])

                    full_text = " ".join(text_list)
                    
                    # 使用正则抽取文本中的第一个浮点数或整数
                    numbers = re.findall(r"[-+]?\d*\.\d+|\d+", full_text)

                    timestamp = time.strftime("%H:%M:%S", time.localtime())

                    if numbers:
                        val = float(numbers[0])
                        is_alarm = False
                        
                        if self.condition == ">" and val > self.threshold:
                            is_alarm = True
                        elif self.condition == "<" and val < self.threshold:
                            is_alarm = True
                        elif self.condition == "==" and val == self.threshold:
                            is_alarm = True

                        msg = f"[{timestamp}] 识别数值: {val} | 条件: (当前值 {self.condition} {self.threshold})"
                        
                        if is_alarm:
                            msg += " 🚨【触发报警】"
                            self.play_alarm()
                            
                        self.log_signal.emit(msg)
                    else:
                        self.log_signal.emit(f"[{timestamp}] 未识别到数字 (识别原始文本: '{full_text}')")

                except Exception as e:
                    self.log_signal.emit(f"[{time.strftime('%H:%M:%S')}] 监控异常: {str(e)}")

                # 按照设定间隔休眠
                for _ in range(int(self.interval * 10)):
                    if not self.running:
                        break
                    time.sleep(0.1)

    def play_alarm(self):
        """播放报警音，默认触发系统蜂鸣或 mp3 文件"""
        sound_path = get_resource_path("alarm.mp3")
        if os.path.exists(sound_path):
            try:
                pygame.mixer.music.load(sound_path)
                pygame.mixer.music.play()
                return
            except Exception:
                pass
        
        # 蜂鸣器备用方案 (Windows)
        try:
            import winsound
            winsound.Beep(1000, 500)
        except Exception:
            pass

    def stop(self):
        self.running = False
        self.wait()


class MainWindow(QMainWindow):
    """主程序窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数值监控报警")
        self.resize(500, 600)
        
        # 加载图标
        icon_path = get_resource_path("favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.snipper = SnippingWidget()
        self.snipper.area_selected.connect(self.update_region)
        
        self.monitor_thread = None
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. 区域设置组
        region_group = QGroupBox("1. 屏幕监控区域选择")
        region_layout = QVBoxLayout()
        
        btn_snip = QPushButton("🎯 点击拖拽选择屏幕区域")
        btn_snip.clicked.connect(self.start_snip)
        region_layout.addWidget(btn_snip)

        coords_layout = QHBoxLayout()
        self.spin_x = QSpinBox(); self.spin_x.setRange(0, 9999)
        self.spin_y = QSpinBox(); self.spin_y.setRange(0, 9999)
        self.spin_w = QSpinBox(); self.spin_w.setRange(10, 9999); self.spin_w.setValue(200)
        self.spin_h = QSpinBox(); self.spin_h.setRange(10, 9999); self.spin_h.setValue(100)

        coords_layout.addWidget(QLabel("X:"))
        coords_layout.addWidget(self.spin_x)
        coords_layout.addWidget(QLabel("Y:"))
        coords_layout.addWidget(self.spin_y)
        coords_layout.addWidget(QLabel("宽:"))
        coords_layout.addWidget(self.spin_w)
        coords_layout.addWidget(QLabel("高:"))
        coords_layout.addWidget(self.spin_h)
        
        region_layout.addLayout(coords_layout)
        region_group.setLayout(region_layout)
        main_layout.addWidget(region_group)

        # 2. 规则与阈值设置组
        rule_group = QGroupBox("2. 报警规则设置")
        rule_layout = QHBoxLayout()

        rule_layout.addWidget(QLabel("当数值"))
        self.combo_cond = QComboBox()
        self.combo_cond.addItems([">", "<", "=="])
        rule_layout.addWidget(self.combo_cond)

        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(-999999, 999999)
        self.spin_threshold.setValue(100.0)
        rule_layout.addWidget(self.spin_threshold)

        rule_layout.addWidget(QLabel("检测间隔(秒):"))
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.2, 60.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        rule_layout.addWidget(self.spin_interval)

        rule_group.setLayout(rule_layout)
        main_layout.addWidget(rule_group)

        # 3. 控制按钮
        self.btn_start = QPushButton("▶ 启动监控")
        self.btn_start.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white; padding: 10px;")
        self.btn_start.clicked.connect(self.toggle_monitor)
        main_layout.addWidget(self.btn_start)

        # 4. 日志显示区
        log_group = QGroupBox("3. 运行日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

    def start_snip(self):
        self.snipper.show_full_screen()

    def update_region(self, x, y, w, h):
        self.spin_x.setValue(x)
        self.spin_y.setValue(y)
        self.spin_w.setValue(w)
        self.spin_h.setValue(h)
        self.append_log(f"📍 区域更新为: X={x}, Y={y}, 宽={w}, 高={h}")

    def toggle_monitor(self):
        if self.monitor_thread is None or not self.monitor_thread.isRunning():
            region = {
                "top": self.spin_y.value(),
                "left": self.spin_x.value(),
                "width": self.spin_w.value(),
                "height": self.spin_h.value()
            }
            threshold = self.spin_threshold.value()
            condition = self.combo_cond.currentText()
            interval = self.spin_interval.value()

            self.monitor_thread = MonitorThread(region, threshold, condition, interval)
            self.monitor_thread.log_signal.connect(self.append_log)
            self.monitor_thread.start()

            self.btn_start.setText("⏹ 停止监控")
            self.btn_start.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #f44336; color: white; padding: 10px;")
        else:
            self.monitor_thread.stop()
            self.monitor_thread = None
            self.btn_start.setText("▶ 启动监控")
            self.btn_start.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white; padding: 10px;")
            self.append_log("⏹ 监控已停止。")

    def append_log(self, text):
        self.log_text.append(text)

    def closeEvent(self, event):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
