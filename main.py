import sys
import json
import os
import time
import re
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QDialogButtonBox, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QGroupBox, QGridLayout, QFrame, QSlider, QFileDialog, QComboBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect, QUrl
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from monitor import MonitorThread


class CoordinatePicker(QWidget):
    """鼠标坐标拾取器 - 全屏透明窗口显示鼠标坐标"""
    coord_selected = Signal(int, int)
    
    def __init__(self, parent=None, coord_type="左上角"):
        super().__init__(parent)
        self.coord_type = coord_type
        self.parent_widget = parent
        self.setWindowTitle(f"选择{coord_type}")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        
        from PySide6.QtWidgets import QApplication
        screens = QApplication.screens()
        total_rect = self.geometry()
        for s in screens:
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)
        
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        
        self.current_pos = QPoint(0, 0)
        
        self.label = QLabel(f"🖱 移动鼠标到{coord_type}位置，点击确认 | 按 ESC 取消", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0,0,0,200);
                padding: 12px 24px;
                border-radius: 12px;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid rgba(255,255,255,0.3);
            }
        """)
        self.label.adjustSize()
        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - self.label.height() - 60
        )
        
        self.coord_label = QLabel("X: 0  Y: 0", self)
        self.coord_label.setAlignment(Qt.AlignCenter)
        self.coord_label.setStyleSheet("""
            QLabel {
                color: #4a9eff;
                background: rgba(0,0,0,200);
                padding: 8px 20px;
                border-radius: 8px;
                font-size: 20px;
                font-weight: bold;
                border: 2px solid #4a9eff;
            }
        """)
        self.coord_label.adjustSize()
        self.coord_label.move(
            (self.width() - self.coord_label.width()) // 2,
            60
        )
        
        self.setMouseTracking(True)
        self.setFocus(Qt.OtherFocusReason)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))
        
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1, Qt.DashLine))
        painter.drawLine(self.current_pos.x(), 0, self.current_pos.x(), self.height())
        painter.drawLine(0, self.current_pos.y(), self.width(), self.current_pos.y())
        
        painter.setPen(QPen(QColor(255, 50, 50), 2))
        painter.setBrush(QBrush(QColor(255, 0, 0, 80)))
        painter.drawEllipse(self.current_pos, 6, 6)
        
        painter.setPen(QColor(255, 255, 255, 200))
        painter.setFont(QFont("Arial", 12))
        painter.drawText(
            self.current_pos.x() + 15,
            self.current_pos.y() - 10,
            f"({self.current_pos.x()}, {self.current_pos.y()})"
        )
    
    def mouseMoveEvent(self, event):
        self.current_pos = event.position().toPoint()
        self.coord_label.setText(f"X: {self.current_pos.x()}  Y: {self.current_pos.y()}")
        self.coord_label.adjustSize()
        self.coord_label.move(
            (self.width() - self.coord_label.width()) // 2,
            60
        )
        self.update()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.coord_selected.emit(self.current_pos.x(), self.current_pos.y())
            self.close()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.coord_selected.emit(-1, -1)
            self.close()
    
    def closeEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        event.accept()


class AlarmSoundPlayer:
    """报警声音播放器 - 支持循环播放MP3/WAV"""
    def __init__(self):
        self.player = QMediaPlayer()
        self.is_playing = False
        self.sound_file = None
        self.loop_timer = QTimer()
        self.loop_timer.timeout.connect(self._check_and_loop)
        self.loop_timer.start(100)
        
    def load_sound(self, file_path):
        """加载音频文件"""
        try:
            self.player.setSource(QUrl.fromLocalFile(file_path))
            # 检查是否加载成功
            if self.player.mediaStatus() == QMediaPlayer.NoMedia:
                return False
            self.sound_file = file_path
            return True
        except Exception as e:
            print(f"加载音频失败: {e}")
            return False
    
    def play(self):
        """播放报警声音（循环）"""
        if self.player.source().isEmpty():
            return
        
        self.player.setLoops(-1)  # 无限循环
        self.player.play()
        self.is_playing = True
    
    def stop(self):
        """停止报警声音"""
        self.player.stop()
        self.is_playing = False
    
    def set_volume(self, volume):
        """设置音量 (0.0 - 1.0)"""
        self.player.setVolume(int(volume * 100))
    
    def _check_and_loop(self):
        """检查并循环播放"""
        if self.is_playing and self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
            self.player.play()
    
    def is_loaded(self):
        return not self.player.source().isEmpty()


class AddMonitorRow(QWidget):
    """添加监控点的行控件"""
    add_completed = Signal(dict)
    cancel = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_table = parent
        self.setStyleSheet("""
            QWidget {
                background-color: #2a2a3a;
                border-radius: 4px;
            }
            QLabel { 
                color: #e0e0e0;
                font-size: 12px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #3d3d4d;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 12px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #4a9eff;
            }
            QPushButton {
                background-color: #4a4a5a;
                color: #e0e0e0;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #5a5a6a; }
            QPushButton#btn_pick {
                background-color: #4a9eff;
                color: #1a1a2a;
                font-weight: bold;
            }
            QPushButton#btn_pick:hover { background-color: #3a8eef; }
            QPushButton#btn_ok {
                background-color: #2a8a4a;
                color: white;
            }
            QPushButton#btn_ok:hover { background-color: #3a9a5a; }
            QPushButton#btn_cancel {
                background-color: #aa3a3a;
                color: white;
            }
            QPushButton#btn_cancel:hover { background-color: #bb4a4a; }
        """)
        
        layout = QHBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # 名称
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("名称")
        self.name_edit.setFixedWidth(70)
        layout.addWidget(self.name_edit)
        
        # X坐标
        self.x_edit = QSpinBox()
        self.x_edit.setRange(0, 9999)
        self.x_edit.setValue(100)
        self.x_edit.setFixedWidth(50)
        layout.addWidget(QLabel("X:"))
        layout.addWidget(self.x_edit)
        
        # Y坐标
        self.y_edit = QSpinBox()
        self.y_edit.setRange(0, 9999)
        self.y_edit.setValue(100)
        self.y_edit.setFixedWidth(50)
        layout.addWidget(QLabel("Y:"))
        layout.addWidget(self.y_edit)
        
        # 宽度
        self.w_edit = QSpinBox()
        self.w_edit.setRange(10, 9999)
        self.w_edit.setValue(150)
        self.w_edit.setFixedWidth(50)
        layout.addWidget(QLabel("W:"))
        layout.addWidget(self.w_edit)
        
        # 高度
        self.h_edit = QSpinBox()
        self.h_edit.setRange(10, 9999)
        self.h_edit.setValue(60)
        self.h_edit.setFixedWidth(50)
        layout.addWidget(QLabel("H:"))
        layout.addWidget(self.h_edit)
        
        # 拾取按钮
        self.btn_pick = QPushButton("拾取")
        self.btn_pick.setObjectName("btn_pick")
        self.btn_pick.clicked.connect(self.start_pick)
        layout.addWidget(self.btn_pick)
        
        # 下限
        self.lower_edit = QDoubleSpinBox()
        self.lower_edit.setRange(-99999, 99999)
        self.lower_edit.setValue(0)
        self.lower_edit.setFixedWidth(60)
        layout.addWidget(QLabel("下限:"))
        layout.addWidget(self.lower_edit)
        
        # 上限
        self.upper_edit = QDoubleSpinBox()
        self.upper_edit.setRange(-99999, 99999)
        self.upper_edit.setValue(100)
        self.upper_edit.setFixedWidth(60)
        layout.addWidget(QLabel("上限:"))
        layout.addWidget(self.upper_edit)
        
        # 确定/取消
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("btn_ok")
        self.btn_ok.clicked.connect(self.confirm_add)
        layout.addWidget(self.btn_ok)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.cancel.emit)
        layout.addWidget(self.btn_cancel)
        
        # 拾取状态
        self.pick_stage = 0
        self.temp_x = 0
        self.temp_y = 0
        self.picker = None
        
        self.name_edit.setFocus()
    
    def start_pick(self):
        """开始拾取 - 第一步：左上角"""
        self.pick_stage = 1
        self.btn_pick.setText("拾取左上角...")
        self.btn_pick.setEnabled(False)
        self.picker = CoordinatePicker(self, "左上角")
        self.picker.coord_selected.connect(self.on_first_pick)
    
    def on_first_pick(self, x, y):
        if x >= 0 and y >= 0:
            self.temp_x = x
            self.temp_y = y
            self.pick_stage = 2
            self.btn_pick.setText("拾取右下角...")
            self.btn_pick.setEnabled(True)
            QTimer.singleShot(200, self.pick_bottom_right)
        else:
            self.pick_stage = 0
            self.btn_pick.setText("拾取")
            self.btn_pick.setEnabled(True)
            self.picker = None
    
    def pick_bottom_right(self):
        if self.pick_stage == 2:
            self.picker = CoordinatePicker(self, "右下角")
            self.picker.coord_selected.connect(self.on_second_pick)
    
    def on_second_pick(self, x, y):
        if x >= 0 and y >= 0 and self.temp_x >= 0 and self.temp_y >= 0:
            width = x - self.temp_x
            height = y - self.temp_y
            if width > 0 and height > 0:
                self.x_edit.setValue(self.temp_x)
                self.y_edit.setValue(self.temp_y)
                self.w_edit.setValue(width)
                self.h_edit.setValue(height)
            else:
                QMessageBox.warning(self, "提示", "右下角必须在左上角的右下方！")
        
        self.pick_stage = 0
        self.btn_pick.setText("拾取")
        self.btn_pick.setEnabled(True)
        self.picker = None
    
    def confirm_add(self):
        """确认添加"""
        name = self.name_edit.text().strip() or "未命名"
        data = {
            'name': name,
            'x': self.x_edit.value(),
            'y': self.y_edit.value(),
            'width': self.w_edit.value(),
            'height': self.h_edit.value(),
            'lower': self.lower_edit.value(),
            'upper': self.upper_edit.value()
        }
        self.add_completed.emit(data)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.resize(1200, 750)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1a1a2a; }
            QLabel { color: #e0e0e0; }
            QTableWidget {
                background-color: #1a1a2a;
                alternate-background-color: #2a2a3a;
                color: #e0e0e0;
                gridline-color: #3a3a4a;
                selection-background-color: #4a9eff;
                selection-color: #1a1a2a;
            }
            QTableWidget::item { padding: 4px; }
            QHeaderView::section {
                background-color: #2a2a3a;
                color: #e0e0e0;
                padding: 6px;
                border: 1px solid #3a3a4a;
            }
            QPushButton {
                background-color: #3a3a4a;
                color: #e0e0e0;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4a4a5a; }
            QPushButton#btn_start {
                background-color: #2a8a4a;
                color: white;
            }
            QPushButton#btn_start:hover { background-color: #3a9a5a; }
            QPushButton#btn_start:disabled {
                background-color: #3a3a4a;
                color: #6a6a7a;
            }
            QPushButton#btn_stop {
                background-color: #aa3a3a;
                color: white;
            }
            QPushButton#btn_stop:hover { background-color: #bb4a4a; }
            QPushButton#btn_stop:disabled {
                background-color: #3a3a4a;
                color: #6a6a7a;
            }
            QPushButton#btn_delete { background-color: #aa3a3a; }
            QPushButton#btn_delete:hover { background-color: #bb4a4a; }
            QPushButton#btn_save { background-color: #2a4a7a; }
            QPushButton#btn_save:hover { background-color: #3a5a8a; }
            QFrame#hint_frame {
                background-color: #2a2a3a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #3a3a4a;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #4a9eff;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #4a9eff;
                border-radius: 3px;
            }
            QComboBox {
                background-color: #3d3d4d;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox:hover {
                border-color: #4a9eff;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a3a;
                color: #e0e0e0;
                selection-background-color: #4a9eff;
            }
        """)
        
        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.alarm_logs = []
        self.alarm_sound_on = True
        self.add_row_widget = None
        self.detect_interval = 500  # 默认500ms
        
        # 报警声音播放器
        self.alarm_player = AlarmSoundPlayer()
        self.alarm_file = ""
        self.alarm_playing = False
        
        # 创建UI
        self._setup_ui()
        self.load_config()
        
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)
        
        # 标题
        title_layout = QHBoxLayout()
        title = QLabel("📊 屏幕数字监控报警系统")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        subtitle = QLabel("-- 陈诚 (EasyOCR)")
        subtitle.setStyleSheet("color: #6a6a7a; font-size: 13px;")
        title_layout.addWidget(subtitle)
        main_layout.addLayout(title_layout)
        
        # 使用提示
        hint_frame = QFrame()
        hint_frame.setObjectName("hint_frame")
        hint_layout = QHBoxLayout(hint_frame)
        hint_layout.setContentsMargins(8, 4, 8, 4)
        hint_label = QLabel("💡 点击「拾取」依次点击左上角和右下角，自动计算宽高")
        hint_label.setStyleSheet("color: #ddaa44;")
        hint_layout.addWidget(hint_label)
        main_layout.addWidget(hint_frame)
        
        # OCR状态
        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 4px 12px; background-color: #2a2a3a; border-radius: 4px; color: #ddaa44;")
        main_layout.addWidget(self.ocr_status_label)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "名称", "当前值", "下限", "上限", "坐标 (X,Y,W,H)", "状态", "报警时间"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setRowCount(0)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 100)
        self.table.horizontalHeader().setStretchLastSection(True)
        main_layout.addWidget(self.table)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.btn_add = QPushButton("添加监控点")
        self.btn_add.clicked.connect(self.add_monitor_row)
        btn_layout.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        btn_layout.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("删除")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout.addWidget(self.btn_delete)
        
        btn_layout.addStretch()
        
        self.btn_start = QPushButton("开始监控")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("停止监控")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        btn_layout.addStretch()
        
        self.btn_clear_alarm = QPushButton("消除所有报警")
        self.btn_clear_alarm.clicked.connect(self.clear_all_alarms)
        btn_layout.addWidget(self.btn_clear_alarm)
        
        self.btn_sound = QPushButton("🔊 声音开启")
        self.btn_sound.clicked.connect(self.toggle_sound)
        btn_layout.addWidget(self.btn_sound)
        
        self.btn_load_sound = QPushButton("加载报警音频")
        self.btn_load_sound.clicked.connect(self.load_alarm_sound)
        btn_layout.addWidget(self.btn_load_sound)
        
        # 音量滑块
        btn_layout.addWidget(QLabel("音量:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        btn_layout.addWidget(self.volume_slider)
        
        # 检测间隔
        btn_layout.addWidget(QLabel("间隔:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["100ms", "200ms", "300ms", "500ms", "1000ms", "2000ms"])
        self.interval_combo.setCurrentIndex(3)  # 500ms
        self.interval_combo.setFixedWidth(80)
        self.interval_combo.currentTextChanged.connect(self.on_interval_changed)
        btn_layout.addWidget(self.interval_combo)
        
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_load = QPushButton("加载配置")
        self.btn_load.clicked.connect(self.load_config_dialog)
        btn_layout.addWidget(self.btn_load)
        
        main_layout.addLayout(btn_layout)
        
        # 状态栏
        status_layout = QHBoxLayout()
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setStyleSheet("padding: 6px; background-color: #2a2a3a; border-radius: 4px;")
        status_layout.addWidget(self.status_label, 2)
        
        self.alarm_count_label = QLabel("报警数: 0")
        self.alarm_count_label.setStyleSheet("padding: 6px; background-color: #2a2a3a; border-radius: 4px;")
        status_layout.addWidget(self.alarm_count_label, 1)
        
        self.alarm_status_label = QLabel("🔇 无报警")
        self.alarm_status_label.setStyleSheet("padding: 6px; background-color: #2a2a3a; border-radius: 4px; color: #6a6a7a;")
        status_layout.addWidget(self.alarm_status_label, 1)
        
        main_layout.addLayout(status_layout)
    
    def on_interval_changed(self, text):
        """检测间隔变化"""
        self.detect_interval = int(text.replace("ms", ""))
        if self.monitoring and self.monitor_thread:
            self.monitor_thread.set_interval(self.detect_interval)
    
    def on_volume_changed(self, value):
        """音量改变"""
        volume = value / 100.0
        self.alarm_player.set_volume(volume)
    
    def load_alarm_sound(self):
        """加载用户选择的音频文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择报警音频文件", "", 
            "音频文件 (*.wav *.mp3 *.flac *.ogg *.m4a);;所有文件 (*.*)"
        )
        if file_path:
            if self.alarm_player.load_sound(file_path):
                self.alarm_file = file_path
                self.status_label.setText(f"状态: 已加载报警音频: {os.path.basename(file_path)}")
                # 测试播放
                self.alarm_player.play()
                QTimer.singleShot(500, self.alarm_player.stop)
                self.save_config()
            else:
                QMessageBox.warning(self, "错误", 
                    "无法加载音频文件\n\n"
                    "支持格式: WAV, MP3, FLAC, OGG, M4A\n"
                    "提示: 如果加载MP3失败，请尝试转换为WAV格式"
                )
    
    def toggle_sound(self):
        """切换声音开关"""
        self.alarm_sound_on = not self.alarm_sound_on
        self.btn_sound.setText("🔊 声音开启" if self.alarm_sound_on else "🔇 声音关闭")
        if not self.alarm_sound_on:
            self.alarm_player.stop()
            self.alarm_playing = False
            self.alarm_status_label.setText("🔇 声音已关闭")
            self.alarm_status_label.setStyleSheet("padding: 6px; background-color: #2a2a3a; border-radius: 4px; color: #aa3a3a;")
    
    def play_alarm(self):
        """播放报警声音（循环）"""
        if not self.alarm_sound_on:
            return
        
        if self.alarm_player.is_loaded():
            self.alarm_player.play()
            self.alarm_playing = True
            self.alarm_status_label.setText("🔊 报警中... (循环)")
            self.alarm_status_label.setStyleSheet("padding: 6px; background-color: #aa3a3a; border-radius: 4px; color: white;")
        else:
            # 如果没加载音频文件，使用系统Beep
            try:
                import winsound
                winsound.Beep(800, 300)
                winsound.Beep(1000, 300)
            except:
                pass
    
    def stop_alarm(self):
        """停止报警声音"""
        if self.alarm_player.is_loaded():
            self.alarm_player.stop()
        self.alarm_playing = False
        self.alarm_status_label.setText("🔇 无报警")
        self.alarm_status_label.setStyleSheet("padding: 6px; background-color: #2a2a3a; border-radius: 4px; color: #6a6a7a;")
    
    def add_monitor_row(self):
        if self.add_row_widget:
            return
        
        self.btn_add.setEnabled(False)
        row = 0
        self.table.insertRow(row)
        self.table.setRowHeight(row, 50)
        
        self.add_row_widget = AddMonitorRow(self.table)
        self.add_row_widget.add_completed.connect(self.on_add_completed)
        self.add_row_widget.cancel.connect(self.on_add_canceled)
        
        self.table.setCellWidget(row, 0, self.add_row_widget)
        self.table.setSpan(row, 0, 1, 7)
        self.table.scrollToTop()
    
    def on_add_completed(self, data):
        self.table.removeRow(0)
        self.add_row_widget = None
        self.btn_add.setEnabled(True)
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(data['name']))
        self.table.setItem(row, 1, QTableWidgetItem("--"))
        self.table.setItem(row, 2, QTableWidgetItem(str(data['lower'])))
        self.table.setItem(row, 3, QTableWidgetItem(str(data['upper'])))
        self.table.setItem(row, 4, QTableWidgetItem(f"{data['x']},{data['y']},{data['width']},{data['height']}"))
        self.table.setItem(row, 5, QTableWidgetItem("待监控"))
        self.table.setItem(row, 6, QTableWidgetItem("--"))
        
        self.status_label.setText(f"状态: 已添加 [{data['name']}]")
    
    def on_add_canceled(self):
        self.table.removeRow(0)
        self.add_row_widget = None
        self.btn_add.setEnabled(True)
        self.status_label.setText("状态: 已取消添加")
    
    def edit_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        if self.table.cellWidget(row, 0) is not None:
            return
        
        name = self.table.item(row, 0).text()
        lower = float(self.table.item(row, 2).text())
        upper = float(self.table.item(row, 3).text())
        coords = self.table.item(row, 4).text()
        nums = re.findall(r'\d+', coords)
        if len(nums) >= 4:
            x, y, w, h = map(int, nums[:4])
        else:
            x, y, w, h = 100, 100, 150, 60
        
        if self.add_row_widget:
            return
        
        self.btn_add.setEnabled(False)
        self.table.removeRow(row)
        self.table.insertRow(row)
        self.table.setRowHeight(row, 50)
        
        self.add_row_widget = AddMonitorRow(self.table)
        self.add_row_widget.add_completed.connect(lambda data: self.on_edit_completed(row, data))
        self.add_row_widget.cancel.connect(self.on_edit_canceled)
        
        self.add_row_widget.name_edit.setText(name)
        self.add_row_widget.x_edit.setValue(x)
        self.add_row_widget.y_edit.setValue(y)
        self.add_row_widget.w_edit.setValue(w)
        self.add_row_widget.h_edit.setValue(h)
        self.add_row_widget.lower_edit.setValue(lower)
        self.add_row_widget.upper_edit.setValue(upper)
        
        self.table.setCellWidget(row, 0, self.add_row_widget)
        self.table.setSpan(row, 0, 1, 7)
    
    def on_edit_completed(self, row, data):
        self.table.removeRow(row)
        self.add_row_widget = None
        self.btn_add.setEnabled(True)
        
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(data['name']))
        self.table.setItem(row, 1, QTableWidgetItem("--"))
        self.table.setItem(row, 2, QTableWidgetItem(str(data['lower'])))
        self.table.setItem(row, 3, QTableWidgetItem(str(data['upper'])))
        self.table.setItem(row, 4, QTableWidgetItem(f"{data['x']},{data['y']},{data['width']},{data['height']}"))
        self.table.setItem(row, 5, QTableWidgetItem("待监控"))
        self.table.setItem(row, 6, QTableWidgetItem("--"))
        self.status_label.setText(f"状态: 已编辑 [{data['name']}]")
    
    def on_edit_canceled(self):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) == self.add_row_widget:
                self.table.removeRow(row)
                break
        self.add_row_widget = None
        self.btn_add.setEnabled(True)
        self.status_label.setText("状态: 已取消编辑")
        self.load_config()
    
    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        if self.table.cellWidget(row, 0) is not None:
            return
        
        name = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 [{name}] 吗？")
        if reply == QMessageBox.Yes:
            self.table.removeRow(row)
            self.status_label.setText("状态: 已删除")
    
    def set_ocr_status(self, status, is_ready=False):
        color = "#44ddaa" if is_ready else "#ddaa44"
        self.ocr_status_label.setStyleSheet(
            f"padding: 4px 12px; background-color: #2a2a3a; border-radius: 4px; color: {color};"
        )
        self.ocr_status_label.setText(f"OCR引擎: {status}")
    
    def start_monitor(self):
        if self.monitoring:
            return
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先添加监控点")
            return
        
        monitors = []
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is not None:
                continue
            name = self.table.item(row, 0).text()
            lower = float(self.table.item(row, 2).text())
            upper = float(self.table.item(row, 3).text())
            coords = self.table.item(row, 4).text()
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
                'row': row
            })
        
        if not monitors:
            QMessageBox.warning(self, "提示", "没有有效的监控点")
            return
        
        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.set_interval(self.detect_interval)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.ocr_status.connect(self.set_ocr_status)
        self.monitor_thread.start()
        
        self.monitoring = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("状态: 监控运行中")
    
    def stop_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        self.monitoring = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("状态: 已停止")
        
        self.stop_alarm()
        
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is None:
                item = self.table.item(row, 5)
                if item and "报警" not in item.text():
                    self.table.setItem(row, 5, QTableWidgetItem("已停止"))
    
    def on_value_updated(self, row, value):
        self.table.setItem(row, 1, QTableWidgetItem(f"{value:.2f}"))
    
    def on_alarm_triggered(self, row, name, value, lower, upper):
        status_item = QTableWidgetItem("报警")
        status_item.setBackground(QBrush(QColor(200, 50, 50)))
        status_item.setForeground(QBrush(QColor(255, 255, 255)))
        self.table.setItem(row, 5, status_item)
        
        now = datetime.now().strftime("%H:%M:%S")
        self.table.setItem(row, 6, QTableWidgetItem(now))
        
        self._update_alarm_count()
        self.status_label.setText(f"报警: {name} = {value:.2f} [范围: {lower}-{upper}]")
        
        self.play_alarm()
        
        with open("alarm_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{now}] 报警: {name} = {value:.2f} 超出范围 [{lower}, {upper}]\n")
    
    def on_status_updated(self, row, status):
        if status == 'normal':
            status_item = QTableWidgetItem("正常")
            status_item.setBackground(QBrush(QColor(50, 150, 50)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
        elif status == 'error':
            status_item = QTableWidgetItem("识别失败")
            status_item.setBackground(QBrush(QColor(100, 100, 100)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
        else:
            status_item = QTableWidgetItem(status)
        self.table.setItem(row, 5, status_item)
    
    def clear_all_alarms(self):
        count = 0
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is not None:
                continue
            item = self.table.item(row, 5)
            if item and item.text() == "报警":
                status_item = QTableWidgetItem("正常")
                status_item.setBackground(QBrush(QColor(50, 150, 50)))
                status_item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(row, 5, status_item)
                self.table.setItem(row, 6, QTableWidgetItem("--"))
                count += 1
        
        if count > 0:
            self.stop_alarm()
        
        self._update_alarm_count()
        if count > 0:
            self.status_label.setText(f"状态: 已消除 {count} 个报警")
        else:
            QMessageBox.information(self, "提示", "没有报警需要消除")
    
    def _update_alarm_count(self):
        count = 0
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is not None:
                continue
            item = self.table.item(row, 5)
            if item and item.text() == "报警":
                count += 1
        self.alarm_count_label.setText(f"报警数: {count}")
    
    def _update_status_display(self):
        if self.monitoring:
            self.status_label.setText("状态: 监控运行中")
    
    def save_config(self):
        config = {
            'monitors': [],
            'alarm_file': self.alarm_file,
            'volume': self.volume_slider.value(),
            'interval': self.interval_combo.currentText()
        }
        
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0) is not None:
                continue
            config['monitors'].append({
                'name': self.table.item(row, 0).text(),
                'lower': float(self.table.item(row, 2).text()),
                'upper': float(self.table.item(row, 3).text()),
                'coords': self.table.item(row, 4).text()
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
            
            self.table.setRowCount(0)
            for item in config.get('monitors', []):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(item['name']))
                self.table.setItem(row, 1, QTableWidgetItem("--"))
                self.table.setItem(row, 2, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 3, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 4, QTableWidgetItem(item['coords']))
                self.table.setItem(row, 5, QTableWidgetItem("待监控"))
                self.table.setItem(row, 6, QTableWidgetItem("--"))
            
            # 加载音频文件
            alarm_file = config.get('alarm_file', '')
            if alarm_file and os.path.exists(alarm_file):
                if self.alarm_player.load_sound(alarm_file):
                    self.alarm_file = alarm_file
                    self.status_label.setText("状态: 已加载报警音频")
            
            # 加载音量
            volume = config.get('volume', 100)
            self.volume_slider.setValue(volume)
            self.on_volume_changed(volume)
            
            # 加载间隔
            interval = config.get('interval', '500ms')
            idx = self.interval_combo.findText(interval)
            if idx >= 0:
                self.interval_combo.setCurrentIndex(idx)
                self.detect_interval = int(interval.replace("ms", ""))
            
            self.status_label.setText("状态: 配置已加载")
        except Exception as e:
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
