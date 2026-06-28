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


class AlarmSoundPlayer:
    # ... 保持原样（省略，实际使用请复制之前完整代码）


class CoordinatePicker:
    # ... 保持原样


class MiniWindow:
    # ... 保持原样


class TrendChartWidget:
    # ... 保持原样


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

        # 样式表：删除 #btn_clear_time 特殊样式，删除音量相关样式
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
            QPushButton#btn_mini { background-color: #4a6a8a; }
            QPushButton#btn_mini:hover { background-color: #5a7a9a; }
            QPushButton#btn_chart_toggle { background-color: #4a4a6a; }
            QPushButton#btn_chart_toggle:hover { background-color: #5a5a7a; }
            /* 清空报警时间使用普通按钮样式，不再单独定义 */
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

    # ---------- 辅助方法 ----------
    def _init_ocr_reader(self):
        # ... 与之前相同

    def _on_reader_loaded(self, reader):
        # ... 与之前相同

    def create_sensitivity_widget(self, row, value=5):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(1, 10)
        slider.setValue(value)
        slider.setFixedWidth(60)
        slider.valueChanged.connect(lambda v, r=row: self.on_row_sensitivity_changed(r, v))
        label = QLabel(str(value))
        label.setFixedWidth(20)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(slider)
        layout.addWidget(label)
        widget.slider = slider
        widget.label = label
        widget.row = row
        return widget

    def on_row_sensitivity_changed(self, row, value):
        widget = self.table.cellWidget(row, 10)
        if widget and hasattr(widget, 'label'):
            widget.label.setText(str(value))
        self.row_sensitivity[row] = value
        if self.monitoring and self.monitor_thread is not None:
            for m in self.monitor_thread.monitors:
                if m['row'] == row:
                    m['sensitivity'] = value
                    break

    def get_row_sensitivity(self, row):
        return self.row_sensitivity.get(row, 5)

    # ---------- UI 布局 ----------
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # 标题
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

        # OCR状态
        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 6px 14px; background-color: #2a2a42; border-radius: 6px; color: #e6b84d; border: 1px solid #3a3a55;")
        main_layout.addWidget(self.ocr_status_label)

        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        main_layout.addWidget(self.download_progress)

        # 表格（11列）
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

        # ---------- 数值趋势曲线组框（包含曲线、记录间隔、检测间隔） ----------
        self.chart_group = QGroupBox("📈 数值趋势曲线")
        chart_layout = QVBoxLayout(self.chart_group)
        chart_layout.setContentsMargins(12, 18, 12, 12)

        self.trend_chart = TrendChartWidget()
        chart_layout.addWidget(self.trend_chart, 1)

        # 设置行：记录间隔 + 检测间隔（靠左）
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

        settings_layout.addStretch()  # 保证靠左
        chart_layout.addLayout(settings_layout)

        main_layout.addWidget(self.chart_group, 2)

        # ---------- 第一排按钮（全部靠左） ----------
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

        self.btn_start = QPushButton("▶ 开始")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout_top.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)
        btn_layout_top.addWidget(self.btn_stop)

        main_layout.addLayout(btn_layout_top)

        # ---------- 第二排按钮（全部靠左） ----------
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

        # 清空报警时间（使用普通按钮样式）
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

        # 状态栏
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

    # ---------- 以下功能方法（与之前相同，仅保持完整性） ----------
    # 由于代码很长，此处省略，实际使用请复制之前完整的功能方法。
    # 包括：clear_alarm_time, toggle_chart, toggle_mini_mode, show_mini_mode,
    # show_normal_mode, _update_mini_alarm, _on_selection_changed,
    # _on_table_item_changed, _on_rows_inserted, _on_rows_removed,
    # _get_row_enabled, _is_row_muted, _on_mute_changed, _check_alarms,
    # on_interval_changed, play_alarm, stop_alarm, on_download_progress,
    # add_monitor_row, _on_picker_completed, _on_enable_changed,
    # edit_monitor_point, _on_edit_picker_completed, delete_monitor_point,
    # set_record_interval, record_current_value, test_selected_point,
    # set_ocr_status, start_monitor, stop_monitor, _reset_row_colors,
    # on_value_updated, on_alarm_triggered, on_status_updated,
    # _update_status_display, save_config, load_config, load_config_dialog,
    # closeEvent
    #
    # 注意：这些方法必须完整复制，此处仅为占位，实际替换时必须包含完整实现。
    # 建议使用之前回答中的完整代码，仅替换 _setup_ui 部分。

# 如果觉得代码太长，可以直接用之前提供的完整版本，仅修改 _setup_ui 部分。
# 但为方便，这里不重复全部方法，确保最终代码完整。


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
