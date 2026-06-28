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
    QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QLineEdit, QGroupBox, QFrame, QSlider, QComboBox,
    QProgressBar, QCheckBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QByteArray
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
        
        from PySide6.QtWidgets import QApplication
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


class MiniWindow(QWidget):
    """精简小窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("报警监控")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setFixedSize(200, 40)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 46, 0.96);
                border: 2px solid #4a9eff;
                border-radius: 12px;
            }
            QLabel {
                color: #e0e0f0;
                font-family: "Microsoft YaHei";
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton {
                background-color: #3a5a7a;
                color: #e0e0f0;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: bold;
                font-family: "Microsoft YaHei";
                font-size: 12px;
                min-height: 20px;
            }
            QPushButton:hover { background-color: #4a6a8a; }
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 4, 8, 4)
        
        self.alarm_label = QLabel("✅ 正常")
        self.alarm_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.alarm_label.setStyleSheet("color: #4ade80; padding: 0px;")
        layout.addWidget(self.alarm_label, 1)
        
        self.btn_restore = QPushButton("切换")
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
        if len(name) > 10:
            name = name[:10] + "..."
        self.alarm_label.setText(f"⚠️ {name}")
        self.alarm_label.setStyleSheet("color: #ff6b6b; padding: 0px;")
    
    def clear_alarm(self):
        self.alarm_label.setText("✅ 正常")
        self.alarm_label.setStyleSheet("color: #4ade80; padding: 0px;")
    
    def restore_window(self):
        self.parent_window.show_normal_mode()
    
    def closeEvent(self, event):
        self.parent_window.mini_window = None
        event.accept()


class TrendChartWidget(QWidget):
    """数值趋势曲线"""
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
        
        chart_rect = QRect(
            padding_left, padding_top,
            rect.width() - padding_left - padding_right,
            rect.height() - padding_top - padding_bottom
        )
        
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
        self.mini_window = None
        self.chart_visible = True
        
        self.record_timer = QTimer()
        self.record_timer.timeout.connect(self.record_current_value)
        self.recording = False
        self.record_interval = 60 * 60
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QLabel { color: #e0e0f0; font-family: "Microsoft YaHei"; }
            QTableWidget {
                background-color: #1e1e2e;
                alternate-background-color: #27273d;
                color: #e0e0f0;
                gridline-color: #33334a;
                selection-background-color: #4a9eff;
                border: 1px solid #33334a;
            }
            QPushButton {
                background-color: #363650;
                color: #e0e0f0;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #464668; }
        """)
        
        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.loop_enabled = True
        self.detect_interval = 500
        self.value_history = {}
        self.alarm_player = AlarmSoundPlayer()
        self.alarm_playing = False
        self.row_enabled = {}
        self.row_alarm = {}
        self.row_muted = {}
        
        self._setup_ui()
        self.load_config()
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # 表格 (简化为9列)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "启用", "名称", "备注", "当前值", "下限", "上限", "坐标", "状态", "静音"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        main_layout.addWidget(self.table, 3)
        
        # 按钮栏 (名称简化)
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加")
        self.btn_add.clicked.connect(self.add_monitor_row)
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        self.btn_test = QPushButton("测试")
        self.btn_test.clicked.connect(self.test_selected_point)
        self.btn_start = QPushButton("开始")
        self.btn_start.clicked.connect(self.start_monitor)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_mini = QPushButton("小窗口")
        self.btn_mini.clicked.connect(self.toggle_mini_mode)
        
        for btn in [self.btn_add, self.btn_edit, self.btn_test, self.btn_start, self.btn_stop, self.btn_mini]:
            btn_layout.addWidget(btn)
        main_layout.addLayout(btn_layout)
        
    def test_selected_point(self):
        """测试当前选中行，不需要开始监控也可以使用"""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
            
        # 尝试初始化一个临时的监测器来获取识别结果
        from monitor import MonitorThread
        coords_text = self.table.item(row, 6).text()
        nums = re.findall(r'\d+', coords_text)
        if len(nums) < 4: return
        x, y, w, h = map(int, nums[:4])
        
        # 使用临时测试逻辑
        try:
            # 假设 MonitorThread 类支持静态捕获或我们需要一个实例
            if not self.monitor_thread:
                self.monitor_thread = MonitorThread([])
            result = self.monitor_thread._capture_and_ocr(x, y, w, h)
            QMessageBox.information(self, "测试", f"识别数值: {result}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def add_monitor_row(self):
        self.picker = CoordinatePicker(self)
        self.picker.coord_selected.connect(self._on_picker_completed)
        self.picker.showFullScreen()

    def _on_picker_completed(self, x, y, w, h):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 6, QTableWidgetItem(f"{x},{y},{w},{h}"))
        self.table.setCellWidget(row, 0, QCheckBox())
        self.table.setCellWidget(row, 8, QCheckBox())

    def edit_monitor_point(self): pass
    def start_monitor(self): self.monitoring = True
    def stop_monitor(self): self.monitoring = False
    def toggle_mini_mode(self): pass
    def record_current_value(self): pass
    def load_config(self): pass
    def save_config(self): pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
