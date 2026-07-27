import sys
import json
import os
import time
import re
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QLineEdit,
    QGroupBox, QSlider, QProgressBar, QCheckBox, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient, QIcon
)

import mss
import numpy as np
import cv2

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# ==================== 1. 后台监控线程（画面变动实时检测） ====================
class MonitorThread(QThread):
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)
    download_progress = Signal(int)

    def __init__(self, monitors, parent=None):
        super().__init__(parent)
        self.monitors = monitors
        self.running = True
        self.reader = None
        self.last_frames = {}
        self.last_values = {}
        self.alarm_states = {}

    def set_reader(self, reader):
        self.reader = reader

    def stop(self):
        self.running = False

    def run(self):
        with mss.mss() as sct:
            while self.running:
                if not self.reader:
                    self.msleep(100)
                    continue

                for m in self.monitors:
                    if not self.running:
                        break
                    row = m['row']
                    if not m.get('enabled', True):
                        self.status_updated.emit(row, 'disabled')
                        continue

                    x, y, w, h = m['x'], m['y'], m['width'], m['height']
                    if w <= 0 or h <= 0:
                        continue

                    try:
                        bbox = {"top": y, "left": x, "width": w, "height": h}
                        sct_img = sct.grab(bbox)
                        img_np = np.array(sct_img)

                        # 画面微小变动检测（避免未变动时频繁进行OCR消耗CPU）
                        last_img = self.last_frames.get(row)
                        frame_changed = True
                        if last_img is not None and last_img.shape == img_np.shape:
                            diff = cv2.absdiff(last_img, img_np)
                            if np.mean(diff) < 0.8:  # 画面几乎没有变化
                                frame_changed = False

                        self.last_frames[row] = img_np

                        if not frame_changed and row in self.last_values:
                            self.msleep(20)
                            continue

                        # 图像预处理与识别
                        sens = m.get('sensitivity', 5)
                        clip_limit = 1.0 + (sens / 10.0) * 2.0
                        block_size = max(3, int(5 + (10 - sens) * 1.5))
                        if block_size % 2 == 0:
                            block_size += 1
                        c_value = max(1, int(2 + (10 - sens) * 0.5))

                        h_img, w_img = img_np.shape[:2]
                        scaled = cv2.resize(img_np, (w_img * 3, h_img * 3), interpolation=cv2.INTER_LINEAR)
                        gray = cv2.cvtColor(scaled, cv2.COLOR_RGBA2GRAY) if scaled.shape[2] == 4 else cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)

                        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)
                        if np.mean(enhanced) < 80:
                            enhanced = 255 - enhanced
                            enhanced = clahe.apply(enhanced)

                        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
                        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c_value)

                        is_success, buffer = cv2.imencode(".png", binary)
                        if not is_success:
                            continue

                        text = self.reader.classification(buffer.tobytes())
                        nums = re.findall(r'-?\d+\.?\d*', text)

                        if nums:
                            val = float(nums[0])
                            last_val = self.last_values.get(row)
                            self.last_values[row] = val

                            # 数值发生变化时立即更新
                            if last_val != val:
                                self.value_updated.emit(row, val)

                            # 报警逻辑检测
                            lower, upper = m['lower'], m['upper']
                            is_alarm = (val < lower or val > upper)
                            prev_alarm = self.alarm_states.get(row, False)

                            if is_alarm:
                                self.alarm_triggered.emit(row, m['name'], val, lower, upper)
                                self.alarm_states[row] = True
                            else:
                                if prev_alarm or last_val != val:
                                    self.status_updated.emit(row, 'normal')
                                self.alarm_states[row] = False
                        else:
                            self.status_updated.emit(row, 'error')

                    except Exception:
                        pass

                self.msleep(40)  # 保持高灵敏度响应


# ==================== 2. 屏幕常驻识别选框组件 ====================
class OverlayRegionWidget(QWidget):
    rect_changed = Signal(int, int, int, int, int)      # row, x, y, w, h
    clear_alarm_requested = Signal(int)                 # row

    def __init__(self, row, name, lower, upper, x, y, w, h, parent=None):
        super().__init__(None)
        self.row = row
        self.region_name = name
        self.lower = lower
        self.upper = upper
        self.is_alarm = False
        self.is_editing = False
        self.current_value_str = "--"

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(x, y, w, h)

        self._drag_pos = QPoint()
        self._resize_edge = None

        # 布局构建
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.top_bar = QWidget(self)
        self.top_bar.setStyleSheet("background-color: rgba(20, 20, 30, 0.85); border-radius: 4px;")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(6, 2, 6, 2)
        top_layout.setSpacing(6)

        self.lbl_info = QLabel(f"{name} [{lower}~{upper}]")
        self.lbl_info.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: bold; font-family: 'Microsoft YaHei';")

        self.btn_clear_alarm = QPushButton("🚨 消除报警")
        self.btn_clear_alarm.setStyleSheet("""
            QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 2px 6px; font-size: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #ff6666; }
        """)
        self.btn_clear_alarm.setVisible(False)
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        self.btn_gear = QPushButton("⚙️")
        self.btn_gear.setFixedSize(24, 20)
        self.btn_gear.setStyleSheet("""
            QPushButton { background-color: rgba(255,255,255,0.2); color: white; border: none; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: rgba(255,255,255,0.4); }
        """)
        self.btn_gear.clicked.connect(self.toggle_edit_mode)

        top_layout.addWidget(self.lbl_info)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_clear_alarm)
        top_layout.addWidget(self.btn_gear)

        layout.addWidget(self.top_bar)
        layout.addStretch()

        self.lbl_val = QLabel("--")
        self.lbl_val.setAlignment(Qt.AlignCenter)
        self.lbl_val.setStyleSheet("color: #00ff8c; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(self.lbl_val)
        layout.addStretch()

        self.setMouseTracking(True)

    def update_info(self, name, lower, upper):
        self.region_name = name
        self.lower = lower
        self.upper = upper
        self.lbl_info.setText(f"{name} [{lower}~{upper}]")

    def set_value(self, val_str):
        self.current_value_str = val_str
        self.lbl_val.setText(val_str)

    def set_alarm_state(self, is_alarm):
        self.is_alarm = is_alarm
        self.btn_clear_alarm.setVisible(is_alarm)
        if is_alarm:
            self.lbl_val.setStyleSheet("color: #ff4d4d; font-size: 18px; font-weight: bold; background: transparent;")
        else:
            self.lbl_val.setStyleSheet("color: #00ff8c; font-size: 16px; font-weight: bold; background: transparent;")
        self.update()

    def _on_clear_alarm(self):
        self.set_alarm_state(False)
        self.clear_alarm_requested.emit(self.row)

    def toggle_edit_mode(self):
        self.is_editing = not self.is_editing
        if self.is_editing:
            self.btn_gear.setText("✅ 完成")
            self.btn_gear.setFixedWidth(52)
        else:
            self.btn_gear.setText("⚙️")
            self.btn_gear.setFixedWidth(24)
            rect = self.geometry()
            self.rect_changed.emit(self.row, rect.x(), rect.y(), rect.width(), rect.height())
        self.update()

    def _get_edge(self, pos):
        m = 8
        w, h = self.width(), self.height()
        edge = ""
        if pos.y() < m: edge += "T"
        elif pos.y() > h - m: edge += "B"
        if pos.x() < m: edge += "L"
        elif pos.x() > w - m: edge += "R"
        return edge if edge else None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_editing:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._resize_edge = self._get_edge(event.position().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.is_editing:
            return
        pos = event.position().toPoint()
        edge = self._get_edge(pos)

        if edge in ["TL", "BR"]: self.setCursor(Qt.SizeFDiagCursor)
        elif edge in ["TR", "BL"]: self.setCursor(Qt.SizeBDiagCursor)
        elif edge in ["L", "R"]: self.setCursor(Qt.SizeHorCursor)
        elif edge in ["T", "B"]: self.setCursor(Qt.SizeVerCursor)
        else: self.setCursor(Qt.SizeAllCursor)

        if event.buttons() & Qt.LeftButton:
            g_pos = event.globalPosition().toPoint()
            rect = self.geometry()
            if self._resize_edge:
                x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
                if "R" in self._resize_edge: w = max(90, g_pos.x() - x)
                if "B" in self._resize_edge: h = max(60, g_pos.y() - y)
                if "L" in self._resize_edge:
                    diff = x - g_pos.x()
                    if w + diff >= 90: x = g_pos.x(); w += diff
                if "T" in self._resize_edge:
                    diff = y - g_pos.y()
                    if h + diff >= 60: y = g_pos.y(); h += diff
                self.setGeometry(x, y, w, h)
            else:
                self.move(g_pos - self._drag_pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        if self.is_editing:
            pen = QPen(QColor(255, 200, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 200, 0, 25))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        elif self.is_alarm:
            pen = QPen(QColor(255, 40, 40), 3, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 0, 0, 50))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 15))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))


# ==================== 3. 音频播放与辅助组件 ====================
class AlarmSoundPlayer:
    def __init__(self):
        self.is_playing = False
        self.sound_file = None
        self.play_thread = None
        self.stop_flag = False
        self.volume = 1.0
        self.current_sound = None
        self.lock = threading.Lock()
        self.loop_enabled = True
        self._load_sound()
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
                self.mixer_ready = True
            except:
                self.mixer_ready = False
        else:
            self.mixer_ready = False

    def _load_sound(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(script_dir, "警报声.mp3")
        if os.path.exists(sound_path):
            self.sound_file = sound_path
            return
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            sound_path = os.path.join(exe_dir, "警报声.mp3")
            if os.path.exists(sound_path):
                self.sound_file = sound_path

    def play(self):
        if not self.sound_file or not os.path.exists(self.sound_file):
            self._play_beep()
            return
        if self.is_playing:
            return
        with self.lock:
            self.stop_flag = False
            self.is_playing = True
        if PYGAME_AVAILABLE and self.mixer_ready:
            self._play_with_pygame()
        else:
            self._play_beep()

    def _play_with_pygame(self):
        def play_loop():
            try:
                sound = pygame.mixer.Sound(self.sound_file)
                self.current_sound = sound
                sound.set_volume(self.volume)
                while not self.stop_flag:
                    sound.play()
                    while pygame.mixer.get_busy() and not self.stop_flag:
                        pygame.time.wait(50)
                    if self.stop_flag:
                        break
                    time.sleep(0.05)
            except Exception as e:
                print(f"播放失败: {e}")
            finally:
                with self.lock:
                    self.is_playing = False
                    self.current_sound = None
        self.play_thread = threading.Thread(target=play_loop, daemon=True)
        self.play_thread.start()

    def _play_beep(self):
        def beep_loop():
            try:
                import winsound
                while not self.stop_flag:
                    winsound.Beep(800, 200)
                    time.sleep(0.1)
                    if self.stop_flag: break
                    winsound.Beep(1000, 200)
                    time.sleep(0.1)
            except:
                pass
            finally:
                with self.lock:
                    self.is_playing = False
        self.play_thread = threading.Thread(target=beep_loop, daemon=True)
        self.play_thread.start()

    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.is_playing = False
            self.current_sound = None
        if PYGAME_AVAILABLE and self.mixer_ready:
            try:
                pygame.mixer.stop()
            except:
                pass


class CoordinatePicker(QWidget):
    coord_selected = Signal(int, int, int, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择监控区域")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setMouseTracking(True)
        screens = QApplication.screens()
        total_rect = screens[0].geometry()
        for s in screens[1:]:
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)
        self.screen_pixmap = QPixmap(total_rect.size())
        painter = QPainter(self.screen_pixmap)
        for screen in screens:
            painter.drawPixmap(screen.geometry().topLeft(), screen.grabWindow(0))
        painter.end()
        self.showFullScreen()

        self.state = 0
        self.start_pos = QPoint()
        self.end_pos = QPoint()

        self.label = QLabel("🖱 点击左上角确定起点", self)
        self.label.setStyleSheet("QLabel { color: white; background: rgba(0,0,0,220); padding: 12px 24px; border-radius: 10px; font-size: 16px; font-weight: bold; }")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - 100)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.state >= 1 and not self.start_pos.isNull() and not self.end_pos.isNull():
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            w = abs(self.end_pos.x() - self.start_pos.x())
            h = abs(self.end_pos.y() - self.start_pos.y())
            rect = QRect(x, y, w, h)
            painter.setPen(QPen(QColor(0, 255, 140), 2, Qt.DashLine))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.state == 0:
                self.start_pos = event.position().toPoint()
                self.end_pos = self.start_pos
                self.state = 1
                self.label.setText("🖱 点击右下角确定终点")
                self.label.adjustSize()
            elif self.state == 1:
                self.end_pos = event.position().toPoint()
                x = min(self.start_pos.x(), self.end_pos.x())
                y = min(self.start_pos.y(), self.end_pos.y())
                w = abs(self.end_pos.x() - self.start_pos.x())
                h = abs(self.end_pos.y() - self.start_pos.y())
                if w > 20 and h > 20:
                    self.coord_selected.emit(x, y, w, h)
                    self.close()

    def mouseMoveEvent(self, event):
        self.end_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()


class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.data = []
        self.title = "数值趋势"

    def set_data(self, data_list, title="数值趋势"):
        self.data = data_list[-15:]
        self.title = title
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.setBrush(QColor("#252538"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("#e8e8f0"))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(20, 22, self.title)

        if len(self.data) < 2:
            painter.setPen(QColor("#7a7a9a"))
            painter.drawText(rect, Qt.AlignCenter, "暂无趋势数据")
            return

        chart_rect = QRect(20, 32, rect.width() - 40, rect.height() - 55)
        min_v, max_v = min(self.data), max(self.data)
        if min_v == max_v: min_v -= 1; max_v += 1
        rng = max_v - min_v

        points = []
        step_x = chart_rect.width() / (len(self.data) - 1)
        for i, val in enumerate(self.data):
            x = chart_rect.left() + i * step_x
            y = chart_rect.bottom() - (val - min_v) / rng * chart_rect.height()
            points.append(QPoint(x, y))

        pen = QPen(QColor("#4a9eff"), 2)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])


# ==================== 4. 主窗口逻辑 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(1100, 700)

        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"

        self.alarm_player = AlarmSoundPlayer()
        self.alarm_playing = False

        self.test_reader = None
        self.reader_loading = False

        self.row_enabled = {}
        self.row_alarm = {}
        self.row_muted = {}
        self.row_sensitivity = {}
        self.value_history = {}
        self.overlay_widgets = {}  # 保持常驻悬浮框引用

        self._setup_ui()
        self.load_config()
        QTimer.singleShot(200, self._init_ocr_reader)

    def _init_ocr_reader(self):
        if self.reader_loading or self.test_reader is not None:
            return
        self.reader_loading = True
        self.ocr_status_label.setText("OCR引擎: 正在加载模型...")

        class LoaderThread(QThread):
            finished = Signal(object)
            def run(self):
                try:
                    import ddddocr
                    reader = ddddocr.DdddOcr(show_ad=False)
                    self.finished.emit(reader)
                except Exception as e:
                    self.finished.emit(None)

        self.loader_thread = LoaderThread()
        self.loader_thread.finished.connect(self._on_reader_loaded)
        self.loader_thread.start()

    def _on_reader_loaded(self, reader):
        self.reader_loading = False
        if reader is not None:
            self.test_reader = reader
            self.set_ocr_status("就绪 ✅ (ddddocr)", True)
        else:
            self.set_ocr_status("加载失败", False)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        title = QLabel("📊 屏幕数字监控报警系统")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        main_layout.addWidget(title)

        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 6px 14px; background-color: #2a2a42; border-radius: 6px; color: #e6b84d;")
        main_layout.addWidget(self.ocr_status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "备注", "当前值", "下限", "上限", "坐标", "状态", "报警时间", "静音", "灵敏度"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        main_layout.addWidget(self.table, 3)

        self.chart_group = QGroupBox("📈 数值趋势曲线")
        chart_layout = QVBoxLayout(self.chart_group)
        self.trend_chart = TrendChartWidget()
        chart_layout.addWidget(self.trend_chart)
        main_layout.addWidget(self.chart_group, 2)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加监控点")
        self.btn_add.clicked.connect(self.add_monitor_row)
        btn_layout.addWidget(self.btn_add)

        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout.addWidget(self.btn_delete)

        self.btn_start_stop = QPushButton("▶ 开始监控")
        self.btn_start_stop.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")
        self.btn_start_stop.clicked.connect(self.toggle_monitor)
        btn_layout.addWidget(self.btn_start_stop)

        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)

        main_layout.addLayout(btn_layout)

        self.status_label = QLabel("状态: 就绪")
        main_layout.addWidget(self.status_label)

    # 同步并管理所有的常驻悬浮识别框
    def _sync_overlays(self):
        existing_rows = set()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None:
                continue
            existing_rows.add(row)
            name = self.table.item(row, 1).text()
            lower = float(self.table.item(row, 4).text())
            upper = float(self.table.item(row, 5).text())
            coords = self.table.item(row, 6).text()
            nums = re.findall(r'\d+', coords)
            if len(nums) < 4:
                continue
            x, y, w, h = map(int, nums[:4])

            if row in self.overlay_widgets:
                ov = self.overlay_widgets[row]
                ov.update_info(name, lower, upper)
            else:
                ov = OverlayRegionWidget(row, name, lower, upper, x, y, w, h, self)
                ov.rect_changed.connect(self._on_overlay_rect_changed)
                ov.clear_alarm_requested.connect(self._on_overlay_clear_alarm)
                self.overlay_widgets[row] = ov
                ov.show()

        # 清除已被删除行的悬浮框
        for r in list(self.overlay_widgets.keys()):
            if r not in existing_rows:
                self.overlay_widgets[r].close()
                del self.overlay_widgets[r]

    def _on_overlay_rect_changed(self, row, x, y, w, h):
        self.table.setItem(row, 6, QTableWidgetItem(f"{x},{y},{w},{h}"))
        if self.monitoring and self.monitor_thread:
            for m in self.monitor_thread.monitors:
                if m['row'] == row:
                    m['x'], m['y'], m['width'], m['height'] = x, y, w, h
                    break

    def _on_overlay_clear_alarm(self, row):
        self.row_alarm[row] = False
        item = self.table.item(row, 7)
        if item:
            item.setText("正常")
            item.setBackground(QBrush(QColor(74, 158, 255)))
        self._check_alarms()

    def add_monitor_row(self):
        self.picker = CoordinatePicker(self)
        self.picker.coord_selected.connect(self._on_picker_completed)
        self.picker.showFullScreen()

    def _on_picker_completed(self, x, y, width, height):
        if width == 0 or height == 0:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.value_history[row] = []

        enable_check = QCheckBox()
        enable_check.setChecked(True)
        self.table.setCellWidget(row, 0, enable_check)
        self.row_enabled[row] = True

        self.table.setItem(row, 1, QTableWidgetItem(f"区域{row+1}"))
        self.table.setItem(row, 3, QTableWidgetItem("--"))
        self.table.setItem(row, 4, QTableWidgetItem("0"))
        self.table.setItem(row, 5, QTableWidgetItem("100"))
        self.table.setItem(row, 6, QTableWidgetItem(f"{x},{y},{width},{height}"))
        self.table.setItem(row, 7, QTableWidgetItem("待监控"))
        self.table.setItem(row, 8, QTableWidgetItem("--"))

        self._sync_overlays()

    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._sync_overlays()

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if self.monitoring or self.table.rowCount() == 0:
            return
        monitors = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None: continue
            coords = self.table.item(row, 6).text()
            nums = re.findall(r'\d+', coords)
            if len(nums) < 4: continue
            monitors.append({
                'name': self.table.item(row, 1).text(),
                'x': int(nums[0]), 'y': int(nums[1]),
                'width': int(nums[2]), 'height': int(nums[3]),
                'lower': float(self.table.item(row, 4).text()),
                'upper': float(self.table.item(row, 5).text()),
                'row': row,
                'enabled': True
            })

        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        if self.test_reader:
            self.monitor_thread.set_reader(self.test_reader)
        self.monitor_thread.start()

        self.monitoring = True
        self.btn_start_stop.setText("⏹ 停止监控")
        self.btn_start_stop.setStyleSheet("background-color: #b03a3a; color: white;")

    def stop_monitor(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        self.monitoring = False
        self.btn_start_stop.setText("▶ 开始监控")
        self.btn_start_stop.setStyleSheet("background-color: #2e9a58; color: white;")
        self.stop_alarm()

    def on_value_updated(self, row, value):
        item = self.table.item(row, 3)
        if item:
            item.setText(f"{value:.2f}")
        if row in self.overlay_widgets:
            self.overlay_widgets[row].set_value(f"{value:.2f}")

    def on_alarm_triggered(self, row, name, value, lower, upper):
        self.row_alarm[row] = True
        item = QTableWidgetItem("报警")
        item.setBackground(QBrush(QColor(200, 50, 50)))
        self.table.setItem(row, 7, item)
        self.table.setItem(row, 8, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))

        if row in self.overlay_widgets:
            self.overlay_widgets[row].set_alarm_state(True)

        self._check_alarms()

    def on_status_updated(self, row, status):
        if status == 'normal':
            item = QTableWidgetItem("正常")
            item.setBackground(QBrush(QColor(74, 158, 255)))
            self.table.setItem(row, 7, item)
            if row in self.overlay_widgets:
                self.overlay_widgets[row].set_alarm_state(False)
            self.row_alarm[row] = False
            self._check_alarms()

    def _check_alarms(self):
        has_alarm = any(self.row_alarm.values())
        if has_alarm and not self.alarm_playing:
            self.alarm_player.play()
            self.alarm_playing = True
        elif not has_alarm and self.alarm_playing:
            self.stop_alarm()

    def stop_alarm(self):
        self.alarm_player.stop()
        self.alarm_playing = False

    def set_ocr_status(self, text, is_ready):
        self.ocr_status_label.setText(f"OCR引擎: {text}")

    def save_config(self):
        config = {'monitors': []}
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None: continue
            config['monitors'].append({
                'name': self.table.item(row, 1).text(),
                'lower': float(self.table.item(row, 4).text()),
                'upper': float(self.table.item(row, 5).text()),
                'coords': self.table.item(row, 6).text()
            })
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.table.setRowCount(0)
            for item in config.get('monitors', []):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 1, QTableWidgetItem(item['name']))
                self.table.setItem(row, 3, QTableWidgetItem("--"))
                self.table.setItem(row, 4, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 5, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 6, QTableWidgetItem(item['coords']))
                self.table.setItem(row, 7, QTableWidgetItem("待监控"))
            self._sync_overlays()
        except Exception:
            pass

    def closeEvent(self, event):
        self.stop_monitor()
        for ov in self.overlay_widgets.values():
            ov.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
