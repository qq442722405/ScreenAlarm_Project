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
    QAbstractItemView, QHeaderView, QFileDialog, QFrame, QSlider,
    QComboBox, QProgressBar, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient
)
from monitor import MonitorThread

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class AlarmSoundPlayer:
    """报警声音播放器"""
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
    
    def set_loop(self, enabled):
        self.loop_enabled = enabled
    
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
                return
    
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
                
                if self.loop_enabled:
                    while not self.stop_flag:
                        sound.play()
                        while pygame.mixer.get_busy() and not self.stop_flag:
                            pygame.time.wait(50)
                        if self.stop_flag:
                            break
                        time.sleep(0.05)
                else:
                    sound.play()
                    while pygame.mixer.get_busy() and not self.stop_flag:
                        pygame.time.wait(50)
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
                if self.loop_enabled:
                    while not self.stop_flag:
                        winsound.Beep(800, 200)
                        time.sleep(0.1)
                        if self.stop_flag:
                            break
                        winsound.Beep(1000, 200)
                        time.sleep(0.1)
                else:
                    winsound.Beep(800, 200)
                    time.sleep(0.1)
                    winsound.Beep(1000, 200)
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
    
    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, volume))
        if self.current_sound is not None:
            try:
                self.current_sound.set_volume(self.volume)
            except:
                pass
    
    def is_loaded(self):
        return self.sound_file is not None and os.path.exists(self.sound_file)


class CoordinatePicker(QWidget):
    """屏幕区域选择器 - 按住左键拖拽选区域，松开自动完成"""
    coord_selected = Signal(int, int, int, int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择监控区域")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool
        )
        self.setMouseTracking(True)
        
        screens = QApplication.screens()
        total_rect = screens[0].geometry()
        for s in screens[1:]:
            total_rect = total_rect.united(s.geometry())
        self.total_rect = total_rect
        self.setGeometry(total_rect)
        
        # 抓取全屏截图作为背景
        self.screen_pixmap = QPixmap(total_rect.size())
        self.screen_pixmap.fill(Qt.black)
        painter = QPainter(self.screen_pixmap)
        for screen in screens:
            screen_pix = screen.grabWindow(0)
            painter.drawPixmap(screen.geometry().topLeft(), screen_pix)
        painter.end()
        
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        
        self.is_selecting = False
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        
        self.label = QLabel("🖱 按住左键拖拽选择监控区域，松开鼠标自动完成", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0,0,0,220);
                padding: 14px 28px;
                border-radius: 14px;
                font-size: 18px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
            }
        """)
        self.label.adjustSize()
        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - self.label.height() - 80
        )
        
        self.coord_label = QLabel("等待选择...", self)
        self.coord_label.setAlignment(Qt.AlignCenter)
        self.coord_label.setStyleSheet("""
            QLabel {
                color: #5aa9ff;
                background: rgba(0,0,0,220);
                padding: 10px 22px;
                border-radius: 10px;
                font-size: 17px;
                font-weight: bold;
                border: 1px solid #5aa9ff;
            }
        """)
        self.coord_label.adjustSize()
        self.coord_label.move(
            (self.width() - self.coord_label.width()) // 2,
            60
        )
        
        self.setFocus(Qt.OtherFocusReason)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.drawPixmap(self.rect(), self.screen_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        
        if self.is_selecting and not self.end_pos.isNull():
            rect = self._get_current_rect()
            if rect.width() > 5 and rect.height() > 5:
                painter.drawPixmap(rect, self.screen_pixmap.copy(rect))
                
                pen = QPen(QColor(0, 255, 140), 2)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect)
                
                painter.setPen(QPen(QColor(0, 255, 140), 2))
                size = 14
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(size, 0))
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(0, size))
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(-size, 0))
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(0, size))
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(size, 0))
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(0, -size))
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(-size, 0))
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(0, -size))
                
                painter.setPen(Qt.white)
                painter.setFont(QFont("Arial", 12, QFont.Bold))
                text_y = rect.y() - 12 if rect.y() > 30 else rect.y() + rect.height() + 25
                painter.drawText(rect.x() + 10, text_y, f"{rect.width()} × {rect.height()}")
    
    def _get_current_rect(self):
        if self.start_pos.isNull():
            return QRect()
        x = min(self.start_pos.x(), self.end_pos.x())
        y = min(self.start_pos.y(), self.end_pos.y())
        w = abs(self.end_pos.x() - self.start_pos.x())
        h = abs(self.end_pos.y() - self.start_pos.y())
        return QRect(x, y, w, h)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_selecting = True
            self.start_pos = event.position().toPoint()
            self.end_pos = self.start_pos
            self.label.setText("🖱 拖动鼠标调整区域大小")
            self.label.adjustSize()
            self.label.move(
                (self.width() - self.label.width()) // 2,
                self.height() - self.label.height() - 80
            )
            self.update()
    
    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.position().toPoint()
            rect = self._get_current_rect()
            self.coord_label.setText(
                f"起点: ({self.start_pos.x()}, {self.start_pos.y()})  "
                f"大小: {rect.width()} × {rect.height()}"
            )
            self.coord_label.adjustSize()
            self.coord_label.move(
                (self.width() - self.coord_label.width()) // 2,
                60
            )
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_pos = event.position().toPoint()
            rect = self._get_current_rect()
            
            if rect.width() > 20 and rect.height() > 20:
                self.coord_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())
                self.close()
            else:
                self.label.setText("⚠️ 区域太小，请重新拖拽选择")
                self.label.adjustSize()
                self.label.move(
                    (self.width() - self.label.width()) // 2,
                    self.height() - self.label.height() - 80
                )
                self.start_pos = QPoint()
                self.end_pos = QPoint()
                self.update()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(0, 0, 0, 0)
            self.close()
    
    def closeEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        event.accept()


class TrendChartWidget(QWidget):
    """数值趋势曲线控件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.data = []
        self.max_points = 200
        self.title = "数值趋势"
    
    def set_data(self, data_list, title="数值趋势"):
        self.data = data_list[-self.max_points:]
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        padding_left = 55
        padding_right = 20
        padding_top = 32
        padding_bottom = 28
        
        # 背景
        painter.setBrush(QColor("#252538"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)
        
        # 标题
        painter.setPen(QColor("#e8e8f0"))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(padding_left, 22, self.title)
        
        chart_rect = QRect(
            padding_left, padding_top,
            rect.width() - padding_left - padding_right,
            rect.height() - padding_top - padding_bottom
        )
        
        # 网格线
        painter.setPen(QColor("#36364a"))
        grid_rows = 5
        for i in range(grid_rows + 1):
            y = chart_rect.top() + chart_rect.height() * i / grid_rows
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)
        
        grid_cols = 10
        for i in range(grid_cols + 1):
            x = chart_rect.left() + chart_rect.width() * i / grid_cols
            painter.drawLine(x, chart_rect.top(), x, chart_rect.bottom())
        
        if len(self.data) < 2:
            painter.setPen(QColor("#7a7a9a"))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(chart_rect, Qt.AlignCenter, "选中监控行后显示数值趋势")
            return
        
        # 计算Y轴范围
        min_val = min(self.data)
        max_val = max(self.data)
        if min_val == max_val:
            min_val -= 1
            max_val += 1
        val_range = max_val - min_val
        margin = val_range * 0.1
        min_val -= margin
        max_val += margin
        val_range = max_val - min_val
        
        # Y轴刻度
        painter.setPen(QColor("#9a9ab0"))
        painter.setFont(QFont("Arial", 9))
        for i in range(grid_rows + 1):
            y = chart_rect.top() + chart_rect.height() * i / grid_rows
            val = max_val - val_range * i / grid_rows
            painter.drawText(8, y + 3, f"{val:.1f}")
        
        # 计算曲线点
        points = []
        step_x = chart_rect.width() / (len(self.data) - 1)
        
        for i, val in enumerate(self.data):
            x = chart_rect.left() + i * step_x
            y = chart_rect.bottom() - (val - min_val) / val_range * chart_rect.height()
            points.append(QPoint(x, y))
        
        # 渐变填充区域
        if len(points) > 2:
            gradient = QLinearGradient(0, chart_rect.top(), 0, chart_rect.bottom())
            gradient.setColorAt(0, QColor(74, 158, 255, 90))
            gradient.setColorAt(1, QColor(74, 158, 255, 10))
            painter.setBrush(gradient)
            painter.setPen(Qt.NoPen)
            
            path = QPainterPath()
            path.moveTo(points[0].x(), chart_rect.bottom())
            for p in points:
                path.lineTo(p)
            path.lineTo(points[-1].x(), chart_rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        
        # 绘制曲线
        pen = QPen(QColor("#4a9eff"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])
        
        # 最新值标记
        if points:
            last_p = points[-1]
            painter.setPen(QPen(QColor("#ff6b6b"), 3))
            painter.setBrush(QColor("#ff6b6b"))
            painter.drawEllipse(last_p, 4, 4)
            
            painter.setPen(QColor("#ff8080"))
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            text = f"{self.data[-1]:.2f}"
            text_w = painter.fontMetrics().horizontalAdvance(text)
            tx = last_p.x() - text_w - 8
            if tx < chart_rect.left():
                tx = last_p.x() + 8
            painter.drawText(tx, last_p.y() - 6, text)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.resize(1200, 820)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QLabel { color: #e0e0f0; font-family: "Microsoft YaHei"; }
            QTableWidget {
                background-color: #1e1e2e;
                alternate-background-color: #27273d;
                color: #e0e0f0;
                gridline-color: #33334a;
                selection-background-color: #4a9eff;
                selection-color: #ffffff;
                border: 1px solid #33334a;
                border-radius: 8px;
            }
            QTableWidget::item { padding: 6px; }
            QHeaderView::section {
                background-color: #2a2a42;
                color: #e0e0f0;
                padding: 8px;
                border: none;
                border-right: 1px solid #33334a;
                border-bottom: 1px solid #33334a;
                font-weight: bold;
            }
            QPushButton {
                background-color: #363650;
                color: #e0e0f0;
                border: none;
                border-radius: 8px;
                padding: 9px 20px;
                font-weight: bold;
                font-family: "Microsoft YaHei";
                min-height: 22px;
            }
            QPushButton:hover { background-color: #464668; }
            QPushButton#btn_start {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2e9a58, stop:1 #258048);
                color: white;
            }
            QPushButton#btn_start:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38ad64, stop:1 #2d9052); }
            QPushButton#btn_start:disabled {
                background-color: #3a3a50;
                color: #7a7a9a;
            }
            QPushButton#btn_stop {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c04040, stop:1 #a03030);
                color: white;
            }
            QPushButton#btn_stop:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d05050, stop:1 #b03a3a); }
            QPushButton#btn_stop:disabled {
                background-color: #3a3a50;
                color: #7a7a9a;
            }
            QPushButton#btn_delete { background-color: #b03a3a; }
            QPushButton#btn_delete:hover { background-color: #c44a4a; }
            QPushButton#btn_save { background-color: #2a5a9a; }
            QPushButton#btn_save:hover { background-color: #356ab0; }
            QFrame#hint_frame {
                background-color: #2a2a42;
                border-radius: 8px;
                padding: 6px 12px;
                border: 1px solid #3a3a55;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #363650;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #4a9eff;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #4a9eff;
                border-radius: 3px;
            }
            QComboBox {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 20px;
            }
            QComboBox:hover { border-color: #4a9eff; }
            QComboBox::drop-down { border: none; width: 20px; }
            QProgressBar {
                background-color: #27273d;
                border: 1px solid #33334a;
                border-radius: 6px;
                text-align: center;
                color: #e0e0f0;
                height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4a9eff, stop:1 #6ab4ff);
                border-radius: 6px;
            }
            QCheckBox { color: #e0e0f0; font-family: "Microsoft YaHei"; }
            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                background-color: #363650;
                border: 1px solid #505070;
            }
            QCheckBox::indicator:checked {
                background-color: #4a9eff;
                border-color: #4a9eff;
            }
            QGroupBox {
                color: #e0e0f0;
                font-weight: bold;
                font-family: "Microsoft YaHei";
                border: 1px solid #33334a;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #c0c0e0;
            }
        """)
        
        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.loop_enabled = True
        self.detect_interval = 500
        self.value_history = {}
        self.last_value = {}  # 记录上一次数值，用于数值变化驱动
        
        self.alarm_player = AlarmSoundPlayer()
        self.alarm_file = self.alarm_player.sound_file or ""
        self.alarm_playing = False
        
        self.row_enabled = {}
        self.row_alarm = {}
        self.row_muted = {}
        
        self._setup_ui()
        self.load_config()
        
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)
        
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel("📊 屏幕数字监控报警系统")
        title_font = QFont("Microsoft YaHei")
        title_font.setPointSize(19)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        subtitle = QLabel("基于 EasyOCR 视觉识别")
        subtitle.setStyleSheet("color: #7a7a9a; font-size: 13px;")
        title_layout.addWidget(subtitle)
        main_layout.addLayout(title_layout)
        
        # 提示栏
        hint_frame = QFrame()
        hint_frame.setObjectName("hint_frame")
        hint_layout = QHBoxLayout(hint_frame)
        hint_layout.setContentsMargins(10, 5, 10, 5)
        hint_label = QLabel("💡 点击「添加监控点」按住左键拖拽选择区域 | 修改上下限立即生效 | 选中行查看数值趋势")
        hint_label.setStyleSheet("color: #e6b84d;")
        hint_layout.addWidget(hint_label)
        main_layout.addWidget(hint_frame)
        
        # OCR状态
        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 6px 14px; background-color: #2a2a42; border-radius: 6px; color: #e6b84d; border: 1px solid #3a3a55;")
        main_layout.addWidget(self.ocr_status_label)
        
        # 下载进度
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        main_layout.addWidget(self.download_progress)
        
        # 监控表格
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "启用", "名称", "当前值", "下限", "上限", 
            "坐标 (X,Y,W,H)", "状态", "报警时间", "🔇 静音"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setRowCount(0)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 65)
        self.table.setColumnWidth(4, 65)
        self.table.setColumnWidth(5, 130)
        self.table.setColumnWidth(6, 85)
        self.table.setColumnWidth(7, 110)
        self.table.setColumnWidth(8, 60)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table, 3)
        
        # 趋势曲线
        chart_group = QGroupBox("📈 数值趋势曲线")
        chart_layout = QVBoxLayout(chart_group)
        chart_layout.setContentsMargins(12, 18, 12, 12)
        self.trend_chart = TrendChartWidget()
        chart_layout.addWidget(self.trend_chart)
        main_layout.addWidget(chart_group, 2)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_add = QPushButton("➕ 添加监控点")
        self.btn_add.clicked.connect(self.add_monitor_row)
        btn_layout.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("✏️ 编辑区域")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        btn_layout.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout.addWidget(self.btn_delete)
        
        btn_layout.addStretch()
        
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("⏹ 停止监控")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        btn_layout.addStretch()
        
        btn_layout.addWidget(QLabel("音量:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        btn_layout.addWidget(self.volume_slider)
        
        self.volume_label = QLabel("80%")
        self.volume_label.setFixedWidth(40)
        btn_layout.addWidget(self.volume_label)
        
        btn_layout.addWidget(QLabel("间隔:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["100ms", "200ms", "300ms", "500ms", "1000ms", "2000ms"])
        self.interval_combo.setCurrentIndex(3)
        self.interval_combo.setFixedWidth(90)
        self.interval_combo.currentTextChanged.connect(self.on_interval_changed)
        btn_layout.addWidget(self.interval_combo)
        
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_load = QPushButton("📂 加载配置")
        self.btn_load.clicked.connect(self.load_config_dialog)
        btn_layout.addWidget(self.btn_load)
        
        main_layout.addLayout(btn_layout)
        
        # 状态栏
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; border: 1px solid #33334a;")
        status_layout.addWidget(self.status_label, 3)
        
        self.alarm_count_label = QLabel("报警数: 0")
        self.alarm_count_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; border: 1px solid #33334a;")
        status_layout.addWidget(self.alarm_count_label, 1)
        
        self.alarm_status_label = QLabel("🔇 无报警")
        self.alarm_status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; color: #7a7a9a; border: 1px solid #33334a;")
        status_layout.addWidget(self.alarm_status_label, 1)
        
        main_layout.addLayout(status_layout)
        
        self.table.model().rowsInserted.connect(self._on_rows_inserted)
        self.table.model().rowsRemoved.connect(self._on_rows_removed)
    
    def _on_selection_changed(self):
        """选中行变化时更新趋势图"""
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row not in self.value_history or not self.value_history[row]:
            self.trend_chart.set_data([], "数值趋势")
            return
        name_item = self.table.item(row, 1)
        name = name_item.text() if name_item else f"区域{row+1}"
        self.trend_chart.set_data(self.value_history[row], f"{name} 数值趋势")
    
    def _on_table_item_changed(self, item):
        if not self.monitoring or self.monitor_thread is None:
            return
        
        row = item.row()
        col = item.column()
        
        if col == 3 or col == 4:
            try:
                new_value = float(item.text())
                for m in self.monitor_thread.monitors:
                    if m['row'] == row:
                        if col == 3:
                            m['lower'] = new_value
                        elif col == 4:
                            m['upper'] = new_value
                        break
            except ValueError:
                pass
    
    def _on_rows_inserted(self, parent, first, last):
        for row in range(first, last + 1):
            widget = self.table.cellWidget(row, 0)
            if widget and isinstance(widget, QCheckBox):
                self.row_enabled[row] = widget.isChecked()
            mute_widget = self.table.cellWidget(row, 8)
            if mute_widget and isinstance(mute_widget, QCheckBox):
                self.row_muted[row] = mute_widget.isChecked()
                mute_widget.stateChanged.connect(lambda state, r=row: self._on_mute_changed(r, state))
    
    def _on_rows_removed(self, parent, first, last):
        for row in range(first, last + 1):
            if row in self.row_enabled:
                del self.row_enabled[row]
            if row in self.row_alarm:
                del self.row_alarm[row]
            if row in self.row_muted:
                del self.row_muted[row]
            if row in self.value_history:
                del self.value_history[row]
            if row in self.last_value:
                del self.last_value[row]
    
    def _get_row_enabled(self, row):
        return self.row_enabled.get(row, True)
    
    def _is_row_muted(self, row):
        return self.row_muted.get(row, False)
    
    def _on_mute_changed(self, row, state):
        """静音状态变化 - 立即生效"""
        is_muted = (state == 2)
        self.row_muted[row] = is_muted
        
        # 立即更新界面状态
        if is_muted:
            status_item = QTableWidgetItem("静音中")
            status_item.setBackground(QBrush(QColor(140, 105, 50)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.table.setItem(row, 6, status_item)
            
            # 重置线程内报警状态
            if self.monitoring and self.monitor_thread and self.monitor_thread.isRunning():
                self.monitor_thread.reset_row_alarm(row)
            
            self.row_alarm[row] = False
            self._set_name_color(row, False)
        else:
            # 取消静音，恢复监控中状态，等待线程下次检测更新
            if self.monitoring:
                status_item = QTableWidgetItem("监控中")
                status_item.setBackground(QBrush(QColor(0, 0, 0, 0)))
                status_item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(row, 6, status_item)
        
        # 检查是否还有活跃报警，没有则停止声音
        has_active_alarm = False
        for r, alarm in self.row_alarm.items():
            if alarm and not self._is_row_muted(r):
                has_active_alarm = True
                break
        if not has_active_alarm:
            self.stop_alarm()
        
        self._update_alarm_count()
    
    def on_interval_changed(self, text):
        self.detect_interval = int(text.replace("ms", ""))
        if self.monitoring and self.monitor_thread:
            self.monitor_thread.set_interval(self.detect_interval)
    
    def on_volume_changed(self, value):
        volume = value / 100.0
        self.volume_label.setText(f"{value}%")
        self.alarm_player.set_volume(volume)
    
    def play_alarm(self, row):
        if self._is_row_muted(row):
            return
        
        # 仅当未置顶时才设置，避免重复重绘闪烁
        if not (self.windowFlags() & Qt.WindowStaysOnTopHint):
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()
        self.raise_()
        self.activateWindow()
        
        self.alarm_player.play()
        self.alarm_playing = True
        self.alarm_status_label.setText("🔊 报警中...")
        self.alarm_status_label.setStyleSheet("padding: 8px 12px; background-color: #b03a3a; border-radius: 6px; color: white; border: 1px solid #c04a4a;")
    
    def stop_alarm(self):
        self.alarm_player.stop()
        self.alarm_playing = False
        self.alarm_status_label.setText("🔇 无报警")
        self.alarm_status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; color: #7a7a9a; border: 1px solid #33334a;")
        
        # 仅当已置顶时才取消，避免重复重绘闪烁
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.show()
    
    def on_download_progress(self, value):
        self.download_progress.setVisible(True)
        self.download_progress.setValue(value)
        if value >= 100:
            QTimer.singleShot(1000, lambda: self.download_progress.setVisible(False))
    
    def add_monitor_row(self):
        self.picker = CoordinatePicker(self)
        self.picker.coord_selected.connect(self._on_picker_completed)
        self.picker.showFullScreen()
    
    def _on_picker_completed(self, x, y, width, height):
        self.picker = None
        
        if x == 0 and y == 0 and width == 0 and height == 0:
            return
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.value_history[row] = []
        self.last_value[row] = None
        
        enable_check = QCheckBox()
        enable_check.setChecked(True)
        enable_check.setStyleSheet("margin-left: 12px;")
        self.table.setCellWidget(row, 0, enable_check)
        self.row_enabled[row] = True
        enable_check.stateChanged.connect(lambda state, r=row: self._on_enable_changed(r, state))
        
        mute_check = QCheckBox()
        mute_check.setChecked(False)
        mute_check.setStyleSheet("margin-left: 12px;")
        self.table.setCellWidget(row, 8, mute_check)
        self.row_muted[row] = False
        mute_check.stateChanged.connect(lambda state, r=row: self._on_mute_changed(r, state))
        
        self.table.setItem(row, 1, QTableWidgetItem(f"区域{row+1}"))
        self.table.setItem(row, 2, QTableWidgetItem("--"))
        self.table.setItem(row, 3, QTableWidgetItem("0"))
        self.table.setItem(row, 4, QTableWidgetItem("100"))
        self.table.setItem(row, 5, QTableWidgetItem(f"{x},{y},{width},{height}"))
        self.table.setItem(row, 6, QTableWidgetItem("待监控"))
        self.table.setItem(row, 7, QTableWidgetItem("--"))
        
        self.status_label.setText(f"状态: 已添加 区域{row+1}")
    
    def _on_enable_changed(self, row, state):
        self.row_enabled[row] = (state == 2)
    
    def edit_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        
        self.picker = CoordinatePicker(self)
        self.picker.coord_selected.connect(lambda x, y, w, h, r=row: self._on_edit_picker_completed(r, x, y, w, h))
        self.picker.showFullScreen()
    
    def _on_edit_picker_completed(self, row, x, y, width, height):
        self.picker = None
        
        if x == 0 and y == 0 and width == 0 and height == 0:
            return
        
        self.table.setItem(row, 5, QTableWidgetItem(f"{x},{y},{width},{height}"))
        self.status_label.setText("状态: 已更新坐标")
    
    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        
        name = self.table.item(row, 1).text()
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 [{name}] 吗？")
        if reply == QMessageBox.Yes:
            self.table.removeRow(row)
            self.status_label.setText("状态: 已删除")
    
    def set_ocr_status(self, status, is_ready=False):
        color = "#44ddaa" if is_ready else "#e6b84d"
        self.ocr_status_label.setStyleSheet(
            f"padding: 6px 14px; background-color: #2a2a42; border-radius: 6px; color: {color}; border: 1px solid #3a3a55;"
        )
        self.ocr_status_label.setText(f"OCR引擎: {status}")
    
    def start_monitor(self):
        if self.monitoring:
            return
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先添加监控点")
            return
        
        has_enabled = False
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None:
                continue
            if self._get_row_enabled(row):
                has_enabled = True
                break
        
        if not has_enabled:
            QMessageBox.warning(self, "提示", "没有启用的监控点，请勾选「启用」复选框")
            return
        
        monitors = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None:
                continue
            name = self.table.item(row, 1).text()
            lower = float(self.table.item(row, 3).text())
            upper = float(self.table.item(row, 4).text())
            coords = self.table.item(row, 5).text()
            nums = re.findall(r'\d+', coords)
            if len(nums) >= 4:
                x, y, w, h = map(int, nums[:4])
            else:
                continue
            monitors.append({
                'name': name,
                'x': x, 'y': y,
                'width': w, 'height': h,
                'lower': lower, 'upper': upper,
                'row': row,
                'enabled': self._get_row_enabled(row)
            })
        
        if not monitors:
            QMessageBox.warning(self, "提示", "没有有效的监控点数据")
            return
        
        # 暂停表格重绘，避免闪烁
        self.table.setUpdatesEnabled(False)
        
        # 清空历史数据
        for row in self.value_history:
            self.value_history[row].clear()
            self.last_value[row] = None
        self.trend_chart.set_data([], "数值趋势")
        
        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.set_interval(self.detect_interval)
        self.monitor_thread.set_alarm_loop(self.loop_enabled)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.ocr_status.connect(self.set_ocr_status)
        self.monitor_thread.download_progress.connect(self.on_download_progress)
        
        self.monitor_thread.get_row_enabled = self._get_row_enabled
        self.monitor_thread.is_row_muted = self._is_row_muted
        
        self.monitor_thread.start()
        
        self.monitoring = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("状态: 监控运行中")
        
        # 恢复表格重绘
        self.table.setUpdatesEnabled(True)
    
    def stop_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        
        # 暂停表格重绘，避免闪烁
        self.table.setUpdatesEnabled(False)
        
        self.monitoring = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("状态: 已停止")
        self.stop_alarm()
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 6)
            if item and "报警" not in item.text():
                self.table.setItem(row, 6, QTableWidgetItem("已停止"))
            self.row_alarm[row] = False
            self._reset_row_colors(row)
        
        # 恢复表格重绘
        self.table.setUpdatesEnabled(True)
    
    def _reset_row_colors(self, row):
        name_item = self.table.item(row, 1)
        if name_item:
            name_item.setBackground(QBrush(QColor(0, 0, 0, 0)))
            name_item.setForeground(QBrush(QColor(255, 255, 255)))
        
        status_item = self.table.item(row, 6)
        if status_item:
            status_item.setBackground(QBrush(QColor(0, 0, 0, 0)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
            if status_item.text() == "报警":
                status_item.setText("正常")
                status_item.setBackground(QBrush(QColor(50, 150, 70)))
                status_item.setForeground(QBrush(QColor(255, 255, 255)))
    
    def _set_name_color(self, row, alarm):
        item = self.table.item(row, 1)
        if item:
            if alarm:
                item.setBackground(QBrush(QColor(200, 50, 50)))
                item.setForeground(QBrush(QColor(255, 255, 255)))
            else:
                item.setBackground(QBrush(QColor(0, 0, 0, 0)))
                item.setForeground(QBrush(QColor(255, 255, 255)))
    
    def on_value_updated(self, row, value):
        """数值更新 - 仅数值变化时才记录到趋势曲线"""
        self.table.setItem(row, 2, QTableWidgetItem(f"{value:.2f}"))
        
        # 数值变化驱动：仅当数值与上一次差值超过阈值时才记录
        threshold = 0.001
        if row not in self.last_value or self.last_value[row] is None or abs(value - self.last_value[row]) > threshold:
            self.last_value[row] = value
            
            if row not in self.value_history:
                self.value_history[row] = []
            self.value_history[row].append(value)
            if len(self.value_history[row]) > 200:
                self.value_history[row].pop(0)
            
            # 当前选中行则实时更新曲线
            if self.table.currentRow() == row:
                name_item = self.table.item(row, 1)
                name = name_item.text() if name_item else f"区域{row+1}"
                self.trend_chart.set_data(self.value_history[row], f"{name} 数值趋势")
    
    def on_alarm_triggered(self, row, name, value, lower, upper):
        if self._is_row_muted(row):
            return
        
        self.row_alarm[row] = True
        
        status_item = QTableWidgetItem("报警")
        status_item.setBackground(QBrush(QColor(200, 50, 50)))
        status_item.setForeground(QBrush(QColor(255, 255, 255)))
        self.table.setItem(row, 6, status_item)
        
        now = datetime.now().strftime("%H:%M:%S")
        self.table.setItem(row, 7, QTableWidgetItem(now))
        
        self._set_name_color(row, True)
        self._update_alarm_count()
        self.status_label.setText(f"报警: {name} = {value:.2f} [范围: {lower}-{upper}]")
        
        self.play_alarm(row)
    
    def on_status_updated(self, row, status):
        # 静音状态由界面直接控制，线程返回的静音状态不覆盖
        if self._is_row_muted(row):
            return
        
        if status == 'normal':
            status_item = QTableWidgetItem("正常")
            status_item.setBackground(QBrush(QColor(45, 145, 70)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.table.setItem(row, 6, status_item)
            if self.row_alarm.get(row, False):
                self.row_alarm[row] = False
                self._set_name_color(row, False)
                if not any(self.row_alarm.values()):
                    self.stop_alarm()
        elif status == 'error':
            status_item = QTableWidgetItem("识别失败")
            status_item.setBackground(QBrush(QColor(100, 100, 115)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.table.setItem(row, 6, status_item)
        elif status == 'disabled':
            status_item = QTableWidgetItem("已禁用")
            status_item.setBackground(QBrush(QColor(80, 80, 95)))
            status_item.setForeground(QBrush(QColor(200, 200, 210)))
            self.table.setItem(row, 6, status_item)
            if self.row_alarm.get(row, False):
                self.row_alarm[row] = False
                self._set_name_color(row, False)
        elif status == '监控中':
            status_item = QTableWidgetItem("监控中")
            status_item.setBackground(QBrush(QColor(0, 0, 0, 0)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.table.setItem(row, 6, status_item)
        else:
            status_item = QTableWidgetItem(status)
            self.table.setItem(row, 6, status_item)
        
        self._update_alarm_count()
    
    def _update_alarm_count(self):
        count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 6)
            if item and item.text() == "报警":
                count += 1
        self.alarm_count_label.setText(f"报警数: {count}")
    
    def _update_status_display(self):
        if self.monitoring:
            self.status_label.setText("状态: 监控运行中")
    
    def save_config(self):
        config = {
            'monitors': [],
            'volume': self.volume_slider.value(),
            'interval': self.interval_combo.currentText(),
            'loop_enabled': self.loop_enabled
        }
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1) is None:
                continue
            enable_check = self.table.cellWidget(row, 0)
            mute_check = self.table.cellWidget(row, 8)
            config['monitors'].append({
                'name': self.table.item(row, 1).text(),
                'lower': float(self.table.item(row, 3).text()),
                'upper': float(self.table.item(row, 4).text()),
                'coords': self.table.item(row, 5).text(),
                'enabled': enable_check.isChecked() if enable_check else True,
                'muted': mute_check.isChecked() if mute_check else False
            })
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.status_label.setText("状态: 配置已保存")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存失败: {e}")
    
    def load_config(self):
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 暂停表格重绘，避免闪烁
            self.table.setUpdatesEnabled(False)
            
            self.table.setRowCount(0)
            self.row_enabled.clear()
            self.row_alarm.clear()
            self.row_muted.clear()
            self.value_history.clear()
            self.last_value.clear()
            
            for item in config.get('monitors', []):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.value_history[row] = []
                self.last_value[row] = None
                
                enable_check = QCheckBox()
                enable_check.setChecked(item.get('enabled', True))
                enable_check.setStyleSheet("margin-left: 12px;")
                self.table.setCellWidget(row, 0, enable_check)
                self.row_enabled[row] = item.get('enabled', True)
                enable_check.stateChanged.connect(lambda state, r=row: self._on_enable_changed(r, state))
                
                mute_check = QCheckBox()
                mute_check.setChecked(item.get('muted', False))
                mute_check.setStyleSheet("margin-left: 12px;")
                self.table.setCellWidget(row, 8, mute_check)
                self.row_muted[row] = item.get('muted', False)
                mute_check.stateChanged.connect(lambda state, r=row: self._on_mute_changed(r, state))
                
                self.table.setItem(row, 1, QTableWidgetItem(item['name']))
                self.table.setItem(row, 2, QTableWidgetItem("--"))
                self.table.setItem(row, 3, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 4, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 5, QTableWidgetItem(item['coords']))
                self.table.setItem(row, 6, QTableWidgetItem("待监控"))
                self.table.setItem(row, 7, QTableWidgetItem("--"))
            
            volume = config.get('volume', 80)
            self.volume_slider.setValue(volume)
            self.on_volume_changed(volume)
            
            interval = config.get('interval', '500ms')
            idx = self.interval_combo.findText(interval)
            if idx >= 0:
                self.interval_combo.setCurrentIndex(idx)
                self.detect_interval = int(interval.replace("ms", ""))
            
            self.status_label.setText("状态: 配置已加载")
            
            # 恢复表格重绘
            self.table.setUpdatesEnabled(True)
        except Exception as e:
            self.table.setUpdatesEnabled(True)
            print(f"加载失败: {e}")
    
    def load_config_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", "", "JSON文件 (*.json)"
        )
        if file_path:
            self.config_file = file_path
            self.load_config()
    
    def closeEvent(self, event):
        self.stop_monitor()
        self.stop_alarm()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
