import sys
import json
import os
import re
import threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QDoubleSpinBox, QSlider, QCheckBox, QProgressBar, QGroupBox, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, QByteArray, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPainterPath, QLinearGradient
)
from monitor import MonitorThread

class TrendChartWidget(QWidget):
    """数值趋势曲线"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.data = []
        self.max_points = 50 # 【修改点4】显示50个
        self.title = "数值趋势"
    
    def set_data(self, data_list, title="数值趋势"):
        self.data = data_list[-self.max_points:]
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.setBrush(QColor("#252538"))
        painter.drawRoundedRect(rect, 8, 8)
        
        # 简单绘制逻辑，保留之前隐藏数字的效果
        padding = 20
        chart_rect = QRect(padding, 32, rect.width()-padding*2, rect.height()-60)
        painter.setPen(QColor("#36364a"))
        for i in range(6):
            y = chart_rect.top() + chart_rect.height() * i / 5
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)
            
        if len(self.data) > 1:
            points = []
            min_val, max_val = min(self.data), max(self.data)
            r = (max_val - min_val) if max_val != min_val else 1
            for i, val in enumerate(self.data):
                x = chart_rect.left() + i * (chart_rect.width() / (len(self.data)-1))
                y = chart_rect.bottom() - ((val - min_val) / r) * chart_rect.height()
                points.append(QPoint(int(x), int(y)))
            
            painter.setPen(QPen(QColor("#4a9eff"), 2))
            for i in range(len(points)-1):
                painter.drawLine(points[i], points[i+1])

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("监控系统")
        self.resize(1000, 600)
        self.setStyleSheet("QMainWindow { background-color: #1e1e2e; } * { color: #e0e0f0; }")
        
        self.monitoring = False
        self.value_history = {}
        self.config_file = "monitor_config.json"
        
        self._setup_ui()
        self.load_config()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        self.ocr_label = QLabel("OCR: 等待启动...")
        layout.addWidget(self.ocr_label)
        
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "备注", "当前", "下限", "上限", "坐标", "状态", "时间", "静音"])
        layout.addWidget(self.table)
        
        self.trend = TrendChartWidget()
        layout.addWidget(self.trend)
        
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始")
        self.btn_start.clicked.connect(self.start_monitor)
        btn_layout.addWidget(self.btn_start)
        
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 60)
        self.interval_spin.setValue(0.5)
        btn_layout.addWidget(QLabel("间隔(秒):"))
        btn_layout.addWidget(self.interval_spin)
        
        layout.addLayout(btn_layout)
        
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)

    def start_monitor(self):
        # 收集监控点逻辑... (与原代码保持一致)
        monitors = []
        for row in range(self.table.rowCount()):
            # 简化收集逻辑
            name = self.table.item(row, 1).text()
            monitors.append({'row': row, 'name': name, 'lower': 0, 'upper': 100, 'x':0, 'y':0, 'width':100, 'height':100})
            
        self.monitor_thread = MonitorThread(monitors)
        self.monitor_thread.value_updated.connect(self.on_value_updated)
        self.monitor_thread.ocr_status.connect(lambda s, r: self.ocr_label.setText(s))
        self.monitor_thread.start()
        self.monitoring = True

    def on_value_updated(self, row, val):
        self.table.setItem(row, 3, QTableWidgetItem(f"{val:.2f}"))
        if row not in self.value_history: self.value_history[row] = []
        self.value_history[row].append(val)
        if self.table.currentRow() == row:
            self.trend.set_data(self.value_history[row])

    def on_alarm_triggered(self, row, name, value, lower, upper):
        # 【修改点2】已删除写入 alarm_log.txt 的代码
        self.status_label.setText(f"报警: {name} = {value}")

    def save_config(self):
        config = {'header_state': self.table.horizontalHeader().saveState().toBase64().data().decode(), 'monitors': []}
        # ... 保存逻辑
        with open(self.config_file, 'w') as f: json.dump(config, f)

    def load_config(self):
        # ... 加载逻辑
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
