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
    QAbstractItemView, QHeaderView, QCheckBox, QDoubleSpinBox, QGroupBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QIcon
)

import mss
import numpy as np
import cv2

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# ==================== 1. 后台监控线程 ====================
class MonitorThread(QThread):
    value_updated = Signal(int, float, str)  # row, val, time_str
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)

    def __init__(self, monitors, interval=1.0, parent=None):
        super().__init__(parent)
        self.monitors = monitors
        self.interval = max(0.1, interval)
        self.running = True
        self.reader = None
        self.last_values = {}
        self.alarm_states = {}

    def set_reader(self, reader):
        self.reader = reader

    def update_interval(self, new_interval):
        self.interval = max(0.1, new_interval)

    def stop(self):
        self.running = False

    def run(self):
        with mss.mss() as sct:
            while self.running:
                if not self.reader:
                    self.msleep(200)
                    continue

                start_time = time.time()

                for m in self.monitors:
                    if not self.running:
                        break
                    row = m['row']
                    if not m.get('enabled', True):
                        self.status_updated.emit(row, 'disabled')
                        continue

                    x, y, w, h = m['x'], m['y'], m['w'], m['h']
                    if w <= 0 or h <= 0:
                        continue

                    try:
                        bbox = {"top": y, "left": x, "width": w, "height": h}
                        sct_img = sct.grab(bbox)
                        img_np = np.array(sct_img)

                        # 图像预处理与识别
                        h_img, w_img = img_np.shape[:2]
                        scaled = cv2.resize(img_np, (w_img * 3, h_img * 3), interpolation=cv2.INTER_LINEAR)
                        gray = cv2.cvtColor(scaled, cv2.COLOR_RGBA2GRAY) if scaled.shape[2] == 4 else cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)

                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)
                        if np.mean(enhanced) < 80:
                            enhanced = 255 - enhanced
                            enhanced = clahe.apply(enhanced)

                        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
                        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

                        is_success, buffer = cv2.imencode(".png", binary)
                        if not is_success:
                            continue

                        text = self.reader.classification(buffer.tobytes())
                        nums = re.findall(r'-?\d+\.?\d*', text)

                        if nums:
                            val = float(nums[0])
                            now_str = datetime.now().strftime("%H:%M:%S")
                            last_val = self.last_values.get(row)

                            if last_val != val:
                                self.last_values[row] = val
                                self.value_updated.emit(row, val, now_str)

                            # 报警逻辑
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

                elapsed = time.time() - start_time
                sleep_needed = max(0.01, self.interval - elapsed)
                self.msleep(int(sleep_needed * 1000))


# ==================== 2. 独立悬浮选框（支持极小尺寸，顶部显示名称） ====================
class OverlayRegionWidget(QWidget):
    rect_changed = Signal(int, int, int, int, int)      # row, x, y, w, h
    clear_alarm_requested = Signal(int)                 # row

    def __init__(self, row, x, y, w, h, name="区域", parent=None):
        super().__init__(None)
        self.row = row
        self.capture_x = x
        self.capture_y = y
        self.capture_w = max(20, w)   # 放开限制，最小支持 20px
        self.capture_h = max(15, h)   # 放开限制，最小支持 15px
        self.top_bar_height = 24

        self.is_alarm = False
        self.is_editing = False

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._update_geometry()

        self._drag_pos = QPoint()
        self._resize_edge = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部控制栏
        self.top_bar = QWidget()
        self.top_bar.setFixedHeight(self.top_bar_height)
        self.top_bar.setStyleSheet("background-color: rgba(20, 20, 30, 0.9); border-top-left-radius: 4px; border-top-right-radius: 4px;")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(4, 1, 4, 1)
        top_layout.setSpacing(4)

        # 左侧显示区域名称
        self.lbl_title = QLabel(name)
        self.lbl_title.setStyleSheet("color: #00ff8c; font-size: 11px; font-weight: bold;")
        top_layout.addWidget(self.lbl_title)

        top_layout.addStretch()

        # 右侧操作按钮
        self.btn_clear_alarm = QPushButton("🚨 消除")
        self.btn_clear_alarm.setStyleSheet("""
            QPushButton { background-color: #ff4d4d; color: white; border: none; border-radius: 3px; padding: 1px 4px; font-size: 10px; font-weight: bold; }
            QPushButton:hover { background-color: #ff6666; }
        """)
        self.btn_clear_alarm.setVisible(False)
        self.btn_clear_alarm.clicked.connect(self._on_clear_alarm)

        self.btn_gear = QPushButton("⚙️")
        self.btn_gear.setFixedSize(22, 18)
        self.btn_gear.setStyleSheet("""
            QPushButton { background-color: rgba(255,255,255,0.2); color: white; border: none; border-radius: 3px; font-size: 10px; }
            QPushButton:hover { background-color: rgba(255,255,255,0.4); }
        """)
        self.btn_gear.clicked.connect(self.toggle_edit_mode)

        top_layout.addWidget(self.btn_clear_alarm)
        top_layout.addWidget(self.btn_gear)

        main_layout.addWidget(self.top_bar)
        main_layout.addStretch()

        self.setMouseTracking(True)

    def set_title(self, name):
        self.lbl_title.setText(name)

    def _update_geometry(self):
        self.setGeometry(self.capture_x, self.capture_y - self.top_bar_height, self.capture_w, self.capture_h + self.top_bar_height)

    def set_alarm_state(self, is_alarm):
        self.is_alarm = is_alarm
        self.btn_clear_alarm.setVisible(is_alarm)
        self.update()

    def _on_clear_alarm(self):
        self.set_alarm_state(False)
        self.clear_alarm_requested.emit(self.row)

    def toggle_edit_mode(self):
        self.is_editing = not self.is_editing
        if self.is_editing:
            self.btn_gear.setText("✅")
            self.btn_gear.setFixedWidth(22)
        else:
            self.btn_gear.setText("⚙️")
            self.btn_gear.setFixedWidth(22)
            self.rect_changed.emit(self.row, self.capture_x, self.capture_y, self.capture_w, self.capture_h)
        self.update()

    def _get_edge(self, pos):
        m = 5  # 减小边缘触发边界，便于小框微调
        w, h = self.width(), self.height()
        edge = ""
        if pos.y() > h - m: edge += "B"
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

        if edge in ["BL", "BR"]: self.setCursor(Qt.SizeBDiagCursor if edge == "BL" else Qt.SizeFDiagCursor)
        elif edge in ["L", "R"]: self.setCursor(Qt.SizeHorCursor)
        elif edge == "B": self.setCursor(Qt.SizeVerCursor)
        else: self.setCursor(Qt.SizeAllCursor)

        if event.buttons() & Qt.LeftButton:
            g_pos = event.globalPosition().toPoint()
            if self._resize_edge:
                if "R" in self._resize_edge: self.capture_w = max(20, g_pos.x() - self.capture_x)
                if "B" in self._resize_edge: self.capture_h = max(15, g_pos.y() - (self.capture_y - self.top_bar_height) - self.top_bar_height)
                if "L" in self._resize_edge:
                    diff = self.capture_x - g_pos.x()
                    if self.capture_w + diff >= 20:
                        self.capture_x = g_pos.x()
                        self.capture_w += diff
            else:
                new_top_left = g_pos - self._drag_pos
                self.capture_x = new_top_left.x()
                self.capture_y = new_top_left.y() + self.top_bar_height

            self._update_geometry()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        box_rect = QRect(0, self.top_bar_height, self.width(), self.height() - self.top_bar_height)

        if self.is_editing:
            pen = QPen(QColor(255, 200, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 200, 0, 20))
        elif self.is_alarm:
            pen = QPen(QColor(255, 40, 40), 3, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 0, 0, 45))
        else:
            pen = QPen(QColor(0, 255, 140), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QColor(0, 255, 140, 15))

        painter.drawRect(box_rect.adjusted(1, 1, -1, -1))


# ==================== 3. 报警声音播放器 ====================
class AlarmSoundPlayer:
    def __init__(self):
        self.is_playing = False
        self.sound_file = None
        self.play_thread = None
        self.stop_flag = False
        self.lock = threading.Lock()
        self._load_sound()
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
                self.mixer_ready = True
            except: self.mixer_ready = False
        else: self.mixer_ready = False

    def _load_sound(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(script_dir, "警报声.mp3")
        if os.path.exists(sound_path):
            self.sound_file = sound_path

    def play(self):
        if self.is_playing: return
        with self.lock:
            self.stop_flag = False
            self.is_playing = True
        if PYGAME_AVAILABLE and self.mixer_ready and self.sound_file:
            self._play_with_pygame()
        else:
            self._play_beep()

    def _play_with_pygame(self):
        def play_loop():
            try:
                sound = pygame.mixer.Sound(self.sound_file)
                while not self.stop_flag:
                    sound.play()
                    while pygame.mixer.get_busy() and not self.stop_flag:
                        pygame.time.wait(50)
                    time.sleep(0.05)
            except: pass
            finally:
                with self.lock: self.is_playing = False
        self.play_thread = threading.Thread(target=play_loop, daemon=True)
        self.play_thread.start()

    def _play_beep(self):
        def beep_loop():
            try:
                import winsound
                while not self.stop_flag:
                    winsound.Beep(800, 200)
                    time.sleep(0.1)
            except: pass
            finally:
                with self.lock: self.is_playing = False
        self.play_thread = threading.Thread(target=beep_loop, daemon=True)
        self.play_thread.start()

    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.is_playing = False
        if PYGAME_AVAILABLE and self.mixer_ready:
            try: pygame.mixer.stop()
            except: pass


# ==================== 4. 屏幕选区拾取器 ====================
class CoordinatePicker(QWidget):
    coord_selected = Signal(int, int, int, int)
    def __init__(self, parent=None):
        super().__init__(parent)
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

        self.state = 0
        self.start_pos = QPoint()
        self.end_pos = QPoint()

        self.label = QLabel("🖱 点击左上角确定起点", self)
        self.label.setStyleSheet("QLabel { color: white; background: rgba(0,0,0,220); padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: bold; }")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - 80)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        if self.state >= 1 and not self.start_pos.isNull() and not self.end_pos.isNull():
            x = min(self.start_pos.x(), self.end_pos.x())
            y = min(self.start_pos.y(), self.end_pos.y())
            w = abs(self.end_pos.x() - self.start_pos.x())
            h = abs(self.end_pos.y() - self.start_pos.y())
            painter.setPen(QPen(QColor(0, 255, 140), 2, Qt.DashLine))
            painter.drawRect(QRect(x, y, w, h))

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
                if w > 5 and h > 5:
                    self.coord_selected.emit(x, y, w, h)
                    self.close()

    def mouseMoveEvent(self, event):
        self.end_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()


# ==================== 5. 带时间的趋势图表 ====================
class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.data = []

    def add_data_point(self, time_str, val):
        self.data.append((time_str, val))
        if len(self.data) > 15:
            self.data.pop(0)
        self.update()

    def clear_data(self):
        self.data.clear()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        painter.setBrush(QColor("#1e1e2d"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)

        if len(self.data) < 2:
            painter.setPen(QColor("#666688"))
            painter.drawText(rect, Qt.AlignCenter, "等待数值变动数据...")
            return

        chart_rect = QRect(40, 20, rect.width() - 60, rect.height() - 50)
        vals = [d[1] for d in self.data]
        min_v, max_v = min(vals), max(vals)
        if min_v == max_v:
            min_v -= 1.0; max_v += 1.0
        rng = max_v - min_v

        step_x = chart_rect.width() / (len(self.data) - 1)
        points = []
        for i, (t_str, val) in enumerate(self.data):
            x = chart_rect.left() + i * step_x
            y = chart_rect.bottom() - (val - min_v) / rng * chart_rect.height()
            points.append((x, y, t_str, val))

        pen = QPen(QColor("#00ff8c"), 2)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(QPoint(points[i][0], points[i][1]), QPoint(points[i+1][0], points[i+1][1]))

        painter.setFont(QFont("Microsoft YaHei", 8))
        for i, (x, y, t_str, val) in enumerate(points):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(QPoint(x, y), 3, 3)

            if i == 0 or i == len(points) - 1 or i % 4 == 0:
                painter.setPen(QColor("#8888aa"))
                painter.drawText(x - 20, chart_rect.bottom() + 18, 40, 15, Qt.AlignCenter, t_str)


# ==================== 6. 主窗口逻辑 ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数值监控报警")
        self.resize(1000, 680)

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"

        self.alarm_player = AlarmSoundPlayer()
        self.alarm_playing = False

        self.test_reader = None
        self.reader_loading = False

        self.row_coords = {}
        self.row_alarm = {}
        self.overlay_widgets = {}

        self._setup_ui()
        self.load_config()
        QTimer.singleShot(200, self._init_ocr_reader)

    def _init_ocr_reader(self):
        if self.reader_loading or self.test_reader is not None: return
        self.reader_loading = True
        self.ocr_status_label.setText("OCR引擎: 正在加载模型...")

        class LoaderThread(QThread):
            finished = Signal(object)
            def run(self):
                try:
                    import ddddocr
                    reader = ddddocr.DdddOcr(show_ad=False)
                    self.finished.emit(reader)
                except Exception:
                    self.finished.emit(None)

        self.loader_thread = LoaderThread()
        self.loader_thread.finished.connect(self._on_reader_loaded)
        self.loader_thread.start()

    def _on_reader_loaded(self, reader):
        self.reader_loading = False
        if reader is not None:
            self.test_reader = reader
            self.ocr_status_label.setText("OCR引擎: 就绪 ✅")
        else:
            self.ocr_status_label.setText("OCR引擎: 加载失败")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 头部
        header_layout = QHBoxLayout()
        title = QLabel("📊 屏幕数值监控报警")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        header_layout.addWidget(title)

        header_layout.addStretch()

        lbl_interval = QLabel("⏱ 识别间隔(秒):")
        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 10.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.setValue(1.0)
        self.spin_interval.valueChanged.connect(self._on_interval_changed)
        header_layout.addWidget(lbl_interval)
        header_layout.addWidget(self.spin_interval)

        main_layout.addLayout(header_layout)

        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 4px 10px; background-color: #2a2a42; border-radius: 4px; color: #e6b84d;")
        main_layout.addWidget(self.ocr_status_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "备注", "当前值", "下限", "上限", "状态", "报警时间", "静音"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_table_item_changed)
        main_layout.addWidget(self.table, 3)

        # 趋势图
        self.chart_group = QGroupBox("📈 实时数值变动趋势")
        chart_layout = QVBoxLayout(self.chart_group)
        self.trend_chart = TrendChartWidget()
        chart_layout.addWidget(self.trend_chart)
        main_layout.addWidget(self.chart_group, 2)

        # 底部按钮组
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加监控区域")
        self.btn_add.clicked.connect(self.add_monitor_row)
        btn_layout.addWidget(self.btn_add)

        self.btn_delete = QPushButton("🗑 删除区域")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout.addWidget(self.btn_delete)

        self.btn_start_stop = QPushButton("▶ 开始监控")
        self.btn_start_stop.setStyleSheet("background-color: #2e9a58; color: white;")
        self.btn_start_stop.clicked.connect(self.toggle_monitor)
        btn_layout.addWidget(self.btn_start_stop)

        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)

        main_layout.addLayout(btn_layout)

    def _on_interval_changed(self, val):
        if self.monitoring and self.monitor_thread:
            self.monitor_thread.update_interval(val)

    def _on_table_item_changed(self, item):
        # 表格中的“名称”列修改时，同步更新选框顶部的显示名称
        if item.column() == 1:
            row = item.row()
            if row in self.overlay_widgets:
                self.overlay_widgets[row].set_title(item.text())

    def _sync_overlays(self):
        existing_rows = set()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None: continue
            existing_rows.add(row)

            x, y, w, h = self.row_coords.get(row, (100, 100, 120, 60))
            name = self.table.item(row, 1).text()

            if row in self.overlay_widgets:
                self.overlay_widgets[row].set_title(name)
            else:
                ov = OverlayRegionWidget(row, x, y, w, h, name, self)
                ov.rect_changed.connect(self._on_overlay_rect_changed)
                ov.clear_alarm_requested.connect(self._on_overlay_clear_alarm)
                self.overlay_widgets[row] = ov
                ov.show()

        for r in list(self.overlay_widgets.keys()):
            if r not in existing_rows:
                self.overlay_widgets[r].close()
                del self.overlay_widgets[r]

    def _on_overlay_rect_changed(self, row, x, y, w, h):
        self.row_coords[row] = (x, y, w, h)
        if self.monitoring and self.monitor_thread:
            for m in self.monitor_thread.monitors:
                if m['row'] == row:
                    m['x'], m['y'], m['w'], m['h'] = x, y, w, h
                    break

    def _on_overlay_clear_alarm(self, row):
        self.row_alarm[row] = False
        item = self.table.item(row, 6)
        if item:
            item.setText("正常")
            item.setBackground(QBrush(QColor(74, 158, 255)))
        self._check_alarms()

    def add_monitor_row(self):
        self.picker = CoordinatePicker(self)
        self.picker.coord_selected.connect(self._on_picker_completed)
        self.picker.showFullScreen()

    def _on_picker_completed(self, x, y, w, h):
        if w == 0 or h == 0: return
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.row_coords[row] = (x, y, w, h)

        enable_check = QCheckBox()
        enable_check.setChecked(True)
        self.table.setCellWidget(row, 0, enable_check)

        mute_check = QCheckBox()
        self.table.setCellWidget(row, 8, mute_check)

        self.table.setItem(row, 1, QTableWidgetItem(f"区域{row+1}"))
        self.table.setItem(row, 2, QTableWidgetItem(""))
        self.table.setItem(row, 3, QTableWidgetItem("--"))
        self.table.setItem(row, 4, QTableWidgetItem("0"))
        self.table.setItem(row, 5, QTableWidgetItem("100"))
        self.table.setItem(row, 6, QTableWidgetItem("待监控"))
        self.table.setItem(row, 7, QTableWidgetItem("--"))

        self._sync_overlays()

    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            if row in self.row_coords: del self.row_coords[row]
            self._sync_overlays()

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if self.monitoring or self.table.rowCount() == 0: return
        monitors = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None: continue
            chk = self.table.cellWidget(row, 0)
            enabled = chk.isChecked() if chk else True
            x, y, w, h = self.row_coords.get(row, (0, 0, 0, 0))

            monitors.append({
                'row': row,
                'name': self.table.item(row, 1).text(),
                'x': x, 'y': y, 'w': w, 'h': h,
                'lower': float(self.table.item(row, 4).text()),
                'upper': float(self.table.item(row, 5).text()),
                'enabled': enabled
            })

        interval = self.spin_interval.value()
        self.monitor_thread = MonitorThread(monitors, interval=interval)
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

    def on_value_updated(self, row, value, time_str):
        item = self.table.item(row, 3)
        if item:
            item.setText(f"{value:.2f}")

        # 记录到数值变动趋势图
        self.trend_chart.add_data_point(time_str, value)

    def on_alarm_triggered(self, row, name, value, lower, upper):
        self.row_alarm[row] = True
        item = QTableWidgetItem("报警")
        item.setBackground(QBrush(QColor(200, 50, 50)))
        self.table.setItem(row, 6, item)
        self.table.setItem(row, 7, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))

        if row in self.overlay_widgets:
            self.overlay_widgets[row].set_alarm_state(True)

        self._check_alarms()

    def on_status_updated(self, row, status):
        if status == 'normal':
            item = QTableWidgetItem("正常")
            item.setBackground(QBrush(QColor(74, 158, 255)))
            self.table.setItem(row, 6, item)
            if row in self.overlay_widgets:
                self.overlay_widgets[row].set_alarm_state(False)
            self.row_alarm[row] = False
            self._check_alarms()

    def _check_alarms(self):
        should_sound = False
        for r, is_alm in self.row_alarm.items():
            if is_alm:
                chk = self.table.cellWidget(r, 8)
                is_muted = chk.isChecked() if chk else False
                if not is_muted:
                    should_sound = True
                    break

        if should_sound and not self.alarm_playing:
            self.alarm_player.play()
            self.alarm_playing = True
        elif not should_sound and self.alarm_playing:
            self.stop_alarm()

    def stop_alarm(self):
        self.alarm_player.stop()
        self.alarm_playing = False

    def save_config(self):
        config = {
            'interval': self.spin_interval.value(),
            'monitors': []
        }
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None: continue
            x, y, w, h = self.row_coords.get(row, (0, 0, 0, 0))
            config['monitors'].append({
                'name': self.table.item(row, 1).text(),
                'remark': self.table.item(row, 2).text(),
                'lower': float(self.table.item(row, 4).text()),
                'upper': float(self.table.item(row, 5).text()),
                'x': x, 'y': y, 'w': w, 'h': h
            })
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.spin_interval.setValue(config.get('interval', 1.0))
            self.table.setRowCount(0)
            for item in config.get('monitors', []):
                row = self.table.rowCount()
                self.table.insertRow(row)

                self.row_coords[row] = (item.get('x', 0), item.get('y', 0), item.get('w', 100), item.get('h', 50))

                chk = QCheckBox()
                chk.setChecked(True)
                self.table.setCellWidget(row, 0, chk)

                mute_chk = QCheckBox()
                self.table.setCellWidget(row, 8, mute_chk)

                self.table.setItem(row, 1, QTableWidgetItem(item['name']))
                self.table.setItem(row, 2, QTableWidgetItem(item.get('remark', '')))
                self.table.setItem(row, 3, QTableWidgetItem("--"))
                self.table.setItem(row, 4, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 5, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 6, QTableWidgetItem("待监控"))
                self.table.setItem(row, 7, QTableWidgetItem("--"))
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
