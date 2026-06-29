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
    QPainterPath, QLinearGradient
)
from monitor import MonitorThread

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# ---------- 类定义（AlarmSoundPlayer, CoordinatePicker, MiniWindow, TrendChartWidget）与之前完全相同，省略----------
# 为保持完整，实际使用时请保留原文件中的完整定义。

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
            QPushButton#btn_start_stop {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2e9a58, stop:1 #258048);
                color: white;
            }
            QPushButton#btn_start_stop:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #38ad64, stop:1 #2d9052); }
            QPushButton#btn_start_stop:disabled {
                background-color: #3a3a50;
                color: #7a7a9a;
            }
            QPushButton#btn_delete { background-color: #b03a3a; }
            QPushButton#btn_delete:hover { background-color: #c44a4a; }
            QPushButton#btn_save { background-color: #2a5a9a; }
            QPushButton#btn_save:hover { background-color: #356ab0; }
            QPushButton#btn_mini { background-color: #4a6a8a; }
            QPushButton#btn_mini:hover { background-color: #5a7a9a; }
            QPushButton#btn_chart_toggle { background-color: #4a4a6a; }
            QPushButton#btn_chart_toggle:hover { background-color: #5a5a7a; }
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
            QDoubleSpinBox {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 20px;
            }
            QDoubleSpinBox:hover { border-color: #4a9eff; }
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
            QCheckBox { color: #e0e0f0; font-family: "Microsoft YaHei"; font-size: 13px; }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
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
            QLineEdit {
                background-color: #363650;
                color: #e0e0f0;
                border: 1px solid #4a4a6a;
                border-radius: 4px;
                padding: 2px 6px;
            }
            QLineEdit:focus { border-color: #4a9eff; }
        """)

        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.loop_enabled = True
        self.detect_interval = 500
        self.value_history = {}
        self.current_row_data = []

        self.alarm_player = AlarmSoundPlayer()
        self.alarm_file = self.alarm_player.sound_file or ""
        self.alarm_playing = False

        self.row_enabled = {}
        self.row_alarm = {}
        self.row_muted = {}
        self.row_sensitivity = {}

        self._setup_ui()
        self.load_config()

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)

        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        QTimer.singleShot(200, self._init_ocr_reader)

    # ---------- 以下为与原代码相同的部分，省略（但实际需保留完整） ----------
    # 为节省篇幅，省略了 _init_ocr_reader, _on_reader_loaded,
    # create_sensitivity_widget, on_row_sensitivity_changed, get_row_sensitivity,
    # _setup_ui, clear_alarm_time, toggle_chart, toggle_mini_mode, ... 等全部方法。
    # 仅显示修改的 start_monitor, stop_monitor, 以及新增的 toggle_monitor 和 _setup_ui 中的按钮部分。

    # 但为了可运行，此处必须包含所有方法。以下是改动部分：

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        title_layout = QHBoxLayout()
        title = QLabel("📊 屏幕数字监控报警系统")
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
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 80)
        self.table.setColumnWidth(8, 100)
        self.table.setColumnWidth(9, 50)
        self.table.setColumnWidth(10, 120)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table, 3)

        self.chart_group = QGroupBox("📈 数值趋势曲线")
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
        self.record_interval_spin.setFixedWidth(90)
        self.record_interval_spin.valueChanged.connect(self.set_record_interval)
        settings_layout.addWidget(self.record_interval_spin)
        settings_layout.addWidget(QLabel("检测间隔:"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 3600.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setValue(0.5)
        self.interval_spin.setFixedWidth(80)
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
        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout_top.addWidget(self.btn_delete)
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        btn_layout_top.addWidget(self.btn_edit)
        self.btn_test = QPushButton("🎯 测试")
        self.btn_test.clicked.connect(self.test_selected_point)
        btn_layout_top.addWidget(self.btn_test)

        # ---------- 合并后的开始/停止按钮 ----------
        self.btn_start_stop = QPushButton("▶ 开始监控")
        self.btn_start_stop.setObjectName("btn_start_stop")
        self.btn_start_stop.clicked.connect(self.toggle_monitor)
        btn_layout_top.addWidget(self.btn_start_stop)

        main_layout.addLayout(btn_layout_top)

        btn_layout_bottom = QHBoxLayout()
        btn_layout_bottom.setSpacing(10)
        btn_layout_bottom.setAlignment(Qt.AlignLeft)
        self.btn_mini = QPushButton("📱 小窗口")
        self.btn_mini.setObjectName("btn_mini")
        self.btn_mini.clicked.connect(self.toggle_mini_mode)
        btn_layout_bottom.addWidget(self.btn_mini)
        self.btn_chart_toggle = QPushButton("📉 收起曲线")
        self.btn_chart_toggle.setObjectName("btn_chart_toggle")
        self.btn_chart_toggle.clicked.connect(self.toggle_chart)
        btn_layout_bottom.addWidget(self.btn_chart_toggle)
        self.btn_clear_time = QPushButton("🗑 清空报警时间")
        self.btn_clear_time.clicked.connect(self.clear_alarm_time)
        btn_layout_bottom.addWidget(self.btn_clear_time)
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout_bottom.addWidget(self.btn_save)
        self.btn_load = QPushButton("📂 加载配置")
        self.btn_load.clicked.connect(self.load_config_dialog)
        btn_layout_bottom.addWidget(self.btn_load)
        main_layout.addLayout(btn_layout_bottom)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; border: 1px solid #33334a;")
        status_layout.addWidget(self.status_label, 1)
        self.alarm_status_label = QLabel("🔇 无报警")
        self.alarm_status_label.setStyleSheet("padding: 8px 12px; background-color: #27273d; border-radius: 6px; color: #7a7a9a; border: 1px solid #33334a;")
        status_layout.addWidget(self.alarm_status_label, 1)
        main_layout.addLayout(status_layout)

        self.table.model().rowsInserted.connect(self._on_rows_inserted)
        self.table.model().rowsRemoved.connect(self._on_rows_removed)

    # ---------- 新增切换方法 ----------
    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

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
            lower = float(self.table.item(row, 4).text())
            upper = float(self.table.item(row, 5).text())
            coords = self.table.item(row, 6).text()
            nums = re.findall(r'\d+', coords)
            if len(nums) >= 4:
                x, y, w, h = map(int, nums[:4])
            else:
                continue
            sens = self.get_row_sensitivity(row)
            monitors.append({
                'name': name,
                'x': x, 'y': y,
                'width': w, 'height': h,
                'lower': lower, 'upper': upper,
                'row': row,
                'enabled': self._get_row_enabled(row),
                'sensitivity': sens
            })

        if not monitors:
            QMessageBox.warning(self, "提示", "没有有效的监控点数据")
            return

        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.set_interval(self.detect_interval)
        self.monitor_thread.set_alarm_loop(self.loop_enabled)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.ocr_status.connect(self.set_ocr_status)
        self.monitor_thread.download_progress.connect(self.on_download_progress)
        if self.test_reader is not None:
            self.monitor_thread.set_reader(self.test_reader)
        self.monitor_thread.get_row_enabled = self._get_row_enabled
        self.monitor_thread.start()

        self.monitoring = True
        self.btn_start_stop.setText("⏹ 停止监控")
        self.status_label.setText("状态: 监控运行中")
        self.recording = True
        self.record_timer.start(int(self.record_interval * 1000))

    def stop_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        self.recording = False
        self.record_timer.stop()
        self.monitoring = False
        self.btn_start_stop.setText("▶ 开始监控")
        self.status_label.setText("状态: 已停止")
        self.stop_alarm()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 7)
            if item and item.text() not in ["报警", "已静音"]:
                self.table.setItem(row, 7, QTableWidgetItem("已停止"))
            self.row_alarm[row] = False
            self._reset_row_colors(row)

    # ---------- 其余方法（load_config, save_config, add_monitor_row, 等）与原代码完全相同，此处省略 ----------
    # 完整代码请参考原文件，只需替换上述三个方法即可。

# 注意：由于篇幅，以上仅列出改动部分。实际完整文件需要保留所有未改动的方法。
# 建议您直接替换 _setup_ui、start_monitor、stop_monitor 三个方法，并添加 toggle_monitor 方法。
