import sys
import json
import os
import winsound
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QDialogButtonBox, QFormLayout, QSpinBox, QDoubleSpinBox, QLineEdit,
    QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QBrush, QFont

from monitor import MonitorThread


class AddMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加监控点")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog { background-color: #2d2d3d; }
            QLabel { color: #e0e0e0; }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #3d3d4d;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border-color: #4a9eff;
            }
            QGroupBox {
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title { left: 10px; padding: 0 6px; }
            QPushButton {
                background-color: #4a4a5a;
                color: #e0e0e0;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #5a5a6a; }
            QPushButton[text="确定"] {
                background-color: #4a9eff;
                color: #1a1a2a;
            }
            QPushButton[text="确定"]:hover { background-color: #3a8eef; }
        """)
        
        layout = QFormLayout(self)
        layout.setSpacing(10)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：温度表")
        layout.addRow("名称:", self.name_edit)
        
        coord_group = QGroupBox("屏幕区域 (使用QQ截图查看坐标)")
        coord_layout = QGridLayout()
        coord_layout.setSpacing(6)
        
        self.x1_edit = QSpinBox()
        self.x1_edit.setRange(0, 9999)
        self.x1_edit.setValue(100)
        coord_layout.addWidget(QLabel("左上X:"), 0, 0)
        coord_layout.addWidget(self.x1_edit, 0, 1)
        
        self.y1_edit = QSpinBox()
        self.y1_edit.setRange(0, 9999)
        self.y1_edit.setValue(100)
        coord_layout.addWidget(QLabel("左上Y:"), 0, 2)
        coord_layout.addWidget(self.y1_edit, 0, 3)
        
        self.x2_edit = QSpinBox()
        self.x2_edit.setRange(0, 9999)
        self.x2_edit.setValue(250)
        coord_layout.addWidget(QLabel("右下X:"), 1, 0)
        coord_layout.addWidget(self.x2_edit, 1, 1)
        
        self.y2_edit = QSpinBox()
        self.y2_edit.setRange(0, 9999)
        self.y2_edit.setValue(160)
        coord_layout.addWidget(QLabel("右下Y:"), 1, 2)
        coord_layout.addWidget(self.y2_edit, 1, 3)
        
        coord_group.setLayout(coord_layout)
        layout.addRow(coord_group)
        
        threshold_group = QGroupBox("报警阈值")
        threshold_layout = QGridLayout()
        threshold_layout.setSpacing(6)
        
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
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def get_data(self):
        return {
            'name': self.name_edit.text().strip() or "未命名",
            'x1': self.x1_edit.value(),
            'y1': self.y1_edit.value(),
            'x2': self.x2_edit.value(),
            'y2': self.y2_edit.value(),
            'lower': self.lower_edit.value(),
            'upper': self.upper_edit.value()
        }


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.resize(1100, 700)
        
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
            QTableWidget::item { padding: 6px; }
            QHeaderView::section {
                background-color: #2a2a3a;
                color: #e0e0e0;
                padding: 8px;
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
        """)
        
        self.monitoring = False
        self.monitor_thread = None
        self.config_file = "monitor_config.json"
        self.alarm_logs = []
        self.alarm_sound_on = True
        
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
        
        # 提示：如何获取坐标
        hint_label = QLabel("💡 提示：使用QQ截图(Ctrl+Alt+A)可以查看鼠标坐标，填入左上角和右下角坐标即可")
        hint_label.setStyleSheet("color: #ddaa44; padding: 4px 8px; background-color: #2a2a3a; border-radius: 4px;")
        main_layout.addWidget(hint_label)
        
        # OCR状态
        self.ocr_status_label = QLabel("OCR引擎: 初始化中...")
        self.ocr_status_label.setStyleSheet("padding: 4px 12px; background-color: #2a2a3a; border-radius: 4px; color: #ddaa44;")
        main_layout.addWidget(self.ocr_status_label)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "名称", "当前值", "下限", "上限", "坐标区域", "状态", "报警时间"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setRowCount(0)
        main_layout.addWidget(self.table)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.btn_add = QPushButton("添加监控点")
        self.btn_add.clicked.connect(self.add_monitor_point)
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
        
        main_layout.addLayout(status_layout)
    
    def toggle_sound(self):
        self.alarm_sound_on = not self.alarm_sound_on
        self.btn_sound.setText("🔊 声音开启" if self.alarm_sound_on else "🔇 声音关闭")
    
    def set_ocr_status(self, status, is_ready=False):
        color = "#44ddaa" if is_ready else "#ddaa44"
        self.ocr_status_label.setStyleSheet(
            f"padding: 4px 12px; background-color: #2a2a3a; border-radius: 4px; color: {color};"
        )
        self.ocr_status_label.setText(f"OCR引擎: {status}")
    
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
            self.table.setItem(row, 4, QTableWidgetItem(f"({data['x1']},{data['y1']})-({data['x2']},{data['y2']})"))
            self.table.setItem(row, 5, QTableWidgetItem("待监控"))
            self.table.setItem(row, 6, QTableWidgetItem("--"))
            self.status_label.setText(f"状态: 已添加 [{data['name']}]")
    
    def edit_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        name = self.table.item(row, 0).text()
        lower = float(self.table.item(row, 2).text())
        upper = float(self.table.item(row, 3).text())
        coords = self.table.item(row, 4).text()
        # 解析坐标: "(x1,y1)-(x2,y2)"
        import re
        nums = re.findall(r'\d+', coords)
        if len(nums) >= 4:
            x1, y1, x2, y2 = map(int, nums[:4])
        else:
            x1, y1, x2, y2 = 100, 100, 250, 160
        
        dialog = AddMonitorDialog(self)
        dialog.name_edit.setText(name)
        dialog.x1_edit.setValue(x1)
        dialog.y1_edit.setValue(y1)
        dialog.x2_edit.setValue(x2)
        dialog.y2_edit.setValue(y2)
        dialog.lower_edit.setValue(lower)
        dialog.upper_edit.setValue(upper)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.table.setItem(row, 0, QTableWidgetItem(data['name']))
            self.table.setItem(row, 2, QTableWidgetItem(str(data['lower'])))
            self.table.setItem(row, 3, QTableWidgetItem(str(data['upper'])))
            self.table.setItem(row, 4, QTableWidgetItem(f"({data['x1']},{data['y1']})-({data['x2']},{data['y2']})"))
            self.status_label.setText(f"状态: 已编辑 [{data['name']}]")
    
    def delete_monitor_point(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一行")
            return
        name = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认删除", f"确定要删除 [{name}] 吗？")
        if reply == QMessageBox.Yes:
            self.table.removeRow(row)
            self.status_label.setText("状态: 已删除")
    
    def start_monitor(self):
        if self.monitoring:
            return
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先添加监控点")
            return
        
        monitors = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            lower = float(self.table.item(row, 2).text())
            upper = float(self.table.item(row, 3).text())
            coords = self.table.item(row, 4).text()
            import re
            nums = re.findall(r'\d+', coords)
            if len(nums) >= 4:
                x1, y1, x2, y2 = map(int, nums[:4])
            else:
                continue
            monitors.append({
                'name': name,
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
                'lower': lower, 'upper': upper,
                'row': row
            })
        
        self.monitor_thread = MonitorThread(monitors)
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
        for row in range(self.table.rowCount()):
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
        
        # 报警声音
        if self.alarm_sound_on:
            try:
                winsound.Beep(800, 300)
                winsound.Beep(1000, 300)
            except:
                pass
        
        # 记录到日志文件
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
            item = self.table.item(row, 5)
            if item and item.text() == "报警":
                status_item = QTableWidgetItem("正常")
                status_item.setBackground(QBrush(QColor(50, 150, 50)))
                status_item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(row, 5, status_item)
                self.table.setItem(row, 6, QTableWidgetItem("--"))
                count += 1
        self._update_alarm_count()
        if count > 0:
            self.status_label.setText(f"状态: 已消除 {count} 个报警")
        else:
            QMessageBox.information(self, "提示", "没有报警需要消除")
    
    def _update_alarm_count(self):
        count = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 5)
            if item and item.text() == "报警":
                count += 1
        self.alarm_count_label.setText(f"报警数: {count}")
    
    def _update_status_display(self):
        if self.monitoring:
            self.status_label.setText("状态: 监控运行中")
    
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
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("屏幕数字监控报警")
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
