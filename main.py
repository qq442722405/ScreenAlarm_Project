import sys
import json
import os
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QDialogButtonBox, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QTabWidget, QTextEdit, QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QBrush, QFont

# 导入监控线程
from monitor import MonitorThread
# 导入屏幕区域选择器
from selector import ScreenSelector


class AddMonitorDialog(QDialog):
    """添加监控点对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加监控点")
        self.setModal(True)
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e2e;
            }
            QLabel {
                color: #cdd6f4;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 6px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #89b4fa;
            }
            QGroupBox {
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
            QPushButton[text="确定"] {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
            QPushButton[text="确定"]:hover {
                background-color: #74c7ec;
            }
            QPushButton#btn_select_area {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                padding: 8px;
            }
            QPushButton#btn_select_area:hover {
                background-color: #74c7ec;
            }
        """)
        
        layout = QFormLayout(self)
        layout.setSpacing(12)
        
        # 名称
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：温度表")
        layout.addRow("📝 名称:", self.name_edit)
        
        # 区域坐标 - 添加"选择区域"按钮
        coord_group = QGroupBox("📐 屏幕区域")
        coord_layout = QGridLayout()
        coord_layout.setSpacing(8)
        
        # X, Y
        self.x_edit = QSpinBox()
        self.x_edit.setRange(0, 9999)
        self.x_edit.setValue(100)
        coord_layout.addWidget(QLabel("X:"), 0, 0)
        coord_layout.addWidget(self.x_edit, 0, 1)
        
        self.y_edit = QSpinBox()
        self.y_edit.setRange(0, 9999)
        self.y_edit.setValue(100)
        coord_layout.addWidget(QLabel("Y:"), 0, 2)
        coord_layout.addWidget(self.y_edit, 0, 3)
        
        # 宽度, 高度
        self.w_edit = QSpinBox()
        self.w_edit.setRange(10, 9999)
        self.w_edit.setValue(150)
        coord_layout.addWidget(QLabel("宽度:"), 1, 0)
        coord_layout.addWidget(self.w_edit, 1, 1)
        
        self.h_edit = QSpinBox()
        self.h_edit.setRange(10, 9999)
        self.h_edit.setValue(60)
        coord_layout.addWidget(QLabel("高度:"), 1, 2)
        coord_layout.addWidget(self.h_edit, 1, 3)
        
        # 选择区域按钮（占满一行）
        self.btn_select_area = QPushButton("🖱 在屏幕上框选区域")
        self.btn_select_area.setObjectName("btn_select_area")
        self.btn_select_area.clicked.connect(self.select_screen_area)
        coord_layout.addWidget(self.btn_select_area, 2, 0, 1, 4)
        
        coord_group.setLayout(coord_layout)
        layout.addRow(coord_group)
        
        # 报警阈值
        threshold_group = QGroupBox("🔔 报警阈值")
        threshold_layout = QGridLayout()
        threshold_layout.setSpacing(8)
        
        self.lower_edit = QDoubleSpinBox()
        self.lower_edit.setRange(-99999, 99999)
        self.lower_edit.setValue(0)
        threshold_layout.addWidget(QLabel("下限:"), 0, 0)
        threshold_layout.addWidget(self.lower_edit, 0, 1)
        
        self.upper_edit = QDoubleSpinBox()
        self.upper_edit.setRange(-99999, 99999)
        self.upper_edit.setValue(100)
        threshold_layout.addWidget(QLabel("上限:"), 0, 2)
        threshold_layout.addWidget(self.upper_edit, 0, 3)
        
        threshold_group.setLayout(threshold_layout)
        layout.addRow(threshold_group)
        
        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        # 保存选择器引用
        self.selector = None
    
    def select_screen_area(self):
        """打开屏幕区域选择器"""
        self.hide()  # 隐藏对话框
        
        # 创建选择器
        self.selector = ScreenSelector()
        self.selector.area_selected.connect(self.on_area_selected)
        self.selector.showFullScreen()
        
        # 确保选择器在最前面
        self.selector.raise_()
        self.selector.activateWindow()
        self.selector.setFocus(Qt.OtherFocusReason)
    
    def on_area_selected(self, x, y, width, height):
        """接收选择结果"""
        if width > 0 and height > 0:
            self.x_edit.setValue(x)
            self.y_edit.setValue(y)
            self.w_edit.setValue(width)
            self.h_edit.setValue(height)
        
        # 显示对话框
        self.show()
        self.raise_()
        self.activateWindow()
        self.selector = None
    
    def get_data(self):
        return {
            'name': self.name_edit.text().strip() or "未命名",
            'x': self.x_edit.value(),
            'y': self.y_edit.value(),
            'width': self.w_edit.value(),
            'height': self.h_edit.value(),
            'lower': self.lower_edit.value(),
            'upper': self.upper_edit.value()
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警 -- 陈诚")
        self.resize(1200, 750)
        
        # 设置样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QLabel {
                color: #cdd6f4;
            }
            QTableWidget {
                background-color: #1e1e2e;
                alternate-background-color: #313244;
                color: #cdd6f4;
                gridline-color: #45475a;
                selection-background-color: #89b4fa;
                selection-color: #1e1e2e;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
            QHeaderView::section {
                background-color: #313244;
                color: #cdd6f4;
                padding: 8px;
                border: 1px solid #45475a;
            }
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
            QPushButton:pressed {
                background-color: #313244;
            }
            QPushButton#btn_start {
                background-color: #26a269;
                color: white;
            }
            QPushButton#btn_start:hover {
                background-color: #2ec27e;
            }
            QPushButton#btn_start:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
            QPushButton#btn_stop {
                background-color: #c64640;
                color: white;
            }
            QPushButton#btn_stop:hover {
                background-color: #e64553;
            }
            QPushButton#btn_stop:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
            QPushButton#btn_delete {
                background-color: #c64640;
            }
            QPushButton#btn_delete:hover {
                background-color: #e64553;
            }
            QPushButton#btn_save {
                background-color: #2a5c8a;
            }
            QPushButton#btn_save:hover {
                background-color: #3584e4;
            }
            QTextEdit {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
            }
            QGroupBox {
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QTabWidget::pane {
                border: 1px solid #45475a;
                border-radius: 6px;
                background-color: #1e1e2e;
            }
            QTabBar::tab {
                background-color: #313244;
                color: #cdd6f4;
                padding: 8px 16px;
                border: 1px solid #45475a;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #45475a;
            }
            QTabBar::tab:hover {
                background-color: #585b70;
            }
        """)
        
        # 状态变量
        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.alarm_logs = []
        
        # 创建UI
        self._setup_ui()
        
        # 加载配置
        self.load_config()
        
        # 定时器更新状态
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status_display)
        self.status_timer.start(500)
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # 标题栏
        title_layout = QHBoxLayout()
        
        title = QLabel("📊 屏幕数字监控报警系统")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        
        title_layout.addStretch()
        
        subtitle = QLabel("-- 陈诚  (EasyOCR引擎)")
        subtitle.setStyleSheet("color: #6c7086; font-size: 14px;")
        title_layout.addWidget(subtitle)
        
        main_layout.addLayout(title_layout)
        
        # OCR初始化状态
        self.ocr_status_label = QLabel("🔧 OCR引擎状态: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 6px 12px; background-color: #313244; border-radius: 4px; color: #f9e2af;")
        main_layout.addWidget(self.ocr_status_label)
        
        # 标签页
        tabs = QTabWidget()
        
        # 监控标签页
        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "名称", "当前值", "下限", "上限", 
            "坐标 (X,Y,W,H)", "状态", "最近报警"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setRowCount(0)
        monitor_layout.addWidget(self.table)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.btn_add = QPushButton("➕ 添加监控点")
        self.btn_add.clicked.connect(self.add_monitor_point)
        btn_layout.addWidget(self.btn_add)
        
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_edit.clicked.connect(self.edit_monitor_point)
        btn_layout.addWidget(self.btn_edit)
        
        self.btn_delete = QPushButton("🗑️ 删除")
        self.btn_delete.setObjectName("btn_delete")
        self.btn_delete.clicked.connect(self.delete_monitor_point)
        btn_layout.addWidget(self.btn_delete)
        
        btn_layout.addStretch()
        
        self.btn_start = QPushButton("▶️ 开始监控")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("⏹️ 停止监控")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        btn_layout.addStretch()
        
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.clicked.connect(self.save_config)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_load = QPushButton("📂 加载配置")
        self.btn_load.clicked.connect(self.load_config_dialog)
        btn_layout.addWidget(self.btn_load)
        
        monitor_layout.addLayout(btn_layout)
        
        # 状态栏
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("状态：就绪")
        self.status_label.setStyleSheet("padding: 8px; background-color: #313244; border-radius: 4px;")
        status_layout.addWidget(self.status_label, 3)
        
        self.alarm_count_label = QLabel("🔴 报警数：0")
        self.alarm_count_label.setStyleSheet("padding: 8px; background-color: #313244; border-radius: 4px;")
        status_layout.addWidget(self.alarm_count_label, 1)
        
        monitor_layout.addLayout(status_layout)
        
        tabs.addTab(monitor_tab, "📊 监控")
        
        # 日志标签页
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        
        log_btn_layout = QHBoxLayout()
        log_btn_layout.addWidget(QLabel("📋 报警日志"))
        log_btn_layout.addStretch()
        
        self.btn_clear_logs = QPushButton("清空日志")
        self.btn_clear_logs.clicked.connect(self.clear_logs)
        log_btn_layout.addWidget(self.btn_clear_logs)
        
        log_layout.addLayout(log_btn_layout)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        tabs.addTab(log_tab, "📋 日志")
        
        main_layout.addWidget(tabs)
    
    def set_ocr_status(self, status, is_ready=False):
        """更新OCR状态显示"""
        if is_ready:
            self.ocr_status_label.setText(f"✅ OCR引擎状态: {status}")
            self.ocr_status_label.setStyleSheet("padding: 6px 12px; background-color: #313244; border-radius: 4px; color: #a6e3a1;")
        else:
            self.ocr_status_label.setText(f"⏳ OCR引擎状态: {status}")
            self.ocr_status_label.setStyleSheet("padding: 6px 12px; background-color: #313244; border-radius: 4px; color: #f9e2af;")
    
    def add_monitor_point(self):
        dialog = AddMonitorDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            self.table.setItem(row, 0, QTableWidgetItem(data['name']))
            self.table.setItem(row, 1, QTableWidgetItem("--"))
            self.table.setItem(row, 2, QTableWidgetItem(str(data['lower'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(data['upper'])))
            self.table.setItem(row, 4, QTableWidgetItem(f"{data['x']},{data['y']},{data['width']},{data['height']}"))
            self.table.setItem(row, 5, QTableWidgetItem("待监控"))
            self.table.setItem(row, 6, QTableWidgetItem("--"))
            
            self.status_label.setText(f"状态：已添加监控点 [{data['name']}]")
    
    def edit_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        
        name = self.table.item(row, 0).text()
        lower = float(self.table.item(row, 2).text())
        upper = float(self.table.item(row, 3).text())
        coords = self.table.item(row, 4).text().split(',')
        x, y, w, h = map(int, coords)
        
        dialog = AddMonitorDialog(self)
        dialog.name_edit.setText(name)
        dialog.x_edit.setValue(x)
        dialog.y_edit.setValue(y)
        dialog.w_edit.setValue(w)
        dialog.h_edit.setValue(h)
        dialog.lower_edit.setValue(lower)
        dialog.upper_edit.setValue(upper)
        
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.table.setItem(row, 0, QTableWidgetItem(data['name']))
            self.table.setItem(row, 2, QTableWidgetItem(str(data['lower'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(data['upper'])))
            self.table.setItem(row, 4, QTableWidgetItem(f"{data['x']},{data['y']},{data['width']},{data['height']}"))
            
            self.status_label.setText(f"状态：已编辑监控点 [{data['name']}]")
    
    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        
        name = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认删除", f"确定要删除监控点 [{name}] 吗？")
        if reply == QMessageBox.Yes:
            self.table.removeRow(row)
            self.status_label.setText("状态：监控点已删除")
    
    def start_monitor(self):
        if self.monitoring:
            return
        
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先添加监控点")
            return
        
        # 收集所有监控点配置
        monitors = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            lower = float(self.table.item(row, 2).text())
            upper = float(self.table.item(row, 3).text())
            coords = self.table.item(row, 4).text().split(',')
            x, y, w, h = map(int, coords)
            
            monitors.append({
                'name': name,
                'x': x, 'y': y, 'width': w, 'height': h,
                'lower': lower, 'upper': upper,
                'row': row
            })
        
        # 启动监控线程
        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.monitor_thread.status_updated.connect(self.on_status_updated)
        self.monitor_thread.ocr_status.connect(self.set_ocr_status)
        self.monitor_thread.start()
        
        self.monitoring = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("状态：监控运行中 🔴")
    
    def stop_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait()
        
        self.monitoring = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("状态：监控已停止")
        
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 5, QTableWidgetItem("已停止"))
    
    def on_value_updated(self, row, value):
        self.table.setItem(row, 1, QTableWidgetItem(f"{value:.2f}"))
    
    def on_alarm_triggered(self, row, name, value, lower, upper):
        status_item = QTableWidgetItem("🔴 报警")
        status_item.setBackground(QBrush(QColor(200, 50, 50)))
        status_item.setForeground(QBrush(QColor(255, 255, 255)))
        self.table.setItem(row, 5, status_item)
        
        now = datetime.now().strftime("%H:%M:%S")
        self.table.setItem(row, 6, QTableWidgetItem(now))
        
        self._update_alarm_count()
        
        log_entry = f"[{now}] ⚠️ 报警：{name} 数值 {value:.2f} 超出范围 [{lower}, {upper}]"
        self.alarm_logs.append(log_entry)
        self.log_text.append(log_entry)
        
        self.status_label.setText(f"⚠️ 报警：{name} 数值 {value:.2f} 超出范围 [{lower}, {upper}]")
    
    def on_status_updated(self, row, status):
        if status == 'normal':
            status_item = QTableWidgetItem("✅ 正常")
            status_item.setBackground(QBrush(QColor(50, 150, 50)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
        elif status == 'error':
            status_item = QTableWidgetItem("❌ 识别失败")
            status_item.setBackground(QBrush(QColor(100, 100, 100)))
            status_item.setForeground(QBrush(QColor(255, 255, 255)))
        else:
            status_item = QTableWidgetItem(status)
        self.table.setItem(row, 5, status_item)
    
    def _update_alarm_count(self):
        count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 5)
            if item and "报警" in item.text():
                count += 1
        self.alarm_count_label.setText(f"🔴 报警数：{count}")
    
    def _update_status_display(self):
        if self.monitoring:
            self.status_label.setText("状态：监控运行中 🔴")
    
    def clear_logs(self):
        self.alarm_logs = []
        self.log_text.clear()
    
    def save_config(self):
        config = []
        for row in range(self.table.rowCount()):
            config.append({
                'name': self.table.item(row, 0).text(),
                'lower': float(self.table.item(row, 2).text()),
                'upper': float(self.table.item(row, 3).text()),
                'coords': self.table.item(row, 4).text()
            })
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.status_label.setText("状态：配置已保存")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存配置失败：{e}")
    
    def load_config(self):
        if not os.path.exists(self.config_file):
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.table.setRowCount(0)
            for item in config:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(item['name']))
                self.table.setItem(row, 1, QTableWidgetItem("--"))
                self.table.setItem(row, 2, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 3, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 4, QTableWidgetItem(item['coords']))
                self.table.setItem(row, 5, QTableWidgetItem("待监控"))
                self.table.setItem(row, 6, QTableWidgetItem("--"))
            
            self.status_label.setText("状态：配置已加载")
        except Exception as e:
            print(f"加载配置失败：{e}")
    
    def load_config_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", "", "JSON文件 (*.json)"
        )
        if file_path:
            self.config_file = file_path
            self.load_config()
    
    def closeEvent(self, event):
        self.stop_monitor()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    
    win = MainWindow()
    win.show()
    
    sys.exit(app.exec())
