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
    QGroupBox, QSlider, QProgressBar, QCheckBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient, QIcon
)
from monitor import MonitorThread

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

try:
    import numpy as np
    import mss
    from PIL import Image
    EXT_LIBS_AVAILABLE = True
except ImportError:
    EXT_LIBS_AVAILABLE = False


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
        self.total_rect = total_rect
        self.setGeometry(total_rect)
        
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
        
        self.label = QLabel("鼠标 按住左键拖拽选择监控区域，松开鼠标自动完成", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("QLabel { color: white; background: rgba(0,0,0,220); padding: 14px 28px; border-radius: 14px; font-size: 18px; font-weight: bold; border: 1px solid rgba(255,255,255,0.2); }")
        self.label.adjustSize()
        self.label.move((self.width() - self.label.width()) // 2, self.height() - self.label.height() - 80)
        
        self.coord_label = QLabel("等待选择...", self)
        self.coord_label.setAlignment(Qt.AlignCenter)
        self.coord_label.setStyleSheet("QLabel { color: #5aa9ff; background: rgba(0,0,0,220); padding: 10px 22px; border-radius: 10px; font-size: 17px; font-weight: bold; border: 1px solid #5aa9ff; }")
        self.coord_label.adjustSize()
        self.coord_label.move((self.width() - self.coord_label.width()) // 2, 60)
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
            self.label.setText("鼠标 拖动鼠标调整区域大小")
            self.label.adjustSize()
            self.label.move((self.width() - self.label.width()) // 2, self.height() - self.label.height() - 80)
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_pos = event.position().toPoint()
            rect = self._get_current_rect()
            self.coord_label.setText(f"起点: ({self.start_pos.x()}, {self.start_pos.y()})  大小: {rect.width()} × {rect.height()}")
            self.coord_label.adjustSize()
            self.coord_label.move((self.width() - self.coord_label.width()) // 2, 60)
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
                self.label.move((self.width() - self.label.width()) // 2, self.height() - self.label.height() - 80)
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


class MiniWindow(QWidget):
    """精简小窗口模式"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("报警监控")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setFixedSize(220, 45)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("""
            QWidget { background-color: rgba(30, 30, 46, 0.96); border: 2px solid #4a9eff; border-radius: 12px; }
            QLabel { color: #e0e0f0; font-family: 'Microsoft YaHei'; font-size: 13px; font-weight: bold; border: none; background: transparent; }
            QPushButton { background-color: #3a5a7a; color: #e0e0f0; border: none; border-radius: 6px; padding: 4px 12px; font-weight: bold; font-family: 'Microsoft YaHei'; font-size: 12px; min-height: 20px; }
            QPushButton:hover { background-color: #4a6a8a; }
        """)
        layout = QHBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 4, 10, 4)
        
        self.alarm_label = QLabel(" 正常")
        self.alarm_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.alarm_label.setStyleSheet("color: #4ade80; padding: 0px;")
        layout.addWidget(self.alarm_label, 1)
        
        self.btn_restore = QPushButton("还原")
        self.btn_restore.clicked.connect(self.restore_window)
        layout.addWidget(self.btn_restore)
        self.drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None:
            delta = event.globalPosition().toPoint() - self.drag_pos
            self.move(self.pos() + delta)
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def set_alarm(self, name):
        if len(name) > 8:
            name = name[:8] + "..."
        self.alarm_label.setText(f"⚠️ {name}")
        self.alarm_label.setStyleSheet("color: #ff6b6b; padding: 0px; font-weight: bold;")

    def clear_alarm(self):
        self.alarm_label.setText(" 正常")
        self.alarm_label.setStyleSheet("color: #4ade80; padding: 0px;")

    def restore_window(self):
        self.parent_window.show_normal_mode()
        self.close()


class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.data = []
        self.max_points = 15
        self.title = "数值趋势"

    def set_data(self, data_list, title="数值趋势"):
        self.data = data_list[-self.max_points:]
        self.title = title
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        padding_left = 20
        padding_right = 20
        padding_top = 32
        padding_bottom = 28
        
        painter.setBrush(QColor("#252538"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)
        
        painter.setPen(QColor("#e8e8f0"))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(padding_left, 22, self.title)
        
        chart_rect = QRect(padding_left, padding_top, rect.width() - padding_left - padding_right, rect.height() - padding_top - padding_bottom)
        painter.setPen(QColor("#36364a"))
        grid_rows = 5
        for i in range(grid_rows + 1):
            y = chart_rect.top() + chart_rect.height() * i / grid_rows
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)
            
        if len(self.data) < 2:
            painter.setPen(QColor("#7a7a9a"))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(chart_rect, Qt.AlignCenter, "选中监控行后显示数值趋势")
            return
            
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
        
        points = []
        step_x = chart_rect.width() / (len(self.data) - 1)
        for i, val in enumerate(self.data):
            x = chart_rect.left() + i * step_x
            y = chart_rect.bottom() - (val - min_val) / val_range * chart_rect.height()
            points.append(QPoint(x, y))
            
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
            
        pen = QPen(QColor("#4a9eff"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])
            
        if points:
            painter.setPen(QColor("#aaccff"))
            painter.setFont(QFont("Arial", 8))
            for i, p in enumerate(points):
                text = f"{self.data[i]:.2f}"
                text_w = painter.fontMetrics().horizontalAdvance(text)
                painter.drawText(p.x() - text_w / 2, p.y() - 8, text)
                
            last_p = points[-1]
            painter.setPen(QPen(QColor("#ff6b6b"), 3))
            painter.setBrush(QColor("#ff6b6b"))
            painter.drawEllipse(last_p, 4, 4)
            
            painter.setPen(QColor("#7a7a9a"))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(chart_rect.left(), chart_rect.bottom() + 18, "首变")
            painter.drawText(chart_rect.right() - 40, chart_rect.bottom() + 18, f"第{len(self.data)}变")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumSize(800, 600)
        self.resize(1200, 750)
        
        # 尝试为主窗口本身也绑定一下图标文件
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.mini_window = None
        self.chart_visible = True

        self.record_timer = QTimer()
        self.record_timer.timeout.connect(self.record_current_value)
        self.recording = False
        self.record_interval = 60 * 60

        self.test_reader = None
        self.reader_loading = False

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
            QTableWidget::item { padding: 6px; text-align: center; }
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
            QPushButton#btn_start:disabled { background-color: #3a3a50; color: #7a7a9a; }
            QPushButton#btn_stop {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c04040, stop:1 #a03030);
                color: white;
            }
            QPushButton#btn_stop:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d05050, stop:1 #b03a3a); }
            QPushButton#btn_stop:disabled { background-color: #3a3a50; color: #7a7a9a; }
            QPushButton#btn_delete { background-color: #b03a3a; }
            QPushButton#btn_delete:hover { background-color: #c44a4a; }
            QPushButton#btn_save { background-color: #2a5a9a; }
            QPushButton#btn_save:hover { background-color: #356ab0; }
            QPushButton#btn_mini { background-color: #4a6a8a; }
            QPushButton#btn_mini:hover { background-color: #5a7a9a; }
            QPushButton#btn_chart_toggle { background-color: #4a4a6a; }
            QPushButton#btn_chart_toggle:hover { background-color: #5a5a7a; }
            QSlider::groove:horizontal { height: 6px; background: #363650; border-radius: 3px; }
            QSlider::handle:horizontal { background: #4a9eff; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #4a9eff; border-radius: 3px; }
            QDoubleSpinBox { background-color: #363650; color: #e0e0f0; border: 1px solid #4a4a6a; border-radius: 6px; padding: 5px 10px; min-height: 20px; }
            QDoubleSpinBox:hover { border-color: #4a9eff; }
            QProgressBar { background-color: #27273d; border: 1px solid #33334a; border-radius: 6px; text-align: center; color: #e0e0f0; height: 18px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4a9eff, stop:1 #6ab4ff); border-radius: 6px; }
            QCheckBox { color: #e0e0f0; font-family: "Microsoft YaHei"; font-size: 13px; }
            QCheckBox::indicator { width: 20px; height: 20px; border-radius: 4px; background-color: #363650; border: 1px solid #505070; }
            QCheckBox::indicator:checked { background-color: #4a9eff; border-color: #4a9eff; }
            QGroupBox { color: #e0e0f0; font-weight: bold; font-family: "Microsoft YaHei"; border: 1px solid #33334a; border-radius: 10px; margin-top: 12px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #c0c0e0; }
            QLineEdit { background-color: #363650; color: #e0e0f0; border: 1px solid #4a4a6a; border-radius: 4px; padding: 2px 6px; }
            QLineEdit:focus { border-color: #4a9eff; }
        """)

        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.value_history = {}
        self.alarm_playing = False

        self.row_sensitivity = {}

        self.alarm_player = AlarmSoundPlayer()
        self._setup_ui()
        self.load_config()

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
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
                    import easyocr
                    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                    self.finished.emit(reader)
                except Exception as e:
                    print(f"OCR加载异常: {e}")
                    self.finished.emit(None)

        self.loader_thread = LoaderThread()
        self.loader_thread.finished.connect(self._on_reader_loaded)
        self.loader_thread.start()

    def _on_reader_loaded(self, reader):
        self.reader_loading = False
        if reader is not None:
            self.test_reader = reader
            self.set_ocr_status("就绪 ✅", True)
        else:
            self.set_ocr_status("加载失败，请检查网络后重启", False)

    def create_sensitivity_widget(self, row, value=5):
        """核心重构点：解耦行号，改用通用Slider对象分发器"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        
        slider = QSlider(Qt.Horizontal)
        slider.setRange(1, 10)
        slider.setValue(value)
        slider.setFixedWidth(60)
        
        label = QLabel(str(value))
        label.setFixedWidth(20)
        label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(slider)
        layout.addWidget(label)
        
        widget.slider = slider
        widget.label = label
        
        # 移除带参数的lambda表达式绑定，改用动态位置扫描
        slider.valueChanged.connect(self.on_slider_value_changed)
        
        self.row_sensitivity[row] = value
        return widget

    def on_slider_value_changed(self, value):
        """核心重构点：利用当前触发的滑块相对表格的坐标，精准算出行号，绝无串行错位现象"""
        sender_slider = self.sender()
        if not sender_slider:
            return
            
        for r in range(self.table.rowCount()):
            cell_widget = self.table.cellWidget(r, 10)
            if cell_widget and cell_widget.findChild(QSlider) == sender_slider:
                if hasattr(cell_widget, 'label'):
                    cell_widget.label.setText(str(value))
                
                self.row_sensitivity[r] = value
                
                # 若监控已启动，将变更后的灵敏度直接注入监控子线程
                if self.monitoring and self.monitor_thread is not None:
                    for m in self.monitor_thread.monitors:
                        if m.get('row') == r:
                            m['sensitivity'] = value
                            break
                break

    def get_row_sensitivity(self, row):
        return self.row_sensitivity.get(row, 5)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        title_layout = QHBoxLayout()
        title = QLabel(" 屏幕数字监控报警系统")
        title_font = QFont("Microsoft YaHei")
        title_font.setPointSize(19)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        subtitle = QLabel("---天长污水陈诚")
        subtitle.setStyleSheet("color: #7a7a9a; font-size: 14px; font-weight: bold;")
        title_layout.addWidget(subtitle)
        main_layout.addLayout(title_layout)

        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 6px 14px; background-color: #2a2a42; border-radius: 6px; color: #e6b84d; border: 1px solid #3a3a55;")
        main_layout.addWidget(self.ocr_status_label)

        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        main_layout.addWidget(self.download_progress)

        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "备注", "当前值", "下限", "上限", "坐标", "状态", "报警时间", "静音", "灵敏度"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setRowCount(0)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 65)
        self.table.setColumnWidth(5, 65)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 80)
        self.table.setColumnWidth(8, 100)
        self.table.setColumnWidth(9, 50)
        self.table.setColumnWidth(10, 110)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table, 3)

        self.chart_group = QGroupBox(" 数值趋势曲线")
        chart_layout = QVBoxLayout(self.chart_group)
        chart_layout.setContentsMargins(12, 18, 12, 12)
        self.trend_chart = TrendChartWidget()
        chart_layout.addWidget(self.trend_chart, 1)

        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(10)
        settings_layout.setAlignment(Qt.AlignLeft)
        settings_layout.addWidget(QLabel("记录间隔:"))
        self.record_interval_spin = QDoubleSpinBox()
        self.record_interval_spin.setRange(1, 1440)
        self.record_interval_spin.setValue(60)
        self.record_interval_spin.setSuffix(" 分钟")
        self.record_interval_spin.setFixedWidth(95)
        settings_layout.addWidget(self.record_interval_spin)
        
        settings_layout.addWidget(QLabel("检测间隔:"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 3600.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setValue(0.5)
        self.interval_spin.setFixedWidth(85)
        self.interval_spin.valueChanged.connect(self.on_interval_changed)
        settings_layout.addWidget(self.interval_spin)
        settings_layout.addStretch()
        chart_layout.addLayout(settings_layout)
        main_layout.addWidget(self.chart_group, 2)

        btn_layout_top = QHBoxLayout()
        btn_layout_top.setSpacing(10)
        btn_layout_top.setAlignment(Qt.AlignLeft)
        self.btn_add = QPushButton("➕ 添加")
        self.btn_add.clicked.connect(self.add_monitor_row)
        btn_layout_top.addWidget(self.btn_add)
        self.btn_delete = QPushButton(" 删除")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout_top.addWidget(self.btn_delete)
        self.btn_edit = QPushButton("✏️ 编辑坐标")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        btn_layout_top.addWidget(self.btn_edit)
        self.btn_test = QPushButton("🎯 区域测试")
        self.btn_test.clicked.connect(self.test_selected_point)
        btn_layout_top.addWidget(self.btn_test)
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout_top.addWidget(self.btn_start)
        self.btn_stop = QPushButton("⏹ 停止监控")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)
        btn_layout_top.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout_top)

        btn_layout_bottom = QHBoxLayout()
        btn_layout_bottom.setSpacing(10)
        btn_layout_bottom.setAlignment(Qt.AlignLeft)
        self.btn_mini = QPushButton("📱 悬浮小窗口")
        self.btn_mini.setObjectName("btn_mini")
        self.btn_mini.clicked.connect(self.toggle_mini_mode)
        btn_layout_bottom.addWidget(self.btn_mini)
        self.btn_chart_toggle = QPushButton(" 收起曲线")
        self.btn_chart_toggle.setObjectName("btn_chart_toggle")
        self.btn_chart_toggle.clicked.connect(self.toggle_chart)
        btn_layout_bottom.addWidget(self.btn_chart_toggle)
        self.btn_clear_time = QPushButton(" 清空报警时间")
        self.btn_clear_time.clicked.connect(self.clear_alarm_time)
        btn_layout_bottom.addWidget(self.btn_clear_time)
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout_bottom.addWidget(self.btn_save)
        self.btn_load = QPushButton("📂 加载外部配置")
        self.btn_load.clicked.connect(self.load_config_dialog)
        btn_layout_bottom.addWidget(self.btn_load)
        main_layout.addLayout(btn_layout_bottom)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; border: 1px solid #33334a;")
        status_layout.addWidget(self.status_label)
        main_layout.addLayout(status_layout)

    def set_ocr_status(self, text, is_ready):
        self.ocr_status_label.setText(f"OCR引擎: {text}")

    def add_monitor_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        cb = QCheckBox()
        cb.setChecked(True)
        self.table.setCellWidget(row, 0, cb)
        
        self.table.setItem(row, 1, QTableWidgetItem(f"监测点_{row+1}"))
        self.table.setItem(row, 2, QTableWidgetItem("无"))
        self.table.setItem(row, 3, QTableWidgetItem("-"))
        self.table.setItem(row, 4, QTableWidgetItem("0"))
        self.table.setItem(row, 5, QTableWidgetItem("100"))
        self.table.setItem(row, 6, QTableWidgetItem("0,0,100,100"))
        self.table.setItem(row, 7, QTableWidgetItem("未开始"))
        self.table.setItem(row, 8, QTableWidgetItem("-"))
        
        cb_mute = QCheckBox()
        self.table.setCellWidget(row, 9, cb_mute)
        
        sens_widget = self.create_sensitivity_widget(row, 5)
        self.table.setCellWidget(row, 10, sens_widget)

    def delete_monitor_point(self):
        cur_row = self.table.currentRow()
        if cur_row >= 0:
            self.table.removeRow(cur_row)
            self.reindex_sensitivity_data()

    def reindex_sensitivity_data(self):
        """删除行后必须重新扫描纠正底层的映射结构，杜绝混乱现象"""
        new_sens = {}
        for r in range(self.table.rowCount()):
            widget = self.table.cellWidget(r, 10)
            if widget and hasattr(widget, 'slider'):
                new_sens[r] = widget.slider.value()
        self.row_sensitivity = new_sens

    def edit_monitor_point(self):
        cur_row = self.table.currentRow()
        if cur_row < 0:
            QMessageBox.warning(self, "警告", "请先选择需要编辑坐标的目标行")
            return
        picker = CoordinatePicker(self)
        def on_selected(x, y, w, h):
            if w > 0 and h > 0:
                self.table.setItem(cur_row, 6, QTableWidgetItem(f"{x},{y},{w},{h}"))
        picker.coord_selected.connect(on_selected)

    def test_selected_point(self):
        """执行单次区域扫描OCR抓取测试"""
        cur_row = self.table.currentRow()
        if cur_row < 0:
            QMessageBox.warning(self, "警告", "请先在列表中选中一行需要测试的监测点")
            return
        if not self.test_reader:
            QMessageBox.warning(self, "警告", "OCR引擎未完全就绪，请稍等...")
            return
        if not EXT_LIBS_AVAILABLE:
            QMessageBox.critical(self, "错误", "缺少必要的运行库(mss/numpy/Pillow)")
            return
            
        coord_str = self.table.item(cur_row, 6).text() if self.table.item(cur_row, 6) else "0,0,0,0"
        try:
            x, y, w, h = [int(p) for p in coord_str.split(',')]
        except:
            QMessageBox.critical(self, "错误", "区域坐标格式错误")
            return
            
        if w <= 0 or h <= 0:
            QMessageBox.warning(self, "警告", "无效的扫描区域大小")
            return
            
        try:
            with mss.mss() as sct:
                monitor = {"top": y, "left": x, "width": w, "height": h}
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                img_np = np.array(img)
                results = self.test_reader.readtext(img_np)
                text = "".join([r[1] for r in results])
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", text)
                val_str = nums[0] if nums else "未提取到任何数值"
                QMessageBox.information(self, "测试结果", f"文字结果: {text}\n数字识别: {val_str}")
        except Exception as e:
            QMessageBox.critical(self, "扫描异常", f"单次识别发生异常:\n{e}")

    def start_monitor(self):
        if self.monitoring: return
        self.monitoring = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        monitors = []
        for r in range(self.table.rowCount()):
            cb = self.table.cellWidget(r, 0)
            if cb and cb.isChecked():
                name = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
                coord_str = self.table.item(r, 6).text() if self.table.item(r, 6) else "0,0,0,0"
                try:
                    parts = [int(p) for p in coord_str.split(',')]
                except:
                    parts = [0, 0, 100, 100]
                lower = float(self.table.item(r, 4).text()) if self.table.item(r, 4) else 0.0
                upper = float(self.table.item(r, 5).text()) if self.table.item(r, 5) else 100.0
                sens = self.get_row_sensitivity(r)
                monitors.append({
                    'row': r, 'name': name, 'bbox': parts,
                    'lower': lower, 'upper': upper, 'sensitivity': sens
                })
                
        self.monitor_thread = MonitorThread(monitors)
        if self.test_reader:
            self.monitor_thread.set_reader(self.test_reader)
        self.monitor_thread.set_interval(int(self.interval_spin.value() * 1000))
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.start()

    def stop_monitor(self):
        if not self.monitoring: return
        self.monitoring = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread.wait()
            self.monitor_thread = None
        self.stop_alarm()

    def on_value_updated(self, row, val):
        if row < self.table.rowCount():
            self.table.setItem(row, 3, QTableWidgetItem(f"{val:.2f}"))
            if row not in self.value_history:
                self.value_history[row] = []
            self.value_history[row].append(val)
            if self.table.currentRow() == row:
                self.trend_chart.set_data(self.value_history[row], f"【{self.table.item(row, 1).text()}】数值趋势")

    def on_status_updated(self, row, status):
        if row < self.table.rowCount():
            self.table.setItem(row, 7, QTableWidgetItem(status))
            if status == 'normal':
                any_alarm = False
                for r in range(self.table.rowCount()):
                    item = self.table.item(r, 7)
                    if item and item.text() not in ['normal', '就绪', '未开始', 'error']:
                        any_alarm = True
                        break
                if not any_alarm:
                    self.stop_alarm()
                    if self.mini_window:
                        self.mini_window.clear_alarm()

    def on_alarm_triggered(self, row, name, val, lower, upper):
        if row < self.table.rowCount():
            now_str = datetime.now().strftime("%H:%M:%S")
            self.table.setItem(row, 8, QTableWidgetItem(now_str))
            
            cb_mute = self.table.cellWidget(row, 9)
            is_muted = cb_mute.isChecked() if cb_mute else False
            
            if not is_muted and not self.alarm_playing:
                self.alarm_playing = True
                self.alarm_player.play()
                
            if self.mini_window:
                self.mini_window.set_alarm(name)

    def stop_alarm(self):
        self.alarm_player.stop()
        self.alarm_playing = False

    def on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.set_interval(int(val * 1000))

    def toggle_mini_mode(self):
        if not self.mini_window:
            self.mini_window = MiniWindow(self)
            # 在悬浮窗初始化时也绑定图标文件
            script_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(script_dir, "favicon.ico")
            if os.path.exists(icon_path):
                self.mini_window.setWindowIcon(QIcon(icon_path))
        geo = self.geometry()
        self.mini_window.move(geo.x() + 100, geo.y() + 100)
        self.mini_window.show()
        self.hide()

    def show_normal_mode(self):
        self.showNormal()
        self.raise_()

    def toggle_chart(self):
        self.chart_visible = not self.chart_visible
        self.chart_group.setVisible(self.chart_visible)
        self.btn_chart_toggle.setText("展开曲线" if not self.chart_visible else " 收起曲线")

    def clear_alarm_time(self):
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 8, QTableWidgetItem("-"))

    def record_current_value(self):
        pass

    def _on_selection_changed(self):
        r = self.table.currentRow()
        if r >= 0 and r in self.value_history:
            name = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            self.trend_chart.set_data(self.value_history[r], f"【{name}】数值趋势")

    def _update_status_display(self):
        if self.monitoring:
            self.status_label.setText(f"状态: 正在连续监控中... 刷新时间: {datetime.now().strftime('%H:%M:%S')}")
            self.status_label.setStyleSheet("padding: 8px 12px; background-color: #1e3a2f; border-radius: 6px; border: 1px solid #2e7d32; color: #4ade80;")
        else:
            self.status_label.setText("状态: 已停止监控，处于挂机就绪态")
            self.status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; border: 1px solid #33334a; color: #e0e0f0;")

    def save_config(self):
        try:
            config = {
                'interval': self.interval_spin.value(),
                'record_interval': self.record_interval_spin.value(),
                'monitors': []
            }
            for r in range(self.table.rowCount()):
                cb = self.table.cellWidget(r, 0)
                cb_mute = self.table.cellWidget(r, 9)
                config['monitors'].append({
                    'enabled': cb.isChecked() if cb else True,
                    'name': self.table.item(r, 1).text() if self.table.item(r, 1) else "",
                    'memo': self.table.item(r, 2).text() if self.table.item(r, 2) else "",
                    'lower': self.table.item(r, 4).text() if self.table.item(r, 4) else "0",
                    'upper': self.table.item(r, 5).text() if self.table.item(r, 5) else "100",
                    'coord': self.table.item(r, 6).text() if self.table.item(r, 6) else "0,0,0,0",
                    'muted': cb_mute.isChecked() if cb_mute else False,
                    'sensitivity': self.get_row_sensitivity(r)
                })
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            self.status_label.setText("状态: 配置已成功自动导出保存")
        except Exception as e:
            print(f"保存失败: {e}")

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self.table.setRowCount(0)
            monitors = config.get('monitors', [])
            for r, m in enumerate(monitors):
                self.table.insertRow(r)
                cb = QCheckBox()
                cb.setChecked(m.get('enabled', True))
                self.table.setCellWidget(r, 0, cb)
                self.table.setItem(r, 1, QTableWidgetItem(m.get('name', '')))
                self.table.setItem(r, 2, QTableWidgetItem(m.get('memo', '')))
                self.table.setItem(r, 3, QTableWidgetItem("-"))
                self.table.setItem(r, 4, QTableWidgetItem(m.get('lower', '0')))
                self.table.setItem(r, 5, QTableWidgetItem(m.get('upper', '100')))
                self.table.setItem(r, 6, QTableWidgetItem(m.get('coord', '0,0,0,0')))
                self.table.setItem(r, 7, QTableWidgetItem("就绪"))
                self.table.setItem(r, 8, QTableWidgetItem("-"))
                cb_mute = QCheckBox()
                cb_mute.setChecked(m.get('muted', False))
                self.table.setCellWidget(r, 9, cb_mute)
                
                sens_val = m.get('sensitivity', 5)
                sens_widget = self.create_sensitivity_widget(r, sens_val)
                self.table.setCellWidget(r, 10, sens_widget)
            
            self.interval_spin.setValue(config.get('interval', 0.5))
            self.record_interval_spin.setValue(config.get('record_interval', 60))
        except Exception as e:
            print(f"配置文件解析错误: {e}")

    def load_config_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择外部监控json配置文件", "", "JSON文件 (*.json)")
        if file_path:
            self.config_file = file_path
            self.load_config()

    def closeEvent(self, event):
        self.stop_monitor()
        if self.mini_window:
            self.mini_window.close()
        self.save_config()
        event.accept()


if __name__ == "__main__":
    # Windows 专属底层修复：防止 Windows 下开发启动时，任务栏图标直接显示 Python 默认的蛇头徽标
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("system.monitor.datacontrol.v1")
        except:
            pass

    app = QApplication(sys)
    
    # 动态分析计算 favicon.ico 的绝对资产路径，兼容未来打包 exe 时的动态展开目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(script_dir, "favicon.ico")
    
    if not os.path.exists(icon_path) and getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        icon_path = os.path.join(exe_dir, "favicon.ico")

    # 全局设置应用图标，让所有的子弹窗、悬浮窗、主窗口一劳永逸
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
